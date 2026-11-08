"""Extraction of the project metadata (name, version and the other fields) from the parsed file."""

from __future__ import annotations

import re
from typing import Any

from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from extract_pyproject_metadata.checks import check_str, check_string_array, get_table
from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.fields import (
    read_authors,
    read_build_system,
    read_extra_names,
    read_group_names,
    read_readme_path,
    read_string_table,
    read_urls,
)
from extract_pyproject_metadata.license import license_warnings, read_license_text
from extract_pyproject_metadata.types import Metadata

# A project name per PEP 508: letters, digits, "-", "_" and "." that start and end with a
# letter or a digit. Always used with ``fullmatch``.
_VALID_NAME = re.compile(r"[A-Z0-9]|[A-Z0-9][A-Z0-9._-]*[A-Z0-9]", re.IGNORECASE)


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

    readme = read_readme_path(project.get("readme", ""), pyproject_path)
    license_ = read_license_text(project.get("license", ""), pyproject_path)
    warnings.extend(license_warnings(project.get("license", ""), pyproject_path))
    authors = read_authors(project.get("authors", []), pyproject_path)
    urls = read_urls(project, pyproject_path)
    scripts = read_string_table(project, "scripts", pyproject_path)
    keywords = check_string_array(project.get("keywords", []), "[project].keywords", pyproject_path)
    classifiers = check_string_array(
        project.get("classifiers", []), "[project].classifiers", pyproject_path
    )

    requires_python = check_str(
        project.get("requires-python", ""), "[project].requires-python", pyproject_path
    )
    build_backend, build_requires = read_build_system(data, pyproject_path)
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
        extras=read_extra_names(project, extra_values, pyproject_path),
        groups=read_group_names(data, pyproject_path),
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
