"""Tests of ``extract_pyproject_metadata.checks``."""

from __future__ import annotations

import pytest

from extract_pyproject_metadata.checks import check_array, check_str, check_string_array, get_table
from extract_pyproject_metadata.errors import MetadataError


@pytest.mark.parametrize("value", [[], ["a"], ["a", "B_c>=1"]])
def test_check_string_array_returns_the_strings(value: list[str]) -> None:
    assert check_string_array(value, "[x]", "p.toml") == value


@pytest.mark.parametrize(
    ("value", "match"),
    [
        ("a", r"^p\.toml: \[x\] must be an array, got: 'a'"),
        (["a", 2], r"^p\.toml: \[x\] must contain only strings, got: 2$"),
        ([["a"]], r"^p\.toml: \[x\] must contain only strings, got: \['a'\]$"),
    ],
)
def test_check_string_array_wrong_types(value: object, match: str) -> None:
    with pytest.raises(MetadataError, match=match):
        check_string_array(value, "[x]", "p.toml")


def test_get_table() -> None:
    assert get_table({"project": {"name": "a"}}, "project", "[project]", "p.toml") == {"name": "a"}


@pytest.mark.parametrize("container", [{}, {"other": 1}])
def test_get_table_absent_is_empty(container: dict) -> None:
    assert get_table(container, "project", "[project]", "p.toml") == {}


@pytest.mark.parametrize("value", [1, "text", [], [{"a": 1}]])
def test_get_table_not_a_table(value: object) -> None:
    with pytest.raises(MetadataError, match=r"^p.toml: \[project\] must be a table, got: "):
        get_table({"project": value}, "project", "[project]", "p.toml")


@pytest.mark.parametrize("value", ["text", ""])
def test_check_str(value: str) -> None:
    assert check_str(value, "[x]", "p.toml") == value


@pytest.mark.parametrize(
    ("value", "shown"), [(1, "1"), (None, "None"), (["a"], "\\['a'\\]"), ({"a": 1}, "\\{'a': 1\\}")]
)
def test_check_str_not_a_string(value: object, shown: str) -> None:
    with pytest.raises(MetadataError, match=rf"^p.toml: \[x\] must be a string, got: {shown}$"):
        check_str(value, "[x]", "p.toml")


def test_check_array() -> None:
    assert check_array(["a", 1], "[x]", "p.toml") == ["a", 1]


@pytest.mark.parametrize("value", [{}, "text", 1])
def test_check_array_not_an_array(value: object) -> None:
    with pytest.raises(MetadataError, match=r"^p.toml: \[x\] must be an array, got: "):
        check_array(value, "[x]", "p.toml")
