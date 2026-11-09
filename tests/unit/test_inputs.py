"""Tests of ``extract_pyproject_metadata.inputs``."""

from __future__ import annotations

import pytest

from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.inputs import (
    Options,
    parse_bool,
    parse_options,
    parse_step_summary,
)
from tests.helpers import (
    parse_args,
)


def test_parse_options() -> None:
    args = parse_args(
        "--fail-on-missing",
        "true",
        "--fail-on-dynamic-version",
        " TRUE",
        "--step-summary",
        "true",
        "p.toml",
        "[]",
    )

    assert parse_options(args) == Options(
        fail_on_missing=True, fail_on_dynamic_version=True, strict=False, step_summary="true"
    )


def test_parse_options_defaults() -> None:
    assert parse_options(parse_args("p.toml", "[]")) == Options(False, False, False, "false")


@pytest.mark.parametrize(
    ("option", "name"),
    [
        ("--fail-on-missing", "fail-on-missing"),
        ("--fail-on-dynamic-version", "fail-on-dynamic-version"),
        ("--strict", "strict"),
    ],
)
def test_parse_options_invalid_value(option: str, name: str) -> None:
    with pytest.raises(MetadataError, match=rf"{name} must be 'true' or 'false', got: 'maybe'"):
        parse_options(parse_args(option, "maybe", "p.toml", "[]"))


def test_parse_options_reports_the_first_invalid_value() -> None:
    args = parse_args("--strict", "x", "--fail-on-missing", "y", "p.toml", "[]")

    with pytest.raises(MetadataError, match=r"fail-on-missing must be"):
        parse_options(args)


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
    ("value", "expected"),
    [
        ("true", "true"),
        ("false", "false"),
        ("auto", "auto"),
        (" AUTO ", "auto"),
        ("True", "true"),
    ],
)
def test_parse_step_summary(value: str, expected: str) -> None:
    assert parse_step_summary(value, "step-summary") == expected


@pytest.mark.parametrize("value", ["", "maybe", "yes", "0", "automatic"])
def test_parse_step_summary_invalid(value: str) -> None:
    with pytest.raises(
        MetadataError, match=rf"my-input must be 'true', 'false' or 'auto', got: {value!r}"
    ):
        parse_step_summary(value, "my-input")


def test_parse_options_step_summary_invalid_value() -> None:
    with pytest.raises(
        MetadataError, match=r"step-summary must be 'true', 'false' or 'auto', got: 'maybe'"
    ):
        parse_options(parse_args("--step-summary", "maybe", "p.toml", "[]"))


def test_parse_options_step_summary_auto() -> None:
    assert (
        parse_options(parse_args("--step-summary", "auto", "p.toml", "[]")).step_summary == "auto"
    )
