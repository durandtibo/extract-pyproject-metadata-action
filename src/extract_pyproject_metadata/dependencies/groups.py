"""Expansion of the ``include-group`` entries of ``[dependency-
groups]``."""

from __future__ import annotations

from typing import Any

from packaging.utils import canonicalize_name

from extract_pyproject_metadata.checks import check_array
from extract_pyproject_metadata.errors import MetadataError

__all__ = ["flatten_group"]

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
