"""Tests of ``extract_pyproject_metadata.output.escaping``."""

from __future__ import annotations

import pytest

import extract_pyproject_metadata.output.escaping as output_escaping_module
from extract_pyproject_metadata.output.escaping import escape_annotation, escape_annotation_property


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("plain", "plain"),
        ("", ""),
        ("100%", "100%25"),
        ("a\nb", "a%0Ab"),
        ("a\r\nb", "a%0D%0Ab"),
        ("%0A", "%250A"),
    ],
)
def test_escape_annotation(message: str, expected: str) -> None:
    assert escape_annotation(message) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("plain", "plain"), ("", ""), ("a\nb", "a\\nb"), ("a\r\nb", "a\\r\\nb"), ("a\\nb", "a\\\\nb")],
)
def test_single_line(value: str, expected: str) -> None:
    assert output_escaping_module.single_line(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("pyproject.toml", "pyproject.toml"),
        ("", ""),
        ("sub dir/pyproject.toml", "sub dir/pyproject.toml"),
        ("C:\\pyproject.toml", "C%3A\\pyproject.toml"),
        ("a,b", "a%2Cb"),
        ("a::b", "a%3A%3Ab"),
        ("100%", "100%25"),
        ("a\nb", "a%0Ab"),
        ("a\r\nb", "a%0D%0Ab"),
        ("%3A", "%253A"),
    ],
)
def test_escape_annotation_property(value: str, expected: str) -> None:
    assert escape_annotation_property(value) == expected
