"""Parsing of the inputs of the action: JSON arrays and booleans."""

from __future__ import annotations

import argparse
import json
from typing import NamedTuple

from extract_pyproject_metadata.errors import MetadataError


class Options(NamedTuple):
    """The boolean inputs of the action, parsed."""

    fail_on_missing: bool
    fail_on_dynamic_version: bool
    strict: bool
    step_summary: bool


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
