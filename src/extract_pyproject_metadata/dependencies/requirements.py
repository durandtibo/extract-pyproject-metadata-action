"""Reading and parsing of the requirements of a pyproject.toml."""

from __future__ import annotations

import functools
from typing import Any, cast

from extract_pyproject_metadata._vendor.packaging.requirements import (
    InvalidRequirement,
    Requirement,
)
from extract_pyproject_metadata._vendor.packaging.utils import canonicalize_name
from extract_pyproject_metadata.checks import check_string_array, get_table
from extract_pyproject_metadata.dependencies.groups import flatten_group
from extract_pyproject_metadata.inputs import PROJECT_SCOPE

__all__ = [
    "candidate_requirements",
    "conflict_warnings",
    "dynamic_dependency_fields",
    "extract_project_dependencies",
    "index_dependencies",
]


def _dynamic_message(field: str, pyproject_path: str) -> str:
    """Describe a dependency field that is dynamic, so cannot be
    read."""
    return (
        f"{pyproject_path}: [project].{field} is dynamic, it cannot be read, so no "
        "requirement is found in it"
    )


def dynamic_dependency_fields(data: dict[str, Any]) -> list[str]:
    """Return the dependency fields that only the build backend can
    provide.

    A field is returned when it is listed in ``[project].dynamic`` and
    has no static value in ``[project]``. Only ``dependencies`` and
    ``optional-dependencies`` are checked, in this order.
    """
    project: object = data.get("project", {})
    if not isinstance(project, dict):
        return []
    table = cast("dict[str, Any]", project)
    dynamic: object = table.get("dynamic", [])
    if not isinstance(dynamic, list):
        return []
    return [
        field
        for field in ("dependencies", "optional-dependencies")
        if field in dynamic and field not in table
    ]


def candidate_requirements(
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
    """All requirement strings with the place they are declared in, in
    search order.

    Returns:
        A tuple ``(requirements, warnings)``, as for ``candidate_requirements``.
        Each requirement is a tuple ``(scope, requirement)``. ``scope`` is
        ``"project"`` for ``[project].dependencies``, ``"extra:<name>"`` for an extra
        and ``"group:<name>"`` for a dependency group (the requirements that its
        ``include-group`` entries add included), with the name normalized per PEP 503.
        Spellings of the same name share one scope.

    Raises:
        MetadataError: Under the same conditions as ``candidate_requirements``.
    """
    project = get_table(data, "project", "[project]", pyproject_path)
    reqs = [
        (PROJECT_SCOPE, raw)
        for raw in check_string_array(
            project.get("dependencies", []), "[project].dependencies", pyproject_path
        )
    ]
    optional_dependencies = get_table(
        project, "optional-dependencies", "[project].optional-dependencies", pyproject_path
    )
    for extra, extra_reqs in optional_dependencies.items():
        label = f"[project.optional-dependencies].{extra}"
        scope = f"extra:{canonicalize_name(extra)}"
        reqs.extend((scope, raw) for raw in check_string_array(extra_reqs, label, pyproject_path))
    groups = get_table(data, "dependency-groups", "[dependency-groups]", pyproject_path)
    warnings = [
        _dynamic_message(field, pyproject_path) for field in dynamic_dependency_fields(data)
    ]
    # flatten_group reads every spelling of a group name (PEP 503), so each group is expanded
    # once, from the first spelling: expanding each spelling would repeat its requirements.
    first_spellings: dict[str, str] = {}
    for group in groups:
        first_spellings.setdefault(canonicalize_name(group), group)
    for gname in first_spellings.values():
        group_reqs, group_warnings = flatten_group(groups, gname, pyproject_path=pyproject_path)
        scope = f"group:{canonicalize_name(gname)}"
        reqs.extend((scope, raw) for raw in group_reqs)
        warnings.extend(group_warnings)
    return reqs, list(dict.fromkeys(warnings))


@functools.cache
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
    project = get_table(data, "project", "[project]", pyproject_path)
    entries = check_string_array(
        project.get("dependencies", []), "[project].dependencies", pyproject_path
    )
    found, names, warnings = _index_requirements(entries, pyproject_path)
    if "dependencies" in dynamic_dependency_fields(data):
        warnings.append(_dynamic_message("dependencies", pyproject_path))
    dependencies: dict[str, str] = {}
    for key, matches in found.items():
        specifier = matches[0][0]
        dependencies[names[key]] = specifier
        warnings.extend(conflict_warnings(names[key], matches, specifier, pyproject_path))
    return dependencies, warnings


def index_dependencies(
    data: dict[str, Any], pyproject_path: str
) -> tuple[dict[str, list[tuple[str, str | None]]], list[str]]:
    """Index every requirement of the file by package, once for all the
    lookups.

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


def conflict_warnings(
    dep: str, matches: list[tuple[str, str | None]], used: str, pyproject_path: str
) -> list[str]:
    """Describe the requirements of ``dep`` that disagree on the
    specifier.

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
    messages: list[str] = []
    for marker, specs in by_marker.items():
        if len(specs) > 1:
            where = "" if marker is None else f" for marker {marker!r}"
            messages.append(
                f"{dep} has different specifiers{where} in {pyproject_path}: "
                f"{sorted(specs)}; using {used!r}"
            )
    return messages
