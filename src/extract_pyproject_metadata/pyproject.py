"""Read and parse a pyproject.toml file, and read and validate the fields that the
action outputs (name, version, ``requires-python``, extras and dependency groups)."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from extract_pyproject_metadata._vendor.packaging.utils import canonicalize_name
from extract_pyproject_metadata._vendor.packaging.version import InvalidVersion, Version
from extract_pyproject_metadata.checks import (
    check_str,
    check_string_array,
    get_table,
    is_package_name,
)
from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.types import Project, ReportWarning

__all__ = ["UTF8_BOM", "load_pyproject", "read_extra_names", "read_group_names", "read_project"]

# The UTF-8 byte order mark that some editors write at the start of a file.
UTF8_BOM = b"\xef\xbb\xbf"


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
        MetadataError: If ``[project]`` is not a table (the first error found is reported,
            ``name`` before ``version``), is missing ``name`` (also
            when ``name`` is listed in ``dynamic``, which PEP 621 forbids) or
            ``version`` (unless the version is dynamic), has a ``dynamic`` that
            is not an array of strings, a ``name`` that is not a non-empty string or not a
            valid PEP 508 name, a ``version`` that is not a string or not a valid PEP 440
            version, a ``requires-python`` that is not a string, or an
            ``optional-dependencies`` or ``dependency-groups`` that is not a table.
    """
    project = get_table(data, "project", "[project]")
    dynamic = check_string_array(project.get("dynamic", []), "[project].dynamic")
    name = _read_name(project, dynamic)
    warnings = _static_and_dynamic_warnings(project, dynamic)
    version, version_warnings = _read_version(project, dynamic)
    warnings.extend(version_warnings)
    requires_python = check_str(project.get("requires-python", ""), "[project].requires-python")
    return Project(
        name=name,
        version=version,
        requires_python=requires_python,
        dynamic=frozenset(dynamic),
        extras=read_extra_names(project, extra_values),
        groups=read_group_names(data),
    ), warnings


def _read_name(project: dict[str, Any], dynamic: list[str]) -> str:
    """Return ``[project].name``, which must be set and valid.

    Args:
        project: The ``[project]`` table.
        dynamic: The ``[project].dynamic`` array.

    Returns:
        The name, unchanged.

    Raises:
        MetadataError: If ``name`` is not set (with a message that says so when it is listed
            in ``dynamic``: PEP 621 requires a static name), is not a non-empty string, or is
            not a valid package name (PEP 508: letters, digits, ``-``, ``_`` and ``.``, starting
            and ending with a letter or a digit).
    """
    if "name" not in project:
        if "name" in dynamic:
            # PEP 621: the name cannot be dynamic, so the build backend cannot supply it.
            msg = "[project].name: listed in [project].dynamic, but PEP 621 requires a static name"
        else:
            msg = "[project].name: missing"
        raise MetadataError(msg)
    name = project["name"]
    if not isinstance(name, str) or not name:
        msg = f"[project].name: must be a non-empty string, got: {name!r}"
        raise MetadataError(msg)
    if not is_package_name(name):
        msg = (
            "[project].name: not a valid project name (letters, digits, "
            f"'-', '_' and '.', starting and ending with a letter or a digit): {name!r}"
        )
        raise MetadataError(msg)
    return name


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


def _read_version(
    project: dict[str, Any], dynamic: list[str]
) -> tuple[str | None, list[ReportWarning]]:
    """Return ``[project].version``, which must be a valid PEP 440 version
    or dynamic.

    Args:
        project: The ``[project]`` table.
        dynamic: The ``[project].dynamic`` array.

    Returns:
        A tuple ``(version, warnings)``. ``version`` is the version, unchanged, or ``None``
        when the build backend computes it (setuptools-scm, hatch-vcs, ...): ``warnings`` then
        has the ``dynamic-version`` warning, and is empty otherwise.

    Raises:
        MetadataError: If ``version`` is neither set nor dynamic, is not a string, or is not a
            valid PEP 440 version.
    """
    if "version" not in project:
        if "version" not in dynamic:
            msg = "[project].version: missing"
            raise MetadataError(msg)
        warning = ReportWarning(
            "dynamic-version", "[project].version is dynamic, the version output is empty"
        )
        return None, [warning]
    version = check_str(project["version"], "[project].version")
    try:
        Version(version)
    except InvalidVersion as exc:
        msg = f"[project].version: not a valid PEP 440 version: {version!r}"
        raise MetadataError(msg) from exc
    return version, []


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
