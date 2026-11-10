"""Validation and parsing of the inputs of the action: the single place
that turns the input strings into ``Inputs``."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, cast

from extract_pyproject_metadata._vendor.packaging.utils import canonicalize_name
from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.types import Inputs, Lookup

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "DEFAULT_INPUTS",
    "DEFAULT_PYTHON_CANDIDATES",
    "PROJECT_SCOPE",
    "parse_bool",
    "parse_dependencies",
    "parse_inputs",
    "parse_python_candidates",
    "parse_string_array",
]

# The Python versions that ``python-candidates`` defaults to (and the default of the input).
DEFAULT_PYTHON_CANDIDATES = '["3.11","3.12","3.13","3.14","3.15"]'

# The scope of the requirements of ``[project].dependencies`` (see ``collect_requirements``).
PROJECT_SCOPE = "project"

# The value of each input that is not given, by input name.
DEFAULT_INPUTS = {
    "pyproject-path": "pyproject.toml",
    "extra-values": "[]",
    "dependencies": "[]",
    "python-candidates": DEFAULT_PYTHON_CANDIDATES,
    "strict": "false",
}

# A "major.minor" Python version, such as "3.12". Always used with ``fullmatch``: ``$`` would
# also match before a trailing line break.
_MINOR_VERSION = re.compile(r"[0-9]+\.[0-9]+")


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
        msg = f"{input_name}: not valid JSON: {raw!r}"
        raise MetadataError(msg) from exc
    items = cast("list[Any]", values) if isinstance(values, list) else None
    if items is None or not all(isinstance(item, str) for item in items):
        msg = f"{input_name}: must be a JSON array of strings, got: {raw!r}"
        raise MetadataError(msg)
    return cast("list[str]", items)


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
        msg = f"{name}: must be 'true' or 'false', got: {value!r}"
        raise MetadataError(msg)
    return lowered == "true"


def parse_dependencies(raw: str) -> list[Lookup]:
    """Parse the ``dependencies`` input: a JSON array of package names
    with an optional scope.

    A name may be followed by ``@`` and the only place to look it up in:
    ``name@project`` (``[project].dependencies``), ``name@extra:<extra>``
    (``[project.optional-dependencies]``) or ``name@group:<group>``
    (``[dependency-groups]``, ``include-group`` expanded). Without a scope, every place is
    searched. A package name cannot contain ``@``, so the scope is unambiguous.

    Args:
        raw: The value of the input.

    Returns:
        The entries, in order, duplicates included. The names and the names of the scopes are
        normalized per PEP 503.

    Raises:
        MetadataError: If ``raw`` is not a JSON array of strings, or an entry has a scope that is
            not ``project``, ``extra:<name>`` or ``group:<name>`` (with a name).
    """
    lookups: list[Lookup] = []
    for entry in parse_string_array(raw, "dependencies"):
        name, separator, scope = entry.partition("@")
        kind, _, scope_name = scope.partition(":")
        if not separator:
            source = None
        elif scope == PROJECT_SCOPE:
            source = PROJECT_SCOPE
        elif kind in {"extra", "group"} and scope_name:
            source = f"{kind}:{canonicalize_name(scope_name)}"
        else:
            msg = (
                f"dependencies: entry {entry!r} has an invalid scope, it must be 'project', "
                "'extra:<name>' or 'group:<name>' (for example 'pytest@group:dev')"
            )
            raise MetadataError(msg)
        lookups.append(Lookup(text=entry, name=canonicalize_name(name), source=source))
    return lookups


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
            msg = f"python-candidates: must contain 'major.minor' versions such as '3.12', got: {candidate!r}"
            raise MetadataError(msg)
    return list(dict.fromkeys(candidates))


def parse_inputs(raw: Mapping[str, str]) -> Inputs:
    """Validate the inputs of the action and parse them, in one place.

    The inputs are validated in the order of ``DEFAULT_INPUTS``, the first
    invalid one is reported.

    Args:
        raw: The input strings by input name (``strict``, ...). An input that is missing
            takes its value in ``DEFAULT_INPUTS``; an empty ``python-candidates`` too.

    Returns:
        The parsed inputs.

    Raises:
        MetadataError: If an input is invalid.
    """
    values = {**DEFAULT_INPUTS, **raw}
    # The action passes an empty string when the caller does not set python-candidates, so that
    # the list of the supported versions is defined here only.
    values["python-candidates"] = values["python-candidates"] or DEFAULT_PYTHON_CANDIDATES
    return Inputs(
        pyproject_path=values["pyproject-path"],
        extra_values=parse_string_array(values["extra-values"], "extra-values"),
        dependencies=parse_dependencies(values["dependencies"]),
        python_candidates=parse_python_candidates(values["python-candidates"]),
        strict=parse_bool(values["strict"], "strict"),
    )
