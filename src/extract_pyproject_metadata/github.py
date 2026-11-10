"""The outputs of the action (``GITHUB_OUTPUT``), the workflow commands (the
annotations) and the one-line log summary, with the escaping of their values."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from extract_pyproject_metadata.errors import MetadataError

if TYPE_CHECKING:
    from collections.abc import Callable

    from extract_pyproject_metadata.types import Report

__all__ = [
    "emit_github_output",
    "escape_annotation",
    "escape_annotation_property",
    "format_error",
    "format_log_line",
    "format_outputs",
    "new_delimiter",
    "single_line",
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


# The outputs shown in the log line, in order (the others are derived from these).
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


def format_log_line(outputs: dict[str, str]) -> str:
    """Build the one-line log line of the outputs that is printed in the
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
        msg = f"GITHUB_OUTPUT: cannot write {output_path}: {exc}"
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
        title = escape_annotation_property(warning["code"])
        print(f"::warning file={file},title={title}::{escape_annotation(warning['message'])}")
    print(format_log_line(outputs))
    write_github_output(output_path, outputs)


def format_error(message: str, pyproject_path: str, annotate: bool) -> str:
    """Format an error message for stderr.

    Args:
        message: The message of the ``MetadataError``.
        pyproject_path: Path of the pyproject.toml: the ``file`` of the annotation, or the
            prefix of the plain message. The message itself never contains it.
        annotate: Whether to build a ``::error file=<path>::`` workflow command
            (so that GitHub shows an error annotation on the file) instead of
            ``<path>: <message>``.

    Returns:
        The line to print on stderr.
    """
    if not annotate:
        return f"{pyproject_path}: {message}"
    file = escape_annotation_property(pyproject_path)
    return f"::error file={file}::{escape_annotation(message)}"


def escape_annotation(message: str) -> str:
    """Escape a message for use in a ``::warning::`` workflow command.

    Same escaping as ``@actions/core``: without it a newline would end the
    command and the rest of the message would be parsed as another command.
    """
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def escape_annotation_property(value: str) -> str:
    """Escape a property value (such as ``file``) of a workflow command.

    Same escaping as ``@actions/core``: like ``escape_annotation``, plus
    ``:`` and ``,``, which delimit properties.
    """
    return escape_annotation(value).replace(":", "%3A").replace(",", "%2C")


def single_line(value: str) -> str:
    """Escape backslashes and line breaks so ``value`` stays on one log
    line."""
    return value.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n")
