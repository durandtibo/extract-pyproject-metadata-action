r"""Extract project metadata and dependency specifiers from a pyproject.toml.

The metadata is the project name and version (and their normalized forms), the
description, readme, license, authors, URLs, ``requires-python``,
optional-dependency extras and dependency groups. The script also selects the
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
[dependency-groups]) has the wrong type, an input is not valid JSON of the
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
import functools
import json
import os
import re
import sys
import string
import tomllib
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple, NoReturn, TypedDict

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

# The version of the JSON printed to stdout (the ``schema_version`` key of the report).
SCHEMA_VERSION = 1

# The Python versions that ``python-candidates`` defaults to (and the default of the input).
DEFAULT_PYTHON_CANDIDATES = '["3.11","3.12","3.13","3.14","3.15"]'

# A "major.minor" Python version, such as "3.12". Always used with ``fullmatch``: ``$`` would
# also match before a trailing line break.
_MINOR_VERSION = re.compile(r"[0-9]+\.[0-9]+")

# The patch numbers that ``compatible_python_versions`` tries for each "major.minor" candidate: every
# real release (CPython patch numbers stay below 100) and a very late one, for the specifiers that
# have no upper bound.
_PATCH_RELEASES = (*range(100), 9999)

# The scope of the requirements of ``[project].dependencies`` (see ``_scoped_requirements``).
_PROJECT_SCOPE = "project"

# A project name per PEP 508: letters, digits, "-", "_" and "." that start and end with a
# letter or a digit. Always used with ``fullmatch``.
_VALID_NAME = re.compile(r"[A-Z0-9]|[A-Z0-9][A-Z0-9._-]*[A-Z0-9]", re.IGNORECASE)


class MetadataError(Exception):
    """Raised when pyproject.toml cannot be read or is missing required metadata."""


class Metadata(TypedDict):
    """The project metadata read by ``extract_metadata``."""

    name: str
    normalized_name: str
    version: str
    normalized_version: str
    description: str
    readme: str
    license: str
    license_files: list[str]
    authors: list[dict[str, str]]
    urls: dict[str, str]
    keywords: list[str]
    classifiers: list[str]
    scripts: dict[str, str]
    requires_python: str
    extras: list[str]
    groups: list[str]


class Report(Metadata):
    """The metadata, Python versions, lowest Python version, dependency specifiers and warnings built by ``build_report``."""

    python_versions: list[str]
    python_min: str
    python_max: str
    project_dependencies: dict[str, str]
    dependency_specifiers: dict[str, str | None]
    dependency_requirements: dict[str, list[dict[str, str]]]
    warnings: list[str]
    schema_version: int


class Options(NamedTuple):
    """The boolean inputs of the action, parsed."""

    fail_on_missing: bool
    fail_on_dynamic_version: bool
    strict: bool
    step_summary: bool


def load_pyproject(pyproject_path: str) -> dict[str, Any]:
    """Read and parse a pyproject.toml file.

    Args:
        pyproject_path: Path to the pyproject.toml file.

    Returns:
        The parsed TOML document.

    Raises:
        MetadataError: If the file is missing, cannot be read (for example for
            lack of permission), is not UTF-8 or is not valid TOML.
    """
    path = Path(pyproject_path)
    if not path.is_file():
        msg = f"pyproject.toml not found at: {pyproject_path}"
        raise MetadataError(msg)
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        msg = f"{pyproject_path} is not valid TOML: {exc}"
        raise MetadataError(msg) from exc
    except UnicodeDecodeError as exc:
        msg = f"{pyproject_path} is not valid UTF-8: {exc}"
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
        ``version``, ``normalized_version``, ``description``, ``readme``, ``license``, ``license_files``, ``authors``, ``urls``, ``keywords``, ``classifiers``, ``scripts``, ``requires_python``, ``extras`` and ``groups``. ``version`` is
        an empty string when ``[project].version`` is declared in
        ``[project].dynamic`` and has no static value (so is ``normalized_version``,
        the version in the canonical form of PEP 440, such as ``1.0rc1`` for ``1.0-RC1``). ``requires_python``
        is ``[project].requires-python`` as written, or an empty string if it is
        not declared. ``description`` is ``[project].description`` as written,
        or an empty string if it is not declared. ``readme`` is the path of the readme
        file (a string ``[project].readme``, or the ``file`` of a table), or an empty
        string if there is none or the readme is inline (``text``). ``license`` is the
        SPDX expression of ``[project].license`` or the ``text`` of its table, or an empty
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
        empty if there is no such table.

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
            ``optional-dependencies`` or ``dependency-groups`` that is not a
            table, or a dynamic version when ``fail_on_dynamic_version`` is true.
    """
    project = _get_table(data, "project", "[project]", pyproject_path)
    dynamic = _check_string_array(project.get("dynamic", []), "[project].dynamic", pyproject_path)
    raw_name = _required_name(project, dynamic, pyproject_path)
    warnings = _static_and_dynamic_warnings(project, dynamic, pyproject_path)
    raw_version, version_warnings = _required_version(
        project, dynamic, pyproject_path, fail_on_dynamic_version
    )
    warnings.extend(version_warnings)
    name = _valid_name(raw_name, pyproject_path)
    version, normalized_version = _valid_version(raw_version, "version" in project, pyproject_path)

    description = _check_str(project.get("description", ""), "[project].description", pyproject_path)

    readme = _readme_path(project.get("readme", ""), pyproject_path)
    license_ = _license_text(project.get("license", ""), pyproject_path)
    authors = _authors(project.get("authors", []), pyproject_path)
    urls = _urls(project, pyproject_path)
    scripts = _string_table(project, "scripts", pyproject_path)
    keywords = _check_string_array(project.get("keywords", []), "[project].keywords", pyproject_path)
    classifiers = _check_string_array(
        project.get("classifiers", []), "[project].classifiers", pyproject_path
    )

    requires_python = _check_str(
        project.get("requires-python", ""), "[project].requires-python", pyproject_path
    )
    metadata = Metadata(
        name=name,
        normalized_name=canonicalize_name(name),
        version=version,
        normalized_version=normalized_version,
        description=description,
        readme=readme,
        license=license_,
        license_files=_check_string_array(
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
    _check_str(version, "[project].version", pyproject_path)
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
    optional_dependencies = _get_table(
        project, "optional-dependencies", "[project].optional-dependencies", pyproject_path
    )
    extras = sorted(optional_dependencies, key=canonicalize_name)
    unique_extras: dict[str, str] = {}
    for extra in extra_values + extras:
        unique_extras.setdefault(canonicalize_name(extra), extra)
    return list(unique_extras.values())


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
    dependency_groups = _get_table(data, "dependency-groups", "[dependency-groups]", pyproject_path)
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
    return _check_str(readme.get("file", ""), "[project].readme.file", pyproject_path)


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
    file = _check_str(license_.get("text", ""), "[project].license.text", pyproject_path)
    _check_str(license_.get("file", ""), "[project].license.file", pyproject_path)
    return file


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
    for index, author in enumerate(_check_array(authors, "[project].authors", pyproject_path)):
        label = f"[project].authors[{index}]"
        if not isinstance(author, dict):
            msg = f"{pyproject_path}: {label} must be a table, got: {author!r}"
            raise MetadataError(msg)
        entry: dict[str, str] = {}
        for key in ("name", "email"):
            if key not in author:
                continue
            entry[key] = _check_str(author[key], f"{label}.{key}", pyproject_path)
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
    table = _get_table(project, key, f"[project.{key}]", pyproject_path)
    for name, value in table.items():
        _check_str(value, f"[project.{key}].{name}", pyproject_path)
    return dict(table)


def parse_string_array(raw: str, input_name: str) -> list[str]:
    """Parse the JSON array of strings of an action input.

    Args:
        raw: The value of the input.
        input_name: The name of the input, used in the error messages.

    Returns:
        The strings, in order, duplicates included.

    Raises:
        MetadataError: If ``raw`` is not valid JSON or not an array of strings.
    """
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"{input_name} is not valid JSON: {raw!r}"
        raise MetadataError(msg) from exc
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        msg = f"{input_name} must be a JSON array of strings, got: {raw!r}"
        raise MetadataError(msg)
    return values


def _check_str(value: object, label: str, pyproject_path: str) -> str:
    """Return ``value`` if it is a string, and raise ``MetadataError`` otherwise.

    Args:
        value: The value read from the file.
        label: The name of the key in the error message, such as ``[project].description``.
        pyproject_path: Path of the file, used in the error message.

    Returns:
        ``value``, unchanged.

    Raises:
        MetadataError: If ``value`` is not a string.
    """
    if not isinstance(value, str):
        msg = f"{pyproject_path}: {label} must be a string, got: {value!r}"
        raise MetadataError(msg)
    return value


def _check_array(value: object, label: str, pyproject_path: str) -> list[Any]:
    """Return ``value`` if it is an array, and raise ``MetadataError`` otherwise."""
    if not isinstance(value, list):
        msg = f"{pyproject_path}: {label} must be an array, got: {value!r}"
        raise MetadataError(msg)
    return value


def _check_string_array(value: object, label: str, pyproject_path: str) -> list[str]:
    """Return ``value`` if it is an array of strings, and raise ``MetadataError`` otherwise.

    Used for the arrays of requirement strings and for ``[project].dynamic``.
    """
    entries = _check_array(value, label, pyproject_path)
    for entry in entries:
        if not isinstance(entry, str):
            msg = f"{pyproject_path}: {label} must contain only strings, got: {entry!r}"
            raise MetadataError(msg)
    return entries


def _get_table(
    container: dict[str, Any], key: str, label: str, pyproject_path: str
) -> dict[str, Any]:
    """Return ``container[key]`` (an empty table if absent), checking that it is a table.

    Args:
        container: The table that holds ``key``.
        key: The key to read.
        label: The name of the table in error messages, such as ``[project]``.
        pyproject_path: Path of the file, used in the error message.

    Returns:
        The table, or an empty dict if ``key`` is absent.

    Raises:
        MetadataError: If the value is not a table.
    """
    value = container.get(key, {})
    if not isinstance(value, dict):
        msg = f"{pyproject_path}: {label} must be a table, got: {value!r}"
        raise MetadataError(msg)
    return value


def _cycle_message(cycle: tuple[str, ...], pyproject_path: str) -> str:
    """Describe an include-group cycle, starting from its smallest group name.

    The same cycle is reached from each of its groups: rotating it to a fixed
    starting point gives the same message each time, so it can be deduplicated.
    """
    start = cycle.index(min(cycle))
    ordered = (*cycle[start:], *cycle[:start])
    path = " -> ".join((*ordered, ordered[0]))
    return f"{pyproject_path}: [dependency-groups] has an include-group cycle: {path}"


def _flatten_group(
    groups: dict[str, Any],
    name: str,
    seen: tuple[str, ...] = (),
    pyproject_path: str = "pyproject.toml",
) -> tuple[list[str], list[str]]:
    """Return requirement strings of a dependency group, expanding include-group.

    An ``include-group`` that leads back to a group being expanded is not
    followed again, with a warning (once per cycle). An ``include-group`` that
    names no group is skipped, with a warning.

    Returns:
        A tuple ``(requirements, warnings)``, without duplicate warnings.

    Raises:
        MetadataError: If a group is not an array, an ``include-group`` value
            is not a string, or an entry is neither a string nor a table whose
            only key is ``include-group`` (for example a typo such as
            ``include_group``).
    """
    key = canonicalize_name(name)
    if key in seen:
        return [], [_cycle_message(seen[seen.index(key) :], pyproject_path)]
    out: list[str] = []
    warnings: list[str] = []
    for gname, entries in groups.items():
        if canonicalize_name(gname) != key:
            continue
        label = f"[dependency-groups].{gname}"
        for entry in _check_array(entries, label, pyproject_path):
            if isinstance(entry, str):
                out.append(entry)
            elif isinstance(entry, dict) and set(entry) == {"include-group"}:
                included = entry["include-group"]
                if not isinstance(included, str):
                    msg = (
                        f"{pyproject_path}: {label}: include-group must be a string, "
                        f"got: {included!r}"
                    )
                    raise MetadataError(msg)
                if not any(
                    canonicalize_name(group) == canonicalize_name(included) for group in groups
                ):
                    warnings.append(
                        f"{pyproject_path}: {label}: include-group {included!r} "
                        "does not match any group"
                    )
                included_reqs, included_warnings = _flatten_group(
                    groups, included, (*seen, key), pyproject_path
                )
                out.extend(included_reqs)
                warnings.extend(included_warnings)
            else:
                msg = (
                    f"{pyproject_path}: {label} entries must be strings or "
                    f"{{'include-group': <name>}} tables, got: {entry!r}"
                )
                raise MetadataError(msg)
    return out, list(dict.fromkeys(warnings))


def _dynamic_message(field: str, pyproject_path: str) -> str:
    """Describe a dependency field that is dynamic, so cannot be read."""
    return (
        f"{pyproject_path}: [project].{field} is dynamic, it cannot be read, so no "
        "requirement is found in it"
    )


def _dynamic_dependency_fields(data: dict[str, Any]) -> list[str]:
    """Return the dependency fields that only the build backend can provide.

    A field is returned when it is listed in ``[project].dynamic`` and has no
    static value in ``[project]``. Only ``dependencies`` and
    ``optional-dependencies`` are checked, in this order.
    """
    project = data.get("project", {})
    if not isinstance(project, dict):
        return []
    dynamic = project.get("dynamic", [])
    if not isinstance(dynamic, list):
        return []
    return [
        field
        for field in ("dependencies", "optional-dependencies")
        if field in dynamic and field not in project
    ]


def _candidate_requirements(
    data: dict[str, Any], pyproject_path: str = "pyproject.toml"
) -> tuple[list[str], list[str]]:
    """All requirement strings, in search order.

    Returns:
        A tuple ``(requirements, warnings)``. ``warnings`` has one message per
        dependency field that is dynamic (the build backend computes it, so it
        cannot be read), per include-group cycle and per ``include-group`` that
        names no group.

    Raises:
        MetadataError: If ``[project]``, ``[project].dependencies``,
            ``[project.optional-dependencies]``, ``[dependency-groups]`` or one
            of their values has the wrong type, or if a requirement of
            ``[project].dependencies`` or of an extra is not a string.
    """
    scoped, warnings = _scoped_requirements(data, pyproject_path)
    return [raw for _, raw in scoped], warnings


def _scoped_requirements(
    data: dict[str, Any], pyproject_path: str = "pyproject.toml"
) -> tuple[list[tuple[str, str]], list[str]]:
    """All requirement strings with the place they are declared in, in search order.

    Returns:
        A tuple ``(requirements, warnings)``, as for ``_candidate_requirements``.
        Each requirement is a tuple ``(scope, requirement)``. ``scope`` is
        ``"project"`` for ``[project].dependencies``, ``"extra:<name>"`` for an extra
        and ``"group:<name>"`` for a dependency group (the requirements that its
        ``include-group`` entries add included), with the name normalized per PEP 503.
        Spellings of the same name share one scope.

    Raises:
        MetadataError: Under the same conditions as ``_candidate_requirements``.
    """
    project = _get_table(data, "project", "[project]", pyproject_path)
    reqs = [
        (_PROJECT_SCOPE, raw)
        for raw in _check_string_array(
            project.get("dependencies", []), "[project].dependencies", pyproject_path
        )
    ]
    optional_dependencies = _get_table(
        project, "optional-dependencies", "[project].optional-dependencies", pyproject_path
    )
    for extra, extra_reqs in optional_dependencies.items():
        label = f"[project.optional-dependencies].{extra}"
        scope = f"extra:{canonicalize_name(extra)}"
        reqs.extend((scope, raw) for raw in _check_string_array(extra_reqs, label, pyproject_path))
    groups = _get_table(data, "dependency-groups", "[dependency-groups]", pyproject_path)
    warnings = [
        _dynamic_message(field, pyproject_path)
        for field in _dynamic_dependency_fields(data)
    ]
    # _flatten_group reads every spelling of a group name (PEP 503), so each group is expanded
    # once, from the first spelling: expanding each spelling would repeat its requirements.
    first_spellings: dict[str, str] = {}
    for group in groups:
        first_spellings.setdefault(canonicalize_name(group), group)
    for gname in first_spellings.values():
        group_reqs, group_warnings = _flatten_group(groups, gname, pyproject_path=pyproject_path)
        scope = f"group:{canonicalize_name(gname)}"
        reqs.extend((scope, raw) for raw in group_reqs)
        warnings.extend(group_warnings)
    return reqs, list(dict.fromkeys(warnings))


def parse_dependencies(raw: str) -> list[str]:
    """Parse the ``dependencies`` input: a JSON array of package names with an optional scope.

    A name may be followed by ``@`` and the only place to look it up in:
    ``name@project`` (``[project].dependencies``), ``name@extra:<extra>``
    (``[project.optional-dependencies]``) or ``name@group:<group>``
    (``[dependency-groups]``, ``include-group`` expanded). Without a scope, every place is
    searched. A package name cannot contain ``@``, so the scope is unambiguous.

    Args:
        raw: The value of the input.

    Returns:
        The entries as written, in order, duplicates included.

    Raises:
        MetadataError: If ``raw`` is not a JSON array of strings, or an entry has a scope that is
            not ``project``, ``extra:<name>`` or ``group:<name>`` (with a name).
    """
    entries = parse_string_array(raw, "dependencies")
    for entry in entries:
        _, separator, scope = entry.partition("@")
        kind, _, name = scope.partition(":")
        if separator and scope != _PROJECT_SCOPE and (kind not in {"extra", "group"} or not name):
            msg = (
                f"dependencies entry {entry!r} has an invalid scope: it must be 'project', "
                "'extra:<name>' or 'group:<name>' (for example 'pytest@group:dev')"
            )
            raise MetadataError(msg)
    return entries


def _lookup_key(dependency: str) -> str:
    """Return the key of the index of the requirements for an entry of ``dependencies``.

    Args:
        dependency: An entry, as returned by ``parse_dependencies``.

    Returns:
        The normalized package name (PEP 503), followed by ``@`` and the normalized scope for
        an entry with a scope, as ``_index_dependencies`` stores them.
    """
    name, separator, scope = dependency.partition("@")
    if not separator:
        return canonicalize_name(name)
    kind, colon, scope_name = scope.partition(":")
    return f"{canonicalize_name(name)}@{kind}{colon}{canonicalize_name(scope_name)}"


@functools.lru_cache(maxsize=None)
def _parse_requirement(raw: str) -> Requirement | InvalidRequirement:
    """Parse a requirement string, once per distinct string.

    ``build_report`` reads the requirements of ``[project].dependencies`` twice (for
    ``project-dependencies`` and in the index of all the requirements that the
    lookups of ``dependencies`` share): the cache makes each string parsed only once.

    Args:
        raw: The requirement string.

    Returns:
        The parsed requirement, or the ``InvalidRequirement`` that was raised
        (returned and not raised, so that the cache keeps it too). The result
        is shared and must not be modified.
    """
    try:
        return Requirement(raw)
    except InvalidRequirement as exc:
        return exc


def _index_requirements(
    raws: list[str], pyproject_path: str
) -> tuple[dict[str, list[tuple[str, str | None]]], dict[str, str], list[str]]:
    """Parse requirement strings and group them by package.

    Args:
        raws: The requirement strings, in search order.
        pyproject_path: Path of the file, used in the warning messages.

    Returns:
        A tuple ``(found, names, warnings)``. ``found`` maps the normalized
        name of each package to the ``(specifier, marker)`` of each of its
        requirements, in order (``marker`` is ``None`` when there is none).
        ``names`` maps it to the name as written in its first requirement.
        ``warnings`` has one message per requirement that cannot be parsed,
        which is ignored.
    """
    found: dict[str, list[tuple[str, str | None]]] = {}
    names: dict[str, str] = {}
    warnings: list[str] = []
    for raw in raws:
        req = _parse_requirement(raw)
        if isinstance(req, InvalidRequirement):
            warnings.append(f"Ignoring invalid requirement {raw!r} in {pyproject_path}: {req}")
            continue
        key = canonicalize_name(req.name)
        marker = None if req.marker is None else str(req.marker)
        found.setdefault(key, []).append((str(req.specifier), marker))
        names.setdefault(key, req.name)
    return found, names, warnings


def extract_project_dependencies(
    data: dict[str, Any], pyproject_path: str = "pyproject.toml"
) -> tuple[dict[str, str], list[str]]:
    """Map each package of ``[project].dependencies`` to its specifier.

    Only the requirements of ``[project].dependencies`` are read, not the
    extras or the dependency groups. Like ``extract_dependency_specifiers``, the
    first requirement of a package wins, whatever its environment marker.

    Args:
        data: The parsed pyproject.toml, as returned by ``load_pyproject``.
        pyproject_path: Path of the file ``data`` was read from, used only in
            error and warning messages.

    Returns:
        A tuple ``(dependencies, warnings)``. ``dependencies`` maps the name of
        each package, as written in its first requirement and in the order of
        the file, to its specifier (``""`` if it has none). ``warnings`` lists
        the requirements that cannot be parsed and are ignored, the packages
        that have different specifiers (with the same environment marker), and
        a ``dynamic`` ``dependencies``.

    Raises:
        MetadataError: If ``[project]`` is not a table, or
            ``[project].dependencies`` is not an array of strings.
    """
    project = _get_table(data, "project", "[project]", pyproject_path)
    entries = _check_string_array(
        project.get("dependencies", []), "[project].dependencies", pyproject_path
    )
    found, names, warnings = _index_requirements(entries, pyproject_path)
    if "dependencies" in _dynamic_dependency_fields(data):
        warnings.append(_dynamic_message("dependencies", pyproject_path))
    dependencies: dict[str, str] = {}
    for key, matches in found.items():
        specifier = matches[0][0]
        dependencies[names[key]] = specifier
        warnings.extend(_conflict_warnings(names[key], matches, specifier, pyproject_path))
    return dependencies, warnings


def extract_dependency_specifiers(
    data: dict[str, Any],
    dependencies: list[str],
    pyproject_path: str = "pyproject.toml",
) -> tuple[dict[str, str | None], list[str]]:
    """Map each requested package to its specifier string, or None if not found.

    Args:
        data: The parsed pyproject.toml, as returned by ``load_pyproject``.
        dependencies: Package names to look up, as returned by
            ``parse_dependencies``: a name may be followed by ``@`` and a scope that limits
            the lookup to ``[project].dependencies``, one extra or one group.
        pyproject_path: Path of the file ``data`` was read from, used only in
            error and warning messages.

    Returns:
        A tuple ``(specifiers, warnings)``. ``specifiers`` maps each requested
        package name to its specifier, ``""`` if the requirement has no
        specifier, or ``None`` if it was not found. ``warnings`` lists the
        warning messages: a package has different specifiers (with the same
        environment marker) in several places, a requirement string cannot be
        parsed and is ignored, ``include-group`` entries form a cycle, or an
        ``include-group`` names a group that does not exist. Invalid
        requirements and include-group problems are only reported when
        ``dependencies`` is not empty.

    Raises:
        MetadataError: If ``[project].dependencies``, ``[project.optional-dependencies]``
            or ``[dependency-groups]`` (or one of their values) has the wrong
            type, or a requirement of ``[project].dependencies`` or of an extra
            is not a string.
    """
    found, index_warnings = _index_dependencies(data, pyproject_path)
    return _specifiers_from_index(found, index_warnings, dependencies, pyproject_path)


def _index_dependencies(
    data: dict[str, Any], pyproject_path: str
) -> tuple[dict[str, list[tuple[str, str | None]]], list[str]]:
    """Index every requirement of the file by package, once for all the lookups.

    Args:
        data: The parsed pyproject.toml, as returned by ``load_pyproject``.
        pyproject_path: Path of the file ``data`` was read from, used only in
            error and warning messages.

    Returns:
        A tuple ``(found, warnings)``. ``found`` is the first result of
        ``_index_requirements`` on the requirements of ``_scoped_requirements``
        (in search order), keyed by normalized package name. It also has, for each
        place that declares requirements, the same index of the requirements of that
        place only under the key ``"<name>@<scope>"`` (for example ``"numpy@extra:x"``,
        see ``_lookup_key``), for the entries of ``dependencies`` that have a scope.
        ``warnings`` lists the warnings of both: dynamic dependency fields,
        include-group problems and invalid requirements.

    Raises:
        MetadataError: Under the same conditions as ``_scoped_requirements``.
    """
    scoped, structure_warnings = _scoped_requirements(data, pyproject_path)
    found, _, invalid_warnings = _index_requirements([raw for _, raw in scoped], pyproject_path)
    for scope in dict.fromkeys(scope for scope, _ in scoped):
        in_scope, _, _ = _index_requirements(
            [raw for other, raw in scoped if other == scope], pyproject_path
        )
        found.update({f"{key}@{scope}": matches for key, matches in in_scope.items()})
    return found, [*structure_warnings, *invalid_warnings]


def _specifiers_from_index(
    found: dict[str, list[tuple[str, str | None]]],
    index_warnings: list[str],
    dependencies: list[str],
    pyproject_path: str,
) -> tuple[dict[str, str | None], list[str]]:
    """Look up the specifier of each requested package in an index of the requirements.

    Args:
        found: The index, as returned by ``_index_dependencies``.
        index_warnings: The warnings returned with the index. They are only
            worth reporting when ``dependencies`` is not empty: an invalid
            requirement may be the very entry that was meant to be found.
        dependencies: Package names to look up, with their optional scope.
        pyproject_path: Path of the file, used in the warning messages.

    Returns:
        A tuple ``(specifiers, warnings)``, as returned by
        ``extract_dependency_specifiers``.
    """
    warnings = list(index_warnings) if dependencies else []

    result: dict[str, str | None] = {}
    for dep in dependencies:
        matches = found.get(_lookup_key(dep))
        if not matches:
            result[dep] = None
            continue
        specifier = matches[0][0]
        warnings.extend(_conflict_warnings(dep, matches, specifier, pyproject_path))
        result[dep] = specifier
    return result, warnings


def extract_dependency_requirements(
    data: dict[str, Any],
    dependencies: list[str],
    pyproject_path: str = "pyproject.toml",
) -> dict[str, list[dict[str, str]]]:
    """Map each requested package to all its requirements, with their markers.

    Unlike ``extract_dependency_specifiers``, which keeps the first requirement
    of a package, this lists every requirement, so that a caller can pick the one
    that applies to its environment (for example one per Python version).

    Args:
        data: The parsed pyproject.toml, as returned by ``load_pyproject``.
        dependencies: Package names to look up, as returned by
            ``parse_dependencies``: a name may be followed by ``@`` and a scope that limits
            the lookup to ``[project].dependencies``, one extra or one group.
        pyproject_path: Path of the file ``data`` was read from, used only in
            error messages.

    Returns:
        A dict that maps each requested package name to the list of its
        requirements, in search order (``[project].dependencies``, extras, then
        dependency groups), each a dict with the ``specifier`` (``""`` if there is
        none) and the environment ``marker`` (``""`` if there is none). The list
        is empty if the package is not found. The warnings are those of
        ``extract_dependency_specifiers``, not repeated here.

    Raises:
        MetadataError: Under the same conditions as ``extract_dependency_specifiers``.
    """
    found, _ = _index_dependencies(data, pyproject_path)
    return _requirements_from_index(found, dependencies)


def _requirements_from_index(
    found: dict[str, list[tuple[str, str | None]]], dependencies: list[str]
) -> dict[str, list[dict[str, str]]]:
    """List the requirements of each requested package in an index of the requirements.

    Args:
        found: The index, as returned by ``_index_dependencies``.
        dependencies: Package names to look up, with their optional scope.

    Returns:
        The mapping returned by ``extract_dependency_requirements``.
    """
    return {
        dep: [
            {"specifier": specifier, "marker": marker or ""}
            for specifier, marker in found.get(_lookup_key(dep), [])
        ]
        for dep in dependencies
    }


def _conflict_warnings(
    dep: str, matches: list[tuple[str, str | None]], used: str, pyproject_path: str
) -> list[str]:
    """Describe the requirements of ``dep`` that disagree on the specifier.

    Requirements with different environment markers (for example one per Python
    version) are expected to have different specifiers, so only requirements
    with the same marker are compared.

    Args:
        dep: The requested package name, as written by the caller.
        matches: The ``(specifier, marker)`` of each requirement of the package,
            in search order. ``marker`` is ``None`` when there is none.
        used: The specifier the lookup returns.
        pyproject_path: Path of the file, used in the messages.

    Returns:
        One message per marker (``None`` included) with more than one specifier.
    """
    by_marker: dict[str | None, set[str]] = {}
    for specifier, marker in matches:
        by_marker.setdefault(marker, set()).add(specifier)
    messages = []
    for marker, specs in by_marker.items():
        if len(specs) > 1:
            where = "" if marker is None else f" for marker {marker!r}"
            messages.append(
                f"{dep} has different specifiers{where} in {pyproject_path}: "
                f"{sorted(specs)}; using {used!r}"
            )
    return messages


def parse_python_candidates(raw: str) -> list[str]:
    """Parse the ``python-candidates`` input.

    Args:
        raw: The value of the input, a JSON array of "major.minor" strings.

    Returns:
        The versions, in order, without duplicates.

    Raises:
        MetadataError: If ``raw`` is not a JSON array of strings, or a string
            is not of the form "major.minor" (such as ``"3.12"``).
    """
    candidates = parse_string_array(raw, "python-candidates")
    for candidate in candidates:
        if not _MINOR_VERSION.fullmatch(candidate):
            msg = f"python-candidates must contain 'major.minor' versions such as '3.12', got: {candidate!r}"
            raise MetadataError(msg)
    return list(dict.fromkeys(candidates))


def compatible_python_versions(
    requires_python: str, candidates: list[str], pyproject_path: str = "pyproject.toml"
) -> tuple[list[str], list[str]]:
    """Select the candidate Python versions that ``requires-python`` allows.

    A "major.minor" candidate is allowed when some release of it can satisfy the
    specifier. This is checked on each ``X.Y.0`` to ``X.Y.99`` (CPython patch
    numbers stay below 100) and on a very late one (``X.Y.9999``), so
    ``>=3.10.2`` and ``<3.12.5`` allow ``3.10`` and ``3.12``, and ``==3.12.3``
    allows ``3.12`` only. A patch number of 100 or more that a specifier names
    exactly (``==3.12.150``) matches no release, so the candidate is not
    allowed; ``>=3.12.150`` is, as it has no upper bound.

    Args:
        requires_python: ``[project].requires-python`` as written, or an empty
            string if it is not declared.
        candidates: The "major.minor" versions to choose from, as returned by
            ``parse_python_candidates``.
        pyproject_path: Path of the file, used in the warning message.

    Returns:
        A tuple ``(versions, warnings)``. ``versions`` are the allowed
        candidates, in the order of ``candidates``: all of them when
        ``requires_python`` is empty, none of them (with a warning) when it is
        not a valid specifier.
    """
    if not requires_python.strip():
        return list(candidates), []
    try:
        specifier = SpecifierSet(requires_python)
    except InvalidSpecifier as exc:
        warning = (
            f"{pyproject_path}: [project].requires-python is not a valid version specifier, "
            f"the python-versions output is empty: {exc}"
        )
        return [], [warning]
    versions = [
        candidate
        for candidate in candidates
        if any(
            specifier.contains(f"{candidate}.{patch}")
            for patch in _PATCH_RELEASES
        )
    ]
    return versions, []


def _minor_version_key(version: str) -> tuple[int, ...]:
    """Return the numbers of a "major.minor" version, to compare versions as numbers."""
    return tuple(int(part) for part in version.split("."))


def lowest_python_version(versions: Sequence[str]) -> str:
    """Return the lowest of "major.minor" versions, compared as numbers.

    Args:
        versions: Versions such as ``"3.9"`` and ``"3.10"``, as returned by
            ``compatible_python_versions``.

    Returns:
        The lowest version (``"3.9"`` is lower than ``"3.10"``), or an empty
        string if ``versions`` is empty.
    """
    if not versions:
        return ""
    return min(versions, key=_minor_version_key)


def highest_python_version(versions: Sequence[str]) -> str:
    """Return the highest of "major.minor" versions, compared as numbers.

    Args:
        versions: Versions such as ``"3.9"`` and ``"3.10"``, as returned by
            ``compatible_python_versions``.

    Returns:
        The highest version (``"3.10"`` is higher than ``"3.9"``), or an empty
        string if ``versions`` is empty.
    """
    if not versions:
        return ""
    return max(versions, key=_minor_version_key)


def parse_bool(value: str, name: str) -> bool:
    """Parse the ``"true"`` / ``"false"`` string of a boolean input.

    Args:
        value: The string, compared case-insensitively.
        name: The name of the input, used in the error message.

    Returns:
        The boolean value.

    Raises:
        MetadataError: If ``value`` is neither ``"true"`` nor ``"false"``.
    """
    lowered = value.strip().lower()
    if lowered not in {"true", "false"}:
        msg = f"{name} must be 'true' or 'false', got: {value!r}"
        raise MetadataError(msg)
    return lowered == "true"


def parse_options(args: argparse.Namespace) -> Options:
    """Parse the four boolean inputs of the command line, in one place.

    Args:
        args: The parsed command line, as returned by ``_build_parser``.

    Returns:
        The parsed booleans.

    Raises:
        MetadataError: If one of them is neither ``"true"`` nor ``"false"``
            (the first invalid one, in the order of ``Options``).
    """
    return Options(
        fail_on_missing=parse_bool(args.fail_on_missing, "fail-on-missing"),
        fail_on_dynamic_version=parse_bool(
            args.fail_on_dynamic_version, "fail-on-dynamic-version"
        ),
        strict=parse_bool(args.strict, "strict"),
        step_summary=parse_bool(args.step_summary, "step-summary"),
    )


def check_no_missing_dependency(
    specifiers: dict[str, str | None],
    pyproject_path: str,
    dynamic_fields: Sequence[str] = (),
) -> None:
    """Raise if a requested dependency was not found.

    Args:
        specifiers: The mapping returned by ``extract_dependency_specifiers``.
        pyproject_path: Path of the file, used in the error message.
        dynamic_fields: The dependency fields that are dynamic, as returned by
            ``_dynamic_dependency_fields``. The error message points them out,
            because a package may be missing only because it cannot be read.

    Raises:
        MetadataError: If a package maps to ``None``.
    """
    missing = [name for name, specifier in specifiers.items() if specifier is None]
    if missing:
        msg = (
            f"{pyproject_path}: dependencies not found in [project].dependencies, "
            f"[project.optional-dependencies] or [dependency-groups]: {missing}"
        )
        for field in dynamic_fields:
            msg += f"; [project].{field} is dynamic and cannot be read"
        raise MetadataError(msg)


def escape_annotation(message: str) -> str:
    """Escape a message for use in a ``::warning::`` workflow command.

    Same escaping as ``@actions/core``: without it a newline would end the
    command and the rest of the message would be parsed as another command.
    """
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def escape_annotation_property(value: str) -> str:
    """Escape a property value (such as ``file``) of a workflow command.

    Same escaping as ``@actions/core``: like ``escape_annotation``, plus ``:``
    and ``,``, which delimit properties.
    """
    return escape_annotation(value).replace(":", "%3A").replace(",", "%2C")


def _compact_json(value: object) -> str:
    """Serialize ``value`` as the compact JSON of an action output.

    No space after ``,`` and ``:``, and non-ASCII characters are kept as they are.
    """
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def format_outputs(metadata: Report) -> dict[str, str]:
    """Convert the metadata dict into the string outputs of the action.

    Args:
        metadata: The report built by ``build_report``.

    Returns:
        A dict mapping each output name of ``action.yaml`` to its value, with
        JSON values in compact form.
    """
    return {
        "name": metadata["name"],
        "normalized-name": metadata["normalized_name"],
        "version": metadata["version"],
        "normalized-version": metadata["normalized_version"],
        "description": metadata["description"],
        "readme": metadata["readme"],
        "license": metadata["license"],
        "license-files": _compact_json(metadata["license_files"]),
        "authors": _compact_json(metadata["authors"]),
        "urls": _compact_json(metadata["urls"]),
        "keywords": _compact_json(metadata["keywords"]),
        "classifiers": _compact_json(metadata["classifiers"]),
        "scripts": _compact_json(metadata["scripts"]),
        "requires-python": metadata["requires_python"],
        "extras": _compact_json(metadata["extras"]),
        "groups": _compact_json(metadata["groups"]),
        "python-versions": _compact_json(metadata["python_versions"]),
        "python-min": metadata["python_min"],
        "python-max": metadata["python_max"],
        "python-matrix": _compact_json({"python-version": metadata["python_versions"]}),
        "project-dependencies": _compact_json(metadata["project_dependencies"]),
        "dependency-specifiers": _compact_json(metadata["dependency_specifiers"]),
        "dependency-requirements": _compact_json(metadata["dependency_requirements"]),
    }


def _new_delimiter() -> str:
    """Return a random delimiter for a multiline ``$GITHUB_OUTPUT`` value."""
    return f"ghadelimiter_{uuid.uuid4()}"


def _single_line(value: str) -> str:
    """Escape backslashes and line breaks so ``value`` stays on one log line."""
    return value.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n")


# The outputs shown in the summary line, in order (normalized-name is derived from name, and
# description may be long).
_SUMMARY_FIELDS = (
    "name",
    "version",
    "requires-python",
    "python-versions",
    "python-min",
    "python-max",
    "extras",
    "groups",
    "project-dependencies",
    "dependency-specifiers",
)


def format_summary(outputs: dict[str, str]) -> str:
    """Build the one-line summary of the outputs that is printed in the log.

    Args:
        outputs: The action outputs, as returned by ``format_outputs``.

    Returns:
        A line that starts with ``📦`` and lists ``name=value`` for the outputs
        in ``_SUMMARY_FIELDS``. Values come from the file, so line breaks and
        backslashes are escaped: a value cannot end the line and start a
        workflow command (``::...``) in the log.
    """
    fields = " ".join(f"{field}={_single_line(outputs[field])}" for field in _SUMMARY_FIELDS)
    return f"📦 {fields}"


def _html_cell(value: str) -> str:
    """Escape ``value`` for a cell of a Markdown table, shown as code.

    Every ASCII punctuation character is replaced by its numeric character
    reference, so that nothing in a value from the file can be interpreted as
    Markdown or HTML (a ``|`` ends the cell, ``<`` starts a tag, ``_`` is
    emphasis...). Line breaks are escaped as in the summary line of the log.
    """
    escaped = "".join(
        f"&#{ord(char)};" if char in string.punctuation else char for char in _single_line(value)
    )
    return f"<code>{escaped}</code>" if escaped else ""


def format_step_summary(report: Report, outputs: dict[str, str]) -> str:
    """Build the Markdown of the job summary.

    Args:
        report: The report built by ``build_report``.
        outputs: The action outputs, as returned by ``format_outputs``.

    Returns:
        A heading, a table with one row per output and, if there are warnings,
        a list of them. Values are escaped by ``_html_cell``.
    """
    lines = [
        "### 📦 Project metadata",
        "",
        "| Output | Value |",
        "| --- | --- |",
    ]
    lines.extend(f"| `{key}` | {_html_cell(value)} |" for key, value in outputs.items())
    if report["warnings"]:
        lines.extend(["", "#### ⚠️ Warnings", ""])
        lines.extend(f"- {_html_cell(warning)}" for warning in report["warnings"])
    return "\n".join(lines) + "\n"


def format_error_summary(message: str) -> str:
    """Build the Markdown of the job summary when the action fails.

    Args:
        message: The message of the ``MetadataError``. Each line (the error
            of ``--strict`` lists one warning per line, each starting with
            ``"- "``) becomes a list item.

    Returns:
        A heading and a list of the lines of the message, escaped by
        ``_html_cell`` like the values of ``format_step_summary``.
    """
    lines = ["### ❌ Project metadata", ""]
    lines.extend(
        f"- {_html_cell(line.strip().removeprefix('- '))}"
        for line in message.split("\n")
        if line.strip()
    )
    return "\n".join(lines) + "\n"


def write_step_summary(summary_path: str, markdown: str) -> None:
    """Append ``markdown`` to the job summary file, followed by a blank line.

    Raises:
        MetadataError: If the file cannot be written.
    """
    try:
        with Path(summary_path).open("a", encoding="utf-8", newline="") as f:
            f.write(f"{markdown}\n")
    except OSError as exc:
        msg = f"cannot write the job summary to {summary_path}: {exc}"
        raise MetadataError(msg) from exc


def resolve_step_summary(enabled: bool, environ: Mapping[str, str]) -> str | None:
    """Return the path of the job summary file, or None if it is not requested.

    Args:
        enabled: The parsed ``--step-summary`` option.
        environ: The environment variables.

    Returns:
        The value of ``GITHUB_STEP_SUMMARY`` when ``enabled`` is true, None
        otherwise.

    Raises:
        MetadataError: If ``enabled`` is true and ``GITHUB_STEP_SUMMARY`` is not
            set (the action is not running in a GitHub workflow).
    """
    if not enabled:
        return None
    summary_path = environ.get("GITHUB_STEP_SUMMARY", "")
    if not summary_path:
        msg = "step-summary is 'true' but the environment variable GITHUB_STEP_SUMMARY is not set"
        raise MetadataError(msg)
    return summary_path


def write_github_output(output_path: str, outputs: dict[str, str]) -> None:
    """Append outputs to a ``$GITHUB_OUTPUT`` file.

    Every value is written with the ``key<<delimiter`` syntax, so a value that
    contains line breaks (a TOML string can) cannot end early and add outputs
    of its own. The delimiter is random and is regenerated if it appears in
    the key or the value.

    Args:
        output_path: Path of the file, which is created if it does not exist.
        outputs: Output names and values.

    Raises:
        MetadataError: If the file cannot be written.
    """
    try:
        with Path(output_path).open("a", encoding="utf-8", newline="") as f:
            for key, value in outputs.items():
                delimiter = _new_delimiter()
                while delimiter in key or delimiter in value:
                    delimiter = _new_delimiter()
                f.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")
    except OSError as exc:
        msg = f"cannot write the outputs to {output_path}: {exc}"
        raise MetadataError(msg) from exc


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
    found, index_warnings = _index_dependencies(data, args.pyproject_path)
    specifiers, specifier_warnings = _specifiers_from_index(
        found, index_warnings, dependencies, args.pyproject_path
    )
    requirements = _requirements_from_index(found, dependencies)
    warnings.extend(python_warnings)
    warnings.extend(project_warnings)
    warnings.extend(specifier_warnings)
    if options.fail_on_missing:
        check_no_missing_dependency(
            specifiers, args.pyproject_path, _dynamic_dependency_fields(data)
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


def emit_github_output(report: Report, pyproject_path: str, output_path: str) -> None:
    """Write the outputs of the action and print the workflow commands and the summary.

    Args:
        report: The report built by ``build_report``.
        pyproject_path: Path of the pyproject.toml, used as the ``file`` of the
            warning annotations.
        output_path: Path of the ``$GITHUB_OUTPUT`` file.

    Raises:
        MetadataError: If the outputs cannot be written.
    """
    outputs = format_outputs(report)
    file = escape_annotation_property(pyproject_path)
    for warning in report["warnings"]:
        print(f"::warning file={file}::{escape_annotation(warning)}")
    print(format_summary(outputs))
    write_github_output(output_path, outputs)


def format_error(message: str, pyproject_path: str, annotate: bool) -> str:
    """Format an error message for stderr.

    Args:
        message: The message of the ``MetadataError``.
        pyproject_path: Path of the pyproject.toml, used as the ``file`` of the
            annotation.
        annotate: Whether to build a ``::error file=<path>::`` workflow command
            (so that GitHub shows an error annotation on the file) instead of
            the plain message.

    Returns:
        The line to print on stderr.
    """
    if not annotate:
        return message
    file = escape_annotation_property(pyproject_path)
    return f"::error file={file}::{escape_annotation(message)}"


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


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
