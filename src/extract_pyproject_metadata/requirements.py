"""Reading, indexing and looking up the requirements of a pyproject.toml:
``[project].dependencies``, the extras and the dependency groups."""

from __future__ import annotations

import functools
from typing import Any, cast

from extract_pyproject_metadata._vendor.packaging.requirements import (
    InvalidRequirement,
    Requirement,
)
from extract_pyproject_metadata._vendor.packaging.utils import canonicalize_name
from extract_pyproject_metadata.checks import check_array, check_string_array, get_table
from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.inputs import PROJECT_SCOPE

__all__ = [
    "candidate_requirements",
    "flatten_group",
    "index_dependencies",
    "requirements_from_index",
    "specifiers_from_index",
]

# Limits that turn a pathological dependency-groups table into an error instead of a Python
# traceback (include-group chain deeper than the recursion limit) or a run that never ends
# (a group that includes the same group twice, 25 levels deep, expands to 2**25 entries).
_MAX_INCLUDE_DEPTH = 100


_MAX_GROUP_EXPANSIONS = 10_000


def _cycle_message(cycle: tuple[str, ...], pyproject_path: str) -> str:
    """Describe an include-group cycle, starting from its smallest group
    name.

    The same cycle is reached from each of its groups: rotating it to a fixed
    starting point gives the same message each time, so it can be deduplicated.
    """
    start = cycle.index(min(cycle))
    ordered = (*cycle[start:], *cycle[:start])
    path = " -> ".join((*ordered, ordered[0]))
    return f"{pyproject_path}: [dependency-groups] has an include-group cycle: {path}"


def flatten_group(  # noqa: C901 (one pass over the include-group tree)
    groups: dict[str, Any],
    name: str,
    seen: tuple[str, ...] = (),
    pyproject_path: str = "pyproject.toml",
    budget: list[int] | None = None,
) -> tuple[list[str], list[str]]:
    """Return requirement strings of a dependency group, expanding
    include-group.

    An ``include-group`` that leads back to a group being expanded is not
    followed again, with a warning (once per cycle). An ``include-group`` that
    names no group is skipped, with a warning.

    Args:
        groups: The ``[dependency-groups]`` table.
        name: The group to expand.
        seen: The (normalized) groups being expanded, outermost first.
        pyproject_path: Path of the file, used in the messages.
        budget: A one-item list with the number of expansions left, shared by the recursive
            calls. ``_MAX_GROUP_EXPANSIONS`` when it is not given.

    Returns:
        A tuple ``(requirements, warnings)``, without duplicate warnings.

    Raises:
        MetadataError: If the ``include-group`` entries are nested deeper than
            ``_MAX_INCLUDE_DEPTH`` or expand more than ``_MAX_GROUP_EXPANSIONS``
            times in total, if a group is not an array, an ``include-group`` value
            is not a string, or an entry is neither a string nor a table whose
            only key is ``include-group`` (for example a typo such as
            ``include_group``).
    """
    key = canonicalize_name(name)
    if key in seen:
        return [], [_cycle_message(seen[seen.index(key) :], pyproject_path)]
    if len(seen) >= _MAX_INCLUDE_DEPTH:
        msg = (
            f"{pyproject_path}: [dependency-groups] include-group entries are nested more than "
            f"{_MAX_INCLUDE_DEPTH} levels deep, at group {name!r}"
        )
        raise MetadataError(msg)
    if budget is None:
        budget = [_MAX_GROUP_EXPANSIONS]
    budget[0] -= 1
    if budget[0] < 0:
        msg = (
            f"{pyproject_path}: [dependency-groups] include-group entries expand more than "
            f"{_MAX_GROUP_EXPANSIONS} groups in total, at group {name!r}: a group is included "
            "several times by several groups"
        )
        raise MetadataError(msg)
    out: list[str] = []
    warnings: list[str] = []
    for gname, entries in groups.items():
        if canonicalize_name(gname) != key:
            continue
        label = f"[dependency-groups].{gname}"
        for entry in check_array(entries, label, pyproject_path):
            if isinstance(entry, str):
                out.append(entry)
            elif isinstance(entry, dict) and set(cast("dict[str, Any]", entry)) == {
                "include-group"
            }:
                included: object = cast("dict[str, Any]", entry)["include-group"]
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
                included_reqs, included_warnings = flatten_group(
                    groups, included, (*seen, key), pyproject_path, budget
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
    """Describe a dependency field that is dynamic, so cannot be
    read."""
    return (
        f"{pyproject_path}: [project].{field} is dynamic, it cannot be read, so no "
        "requirement is found in it"
    )


def _dynamic_dependency_fields(data: dict[str, Any]) -> list[str]:
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
        _dynamic_message(field, pyproject_path) for field in _dynamic_dependency_fields(data)
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

    ``index_dependencies`` parses the requirements of each place twice (all the
    places together, then each place alone): the cache makes each string parsed only once.

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


# One requirement of a package: its specifier, its environment marker (None when there is
# none) and the place that declares it ("project", "extra:<name>" or "group:<name>").
_Entry = tuple[str, str | None, str]


def _index_requirements(
    scoped: list[tuple[str, str]], pyproject_path: str
) -> tuple[dict[str, list[_Entry]], list[str]]:
    """Parse requirement strings and group them by package.

    Args:
        scoped: The ``(scope, requirement)`` pairs, in search order, as returned by
            ``_scoped_requirements``.
        pyproject_path: Path of the file, used in the warning messages.

    Returns:
        A tuple ``(found, warnings)``. ``found`` maps the normalized name of each package
        to the ``(specifier, marker, source)`` of each of its requirements, in order
        (``marker`` is ``None`` when there is none, ``source`` is the scope). ``warnings``
        has one message per requirement that cannot be parsed, which is ignored.
    """
    found: dict[str, list[_Entry]] = {}
    warnings: list[str] = []
    for scope, raw in scoped:
        req = _parse_requirement(raw)
        if isinstance(req, InvalidRequirement):
            warnings.append(f"Ignoring invalid requirement {raw!r} in {pyproject_path}: {req}")
            continue
        marker = None if req.marker is None else str(req.marker)
        found.setdefault(canonicalize_name(req.name), []).append(
            (str(req.specifier), marker, scope)
        )
    return found, warnings


def index_dependencies(
    data: dict[str, Any], pyproject_path: str
) -> tuple[dict[str, list[_Entry]], list[str]]:
    """Index every requirement of the file by package, once for all the
    lookups.

    Args:
        data: The parsed pyproject.toml, as returned by ``load_pyproject``.
        pyproject_path: Path of the file ``data`` was read from, used only in
            error and warning messages.

    Returns:
        A tuple ``(found, warnings)``. ``found`` is the index returned by
        ``_index_requirements`` for the requirements of ``_scoped_requirements``
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
    found, invalid_warnings = _index_requirements(scoped, pyproject_path)
    for scope in dict.fromkeys(scope for scope, _ in scoped):
        in_scope, _ = _index_requirements(
            [(other, raw) for other, raw in scoped if other == scope], pyproject_path
        )
        found.update({f"{key}@{scope}": matches for key, matches in in_scope.items()})
    return found, [*structure_warnings, *invalid_warnings]


def _lookup_key(dependency: str) -> str:
    """Return the key of the index of the requirements for an entry of
    ``dependencies``.

    Args:
        dependency: An entry, as returned by ``parse_inputs``.

    Returns:
        The normalized package name (PEP 503), followed by ``@`` and the normalized scope for
        an entry with a scope, as ``index_dependencies`` stores them.
    """
    name, separator, scope = dependency.partition("@")
    if not separator:
        return canonicalize_name(name)
    kind, colon, scope_name = scope.partition(":")
    return f"{canonicalize_name(name)}@{kind}{colon}{canonicalize_name(scope_name)}"


def specifiers_from_index(
    found: dict[str, list[_Entry]],
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
        A tuple ``(specifiers, warnings)``. ``specifiers`` maps each requested entry, as
        written, to the specifier of the **first** requirement of the search order (the
        environment markers are not evaluated), ``""`` if it has none, or ``None`` if the
        package is not found. ``warnings`` has the ``warnings`` of the index (only when
        ``dependencies`` is not empty) and one message per package that is not found.
    """
    warnings = list(index_warnings) if dependencies else []

    result: dict[str, str | None] = {}
    for dep in dependencies:
        matches = found.get(_lookup_key(dep))
        if not matches:
            result[dep] = None
            warnings.append(f"{pyproject_path}: dependency {dep!r} not found")
            continue
        result[dep] = matches[0][0]
    return result, warnings


def requirements_from_index(
    found: dict[str, list[_Entry]], dependencies: list[str]
) -> dict[str, list[dict[str, str]]]:
    """List the requirements of each requested package in an index of
    the requirements.

    Args:
        found: The index, as returned by ``index_dependencies``.
        dependencies: Package names to look up, with their optional scope.

    Returns:
        A dict that maps each requested entry, as written, to the list of all its
        requirements, in search order (``[project].dependencies``, extras, then dependency
        groups), each a dict with the ``specifier`` (``""`` if there is none), the environment
        ``marker`` (``""`` if there is none) and the ``source`` that declares it (``project``,
        ``extra:<name>`` or ``group:<name>``). The list is empty if the package is not found.
    """
    return {
        dep: [
            {"specifier": specifier, "marker": marker or "", "source": source}
            for specifier, marker, source in found.get(_lookup_key(dep), [])
        ]
        for dep in dependencies
    }
