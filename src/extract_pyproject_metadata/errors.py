"""The error raised for invalid user input."""

from __future__ import annotations


class MetadataError(Exception):
    """Raised when pyproject.toml cannot be read or is missing required metadata."""
