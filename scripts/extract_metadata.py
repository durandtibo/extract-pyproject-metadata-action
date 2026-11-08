r"""Extract project name, version, and optional-dependency extras from a pyproject.toml.

Usage:
    extract_metadata.py <pyproject-path> <extra-values-json> [<dependencies-json>]

Prints a single JSON object to stdout:
    {"name": ..., "version": ..., "extras": [...], "dependency_specifiers": {...},
     "warnings": [...]}

"warnings" lists human-readable messages about suspicious but non-fatal
input. They are not printed to stderr here: the caller (action.yaml) turns
them into ``::warning::`` annotations, which GitHub only parses on stdout.

Exits non-zero with a message on stderr if the file is missing, is not
valid TOML, [project] is missing the required "name"/"version" keys, or an
input is not valid JSON of the expected shape.
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


def load_pyproject(pyproject_path: str) -> dict:
    """Read and parse a pyproject.toml file.

    Args:
        pyproject_path: Path to the pyproject.toml file.

    Returns:
        The parsed TOML document.

    Raises:
        MetadataError: If the file is missing or is not valid TOML.
    """
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


def extract_metadata(
    data: dict, extra_values_json: str, pyproject_path: str = "pyproject.toml"
) -> dict:
    """Read name, version, and sorted extras from a parsed pyproject.toml.

    Args:
        data: The parsed pyproject.toml, as returned by ``load_pyproject``.
        extra_values_json: JSON array of extra values to prepend to the
            extras read from ``[project.optional-dependencies]``.
        pyproject_path: Path of the file ``data`` was read from, used only in
            error messages.

    Returns:
        A dict with keys ``name``, ``version``, and ``extras``. ``extras``
        lists the ``extra_values`` first, then the sorted extras, without
        duplicates.

    Raises:
        MetadataError: If ``[project]`` is not a table, is missing ``name`` or
            ``version``, has a ``name`` that is not a non-empty string, a
            ``version`` that is not a string or an ``optional-dependencies``
            that is not a table, or ``extra_values_json`` is not a JSON array
            of strings.
    """
    project = data.get("project", {})
    if not isinstance(project, dict):
        msg = f"{pyproject_path}: [project] must be a table, got: {project!r}"
        raise MetadataError(msg)
    try:
        name = project["name"]
        version = project["version"]
    except KeyError as exc:
        msg = f"{pyproject_path} is missing required key [project].{exc.args[0]}"
        raise MetadataError(msg) from exc
    if not isinstance(name, str) or not name:
        msg = f"{pyproject_path}: [project].name must be a non-empty string, got: {name!r}"
        raise MetadataError(msg)
    if not isinstance(version, str):
        msg = f"{pyproject_path}: [project].version must be a string, got: {version!r}"
        raise MetadataError(msg)

    optional_dependencies = project.get("optional-dependencies", {})
    if not isinstance(optional_dependencies, dict):
        msg = (
            f"{pyproject_path}: [project].optional-dependencies must be a table, "
            f"got: {optional_dependencies!r}"
        )
        raise MetadataError(msg)
    extras = sorted(optional_dependencies)

    try:
        extra_values = json.loads(extra_values_json)
    except json.JSONDecodeError as exc:
        msg = f"extra-values is not valid JSON: {extra_values_json!r}"
        raise MetadataError(msg) from exc

    if not isinstance(extra_values, list):
        msg = f"extra-values must be a JSON array, got: {extra_values_json!r}"
        raise MetadataError(msg)
    if not all(isinstance(value, str) for value in extra_values):
        msg = f"extra-values must be a JSON array of strings, got: {extra_values_json!r}"
        raise MetadataError(msg)

    # dict.fromkeys removes duplicates and keeps the first occurrence's position.
    return {
        "name": name,
        "version": version,
        "extras": list(dict.fromkeys(extra_values + extras)),
    }


def _parse_dependencies(dependencies_json: str) -> list[str]:
    """Parse the ``dependencies`` input into a list of package names."""
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


def extract_dependency_specifiers(
    data: dict,
    dependencies_json: str,
    pyproject_path: str = "pyproject.toml",
    warnings: list[str] | None = None,
) -> dict:
    """Map each requested package to its specifier string, or None if not found.

    Args:
        data: The parsed pyproject.toml, as returned by ``load_pyproject``.
        dependencies_json: JSON array of package names to look up.
        pyproject_path: Path of the file ``data`` was read from, used only in
            warning messages.
        warnings: List to which warning messages are appended (for example
            when a package has different specifiers in several places).

    Returns:
        A dict mapping each requested package name to its specifier, ``""`` if
        the requirement has no specifier, or ``None`` if it was not found.

    Raises:
        MetadataError: If ``dependencies_json`` is not a JSON array of strings.
    """
    deps = _parse_dependencies(dependencies_json)
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
            if warnings is not None:
                warnings.append(
                    f"{dep} has different specifiers in {pyproject_path}: "
                    f"{sorted(set(specs))}; using {specs[0]!r}"
                )
        result[dep] = specs[0]
    return result


def main(argv: list[str]) -> int:
    """Run the command line interface and return the process exit code."""
    if len(argv) not in (3, 4):
        print(
            f"Usage: {argv[0]} <pyproject-path> <extra-values-json> [<dependencies-json>]",
            file=sys.stderr,
        )
        return 2

    try:
        data = load_pyproject(argv[1])
        metadata = extract_metadata(data, argv[2], argv[1])
        warnings: list[str] = []
        metadata["dependency_specifiers"] = extract_dependency_specifiers(
            data, argv[3] if len(argv) == 4 else "[]", argv[1], warnings
        )
        metadata["warnings"] = warnings
    except MetadataError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(metadata))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
