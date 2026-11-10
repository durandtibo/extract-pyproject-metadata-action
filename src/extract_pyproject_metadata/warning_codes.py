"""The documentation of the warning codes: when each is reported and what
the action does then."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from extract_pyproject_metadata.types import WarningCode

__all__ = ["WARNING_CODES"]

# Each code of ``types.WarningCode`` with the case that raises it and its effect. The tables of
# the README are generated from this one (``make docs``).
WARNING_CODES: dict[WarningCode, tuple[str, str]] = {
    "static-and-dynamic": (
        "A field of `[project]` has a value and is also in `dynamic` (forbidden by PEP 621).",
        "The static value is used.",
    ),
    "dynamic-version": (
        "`version` is in `dynamic` and not set.",
        "`version` and `normalized-version` are empty.",
    ),
    "invalid-requires-python": (
        "`requires-python` is not a valid version specifier.",
        "`python-versions` is empty.",
    ),
    "no-python-version": (
        "No version of `python-candidates` is allowed by `requires-python`.",
        "`python-versions` is empty.",
    ),
    "invalid-requirement": (
        (
            "A requirement string of `[project].dependencies`, an extra or a group cannot be "
            "parsed (only when `dependencies` is not empty)."
        ),
        "The requirement is skipped.",
    ),
    "include-group-cycle": (
        (
            "The `include-group` entries of `[dependency-groups]` include each other in a loop "
            "(only when `dependencies` is not empty)."
        ),
        "The loop is not followed.",
    ),
    "unknown-include-group": (
        (
            "An `include-group` names a group that does not exist (only when `dependencies` is "
            "not empty)."
        ),
        "The entry is skipped.",
    ),
    "dynamic-dependencies": (
        (
            "`dependencies` or `optional-dependencies` is in `dynamic` and not set (only when "
            "`dependencies` is not empty)."
        ),
        "No requirement is found in it.",
    ),
    "dependency-not-found": (
        "A package of `dependencies` is not in the place(s) searched.",
        "Its specifier is `null`.",
    ),
}
