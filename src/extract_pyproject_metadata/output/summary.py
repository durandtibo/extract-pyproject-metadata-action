"""The Markdown job summary (``GITHUB_STEP_SUMMARY``): the warnings or the
error of the run."""

from __future__ import annotations

import string
from pathlib import Path
from typing import TYPE_CHECKING

from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.output.escaping import (
    single_line,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


__all__ = [
    "format_error_summary",
    "format_warning_summary",
    "resolve_summary_path",
    "write_step_summary",
]


def _html_cell(value: str) -> str:
    """Escape ``value`` for a cell of a Markdown table, shown as code.

    Every ASCII punctuation character is replaced by its numeric
    character reference, so that nothing in a value from the file can be
    interpreted as Markdown or HTML (a ``|`` ends the cell, ``<`` starts
    a tag, ``_`` is emphasis...). Line breaks are escaped as in the
    summary line of the log.
    """
    escaped = "".join(
        f"&#{ord(char)};" if char in string.punctuation else char for char in single_line(value)
    )
    return f"<code>{escaped}</code>" if escaped else ""


def format_warning_summary(warnings: Sequence[str]) -> str:
    """Build the Markdown of the job summary when the run has warnings.

    Args:
        warnings: The warnings of the report.

    Returns:
        A heading and a list of the warnings, escaped by ``_html_cell``.
    """
    lines = ["### ⚠️ Project metadata", ""]
    lines.extend(f"- {_html_cell(warning)}" for warning in warnings)
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
    """Append ``markdown`` to the job summary file, followed by a blank
    line.

    Raises:
        MetadataError: If the file cannot be written.
    """
    try:
        with Path(summary_path).open("a", encoding="utf-8", newline="") as f:
            f.write(f"{markdown}\n")
    except OSError as exc:
        msg = f"cannot write the job summary to {summary_path}: {exc}"
        raise MetadataError(msg) from exc


def resolve_summary_path(environ: Mapping[str, str]) -> str | None:
    """Return the path of the job summary file, or None outside a GitHub
    workflow.

    Args:
        environ: The environment variables.

    Returns:
        The value of ``GITHUB_STEP_SUMMARY``, or None when it is not set or empty.
    """
    return environ.get("GITHUB_STEP_SUMMARY") or None
