"""Reading and looking up the requirements of a pyproject.toml:
``[project].dependencies``, the extras and the dependency groups."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from extract_pyproject_metadata._vendor.packaging import requirements as pep508
from extract_pyproject_metadata._vendor.packaging.utils import canonicalize_name
from extract_pyproject_metadata.checks import check_array, check_string_array, get_table, is_table
from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.inputs import PROJECT_SCOPE
from extract_pyproject_metadata.pyproject import read_groups
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


@dataclass
class _Expansion:
    """The expansion of the ``include-group`` entries of one group.

    Attributes:
        groups: The table read by ``read_groups``.
        warnings: The warnings of the expansion, in the order they are found, without
            duplicates (the keys of a dict, which keeps the insertion order).
        budget: The number of expansions left, shared by the included groups.
    """

    groups: dict[str, list[tuple[str, object]]]
    warnings: dict[ReportWarning, None] = field(default_factory=dict[ReportWarning, None])
    budget: int = _MAX_GROUP_EXPANSIONS

    def expand(self, name: str, path: tuple[str, ...] = ()) -> list[str]:
        """Return the requirement strings of a group, ``include-group``
        expanded.

        An ``include-group`` that leads back to a group being expanded is not followed again,
        with a warning (once per cycle). An ``include-group`` that names no group is skipped,
        with a warning.

        Args:
            name: The group to expand, as written.
            path: The (normalized) groups being expanded, outermost first.

        Returns:
            The requirement strings; the warnings are in ``warnings``.

        Raises:
            MetadataError: If the ``include-group`` entries are nested deeper than
                ``_MAX_INCLUDE_DEPTH`` or expand more than ``_MAX_GROUP_EXPANSIONS`` times in
                total, if a group is not an array, an ``include-group`` value is not a string,
                or an entry is neither a string nor a table whose only key is
                ``include-group`` (for example a typo such as ``include_group``).
        """
        key = canonicalize_name(name)
        if key in path:
            self.warnings[_cycle_warning(path[path.index(key) :])] = None
            return []
        self._enter(name, path)
        out: list[str] = []
        for spelling, value in self.groups.get(key, []):
            label = f"[dependency-groups].{spelling}"
            for entry in check_array(value, label):
                if isinstance(entry, str):
                    out.append(entry)
                elif is_table(entry) and set(entry) == {"include-group"}:
                    out.extend(self._include(label, entry["include-group"], (*path, key)))
                else:
                    msg = (
                        f"{label}: entries must be strings or "
                        f"{{'include-group': <name>}} tables, got: {entry!r}"
                    )
                    raise MetadataError(msg)
        return out

    def _enter(self, name: str, path: tuple[str, ...]) -> None:
        """Count the expansion of a group, and check the limits.

        Raises:
            MetadataError: If ``path`` is already ``_MAX_INCLUDE_DEPTH`` groups deep or the
                budget is spent.
        """
        if len(path) >= _MAX_INCLUDE_DEPTH:
            msg = (
                "[dependency-groups]: include-group entries are nested more than "
                f"{_MAX_INCLUDE_DEPTH} levels deep, at group {name!r}"
            )
            raise MetadataError(msg)
        self.budget -= 1
        if self.budget < 0:
            msg = (
                "[dependency-groups]: include-group entries expand more than "
                f"{_MAX_GROUP_EXPANSIONS} groups in total, at group {name!r}: a group is "
                "included several times by several groups"
            )
            raise MetadataError(msg)

    def _include(self, label: str, included: object, path: tuple[str, ...]) -> list[str]:
        """Expand the group of an ``{"include-group": ...}`` entry.

        Args:
            label: The group that holds the entry, such as ``[dependency-groups].dev``.
            included: The value of ``include-group``.
            path: The (normalized) groups being expanded, outermost first.

        Returns:
            The requirement strings of the included group.

        Raises:
            MetadataError: If ``included`` is not a string, or the expansion fails.
        """
        if not isinstance(included, str):
            msg = f"{label}: include-group must be a string, got: {included!r}"
            raise MetadataError(msg)
        if canonicalize_name(included) not in self.groups:
            self.warnings[
                ReportWarning(
                    "unknown-include-group",
                    f"{label}: include-group {included!r} does not match any group",
                )
            ] = None
        return self.expand(included, path)


def flatten_group(groups: dict[str, Any], name: str) -> tuple[list[str], list[ReportWarning]]:
    """Return requirement strings of a dependency group, expanding
    include-group.

    Args:
        groups: The ``[dependency-groups]`` table.
        name: The group to expand.

    Returns:
        A tuple ``(requirements, warnings)``, without duplicate warnings.

    Raises:
        MetadataError: See ``_Expansion.expand``.
    """
    expansion = _Expansion(read_groups(groups))
    requirements = expansion.expand(name)
    return requirements, list(expansion.warnings)


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
    # read_groups merges the spellings of a group name (PEP 503), so each group is expanded
    # once, from the first spelling: expanding each spelling would repeat its requirements.
    table = read_groups(groups)
    for key, spellings in table.items():
        expansion = _Expansion(table)
        reqs.extend((f"group:{key}", raw) for raw in expansion.expand(spellings[0][0]))
        warnings.extend(expansion.warnings)
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
