r"""Extract project metadata and dependency specifiers from a pyproject.toml.

The metadata is the project name, version, ``requires-python``, optional-dependency
extras and dependency groups.

Usage:
    extract_metadata.py [--github-output FILE] [--fail-on-missing true|false]
        [--] <pyproject-path> <extra-values-json> [<dependencies-json>]

Without ``--github-output``, prints a single JSON object to stdout:
    {"name": ..., "normalized_name": ..., "version": ..., "requires_python": ...,
     "extras": [...], "groups": [...], "dependency_specifiers": {...},
     "warnings": [...]}

"warnings" lists human-readable messages about suspicious but non-fatal
input.

With ``--github-output FILE`` (used by action.yaml), appends the action
outputs ``name``, ``normalized-name``, ``version``, ``requires-python``,
``extras``, ``groups`` and ``dependency-specifiers`` to FILE (the format of
``$GITHUB_OUTPUT``, with a delimiter so that values may contain line breaks)
and prints to stdout one ``::warning file=<path>::`` workflow command per
warning, where ``<path>`` is the pyproject path, so that GitHub attaches the
annotation to the file, followed by a one-line summary. Warnings are printed
on stdout because GitHub only parses workflow commands there.

With ``--fail-on-missing true``, a requested dependency that is not found
is an error instead of a ``null`` specifier.

Exits non-zero with a message on stderr if the file is missing, is not
valid TOML, [project] is missing the required "name"/"version" keys, a
dependency table ([project].dependencies, [project.optional-dependencies] or
[dependency-groups]) has the wrong type, an input is not valid JSON of the
expected shape, or ``--fail-on-missing true`` is given and a requested
dependency is not found.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

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
    data: dict,
    extra_values_json: str,
    pyproject_path: str = "pyproject.toml",
    warnings: list[str] | None = None,
) -> dict:
    """Read name, version, and sorted extras from a parsed pyproject.toml.

    Args:
        data: The parsed pyproject.toml, as returned by ``load_pyproject``.
        extra_values_json: JSON array of extra values to prepend to the
            extras read from ``[project.optional-dependencies]``.
        pyproject_path: Path of the file ``data`` was read from, used only in
            error and warning messages.
        warnings: List to which warning messages are appended (for example
            when the version is dynamic).

    Returns:
        A dict with keys ``name``, ``normalized_name`` (the name per PEP 503),
        ``version``, ``requires_python``, ``extras`` and ``groups``. ``version`` is
        an empty string when ``[project].version`` is declared in
        ``[project].dynamic`` and has no static value. ``requires_python``
        is ``[project].requires-python`` as written, or an empty string if it is
        not declared. ``extras`` lists the ``extra_values`` first, then the
        extras sorted by normalized name. Names are compared per PEP 685 (like
        package names), so spellings of the same extra are duplicates: the
        first one is kept. ``groups`` lists the names of ``[dependency-groups]``
        the same way (sorted by normalized name, without duplicates), and is
        empty if there is no such table.

    Raises:
        MetadataError: If ``[project]`` is not a table, is missing ``name`` or
            ``version`` (unless the version is dynamic), has a ``dynamic`` that
            is not an array, a ``name`` that is not a non-empty string, a
            ``version`` that is not a string or not a valid PEP 440 version, a
            ``requires-python`` that is not a string, an
            ``optional-dependencies`` or ``dependency-groups`` that is not a
            table, or
            ``extra_values_json`` is not a JSON array of strings.
    """
    project = data.get("project", {})
    if not isinstance(project, dict):
        msg = f"{pyproject_path}: [project] must be a table, got: {project!r}"
        raise MetadataError(msg)
    dynamic = project.get("dynamic", [])
    if not isinstance(dynamic, list):
        msg = f"{pyproject_path}: [project].dynamic must be an array, got: {dynamic!r}"
        raise MetadataError(msg)
    try:
        name = project["name"]
    except KeyError as exc:
        msg = f"{pyproject_path} is missing required key [project].{exc.args[0]}"
        raise MetadataError(msg) from exc
    if "version" in project:
        version = project["version"]
    elif "version" in dynamic:
        # The build backend computes the version (setuptools-scm, hatch-vcs, ...).
        version = ""
        if warnings is not None:
            warnings.append(
                f"{pyproject_path}: [project].version is dynamic, the version output is empty"
            )
    else:
        msg = f"{pyproject_path} is missing required key [project].version"
        raise MetadataError(msg)
    if not isinstance(name, str) or not name:
        msg = f"{pyproject_path}: [project].name must be a non-empty string, got: {name!r}"
        raise MetadataError(msg)
    if not isinstance(version, str):
        msg = f"{pyproject_path}: [project].version must be a string, got: {version!r}"
        raise MetadataError(msg)
    if "version" in project:
        try:
            Version(version)
        except InvalidVersion as exc:
            msg = (
                f"{pyproject_path}: [project].version is not a valid PEP 440 version: "
                f"{version!r}"
            )
            raise MetadataError(msg) from exc

    requires_python = project.get("requires-python", "")
    if not isinstance(requires_python, str):
        msg = (
            f"{pyproject_path}: [project].requires-python must be a string, "
            f"got: {requires_python!r}"
        )
        raise MetadataError(msg)

    optional_dependencies = project.get("optional-dependencies", {})
    if not isinstance(optional_dependencies, dict):
        msg = (
            f"{pyproject_path}: [project].optional-dependencies must be a table, "
            f"got: {optional_dependencies!r}"
        )
        raise MetadataError(msg)
    extras = sorted(optional_dependencies, key=canonicalize_name)

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

    # Extra names are normalized like package names (PEP 685), so "Foo_Bar" and
    # "foo-bar" are one extra. The first spelling of each is kept, at the
    # position of its first occurrence.
    unique_extras: dict[str, str] = {}
    for extra in extra_values + extras:
        unique_extras.setdefault(canonicalize_name(extra), extra)

    dependency_groups = data.get("dependency-groups", {})
    if not isinstance(dependency_groups, dict):
        msg = f"{pyproject_path}: [dependency-groups] must be a table, got: {dependency_groups!r}"
        raise MetadataError(msg)
    # Group names are normalized per PEP 503 (PEP 735): the first spelling is kept.
    unique_groups: dict[str, str] = {}
    for group in sorted(dependency_groups, key=canonicalize_name):
        unique_groups.setdefault(canonicalize_name(group), group)
    groups = list(unique_groups.values())
    return {
        "name": name,
        "normalized_name": canonicalize_name(name),
        "version": version,
        "requires_python": requires_python,
        "extras": list(unique_extras.values()),
        "groups": groups,
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


def _check_array(value: object, label: str, pyproject_path: str) -> list:
    """Return ``value`` if it is an array, and raise ``MetadataError`` otherwise."""
    if not isinstance(value, list):
        msg = f"{pyproject_path}: {label} must be an array, got: {value!r}"
        raise MetadataError(msg)
    return value


def _cycle_message(cycle: tuple[str, ...], pyproject_path: str) -> str:
    """Describe an include-group cycle, starting from its smallest group name.

    The same cycle is reached from each of its groups: rotating it to a fixed
    starting point gives the same message each time, so it can be deduplicated.
    """
    start = cycle.index(min(cycle))
    ordered = (*cycle[start:], *cycle[:start])
    path = " -> ".join((*ordered, ordered[0]))
    return f"{pyproject_path}: [dependency-groups] has an include-group cycle: {path}"


def _flatten_group(
    groups: dict,
    name: str,
    seen: tuple[str, ...] = (),
    pyproject_path: str = "pyproject.toml",
    warnings: list[str] | None = None,
) -> list[str]:
    """Return requirement strings of a dependency group, expanding include-group.

    An ``include-group`` that leads back to a group being expanded is not
    followed again; a warning is appended to ``warnings`` (once per cycle). An
    ``include-group`` that names no group is skipped, with a warning.

    Raises:
        MetadataError: If a group is not an array or an ``include-group`` value
            is not a string.
    """
    key = canonicalize_name(name)
    if key in seen:
        if warnings is not None:
            message = _cycle_message(seen[seen.index(key) :], pyproject_path)
            if message not in warnings:
                warnings.append(message)
        return []
    out: list[str] = []
    for gname, entries in groups.items():
        if canonicalize_name(gname) != key:
            continue
        label = f"[dependency-groups].{gname}"
        for entry in _check_array(entries, label, pyproject_path):
            if isinstance(entry, str):
                out.append(entry)
            elif isinstance(entry, dict) and "include-group" in entry:
                included = entry["include-group"]
                if not isinstance(included, str):
                    msg = (
                        f"{pyproject_path}: {label}: include-group must be a string, "
                        f"got: {included!r}"
                    )
                    raise MetadataError(msg)
                if warnings is not None and not any(
                    canonicalize_name(group) == canonicalize_name(included) for group in groups
                ):
                    message = (
                        f"{pyproject_path}: {label}: include-group {included!r} "
                        "does not match any group"
                    )
                    if message not in warnings:
                        warnings.append(message)
                out.extend(
                    _flatten_group(groups, included, (*seen, key), pyproject_path, warnings)
                )
    return out


def _candidate_requirements(
    data: dict, pyproject_path: str = "pyproject.toml", warnings: list[str] | None = None
) -> list[str]:
    """All requirement strings, in search order.

    ``warnings`` receives one message per include-group cycle and per
    ``include-group`` that names no group.

    Raises:
        MetadataError: If ``[project]``, ``[project].dependencies``,
            ``[project.optional-dependencies]``, ``[dependency-groups]`` or one
            of their values has the wrong type.
    """
    project = data.get("project", {})
    if not isinstance(project, dict):
        msg = f"{pyproject_path}: [project] must be a table, got: {project!r}"
        raise MetadataError(msg)
    dependencies = _check_array(
        project.get("dependencies", []), "[project].dependencies", pyproject_path
    )
    reqs = [r for r in dependencies if isinstance(r, str)]
    optional_dependencies = project.get("optional-dependencies", {})
    if not isinstance(optional_dependencies, dict):
        msg = (
            f"{pyproject_path}: [project].optional-dependencies must be a table, "
            f"got: {optional_dependencies!r}"
        )
        raise MetadataError(msg)
    for extra, extra_reqs in optional_dependencies.items():
        label = f"[project.optional-dependencies].{extra}"
        extra_reqs = _check_array(extra_reqs, label, pyproject_path)
        reqs.extend(r for r in extra_reqs if isinstance(r, str))
    groups = data.get("dependency-groups", {})
    if not isinstance(groups, dict):
        msg = f"{pyproject_path}: [dependency-groups] must be a table, got: {groups!r}"
        raise MetadataError(msg)
    for gname in groups:
        reqs.extend(_flatten_group(groups, gname, pyproject_path=pyproject_path, warnings=warnings))
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
            error and warning messages.
        warnings: List to which warning messages are appended (for example
            when a package has different specifiers (with the same environment
            marker) in several places, a
            requirement string cannot be parsed and is ignored,
            ``include-group`` entries form a cycle, or an ``include-group``
            names a group that does not exist). Invalid requirements and
            include-group problems are only reported when ``dependencies_json``
            is not empty.

    Returns:
        A dict mapping each requested package name to its specifier, ``""`` if
        the requirement has no specifier, or ``None`` if it was not found.

    Raises:
        MetadataError: If ``dependencies_json`` is not a JSON array of strings,
            or if ``[project].dependencies``, ``[project.optional-dependencies]``
            or ``[dependency-groups]`` (or one of their values) has the wrong
            type.
    """
    deps = _parse_dependencies(dependencies_json)
    # Like invalid requirements below, structure warnings are only worth
    # reporting when the caller looks something up.
    candidates = _candidate_requirements(data, pyproject_path, warnings if deps else None)
    found: dict[str, list[tuple[str, str | None]]] = {}
    for raw in candidates:
        try:
            req = Requirement(raw)
        except InvalidRequirement as exc:
            # Only worth a warning when the caller looks something up: it may
            # be the very entry that was meant to be found.
            if deps and warnings is not None:
                warnings.append(f"Ignoring invalid requirement {raw!r} in {pyproject_path}: {exc}")
            continue
        marker = None if req.marker is None else str(req.marker)
        found.setdefault(canonicalize_name(req.name), []).append((str(req.specifier), marker))

    result: dict = {}
    for dep in deps:
        matches = found.get(canonicalize_name(dep))
        if not matches:
            result[dep] = None
            continue
        specifier = matches[0][0]
        if warnings is not None:
            warnings.extend(_conflict_warnings(dep, matches, specifier, pyproject_path))
        result[dep] = specifier
    return result


def _conflict_warnings(
    dep: str, matches: list[tuple[str, str | None]], used: str, pyproject_path: str
) -> list[str]:
    """Describe the requirements of ``dep`` that disagree on the specifier.

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
    messages = []
    for marker, specs in by_marker.items():
        if len(specs) > 1:
            where = "" if marker is None else f" for marker {marker!r}"
            messages.append(
                f"{dep} has different specifiers{where} in {pyproject_path}: "
                f"{sorted(specs)}; using {used!r}"
            )
    return messages


def parse_bool(value: str, name: str) -> bool:
    """Parse the ``"true"`` / ``"false"`` string of a boolean input.

    Args:
        value: The string, compared case-insensitively.
        name: The name of the input, used in the error message.

    Returns:
        The boolean value.

    Raises:
        MetadataError: If ``value`` is neither ``"true"`` nor ``"false"``.
    """
    lowered = value.strip().lower()
    if lowered not in {"true", "false"}:
        msg = f"{name} must be 'true' or 'false', got: {value!r}"
        raise MetadataError(msg)
    return lowered == "true"


def check_no_missing_dependency(specifiers: dict, pyproject_path: str) -> None:
    """Raise if a requested dependency was not found.

    Args:
        specifiers: The mapping returned by ``extract_dependency_specifiers``.
        pyproject_path: Path of the file, used in the error message.

    Raises:
        MetadataError: If a package maps to ``None``.
    """
    missing = [name for name, specifier in specifiers.items() if specifier is None]
    if missing:
        msg = (
            f"{pyproject_path}: dependencies not found in [project].dependencies, "
            f"[project.optional-dependencies] or [dependency-groups]: {missing}"
        )
        raise MetadataError(msg)


def escape_annotation(message: str) -> str:
    """Escape a message for use in a ``::warning::`` workflow command.

    Same escaping as ``@actions/core``: without it a newline would end the
    command and the rest of the message would be parsed as another command.
    """
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def escape_annotation_property(value: str) -> str:
    """Escape a property value (such as ``file``) of a workflow command.

    Same escaping as ``@actions/core``: like ``escape_annotation``, plus ``:``
    and ``,``, which delimit properties.
    """
    return escape_annotation(value).replace(":", "%3A").replace(",", "%2C")


def format_outputs(metadata: dict) -> dict[str, str]:
    """Convert the metadata dict into the string outputs of the action.

    Args:
        metadata: The dict built by ``main``, with keys ``name``,
            ``normalized_name``, ``version``, ``requires_python``, ``extras``,
            ``groups`` and ``dependency_specifiers``.

    Returns:
        A dict mapping each output name of ``action.yaml`` to its value, with
        JSON values in compact form.
    """
    return {
        "name": metadata["name"],
        "normalized-name": metadata["normalized_name"],
        "version": metadata["version"],
        "requires-python": metadata["requires_python"],
        "extras": json.dumps(metadata["extras"], separators=(",", ":"), ensure_ascii=False),
        "groups": json.dumps(metadata["groups"], separators=(",", ":"), ensure_ascii=False),
        "dependency-specifiers": json.dumps(
            metadata["dependency_specifiers"], separators=(",", ":"), ensure_ascii=False
        ),
    }


def _new_delimiter() -> str:
    """Return a random delimiter for a multiline ``$GITHUB_OUTPUT`` value."""
    return f"ghadelimiter_{uuid.uuid4()}"


def _single_line(value: str) -> str:
    """Escape backslashes and line breaks so ``value`` stays on one log line."""
    return value.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n")


def write_github_output(output_path: str, outputs: dict[str, str]) -> None:
    """Append outputs to a ``$GITHUB_OUTPUT`` file.

    Every value is written with the ``key<<delimiter`` syntax, so a value that
    contains line breaks (a TOML string can) cannot end early and add outputs
    of its own. The delimiter is random and is regenerated if it appears in
    the key or the value.

    Args:
        output_path: Path of the file, which is created if it does not exist.
        outputs: Output names and values.
    """
    with Path(output_path).open("a", encoding="utf-8", newline="") as f:
        for key, value in outputs.items():
            delimiter = _new_delimiter()
            while delimiter in key or delimiter in value:
                delimiter = _new_delimiter()
            f.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")


def _build_parser(prog: str) -> argparse.ArgumentParser:
    """Build the command line parser."""
    parser = argparse.ArgumentParser(prog=prog, description=__doc__.splitlines()[0])
    parser.add_argument(
        "--github-output",
        metavar="FILE",
        help="append the action outputs to FILE and print workflow commands instead of JSON",
    )
    parser.add_argument(
        "--fail-on-missing",
        metavar="BOOL",
        default="false",
        help="'true' to fail when a requested dependency is not found (default: false)",
    )
    parser.add_argument("pyproject_path", help="path to pyproject.toml")
    parser.add_argument("extra_values", help="JSON array of extra values to prepend")
    parser.add_argument(
        "dependencies", nargs="?", default="[]", help="JSON array of package names to look up"
    )
    return parser


def main(argv: list[str]) -> int:
    """Run the command line interface and return the process exit code."""
    try:
        args = _build_parser(Path(argv[0]).name).parse_args(argv[1:])
    except SystemExit as exc:  # argparse exits on bad arguments and on --help
        return exc.code if isinstance(exc.code, int) else 2

    try:
        fail_on_missing = parse_bool(args.fail_on_missing, "fail-on-missing")
        data = load_pyproject(args.pyproject_path)
        warnings: list[str] = []
        metadata = extract_metadata(data, args.extra_values, args.pyproject_path, warnings)
        metadata["dependency_specifiers"] = extract_dependency_specifiers(
            data, args.dependencies, args.pyproject_path, warnings
        )
        if fail_on_missing:
            check_no_missing_dependency(metadata["dependency_specifiers"], args.pyproject_path)
        metadata["warnings"] = warnings
    except MetadataError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.github_output is None:
        print(json.dumps(metadata))
        return 0

    outputs = format_outputs(metadata)
    for warning in warnings:
        file = escape_annotation_property(args.pyproject_path)
        print(f"::warning file={file}::{escape_annotation(warning)}")
    # name and version come from the file: keep them on one line so they cannot
    # start a workflow command in the log.
    print(
        f"📦 name={_single_line(outputs['name'])} version={_single_line(outputs['version'])} "
        f"extras={outputs['extras']}"
    )
    write_github_output(args.github_output, outputs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
