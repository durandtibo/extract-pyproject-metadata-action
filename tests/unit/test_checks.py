"""Tests of ``extract_pyproject_metadata.checks``."""

from __future__ import annotations

import pytest

from extract_pyproject_metadata.checks import (
    check_array,
    check_str,
    check_string_array,
    get_table,
    is_package_name,
)
from extract_pyproject_metadata.errors import MetadataError


@pytest.mark.parametrize("value", [[], ["a"], ["a", "B_c>=1"]])
def test_check_string_array_returns_the_strings(value: list[str]) -> None:
    assert check_string_array(value, "[x]") == value


@pytest.mark.parametrize(
    ("value", "match"),
    [
        ("a", r"^\[x\]: must be an array, got: 'a'"),
        (["a", 2], r"^\[x\]: must contain only strings, got: 2$"),
        ([["a"]], r"^\[x\]: must contain only strings, got: \['a'\]$"),
    ],
)
def test_check_string_array_wrong_types(value: object, match: str) -> None:
    with pytest.raises(MetadataError, match=match):
        check_string_array(value, "[x]")


def test_get_table() -> None:
    assert get_table({"project": {"name": "a"}}, "project", "[project]") == {"name": "a"}


@pytest.mark.parametrize("container", [{}, {"other": 1}])
def test_get_table_absent_is_empty(container: dict) -> None:
    assert get_table(container, "project", "[project]") == {}


@pytest.mark.parametrize("value", [1, "text", [], [{"a": 1}]])
def test_get_table_not_a_table(value: object) -> None:
    with pytest.raises(MetadataError, match=r"^\[project\]: must be a table, got: "):
        get_table({"project": value}, "project", "[project]")


@pytest.mark.parametrize("value", ["text", ""])
def test_check_str(value: str) -> None:
    assert check_str(value, "[x]") == value


@pytest.mark.parametrize(
    ("value", "shown"), [(1, "1"), (None, "None"), (["a"], "\\['a'\\]"), ({"a": 1}, "\\{'a': 1\\}")]
)
def test_check_str_not_a_string(value: object, shown: str) -> None:
    with pytest.raises(MetadataError, match=rf"^\[x\]: must be a string, got: {shown}$"):
        check_str(value, "[x]")


def test_check_array() -> None:
    assert check_array(["a", 1], "[x]") == ["a", 1]


@pytest.mark.parametrize("value", [{}, "text", 1])
def test_check_array_not_an_array(value: object) -> None:
    with pytest.raises(MetadataError, match=r"^\[x\]: must be an array, got: "):
        check_array(value, "[x]")


@pytest.mark.parametrize("name", ["a", "A1", "My_Package.Name", "a-b", "a1", "Numpy_x", "0"])
def test_is_package_name(name: str) -> None:
    assert is_package_name(name)


@pytest.mark.parametrize("name", ["", "my pkg", "-a", "a-", "_a", "a.", "a/b", "a\n", "@a"])
def test_is_not_package_name(name: str) -> None:
    assert not is_package_name(name)
