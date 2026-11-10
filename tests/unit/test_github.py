"""Tests of ``extract_pyproject_metadata.github``."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

import extract_pyproject_metadata.github as output_github_module
from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.github import (
    emit_github_output,
    escape_annotation,
    escape_annotation_property,
    format_log_line,
    format_outputs,
    new_delimiter,
    write_github_output,
)
from extract_pyproject_metadata.report import build_report
from extract_pyproject_metadata.types import Report
from tests.helpers import (
    ACTION_PATH,
    DEPS_TOML,
    METADATA,
    README_PATH,
    action_section_keys,
    parse_github_output,
    parse_inputs_args,
    write_pyproject,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ([], "[]"),
        ({}, "{}"),
        (["a", "b"], '["a","b"]'),
        ({"a": [1, None], "b": {"c": True}}, '{"a":[1,null],"b":{"c":true}}'),
        (["é", "日本"], '["é","日本"]'),
        (['say "hi"\n'], '["say \\"hi\\"\\n"]'),
    ],
)
def test_compact_json(value: object, expected: str) -> None:
    assert output_github_module._compact_json(value) == expected


def test_write_github_output_unwritable_file(tmp_path: Path) -> None:
    with pytest.raises(MetadataError, match=r"GITHUB_OUTPUT: cannot write .*: "):
        write_github_output(str(tmp_path), {"name": "coola"})


def test_format_outputs() -> None:
    outputs = format_outputs(METADATA)
    outputs.pop("json")  # tested below
    assert outputs == {
        "name": "coola",
        "normalized-name": "coola",
        "file-name": "coola",
        "version": "1.2.3",
        "normalized-version": "1.2.3",
        "requires-python": ">=3.10",
        "extras": '["","numpy"]',
        "groups": '["dev","test"]',
        "python-versions": '["3.11","3.12","3.13","3.14","3.15"]',
        "python-min": "3.11",
        "python-max": "3.15",
        "dependency-specifiers": '{"numpy":">=1","missing":null}',
    }


def test_format_outputs_json_is_the_whole_report_in_compact_form() -> None:
    result = format_outputs(METADATA)["json"]

    assert result.startswith(
        '{"name":"coola","normalized_name":"coola","file_name":"coola","version":"1.2.3",'
    )
    assert result.endswith('"warnings":[],"schema_version":1}')
    assert json.loads(result) == METADATA


def test_format_outputs_json_keeps_non_ascii_characters() -> None:
    metadata: Report = {**METADATA, "requires_python": "é"}

    assert '"requires_python":"é"' in format_outputs(metadata)["json"]


def test_format_outputs_keeps_non_ascii_characters() -> None:
    metadata: Report = {**METADATA, "extras": ["é"], "dependency_specifiers": {}}

    assert format_outputs(metadata)["extras"] == '["é"]'


@pytest.mark.parametrize(
    "value",
    ["a\nb", "a\r\nb", "evil\nversion=hacked", "trailing\n", "\n\n", "x<<y", "k=v", "é\n"],
)
def test_write_github_output_round_trips_any_value(tmp_path: Path, value: str) -> None:
    output = tmp_path / "github_output"

    write_github_output(str(output), {"name": value, "version": "1"})

    assert parse_github_output(output.read_bytes().decode("utf-8")) == {
        "name": value,
        "version": "1",
    }


def test_write_github_output_picks_a_delimiter_not_in_the_value(tmp_path: Path) -> None:
    delimiters = iter(["BAD", "GOOD"])
    output = tmp_path / "github_output"

    write_github_output(str(output), {"name": "xBADx"}, lambda: next(delimiters))

    assert output.read_text(encoding="utf-8") == "name<<GOOD\nxBADx\nGOOD\n"


def test_new_delimiter_is_random_and_not_guessable() -> None:
    first, second = new_delimiter(), new_delimiter()

    assert first != second
    assert first.startswith("ghadelimiter_")
    assert len(first) > 32


def test_emit_github_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "github_output"
    report = build_report(
        parse_inputs_args(str(write_pyproject(tmp_path, DEPS_TOML)), "[]", '["missing"]')
    )

    emit_github_output(report, "my,file.toml", str(output))

    out_lines = capsys.readouterr().out.splitlines()
    assert out_lines[0].startswith(
        "::warning file=my%2Cfile.toml,title=dependency-not-found::dependency 'missing' not found"
    )
    assert out_lines[1].startswith("📦 name=p version=1 ")
    assert len(out_lines) == 2
    assert parse_github_output(output.read_text(encoding="utf-8")) == format_outputs(report)


def test_format_outputs_normalized_version() -> None:
    report = Report(
        name="a",
        normalized_name="a",
        file_name="a",
        version="1.0-RC1",
        normalized_version="1.0rc1",
        requires_python="",
        extras=[],
        groups=[],
        python_versions=[],
        python_min="",
        python_max="",
        dependency_specifiers={},
        dependency_requirements={},
        warnings=[],
        schema_version=1,
    )

    outputs = format_outputs(report)

    assert (outputs["version"], outputs["normalized-version"]) == ("1.0-RC1", "1.0rc1")


def test_the_format_of_the_boolean_inputs_is_stated_once_in_the_readme() -> None:
    readme = " ".join(README_PATH.read_text(encoding="utf-8").split())

    assert readme.count("the case and the surrounding spaces are ignored") == 1
    assert "case and surrounding spaces are ignored" not in readme
    assert "surrounding" not in ACTION_PATH.read_text(encoding="utf-8")


def test_action_section_keys_finds_the_inputs_and_outputs() -> None:
    assert "pyproject-path" in action_section_keys("inputs")
    assert "normalized-name" in action_section_keys("outputs")


def test_readme_lists_the_outputs_of_the_log_line() -> None:
    readme = " ".join(README_PATH.read_text(encoding="utf-8").split())
    listed = ", ".join(f"`{field}`" for field in output_github_module._SUMMARY_FIELDS)

    assert f"The line shows {listed}." in readme


def test_log_line_leaves_out_only_derived_outputs() -> None:
    omitted = set(action_section_keys("outputs")) - set(output_github_module._SUMMARY_FIELDS)

    assert omitted == {
        "normalized-name",
        "file-name",
        "normalized-version",
        "json",
    }


def test_format_log_line() -> None:
    assert format_log_line(format_outputs(METADATA)) == (
        "📦 name=coola version=1.2.3 requires-python=>=3.10 "
        'python-versions=["3.11","3.12","3.13","3.14","3.15"] python-min=3.11 python-max=3.15 extras=["","numpy"] '
        'groups=["dev","test"] '
        'dependency-specifiers={"numpy":">=1","missing":null}'
    )


def test_format_log_line_is_one_line_and_escapes_values() -> None:
    outputs = {**format_outputs(METADATA), "requires-python": "a\nb\r\n::error::boom\\"}

    summary = format_log_line(outputs)

    assert "\n" not in summary
    assert "\r" not in summary
    assert "requires-python=a\\nb\\r\\n::error::boom\\\\ " in summary


def test_write_github_output(tmp_path: Path) -> None:
    output = tmp_path / "github_output"

    write_github_output(
        str(output), {"name": "coola", "version": "", "extras": "[]"}, lambda: "DELIM"
    )

    assert output.read_text(encoding="utf-8") == (
        "name<<DELIM\ncoola\nDELIM\nversion<<DELIM\n\nDELIM\nextras<<DELIM\n[]\nDELIM\n"
    )


def test_write_github_output_appends(tmp_path: Path) -> None:
    output = tmp_path / "github_output"
    output.write_text("previous=step\n", encoding="utf-8")

    write_github_output(str(output), {"name": "coola"}, lambda: "DELIM")

    assert output.read_text(encoding="utf-8") == "previous=step\nname<<DELIM\ncoola\nDELIM\n"


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
    assert output_github_module.single_line(value) == expected


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
