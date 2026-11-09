"""Reading of the optional fields of ``[project]`` and ``[build-
system]``."""

from __future__ import annotations

from typing import Any, cast

from packaging.utils import canonicalize_name

from extract_pyproject_metadata.checks import check_array, check_str, check_string_array, get_table
from extract_pyproject_metadata.errors import MetadataError

__all__ = [
    "read_authors",
    "read_build_system",
    "read_extra_names",
    "read_group_names",
    "read_readme_path",
    "read_string_table",
    "read_urls",
]


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


def read_build_system(data: dict[str, Any], pyproject_path: str) -> tuple[str, list[str]]:
    """Return the build backend and the build requirements of ``[build-
    system]``.

    Args:
        data: The parsed pyproject.toml.
        pyproject_path: Path of the file, used in the error messages.

    Returns:
        A tuple ``(build_backend, build_requires)``: ``build-backend`` as written
        (an empty string if there is none) and the ``requires`` array as written
        (empty if there is none). Both are empty if there is no ``[build-system]``.

    Raises:
        MetadataError: If ``[build-system]`` is not a table, ``build-backend`` is
            not a string or ``requires`` is not an array of strings.
    """
    table = get_table(data, "build-system", "[build-system]", pyproject_path)
    build_backend = check_str(
        table.get("build-backend", ""), "[build-system].build-backend", pyproject_path
    )
    requires = check_string_array(
        table.get("requires", []), "[build-system].requires", pyproject_path
    )
    return build_backend, list(requires)


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


def read_readme_path(readme: object, pyproject_path: str) -> str:
    """Return the path of the readme file declared by
    ``[project].readme``.

    Args:
        readme: The value of ``[project].readme``: a path (string), or a table
            with a ``file`` (path) or a ``text`` (the readme itself) and a
            ``content-type``.
        pyproject_path: Path of the file, used in the error message.

    Returns:
        The path as written, or an empty string if ``readme`` is empty, is not
        declared, or is a table without ``file`` (inline ``text``).

    Raises:
        MetadataError: If ``readme`` is neither a string nor a table, or its
            ``file`` is not a string.
    """
    if isinstance(readme, str):
        return readme
    if not isinstance(readme, dict):
        msg = f"{pyproject_path}: [project].readme must be a string or a table, got: {readme!r}"
        raise MetadataError(msg)
    table = cast("dict[str, Any]", readme)
    return check_str(table.get("file", ""), "[project].readme.file", pyproject_path)


def read_authors(authors: object, pyproject_path: str) -> list[dict[str, str]]:
    """Return the authors declared by ``[project].authors``.

    Args:
        authors: The value of ``[project].authors``: an array of tables with an
            optional ``name`` and an optional ``email`` (strings).
        pyproject_path: Path of the file, used in the error messages.

    Returns:
        One dict per author, in order, with the ``name`` and ``email`` that the
        author has (in this order). Other keys are ignored.

    Raises:
        MetadataError: If ``authors`` is not an array, an author is not a
            table, or a ``name`` or an ``email`` is not a string.
    """
    result: list[dict[str, str]] = []
    for index, author in enumerate(check_array(authors, "[project].authors", pyproject_path)):
        label = f"[project].authors[{index}]"
        if not isinstance(author, dict):
            msg = f"{pyproject_path}: {label} must be a table, got: {author!r}"
            raise MetadataError(msg)
        fields = cast("dict[str, Any]", author)
        entry: dict[str, str] = {}
        for key in ("name", "email"):
            if key not in fields:
                continue
            entry[key] = check_str(fields[key], f"{label}.{key}", pyproject_path)
        result.append(entry)
    return result


def read_urls(project: dict[str, Any], pyproject_path: str) -> dict[str, str]:
    """Return the project URLs of ``[project.urls]``.

    Args:
        project: The ``[project]`` table.
        pyproject_path: Path of the file, used in the error messages.

    Returns:
        The label of each URL and the URL, as written and in the order of the
        file. Empty if there is no ``[project.urls]``.

    Raises:
        MetadataError: If ``[project.urls]`` is not a table or a URL is not a
            string.
    """
    return read_string_table(project, "urls", pyproject_path)


def read_string_table(project: dict[str, Any], key: str, pyproject_path: str) -> dict[str, str]:
    """Return a table of ``[project]`` whose values are strings, such as
    ``[project.urls]``.

    Args:
        project: The ``[project]`` table.
        key: The key of the table, such as ``"scripts"``.
        pyproject_path: Path of the file, used in the error messages.

    Returns:
        The keys and the values as written, in the order of the file. Empty if
        there is no such table.

    Raises:
        MetadataError: If the table is not a table or a value is not a string.
    """
    table = get_table(project, key, f"[project.{key}]", pyproject_path)
    for name, value in table.items():
        check_str(value, f"[project.{key}].{name}", pyproject_path)
    return dict(table)
