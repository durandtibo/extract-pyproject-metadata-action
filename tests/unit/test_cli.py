"""Tests of ``extract_pyproject_metadata.cli``: ``main`` and the
environment variables."""

from __future__ import annotations

import io
import json
import sys
from typing import TYPE_CHECKING

import pytest

import extract_pyproject_metadata.report as report_module
from extract_pyproject_metadata.cli import env_name, main, read_inputs, run
from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.pyproject import load_pyproject
from extract_pyproject_metadata.types import Report
from tests.helpers import (
    DEPS_TOML,
    messages,
    parse_github_output,
    run_main,
    write_pyproject,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_report_keys_match_the_json_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')

    assert run_main([str(path), "[]"]) == 0

    assert list(json.loads(capsys.readouterr().out)) == list(Report.__annotations__)


def test_github_output_has_no_schema_version(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')
    output = tmp_path / "out"

    assert run_main(["--github-output", str(output), str(path), "[]"]) == 0
    assert "schema-version" not in parse_github_output(output.read_text(encoding="utf-8"))


def test_main_returns_one_when_the_outputs_cannot_be_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')

    exit_code = run_main(["--github-output", str(tmp_path), str(path), "[]"])

    assert exit_code == 1
    assert "::error file=" in capsys.readouterr().err


def test_main_json_keeps_non_ascii_characters(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = "Héllo ✓"\n'
    )

    assert run_main([str(path), "[]"]) == 0

    out = capsys.readouterr().out
    assert '"requires_python": "Héllo ✓"' in out
    assert "\\u" not in out


def test_main_parses_the_file_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')
    calls: list[str] = []

    def counting_load(pyproject_path: str) -> dict:
        calls.append(pyproject_path)
        return load_pyproject(pyproject_path)

    monkeypatch.setattr(report_module, "load_pyproject", counting_load)

    exit_code = run_main([str(path), "[]", '["numpy"]'])
    capsys.readouterr()

    assert exit_code == 0
    assert calls == [str(path)]


BASE_TOML = '[project]\nname = "coola"\nversion = "1"\n'


@pytest.mark.parametrize(
    ("toml", "options", "tail", "message"),
    [
        (BASE_TOML, [], ["not json"], "extra-values: not valid JSON"),
        (BASE_TOML.replace('"1"', '"latest"'), [], ["[]"], "not a valid PEP 440 version"),
        (
            BASE_TOML + 'dependencies = ["a", 1]\n',
            [],
            ["[]", '["a"]'],
            "[project].dependencies: must contain only strings, got: 1",
        ),
    ],
    ids=["input", "project", "requirements"],
)
def test_main_returns_one_with_the_message_for_an_invalid_input(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    toml: str,
    options: list[str],
    tail: list[str],
    message: str,
) -> None:
    path = write_pyproject(tmp_path, toml)

    exit_code = run_main([*options, str(path), *tail])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert message in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


def test_main_outputs_warnings_in_json_and_nothing_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)

    exit_code = run_main([str(path), "[]", '["missing"]'])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert messages(json.loads(captured.out)["warnings"]) == ["dependency 'missing' not found"]
    assert captured.err == ""


def test_main_github_output_writes_outputs_and_annotations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    output = tmp_path / "github_output"

    exit_code = run_main(
        [
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
        f"::warning file={path},title=dependency-not-found::dependency 'missing' not found\n"
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

    exit_code = run_main(
        [
            "--github-output",
            str(output),
            "--strict",
            "true",
            str(path),
            "[]",
            '["missing"]',
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.err.startswith(
        f"::error file={path}::strict: true and there are 1 warning(s):%0A- dependency"
    )
    assert captured.out == ""
    assert not output.exists()


def test_main_error_annotation_cannot_inject_a_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = 3\n')

    exit_code = run_main(["--github-output", str(tmp_path / "out"), str(path), "[]"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert len(captured.err.splitlines()) == 1
    assert captured.err.startswith("::error file=")


@pytest.mark.parametrize(
    ("github_output", "expected"),
    [
        (False, "{path}: pyproject-path: not a file\n"),
        (True, "::error file={path}::pyproject-path: not a file\n"),
    ],
    ids=["plain", "annotation"],
)
def test_main_error_is_a_message_or_an_annotation_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], github_output: bool, expected: str
) -> None:
    path = tmp_path / "nope.toml"
    output = tmp_path / "out"
    options = ["--github-output", str(output)] if github_output else []

    assert run_main([*options, str(path), "[]"]) == 1
    captured = capsys.readouterr()

    assert captured.err == expected.format(path=path)
    assert captured.out == ""
    assert not output.exists()


def test_main_github_output_multiline_name_is_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "evil\\n::error::boom\\nversion=hacked"\nversion = "1"\n',
    )
    output = tmp_path / "github_output"

    exit_code = run_main(["--github-output", str(output), str(path), "[]"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert not output.exists()
    assert captured.out == ""
    assert len(captured.err.splitlines()) == 1
    assert "[project].name: not a valid project name" in captured.err


@pytest.mark.parametrize(
    ("relative_path", "escaped"),
    [("pyproject.toml", "pyproject.toml"), ("a,b:c/pyproject.toml", "a%2Cb%3Ac/pyproject.toml")],
)
def test_main_warning_annotation_names_the_file_and_escapes_it(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
    escaped: str,
) -> None:
    path = tmp_path / relative_path
    path.parent.mkdir(exist_ok=True)
    path.write_text('[project]\nname = "p"\ndynamic = ["version"]\n')
    monkeypatch.chdir(tmp_path)

    exit_code = run_main(["--github-output", str(tmp_path / "out"), relative_path, "[]"])

    assert exit_code == 0
    assert capsys.readouterr().out.splitlines()[0] == (
        f"::warning file={escaped},title=dynamic-version::"
        "[project].version is dynamic, the version output is empty"
    )


def test_main_github_output_multiline_requires_python_cannot_inject_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "a"\nversion = "1"\nrequires-python = "x\\n::error::boom\\nversion=hacked"\n',
    )
    output = tmp_path / "github_output"

    exit_code = run_main(["--github-output", str(output), str(path), "[]"])
    captured = capsys.readouterr()

    assert exit_code == 0
    outputs = parse_github_output(output.read_text(encoding="utf-8"))
    assert outputs["requires-python"] == "x\n::error::boom\nversion=hacked"
    assert outputs["version"] == "1"
    assert not any(line.startswith("::error") for line in captured.out.splitlines())
    assert (
        len(captured.out.splitlines()) == 2
    )  # the warning for the invalid specifier, then the log line
    assert "requires-python=x\\n::error::boom\\nversion=hacked " in captured.out


@pytest.mark.parametrize(
    ("name", "variable"),
    [
        ("pyproject-path", "INPUT_PYPROJECT_PATH"),
        ("extra-values", "INPUT_EXTRA_VALUES"),
        ("dependencies", "INPUT_DEPENDENCIES"),
        ("python-candidates", "INPUT_PYTHON_CANDIDATES"),
        ("strict", "INPUT_STRICT"),
    ],
)
def test_env_name(name: str, variable: str) -> None:
    assert env_name(name) == variable


def test_read_inputs_reads_every_variable() -> None:
    environ = {
        "INPUT_PYPROJECT_PATH": "sub/pyproject.toml",
        "INPUT_EXTRA_VALUES": '["", "a"]',
        "INPUT_DEPENDENCIES": '["numpy@project"]',
        "INPUT_PYTHON_CANDIDATES": '["3.12"]',
        "INPUT_STRICT": "true",
        "OTHER": "ignored",
    }

    inputs = read_inputs(environ)

    assert (
        inputs.pyproject_path,
        inputs.extra_values,
        inputs.python_candidates,
        inputs.strict,
    ) == (
        "sub/pyproject.toml",
        ["", "a"],
        ["3.12"],
        True,
    )
    assert [lookup.text for lookup in inputs.dependencies] == ["numpy@project"]


def test_read_inputs_uses_the_defaults_of_the_inputs_that_are_not_set() -> None:
    inputs = read_inputs({})

    assert inputs.pyproject_path == "pyproject.toml"
    assert (inputs.extra_values, inputs.dependencies, inputs.strict) == ([], [], False)
    assert inputs.python_candidates == ["3.11", "3.12", "3.13", "3.14", "3.15"]


def test_read_inputs_empty_python_candidates_is_an_error() -> None:
    with pytest.raises(MetadataError, match=r"^python-candidates: not valid JSON: ''"):
        read_inputs({"INPUT_PYTHON_CANDIDATES": ""})


def test_read_inputs_invalid_value() -> None:
    with pytest.raises(MetadataError, match=r"^strict: must be 'true' or 'false'"):
        read_inputs({"INPUT_STRICT": "maybe"})


def test_main_reads_os_environ_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')
    monkeypatch.setenv("INPUT_PYPROJECT_PATH", str(path))
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

    assert main() == 0
    assert json.loads(capsys.readouterr().out)["name"] == "a"


def test_main_without_github_output_prints_the_json_and_no_annotation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\ndynamic = ["version"]\n')

    assert main({"INPUT_PYPROJECT_PATH": str(path)}) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out)["warnings"][0]["code"] == "dynamic-version"
    assert "::" not in captured.out
    assert captured.err == ""


@pytest.mark.parametrize("github_output", ["", None])
def test_main_an_empty_github_output_is_not_set(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], github_output: str | None
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')
    environ = {"INPUT_PYPROJECT_PATH": str(path)}
    if github_output is not None:
        environ["GITHUB_OUTPUT"] = github_output

    assert main(environ) == 0
    assert json.loads(capsys.readouterr().out)["name"] == "a"


def test_run_uses_the_environment_of_the_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1"\n')
    monkeypatch.setattr(sys, "argv", ["extract_metadata.py"])
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setenv("INPUT_PYPROJECT_PATH", str(path))
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)

    assert run() == 0
    assert json.loads(stdout.getvalue())["name"] == "coola"


def test_run_switches_a_text_stream_to_utf8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1"\n')
    monkeypatch.setattr(sys, "argv", ["extract_metadata.py"])
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setenv("INPUT_PYPROJECT_PATH", str(path))
    monkeypatch.setenv("INPUT_EXTRA_VALUES", '["é"]')
    buffer = io.BytesIO()
    stdout = io.TextIOWrapper(buffer, encoding="ascii")
    monkeypatch.setattr(sys, "stdout", stdout)

    assert run() == 0
    stdout.flush()
    assert json.loads(buffer.getvalue().decode("utf-8"))["extras"] == ["é"]


def test_run_decodes_the_environment_as_utf8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1"\n')
    monkeypatch.setattr(sys, "argv", ["extract_metadata.py"])
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setenv("INPUT_PYPROJECT_PATH", str(path))
    # What a C locale makes of the UTF-8 bytes of "é".
    monkeypatch.setenv("INPUT_EXTRA_VALUES", '["\udcc3\udca9"]')
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)

    assert run() == 0
    assert json.loads(stdout.getvalue())["extras"] == ["é"]


def test_main_strict_passes_on_a_static_and_dynamic_field_that_is_not_read(
    tmp_path: Path,
) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "coola"\nversion = "1"\ndescription = "d"\ndynamic = ["description"]\n',
    )

    assert run_main(["--strict", "true", str(path), "[]"]) == 0
