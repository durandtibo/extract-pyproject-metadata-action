"""Tests of ``extract_pyproject_metadata.output.summary``."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

import extract_pyproject_metadata.output.summary as output_summary_module
from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.output.github import (
    format_outputs,
)
from extract_pyproject_metadata.output.summary import (
    format_error_summary,
    format_step_summary,
    resolve_step_summary,
    write_step_summary,
)
from extract_pyproject_metadata.types import Report

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


def test_format_step_summary_without_warnings() -> None:
    report = Report(
        name="coola",
        normalized_name="coola",
        version="1.2.3",
        normalized_version="1.2.3",
        description="",
        readme="",
        license="",
        license_files=[],
        authors=[],
        urls={},
        keywords=[],
        classifiers=[],
        scripts={},
        requires_python="",
        extras=["", "a"],
        groups=[],
        build_backend="",
        build_requires=[],
        python_versions=["3.12"],
        python_min="3.12",
        python_max="3.12",
        project_dependencies={},
        dependency_specifiers={},
        dependency_requirements={},
        warnings=[],
        schema_version=1,
    )

    assert format_step_summary(report, format_outputs(report)) == (
        "### 📦 Project metadata\n"
        "\n"
        "| Output | Value |\n"
        "| --- | --- |\n"
        "| `name` | <code>coola</code> |\n"
        "| `normalized-name` | <code>coola</code> |\n"
        "| `version` | <code>1&#46;2&#46;3</code> |\n"
        "| `normalized-version` | <code>1&#46;2&#46;3</code> |\n"
        "| `description` |  |\n"
        "| `readme` |  |\n"
        "| `license` |  |\n"
        "| `license-files` | <code>&#91;&#93;</code> |\n"
        "| `authors` | <code>&#91;&#93;</code> |\n"
        "| `urls` | <code>&#123;&#125;</code> |\n"
        "| `keywords` | <code>&#91;&#93;</code> |\n"
        "| `classifiers` | <code>&#91;&#93;</code> |\n"
        "| `scripts` | <code>&#123;&#125;</code> |\n"
        "| `requires-python` |  |\n"
        "| `extras` | <code>&#91;&#34;&#34;&#44;&#34;a&#34;&#93;</code> |\n"
        "| `groups` | <code>&#91;&#93;</code> |\n"
        "| `build-backend` |  |\n"
        "| `build-requires` | <code>&#91;&#93;</code> |\n"
        "| `python-versions` | <code>&#91;&#34;3&#46;12&#34;&#93;</code> |\n"
        "| `python-min` | <code>3&#46;12</code> |\n"
        "| `python-max` | <code>3&#46;12</code> |\n"
        "| `python-matrix` | <code>&#123;&#34;python&#45;version&#34;&#58;&#91;&#34;3&#46;12&#34;&#93;&#125;</code> |\n"
        "| `project-dependencies` | <code>&#123;&#125;</code> |\n"
        "| `dependency-specifiers` | <code>&#123;&#125;</code> |\n"
        "| `dependency-requirements` | <code>&#123;&#125;</code> |\n"
    )


def test_format_step_summary_lists_the_warnings() -> None:
    report = Report(
        name="a",
        normalized_name="a",
        version="1",
        normalized_version="1",
        description="",
        readme="",
        license="",
        license_files=[],
        authors=[],
        urls={},
        keywords=[],
        classifiers=[],
        scripts={},
        requires_python="",
        extras=[],
        groups=[],
        build_backend="",
        build_requires=[],
        python_versions=[],
        python_min="",
        python_max="",
        project_dependencies={},
        dependency_specifiers={},
        dependency_requirements={},
        warnings=["first | one", "second"],
        schema_version=1,
    )

    summary = format_step_summary(report, format_outputs(report))

    assert summary.endswith(
        "\n#### ⚠️ Warnings\n\n- <code>first &#124; one</code>\n- <code>second</code>\n"
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
def test_resolve_step_summary_without_the_environment_variable(environ: dict[str, str]) -> None:
    with pytest.raises(MetadataError, match=r"step-summary is 'true' but .*GITHUB_STEP_SUMMARY"):
        resolve_step_summary(True, environ)
