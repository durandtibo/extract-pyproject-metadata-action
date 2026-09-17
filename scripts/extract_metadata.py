#!/usr/bin/env python3
"""Extract project name, version, and optional-dependency extras from a pyproject.toml.

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
import tomllib
from pathlib import Path


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
    extra_values = json.loads(extra_values_json)

    return {"name": name, "version": version, "extras": extra_values + extras}


def main(argv: list[str]) -> int:
    if len(argv) != 3:  # noqa: PLR2004
        print(f"Usage: {argv[0]} <pyproject-path> <extra-values-json>", file=sys.stderr)
        return 2

    try:
        metadata = extract_metadata(argv[1], argv[2])
    except MetadataError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(metadata))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
