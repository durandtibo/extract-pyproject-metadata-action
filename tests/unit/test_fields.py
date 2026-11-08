"""Tests of ``extract_pyproject_metadata.fields``."""

from __future__ import annotations

import pytest

from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.fields import (
    read_build_system,
    read_extra_names,
    read_string_table,
)


def test_extra_names_without_optional_dependencies() -> None:
    assert read_extra_names({}, ["all"], "p.toml") == ["all"]


def test_extra_names_optional_dependencies_must_be_a_table() -> None:
    with pytest.raises(MetadataError, match=r"^p.toml: \[project\].optional-dependencies must be a table"):
        read_extra_names({"optional-dependencies": []}, [], "p.toml")


def test_string_table() -> None:
    assert read_string_table({"x": {"b": "1", "a": "2"}}, "x", "p.toml") == {"b": "1", "a": "2"}


def test_string_table_absent() -> None:
    assert read_string_table({}, "x", "p.toml") == {}


def test_string_table_returns_a_copy() -> None:
    project = {"x": {"a": "1"}}

    read_string_table(project, "x", "p.toml")["b"] = "2"

    assert project == {"x": {"a": "1"}}


def test_string_table_not_a_table() -> None:
    with pytest.raises(MetadataError, match=r"^p.toml: \[project\.x\] must be a table, got: 1$"):
        read_string_table({"x": 1}, "x", "p.toml")


def test_string_table_not_a_string() -> None:
    with pytest.raises(MetadataError, match=r"^p.toml: \[project\.x\]\.a must be a string, got: 1$"):
        read_string_table({"x": {"a": 1}}, "x", "p.toml")


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({}, ("", [])),
        ({"build-system": {}}, ("", [])),
        ({"build-system": {"requires": ["setuptools>=61", "wheel"]}}, ("", ["setuptools>=61", "wheel"])),
        ({"build-system": {"build-backend": "hatchling.build"}}, ("hatchling.build", [])),
        (
            {"build-system": {"requires": ["a", "a"], "build-backend": "a.b:c", "backend-path": ["."]}},
            ("a.b:c", ["a", "a"]),
        ),
    ],
)
def test_build_system(data: dict, expected: tuple[str, list[str]]) -> None:
    assert read_build_system(data, "p.toml") == expected


def test_build_system_returns_a_copy_of_requires() -> None:
    data = {"build-system": {"requires": ["a"]}}

    read_build_system(data, "p.toml")[1].append("b")

    assert data == {"build-system": {"requires": ["a"]}}


@pytest.mark.parametrize(
    ("data", "match"),
    [
        ({"build-system": "x"}, r"^p.toml: \[build-system\] must be a table, got: 'x'$"),
        ({"build-system": {"build-backend": 1}}, r"^p.toml: \[build-system\].build-backend must be a string, got: 1$"),
        ({"build-system": {"requires": "a"}}, r"^p.toml: \[build-system\].requires must be an array, got: 'a'$"),
        ({"build-system": {"requires": ["a", 1]}}, r"^p.toml: \[build-system\].requires must contain only strings, got: 1$"),
    ],
)
def test_build_system_wrong_type(data: dict, match: str) -> None:
    with pytest.raises(MetadataError, match=match):
        read_build_system(data, "p.toml")


def test_extra_names() -> None:
    project = {"optional-dependencies": {"b": [], "A_x": [], "a-x": []}}

    assert read_extra_names(project, ["", "b"], "p.toml") == ["", "b", "A_x"]
