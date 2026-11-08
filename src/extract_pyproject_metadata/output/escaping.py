"""Escaping of the values written to workflow commands and to the
logs."""

from __future__ import annotations

__all__ = ["escape_annotation", "escape_annotation_property", "single_line"]


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
