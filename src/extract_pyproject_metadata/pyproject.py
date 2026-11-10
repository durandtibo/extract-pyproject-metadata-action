"""Read and parse a pyproject.toml file, and read the names of its extras and
dependency groups."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from extract_pyproject_metadata._vendor.packaging.utils import canonicalize_name
from extract_pyproject_metadata.checks import get_table
from extract_pyproject_metadata.errors import MetadataError

__all__ = ["UTF8_BOM", "load_pyproject", "read_extra_names", "read_group_names"]

# The UTF-8 byte order mark that some editors write at the start of a file.
UTF8_BOM = b"\xef\xbb\xbf"


def load_pyproject(pyproject_path: str) -> dict[str, Any]:
    """Read and parse a pyproject.toml file.

    Args:
        pyproject_path: Path to the pyproject.toml file.

    Returns:
        The parsed TOML document. A UTF-8 byte order mark at the start of the
        file is ignored.

    Raises:
        MetadataError: If the file is missing, cannot be read (for example for
            lack of permission), is not UTF-8, is not valid TOML or has arrays or inline
            tables nested too deeply for the parser.
    """
    path = Path(pyproject_path)
    if not path.is_file():
        msg = f"pyproject.toml not found at: {pyproject_path}"
        raise MetadataError(msg)
    try:
        with path.open("rb") as f:
            content = f.read()
        # Some editors (on Windows) start a UTF-8 file with a byte order mark, which TOML rejects.
        return tomllib.loads(content.removeprefix(UTF8_BOM).decode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        msg = f"{pyproject_path} is not valid TOML: {exc}"
        raise MetadataError(msg) from exc
    except UnicodeDecodeError as exc:
        msg = f"{pyproject_path} is not valid UTF-8: {exc}"
        raise MetadataError(msg) from exc
    except RecursionError as exc:  # tomllib recurses on nested arrays and inline tables
        msg = f"{pyproject_path} is nested too deeply to be parsed"
        raise MetadataError(msg) from exc
    except OSError as exc:
        msg = f"{pyproject_path} cannot be read: {exc}"
        raise MetadataError(msg) from exc


def read_extra_names(
    project: dict[str, Any], extra_values: list[str], pyproject_path: str
) -> list[str]:
    """Return the extra names: ``extra_values`` first, then the sorted
    extras.

    Extra names are normalized like package names (PEP 685), so "Foo_Bar" and
    "foo-bar" are one extra. The first spelling of each is kept, at the
    position of its first occurrence.

    Args:
        project: The ``[project]`` table.
        extra_values: The values to put first, as returned by ``parse_string_array``.
        pyproject_path: Path of the file, used in the error message.

    Returns:
        The names, without duplicates.

    Raises:
        MetadataError: If ``[project.optional-dependencies]`` is not a table.
    """
    optional_dependencies = get_table(
        project, "optional-dependencies", "[project].optional-dependencies", pyproject_path
    )
    extras = sorted(optional_dependencies, key=canonicalize_name)
    unique_extras: dict[str, str] = {}
    for extra in extra_values + extras:
        unique_extras.setdefault(canonicalize_name(extra), extra)
    return list(unique_extras.values())


def read_group_names(data: dict[str, Any], pyproject_path: str) -> list[str]:
    """Return the names of ``[dependency-groups]``, sorted by normalized
    name.

    Group names are normalized per PEP 503 (PEP 735): the first spelling is kept.

    Args:
        data: The parsed pyproject.toml.
        pyproject_path: Path of the file, used in the error message.

    Returns:
        The names, without duplicates; empty if there is no such table.

    Raises:
        MetadataError: If ``[dependency-groups]`` is not a table.
    """
    dependency_groups = get_table(data, "dependency-groups", "[dependency-groups]", pyproject_path)
    unique_groups: dict[str, str] = {}
    for group in sorted(dependency_groups, key=canonicalize_name):
        unique_groups.setdefault(canonicalize_name(group), group)
    return list(unique_groups.values())
