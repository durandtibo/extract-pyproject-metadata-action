"""The action outputs (``GITHUB_OUTPUT``), the workflow commands and the
one-line summary."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.output.escaping import (
    escape_annotation,
    escape_annotation_property,
    single_line,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from extract_pyproject_metadata.types import Report

__all__ = [
    "emit_github_output",
    "format_error",
    "format_outputs",
    "format_summary",
    "new_delimiter",
    "write_github_output",
]


def _compact_json(value: object) -> str:
    """Serialize ``value`` as the compact JSON of an action output.

    No space after ``,`` and ``:``, and non-ASCII characters are kept as
    they are.
    """
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def format_outputs(metadata: Report) -> dict[str, str]:
    """Convert the metadata dict into the string outputs of the action.

    Args:
        metadata: The report built by ``build_report``.

    Returns:
        A dict mapping each output name of ``action.yaml`` to its value, with
        JSON values in compact form. ``json`` is the whole report, the object
        that the script prints to stdout (with the names in ``snake_case``,
        the ``warnings`` and the ``schema_version``).
    """
    return {
        "name": metadata["name"],
        "normalized-name": metadata["normalized_name"],
        "file-name": metadata["file_name"],
        "version": metadata["version"],
        "normalized-version": metadata["normalized_version"],
        "requires-python": metadata["requires_python"],
        "python-versions": _compact_json(metadata["python_versions"]),
        "python-min": metadata["python_min"],
        "python-max": metadata["python_max"],
        "extras": _compact_json(metadata["extras"]),
        "groups": _compact_json(metadata["groups"]),
        "dependency-specifiers": _compact_json(metadata["dependency_specifiers"]),
        "json": _compact_json(metadata),
    }


def new_delimiter() -> str:
    """Return a random delimiter for a multiline ``$GITHUB_OUTPUT``
    value."""
    return f"ghadelimiter_{uuid.uuid4()}"


# The outputs shown in the summary line, in order (the others are derived from these).
_SUMMARY_FIELDS = (
    "name",
    "version",
    "requires-python",
    "python-versions",
    "python-min",
    "python-max",
    "extras",
    "groups",
    "dependency-specifiers",
)


def format_summary(outputs: dict[str, str]) -> str:
    """Build the one-line summary of the outputs that is printed in the
    log.

    Args:
        outputs: The action outputs, as returned by ``format_outputs``.

    Returns:
        A line that starts with ``📦`` and lists ``name=value`` for the outputs
        in ``_SUMMARY_FIELDS``. Values come from the file, so line breaks and
        backslashes are escaped: a value cannot end the line and start a
        workflow command (``::...``) in the log.
    """
    fields = " ".join(f"{field}={single_line(outputs[field])}" for field in _SUMMARY_FIELDS)
    return f"📦 {fields}"


def write_github_output(
    output_path: str,
    outputs: dict[str, str],
    delimiter_factory: Callable[[], str] = new_delimiter,
) -> None:
    """Append outputs to a ``$GITHUB_OUTPUT`` file.

    Every value is written with the ``key<<delimiter`` syntax, so a value that
    contains line breaks (a TOML string can) cannot end early and add outputs
    of its own. The delimiter is random and is regenerated if it appears in
    the key or the value.

    Args:
        output_path: Path of the file, which is created if it does not exist.
        outputs: Output names and values.
        delimiter_factory: Returns a new delimiter on each call. The default is random; a test
            can give a fixed one.

    Raises:
        MetadataError: If the file cannot be written.
    """
    try:
        with Path(output_path).open("a", encoding="utf-8", newline="") as f:
            for key, value in outputs.items():
                delimiter = delimiter_factory()
                while delimiter in key or delimiter in value:
                    delimiter = delimiter_factory()
                f.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")
    except OSError as exc:
        msg = f"cannot write the outputs to {output_path}: {exc}"
        raise MetadataError(msg) from exc


def emit_github_output(report: Report, pyproject_path: str, output_path: str) -> None:
    """Write the outputs of the action and print the workflow commands
    and the summary.

    Args:
        report: The report built by ``build_report``.
        pyproject_path: Path of the pyproject.toml, used as the ``file`` of the
            warning annotations.
        output_path: Path of the ``$GITHUB_OUTPUT`` file.

    Raises:
        MetadataError: If the outputs cannot be written.
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
