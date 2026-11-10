"""Select the Python versions that ``requires-python`` allows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from extract_pyproject_metadata._vendor.packaging.specifiers import InvalidSpecifier, SpecifierSet

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "compatible_python_versions",
    "highest_python_version",
    "lowest_python_version",
]

# The patch numbers that ``compatible_python_versions`` tries for each "major.minor" candidate: every
# real release (CPython patch numbers stay below 100) and a very late one, for the specifiers that
# have no upper bound.
_PATCH_RELEASES = (*range(100), 9999)


def compatible_python_versions(
    requires_python: str, candidates: list[str], pyproject_path: str = "pyproject.toml"
) -> tuple[list[str], list[str]]:
    """Select the candidate Python versions that ``requires-python``
    allows.

    A "major.minor" candidate is allowed when some release of it can satisfy the
    specifier. This is checked on each ``X.Y.0`` to ``X.Y.99`` (CPython patch
    numbers stay below 100) and on a very late one (``X.Y.9999``), so
    ``>=3.10.2`` and ``<3.12.5`` allow ``3.10`` and ``3.12``, and ``==3.12.3``
    allows ``3.12`` only. A patch number of 100 or more that a specifier names
    exactly (``==3.12.150``) matches no release, so the candidate is not
    allowed; ``>=3.12.150`` is, as it has no upper bound.

    Args:
        requires_python: ``[project].requires-python`` as written, or an empty
            string if it is not declared.
        candidates: The "major.minor" versions to choose from, as returned by
            ``parse_inputs``.
        pyproject_path: Path of the file, used in the warning message.

    Returns:
        A tuple ``(versions, warnings)``. ``versions`` are the allowed
        candidates, in the order of ``candidates``: all of them when
        ``requires_python`` is empty, none of them (with a warning) when it is
        not a valid specifier. There is also a warning when ``candidates`` is
        not empty and none of them is allowed, because a job matrix built from
        an empty list is rejected by GitHub.
    """
    if not requires_python.strip():
        return list(candidates), []
    try:
        specifier = SpecifierSet(requires_python)
    except InvalidSpecifier as exc:
        warning = (
            f"{pyproject_path}: [project].requires-python is not a valid version specifier, "
            f"the python-versions output is empty: {exc}"
        )
        return [], [warning]
    versions = [
        candidate
        for candidate in candidates
        if any(specifier.contains(f"{candidate}.{patch}") for patch in _PATCH_RELEASES)
    ]
    if candidates and not versions:
        # GitHub rejects a matrix vector without values, far from the cause.
        warning = (
            f"{pyproject_path}: no python-candidates version satisfies [project].requires-python "
            f"({requires_python!r}): python-versions is empty, and a job "
            "matrix built from it is rejected by GitHub"
        )
        return versions, [warning]
    return versions, []


def _minor_version_key(version: str) -> tuple[int, ...]:
    """Return the numbers of a "major.minor" version, to compare
    versions as numbers."""
    return tuple(int(part) for part in version.split("."))


def lowest_python_version(versions: Sequence[str]) -> str:
    """Return the lowest of "major.minor" versions, compared as numbers.

    Args:
        versions: Versions such as ``"3.9"`` and ``"3.10"``, as returned by
            ``compatible_python_versions``.

    Returns:
        The lowest version (``"3.9"`` is lower than ``"3.10"``), or an empty
        string if ``versions`` is empty.
    """
    if not versions:
        return ""
    return min(versions, key=_minor_version_key)


def highest_python_version(versions: Sequence[str]) -> str:
    """Return the highest of "major.minor" versions, compared as
    numbers.

    Args:
        versions: Versions such as ``"3.9"`` and ``"3.10"``, as returned by
            ``compatible_python_versions``.

    Returns:
        The highest version (``"3.10"`` is higher than ``"3.9"``), or an empty
        string if ``versions`` is empty.
    """
    if not versions:
        return ""
    return max(versions, key=_minor_version_key)
