"""Tests of ``extract_pyproject_metadata.inputs``."""

from __future__ import annotations

import json
import re

import pytest

from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.inputs import (
    DEFAULT_PYTHON_CANDIDATES,
    parse_bool,
    parse_dependencies,
    parse_inputs,
    parse_python_candidates,
)
from extract_pyproject_metadata.types import Inputs
from tests.helpers import README_PATH


def test_parse_inputs() -> None:
    raw = {
        "pyproject-path": "sub/pyproject.toml",
        "extra-values": '["", "a"]',
        "dependencies": '["numpy@project"]',
        "python-candidates": '["3.12", "3.12", "3.13"]',
        "strict": " TRUE",
        "resolve-dynamic-version": "TRUE",
    }

    assert parse_inputs(raw) == Inputs(
        pyproject_path="sub/pyproject.toml",
        extra_values=["", "a"],
        dependencies=["numpy@project"],
        python_candidates=["3.12", "3.13"],
        strict=True,
        resolve_dynamic_version=True,
    )


def test_parse_inputs_defaults() -> None:
    assert parse_inputs({}) == Inputs(
        pyproject_path="pyproject.toml",
        extra_values=[],
        dependencies=[],
        python_candidates=["3.11", "3.12", "3.13", "3.14", "3.15"],
        strict=False,
        resolve_dynamic_version=False,
    )


@pytest.mark.parametrize("name", ["strict", "resolve-dynamic-version"])
def test_parse_inputs_invalid_boolean(name: str) -> None:
    with pytest.raises(MetadataError, match=rf"{name} must be 'true' or 'false', got: 'maybe'"):
        parse_inputs({name: "maybe"})


@pytest.mark.parametrize(
    ("name", "value", "match"),
    [
        ("extra-values", "not json", r"extra-values is not valid JSON"),
        ("dependencies", "[1]", r"dependencies must be a JSON array of strings"),
        ("dependencies", '["numpy@dev"]', r"dependencies entry 'numpy@dev' has an invalid scope"),
        ("python-candidates", '["3"]', r"python-candidates must contain 'major.minor'"),
    ],
)
def test_parse_inputs_invalid_array(name: str, value: str, match: str) -> None:
    with pytest.raises(MetadataError, match=match):
        parse_inputs({name: value})


def test_parse_inputs_reports_the_first_invalid_value() -> None:
    with pytest.raises(MetadataError, match=r"^extra-values is not valid JSON"):
        parse_inputs({"strict": "x", "extra-values": "y"})


def test_parse_inputs_does_not_read_the_file() -> None:
    assert parse_inputs({"pyproject-path": "/does/not/exist.toml"}).pyproject_path == (
        "/does/not/exist.toml"
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [("true", True), ("false", False), ("True", True), ("FALSE", False), (" true ", True)],
)
def test_parse_bool(value: str, expected: bool) -> None:
    assert parse_bool(value, "flag") is expected


@pytest.mark.parametrize("value", ["", "yes", "1", "0", "tru", "true false", "null"])
def test_parse_bool_invalid(value: str) -> None:
    with pytest.raises(MetadataError, match=rf"my-input must be 'true' or 'false', got: {value!r}"):
        parse_bool(value, "my-input")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("[]", []),
        ('["3.12"]', ["3.12"]),
        ('["3.10", "3.9", "3.10"]', ["3.10", "3.9"]),
        ('["0.1", "10.20"]', ["0.1", "10.20"]),
        (DEFAULT_PYTHON_CANDIDATES, ["3.11", "3.12", "3.13", "3.14", "3.15"]),
    ],
)
def test_parse_python_candidates(raw: str, expected: list[str]) -> None:
    assert parse_python_candidates(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ['["3"]', '["3.12.1"]', '["3.x"]', '["v3.12"]', '["3.12 "]', '[""]', '["3.1a"]', '["3.12\\n"]'],
)
def test_parse_python_candidates_not_major_minor(raw: str) -> None:
    with pytest.raises(
        MetadataError, match=r"python-candidates must contain 'major.minor' versions"
    ):
        parse_python_candidates(raw)


@pytest.mark.parametrize("raw", ["not json", '{"a": 1}', "[3.12]"])
def test_parse_python_candidates_not_an_array_of_strings(raw: str) -> None:
    with pytest.raises(
        MetadataError, match=r"python-candidates (is not valid JSON|must be a JSON array)"
    ):
        parse_python_candidates(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "[]",
        '["numpy", "NumPy"]',
        '["numpy@project"]',
        '["numpy@extra:x", "numpy@group:dev"]',
        '["a@extra:with:colon", "a@group:Dev_Tools"]',
    ],
)
def test_parse_dependencies(raw: str) -> None:
    assert parse_dependencies(raw) == json.loads(raw)


@pytest.mark.parametrize(
    "entry",
    [
        "numpy@dev",
        "numpy@",
        "numpy@extra",
        "numpy@extra:",
        "numpy@group:",
        "numpy@Project",
        "numpy@feature:x",
        "numpy@@project",
    ],
)
def test_parse_dependencies_invalid_scope(entry: str) -> None:
    with pytest.raises(
        MetadataError, match=rf"^dependencies entry {re.escape(repr(entry))} has an invalid scope: "
    ):
        parse_dependencies(json.dumps([entry]))


@pytest.mark.parametrize("raw", ["not json", '{"a": 1}', "[1]"])
def test_parse_dependencies_not_an_array_of_strings(raw: str) -> None:
    with pytest.raises(
        MetadataError, match=r"^dependencies (is not valid JSON|must be a JSON array of strings)"
    ):
        parse_dependencies(raw)


def test_readme_default_of_python_candidates_matches_the_script() -> None:
    readme = README_PATH.read_text(encoding="utf-8")

    assert f"| `{DEFAULT_PYTHON_CANDIDATES}` |" in readme
