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
from extract_pyproject_metadata.github import (
    format_error,
)
from extract_pyproject_metadata.pyproject import load_pyproject
from extract_pyproject_metadata.types import Report
from tests.helpers import (
    DATA_WITH_SCOPES,
    DEPS_TOML,
    messages,
    parse_github_output,
    run_main,
    specifier_error,
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


def test_main_returns_one_for_an_invalid_utf8_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_bytes(b"\xff\xfe")

    assert run_main([str(path), "[]"]) == 1
    assert "not valid UTF-8" in capsys.readouterr().err


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


def test_main_strict_fails_on_a_static_and_dynamic_field(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "coola"\nversion = "1"\ndynamic = ["version"]\n'
    )

    assert run_main(["--strict", "true", str(path), "[]"]) == 1
    assert (
        "[project].version is set and also listed in [project].dynamic" in capsys.readouterr().err
    )


def test_main_prints_json_to_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [project]
        name = "coola"
        version = "1.2.3"
        """,
    )

    exit_code = run_main([str(path), "[]"])
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

    exit_code = run_main([str(path), "[]", '["numpy"]'])
    capsys.readouterr()

    assert exit_code == 0
    assert calls == [str(path)]


def test_main_returns_nonzero_on_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "does-not-exist.toml"

    exit_code = run_main([str(missing), "[]"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "not a file" in captured.err


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


def test_main_invalid_strict_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    assert run_main(["--strict", "maybe", str(path), "[]"]) == 1
    assert "strict: must be 'true' or 'false', got: 'maybe'" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("message", "pyproject_path", "annotate", "expected"),
    [
        ("boom", "p.toml", False, "p.toml: boom"),
        ("a\nb", "p.toml", False, "p.toml: a\nb"),
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

    assert run_main([str(path), "[]"]) == 1
    captured = capsys.readouterr()

    assert captured.err == f"{path}: pyproject-path: not a file\n"
    assert captured.out == ""


def test_main_error_is_an_annotation_with_github_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "nope.toml"

    exit_code = run_main(["--github-output", str(tmp_path / "out"), str(path), "[]"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.err == f"::error file={path}::pyproject-path: not a file\n"


def test_main_error_annotation_cannot_inject_a_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = 3\n')

    exit_code = run_main(["--github-output", str(tmp_path / "out"), str(path), "[]"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert len(captured.err.splitlines()) == 1
    assert captured.err.startswith("::error file=")


def test_main_github_output_error_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "github_output"

    exit_code = run_main(["--github-output", str(output), str(tmp_path / "nope.toml"), "[]"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "not a file" in captured.err
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
    ("argv_tail", "message"),
    [
        (["[]", "not json"], "dependencies: not valid JSON"),
        (["[]", '{"a": 1}'], "dependencies: must be a JSON array of strings"),
        (["not json"], "extra-values: not valid JSON"),
        (["{}"], "extra-values: must be a JSON array"),
        (["[1]"], "extra-values: must be a JSON array of strings"),
    ],
)
def test_main_invalid_inputs_return_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv_tail: list[str], message: str
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')

    exit_code = run_main([str(path), *argv_tail])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert message in captured.err
    assert captured.out == ""


def test_main_unknown_group_entry_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "coola"\nversion = "1"\n\n[dependency-groups]\ndev = [{include_group = "a"}]\n',
    )

    assert run_main([str(path), "[]", '["x"]']) == 1
    assert "[dependency-groups].dev: entries must be strings or" in capsys.readouterr().err


def test_main_malformed_dependency_table_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "p"\nversion = "1"\n[dependency-groups]\ndev = "numpy"\n'
    )

    exit_code = run_main([str(path), "[]", '["numpy"]'])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "[dependency-groups].dev: must be an array" in captured.err
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

    exit_code = run_main(["--github-output", str(output), str(path), "[]", '["x"]'])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out.splitlines()[0] == (
        f"::warning file={path},title=include-group-cycle::[dependency-groups] has an include-group cycle: a -> a"
    )


def test_main_warning_annotation_escapes_the_file_property(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "a,b:c"
    directory.mkdir()
    path = directory / "pyproject.toml"
    path.write_text('[project]\nname = "p"\ndynamic = ["version"]\n')
    output = tmp_path / "github_output"

    exit_code = run_main(["--github-output", str(output), str(path), "[]"])
    captured = capsys.readouterr()

    escaped = str(path).replace("%", "%25").replace(":", "%3A").replace(",", "%2C")
    assert exit_code == 0
    assert captured.out.splitlines()[0] == (
        f"::warning file={escaped},title=dynamic-version::[project].version is dynamic, the version output is empty"
    )


def test_main_warning_annotation_names_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    write_pyproject(tmp_path, '[project]\nname = "p"\ndynamic = ["version"]\n')
    monkeypatch.chdir(tmp_path)

    exit_code = run_main(["--github-output", str(tmp_path / "out"), "pyproject.toml", "[]"])

    assert exit_code == 0
    assert capsys.readouterr().out.splitlines()[0] == (
        "::warning file=pyproject.toml,title=dynamic-version::[project].version is dynamic, the version output is empty"
    )


def test_main_invalid_version_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "p"\nversion = "latest"\n')

    exit_code = run_main([str(path), "[]"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "not a valid PEP 440 version: 'latest'" in captured.err
    assert captured.out == ""


def test_main_missing_dependency_is_a_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    output = tmp_path / "github_output"

    exit_code = run_main(
        [
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
    assert (
        f"::warning file={path},title=dependency-not-found::dependency 'missing' not found"
        in captured.out
    )


def test_main_strict_fails_for_a_missing_dependency(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    output = tmp_path / "github_output"

    exit_code = run_main(
        [
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
        f"::error file={path}::strict: true and there are 2 warning(s):"
        "%0A- dependency-not-found: dependency 'missing' not found"
        "%0A- dependency-not-found: dependency 'other' not found\n"
    )
    assert captured.out == ""
    assert not output.exists()


def test_main_no_warning_when_all_the_dependencies_are_found(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)

    exit_code = run_main(["--strict", "true", str(path), "[]", '["nospec"]'])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["dependency_specifiers"] == {"nospec": ""}


def test_main_missing_dependency_with_dynamic_dependencies_warns_twice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\ndynamic = ["dependencies"]\n'
    )

    exit_code = run_main([str(path), "[]", '["numpy"]'])

    assert exit_code == 0
    assert messages(json.loads(capsys.readouterr().out)["warnings"]) == [
        ("[project].dependencies is dynamic, it cannot be read, so no requirement is found in it"),
        "dependency 'numpy' not found",
    ]


def test_main_strict_fails_when_no_python_version_is_allowed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = ">=4"\n'
    )

    assert run_main(["--strict", "true", str(path), "[]"]) == 1
    assert "strict: true and there are 1 warning(s)" in capsys.readouterr().err


@pytest.mark.parametrize("raw", ['["3.12.1"]', "not json"])
def test_main_invalid_python_candidates_return_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], raw: str
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    exit_code = run_main(["--python-candidates", raw, str(path), "[]"])
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

    assert run_main([str(path), "[]", '["x"]']) == 0
    warnings = json.loads(capsys.readouterr().out)["warnings"]
    assert len(warnings) == 3
    # The metadata, the Python versions, then the lookups.
    assert [w["message"] for w in warnings[:2]] == [
        "[project].version is dynamic, the version output is empty",
        (
            f"[project].requires-python is not a valid version specifier, "
            f"the python-versions output is empty: {specifier_error('python3')}"
        ),
    ]
    assert warnings[2]["message"].startswith("Ignoring invalid requirement 'not valid!': ")


def test_main_missing_dependency_names_the_entry_with_a_scope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DATA_WITH_SCOPES)

    assert run_main([str(path), "[]", '["tqdm", "tqdm@extra:fast"]']) == 0
    assert messages(json.loads(capsys.readouterr().out)["warnings"]) == [
        "dependency 'tqdm@extra:fast' not found"
    ]


def test_main_returns_one_for_an_invalid_dependency_scope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DATA_WITH_SCOPES)

    assert run_main([str(path), "[]", '["numpy@dev"]']) == 1
    assert "dependencies: entry 'numpy@dev' has an invalid scope" in capsys.readouterr().err


def test_main_non_string_requirement_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "coola"\nversion = "1"\ndependencies = ["a", 1]\n'
    )

    assert run_main([str(path), "[]", '["a"]']) == 1
    assert "[project].dependencies: must contain only strings, got: 1" in capsys.readouterr().err


def test_main_dynamic_version_is_a_warning_and_strict_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\ndynamic = ["version"]\n')

    assert run_main([str(path), "[]"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert (report["version"], len(report["warnings"])) == ("", 1)

    assert run_main(["--strict", "true", str(path), "[]"]) == 1
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


def test_read_inputs_empty_python_candidates_is_the_default() -> None:
    assert read_inputs({"INPUT_PYTHON_CANDIDATES": ""}) == read_inputs({})


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


def test_main_arguments_are_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main({}, ["pyproject.toml"]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unexpected arguments ['pyproject.toml']" in captured.err
    assert "INPUT_PYPROJECT_PATH" in captured.err


def test_main_arguments_are_an_annotated_usage_error_with_github_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main({"GITHUB_OUTPUT": str(tmp_path / "out")}, ["x"]) == 2

    assert capsys.readouterr().err.startswith("::error::extract_pyproject_metadata: error: ")
    assert not (tmp_path / "out").exists()


def test_run_uses_the_environment_and_the_arguments_of_the_process(
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


def test_run_with_an_argument_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["extract_metadata.py", "pyproject.toml"])
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

    assert run() == 2
    assert "unexpected arguments" in capsys.readouterr().err
