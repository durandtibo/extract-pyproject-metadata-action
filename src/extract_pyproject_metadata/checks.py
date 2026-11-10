"""Checks of the type of the values read from a pyproject.toml."""

from __future__ import annotations

import re
from typing import Any, TypeGuard, cast

from extract_pyproject_metadata.errors import MetadataError

__all__ = [
    "check_array",
    "check_str",
    "check_string_array",
    "get_table",
    "is_package_name",
    "is_table",
]

# A package name per PEP 508: letters, digits, "-", "_" and "." that start and end with a
# letter or a digit. Always used with ``fullmatch``.
_PACKAGE_NAME = re.compile(r"[A-Z0-9]|[A-Z0-9][A-Z0-9._-]*[A-Z0-9]", re.IGNORECASE)


def is_package_name(name: str) -> bool:
    """Tell whether ``name`` is a valid package name (PEP 508).

    The rule of ``[project].name`` and of the names of the ``dependencies`` input, so that the
    file and the input cannot disagree.

    Args:
        name: The name to check.

    Returns:
        ``True`` if ``name`` has only letters, digits, ``-``, ``_`` and ``.``, and starts and
        ends with a letter or a digit.
    """
    return _PACKAGE_NAME.fullmatch(name) is not None


def check_str(value: object, label: str) -> str:
    """Return ``value`` if it is a string, and raise ``MetadataError``
    otherwise.

    Args:
        value: The value read from the file.
        label: The name of the key in the error message, such as ``[project].description``.

    Returns:
        ``value``, unchanged.

    Raises:
        MetadataError: If ``value`` is not a string.
    """
    if not isinstance(value, str):
        msg = f"{label}: must be a string, got: {value!r}"
        raise MetadataError(msg)
    return value


def check_array(value: object, label: str) -> list[Any]:
    """Return ``value`` if it is an array, and raise ``MetadataError``
    otherwise."""
    if not isinstance(value, list):
        msg = f"{label}: must be an array, got: {value!r}"
        raise MetadataError(msg)
    return cast("list[Any]", value)


def check_string_array(value: object, label: str) -> list[str]:
    """Return ``value`` if it is an array of strings, and raise
    ``MetadataError`` otherwise.

    Used for the arrays of requirement strings and for
    ``[project].dynamic``.
    """
    entries = check_array(value, label)
    for entry in entries:
        if not isinstance(entry, str):
            msg = f"{label}: must contain only strings, got: {entry!r}"
            raise MetadataError(msg)
    return entries


def get_table(container: dict[str, Any], key: str, label: str) -> dict[str, Any]:
    """Return ``container[key]`` (an empty table if absent), checking
    that it is a table.

    Args:
        container: The table that holds ``key``.
        key: The key to read.
        label: The name of the table in error messages, such as ``[project]``.

    Returns:
        The table, or an empty dict if ``key`` is absent.

    Raises:
        MetadataError: If the value is not a table.
    """
    value = container.get(key, {})
    if not isinstance(value, dict):
        msg = f"{label}: must be a table, got: {value!r}"
        raise MetadataError(msg)
    return cast("dict[str, Any]", value)


def is_table(value: object) -> TypeGuard[dict[str, Any]]:
    """Tell whether ``value`` is a table (a TOML table is a dict with
    string keys).

    Args:
        value: The value read from the file.

    Returns:
        ``True`` if ``value`` is a dict, which then has the type ``dict[str, Any]``.
    """
    return isinstance(value, dict)
