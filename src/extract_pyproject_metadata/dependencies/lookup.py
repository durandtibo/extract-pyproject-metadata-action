"""Lookup of the requested dependencies in the requirements of a
pyproject.toml."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from packaging.utils import canonicalize_name

from extract_pyproject_metadata.dependencies.requirements import (
    PROJECT_SCOPE,
    conflict_warnings,
    index_dependencies,
)
from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.inputs import parse_string_array

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "check_no_missing_dependency",
    "extract_dependency_requirements",
    "extract_dependency_specifiers",
    "parse_dependencies",
    "requirements_from_index",
    "specifiers_from_index",
]


def parse_dependencies(raw: str) -> list[str]:
    """Parse the ``dependencies`` input: a JSON array of package names
    with an optional scope.

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
        if separator and scope != PROJECT_SCOPE and (kind not in {"extra", "group"} or not name):
            msg = (
                f"dependencies entry {entry!r} has an invalid scope: it must be 'project', "
                "'extra:<name>' or 'group:<name>' (for example 'pytest@group:dev')"
            )
            raise MetadataError(msg)
    return entries


def _lookup_key(dependency: str) -> str:
    """Return the key of the index of the requirements for an entry of
    ``dependencies``.

    Args:
        dependency: An entry, as returned by ``parse_dependencies``.

    Returns:
        The normalized package name (PEP 503), followed by ``@`` and the normalized scope for
        an entry with a scope, as ``index_dependencies`` stores them.
    """
    name, separator, scope = dependency.partition("@")
    if not separator:
        return canonicalize_name(name)
    kind, colon, scope_name = scope.partition(":")
    return f"{canonicalize_name(name)}@{kind}{colon}{canonicalize_name(scope_name)}"


def extract_dependency_specifiers(
    data: dict[str, Any],
    dependencies: list[str],
    pyproject_path: str = "pyproject.toml",
) -> tuple[dict[str, str | None], list[str]]:
    """Map each requested package to its specifier string, or None if
    not found.

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
    found, index_warnings = index_dependencies(data, pyproject_path)
    return specifiers_from_index(found, index_warnings, dependencies, pyproject_path)


def specifiers_from_index(
    found: dict[str, list[tuple[str, str | None]]],
    index_warnings: list[str],
    dependencies: list[str],
    pyproject_path: str,
) -> tuple[dict[str, str | None], list[str]]:
    """Look up the specifier of each requested package in an index of
    the requirements.

    Args:
        found: The index, as returned by ``index_dependencies``.
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
        warnings.extend(conflict_warnings(dep, matches, specifier, pyproject_path))
        result[dep] = specifier
    return result, warnings


def extract_dependency_requirements(
    data: dict[str, Any],
    dependencies: list[str],
    pyproject_path: str = "pyproject.toml",
) -> dict[str, list[dict[str, str]]]:
    """Map each requested package to all its requirements, with their
    markers.

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
    found, _ = index_dependencies(data, pyproject_path)
    return requirements_from_index(found, dependencies)


def requirements_from_index(
    found: dict[str, list[tuple[str, str | None]]], dependencies: list[str]
) -> dict[str, list[dict[str, str]]]:
    """List the requirements of each requested package in an index of
    the requirements.

    Args:
        found: The index, as returned by ``index_dependencies``.
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
            ``dynamic_dependency_fields``. The error message points them out,
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
