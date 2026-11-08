r"""Extract project metadata and dependency specifiers from a pyproject.toml.

The metadata is the project name, version, ``requires-python``, optional-dependency
extras and dependency groups.

Usage:
    extract_metadata.py [--github-output FILE] [--fail-on-missing true|false]
        [--fail-on-dynamic-version true|false] [--step-summary true|false]
        [--strict true|false]
        [--python-candidates JSON] [--] <pyproject-path> <extra-values-json>
        [<dependencies-json>]

Without ``--github-output``, prints a single JSON object to stdout (non-ASCII
characters are kept as they are, as in the action outputs):
    {"name": ..., "normalized_name": ..., "version": ..., "normalized_version": ...,
     "description": ...,
     "requires_python": ...,
     "extras": [...], "groups": [...], "python_versions": [...], "python_min": ..., "python_max": ...,
     "project_dependencies": {...}, "dependency_specifiers": {...},
     "warnings": [...]}

"warnings" lists human-readable messages about suspicious but non-fatal
input.

With ``--github-output FILE`` (used by action.yaml), appends the action
outputs ``name``, ``normalized-name``, ``version``, ``normalized-version``, ``description``, ``requires-python``,
``extras``, ``groups``, ``python-versions``, ``python-min``, ``python-max``, ``python-matrix``, ``project-dependencies`` and
``dependency-specifiers`` to FILE (the format of ``$GITHUB_OUTPUT``, with a
delimiter so that values may contain line breaks) and prints to stdout one
``::warning file=<path>::`` workflow command per warning, where ``<path>`` is
the pyproject path, so that GitHub attaches the annotation to the file,
followed by a one-line summary of the outputs. Warnings are printed on stdout
because GitHub only parses workflow commands there.

With ``--step-summary true``, also appends a Markdown table of the outputs
and the list of warnings to the file named by the ``GITHUB_STEP_SUMMARY``
environment variable (the job summary of GitHub), whichever the other options.
When the run fails, the error message is appended instead (unless
``--step-summary`` or ``GITHUB_STEP_SUMMARY`` is itself the problem).

With ``--strict true``, any warning is an error instead: the outputs are not
written and the message lists the warnings.

With ``--fail-on-missing true``, a requested dependency that is not found
is an error instead of a ``null`` specifier.

With ``--fail-on-dynamic-version true``, a ``version`` that is listed in
``[project].dynamic`` (so that the version output would be empty) is an error
instead of a warning.

``python_versions`` lists the ``--python-candidates`` (a JSON array of
"major.minor" strings) that ``[project].requires-python`` allows, and
``python_min`` is the lowest of them and ``python_max`` the highest (each an
empty string if there is none).
The ``python-matrix`` output (not in the JSON) is
``{"python-version": python_versions}``, an object that ``fromJSON`` can give
to ``strategy.matrix`` as it is.

Exits non-zero with a message on stderr (with ``--github-output FILE``, an
``::error file=<path>::`` workflow command, so that GitHub shows an error
annotation on the file) if the file is missing, is not
valid TOML, [project] is missing the required "name"/"version" keys, a
dependency table ([project].dependencies, [project.optional-dependencies] or
[dependency-groups]) has the wrong type, an input is not valid JSON of the
expected shape, a Python candidate is not a "major.minor" string,
``--fail-on-dynamic-version true`` is given and the version is dynamic, or
``--fail-on-missing true`` is given and a requested dependency is not found.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import sys
import string
import tomllib
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple, TypedDict

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

# The Python versions that ``python-candidates`` defaults to (and the default of the input).
DEFAULT_PYTHON_CANDIDATES = '["3.10","3.11","3.12","3.13","3.14"]'

# A "major.minor" Python version, such as "3.12". Always used with ``fullmatch``: ``$`` would
# also match before a trailing line break.
_MINOR_VERSION = re.compile(r"[0-9]+\.[0-9]+")

# A project name per PEP 508: letters, digits, "-", "_" and "." that start and end with a
# letter or a digit. Always used with ``fullmatch``.
_VALID_NAME = re.compile(r"[A-Z0-9]|[A-Z0-9][A-Z0-9._-]*[A-Z0-9]", re.IGNORECASE)


class MetadataError(Exception):
    """Raised when pyproject.toml cannot be read or is missing required metadata."""


class Metadata(TypedDict):
    """The project metadata read by ``extract_metadata``."""

    name: str
    normalized_name: str
    version: str
    normalized_version: str
    description: str
    requires_python: str
    extras: list[str]
    groups: list[str]


class Report(Metadata):
    """The metadata, Python versions, lowest Python version, dependency specifiers and warnings built by ``build_report``."""

    python_versions: list[str]
    python_min: str
    python_max: str
    project_dependencies: dict[str, str]
    dependency_specifiers: dict[str, str | None]
    warnings: list[str]


class Options(NamedTuple):
    """The boolean inputs of the action, parsed."""

    fail_on_missing: bool
    fail_on_dynamic_version: bool
    strict: bool
    step_summary: bool


def load_pyproject(pyproject_path: str) -> dict[str, Any]:
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
    data: dict[str, Any],
    extra_values: list[str],
    pyproject_path: str = "pyproject.toml",
    fail_on_dynamic_version: bool = False,
) -> tuple[Metadata, list[str]]:
    """Read name, version, and sorted extras from a parsed pyproject.toml.

    Args:
        data: The parsed pyproject.toml, as returned by ``load_pyproject``.
        extra_values: Extra values to prepend to the extras read from
            ``[project.optional-dependencies]``, as returned by
            ``parse_string_array``.
        pyproject_path: Path of the file ``data`` was read from, used only in
            error and warning messages.
        fail_on_dynamic_version: Whether a ``version`` listed in
            ``[project].dynamic`` is an error instead of a warning.

    Returns:
        A tuple ``(metadata, warnings)``. ``warnings`` lists the warning
        messages (for example when the version is dynamic, or when a field is
        both set and listed in ``dynamic``). ``metadata`` is a
        ``Metadata`` dict with keys ``name``, ``normalized_name`` (the name per PEP 503),
        ``version``, ``normalized_version``, ``description``, ``requires_python``, ``extras`` and ``groups``. ``version`` is
        an empty string when ``[project].version`` is declared in
        ``[project].dynamic`` and has no static value (so is ``normalized_version``,
        the version in the canonical form of PEP 440, such as ``1.0rc1`` for ``1.0-RC1``). ``requires_python``
        is ``[project].requires-python`` as written, or an empty string if it is
        not declared. ``description`` is ``[project].description`` as written,
        or an empty string if it is not declared. ``extras`` lists the ``extra_values`` first, then the
        extras sorted by normalized name. Names are compared per PEP 685 (like
        package names), so spellings of the same extra are duplicates: the
        first one is kept. ``groups`` lists the names of ``[dependency-groups]``
        the same way (sorted by normalized name, without duplicates), and is
        empty if there is no such table.

    Raises:
        MetadataError: If ``[project]`` is not a table, is missing ``name`` (also
            when ``name`` is listed in ``dynamic``, which PEP 621 forbids) or
            ``version`` (unless the version is dynamic), has a ``dynamic`` that
            is not an array of strings, a ``name`` that is not a non-empty string or not a
            valid PEP 508 name, a
            ``version`` that is not a string or not a valid PEP 440 version, a
            ``description`` or ``requires-python`` that is not a string, an
            ``optional-dependencies`` or ``dependency-groups`` that is not a
            table, or a dynamic version when ``fail_on_dynamic_version`` is true.
    """
    project = _get_table(data, "project", "[project]", pyproject_path)
    dynamic = _check_requirements(project.get("dynamic", []), "[project].dynamic", pyproject_path)
    try:
        name = project["name"]
    except KeyError as exc:
        if "name" in dynamic:
            # PEP 621: the name cannot be dynamic, so the build backend cannot supply it.
            msg = (
                f"{pyproject_path}: [project].name is listed in [project].dynamic, but "
                "PEP 621 requires a static name"
            )
            raise MetadataError(msg) from exc
        msg = f"{pyproject_path} is missing required key [project].{exc.args[0]}"
        raise MetadataError(msg) from exc
    # PEP 621: a field that is set cannot also be dynamic. The static value is the one read.
    warnings: list[str] = [
        f"{pyproject_path}: [project].{field} is set and also listed in [project].dynamic, "
        "which PEP 621 forbids; the static value is used"
        for field in dict.fromkeys(dynamic)
        if field in project
    ]
    if "version" in project:
        version = project["version"]
    elif "version" in dynamic:
        # The build backend computes the version (setuptools-scm, hatch-vcs, ...).
        if fail_on_dynamic_version:
            msg = (
                f"{pyproject_path}: [project].version is dynamic, so it cannot be read "
                "(fail-on-dynamic-version is 'true')"
            )
            raise MetadataError(msg)
        version = ""
        warnings.append(
            f"{pyproject_path}: [project].version is dynamic, the version output is empty"
        )
    else:
        msg = f"{pyproject_path} is missing required key [project].version"
        raise MetadataError(msg)
    if not isinstance(name, str) or not name:
        msg = f"{pyproject_path}: [project].name must be a non-empty string, got: {name!r}"
        raise MetadataError(msg)
    if not _VALID_NAME.fullmatch(name):
        msg = (
            f"{pyproject_path}: [project].name is not a valid project name (letters, digits, "
            f"'-', '_' and '.', starting and ending with a letter or a digit): {name!r}"
        )
        raise MetadataError(msg)
    if not isinstance(version, str):
        msg = f"{pyproject_path}: [project].version must be a string, got: {version!r}"
        raise MetadataError(msg)
    normalized_version = ""
    if "version" in project:
        try:
            normalized_version = str(Version(version))
        except InvalidVersion as exc:
            msg = (
                f"{pyproject_path}: [project].version is not a valid PEP 440 version: "
                f"{version!r}"
            )
            raise MetadataError(msg) from exc

    description = project.get("description", "")
    if not isinstance(description, str):
        msg = f"{pyproject_path}: [project].description must be a string, got: {description!r}"
        raise MetadataError(msg)

    requires_python = project.get("requires-python", "")
    if not isinstance(requires_python, str):
        msg = (
            f"{pyproject_path}: [project].requires-python must be a string, "
            f"got: {requires_python!r}"
        )
        raise MetadataError(msg)

    optional_dependencies = _get_table(
        project, "optional-dependencies", "[project].optional-dependencies", pyproject_path
    )
    extras = sorted(optional_dependencies, key=canonicalize_name)

    # Extra names are normalized like package names (PEP 685), so "Foo_Bar" and
    # "foo-bar" are one extra. The first spelling of each is kept, at the
    # position of its first occurrence.
    unique_extras: dict[str, str] = {}
    for extra in extra_values + extras:
        unique_extras.setdefault(canonicalize_name(extra), extra)

    dependency_groups = _get_table(data, "dependency-groups", "[dependency-groups]", pyproject_path)
    # Group names are normalized per PEP 503 (PEP 735): the first spelling is kept.
    unique_groups: dict[str, str] = {}
    for group in sorted(dependency_groups, key=canonicalize_name):
        unique_groups.setdefault(canonicalize_name(group), group)
    groups = list(unique_groups.values())
    metadata = Metadata(
        name=name,
        normalized_name=canonicalize_name(name),
        version=version,
        normalized_version=normalized_version,
        description=description,
        requires_python=requires_python,
        extras=list(unique_extras.values()),
        groups=groups,
    )
    return metadata, warnings


def parse_string_array(raw: str, input_name: str) -> list[str]:
    """Parse the JSON array of strings of an action input.

    Args:
        raw: The value of the input.
        input_name: The name of the input, used in the error messages.

    Returns:
        The strings, in order, duplicates included.

    Raises:
        MetadataError: If ``raw`` is not valid JSON or not an array of strings.
    """
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"{input_name} is not valid JSON: {raw!r}"
        raise MetadataError(msg) from exc
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        msg = f"{input_name} must be a JSON array of strings, got: {raw!r}"
        raise MetadataError(msg)
    return values


def _check_array(value: object, label: str, pyproject_path: str) -> list[Any]:
    """Return ``value`` if it is an array, and raise ``MetadataError`` otherwise."""
    if not isinstance(value, list):
        msg = f"{pyproject_path}: {label} must be an array, got: {value!r}"
        raise MetadataError(msg)
    return value


def _check_requirements(value: object, label: str, pyproject_path: str) -> list[str]:
    """Return ``value`` if it is an array of strings, and raise ``MetadataError`` otherwise.

    Despite its name it is not specific to requirements: ``[project].dynamic`` is checked with it too.
    """
    entries = _check_array(value, label, pyproject_path)
    for entry in entries:
        if not isinstance(entry, str):
            msg = f"{pyproject_path}: {label} must contain only strings, got: {entry!r}"
            raise MetadataError(msg)
    return entries


def _get_table(
    container: dict[str, Any], key: str, label: str, pyproject_path: str
) -> dict[str, Any]:
    """Return ``container[key]`` (an empty table if absent), checking that it is a table.

    Args:
        container: The table that holds ``key``.
        key: The key to read.
        label: The name of the table in error messages, such as ``[project]``.
        pyproject_path: Path of the file, used in the error message.

    Returns:
        The table, or an empty dict if ``key`` is absent.

    Raises:
        MetadataError: If the value is not a table.
    """
    value = container.get(key, {})
    if not isinstance(value, dict):
        msg = f"{pyproject_path}: {label} must be a table, got: {value!r}"
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
    groups: dict[str, Any],
    name: str,
    seen: tuple[str, ...] = (),
    pyproject_path: str = "pyproject.toml",
) -> tuple[list[str], list[str]]:
    """Return requirement strings of a dependency group, expanding include-group.

    An ``include-group`` that leads back to a group being expanded is not
    followed again, with a warning (once per cycle). An ``include-group`` that
    names no group is skipped, with a warning.

    Returns:
        A tuple ``(requirements, warnings)``, without duplicate warnings.

    Raises:
        MetadataError: If a group is not an array, an ``include-group`` value
            is not a string, or an entry is neither a string nor a table whose
            only key is ``include-group`` (for example a typo such as
            ``include_group``).
    """
    key = canonicalize_name(name)
    if key in seen:
        return [], [_cycle_message(seen[seen.index(key) :], pyproject_path)]
    out: list[str] = []
    warnings: list[str] = []
    for gname, entries in groups.items():
        if canonicalize_name(gname) != key:
            continue
        label = f"[dependency-groups].{gname}"
        for entry in _check_array(entries, label, pyproject_path):
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
                included_reqs, included_warnings = _flatten_group(
                    groups, included, (*seen, key), pyproject_path
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
    """Describe a dependency field that is dynamic, so cannot be read."""
    return (
        f"{pyproject_path}: [project].{field} is dynamic, it cannot be read, so no "
        "requirement is found in it"
    )


def _dynamic_dependency_fields(data: dict[str, Any]) -> list[str]:
    """Return the dependency fields that only the build backend can provide.

    A field is returned when it is listed in ``[project].dynamic`` and has no
    static value in ``[project]``. Only ``dependencies`` and
    ``optional-dependencies`` are checked, in this order.
    """
    project = data.get("project", {})
    if not isinstance(project, dict):
        return []
    dynamic = project.get("dynamic", [])
    if not isinstance(dynamic, list):
        return []
    return [
        field
        for field in ("dependencies", "optional-dependencies")
        if field in dynamic and field not in project
    ]


def _candidate_requirements(
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
    project = _get_table(data, "project", "[project]", pyproject_path)
    # A copy: the lists below are extended, and the parsed document must stay as it is.
    reqs = list(
        _check_requirements(
            project.get("dependencies", []), "[project].dependencies", pyproject_path
        )
    )
    optional_dependencies = _get_table(
        project, "optional-dependencies", "[project].optional-dependencies", pyproject_path
    )
    for extra, extra_reqs in optional_dependencies.items():
        label = f"[project.optional-dependencies].{extra}"
        reqs.extend(_check_requirements(extra_reqs, label, pyproject_path))
    groups = _get_table(data, "dependency-groups", "[dependency-groups]", pyproject_path)
    warnings = [
        _dynamic_message(field, pyproject_path)
        for field in _dynamic_dependency_fields(data)
    ]
    for gname in groups:
        group_reqs, group_warnings = _flatten_group(groups, gname, pyproject_path=pyproject_path)
        reqs.extend(group_reqs)
        warnings.extend(group_warnings)
    return reqs, list(dict.fromkeys(warnings))


@functools.lru_cache(maxsize=None)
def _parse_requirement(raw: str) -> Requirement | InvalidRequirement:
    """Parse a requirement string, once per distinct string.

    ``build_report`` reads the requirements of ``[project].dependencies`` twice (for
    ``project-dependencies`` and for the lookup of ``dependencies``): the cache
    makes each string parsed only once.

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


def _index_requirements(
    raws: list[str], pyproject_path: str
) -> tuple[dict[str, list[tuple[str, str | None]]], dict[str, str], list[str]]:
    """Parse requirement strings and group them by package.

    Args:
        raws: The requirement strings, in search order.
        pyproject_path: Path of the file, used in the warning messages.

    Returns:
        A tuple ``(found, names, warnings)``. ``found`` maps the normalized
        name of each package to the ``(specifier, marker)`` of each of its
        requirements, in order (``marker`` is ``None`` when there is none).
        ``names`` maps it to the name as written in its first requirement.
        ``warnings`` has one message per requirement that cannot be parsed,
        which is ignored.
    """
    found: dict[str, list[tuple[str, str | None]]] = {}
    names: dict[str, str] = {}
    warnings: list[str] = []
    for raw in raws:
        req = _parse_requirement(raw)
        if isinstance(req, InvalidRequirement):
            warnings.append(f"Ignoring invalid requirement {raw!r} in {pyproject_path}: {req}")
            continue
        key = canonicalize_name(req.name)
        marker = None if req.marker is None else str(req.marker)
        found.setdefault(key, []).append((str(req.specifier), marker))
        names.setdefault(key, req.name)
    return found, names, warnings


def extract_project_dependencies(
    data: dict[str, Any], pyproject_path: str = "pyproject.toml"
) -> tuple[dict[str, str], list[str]]:
    """Map each package of ``[project].dependencies`` to its specifier.

    Only the requirements of ``[project].dependencies`` are read, not the
    extras or the dependency groups. Like ``extract_dependency_specifiers``, the
    first requirement of a package wins, whatever its environment marker.

    Args:
        data: The parsed pyproject.toml, as returned by ``load_pyproject``.
        pyproject_path: Path of the file ``data`` was read from, used only in
            error and warning messages.

    Returns:
        A tuple ``(dependencies, warnings)``. ``dependencies`` maps the name of
        each package, as written in its first requirement and in the order of
        the file, to its specifier (``""`` if it has none). ``warnings`` lists
        the requirements that cannot be parsed and are ignored, the packages
        that have different specifiers (with the same environment marker), and
        a ``dynamic`` ``dependencies``.

    Raises:
        MetadataError: If ``[project]`` is not a table, or
            ``[project].dependencies`` is not an array of strings.
    """
    project = _get_table(data, "project", "[project]", pyproject_path)
    entries = _check_requirements(
        project.get("dependencies", []), "[project].dependencies", pyproject_path
    )
    found, names, warnings = _index_requirements(entries, pyproject_path)
    if "dependencies" in _dynamic_dependency_fields(data):
        warnings.append(_dynamic_message("dependencies", pyproject_path))
    dependencies: dict[str, str] = {}
    for key, matches in found.items():
        specifier = matches[0][0]
        dependencies[names[key]] = specifier
        warnings.extend(_conflict_warnings(names[key], matches, specifier, pyproject_path))
    return dependencies, warnings


def extract_dependency_specifiers(
    data: dict[str, Any],
    dependencies: list[str],
    pyproject_path: str = "pyproject.toml",
) -> tuple[dict[str, str | None], list[str]]:
    """Map each requested package to its specifier string, or None if not found.

    Args:
        data: The parsed pyproject.toml, as returned by ``load_pyproject``.
        dependencies: Package names to look up, as returned by
            ``parse_string_array``.
        pyproject_path: Path of the file ``data`` was read from, used only in
            error and warning messages.

    Returns:
        A tuple ``(specifiers, warnings)``. ``specifiers`` maps each requested
        package name to its specifier, ``""`` if the requirement has no
        specifier, or ``None`` if it was not found. ``warnings`` lists the
        warning messages: a package has different specifiers (with the same
        environment marker) in several places, a requirement string cannot be
        parsed and is ignored, ``include-group`` entries form a cycle, or an
        ``include-group`` names a group that does not exist. Invalid
        requirements and include-group problems are only reported when
        ``dependencies`` is not empty.

    Raises:
        MetadataError: If ``[project].dependencies``, ``[project.optional-dependencies]``
            or ``[dependency-groups]`` (or one of their values) has the wrong
            type, or a requirement of ``[project].dependencies`` or of an extra
            is not a string.
    """
    # Like invalid requirements below, structure warnings are only worth
    # reporting when the caller looks something up.
    candidates, structure_warnings = _candidate_requirements(data, pyproject_path)
    found, _, invalid_warnings = _index_requirements(candidates, pyproject_path)
    # An invalid requirement is only worth a warning when the caller looks
    # something up: it may be the very entry that was meant to be found.
    warnings = [*structure_warnings, *invalid_warnings] if dependencies else []

    result: dict[str, str | None] = {}
    for dep in dependencies:
        matches = found.get(canonicalize_name(dep))
        if not matches:
            result[dep] = None
            continue
        specifier = matches[0][0]
        warnings.extend(_conflict_warnings(dep, matches, specifier, pyproject_path))
        result[dep] = specifier
    return result, warnings


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


def parse_python_candidates(raw: str) -> list[str]:
    """Parse the ``python-candidates`` input.

    Args:
        raw: The value of the input, a JSON array of "major.minor" strings.

    Returns:
        The versions, in order, without duplicates.

    Raises:
        MetadataError: If ``raw`` is not a JSON array of strings, or a string
            is not of the form "major.minor" (such as ``"3.12"``).
    """
    candidates = parse_string_array(raw, "python-candidates")
    for candidate in candidates:
        if not _MINOR_VERSION.fullmatch(candidate):
            msg = f"python-candidates must contain 'major.minor' versions such as '3.12', got: {candidate!r}"
            raise MetadataError(msg)
    return list(dict.fromkeys(candidates))


def _patch_releases(specifier: SpecifierSet, candidate: str) -> set[int]:
    """Return the patch numbers of ``candidate`` that are worth testing against ``specifier``.

    The first release (``0``) and a very late one (``9999``) are always tested.
    A patch number that a specifier names for the same "major.minor" (as in
    ``==3.12.3``, ``>3.12.5`` or ``~=3.12.3``) is tested too, with the previous
    and the next one, so that the bounds of the allowed range are found
    whichever operator is used.

    Why this is enough: a specifier is a conjunction of clauses, and each clause
    only changes at the patch numbers it names (``>``, ``>=``, ``<``, ``<=``,
    ``==``, ``!=``, ``~=``, ``===``), so the set of allowed patch numbers is a
    union of intervals whose ends are a named number or one next to it. If it
    is not empty, it contains one of ``0``, ``9999``, a named number or its
    neighbours. The only blind spots are wildcards (``!=3.12.*``), which have
    no patch number and exclude the whole minor version, and releases of more
    than three numbers (``3.12.1.5``), which no Python has.

    Args:
        specifier: The parsed ``requires-python``.
        candidate: A "major.minor" version, such as ``"3.12"``.

    Returns:
        The patch numbers to test.
    """
    patches = {0, 9999}
    major, minor = (int(part) for part in candidate.split("."))
    for item in specifier:
        try:
            release = Version(item.version).release
        except InvalidVersion:  # a wildcard such as "3.12.*" has no bound to find
            continue
        if len(release) >= 3 and release[:2] == (major, minor):
            patches.update({max(release[2] - 1, 0), release[2], release[2] + 1})
    return patches


def compatible_python_versions(
    requires_python: str, candidates: list[str], pyproject_path: str = "pyproject.toml"
) -> tuple[list[str], list[str]]:
    """Select the candidate Python versions that ``requires-python`` allows.

    A "major.minor" candidate is allowed when some release of it can satisfy the
    specifier. This is checked on the first release (``X.Y.0``), on a very late
    one (``X.Y.9999``) and around each patch number that the specifier names
    for the candidate (see ``_patch_releases``), so ``>=3.10.2`` and ``<3.12.5``
    allow ``3.10`` and ``3.12``, and ``==3.12.3`` allows ``3.12`` only.

    Args:
        requires_python: ``[project].requires-python`` as written, or an empty
            string if it is not declared.
        candidates: The "major.minor" versions to choose from, as returned by
            ``parse_python_candidates``.
        pyproject_path: Path of the file, used in the warning message.

    Returns:
        A tuple ``(versions, warnings)``. ``versions`` are the allowed
        candidates, in the order of ``candidates``: all of them when
        ``requires_python`` is empty, none of them (with a warning) when it is
        not a valid specifier.
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
        if any(
            specifier.contains(f"{candidate}.{patch}")
            for patch in sorted(_patch_releases(specifier, candidate))
        )
    ]
    return versions, []


def _minor_version_key(version: str) -> tuple[int, ...]:
    """Return the numbers of a "major.minor" version, to compare versions as numbers."""
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
    """Return the highest of "major.minor" versions, compared as numbers.

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


def parse_options(args: argparse.Namespace) -> Options:
    """Parse the four boolean inputs of the command line, in one place.

    Args:
        args: The parsed command line, as returned by ``_build_parser``.

    Returns:
        The parsed booleans.

    Raises:
        MetadataError: If one of them is neither ``"true"`` nor ``"false"``
            (the first invalid one, in the order of ``Options``).
    """
    return Options(
        fail_on_missing=parse_bool(args.fail_on_missing, "fail-on-missing"),
        fail_on_dynamic_version=parse_bool(
            args.fail_on_dynamic_version, "fail-on-dynamic-version"
        ),
        strict=parse_bool(args.strict, "strict"),
        step_summary=parse_bool(args.step_summary, "step-summary"),
    )


def check_no_missing_dependency(
    specifiers: dict[str, str | None],
    pyproject_path: str,
    dynamic_fields: Sequence[str] = (),
) -> None:
    """Raise if a requested dependency was not found.

    Args:
        specifiers: The mapping returned by ``extract_dependency_specifiers``.
        pyproject_path: Path of the file, used in the error message.
        dynamic_fields: The dependency fields that are dynamic, as returned by
            ``_dynamic_dependency_fields``. The error message points them out,
            because a package may be missing only because it cannot be read.

    Raises:
        MetadataError: If a package maps to ``None``.
    """
    missing = [name for name, specifier in specifiers.items() if specifier is None]
    if missing:
        msg = (
            f"{pyproject_path}: dependencies not found in [project].dependencies, "
            f"[project.optional-dependencies] or [dependency-groups]: {missing}"
        )
        for field in dynamic_fields:
            msg += f"; [project].{field} is dynamic and cannot be read"
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


def format_outputs(metadata: Report) -> dict[str, str]:
    """Convert the metadata dict into the string outputs of the action.

    Args:
        metadata: The report built by ``build_report``.

    Returns:
        A dict mapping each output name of ``action.yaml`` to its value, with
        JSON values in compact form.
    """
    return {
        "name": metadata["name"],
        "normalized-name": metadata["normalized_name"],
        "version": metadata["version"],
        "normalized-version": metadata["normalized_version"],
        "description": metadata["description"],
        "requires-python": metadata["requires_python"],
        "extras": json.dumps(metadata["extras"], separators=(",", ":"), ensure_ascii=False),
        "groups": json.dumps(metadata["groups"], separators=(",", ":"), ensure_ascii=False),
        "python-versions": json.dumps(
            metadata["python_versions"], separators=(",", ":"), ensure_ascii=False
        ),
        "python-min": metadata["python_min"],
        "python-max": metadata["python_max"],
        "python-matrix": json.dumps(
            {"python-version": metadata["python_versions"]}, separators=(",", ":"), ensure_ascii=False
        ),
        "project-dependencies": json.dumps(
            metadata["project_dependencies"], separators=(",", ":"), ensure_ascii=False
        ),
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


# The outputs shown in the summary line, in order (normalized-name is derived from name, and
# description may be long).
_SUMMARY_FIELDS = (
    "name",
    "version",
    "requires-python",
    "python-versions",
    "python-min",
    "python-max",
    "extras",
    "groups",
    "project-dependencies",
    "dependency-specifiers",
)


def format_summary(outputs: dict[str, str]) -> str:
    """Build the one-line summary of the outputs that is printed in the log.

    Args:
        outputs: The action outputs, as returned by ``format_outputs``.

    Returns:
        A line that starts with ``📦`` and lists ``name=value`` for the outputs
        in ``_SUMMARY_FIELDS``. Values come from the file, so line breaks and
        backslashes are escaped: a value cannot end the line and start a
        workflow command (``::...``) in the log.
    """
    fields = " ".join(f"{field}={_single_line(outputs[field])}" for field in _SUMMARY_FIELDS)
    return f"📦 {fields}"


def _html_cell(value: str) -> str:
    """Escape ``value`` for a cell of a Markdown table, shown as code.

    Every ASCII punctuation character is replaced by its numeric character
    reference, so that nothing in a value from the file can be interpreted as
    Markdown or HTML (a ``|`` ends the cell, ``<`` starts a tag, ``_`` is
    emphasis...). Line breaks are escaped as in the summary line of the log.
    """
    escaped = "".join(
        f"&#{ord(char)};" if char in string.punctuation else char for char in _single_line(value)
    )
    return f"<code>{escaped}</code>" if escaped else ""


def format_step_summary(report: Report, outputs: dict[str, str]) -> str:
    """Build the Markdown of the job summary.

    Args:
        report: The report built by ``build_report``.
        outputs: The action outputs, as returned by ``format_outputs``.

    Returns:
        A heading, a table with one row per output and, if there are warnings,
        a list of them. Values are escaped by ``_html_cell``.
    """
    lines = [
        "### 📦 Project metadata",
        "",
        "| Output | Value |",
        "| --- | --- |",
    ]
    lines.extend(f"| `{key}` | {_html_cell(value)} |" for key, value in outputs.items())
    if report["warnings"]:
        lines.extend(["", "#### ⚠️ Warnings", ""])
        lines.extend(f"- {_html_cell(warning)}" for warning in report["warnings"])
    return "\n".join(lines) + "\n"


def format_error_summary(message: str) -> str:
    """Build the Markdown of the job summary when the action fails.

    Args:
        message: The message of the ``MetadataError``. Each line (the error
            of ``--strict`` lists one warning per line, each starting with
            ``"- "``) becomes a list item.

    Returns:
        A heading and a list of the lines of the message, escaped by
        ``_html_cell`` like the values of ``format_step_summary``.
    """
    lines = ["### ❌ Project metadata", ""]
    lines.extend(
        f"- {_html_cell(line.strip().removeprefix('- '))}"
        for line in message.split("\n")
        if line.strip()
    )
    return "\n".join(lines) + "\n"


def write_step_summary(summary_path: str, markdown: str) -> None:
    """Append ``markdown`` to the job summary file, followed by a blank line."""
    with Path(summary_path).open("a", encoding="utf-8", newline="") as f:
        f.write(f"{markdown}\n")


def resolve_step_summary(enabled: bool, environ: Mapping[str, str]) -> str | None:
    """Return the path of the job summary file, or None if it is not requested.

    Args:
        enabled: The parsed ``--step-summary`` option.
        environ: The environment variables.

    Returns:
        The value of ``GITHUB_STEP_SUMMARY`` when ``enabled`` is true, None
        otherwise.

    Raises:
        MetadataError: If ``enabled`` is true and ``GITHUB_STEP_SUMMARY`` is not
            set (the action is not running in a GitHub workflow).
    """
    if not enabled:
        return None
    summary_path = environ.get("GITHUB_STEP_SUMMARY", "")
    if not summary_path:
        msg = "step-summary is 'true' but the environment variable GITHUB_STEP_SUMMARY is not set"
        raise MetadataError(msg)
    return summary_path


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
    # ``__doc__`` is None when Python runs with -OO, which strips docstrings.
    description = (__doc__ or "").split("\n", 1)[0]
    parser = argparse.ArgumentParser(prog=prog, description=description)
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
    parser.add_argument(
        "--fail-on-dynamic-version",
        metavar="BOOL",
        default="false",
        help="'true' to fail when the version is dynamic, instead of a warning (default: false)",
    )
    parser.add_argument(
        "--strict",
        metavar="BOOL",
        default="false",
        help="'true' to fail when there is a warning (default: false)",
    )
    parser.add_argument(
        "--step-summary",
        metavar="BOOL",
        default="false",
        help="'true' to also write the outputs to the job summary, GITHUB_STEP_SUMMARY (default: false)",
    )
    parser.add_argument(
        "--python-candidates",
        metavar="JSON",
        default=DEFAULT_PYTHON_CANDIDATES,
        help=(
            "JSON array of 'major.minor' Python versions to select from, using requires-python "
            f"(default: {DEFAULT_PYTHON_CANDIDATES})"
        ),
    )
    parser.add_argument("pyproject_path", help="path to pyproject.toml")
    parser.add_argument("extra_values", help="JSON array of extra values to prepend")
    parser.add_argument(
        "dependencies", nargs="?", default="[]", help="JSON array of package names to look up"
    )
    return parser


def build_report(args: argparse.Namespace, options: Options | None = None) -> Report:
    """Read the pyproject.toml and the inputs of the command line, and build the report.

    Args:
        args: The parsed command line, as returned by ``_build_parser``.
        options: The parsed boolean inputs. Parsed from ``args`` when omitted.

    Returns:
        The report: the metadata, the Python versions, the dependency
        specifiers and the warnings (without duplicates).

    Raises:
        MetadataError: If an input or the pyproject.toml is invalid, the version
            is dynamic with ``--fail-on-dynamic-version true``, a dependency
            is not found with ``--fail-on-missing true``, or there is a
            warning with ``--strict true``.
    """
    if options is None:
        options = parse_options(args)
    data = load_pyproject(args.pyproject_path)
    extra_values = parse_string_array(args.extra_values, "extra-values")
    dependencies = parse_string_array(args.dependencies, "dependencies")
    python_candidates = parse_python_candidates(args.python_candidates)
    metadata, warnings = extract_metadata(
        data, extra_values, args.pyproject_path, options.fail_on_dynamic_version
    )
    specifiers, specifier_warnings = extract_dependency_specifiers(
        data, dependencies, args.pyproject_path
    )
    python_versions, python_warnings = compatible_python_versions(
        metadata["requires_python"], python_candidates, args.pyproject_path
    )
    project_dependencies, project_warnings = extract_project_dependencies(
        data, args.pyproject_path
    )
    warnings.extend(python_warnings)
    warnings.extend(project_warnings)
    warnings.extend(specifier_warnings)
    if options.fail_on_missing:
        check_no_missing_dependency(
            specifiers, args.pyproject_path, _dynamic_dependency_fields(data)
        )
    warnings = list(dict.fromkeys(warnings))
    if options.strict and warnings:
        listed = "".join(f"\n- {warning}" for warning in warnings)
        msg = f"strict is 'true' and there are {len(warnings)} warning(s):{listed}"
        raise MetadataError(msg)
    return Report(
        **metadata,
        python_versions=python_versions,
        python_min=lowest_python_version(python_versions),
        python_max=highest_python_version(python_versions),
        project_dependencies=project_dependencies,
        dependency_specifiers=specifiers,
        warnings=warnings,
    )


def emit_github_output(report: Report, pyproject_path: str, output_path: str) -> None:
    """Write the outputs of the action and print the workflow commands and the summary.

    Args:
        report: The report built by ``build_report``.
        pyproject_path: Path of the pyproject.toml, used as the ``file`` of the
            warning annotations.
        output_path: Path of the ``$GITHUB_OUTPUT`` file.
    """
    outputs = format_outputs(report)
    file = escape_annotation_property(pyproject_path)
    for warning in report["warnings"]:
        print(f"::warning file={file}::{escape_annotation(warning)}")
    print(format_summary(outputs))
    write_github_output(output_path, outputs)


def format_error(message: str, pyproject_path: str, annotate: bool) -> str:
    """Format an error message for stderr.

    Args:
        message: The message of the ``MetadataError``.
        pyproject_path: Path of the pyproject.toml, used as the ``file`` of the
            annotation.
        annotate: Whether to build a ``::error file=<path>::`` workflow command
            (so that GitHub shows an error annotation on the file) instead of
            the plain message.

    Returns:
        The line to print on stderr.
    """
    if not annotate:
        return message
    file = escape_annotation_property(pyproject_path)
    return f"::error file={file}::{escape_annotation(message)}"


def main(argv: list[str]) -> int:
    """Run the command line interface and return the process exit code."""
    try:
        args = _build_parser(Path(argv[0]).name).parse_args(argv[1:])
    except SystemExit as exc:  # argparse exits on bad arguments and on --help
        return exc.code if isinstance(exc.code, int) else 2

    summary_path: str | None = None
    try:
        options = parse_options(args)
        summary_path = resolve_step_summary(options.step_summary, os.environ)
        report = build_report(args, options)
    except MetadataError as exc:
        annotate = args.github_output is not None
        print(format_error(str(exc), args.pyproject_path, annotate), file=sys.stderr)
        if summary_path is not None:
            write_step_summary(summary_path, format_error_summary(str(exc)))
        return 1

    if args.github_output is None:
        # Like the action outputs, keep non-ASCII characters as they are.
        print(json.dumps(report, ensure_ascii=False))
    else:
        emit_github_output(report, args.pyproject_path, args.github_output)
    if summary_path is not None:
        write_step_summary(summary_path, format_step_summary(report, format_outputs(report)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
