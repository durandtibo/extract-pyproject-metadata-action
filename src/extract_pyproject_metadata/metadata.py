"""Extraction of the project metadata (name, version and the other
fields) from the parsed file."""

from __future__ import annotations

import re
from typing import Any

from extract_pyproject_metadata._vendor.packaging.utils import canonicalize_name
from extract_pyproject_metadata._vendor.packaging.version import InvalidVersion, Version
from extract_pyproject_metadata.checks import check_str, check_string_array, get_table
from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.pyproject import read_extra_names, read_group_names
from extract_pyproject_metadata.types import Metadata

__all__ = ["extract_metadata"]

# A project name per PEP 508: letters, digits, "-", "_" and "." that start and end with a
# letter or a digit. Always used with ``fullmatch``.
_VALID_NAME = re.compile(r"[A-Z0-9]|[A-Z0-9][A-Z0-9._-]*[A-Z0-9]", re.IGNORECASE)


def extract_metadata(
    data: dict[str, Any],
    extra_values: list[str],
    pyproject_path: str = "pyproject.toml",
) -> tuple[Metadata, list[str]]:
    """Read the name, version, requires-python, extras and groups from a
    parsed pyproject.toml.

    Args:
        data: The parsed pyproject.toml, as returned by ``load_pyproject``.
        extra_values: Extra values to prepend to the extras read from
            ``[project.optional-dependencies]``, as returned by
            ``parse_string_array``.
        pyproject_path: Path of the file ``data`` was read from, used only in
            error and warning messages.

    Returns:
        A tuple ``(metadata, warnings)``. ``warnings`` lists the warning
        messages (for example when the version is dynamic, or when a field is
        both set and listed in ``dynamic``). ``metadata`` is a ``Metadata`` dict:

        - ``name`` as written, ``normalized_name`` (PEP 503, ``my-package``) and
          ``file_name`` (the name as it is written in the file names of wheels and sdists,
          ``my_package``);
        - ``version`` as written and ``normalized_version`` (the canonical form of PEP 440,
          such as ``1.0rc1`` for ``1.0-RC1``), both empty when ``[project].version`` is
          dynamic and has no static value;
        - ``requires_python``: ``[project].requires-python`` as written (empty if it is not
          declared);
        - ``extras``: the ``extra_values`` first, then the extras sorted by normalized name,
          compared per PEP 685 (spellings of the same extra are duplicates: the first one is
          kept);
        - ``groups``: the names of ``[dependency-groups]`` the same way (sorted by normalized
          name, without duplicates), empty if there is no such table.

    Raises:
        MetadataError: If ``[project]`` is not a table, is missing ``name`` (also
            when ``name`` is listed in ``dynamic``, which PEP 621 forbids) or
            ``version`` (unless the version is dynamic), has a ``dynamic`` that
            is not an array of strings, a ``name`` that is not a non-empty string or not a
            valid PEP 508 name, a ``version`` that is not a string or not a valid PEP 440
            version, a ``requires-python`` that is not a string, or an
            ``optional-dependencies`` or ``dependency-groups`` that is not a table.
    """
    project = get_table(data, "project", "[project]", pyproject_path)
    dynamic = check_string_array(project.get("dynamic", []), "[project].dynamic", pyproject_path)
    raw_name = _required_name(project, dynamic, pyproject_path)
    warnings = _static_and_dynamic_warnings(project, dynamic, pyproject_path)
    raw_version, is_known, version_warnings = _required_version(project, dynamic, pyproject_path)
    warnings.extend(version_warnings)
    name = _valid_name(raw_name, pyproject_path)
    version, normalized_version = _valid_version(raw_version, is_known, pyproject_path)
    requires_python = check_str(
        project.get("requires-python", ""), "[project].requires-python", pyproject_path
    )
    normalized_name = canonicalize_name(name)
    metadata = Metadata(
        name=name,
        normalized_name=normalized_name,
        file_name=normalized_name.replace("-", "_"),
        version=version,
        normalized_version=normalized_version,
        requires_python=requires_python,
        extras=read_extra_names(project, extra_values, pyproject_path),
        groups=read_group_names(data, pyproject_path),
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
    """Describe the fields that are set in ``[project]`` and also listed
    in ``dynamic``.

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
    project: dict[str, Any], dynamic: list[str], pyproject_path: str
) -> tuple[object, bool, list[str]]:
    """Return ``[project].version`` as written, or an empty string if it
    is dynamic.

    Args:
        project: The ``[project]`` table.
        dynamic: The ``[project].dynamic`` array.
        pyproject_path: Path of the file, used in the messages.

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
        msg = f"{pyproject_path} is missing required key [project].version"
        raise MetadataError(msg)
    warnings = [f"{pyproject_path}: [project].version is dynamic, the version output is empty"]
    return "", False, warnings


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
