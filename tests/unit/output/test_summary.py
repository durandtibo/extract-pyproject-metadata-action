"""Tests of ``extract_pyproject_metadata.output.summary``."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

import extract_pyproject_metadata.output.summary as output_summary_module
from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.output.summary import (
    format_error_summary,
    format_warning_summary,
    resolve_summary_path,
    write_step_summary,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_write_step_summary_unwritable_file(tmp_path: Path) -> None:
    with pytest.raises(MetadataError, match=r"cannot write the job summary to .*: "):
        write_step_summary(str(tmp_path), "# Title\n")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("coola", "<code>coola</code>"),
        ("", ""),
        ("a b", "<code>a b</code>"),
        ("a|b", "<code>a&#124;b</code>"),
        ("<b>x</b>", "<code>&#60;b&#62;x&#60;&#47;b&#62;</code>"),
        ("snake_case*", "<code>snake&#95;case&#42;</code>"),
        ("a\nb", "<code>a&#92;nb</code>"),
        ("`x`", "<code>&#96;x&#96;</code>"),
    ],
)
def test_html_cell(value: str, expected: str) -> None:
    assert output_summary_module._html_cell(value) == expected


def test_format_warning_summary_lists_the_warnings() -> None:
    assert format_warning_summary(["first | one", "second"]) == (
        "### ⚠️ Project metadata\n\n- <code>first &#124; one</code>\n- <code>second</code>\n"
    )


def test_write_step_summary_appends(tmp_path: Path) -> None:
    summary = tmp_path / "summary.md"
    summary.write_text("before\n")

    write_step_summary(str(summary), "# Title\n")
    write_step_summary(str(summary), "again\n")

    assert summary.read_text() == "before\n# Title\n\nagain\n\n"


def test_format_error_summary() -> None:
    summary = format_error_summary("p.toml: [project].name | bad\nsecond line")

    assert summary == (
        "### ❌ Project metadata\n"
        "\n"
        "- <code>p&#46;toml&#58; &#91;project&#93;&#46;name &#124; bad</code>\n"
        "- <code>second line</code>\n"
    )


def test_format_error_summary_removes_the_bullet_of_a_line() -> None:
    assert format_error_summary("head:\n- first\n- second") == (
        "### ❌ Project metadata\n\n"
        "- <code>head&#58;</code>\n- <code>first</code>\n- <code>second</code>\n"
    )


def test_format_error_summary_skips_blank_lines() -> None:
    assert format_error_summary("a\n\n  \nb") == (
        "### ❌ Project metadata\n\n- <code>a</code>\n- <code>b</code>\n"
    )


@pytest.mark.parametrize("environ", [{}, {"GITHUB_STEP_SUMMARY": ""}])
def test_resolve_summary_path_outside_a_workflow(environ: dict[str, str]) -> None:
    assert resolve_summary_path(environ) is None


def test_resolve_summary_path() -> None:
    assert resolve_summary_path({"GITHUB_STEP_SUMMARY": "/tmp/s.md"}) == "/tmp/s.md"
