r"""Extract project metadata and dependency specifiers from a pyproject.toml.

The metadata is the project name and version (and their normalized forms), the
description, readme, license, authors, URLs, ``requires-python``,
optional-dependency extras and dependency groups, and the build backend and
requirements of ``[build-system]``. The script also selects the
Python versions that ``requires-python`` allows, and lists the requirements of
``[project].dependencies`` and of the packages that it is asked to look up.

Usage:
    extract_metadata.py [--github-output FILE] [--fail-on-missing true|false]
        [--fail-on-dynamic-version true|false] [--step-summary true|false]
        [--strict true|false]
        [--python-candidates JSON] [--] <pyproject-path> <extra-values-json>
        [<dependencies-json>]

A name of ``<dependencies-json>`` may be followed by ``@project``, ``@extra:<name>`` or
``@group:<name>`` to look it up in ``[project].dependencies``, one extra or one dependency
group only (``numpy@extra:fast``); the key of the result is the entry as written.

Without ``--github-output``, prints a single JSON object to stdout (non-ASCII
characters are kept as they are, as in the action outputs):
    {"name": ..., "normalized_name": ..., "version": ..., "normalized_version": ...,
     "description": ..., "readme": ..., "license": ..., "license_files": [...],
     "authors": [...], "urls": {...},
     "keywords": [...], "classifiers": [...], "scripts": {...},
     "requires_python": ...,
     "extras": [...], "groups": [...],
     "build_backend": ..., "build_requires": [...],
     "python_versions": [...], "python_min": ..., "python_max": ...,
     "project_dependencies": {...}, "dependency_specifiers": {...},
     "dependency_requirements": {...},
     "warnings": [...], "schema_version": 1}

"warnings" lists human-readable messages about suspicious but non-fatal
input.

"schema_version" is the version of this JSON object: it increases when a key is
renamed, removed or changes type, not when a key is added, so that a tool that
reads the object can check it.

With ``--github-output FILE`` (used by action.yaml), appends the action
outputs to FILE (the format of ``$GITHUB_OUTPUT``, with a delimiter so that
values may contain line breaks). They are ``name``, ``normalized-name``,
``version``, ``normalized-version``, ``description``, ``readme``, ``license``,
``license-files``, ``authors``, ``urls``, ``keywords``, ``classifiers``, ``scripts``, ``requires-python``, ``extras``, ``groups``,
``build-backend``, ``build-requires``,
``python-versions``, ``python-min``, ``python-max``, ``python-matrix``,
``project-dependencies``, ``dependency-specifiers`` and
``dependency-requirements``. It also prints to stdout one
``::warning file=<path>::`` workflow command per warning, where ``<path>`` is
the pyproject path, so that GitHub attaches the annotation to the file,
followed by a one-line summary of the outputs. Warnings are printed on stdout
because GitHub only parses workflow commands there.

With ``--step-summary true``, also appends a Markdown table of the outputs
and the list of warnings to the file named by the ``GITHUB_STEP_SUMMARY``
environment variable (the job summary of GitHub), whichever the other options.
When the run fails, the error message is appended instead (unless
``--step-summary`` or ``GITHUB_STEP_SUMMARY`` is itself the problem).

With ``--strict true``, any warning is an error instead: the outputs are not
written and the message lists the warnings.

With ``--fail-on-missing true``, a requested dependency that is not found
is an error instead of a ``null`` specifier.

With ``--fail-on-dynamic-version true``, a ``version`` that is listed in
``[project].dynamic`` (so that the version output would be empty) is an error
instead of a warning.

``python_versions`` lists the ``--python-candidates`` (a JSON array of
"major.minor" strings) that ``[project].requires-python`` allows, and
``python_min`` is the lowest of them and ``python_max`` the highest (each an
empty string if there is none).
The ``python-matrix`` output (not in the JSON) is
``{"python-version": python_versions}``, an object that ``fromJSON`` can give
to ``strategy.matrix`` as it is.

Exits non-zero with a message on stderr (with ``--github-output FILE``, an
``::error file=<path>::`` workflow command, so that GitHub shows an error
annotation on the file) if the file is missing, cannot be read, is not UTF-8 or
is not valid TOML, the outputs or the job summary cannot be written, [project]
is missing the required "name"/"version" keys, a dependency table
([project].dependencies, [project.optional-dependencies] or
[dependency-groups]) has the wrong type, [build-system] has a ``build-backend``
that is not a string or ``requires`` that is not an array of strings, an input is not valid JSON of the
expected shape, a Python candidate is not a "major.minor" string,
``--fail-on-dynamic-version true`` is given and the version is dynamic,
``--strict true`` is given and there is a warning, a requested dependency has a scope that
is not ``project``, ``extra:<name>`` or ``group:<name>``, or ``--fail-on-missing true``
is given and a requested dependency is not found.

A wrong command line (which the action never builds) prints the usage and the
problem on stderr and exits with the code 2, as ``argparse`` does; with
``--github-output FILE`` it is one ``::error::`` workflow command instead.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import tomllib
from pathlib import Path
from typing import Any, NoReturn

from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from extract_pyproject_metadata.checks import check_array, check_str, check_string_array, get_table
from extract_pyproject_metadata.dependencies.lookup import (
    check_no_missing_dependency,
    parse_dependencies,
    requirements_from_index,
    specifiers_from_index,
)
from extract_pyproject_metadata.dependencies.requirements import (
    dynamic_dependency_fields,
    extract_project_dependencies,
    index_dependencies,
)
from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.inputs import Options, parse_options, parse_string_array
from extract_pyproject_metadata.output.escaping import (
    escape_annotation,
)
from extract_pyproject_metadata.output.github import (
    emit_github_output,
    format_error,
    format_outputs,
)
from extract_pyproject_metadata.output.summary import (
    format_error_summary,
    format_step_summary,
    resolve_step_summary,
    write_step_summary,
)
from extract_pyproject_metadata.python_versions import (
    DEFAULT_PYTHON_CANDIDATES,
    compatible_python_versions,
    highest_python_version,
    lowest_python_version,
    parse_python_candidates,
)
from extract_pyproject_metadata.types import Metadata, Report

try:
    from packaging.licenses import InvalidLicenseExpression, canonicalize_license_expression
except ImportError:  # packaging before 24.2 cannot validate license expressions
    # Only the None checks of ``_license_warnings`` use these names without the import.
    InvalidLicenseExpression = None  # type: ignore[assignment,misc]
    canonicalize_license_expression = None  # type: ignore[assignment]

# The UTF-8 byte order mark that some editors write at the start of a file.
UTF8_BOM = b"\xef\xbb\xbf"


# The version of the JSON printed to stdout (the ``schema_version`` key of the report).
SCHEMA_VERSION = 1


# A project name per PEP 508: letters, digits, "-", "_" and "." that start and end with a
# letter or a digit. Always used with ``fullmatch``.
_VALID_NAME = re.compile(r"[A-Z0-9]|[A-Z0-9][A-Z0-9._-]*[A-Z0-9]", re.IGNORECASE)


def load_pyproject(pyproject_path: str) -> dict[str, Any]:
    """Read and parse a pyproject.toml file.

    Args:
        pyproject_path: Path to the pyproject.toml file.

    Returns:
        The parsed TOML document. A UTF-8 byte order mark at the start of the
        file is ignored.

    Raises:
        MetadataError: If the file is missing, cannot be read (for example for
            lack of permission), is not UTF-8, is not valid TOML or has arrays or inline
            tables nested too deeply for the parser.
    """
    path = Path(pyproject_path)
    if not path.is_file():
        msg = f"pyproject.toml not found at: {pyproject_path}"
        raise MetadataError(msg)
    try:
        with path.open("rb") as f:
            content = f.read()
        # Some editors (on Windows) start a UTF-8 file with a byte order mark, which TOML rejects.
        return tomllib.loads(content.removeprefix(UTF8_BOM).decode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        msg = f"{pyproject_path} is not valid TOML: {exc}"
        raise MetadataError(msg) from exc
    except UnicodeDecodeError as exc:
        msg = f"{pyproject_path} is not valid UTF-8: {exc}"
        raise MetadataError(msg) from exc
    except RecursionError as exc:  # tomllib recurses on nested arrays and inline tables
        msg = f"{pyproject_path} is nested too deeply to be parsed"
        raise MetadataError(msg) from exc
    except OSError as exc:
        msg = f"{pyproject_path} cannot be read: {exc}"
        raise MetadataError(msg) from exc


def extract_metadata(
    data: dict[str, Any],
    extra_values: list[str],
    pyproject_path: str = "pyproject.toml",
    fail_on_dynamic_version: bool = False,
) -> tuple[Metadata, list[str]]:
    """Read name, version, and sorted extras from a parsed pyproject.toml.

    Args:
        data: The parsed pyproject.toml, as returned by ``load_pyproject``.
        extra_values: Extra values to prepend to the extras read from
            ``[project.optional-dependencies]``, as returned by
            ``parse_string_array``.
        pyproject_path: Path of the file ``data`` was read from, used only in
            error and warning messages.
        fail_on_dynamic_version: Whether a ``version`` listed in
            ``[project].dynamic`` is an error instead of a warning.

    Returns:
        A tuple ``(metadata, warnings)``. ``warnings`` lists the warning
        messages (for example when the version is dynamic, or when a field is
        both set and listed in ``dynamic``). ``metadata`` is a
        ``Metadata`` dict with keys ``name``, ``normalized_name`` (the name per PEP 503),
        ``version``, ``normalized_version``, ``description``, ``readme``, ``license``, ``license_files``, ``authors``, ``urls``, ``keywords``, ``classifiers``, ``scripts``, ``requires_python``, ``extras``, ``groups``, ``build_backend`` and ``build_requires``. ``version`` is
        an empty string when ``[project].version`` is declared in
        ``[project].dynamic`` and has no static value (so is ``normalized_version``,
        the version in the canonical form of PEP 440, such as ``1.0rc1`` for ``1.0-RC1``). ``requires_python``
        is ``[project].requires-python`` as written, or an empty string if it is
        not declared. ``description`` is ``[project].description`` as written,
        or an empty string if it is not declared. ``readme`` is the path of the readme
        file (a string ``[project].readme``, or the ``file`` of a table), or an empty
        string if there is none or the readme is inline (``text``). ``license`` is the
        SPDX expression of ``[project].license`` (a warning if it is not a valid one, when
        ``packaging`` can check it) or the ``text`` of its table, or an empty
        string if there is none or the license is a ``file``. ``license_files`` is the array of
        ``[project].license-files`` (the patterns as written), empty if there is none. ``authors`` is the list of
        the authors of ``[project].authors`` (``name`` and ``email`` only), empty if
        there is none. ``urls`` maps the labels of ``[project.urls]`` to their URLs, in
        the order of the file, and is empty if there is none. ``keywords`` and
        ``classifiers`` are the arrays of ``[project].keywords`` and
        ``[project].classifiers`` as written (empty if there is none), and ``scripts`` maps
        the names of ``[project.scripts]`` to their entry points, like ``urls``. ``extras`` lists the ``extra_values`` first, then the
        extras sorted by normalized name. Names are compared per PEP 685 (like
        package names), so spellings of the same extra are duplicates: the
        first one is kept. ``groups`` lists the names of ``[dependency-groups]``
        the same way (sorted by normalized name, without duplicates), and is
        empty if there is no such table. ``build_backend`` is ``[build-system].build-backend``
        (empty if there is none) and ``build_requires`` is ``[build-system].requires``
        as written (empty if there is none).

    Raises:
        MetadataError: If ``[project]`` is not a table, is missing ``name`` (also
            when ``name`` is listed in ``dynamic``, which PEP 621 forbids) or
            ``version`` (unless the version is dynamic), has a ``dynamic`` that
            is not an array of strings, a ``name`` that is not a non-empty string or not a
            valid PEP 508 name, a
            ``version`` that is not a string or not a valid PEP 440 version, a
            ``description`` or ``requires-python`` that is not a string, a ``readme`` that
            is neither a string nor a table with a string ``file``, a ``license`` that
            is neither a string nor a table with a string ``text`` and ``file``, a
            ``license-files`` that is not an array of strings, an
            ``authors`` that is not an array of tables with string ``name`` and ``email``, a ``urls`` or ``scripts`` that is not a table of strings, a
            ``keywords`` or ``classifiers`` that is not an array of strings, an
            ``optional-dependencies``, ``dependency-groups`` or ``build-system`` that is not a
            table, a ``build-backend`` that is not a string, a ``requires`` that is not an
            array of strings, or a dynamic version when ``fail_on_dynamic_version`` is true.
    """
    project = get_table(data, "project", "[project]", pyproject_path)
    dynamic = check_string_array(project.get("dynamic", []), "[project].dynamic", pyproject_path)
    raw_name = _required_name(project, dynamic, pyproject_path)
    warnings = _static_and_dynamic_warnings(project, dynamic, pyproject_path)
    raw_version, version_warnings = _required_version(
        project, dynamic, pyproject_path, fail_on_dynamic_version
    )
    warnings.extend(version_warnings)
    name = _valid_name(raw_name, pyproject_path)
    version, normalized_version = _valid_version(raw_version, "version" in project, pyproject_path)

    description = check_str(project.get("description", ""), "[project].description", pyproject_path)

    readme = _readme_path(project.get("readme", ""), pyproject_path)
    license_ = _license_text(project.get("license", ""), pyproject_path)
    warnings.extend(_license_warnings(project.get("license", ""), pyproject_path))
    authors = _authors(project.get("authors", []), pyproject_path)
    urls = _urls(project, pyproject_path)
    scripts = _string_table(project, "scripts", pyproject_path)
    keywords = check_string_array(project.get("keywords", []), "[project].keywords", pyproject_path)
    classifiers = check_string_array(
        project.get("classifiers", []), "[project].classifiers", pyproject_path
    )

    requires_python = check_str(
        project.get("requires-python", ""), "[project].requires-python", pyproject_path
    )
    build_backend, build_requires = _build_system(data, pyproject_path)
    metadata = Metadata(
        name=name,
        normalized_name=canonicalize_name(name),
        version=version,
        normalized_version=normalized_version,
        description=description,
        readme=readme,
        license=license_,
        license_files=check_string_array(
            project.get("license-files", []), "[project].license-files", pyproject_path
        ),
        authors=authors,
        urls=urls,
        keywords=keywords,
        classifiers=classifiers,
        scripts=scripts,
        requires_python=requires_python,
        extras=_extra_names(project, extra_values, pyproject_path),
        groups=_group_names(data, pyproject_path),
        build_backend=build_backend,
        build_requires=build_requires,
    )
    return metadata, warnings


def _required_name(project: dict[str, Any], dynamic: list[str], pyproject_path: str) -> object:
    """Return ``[project].name`` as written, which must be set.

    Args:
        project: The ``[project]`` table.
        dynamic: The ``[project].dynamic`` array.
        pyproject_path: Path of the file, used in the error messages.

    Returns:
        The value of ``name``, whatever its type (see ``_valid_name``).

    Raises:
        MetadataError: If ``name`` is not set, with a message that says so when
            it is listed in ``dynamic`` (PEP 621 requires a static name).
    """
    try:
        return project["name"]
    except KeyError as exc:
        if "name" in dynamic:
            # PEP 621: the name cannot be dynamic, so the build backend cannot supply it.
            msg = (
                f"{pyproject_path}: [project].name is listed in [project].dynamic, but "
                "PEP 621 requires a static name"
            )
            raise MetadataError(msg) from exc
        msg = f"{pyproject_path} is missing required key [project].{exc.args[0]}"
        raise MetadataError(msg) from exc


def _static_and_dynamic_warnings(
    project: dict[str, Any], dynamic: list[str], pyproject_path: str
) -> list[str]:
    """Describe the fields that are set in ``[project]`` and also listed in ``dynamic``.

    PEP 621 forbids it. The static value is the one that is read.

    Args:
        project: The ``[project]`` table.
        dynamic: The ``[project].dynamic`` array.
        pyproject_path: Path of the file, used in the messages.

    Returns:
        One warning per such field, in the order of ``dynamic``, without duplicates.
    """
    return [
        f"{pyproject_path}: [project].{field} is set and also listed in [project].dynamic, "
        "which PEP 621 forbids; the static value is used"
        for field in dict.fromkeys(dynamic)
        if field in project
    ]


def _required_version(
    project: dict[str, Any],
    dynamic: list[str],
    pyproject_path: str,
    fail_on_dynamic_version: bool,
) -> tuple[object, list[str]]:
    """Return ``[project].version`` as written, or an empty string if it is dynamic.

    Args:
        project: The ``[project]`` table.
        dynamic: The ``[project].dynamic`` array.
        pyproject_path: Path of the file, used in the messages.
        fail_on_dynamic_version: Whether a dynamic version is an error instead
            of a warning.

    Returns:
        A tuple ``(version, warnings)``. ``version`` is the value of ``version``
        whatever its type (see ``_valid_version``), or ``""`` when the build
        backend computes it. ``warnings`` has one message in that case.

    Raises:
        MetadataError: If ``version`` is neither set nor dynamic, or is dynamic
            and ``fail_on_dynamic_version`` is true.
    """
    if "version" in project:
        return project["version"], []
    if "version" not in dynamic:
        msg = f"{pyproject_path} is missing required key [project].version"
        raise MetadataError(msg)
    # The build backend computes the version (setuptools-scm, hatch-vcs, ...).
    if fail_on_dynamic_version:
        msg = (
            f"{pyproject_path}: [project].version is dynamic, so it cannot be read "
            "(fail-on-dynamic-version is 'true')"
        )
        raise MetadataError(msg)
    return "", [f"{pyproject_path}: [project].version is dynamic, the version output is empty"]


def _valid_name(name: object, pyproject_path: str) -> str:
    """Return ``name`` if it is a valid project name (PEP 508).

    Args:
        name: The value of ``[project].name``.
        pyproject_path: Path of the file, used in the error messages.

    Returns:
        ``name``, unchanged.

    Raises:
        MetadataError: If ``name`` is not a non-empty string, or contains
            other characters than letters, digits, ``-``, ``_`` and ``.``, or
            does not start and end with a letter or a digit.
    """
    if not isinstance(name, str) or not name:
        msg = f"{pyproject_path}: [project].name must be a non-empty string, got: {name!r}"
        raise MetadataError(msg)
    if not _VALID_NAME.fullmatch(name):
        msg = (
            f"{pyproject_path}: [project].name is not a valid project name (letters, digits, "
            f"'-', '_' and '.', starting and ending with a letter or a digit): {name!r}"
        )
        raise MetadataError(msg)
    return name


def _valid_version(version: object, is_static: bool, pyproject_path: str) -> tuple[str, str]:
    """Return the version and its canonical form (PEP 440).

    Args:
        version: The value of ``[project].version``, or ``""`` if it is dynamic.
        is_static: Whether ``version`` is set in ``[project]`` (it is not
            when it is dynamic).
        pyproject_path: Path of the file, used in the error messages.

    Returns:
        A tuple ``(version, normalized_version)``. ``normalized_version`` is an
        empty string when the version is not static.

    Raises:
        MetadataError: If ``version`` is not a string, or a static version is
            not a valid PEP 440 version.
    """
    version = check_str(version, "[project].version", pyproject_path)
    if not is_static:
        return version, ""
    try:
        return version, str(Version(version))
    except InvalidVersion as exc:
        msg = f"{pyproject_path}: [project].version is not a valid PEP 440 version: {version!r}"
        raise MetadataError(msg) from exc


def _extra_names(
    project: dict[str, Any], extra_values: list[str], pyproject_path: str
) -> list[str]:
    """Return the extra names: ``extra_values`` first, then the sorted extras.

    Extra names are normalized like package names (PEP 685), so "Foo_Bar" and
    "foo-bar" are one extra. The first spelling of each is kept, at the
    position of its first occurrence.

    Args:
        project: The ``[project]`` table.
        extra_values: The values to put first, as returned by ``parse_string_array``.
        pyproject_path: Path of the file, used in the error message.

    Returns:
        The names, without duplicates.

    Raises:
        MetadataError: If ``[project.optional-dependencies]`` is not a table.
    """
    optional_dependencies = get_table(
        project, "optional-dependencies", "[project].optional-dependencies", pyproject_path
    )
    extras = sorted(optional_dependencies, key=canonicalize_name)
    unique_extras: dict[str, str] = {}
    for extra in extra_values + extras:
        unique_extras.setdefault(canonicalize_name(extra), extra)
    return list(unique_extras.values())


def _build_system(data: dict[str, Any], pyproject_path: str) -> tuple[str, list[str]]:
    """Return the build backend and the build requirements of ``[build-system]``.

    Args:
        data: The parsed pyproject.toml.
        pyproject_path: Path of the file, used in the error messages.

    Returns:
        A tuple ``(build_backend, build_requires)``: ``build-backend`` as written
        (an empty string if there is none) and the ``requires`` array as written
        (empty if there is none). Both are empty if there is no ``[build-system]``.

    Raises:
        MetadataError: If ``[build-system]`` is not a table, ``build-backend`` is
            not a string or ``requires`` is not an array of strings.
    """
    table = get_table(data, "build-system", "[build-system]", pyproject_path)
    build_backend = check_str(
        table.get("build-backend", ""), "[build-system].build-backend", pyproject_path
    )
    requires = check_string_array(table.get("requires", []), "[build-system].requires", pyproject_path)
    return build_backend, list(requires)


def _group_names(data: dict[str, Any], pyproject_path: str) -> list[str]:
    """Return the names of ``[dependency-groups]``, sorted by normalized name.

    Group names are normalized per PEP 503 (PEP 735): the first spelling is kept.

    Args:
        data: The parsed pyproject.toml.
        pyproject_path: Path of the file, used in the error message.

    Returns:
        The names, without duplicates; empty if there is no such table.

    Raises:
        MetadataError: If ``[dependency-groups]`` is not a table.
    """
    dependency_groups = get_table(data, "dependency-groups", "[dependency-groups]", pyproject_path)
    unique_groups: dict[str, str] = {}
    for group in sorted(dependency_groups, key=canonicalize_name):
        unique_groups.setdefault(canonicalize_name(group), group)
    return list(unique_groups.values())


def _readme_path(readme: object, pyproject_path: str) -> str:
    """Return the path of the readme file declared by ``[project].readme``.

    Args:
        readme: The value of ``[project].readme``: a path (string), or a table
            with a ``file`` (path) or a ``text`` (the readme itself) and a
            ``content-type``.
        pyproject_path: Path of the file, used in the error message.

    Returns:
        The path as written, or an empty string if ``readme`` is empty, is not
        declared, or is a table without ``file`` (inline ``text``).

    Raises:
        MetadataError: If ``readme`` is neither a string nor a table, or its
            ``file`` is not a string.
    """
    if isinstance(readme, str):
        return readme
    if not isinstance(readme, dict):
        msg = f"{pyproject_path}: [project].readme must be a string or a table, got: {readme!r}"
        raise MetadataError(msg)
    return check_str(readme.get("file", ""), "[project].readme.file", pyproject_path)


def _license_text(license_: object, pyproject_path: str) -> str:
    """Return the license declared by ``[project].license``.

    Args:
        license_: The value of ``[project].license``: an SPDX license expression
            (a string, PEP 639), or the table of PEP 621 with a ``text`` (the
            name or the text of the license) or a ``file`` (path).
        pyproject_path: Path of the file, used in the error message.

    Returns:
        The expression or the ``text`` as written, or an empty string if
        ``license_`` is empty, is not declared, or is a table without ``text``
        (a ``file``).

    Raises:
        MetadataError: If ``license_`` is neither a string nor a table, or its
            ``text`` or ``file`` is not a string.
    """
    if isinstance(license_, str):
        return license_
    if not isinstance(license_, dict):
        msg = f"{pyproject_path}: [project].license must be a string or a table, got: {license_!r}"
        raise MetadataError(msg)
    file = check_str(license_.get("text", ""), "[project].license.text", pyproject_path)
    check_str(license_.get("file", ""), "[project].license.file", pyproject_path)
    return file


def _license_warnings(license_: object, pyproject_path: str) -> list[str]:
    """Describe a ``[project].license`` that is not a valid SPDX license expression.

    Only an expression (a string, PEP 639) is checked: not the table of PEP 621, and not an
    empty string. The check needs ``packaging`` 24.2 or later; with an older one, nothing is
    checked.

    Args:
        license_: The value of ``[project].license``.
        pyproject_path: Path of the file, used in the message.

    Returns:
        One warning if ``license_`` is a string that is not a valid expression, none otherwise.
    """
    if canonicalize_license_expression is None or not isinstance(license_, str) or not license_:
        return []
    try:
        canonicalize_license_expression(license_)
    except InvalidLicenseExpression as exc:
        return [
            f"{pyproject_path}: [project].license is not a valid SPDX license expression "
            f"(PEP 639): {exc}"
        ]
    return []


def _authors(authors: object, pyproject_path: str) -> list[dict[str, str]]:
    """Return the authors declared by ``[project].authors``.

    Args:
        authors: The value of ``[project].authors``: an array of tables with an
            optional ``name`` and an optional ``email`` (strings).
        pyproject_path: Path of the file, used in the error messages.

    Returns:
        One dict per author, in order, with the ``name`` and ``email`` that the
        author has (in this order). Other keys are ignored.

    Raises:
        MetadataError: If ``authors`` is not an array, an author is not a
            table, or a ``name`` or an ``email`` is not a string.
    """
    result: list[dict[str, str]] = []
    for index, author in enumerate(check_array(authors, "[project].authors", pyproject_path)):
        label = f"[project].authors[{index}]"
        if not isinstance(author, dict):
            msg = f"{pyproject_path}: {label} must be a table, got: {author!r}"
            raise MetadataError(msg)
        entry: dict[str, str] = {}
        for key in ("name", "email"):
            if key not in author:
                continue
            entry[key] = check_str(author[key], f"{label}.{key}", pyproject_path)
        result.append(entry)
    return result


def _urls(project: dict[str, Any], pyproject_path: str) -> dict[str, str]:
    """Return the project URLs of ``[project.urls]``.

    Args:
        project: The ``[project]`` table.
        pyproject_path: Path of the file, used in the error messages.

    Returns:
        The label of each URL and the URL, as written and in the order of the
        file. Empty if there is no ``[project.urls]``.

    Raises:
        MetadataError: If ``[project.urls]`` is not a table or a URL is not a
            string.
    """
    return _string_table(project, "urls", pyproject_path)


def _string_table(project: dict[str, Any], key: str, pyproject_path: str) -> dict[str, str]:
    """Return a table of ``[project]`` whose values are strings, such as ``[project.urls]``.

    Args:
        project: The ``[project]`` table.
        key: The key of the table, such as ``"scripts"``.
        pyproject_path: Path of the file, used in the error messages.

    Returns:
        The keys and the values as written, in the order of the file. Empty if
        there is no such table.

    Raises:
        MetadataError: If the table is not a table or a value is not a string.
    """
    table = get_table(project, key, f"[project.{key}]", pyproject_path)
    for name, value in table.items():
        check_str(value, f"[project.{key}].{name}", pyproject_path)
    return dict(table)


class _ArgumentParser(argparse.ArgumentParser):
    """An argument parser whose usage errors can be GitHub error annotations.

    Attributes:
        annotate: Whether ``error`` prints a ``::error::`` workflow command (so that GitHub shows
            an error annotation) instead of the usage and the message.
    """

    annotate = False

    def error(self, message: str) -> NoReturn:
        """Print the usage error on stderr and exit with the code 2, like ``argparse``.

        Args:
            message: What is wrong with the command line.
        """
        text = f"{self.format_usage().rstrip()}\n{self.prog}: error: {message}"
        if self.annotate:
            text = f"::error::{escape_annotation(text)}"
        print(text, file=sys.stderr)
        self.exit(2)


def _build_parser(prog: str) -> _ArgumentParser:
    """Build the command line parser."""
    # ``__doc__`` is None when Python runs with -OO, which strips docstrings.
    description = (__doc__ or "").split("\n", 1)[0]
    parser = _ArgumentParser(prog=prog, description=description)
    parser.add_argument(
        "--github-output",
        metavar="FILE",
        help="append the action outputs to FILE and print workflow commands instead of JSON",
    )
    parser.add_argument(
        "--fail-on-missing",
        metavar="BOOL",
        default="false",
        help="'true' to fail when a requested dependency is not found (default: false)",
    )
    parser.add_argument(
        "--fail-on-dynamic-version",
        metavar="BOOL",
        default="false",
        help="'true' to fail when the version is dynamic, instead of a warning (default: false)",
    )
    parser.add_argument(
        "--strict",
        metavar="BOOL",
        default="false",
        help="'true' to fail when there is a warning (default: false)",
    )
    parser.add_argument(
        "--step-summary",
        metavar="BOOL",
        default="false",
        help="'true' to also write the outputs to the job summary, GITHUB_STEP_SUMMARY (default: false)",
    )
    parser.add_argument(
        "--python-candidates",
        metavar="JSON",
        default=DEFAULT_PYTHON_CANDIDATES,
        help=(
            "JSON array of 'major.minor' Python versions to select from, using requires-python "
            f"(default: {DEFAULT_PYTHON_CANDIDATES})"
        ),
    )
    parser.add_argument("pyproject_path", help="path to pyproject.toml")
    parser.add_argument("extra_values", help="JSON array of extra values to prepend")
    parser.add_argument(
        "dependencies", nargs="?", default="[]", help="JSON array of package names to look up"
    )
    return parser


def build_report(args: argparse.Namespace, options: Options | None = None) -> Report:
    """Read the pyproject.toml and the inputs of the command line, and build the report.

    Args:
        args: The parsed command line, as returned by ``_build_parser``.
        options: The parsed boolean inputs. Parsed from ``args`` when omitted.

    Returns:
        The report: the metadata, the Python versions, the dependency
        specifiers and the warnings (without duplicates).

    Raises:
        MetadataError: If an input or the pyproject.toml is invalid, the version
            is dynamic with ``--fail-on-dynamic-version true``, a dependency
            is not found with ``--fail-on-missing true``, or there is a
            warning with ``--strict true``.
    """
    if options is None:
        options = parse_options(args)
    data = load_pyproject(args.pyproject_path)
    extra_values = parse_string_array(args.extra_values, "extra-values")
    dependencies = parse_dependencies(args.dependencies)
    python_candidates = parse_python_candidates(args.python_candidates)
    metadata, warnings = extract_metadata(
        data, extra_values, args.pyproject_path, options.fail_on_dynamic_version
    )
    # Computed in the order of their warnings in the report: the metadata, the Python versions,
    # the dependencies of the project, then the lookups of the requested dependencies.
    python_versions, python_warnings = compatible_python_versions(
        metadata["requires_python"], python_candidates, args.pyproject_path
    )
    project_dependencies, project_warnings = extract_project_dependencies(
        data, args.pyproject_path
    )
    # The requirements of the file are read and parsed once, for both lookups.
    found, index_warnings = index_dependencies(data, args.pyproject_path)
    specifiers, specifier_warnings = specifiers_from_index(
        found, index_warnings, dependencies, args.pyproject_path
    )
    requirements = requirements_from_index(found, dependencies)
    warnings.extend(python_warnings)
    warnings.extend(project_warnings)
    warnings.extend(specifier_warnings)
    if options.fail_on_missing:
        check_no_missing_dependency(
            specifiers, args.pyproject_path, dynamic_dependency_fields(data)
        )
    warnings = list(dict.fromkeys(warnings))
    if options.strict and warnings:
        listed = "".join(f"\n- {warning}" for warning in warnings)
        msg = f"strict is 'true' and there are {len(warnings)} warning(s):{listed}"
        raise MetadataError(msg)
    return Report(
        **metadata,
        python_versions=python_versions,
        python_min=lowest_python_version(python_versions),
        python_max=highest_python_version(python_versions),
        project_dependencies=project_dependencies,
        dependency_specifiers=specifiers,
        dependency_requirements=requirements,
        warnings=warnings,
        schema_version=SCHEMA_VERSION,
    )


def main(argv: list[str]) -> int:
    """Run the command line interface and return the process exit code."""
    parser = _build_parser(Path(argv[0]).name)
    # The arguments are not parsed yet when one is wrong: look for the option as it is written.
    parser.annotate = any(arg.split("=", 1)[0] == "--github-output" for arg in argv[1:])
    try:
        args = parser.parse_args(argv[1:])
    except SystemExit as exc:  # argparse exits on bad arguments and on --help
        return exc.code if isinstance(exc.code, int) else 2

    summary_path: str | None = None
    try:
        options = parse_options(args)
        summary_path = resolve_step_summary(options.step_summary, os.environ)
        report = build_report(args, options)
        if args.github_output is None:
            # Like the action outputs, keep non-ASCII characters as they are.
            print(json.dumps(report, ensure_ascii=False))
        else:
            emit_github_output(report, args.pyproject_path, args.github_output)
        if summary_path is not None:
            write_step_summary(summary_path, format_step_summary(report, format_outputs(report)))
    except MetadataError as exc:
        annotate = args.github_output is not None
        print(format_error(str(exc), args.pyproject_path, annotate), file=sys.stderr)
        if summary_path is not None:
            # The error is already reported: a summary that cannot be written is not worth another.
            with contextlib.suppress(MetadataError):
                write_step_summary(summary_path, format_error_summary(str(exc)))
        return 1
    return 0

