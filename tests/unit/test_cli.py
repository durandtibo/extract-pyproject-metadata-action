"""Tests of ``extract_pyproject_metadata.cli``: ``main`` and the
options."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

import extract_pyproject_metadata.cli as extract_metadata_module
import extract_pyproject_metadata.dependencies.requirements as dependencies_requirements_module
import extract_pyproject_metadata.report as report_module
from extract_pyproject_metadata.cli import main, parse_cli_inputs
from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.inputs import parse_inputs
from extract_pyproject_metadata.output.github import (
    format_error,
)
from extract_pyproject_metadata.pyproject import load_pyproject
from extract_pyproject_metadata.types import Report
from tests.helpers import (
    DATA_WITH_SCOPES,
    DEPS_TOML,
    GROUPS_TOML,
    _specifier_error,
    parse_args,
    parse_github_output,
    write_pyproject,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_report_keys_match_the_json_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')

    assert main(["extract_metadata.py", str(path), "[]"]) == 0

    assert list(json.loads(capsys.readouterr().out)) == list(Report.__annotations__)


def test_github_output_has_no_schema_version(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')
    output = tmp_path / "out"

    assert main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"]) == 0
    assert "schema-version" not in parse_github_output(output.read_text(encoding="utf-8"))


def test_main_returns_one_for_an_invalid_utf8_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_bytes(b"\xff\xfe")

    assert main(["extract_metadata.py", str(path), "[]"]) == 1
    assert "is not valid UTF-8" in capsys.readouterr().err


def test_main_returns_one_when_the_outputs_cannot_be_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')

    exit_code = main(["extract_metadata.py", "--github-output", str(tmp_path), str(path), "[]"])

    assert exit_code == 1
    assert "::error file=" in capsys.readouterr().err


def test_main_returns_one_when_the_job_summary_cannot_be_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path))
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\ndynamic = ["version"]\n'
    )  # a warning, so the summary is written

    exit_code = main(["extract_metadata.py", str(path), "[]"])

    assert exit_code == 1
    assert "cannot write the job summary" in capsys.readouterr().err


def test_main_reports_the_error_once_when_the_job_summary_cannot_be_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path))
    path = write_pyproject(tmp_path, '[project]\nversion = "1"\n')

    exit_code = main(["extract_metadata.py", str(path), "[]"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "missing required key" in err
    assert "cannot write the job summary" not in err


def test_main_json_keeps_non_ascii_characters(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = "Héllo ✓"\n'
    )

    assert main(["extract_metadata.py", str(path), "[]"]) == 0

    out = capsys.readouterr().out
    assert '"requires_python": "Héllo ✓"' in out
    assert "\\u" not in out


def test_main_strict_fails_on_a_static_and_dynamic_field(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "coola"\nversion = "1"\ndynamic = ["version"]\n'
    )

    assert main(["extract_metadata.py", "--strict", "true", str(path), "[]"]) == 1
    assert (
        "[project].version is set and also listed in [project].dynamic" in capsys.readouterr().err
    )


def test_main_dynamic_version_warning_in_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\ndynamic = ["version"]\n')

    exit_code = main(["extract_metadata.py", str(path), "[]"])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "name": "coola",
        "normalized_name": "coola",
        "file_name": "coola",
        "version": "",
        "normalized_version": "",
        "requires_python": "",
        "extras": [],
        "groups": [],
        "python_versions": ["3.11", "3.12", "3.13", "3.14", "3.15"],
        "python_min": "3.11",
        "python_max": "3.15",
        "dependency_specifiers": {},
        "dependency_requirements": {},
        "warnings": [f"{path}: [project].version is dynamic, the version output is empty"],
        "schema_version": 1,
    }


def test_main_prints_json_to_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [project]
        name = "coola"
        version = "1.2.3"
        """,
    )

    exit_code = main(["extract_metadata.py", str(path), "[]"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert json.loads(captured.out) == {
        "name": "coola",
        "normalized_name": "coola",
        "file_name": "coola",
        "version": "1.2.3",
        "normalized_version": "1.2.3",
        "requires_python": "",
        "extras": [],
        "groups": [],
        "python_versions": ["3.11", "3.12", "3.13", "3.14", "3.15"],
        "python_min": "3.11",
        "python_max": "3.15",
        "dependency_specifiers": {},
        "dependency_requirements": {},
        "warnings": [],
        "schema_version": 1,
    }


def test_main_parses_the_file_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')
    calls: list[str] = []

    def counting_load(pyproject_path: str) -> dict:
        calls.append(pyproject_path)
        return load_pyproject(pyproject_path)

    monkeypatch.setattr(report_module, "load_pyproject", counting_load)

    exit_code = main(["extract_metadata.py", str(path), "[]", '["numpy"]'])
    capsys.readouterr()

    assert exit_code == 0
    assert calls == [str(path)]


def test_main_returns_nonzero_on_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "does-not-exist.toml"

    exit_code = main(["extract_metadata.py", str(missing), "[]"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "not found" in captured.err


def test_main_returns_usage_error_on_bad_args() -> None:
    exit_code = main(["extract_metadata.py"])

    assert exit_code == 2


def test_main_prints_the_usage_error_on_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["extract_metadata.py"]) == 2

    err = capsys.readouterr().err
    assert err.startswith("usage: extract_metadata.py [-h]")
    assert err.endswith(
        "\nextract_metadata.py: error: the following arguments are required: "
        "pyproject_path, extra_values\n"
    )


@pytest.mark.parametrize("option", [["--github-output", "out"], ["--github-output=out"]])
def test_main_annotates_the_usage_error_with_github_output(
    option: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["extract_metadata.py", *option]) == 2

    err = capsys.readouterr().err
    assert err.startswith("::error::usage: extract_metadata.py [-h]")
    assert err.endswith(
        "%0Aextract_metadata.py: error: the following arguments are required: "
        "pyproject_path, extra_values\n"
    )
    assert err.count("\n") == 1


def test_main_help_exits_with_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["extract_metadata.py", "--github-output", "out", "--help"]) == 0

    assert capsys.readouterr().out.startswith("usage: extract_metadata.py [-h]")


def test_main_outputs_warnings_in_json_and_nothing_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)

    exit_code = main(["extract_metadata.py", str(path), "[]", '["dup"]'])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert json.loads(captured.out)["warnings"] == [
        f"dup has different specifiers in {path}: ['>=1', '>=2']; using '>=1'"
    ]
    assert captured.err == ""


def test_main_github_output_writes_outputs_and_annotations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    output = tmp_path / "github_output"

    exit_code = main(
        [
            "extract_metadata.py",
            "--github-output",
            str(output),
            str(path),
            '[""]',
            '["dup", "nospec", "missing"]',
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    outputs = parse_github_output(output.read_text(encoding="utf-8"))
    report = json.loads(outputs.pop("json"))
    assert list(report) == list(Report.__annotations__)
    assert report["name"] == "p"
    assert report["extras"] == ["", "a"]
    assert outputs == {
        "name": "p",
        "normalized-name": "p",
        "file-name": "p",
        "version": "1",
        "normalized-version": "1",
        "requires-python": "",
        "extras": '["","a"]',
        "groups": '["base","dev","other"]',
        "python-versions": '["3.11","3.12","3.13","3.14","3.15"]',
        "python-min": "3.11",
        "python-max": "3.15",
        "dependency-specifiers": '{"dup":">=1","nospec":"","missing":null}',
    }
    assert captured.out == (
        f"::warning file={path}::dup has different specifiers in {path}: ['>=1', '>=2']; using '>=1'\n"
        f"::warning file={path}::{path}: dependency 'missing' not found\n"
        "📦 name=p version=1 requires-python= "
        'python-versions=["3.11","3.12","3.13","3.14","3.15"] python-min=3.11 python-max=3.15 extras=["","a"] '
        'groups=["base","dev","other"] '
        'dependency-specifiers={"dup":">=1","nospec":"","missing":null}\n'
    )
    assert captured.err == ""


def test_main_strict_fails_without_writing_the_outputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    output = tmp_path / "out"

    exit_code = main(
        [
            "extract_metadata.py",
            "--github-output",
            str(output),
            "--strict",
            "true",
            str(path),
            "[]",
            '["dup"]',
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.err.startswith(
        f"::error file={path}::strict is 'true' and there are 1 warning(s):%0A- dup"
    )
    assert captured.out == ""
    assert not output.exists()


def test_main_invalid_strict_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    assert main(["extract_metadata.py", "--strict", "maybe", str(path), "[]"]) == 1
    assert "strict must be 'true' or 'false', got: 'maybe'" in capsys.readouterr().err


def test_parse_cli_inputs_maps_every_option() -> None:
    args = parse_args(
        "--strict", "true", "--python-candidates", '["3.12"]',
        "--resolve-dynamic-version", "true", "p.toml", '["a"]', '["numpy"]',
    )  # fmt: skip

    assert parse_cli_inputs(args) == parse_inputs(
        {
            "pyproject-path": "p.toml",
            "extra-values": '["a"]',
            "dependencies": '["numpy"]',
            "python-candidates": '["3.12"]',
            "strict": "true",
            "resolve-dynamic-version": "true",
        }
    )


def test_parse_cli_inputs_invalid_value() -> None:
    with pytest.raises(MetadataError, match=r"strict must be 'true' or 'false', got: 'maybe'"):
        parse_cli_inputs(parse_args("--strict", "maybe", "p.toml", "[]"))


def test_main_summary_lists_the_warnings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    path = write_pyproject(tmp_path, DEPS_TOML)

    exit_code = main(
        [
            "extract_metadata.py",
            "--github-output",
            str(tmp_path / "out"),
            str(path),
            "[]",
            '["missing"]',
        ]
    )

    assert exit_code == 0
    text = summary.read_text(encoding="utf-8")
    assert text.startswith("### ⚠️ Project metadata\n\n- <code>")
    assert "dependency &#39;missing&#39; not found</code>\n" in text
    capsys.readouterr()


def test_main_summary_reports_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    path = write_pyproject(tmp_path, '[project]\nversion = "1"\n')

    exit_code = main(["extract_metadata.py", str(path), "[]"])

    assert exit_code == 1
    text = summary.read_text(encoding="utf-8")
    assert text.startswith("### ❌ Project metadata\n")
    assert "missing required key" in text
    assert "&#91;project&#93;&#46;name" in text
    assert "missing required key" in capsys.readouterr().err


def test_main_summary_lists_the_warnings_of_a_strict_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    path = write_pyproject(tmp_path, '[project]\nname = "a"\ndynamic = ["version"]\n')

    exit_code = main(["extract_metadata.py", "--strict", "true", str(path), "[]"])

    assert exit_code == 1
    text = summary.read_text(encoding="utf-8")
    assert text.startswith("### ❌ Project metadata\n")
    assert "there are 1 warning&#40;s&#41;&#58;</code>\n- <code>" in text
    assert "<code>&#45;" not in text
    assert "[project].version is dynamic" not in text  # escaped, not raw


def test_main_summary_writes_nothing_without_warnings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert not summary.exists()


def test_main_summary_writes_nothing_outside_a_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    path = write_pyproject(tmp_path, '[project]\nname = "a"\ndynamic = ["version"]\n')

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["name"] == "a"


@pytest.mark.parametrize(
    "option", ["--step-summary", "--fail-on-missing", "--fail-on-dynamic-version"]
)
def test_main_removed_options_are_usage_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], option: str
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    assert main(["extract_metadata.py", option, "true", str(path), "[]"]) == 2
    assert (
        "unrecognized arguments" in capsys.readouterr().err or "usage:" in capsys.readouterr().err
    )


@pytest.mark.parametrize(
    ("message", "pyproject_path", "annotate", "expected"),
    [
        ("boom", "p.toml", False, "boom"),
        ("a\nb", "p.toml", False, "a\nb"),
        ("boom", "p.toml", True, "::error file=p.toml::boom"),
        ("50%\nnext\r", "a,b:c.toml", True, "::error file=a%2Cb%3Ac.toml::50%25%0Anext%0D"),
    ],
)
def test_format_error(message: str, pyproject_path: str, annotate: bool, expected: str) -> None:
    assert format_error(message, pyproject_path, annotate) == expected


def test_main_error_is_a_plain_message_without_github_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "nope.toml"

    assert main(["extract_metadata.py", str(path), "[]"]) == 1
    captured = capsys.readouterr()

    assert captured.err == f"pyproject.toml not found at: {path}\n"
    assert captured.out == ""


def test_main_error_is_an_annotation_with_github_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "nope.toml"

    exit_code = main(
        ["extract_metadata.py", "--github-output", str(tmp_path / "out"), str(path), "[]"]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.err == f"::error file={path}::pyproject.toml not found at: {path}\n"


def test_main_error_annotation_cannot_inject_a_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = 3\n')

    exit_code = main(
        ["extract_metadata.py", "--github-output", str(tmp_path / "out"), str(path), "[]"]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert len(captured.err.splitlines()) == 1
    assert captured.err.startswith("::error file=")


def test_main_github_output_error_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "github_output"

    exit_code = main(
        ["extract_metadata.py", "--github-output", str(output), str(tmp_path / "nope.toml"), "[]"]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "not found" in captured.err
    assert captured.out == ""
    assert not output.exists()


@pytest.mark.parametrize(
    "argv",
    [
        ["extract_metadata.py", "--github-output"],
        ["extract_metadata.py", "--github-output", "out"],
        ["extract_metadata.py", "--github-output", "out", "a", "[]", "[]", "extra"],
        ["extract_metadata.py", "--unknown", "a", "[]"],
    ],
)
def test_main_usage_errors_with_options(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(argv) == 2
    assert "usage:" in capsys.readouterr().err


def test_main_github_output_multiline_name_is_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "evil\\n::error::boom\\nversion=hacked"\nversion = "1"\n',
    )
    output = tmp_path / "github_output"

    exit_code = main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert not output.exists()
    assert captured.out == ""
    assert len(captured.err.splitlines()) == 1
    assert "[project].name is not a valid project name" in captured.err


@pytest.mark.parametrize(
    ("argv_tail", "message"),
    [
        (["[]", "not json"], "dependencies is not valid JSON"),
        (["[]", '{"a": 1}'], "dependencies must be a JSON array of strings"),
        (["not json"], "extra-values is not valid JSON"),
        (["{}"], "extra-values must be a JSON array"),
        (["[1]"], "extra-values must be a JSON array of strings"),
    ],
)
def test_main_invalid_inputs_return_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv_tail: list[str], message: str
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')

    exit_code = main(["extract_metadata.py", str(path), *argv_tail])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert message in captured.err
    assert captured.out == ""


@pytest.mark.parametrize(
    "argv",
    [
        ["extract_metadata.py", "a"],
        ["extract_metadata.py", "a", "[]", "[]", "extra"],
    ],
)
def test_main_wrong_number_of_arguments_returns_two(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(argv) == 2
    assert "usage:" in capsys.readouterr().err


def test_main_unknown_group_entry_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "coola"\nversion = "1"\n\n[dependency-groups]\ndev = [{include_group = "a"}]\n',
    )

    assert main(["extract_metadata.py", str(path), "[]", '["x"]']) == 1
    assert "[dependency-groups].dev entries must be strings or" in capsys.readouterr().err


def test_main_malformed_dependency_table_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "p"\nversion = "1"\n[dependency-groups]\ndev = "numpy"\n'
    )

    exit_code = main(["extract_metadata.py", str(path), "[]", '["numpy"]'])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "[dependency-groups].dev must be an array" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


def test_main_include_group_cycle_warning_annotation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "p"\nversion = "1"\n[dependency-groups]\na = [{include-group = "a"}]\n',
    )
    output = tmp_path / "github_output"

    exit_code = main(
        ["extract_metadata.py", "--github-output", str(output), str(path), "[]", '["x"]']
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out.splitlines()[0] == (
        f"::warning file={path}::{path}: [dependency-groups] has an include-group cycle: a -> a"
    )


def test_main_warning_annotation_escapes_the_file_property(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "a,b:c"
    directory.mkdir()
    path = directory / "pyproject.toml"
    path.write_text('[project]\nname = "p"\ndynamic = ["version"]\n')
    output = tmp_path / "github_output"

    exit_code = main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"])
    captured = capsys.readouterr()

    escaped = str(path).replace("%", "%25").replace(":", "%3A").replace(",", "%2C")
    assert exit_code == 0
    assert captured.out.splitlines()[0] == (
        f"::warning file={escaped}::{path}: [project].version is dynamic, "
        "the version output is empty"
    )


def test_main_warning_annotation_names_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    write_pyproject(tmp_path, '[project]\nname = "p"\ndynamic = ["version"]\n')
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        ["extract_metadata.py", "--github-output", str(tmp_path / "out"), "pyproject.toml", "[]"]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.splitlines()[0] == (
        "::warning file=pyproject.toml::pyproject.toml: [project].version is dynamic, "
        "the version output is empty"
    )


def test_main_invalid_version_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "p"\nversion = "latest"\n')

    exit_code = main(["extract_metadata.py", str(path), "[]"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "is not a valid PEP 440 version: 'latest'" in captured.err
    assert captured.out == ""


def test_main_github_output_normalized_name(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "My_Package.Name"\nversion = "1"\n')
    output = tmp_path / "github_output"

    exit_code = main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"])

    assert exit_code == 0
    outputs = parse_github_output(output.read_text(encoding="utf-8"))
    assert outputs["name"] == "My_Package.Name"
    assert outputs["normalized-name"] == "my-package-name"


def test_main_github_output_requires_python(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "p"\nversion = "1"\nrequires-python = ">=3.10,<4"\n'
    )
    output = tmp_path / "github_output"

    exit_code = main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"])

    assert exit_code == 0
    assert parse_github_output(output.read_text(encoding="utf-8"))["requires-python"] == ">=3.10,<4"


def test_main_json_requires_python(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "p"\nversion = "1"\nrequires-python = ">=3.10"\n'
    )

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["requires_python"] == ">=3.10"


def test_main_github_output_groups(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, GROUPS_TOML)
    output = tmp_path / "github_output"

    exit_code = main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"])

    assert exit_code == 0
    assert (
        parse_github_output(output.read_text(encoding="utf-8"))["groups"] == '["Dev","docs","test"]'
    )


def test_main_json_groups(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_pyproject(tmp_path, GROUPS_TOML)

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["groups"] == ["Dev", "docs", "test"]


def test_main_missing_dependency_is_a_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    output = tmp_path / "github_output"

    exit_code = main(
        [
            "extract_metadata.py",
            "--github-output",
            str(output),
            str(path),
            "[]",
            '["nospec", "missing"]',
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert parse_github_output(output.read_text(encoding="utf-8"))["dependency-specifiers"] == (
        '{"nospec":"","missing":null}'
    )
    assert f"::warning file={path}::{path}: dependency 'missing' not found" in captured.out


def test_main_strict_fails_for_a_missing_dependency(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    output = tmp_path / "github_output"

    exit_code = main(
        [
            "extract_metadata.py",
            "--github-output",
            str(output),
            "--strict",
            "true",
            str(path),
            "[]",
            '["nospec", "missing", "other"]',
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.err == (
        f"::error file={path}::strict is 'true' and there are 2 warning(s):"
        f"%0A- {path}: dependency 'missing' not found"
        f"%0A- {path}: dependency 'other' not found\n"
    )
    assert captured.out == ""
    assert not output.exists()


def test_main_no_warning_when_all_the_dependencies_are_found(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)

    exit_code = main(["extract_metadata.py", "--strict", "true", str(path), "[]", '["nospec"]'])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["dependency_specifiers"] == {"nospec": ""}


def test_main_missing_dependency_with_dynamic_dependencies_warns_twice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\ndynamic = ["dependencies"]\n'
    )

    exit_code = main(["extract_metadata.py", str(path), "[]", '["numpy"]'])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["warnings"] == [
        (
            f"{path}: [project].dependencies is dynamic, it cannot be read, so no requirement is "
            "found in it"
        ),
        f"{path}: dependency 'numpy' not found",
    ]


def test_main_github_output_normalized_version(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1.0-RC1"\n')
    output = tmp_path / "out"

    assert main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"]) == 0
    values = parse_github_output(output.read_text(encoding="utf-8"))
    assert (values["version"], values["normalized-version"]) == ("1.0-RC1", "1.0rc1")


def test_main_json_has_a_schema_version(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert (
        json.loads(capsys.readouterr().out)["schema_version"] == report_module.SCHEMA_VERSION == 1
    )


def test_main_python_max_in_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = "<3.13"\n'
    )

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["python_max"] == "3.12"


def test_main_python_max_is_empty_without_allowed_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = ">=4"\n'
    )

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert (report["python_versions"], report["python_max"]) == ([], "")


def test_main_warns_when_no_python_version_is_allowed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = ">=4"\n'
    )

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["warnings"] == [
        (
            f"{path}: no python-candidates version satisfies [project].requires-python ('>=4'): "
            "python-versions is empty, and a job matrix built from it is rejected by GitHub"
        )
    ]


def test_main_strict_fails_when_no_python_version_is_allowed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = ">=4"\n'
    )

    assert main(["extract_metadata.py", "--strict", "true", str(path), "[]"]) == 1
    assert "strict is 'true' and there are 1 warning(s)" in capsys.readouterr().err


def test_main_python_max_compares_versions_as_numbers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    assert (
        main(["extract_metadata.py", "--python-candidates", '["3.9","3.10"]', str(path), "[]"]) == 0
    )
    assert json.loads(capsys.readouterr().out)["python_max"] == "3.10"


def test_main_github_output_python_max(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = ">=3.11,<3.14"\n'
    )
    output = tmp_path / "out"

    assert main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"]) == 0
    assert parse_github_output(output.read_text(encoding="utf-8"))["python-max"] == "3.13"


def test_main_python_min_in_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = ">=3.11,<3.13"\n'
    )

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["python_min"] == "3.11"


def test_main_python_min_is_empty_without_allowed_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = ">=4"\n'
    )

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert (report["python_versions"], report["python_min"]) == ([], "")


def test_main_python_min_compares_versions_as_numbers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    exit_code = main(
        ["extract_metadata.py", "--python-candidates", '["3.10","3.9"]', str(path), "[]"]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["python_min"] == "3.9"


def test_main_github_output_python_min(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = ">=3.13"\n'
    )
    output = tmp_path / "github_output"

    assert main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"]) == 0
    assert parse_github_output(output.read_text(encoding="utf-8"))["python-min"] == "3.13"


def test_main_python_versions_in_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = ">=3.11,<3.13"\n'
    )

    exit_code = main(["extract_metadata.py", str(path), "[]"])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["python_versions"] == ["3.11", "3.12"]


def test_main_python_candidates_option(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = ">=3.9"\n'
    )

    exit_code = main(
        ["extract_metadata.py", "--python-candidates", '["3.8","3.9","3.15"]', str(path), "[]"]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["python_versions"] == ["3.9", "3.15"]


def test_main_invalid_requires_python_specifier_warns_and_gives_no_versions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = "python3"\n'
    )

    exit_code = main(["extract_metadata.py", str(path), "[]"])
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert report["python_versions"] == []
    assert len(report["warnings"]) == 1
    assert "requires-python is not a valid version specifier" in report["warnings"][0]


def test_main_github_output_python_versions(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = ">=3.13"\n'
    )
    output = tmp_path / "github_output"

    exit_code = main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"])

    assert exit_code == 0
    assert parse_github_output(output.read_text(encoding="utf-8"))["python-versions"] == (
        '["3.13","3.14","3.15"]'
    )


@pytest.mark.parametrize("raw", ['["3.12.1"]', "not json"])
def test_main_invalid_python_candidates_return_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], raw: str
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    exit_code = main(["extract_metadata.py", "--python-candidates", raw, str(path), "[]"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "python-candidates" in captured.err
    assert captured.out == ""


def test_main_warnings_are_in_the_order_of_the_sources(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "a"\ndynamic = ["version"]\nrequires-python = "python3"\n'
        'dependencies = ["x>=1", "x>=2"]\n\n[dependency-groups]\ndev = ["x>=3", "not valid!"]\n',
    )

    assert main(["extract_metadata.py", str(path), "[]", '["x"]']) == 0
    warnings = json.loads(capsys.readouterr().out)["warnings"]
    assert len(warnings) == 4
    # The metadata, the Python versions, then the lookups.
    assert warnings[:2] == [
        f"{path}: [project].version is dynamic, the version output is empty",
        (
            f"{path}: [project].requires-python is not a valid version specifier, "
            f"the python-versions output is empty: {_specifier_error('python3')}"
        ),
    ]
    assert warnings[2].startswith(f"Ignoring invalid requirement 'not valid!' in {path}: ")
    assert (
        warnings[3] == f"x has different specifiers in {path}: ['>=1', '>=2', '>=3']; using '>=1'"
    )


def test_main_dependency_requirements_with_a_scope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DATA_WITH_SCOPES)

    assert (
        main(
            [
                "extract_metadata.py",
                str(path),
                "[]",
                '["numpy", "numpy@extra:slow", "pytest@group:dev"]',
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["dependency_requirements"] == {
        "numpy": [
            {"specifier": ">=1.20", "marker": ""},
            {"specifier": ">=2", "marker": ""},
            {"specifier": "<2", "marker": ""},
            {"specifier": ">=1.26", "marker": ""},
        ],
        "numpy@extra:slow": [{"specifier": "<2", "marker": ""}],
        "pytest@group:dev": [{"specifier": "", "marker": ""}],
    }
    assert report["dependency_specifiers"] == {
        "numpy": ">=1.20",
        "numpy@extra:slow": "<2",
        "pytest@group:dev": "",
    }


def test_main_missing_dependency_names_the_entry_with_a_scope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DATA_WITH_SCOPES)

    assert main(["extract_metadata.py", str(path), "[]", '["tqdm", "tqdm@extra:fast"]']) == 0
    assert json.loads(capsys.readouterr().out)["warnings"] == [
        f"{path}: dependency 'tqdm@extra:fast' not found"
    ]


def test_main_returns_one_for_an_invalid_dependency_scope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DATA_WITH_SCOPES)

    assert main(["extract_metadata.py", str(path), "[]", '["numpy@dev"]']) == 1
    assert "dependencies entry 'numpy@dev' has an invalid scope" in capsys.readouterr().err


def test_main_parses_each_requirement_once(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "a"\nversion = "1"\ndependencies = ["x>=1", "y"]\n\n'
        '[project.optional-dependencies]\nz = ["w"]\n',
    )
    dependencies_requirements_module._parse_requirement.cache_clear()

    assert main(["extract_metadata.py", str(path), "[]", '["x", "w"]']) == 0
    # "x>=1", "y" and "w" are parsed once, in the index of all the requirements that both lookups
    # share. They are read again for the index of their own place ("x>=1" and "y" for the project,
    # "w" for the extra).
    assert dependencies_requirements_module._parse_requirement.cache_info().misses == 3
    assert dependencies_requirements_module._parse_requirement.cache_info().hits == 3


def test_build_parser_description_is_the_first_line_of_the_docstring() -> None:
    parser = extract_metadata_module._build_parser("extract_metadata.py")

    assert parser.description == (extract_metadata_module.__doc__ or "").splitlines()[0]


def test_build_parser_without_docstring(monkeypatch: pytest.MonkeyPatch) -> None:
    # Python runs with -OO strip the docstrings.
    monkeypatch.setattr(extract_metadata_module, "__doc__", None)

    assert extract_metadata_module._build_parser("extract_metadata.py").description == ""


def test_main_non_string_requirement_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "coola"\nversion = "1"\ndependencies = ["a", 1]\n'
    )

    assert main(["extract_metadata.py", str(path), "[]"]) == 1
    assert "[project].dependencies must contain only strings, got: 1" in capsys.readouterr().err


def test_main_dynamic_version_is_a_warning_and_strict_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\ndynamic = ["version"]\n')

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert (report["version"], len(report["warnings"])) == ("", 1)

    assert main(["extract_metadata.py", "--strict", "true", str(path), "[]"]) == 1
    captured = capsys.readouterr()
    assert "[project].version is dynamic" in captured.err
    assert captured.out == ""


def test_main_github_output_multiline_requires_python_cannot_inject_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "a"\nversion = "1"\nrequires-python = "x\\n::error::boom\\nversion=hacked"\n',
    )
    output = tmp_path / "github_output"

    exit_code = main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"])
    captured = capsys.readouterr()

    assert exit_code == 0
    outputs = parse_github_output(output.read_text(encoding="utf-8"))
    assert outputs["requires-python"] == "x\n::error::boom\nversion=hacked"
    assert outputs["version"] == "1"
    assert not any(line.startswith("::error") for line in captured.out.splitlines())
    assert (
        len(captured.out.splitlines()) == 2
    )  # the warning for the invalid specifier, then the summary
    assert "requires-python=x\\n::error::boom\\nversion=hacked " in captured.out


def test_main_dependency_requirements_in_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "a"\nversion = "1"\n'
        "dependencies = [\"numpy>=1; python_version < '3.12'\", \"numpy>=2; python_version >= '3.12'\"]\n",
    )

    assert main(["extract_metadata.py", str(path), "[]", '["numpy", "missing"]']) == 0
    assert json.loads(capsys.readouterr().out)["dependency_requirements"] == {
        "numpy": [
            {"specifier": ">=1", "marker": 'python_version < "3.12"'},
            {"specifier": ">=2", "marker": 'python_version >= "3.12"'},
        ],
        "missing": [],
    }
