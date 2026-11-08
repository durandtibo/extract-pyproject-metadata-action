"""Tests that a hostile value from ``pyproject.toml`` cannot forge outputs or workflow commands.

The values of the file reach three places: ``$GITHUB_OUTPUT``, the log (workflow commands read
from stdout) and the job summary (``$GITHUB_STEP_SUMMARY``, Markdown). Each test builds a value
that tries to end its container and start something else, then reads the result back.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from extract_pyproject_metadata.cli import _build_parser, main
from extract_pyproject_metadata.output.github import (
    format_outputs,
    format_summary,
    write_github_output,
)
from extract_pyproject_metadata.output.summary import format_step_summary
from extract_pyproject_metadata.report import build_report

HOSTILE_VALUES = [
    "plain",
    "",
    "line 1\nline 2",
    "carriage\rreturn",
    "windows\r\nline break",
    "::error::forged error",
    "first line\n::add-mask::secret",
    "::set-output name=name::forged",
    "name<<EOF\nforged\nEOF",
    "EOF",
    "ghadelimiter_",
    "%0A%0D%25",
    "<script>alert(1)</script> | | `code` [link](http://x) _em_ *b*",
    "unicode: é ☕ 😀 \u2028 \u0085",
    "a" * 100_000,
]


def parse_github_output(content: str) -> dict[str, str]:
    """Parse a ``$GITHUB_OUTPUT`` file like the runner: ``name<<delimiter`` blocks."""
    outputs: dict[str, str] = {}
    lines = content.split("\n")
    index = 0
    while index < len(lines) - 1:  # the file ends with a line break
        name, separator, delimiter = lines[index].partition("<<")
        assert separator, f"not a name<<delimiter line: {lines[index]!r}"
        end = lines.index(delimiter, index + 1)
        assert name not in outputs, f"duplicate output {name!r}"
        outputs[name] = "\n".join(lines[index + 1 : end])
        index = end + 1
    return outputs


@pytest.mark.parametrize("value", HOSTILE_VALUES)
def test_write_github_output_round_trips_a_hostile_value(tmp_path: Path, value: str) -> None:
    path = tmp_path / "output"

    write_github_output(str(path), {"before": "1", "hostile": value, "after": "2"})

    content = path.read_bytes().decode("utf-8")
    assert parse_github_output(content) == {"before": "1", "hostile": value, "after": "2"}


@settings(max_examples=200, deadline=None, derandomize=True)
@given(st.text(alphabet=st.characters(blacklist_categories=("Cs",))))
def test_write_github_output_round_trips_any_value(value: str) -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "output"

        write_github_output(str(path), {"key": value})

        assert parse_github_output(path.read_bytes().decode("utf-8")) == {"key": value}


def test_write_github_output_picks_another_delimiter_when_the_value_contains_it(
    tmp_path: Path,
) -> None:
    delimiters = iter(["DELIM", "DELIM", "OTHER"])
    path = tmp_path / "output"
    value = "first\nDELIM\n::error::forged"

    write_github_output(str(path), {"key": value}, lambda: next(delimiters))

    content = path.read_text(encoding="utf-8")
    assert content == f"key<<OTHER\n{value}\nOTHER\n"
    assert parse_github_output(content) == {"key": value}


def test_write_github_output_picks_another_delimiter_when_the_key_contains_it(
    tmp_path: Path,
) -> None:
    delimiters = iter(["DELIM", "OTHER"])
    path = tmp_path / "output"

    write_github_output(str(path), {"keyDELIM": "value"}, lambda: next(delimiters))

    assert path.read_text(encoding="utf-8") == "keyDELIM<<OTHER\nvalue\nOTHER\n"


def hostile_pyproject(tmp_path: Path) -> Path:
    """Write a pyproject.toml whose free-text fields are all hostile."""
    hostile = "x\n::error::forged\r\n::add-mask::secret\n::set-output name=a::b"
    quoted = json.dumps(hostile)
    path = tmp_path / "pyproject.toml"
    path.write_text(
        "[project]\n"
        'name = "a"\n'
        'version = "1"\n'
        f"description = {quoted}\n"
        f"license = {json.dumps('MIT' + hostile)}\n"
        f"keywords = [{quoted}]\n"
        f"classifiers = [{quoted}]\n"
        f"requires-python = {json.dumps('>=3.11' + hostile)}\n"
        f"authors = [{{name = {quoted}, email = {quoted}}}]\n"
        f"[project.urls]\n{quoted} = {quoted}\n"
        f"[project.scripts]\ncmd = {quoted}\n",
        encoding="utf-8",
    )
    return path


def test_stdout_has_only_the_workflow_commands_of_the_script(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = hostile_pyproject(tmp_path)
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary"))

    status = main(["extract_metadata.py", "--github-output", str(output), "--step-summary", "true", str(path), "[]"])

    assert status == 0
    lines = capsys.readouterr().out.splitlines()
    summaries = [line for line in lines if line.startswith("📦 ")]
    warnings = [line for line in lines if line.startswith("::warning file=")]
    assert len(summaries) == 1
    assert len(summaries) + len(warnings) == len(lines)  # nothing else, in particular no `::error`
    assert warnings  # the invalid license and requires-python
    assert not any(line.startswith(("::error", "::add-mask", "::set-output")) for line in lines)


def test_the_output_file_of_a_hostile_pyproject_reads_back_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = hostile_pyproject(tmp_path)
    output = tmp_path / "output"

    assert main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"]) == 0

    capsys.readouterr()
    expected = format_outputs(build_report(_args(path)))
    assert parse_github_output(output.read_bytes().decode("utf-8")) == expected
    assert expected["description"].startswith("x\n::error::forged\r\n")


def _args(path: Path) -> argparse.Namespace:
    """Parse the command line of the action, with the defaults."""
    return _build_parser("extract_metadata.py").parse_args([str(path), "[]"])


def test_the_log_line_of_a_hostile_pyproject_is_a_single_line(tmp_path: Path) -> None:
    path = hostile_pyproject(tmp_path)
    outputs = format_outputs(build_report(_args(path)))

    summary = format_summary(outputs)

    assert "\n" not in summary
    assert "\r" not in summary


def test_the_job_summary_of_a_hostile_pyproject_stays_a_table(tmp_path: Path) -> None:
    path = hostile_pyproject(tmp_path)
    report = build_report(_args(path))
    outputs = format_outputs(report)

    markdown = format_step_summary(report, outputs)

    rows = [line for line in markdown.splitlines() if line.startswith("| `")]
    assert [row.split("`")[1] for row in rows] == list(outputs)
    for row in rows:
        cell = row.split(" | ", 1)[1]
        assert cell.count("|") == 1  # only the closing pipe of the row
        assert "<script" not in cell
        assert "::" not in cell
    assert not any(line.startswith("::") for line in markdown.splitlines())
