"""Read and parse a pyproject.toml file, and read and validate the fields that the
action outputs (name, version, ``requires-python``, extras and dependency groups)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from extract_pyproject_metadata._vendor.packaging.utils import canonicalize_name
from extract_pyproject_metadata._vendor.packaging.version import InvalidVersion, Version
from extract_pyproject_metadata.checks import check_str, check_string_array, get_table
from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.types import Project, ReportWarning

__all__ = ["UTF8_BOM", "load_pyproject", "read_extra_names", "read_group_names", "read_project"]

# The UTF-8 byte order mark that some editors write at the start of a file.
UTF8_BOM = b"\xef\xbb\xbf"

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
        msg = "pyproject-path: not a file"
        raise MetadataError(msg)
    try:
        with path.open("rb") as f:
            content = f.read()
        # Some editors start a UTF-8 file with a byte order mark, which TOML rejects.
        return tomllib.loads(content.removeprefix(UTF8_BOM).decode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        msg = f"pyproject-path: not valid TOML: {exc}"
        raise MetadataError(msg) from exc
    except UnicodeDecodeError as exc:
        msg = f"pyproject-path: not valid UTF-8: {exc}"
        raise MetadataError(msg) from exc
    except RecursionError as exc:  # tomllib recurses on nested arrays and inline tables
        msg = "pyproject-path: nested too deeply to be parsed"
        raise MetadataError(msg) from exc
    except OSError as exc:
        msg = f"pyproject-path: cannot be read: {exc}"
        raise MetadataError(msg) from exc


def read_project(
    data: dict[str, Any],
    extra_values: list[str],
) -> tuple[Project, list[ReportWarning]]:
    """Read and validate the fields that the action outputs from a parsed
    pyproject.toml.

    Args:
        data: The parsed pyproject.toml, as returned by ``load_pyproject``.
        extra_values: Extra values to prepend to the extras read from
            ``[project.optional-dependencies]``, as returned by
            ``parse_string_array``.

    Returns:
        A tuple ``(project, warnings)``. ``warnings`` lists the warning messages (for example
        when the version is dynamic, or when a field is both set and listed in ``dynamic``).

    Raises:
        MetadataError: If ``[project]`` is not a table, is missing ``name`` (also
            when ``name`` is listed in ``dynamic``, which PEP 621 forbids) or
            ``version`` (unless the version is dynamic), has a ``dynamic`` that
            is not an array of strings, a ``name`` that is not a non-empty string or not a
            valid PEP 508 name, a ``version`` that is not a string or not a valid PEP 440
            version, a ``requires-python`` that is not a string, or an
            ``optional-dependencies`` or ``dependency-groups`` that is not a table.
    """
    project = get_table(data, "project", "[project]")
    dynamic = check_string_array(project.get("dynamic", []), "[project].dynamic")
    raw_name = _required_name(project, dynamic)
    warnings = _static_and_dynamic_warnings(project, dynamic)
    raw_version, is_known, version_warnings = _required_version(project, dynamic)
    warnings.extend(version_warnings)
    name = _valid_name(raw_name)
    version = _valid_version(raw_version, is_known)
    requires_python = check_str(project.get("requires-python", ""), "[project].requires-python")
    return Project(
        name=name,
        version=version,
        requires_python=requires_python,
        dynamic=frozenset(dynamic),
        extras=read_extra_names(project, extra_values),
        groups=read_group_names(data),
    ), warnings


def _required_name(project: dict[str, Any], dynamic: list[str]) -> object:
    """Return ``[project].name`` as written, which must be set.

    Args:
        project: The ``[project]`` table.
        dynamic: The ``[project].dynamic`` array.

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
            msg = "[project].name: listed in [project].dynamic, but PEP 621 requires a static name"
            raise MetadataError(msg) from exc
        msg = f"[project].{exc.args[0]}: missing"
        raise MetadataError(msg) from exc


def _static_and_dynamic_warnings(
    project: dict[str, Any], dynamic: list[str]
) -> list[ReportWarning]:
    """Describe the fields that are set in ``[project]`` and also listed
    in ``dynamic``.

    PEP 621 forbids it. The static value is the one that is read.

    Args:
        project: The ``[project]`` table.
        dynamic: The ``[project].dynamic`` array.

    Returns:
        One warning per such field, in the order of ``dynamic``, without duplicates.
    """
    return [
        ReportWarning(
            "static-and-dynamic",
            f"[project].{field} is set and also listed in [project].dynamic, "
            "which PEP 621 forbids; the static value is used",
        )
        for field in dict.fromkeys(dynamic)
        if field in project
    ]


def _required_version(
    project: dict[str, Any], dynamic: list[str]
) -> tuple[object, bool, list[ReportWarning]]:
    """Return ``[project].version`` as written, or an empty string if it
    is dynamic.

    Args:
        project: The ``[project]`` table.
        dynamic: The ``[project].dynamic`` array.

    Returns:
        A tuple ``(version, is_known, warnings)``. ``version`` is the value of
        ``version`` whatever its type (see ``_valid_version``), or ``""`` when the
        build backend computes it (setuptools-scm, hatch-vcs, ...). ``is_known`` is
        false in that last case, and ``warnings`` then says so.

    Raises:
        MetadataError: If ``version`` is neither set nor dynamic.
    """
    if "version" in project:
        return project["version"], True, []
    if "version" not in dynamic:
        msg = "[project].version: missing"
        raise MetadataError(msg)
    warnings = [
        ReportWarning(
            "dynamic-version", "[project].version is dynamic, the version output is empty"
        )
    ]
    return "", False, warnings


def _valid_name(name: object) -> str:
    """Return ``name`` if it is a valid project name (PEP 508).

    Args:
        name: The value of ``[project].name``.

    Returns:
        ``name``, unchanged.

    Raises:
        MetadataError: If ``name`` is not a non-empty string, or contains
            other characters than letters, digits, ``-``, ``_`` and ``.``, or
            does not start and end with a letter or a digit.
    """
    if not isinstance(name, str) or not name:
        msg = f"[project].name: must be a non-empty string, got: {name!r}"
        raise MetadataError(msg)
    if not _VALID_NAME.fullmatch(name):
        msg = (
            "[project].name: not a valid project name (letters, digits, "
            f"'-', '_' and '.', starting and ending with a letter or a digit): {name!r}"
        )
        raise MetadataError(msg)
    return name


def _valid_version(version: object, is_static: bool) -> str | None:
    """Return the version if it is static and valid (PEP 440).

    Args:
        version: The value of ``[project].version``, or ``""`` if it is dynamic.
        is_static: Whether ``version`` is set in ``[project]`` (it is not
            when it is dynamic).

    Returns:
        ``version``, unchanged, or None when the version is dynamic.

    Raises:
        MetadataError: If ``version`` is not a string, or a static version is
            not a valid PEP 440 version.
    """
    version = check_str(version, "[project].version")
    if not is_static:
        return None
    try:
        Version(version)
    except InvalidVersion as exc:
        msg = f"[project].version: not a valid PEP 440 version: {version!r}"
        raise MetadataError(msg) from exc
    return version


def read_extra_names(project: dict[str, Any], extra_values: list[str]) -> list[str]:
    """Return the extra names: ``extra_values`` first, then the sorted
    extras.

    Extra names are normalized like package names (PEP 685), so "Foo_Bar" and
    "foo-bar" are one extra. The first spelling of each is kept, at the
    position of its first occurrence.

    Args:
        project: The ``[project]`` table.
        extra_values: The values to put first, as returned by ``parse_string_array``.

    Returns:
        The names, without duplicates.

    Raises:
        MetadataError: If ``[project.optional-dependencies]`` is not a table.
    """
    optional_dependencies = get_table(
        project, "optional-dependencies", "[project].optional-dependencies"
    )
    extras = sorted(optional_dependencies, key=canonicalize_name)
    unique_extras: dict[str, str] = {}
    for extra in extra_values + extras:
        unique_extras.setdefault(canonicalize_name(extra), extra)
    return list(unique_extras.values())


def read_group_names(data: dict[str, Any]) -> list[str]:
    """Return the names of ``[dependency-groups]``, sorted by normalized
    name.

    Group names are normalized per PEP 503 (PEP 735): the first spelling is kept.

    Args:
        data: The parsed pyproject.toml.

    Returns:
        The names, without duplicates; empty if there is no such table.

    Raises:
        MetadataError: If ``[dependency-groups]`` is not a table.
    """
    dependency_groups = get_table(data, "dependency-groups", "[dependency-groups]")
    unique_groups: dict[str, str] = {}
    for group in sorted(dependency_groups, key=canonicalize_name):
        unique_groups.setdefault(canonicalize_name(group), group)
    return list(unique_groups.values())
