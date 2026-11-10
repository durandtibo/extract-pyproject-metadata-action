"""Select the Python versions that ``requires-python`` allows."""

from __future__ import annotations

from extract_pyproject_metadata._vendor.packaging.specifiers import InvalidSpecifier, SpecifierSet
from extract_pyproject_metadata.types import ReportWarning

__all__ = [
    "DEFAULT_PYTHON_CANDIDATES",
    "compatible_python_versions",
]

# The Python versions that ``python-candidates`` defaults to (and the default of the input). Add
# the new minor version every October: ``maintenance.yaml`` opens an issue when it is missing.
DEFAULT_PYTHON_CANDIDATES = '["3.11","3.12","3.13","3.14","3.15"]'

# The patch numbers that ``compatible_python_versions`` tries for each "major.minor" candidate: every
# real release (CPython patch numbers stay below 100) and a very late one, for the specifiers that
# have no upper bound.
_PATCH_RELEASES = (*range(100), 9999)


def _version_key(version: str) -> tuple[int, ...]:
    """Return the numbers of a "major.minor" version, to sort versions as numbers."""
    return tuple(int(part) for part in version.split("."))


def compatible_python_versions(
    requires_python: str, candidates: list[str]
) -> tuple[list[str], list[ReportWarning]]:
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

    Returns:
        A tuple ``(versions, warnings)``. ``versions`` are the allowed
        candidates, sorted ascending as numbers (``3.9`` before ``3.10``) and without
        duplicates, whatever the order of ``candidates``: all of them when
        ``requires_python`` is empty, none of them (with a warning) when it is
        not a valid specifier. There is also a warning when ``candidates`` is
        not empty and none of them is allowed, because a job matrix built from
        an empty list is rejected by GitHub.
    """
    candidates = sorted(set(candidates), key=_version_key)
    if not requires_python.strip():
        return candidates, []
    try:
        specifier = SpecifierSet(requires_python)
    except InvalidSpecifier as exc:
        message = (
            "[project].requires-python is not a valid version specifier, "
            f"the python-versions output is empty: {exc}"
        )
        return [], [ReportWarning("invalid-requires-python", message)]
    versions = [
        candidate
        for candidate in candidates
        if any(specifier.contains(f"{candidate}.{patch}") for patch in _PATCH_RELEASES)
    ]
    if candidates and not versions:
        # GitHub rejects a matrix vector without values, far from the cause.
        message = (
            "no python-candidates version satisfies [project].requires-python "
            f"({requires_python!r}): python-versions is empty, and a job "
            "matrix built from it is rejected by GitHub"
        )
        return versions, [ReportWarning("no-python-version", message)]
    return versions, []
