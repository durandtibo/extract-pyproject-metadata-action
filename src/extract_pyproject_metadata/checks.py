"""Checks of the type of the values read from a pyproject.toml."""

from __future__ import annotations

from typing import Any, cast

from extract_pyproject_metadata.errors import MetadataError

__all__ = ["check_array", "check_str", "check_string_array", "get_table"]


def check_str(value: object, label: str, pyproject_path: str) -> str:
    """Return ``value`` if it is a string, and raise ``MetadataError``
    otherwise.

    Args:
        value: The value read from the file.
        label: The name of the key in the error message, such as ``[project].description``.
        pyproject_path: Path of the file, used in the error message.

    Returns:
        ``value``, unchanged.

    Raises:
        MetadataError: If ``value`` is not a string.
    """
    if not isinstance(value, str):
        msg = f"{pyproject_path}: {label} must be a string, got: {value!r}"
        raise MetadataError(msg)
    return value


def check_array(value: object, label: str, pyproject_path: str) -> list[Any]:
    """Return ``value`` if it is an array, and raise ``MetadataError``
    otherwise."""
    if not isinstance(value, list):
        msg = f"{pyproject_path}: {label} must be an array, got: {value!r}"
        raise MetadataError(msg)
    return cast("list[Any]", value)


def check_string_array(value: object, label: str, pyproject_path: str) -> list[str]:
    """Return ``value`` if it is an array of strings, and raise
    ``MetadataError`` otherwise.

    Used for the arrays of requirement strings and for
    ``[project].dynamic``.
    """
    entries = check_array(value, label, pyproject_path)
    for entry in entries:
        if not isinstance(entry, str):
            msg = f"{pyproject_path}: {label} must contain only strings, got: {entry!r}"
            raise MetadataError(msg)
    return entries


def get_table(
    container: dict[str, Any], key: str, label: str, pyproject_path: str
) -> dict[str, Any]:
    """Return ``container[key]`` (an empty table if absent), checking
    that it is a table.

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
    return cast("dict[str, Any]", value)
