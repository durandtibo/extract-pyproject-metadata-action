r"""Extract project name, version, and optional-dependency extras from a pyproject.toml.

Usage:
    extract_metadata.py <pyproject-path> <extra-values-json>

Prints a single JSON object to stdout:
    {"name": ..., "version": ..., "extras": [...]}

Exits non-zero with a message on stderr if the file is missing, is not
valid TOML, or [project] is missing the required "name"/"version" keys.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib  # type: ignore[no-redef]


class MetadataError(Exception):
    """Raised when pyproject.toml cannot be read or is missing required metadata."""


def extract_metadata(pyproject_path: str, extra_values_json: str) -> dict:
    """Read name, version, and sorted extras from a pyproject.toml file.

    Args:
        pyproject_path: Path to the pyproject.toml file.
        extra_values_json: JSON array of extra values to prepend to the
            extras read from ``[project.optional-dependencies]``.

    Returns:
        A dict with keys ``name``, ``version``, and ``extras``.

    Raises:
        MetadataError: If the file is missing, is not valid TOML, or
            ``[project]`` is missing ``name`` or ``version``.
    """
    path = Path(pyproject_path)
    if not path.is_file():
        msg = f"pyproject.toml not found at: {pyproject_path}"
        raise MetadataError(msg)

    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        msg = f"{pyproject_path} is not valid TOML: {exc}"
        raise MetadataError(msg) from exc

    project = data.get("project", {})
    try:
        name = project["name"]
        version = project["version"]
    except KeyError as exc:
        msg = f"{pyproject_path} is missing required key [project].{exc.args[0]}"
        raise MetadataError(msg) from exc

    extras = sorted(project.get("optional-dependencies", {}).keys())

    try:
        extra_values = json.loads(extra_values_json)
    except json.JSONDecodeError as exc:
        msg = f"extra-values is not valid JSON: {extra_values_json!r}"
        raise MetadataError(msg) from exc

    if not isinstance(extra_values, list):
        msg = f"extra-values must be a JSON array, got: {extra_values_json!r}"
        raise MetadataError(msg)

    return {"name": name, "version": version, "extras": extra_values + extras}


def _load(pyproject_path: str) -> dict:
    path = Path(pyproject_path)
    if not path.is_file():
        msg = f"pyproject.toml not found at: {pyproject_path}"
        raise MetadataError(msg)
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        msg = f"{pyproject_path} is not valid TOML: {exc}"
        raise MetadataError(msg) from exc


def _parse_dependencies(dependencies_json: str) -> list[str]:
    try:
        deps = json.loads(dependencies_json)
    except json.JSONDecodeError as exc:
        msg = f"dependencies is not valid JSON: {dependencies_json!r}"
        raise MetadataError(msg) from exc
    if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
        msg = f"dependencies must be a JSON array of strings, got: {dependencies_json!r}"
        raise MetadataError(msg)
    return deps


def _flatten_group(groups: dict, name: str, seen: tuple[str, ...] = ()) -> list[str]:
    """Return requirement strings of a dependency group, expanding include-group."""
    key = canonicalize_name(name)
    if key in seen:
        return []
    out: list[str] = []
    for gname, entries in groups.items():
        if canonicalize_name(gname) != key:
            continue
        for entry in entries:
            if isinstance(entry, str):
                out.append(entry)
            elif isinstance(entry, dict) and "include-group" in entry:
                out.extend(_flatten_group(groups, entry["include-group"], (*seen, key)))
    return out


def _candidate_requirements(data: dict) -> list[str]:
    """All requirement strings, in search order."""
    project = data.get("project", {})
    reqs = [r for r in project.get("dependencies", []) if isinstance(r, str)]
    for extra_reqs in project.get("optional-dependencies", {}).values():
        reqs.extend(r for r in extra_reqs if isinstance(r, str))
    groups = data.get("dependency-groups", {})
    for gname in groups:
        reqs.extend(_flatten_group(groups, gname))
    return reqs


def extract_dependency_specifiers(pyproject_path: str, dependencies_json: str) -> dict:
    """Map each requested package to its specifier string, or None if not found."""
    deps = _parse_dependencies(dependencies_json)
    data = _load(pyproject_path)
    found: dict[str, list[str]] = {}
    for raw in _candidate_requirements(data):
        try:
            req = Requirement(raw)
        except InvalidRequirement:
            continue
        found.setdefault(canonicalize_name(req.name), []).append(str(req.specifier))

    result: dict = {}
    for dep in deps:
        specs = found.get(canonicalize_name(dep))
        if not specs:
            result[dep] = None
            continue
        if len(set(specs)) > 1:
            print(
                f"::warning::{dep} has different specifiers in {pyproject_path}: "
                f"{sorted(set(specs))}; using {specs[0]!r}",
                file=sys.stderr,
            )
        result[dep] = specs[0]
    return result


def main(argv: list[str]) -> int:
    if len(argv) not in (3, 4):
        print(
            f"Usage: {argv[0]} <pyproject-path> <extra-values-json> [<dependencies-json>]",
            file=sys.stderr,
        )
        return 2

    try:
        metadata = extract_metadata(argv[1], argv[2])
        metadata["dependency_specifiers"] = extract_dependency_specifiers(
            argv[1], argv[3] if len(argv) == 4 else "[]"
        )
    except MetadataError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(metadata))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
