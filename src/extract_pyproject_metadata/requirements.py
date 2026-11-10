"""Reading and looking up the requirements of a pyproject.toml:
``[project].dependencies``, the extras and the dependency groups."""

from __future__ import annotations

from typing import Any, cast

from extract_pyproject_metadata._vendor.packaging import requirements as pep508
from extract_pyproject_metadata._vendor.packaging.utils import canonicalize_name
from extract_pyproject_metadata.checks import check_array, check_string_array, get_table
from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.inputs import PROJECT_SCOPE
from extract_pyproject_metadata.types import Lookup, ReportWarning, Requirement

__all__ = [
    "collect_requirements",
    "find_requirements",
    "flatten_group",
    "lookup_requirements",
    "lookup_specifiers",
]

# Limits that turn a pathological dependency-groups table into an error instead of a Python
# traceback (include-group chain deeper than the recursion limit) or a run that never ends
# (a group that includes the same group twice, 25 levels deep, expands to 2**25 entries).
_MAX_INCLUDE_DEPTH = 100


_MAX_GROUP_EXPANSIONS = 10_000


def _cycle_warning(cycle: tuple[str, ...]) -> ReportWarning:
    """Describe an include-group cycle, starting from its smallest group
    name.

    The same cycle is reached from each of its groups: rotating it to a fixed
    starting point gives the same message each time, so it can be deduplicated.
    """
    start = cycle.index(min(cycle))
    ordered = (*cycle[start:], *cycle[:start])
    path = " -> ".join((*ordered, ordered[0]))
    return ReportWarning(
        "include-group-cycle", f"[dependency-groups] has an include-group cycle: {path}"
    )


def flatten_group(  # noqa: C901 (one pass over the include-group tree)
    groups: dict[str, Any],
    name: str,
    seen: tuple[str, ...] = (),
    budget: list[int] | None = None,
) -> tuple[list[str], list[ReportWarning]]:
    """Return requirement strings of a dependency group, expanding
    include-group.

    An ``include-group`` that leads back to a group being expanded is not
    followed again, with a warning (once per cycle). An ``include-group`` that
    names no group is skipped, with a warning.

    Args:
        groups: The ``[dependency-groups]`` table.
        name: The group to expand.
        seen: The (normalized) groups being expanded, outermost first.
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
        return [], [_cycle_warning(seen[seen.index(key) :])]
    if len(seen) >= _MAX_INCLUDE_DEPTH:
        msg = (
            "[dependency-groups]: include-group entries are nested more than "
            f"{_MAX_INCLUDE_DEPTH} levels deep, at group {name!r}"
        )
        raise MetadataError(msg)
    if budget is None:
        budget = [_MAX_GROUP_EXPANSIONS]
    budget[0] -= 1
    if budget[0] < 0:
        msg = (
            "[dependency-groups]: include-group entries expand more than "
            f"{_MAX_GROUP_EXPANSIONS} groups in total, at group {name!r}: a group is included "
            "several times by several groups"
        )
        raise MetadataError(msg)
    out: list[str] = []
    warnings: list[ReportWarning] = []
    for gname, entries in groups.items():
        if canonicalize_name(gname) != key:
            continue
        label = f"[dependency-groups].{gname}"
        for entry in check_array(entries, label):
            if isinstance(entry, str):
                out.append(entry)
            elif isinstance(entry, dict) and set(cast("dict[str, Any]", entry)) == {
                "include-group"
            }:
                included: object = cast("dict[str, Any]", entry)["include-group"]
                if not isinstance(included, str):
                    msg = f"{label}: include-group must be a string, got: {included!r}"
                    raise MetadataError(msg)
                if not any(
                    canonicalize_name(group) == canonicalize_name(included) for group in groups
                ):
                    warnings.append(
                        ReportWarning(
                            "unknown-include-group",
                            f"{label}: include-group {included!r} does not match any group",
                        )
                    )
                included_reqs, included_warnings = flatten_group(
                    groups, included, (*seen, key), budget
                )
                out.extend(included_reqs)
                warnings.extend(included_warnings)
            else:
                msg = (
                    f"{label}: entries must be strings or "
                    f"{{'include-group': <name>}} tables, got: {entry!r}"
                )
                raise MetadataError(msg)
    return out, list(dict.fromkeys(warnings))


def _dynamic_warning(field: str) -> ReportWarning:
    """Describe a dependency field that is dynamic, so cannot be
    read."""
    return ReportWarning(
        "dynamic-dependencies",
        f"[project].{field} is dynamic, it cannot be read, so no requirement is found in it",
    )


def _gather(
    data: dict[str, Any], dynamic: frozenset[str]
) -> tuple[list[tuple[str, str]], list[ReportWarning]]:
    """All requirement strings with the place they are declared in, in
    search order.

    Args:
        data: The parsed pyproject.toml.
        dynamic: The fields of ``[project].dynamic``, as read by ``read_project``.

    Returns:
        A tuple ``(requirements, warnings)``. ``warnings`` has one message per dependency
        field that is dynamic (the build backend computes it, so it cannot be read), per
        include-group cycle and per ``include-group`` that names no group. Each requirement
        is a tuple ``(scope, requirement)``. ``scope`` is ``"project"`` for
        ``[project].dependencies``, ``"extra:<name>"`` for an extra and ``"group:<name>"``
        for a dependency group (the requirements that its ``include-group`` entries add
        included), with the name normalized per PEP 503. Spellings of the same name share
        one scope.

    Raises:
        MetadataError: If ``[project]``, ``[project].dependencies``,
            ``[project.optional-dependencies]``, ``[dependency-groups]`` or one
            of their values has the wrong type, or if a requirement of
            ``[project].dependencies`` or of an extra is not a string.
    """
    project = get_table(data, "project", "[project]")
    reqs = [
        (PROJECT_SCOPE, raw)
        for raw in check_string_array(project.get("dependencies", []), "[project].dependencies")
    ]
    optional_dependencies = get_table(
        project, "optional-dependencies", "[project].optional-dependencies"
    )
    for extra, extra_reqs in optional_dependencies.items():
        label = f"[project.optional-dependencies].{extra}"
        scope = f"extra:{canonicalize_name(extra)}"
        reqs.extend((scope, raw) for raw in check_string_array(extra_reqs, label))
    groups = get_table(data, "dependency-groups", "[dependency-groups]")
    warnings = [
        _dynamic_warning(field)
        for field in ("dependencies", "optional-dependencies")
        if field in dynamic and field not in project
    ]
    # flatten_group reads every spelling of a group name (PEP 503), so each group is expanded
    # once, from the first spelling: expanding each spelling would repeat its requirements.
    first_spellings: dict[str, str] = {}
    for group in groups:
        first_spellings.setdefault(canonicalize_name(group), group)
    for gname in first_spellings.values():
        group_reqs, group_warnings = flatten_group(groups, gname)
        scope = f"group:{canonicalize_name(gname)}"
        reqs.extend((scope, raw) for raw in group_reqs)
        warnings.extend(group_warnings)
    return reqs, warnings


def collect_requirements(
    data: dict[str, Any], dynamic: frozenset[str]
) -> tuple[list[Requirement], list[ReportWarning]]:
    """Read and parse every requirement of the file, in search order.

    The order is ``[project].dependencies``, then each extra (file order), then each
    dependency group (file order, ``include-group`` expanded).

    Args:
        data: The parsed pyproject.toml, as returned by ``load_pyproject``.
        dynamic: The fields of ``[project].dynamic``, as read by ``read_project``.

    Returns:
        A tuple ``(requirements, warnings)``. ``warnings`` lists the dynamic dependency fields,
        the include-group problems (without duplicates) and one message per requirement string
        that cannot be parsed, which is skipped.

    Raises:
        MetadataError: If a table or a value has the wrong type, or an include-group limit is
            exceeded (see ``_gather`` and ``flatten_group``).
    """
    scoped, warnings = _gather(data, dynamic)
    warnings = list(dict.fromkeys(warnings))
    requirements: list[Requirement] = []
    for scope, raw in scoped:
        try:
            parsed = pep508.Requirement(raw)
        except pep508.InvalidRequirement as exc:
            warnings.append(
                ReportWarning("invalid-requirement", f"Ignoring invalid requirement {raw!r}: {exc}")
            )
            continue
        requirements.append(
            Requirement(
                name=canonicalize_name(parsed.name),
                specifier=str(parsed.specifier),
                marker="" if parsed.marker is None else str(parsed.marker),
                source=scope,
            )
        )
    return requirements, warnings


def find_requirements(requirements: list[Requirement], lookup: Lookup) -> list[Requirement]:
    """Return the requirements of the package of ``lookup``, in search
    order.

    Args:
        requirements: The requirements, as returned by ``collect_requirements``.
        lookup: The entry to look up.

    Returns:
        The requirements of that package in the place of the entry (everywhere when it has
        none); empty if the package is not found.
    """
    return [
        req
        for req in requirements
        if req.name == lookup.name and lookup.source in {None, req.source}
    ]


def lookup_specifiers(
    requirements: list[Requirement], lookups: list[Lookup]
) -> tuple[dict[str, str | None], list[ReportWarning]]:
    """Look up the specifier of each requested package.

    Args:
        requirements: The requirements, as returned by ``collect_requirements``.
        lookups: The entries to look up.

    Returns:
        A tuple ``(specifiers, warnings)``. ``specifiers`` maps each entry, as written, to the
        specifier of the **first** requirement of the search order (the environment markers
        are not evaluated), ``""`` if it has none, or ``None`` if the package is not found.
        ``warnings`` has one message per package that is not found.
    """
    result: dict[str, str | None] = {}
    warnings: list[ReportWarning] = []
    for lookup in lookups:
        matches = find_requirements(requirements, lookup)
        if not matches:
            result[lookup.text] = None
            warnings.append(
                ReportWarning("dependency-not-found", f"dependency {lookup.text!r} not found")
            )
            continue
        result[lookup.text] = matches[0].specifier
    return result, warnings


def lookup_requirements(
    requirements: list[Requirement], lookups: list[Lookup]
) -> dict[str, list[dict[str, str]]]:
    """List the requirements of each requested package.

    Args:
        requirements: The requirements, as returned by ``collect_requirements``.
        lookups: The entries to look up.

    Returns:
        A dict that maps each entry, as written, to the list of all its requirements, in search
        order, each a dict with the ``specifier`` (``""`` if there is none), the environment
        ``marker`` (``""`` if there is none) and the ``source`` that declares it (``project``,
        ``extra:<name>`` or ``group:<name>``). The list is empty if the package is not found.
    """
    return {
        lookup.text: [
            {"specifier": req.specifier, "marker": req.marker, "source": req.source}
            for req in find_requirements(requirements, lookup)
        ]
        for lookup in lookups
    }
