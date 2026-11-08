"""Tests of the command line: main, build_report, the options and the end-to-end runs."""



import importlib.util
import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest
from helpers import (
    DATA_WITH_SCOPES,
    DEPS_TOML,
    GROUPS_TOML,
    PACKAGE_PATH,
    SCRIPT_PATH,
    _specifier_error,
    parse_args,
    parse_github_output,
    requires_licenses,
    write_pyproject,
)

import extract_pyproject_metadata.cli as extract_metadata_module
import extract_pyproject_metadata.dependencies.requirements as dependencies_requirements_module
from extract_pyproject_metadata.cli import build_report, load_pyproject, main
from extract_pyproject_metadata.dependencies.lookup import check_no_missing_dependency
from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.inputs import Options, parse_bool, parse_options
from extract_pyproject_metadata.output.github import format_error
from extract_pyproject_metadata.output.summary import format_error_summary, resolve_step_summary


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
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')

    exit_code = main(["extract_metadata.py", "--step-summary", "true", str(path), "[]"])

    assert exit_code == 1
    assert "cannot write the job summary" in capsys.readouterr().err



def test_main_reports_the_error_once_when_the_job_summary_cannot_be_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path))
    path = write_pyproject(tmp_path, '[project]\nversion = "1"\n')

    exit_code = main(["extract_metadata.py", "--step-summary", "true", str(path), "[]"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "missing required key" in err
    assert "cannot write the job summary" not in err



def test_main_description_in_json_and_github_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\ndescription = "Two\\nlines"\n'
    )
    output = tmp_path / "github_output"

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["description"] == "Two\nlines"
    assert main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"]) == 0
    assert parse_github_output(output.read_text(encoding="utf-8"))["description"] == "Two\nlines"
    assert "description=" not in capsys.readouterr().out



def test_main_json_keeps_non_ascii_characters(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\ndescription = "Héllo ✓"\n'
    )

    assert main(["extract_metadata.py", str(path), "[]"]) == 0

    out = capsys.readouterr().out
    assert '"description": "Héllo ✓"' in out
    assert "\\u" not in out



def test_main_license_files_in_json_and_github_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nlicense-files = ["LICENSE", "licenses/*.txt"]\n'
    )
    output = tmp_path / "github_output"

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["license_files"] == ["LICENSE", "licenses/*.txt"]
    assert main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"]) == 0
    assert parse_github_output(output.read_text(encoding="utf-8"))["license-files"] == (
        '["LICENSE","licenses/*.txt"]'
    )



def test_main_keywords_classifiers_and_scripts_in_json_and_github_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "a"\nversion = "1"\nkeywords = ["toml"]\n'
        'classifiers = ["Programming Language :: Python :: 3"]\n\n[project.scripts]\ntool = "a.cli:main"\n',
    )
    output = tmp_path / "github_output"

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert (report["keywords"], report["classifiers"], report["scripts"]) == (
        ["toml"],
        ["Programming Language :: Python :: 3"],
        {"tool": "a.cli:main"},
    )
    assert main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"]) == 0
    values = parse_github_output(output.read_text(encoding="utf-8"))
    assert (values["keywords"], values["classifiers"], values["scripts"]) == (
        '["toml"]',
        '["Programming Language :: Python :: 3"]',
        '{"tool":"a.cli:main"}',
    )



def test_main_build_system_in_json_and_github_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path,
        '[build-system]\nrequires = ["hatchling", "hatch-vcs>=0.4"]\nbuild-backend = "hatchling.build"\n\n'
        '[project]\nname = "a"\nversion = "1"\n',
    )
    output = tmp_path / "github_output"

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert (report["build_backend"], report["build_requires"]) == (
        "hatchling.build",
        ["hatchling", "hatch-vcs>=0.4"],
    )
    assert main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"]) == 0
    values = parse_github_output(output.read_text(encoding="utf-8"))
    assert (values["build-backend"], values["build-requires"]) == (
        "hatchling.build",
        '["hatchling","hatch-vcs>=0.4"]',
    )



def test_main_returns_one_for_an_invalid_build_system(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[build-system]\nrequires = "x"\n\n[project]\nname = "a"\nversion = "1"\n')

    assert main(["extract_metadata.py", str(path), "[]"]) == 1
    assert f"{path}: [build-system].requires must be an array, got: 'x'" in capsys.readouterr().err



def test_the_script_runs_without_packaging_licenses(monkeypatch: pytest.MonkeyPatch) -> None:
    # packaging before 24.2 has no ``packaging.licenses``: importing it raises ImportError.
    monkeypatch.setitem(sys.modules, "packaging.licenses", None)

    spec = importlib.util.spec_from_file_location("cli_without_licenses", PACKAGE_PATH / "cli.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    spec.loader.exec_module(module)

    assert module.canonicalize_license_expression is None
    assert module._license_warnings("MIT License", "p.toml") == []



@requires_licenses
def test_main_strict_fails_on_an_invalid_license_expression(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\nlicense = "MIT License"\n')

    assert main(["extract_metadata.py", "--strict", "true", str(path), "[]"]) == 1
    assert "not a valid SPDX license expression" in capsys.readouterr().err



def test_main_strict_fails_on_a_static_and_dynamic_field(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "coola"\nversion = "1"\ndynamic = ["version"]\n'
    )

    assert main(["extract_metadata.py", "--strict", "true", str(path), "[]"]) == 1
    assert "[project].version is set and also listed in [project].dynamic" in capsys.readouterr().err



def test_main_dynamic_version_warning_in_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\ndynamic = ["version"]\n')

    exit_code = main(["extract_metadata.py", str(path), "[]"])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "name": "coola",
        "normalized_name": "coola",
        "version": "",
        "normalized_version": "",
        "description": "",
        "readme": "",
        "license": "",
        "license_files": [],
        "authors": [],
        "urls": {},
        "keywords": [],
        "classifiers": [],
        "scripts": {},
        "requires_python": "",
        "extras": [],
        "groups": [],
        "build_backend": "",
        "build_requires": [],
        "python_versions": ["3.11", "3.12", "3.13", "3.14", "3.15"],
        "python_min": "3.11",
        "python_max": "3.15",
        "project_dependencies": {},
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
        "version": "1.2.3",
        "normalized_version": "1.2.3",
        "description": "",
        "readme": "",
        "license": "",
        "license_files": [],
        "authors": [],
        "urls": {},
        "keywords": [],
        "classifiers": [],
        "scripts": {},
        "requires_python": "",
        "extras": [],
        "groups": [],
        "build_backend": "",
        "build_requires": [],
        "python_versions": ["3.11", "3.12", "3.13", "3.14", "3.15"],
        "python_min": "3.11",
        "python_max": "3.15",
        "project_dependencies": {},
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

    monkeypatch.setattr(extract_metadata_module, "load_pyproject", counting_load)

    exit_code = main(["extract_metadata.py", str(path), "[]", '["numpy"]'])
    capsys.readouterr()

    assert exit_code == 0
    assert calls == [str(path)]



def test_main_returns_nonzero_on_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
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



def test_cli_end_to_end(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [project]
        name = "coola"
        version = "1.2.3"

        [project.optional-dependencies]
        numpy = ["numpy"]
        """,
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(path), '[""]'],
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(result.stdout) == {
        "name": "coola",
        "normalized_name": "coola",
        "version": "1.2.3",
        "normalized_version": "1.2.3",
        "description": "",
        "readme": "",
        "license": "",
        "license_files": [],
        "authors": [],
        "urls": {},
        "keywords": [],
        "classifiers": [],
        "scripts": {},
        "requires_python": "",
        "extras": ["", "numpy"],
        "groups": [],
        "build_backend": "",
        "build_requires": [],
        "python_versions": ["3.11", "3.12", "3.13", "3.14", "3.15"],
        "python_min": "3.11",
        "python_max": "3.15",
        "project_dependencies": {},
        "dependency_specifiers": {},
        "dependency_requirements": {},
        "warnings": [],
        "schema_version": 1,
    }



def test_cli_end_to_end_error_exit_code(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.toml"

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(missing), "[]"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "not found" in result.stderr



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
    assert parse_github_output(output.read_text(encoding="utf-8")) == {
        "name": "p",
        "normalized-name": "p",
        "version": "1",
        "normalized-version": "1",
        "description": "",
        "readme": "",
        "license": "",
        "license-files": '[]',
        "authors": '[]',
        "urls": '{}',
        "keywords": '[]',
        "classifiers": '[]',
        "scripts": '{}',
        "requires-python": "",
        "extras": '["","a"]',
        "groups": '["base","dev","other"]',
        "build-backend": "",
        "build-requires": '[]',
        "python-versions": '["3.11","3.12","3.13","3.14","3.15"]',
        "python-min": "3.11",
        "python-max": "3.15",
        "python-matrix": '{"python-version":["3.11","3.12","3.13","3.14","3.15"]}',
        "project-dependencies": '{"Foo_Bar":"<2,>=1","nospec":"","withextra":">=3"}',
        "dependency-specifiers": '{"dup":">=1","nospec":"","missing":null}',
        "dependency-requirements": (
            '{"dup":[{"specifier":">=1","marker":""},{"specifier":">=2","marker":""}],'
            '"nospec":[{"specifier":"","marker":""}],"missing":[]}'
        ),
    }
    assert captured.out == (
        f"::warning file={path}::dup has different specifiers in {path}: ['>=1', '>=2']; using '>=1'\n"
        "📦 name=p version=1 requires-python= "
        'python-versions=["3.11","3.12","3.13","3.14","3.15"] python-min=3.11 python-max=3.15 extras=["","a"] '
        'groups=["base","dev","other"] '
        'project-dependencies={"Foo_Bar":"<2,>=1","nospec":"","withextra":">=3"} '
        'dependency-specifiers={"dup":">=1","nospec":"","missing":null}\n'
    )
    assert captured.err == ""



def test_build_report(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)

    report = build_report(parse_args(str(path), '[""]', '["dup", "missing"]'))

    assert report == {
        "name": "p",
        "normalized_name": "p",
        "version": "1",
        "normalized_version": "1",
        "description": "",
        "readme": "",
        "license": "",
        "license_files": [],
        "authors": [],
        "urls": {},
        "keywords": [],
        "classifiers": [],
        "scripts": {},
        "requires_python": "",
        "extras": ["", "a"],
        "groups": ["base", "dev", "other"],
        "build_backend": "",
        "build_requires": [],
        "python_versions": ["3.11", "3.12", "3.13", "3.14", "3.15"],
        "python_min": "3.11",
        "python_max": "3.15",
        "project_dependencies": {"Foo_Bar": "<2,>=1", "nospec": "", "withextra": ">=3"},
        "dependency_specifiers": {"dup": ">=1", "missing": None},
        "dependency_requirements": {
            "dup": [{"specifier": ">=1", "marker": ""}, {"specifier": ">=2", "marker": ""}],
            "missing": [],
        },
        "warnings": [f"dup has different specifiers in {path}: ['>=1', '>=2']; using '>=1'"],
        "schema_version": 1,
    }



@pytest.mark.parametrize(
    ("argv", "match"),
    [
        (["--fail-on-missing", "maybe", "{path}", "[]"], r"fail-on-missing must be 'true' or 'false'"),
        (["--fail-on-dynamic-version", "maybe", "{path}", "[]"], r"fail-on-dynamic-version must be"),
        (["--python-candidates", "[3]", "{path}", "[]"], r"python-candidates must be a JSON array of strings"),
        (["--fail-on-missing", "true", "{path}", "[]", '["missing"]'], r"dependencies not found"),
        (["{path}", "nope"], r"extra-values is not valid JSON"),
        (["{path}", "[]", "nope"], r"dependencies is not valid JSON"),
        (["missing.toml", "[]"], r"pyproject\.toml not found at: missing\.toml"),
    ],
)
def test_build_report_errors(tmp_path: Path, argv: list[str], match: str) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    argv = [arg.replace("{path}", str(path)) for arg in argv]

    with pytest.raises(MetadataError, match=match):
        build_report(parse_args(*argv))



def test_build_report_strict_fails_on_warnings(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)

    with pytest.raises(
        MetadataError,
        match=r"^strict is 'true' and there are 1 warning\(s\):\n- dup has different specifiers in ",
    ):
        build_report(parse_args("--strict", "true", str(path), "[]", '["dup"]'))



def test_build_report_strict_lists_every_warning(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "a"\nversion = "1"\nrequires-python = "nope"\n'
        'dependencies = ["bad requirement!!"]\n',
    )

    with pytest.raises(MetadataError) as excinfo:
        build_report(parse_args("--strict", "true", str(path), "[]"))

    lines = str(excinfo.value).splitlines()
    assert lines[0] == "strict is 'true' and there are 2 warning(s):"
    assert lines[1].startswith("- ")
    assert lines[2].startswith("- ")



def test_build_report_strict_without_warnings(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    report = build_report(parse_args("--strict", "true", str(path), "[]"))

    assert report["warnings"] == []



def test_build_report_not_strict_keeps_the_warnings(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)

    report = build_report(parse_args("--strict", "false", str(path), "[]", '["dup"]'))

    assert len(report["warnings"]) == 1



def test_main_strict_fails_without_writing_the_outputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    output = tmp_path / "out"

    exit_code = main(
        ["extract_metadata.py", "--github-output", str(output), "--strict", "true", str(path), "[]", '["dup"]']
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.err.startswith(f"::error file={path}::strict is 'true' and there are 1 warning(s):%0A- dup")
    assert captured.out == ""
    assert not output.exists()



def test_main_invalid_strict_returns_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    assert main(["extract_metadata.py", "--strict", "maybe", str(path), "[]"]) == 1
    assert "strict must be 'true' or 'false', got: 'maybe'" in capsys.readouterr().err



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



@pytest.mark.parametrize(
    ("value", "environ", "expected"),
    [
        ("false", {}, None),
        ("false", {"GITHUB_STEP_SUMMARY": "/tmp/s.md"}, None),
        ("true", {"GITHUB_STEP_SUMMARY": "/tmp/s.md"}, "/tmp/s.md"),
        (" TRUE ", {"GITHUB_STEP_SUMMARY": "/tmp/s.md"}, "/tmp/s.md"),
    ],
)
def test_resolve_step_summary(value: str, environ: dict[str, str], expected: str | None) -> None:
    assert resolve_step_summary(parse_bool(value, "step-summary"), environ) == expected



@pytest.mark.parametrize("environ", [{}, {"GITHUB_STEP_SUMMARY": ""}])
def test_resolve_step_summary_without_the_environment_variable(environ: dict[str, str]) -> None:
    with pytest.raises(MetadataError, match=r"step-summary is 'true' but .*GITHUB_STEP_SUMMARY"):
        resolve_step_summary(True, environ)



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
        fail_on_missing=True, fail_on_dynamic_version=True, strict=False, step_summary=True
    )



def test_parse_options_defaults() -> None:
    assert parse_options(parse_args("p.toml", "[]")) == Options(False, False, False, False)



@pytest.mark.parametrize(
    ("option", "name"),
    [
        ("--fail-on-missing", "fail-on-missing"),
        ("--fail-on-dynamic-version", "fail-on-dynamic-version"),
        ("--strict", "strict"),
        ("--step-summary", "step-summary"),
    ],
)
def test_parse_options_invalid_value(option: str, name: str) -> None:
    with pytest.raises(MetadataError, match=rf"{name} must be 'true' or 'false', got: 'maybe'"):
        parse_options(parse_args(option, "maybe", "p.toml", "[]"))



def test_parse_options_reports_the_first_invalid_value() -> None:
    args = parse_args("--strict", "x", "--fail-on-missing", "y", "p.toml", "[]")

    with pytest.raises(MetadataError, match=r"fail-on-missing must be"):
        parse_options(args)



def test_build_report_uses_the_given_options(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')
    args = parse_args("--strict", "maybe", str(path), "[]", '["missing"]')

    report = build_report(args, Options(False, False, False, False))

    assert report["dependency_specifiers"] == {"missing": None}



def test_main_step_summary_writes_the_job_summary(
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
            "--step-summary",
            "true",
            str(path),
            "[]",
            '["dup"]',
        ]
    )

    assert exit_code == 0
    text = summary.read_text(encoding="utf-8")
    assert text.startswith("### 📦 Project metadata\n")
    assert "| `name` | <code>p</code> |" in text
    assert "#### ⚠️ Warnings" in text
    assert "<code>dup has different specifiers" in text
    capsys.readouterr()



def test_main_step_summary_reports_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    path = write_pyproject(tmp_path, '[project]\nversion = "1"\n')

    exit_code = main(["extract_metadata.py", "--step-summary", "true", str(path), "[]"])

    assert exit_code == 1
    text = summary.read_text(encoding="utf-8")
    assert text.startswith("### ❌ Project metadata\n")
    assert "missing required key" in text
    assert "&#91;project&#93;&#46;name" in text
    assert "missing required key" in capsys.readouterr().err



def test_main_step_summary_lists_the_warnings_of_a_strict_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    path = write_pyproject(tmp_path, '[project]\nname = "a"\ndynamic = ["version"]\n')

    exit_code = main(
        ["extract_metadata.py", "--step-summary", "true", "--strict", "true", str(path), "[]"]
    )

    assert exit_code == 1
    text = summary.read_text(encoding="utf-8")
    assert "there are 1 warning&#40;s&#41;&#58;</code>\n- <code>" in text
    assert "<code>&#45;" not in text
    assert "[project].version is dynamic" not in text  # escaped, not raw



def test_main_step_summary_off_writes_nothing_on_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    path = write_pyproject(tmp_path, '[project]\nversion = "1"\n')

    assert main(["extract_metadata.py", str(path), "[]"]) == 1
    assert not summary.exists()



def test_main_step_summary_misconfiguration_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    assert main(["extract_metadata.py", "--step-summary", "true", str(path), "[]"]) == 1



def test_main_step_summary_is_off_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    path = write_pyproject(tmp_path, DEPS_TOML)

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert not summary.exists()



def test_main_step_summary_without_json_output_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    path = write_pyproject(tmp_path, DEPS_TOML)

    assert main(["extract_metadata.py", "--step-summary", "true", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["name"] == "p"
    assert summary.read_text(encoding="utf-8").startswith("### 📦 Project metadata\n")



@pytest.mark.parametrize(
    ("step_summary", "has_variable", "message"),
    [
        ("maybe", True, "step-summary must be 'true' or 'false'"),
        ("true", False, "GITHUB_STEP_SUMMARY is not set"),
    ],
)
def test_main_step_summary_errors_return_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    step_summary: str,
    has_variable: bool,
    message: str,
) -> None:
    if has_variable:
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    else:
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    path = write_pyproject(tmp_path, DEPS_TOML)

    exit_code = main(["extract_metadata.py", "--step-summary", step_summary, str(path), "[]"])

    assert exit_code == 1
    assert message in capsys.readouterr().err
    assert not (tmp_path / "summary.md").exists()



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

    exit_code = main(["extract_metadata.py", "--github-output", str(tmp_path / "out"), str(path), "[]"])
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
def test_main_usage_errors_with_options(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(argv) == 2
    assert "usage:" in capsys.readouterr().err



def test_cli_end_to_end_github_output(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n[project.optional-dependencies]\nnumpy = ["numpy"]\n'
    )
    output = tmp_path / "github_output"

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--github-output", str(output), "--", str(path), '[""]'],
        capture_output=True,
        text=True,
        check=True,
    )

    assert parse_github_output(output.read_text(encoding="utf-8")) == {
        "name": "coola",
        "normalized-name": "coola",
        "version": "1.2.3",
        "normalized-version": "1.2.3",
        "description": "",
        "readme": "",
        "license": "",
        "license-files": '[]',
        "authors": '[]',
        "urls": '{}',
        "keywords": '[]',
        "classifiers": '[]',
        "scripts": '{}',
        "requires-python": "",
        "extras": '["","numpy"]',
        "groups": "[]",
        "build-backend": "",
        "build-requires": "[]",
        "python-versions": '["3.11","3.12","3.13","3.14","3.15"]',
        "python-min": "3.11",
        "python-max": "3.15",
        "python-matrix": '{"python-version":["3.11","3.12","3.13","3.14","3.15"]}',
        "project-dependencies": "{}",
        "dependency-specifiers": "{}",
        "dependency-requirements": "{}",
    }
    assert result.stdout == (
        "📦 name=coola version=1.2.3 requires-python= "
        'python-versions=["3.11","3.12","3.13","3.14","3.15"] python-min=3.11 python-max=3.15 extras=["","numpy"] groups=[] '
        "project-dependencies={} dependency-specifiers={}\n"
    )



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



def test_cli_end_to_end_with_dependencies(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "coola"\nversion = "1.2.3"\ndependencies = ["numpy>=1.20"]\n',
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(path), "[]", '["numpy", "pandas"]'],
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(result.stdout) == {
        "name": "coola",
        "normalized_name": "coola",
        "version": "1.2.3",
        "normalized_version": "1.2.3",
        "description": "",
        "readme": "",
        "license": "",
        "license_files": [],
        "authors": [],
        "urls": {},
        "keywords": [],
        "classifiers": [],
        "scripts": {},
        "requires_python": "",
        "extras": [],
        "groups": [],
        "build_backend": "",
        "build_requires": [],
        "python_versions": ["3.11", "3.12", "3.13", "3.14", "3.15"],
        "python_min": "3.11",
        "python_max": "3.15",
        "project_dependencies": {"numpy": ">=1.20"},
        "dependency_specifiers": {"numpy": ">=1.20", "pandas": None},
        "dependency_requirements": {
            "numpy": [{"specifier": ">=1.20", "marker": ""}],
            "pandas": [],
        },
        "warnings": [],
        "schema_version": 1,
    }



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
    assert parse_github_output(output.read_text(encoding="utf-8"))["groups"] == '["Dev","docs","test"]'



def test_main_json_groups(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_pyproject(tmp_path, GROUPS_TOML)

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["groups"] == ["Dev", "docs", "test"]



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



def test_check_no_missing_dependency_all_found() -> None:
    check_no_missing_dependency({"a": ">=1", "b": ""}, "p.toml")



def test_check_no_missing_dependency_nothing_requested() -> None:
    check_no_missing_dependency({}, "p.toml")



def test_check_no_missing_dependency_lists_the_missing_packages() -> None:
    with pytest.raises(
        MetadataError, match=r"custom\.toml: dependencies not found in .*: \['b', 'd'\]$"
    ):
        check_no_missing_dependency({"a": ">=1", "b": None, "c": "", "d": None}, "custom.toml")



def test_main_fail_on_missing_true_fails_for_a_missing_dependency(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    output = tmp_path / "github_output"

    exit_code = main(
        [
            "extract_metadata.py",
            "--github-output",
            str(output),
            "--fail-on-missing",
            "true",
            str(path),
            "[]",
            '["nospec", "missing", "other"]',
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.err == (
        f"::error file={path}::{path}: dependencies not found in [project].dependencies, "
        "[project.optional-dependencies] or [dependency-groups]: ['missing', 'other']\n"
    )
    assert captured.out == ""
    assert not output.exists()



def test_main_fail_on_missing_true_passes_when_all_are_found(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)

    exit_code = main(
        ["extract_metadata.py", "--fail-on-missing", "true", str(path), "[]", '["nospec", "dup"]']
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["dependency_specifiers"] == {
        "nospec": "",
        "dup": ">=1",
    }



@pytest.mark.parametrize("argv_tail", [[], ["--fail-on-missing", "false"], ["--fail-on-missing", "FALSE"]])
def test_main_fail_on_missing_false_keeps_null(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv_tail: list[str]
) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)

    exit_code = main(["extract_metadata.py", *argv_tail, str(path), "[]", '["missing"]'])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["dependency_specifiers"] == {"missing": None}



def test_main_fail_on_missing_true_without_dependencies_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)

    assert main(["extract_metadata.py", "--fail-on-missing", "true", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["dependency_specifiers"] == {}



@pytest.mark.parametrize("value", ["", "yes", "1"])
def test_main_fail_on_missing_invalid_value_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)

    exit_code = main(["extract_metadata.py", "--fail-on-missing", value, str(path), "[]"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert f"fail-on-missing must be 'true' or 'false', got: {value!r}" in captured.err
    assert captured.out == ""



def test_main_fail_on_missing_requires_a_value(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["extract_metadata.py", "--fail-on-missing"]) == 2
    assert "usage:" in capsys.readouterr().err



def test_cli_end_to_end_fail_on_missing(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\ndependencies = ["numpy>=1.20"]\n'
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--fail-on-missing",
            "true",
            "--",
            str(path),
            "[]",
            '["numpy", "pandas"]',
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "dependencies not found" in result.stderr
    assert "['pandas']" in result.stderr
    assert result.stdout == ""



def test_check_no_missing_dependency_points_out_dynamic_fields() -> None:
    with pytest.raises(
        MetadataError,
        match=r"\['numpy'\]; \[project\]\.dependencies is dynamic and cannot be read$",
    ):
        check_no_missing_dependency({"numpy": None}, "p.toml", ["dependencies"])



def test_main_fail_on_missing_points_out_dynamic_dependencies(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\ndynamic = ["dependencies"]\n')

    exit_code = main(["extract_metadata.py", "--fail-on-missing", "true", str(path), "[]", '["numpy"]'])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.err.endswith("; [project].dependencies is dynamic and cannot be read\n")



def test_main_github_output_python_matrix(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = ">=3.12"\n'
    )
    output = tmp_path / "out"

    assert main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"]) == 0
    values = parse_github_output(output.read_text(encoding="utf-8"))
    assert values["python-matrix"] == '{"python-version":["3.12","3.13","3.14","3.15"]}'
    assert json.loads(values["python-matrix"])["python-version"] == json.loads(
        values["python-versions"]
    )



def test_main_json_has_no_python_matrix(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert "python_matrix" not in json.loads(capsys.readouterr().out)



def test_main_github_output_normalized_version(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1.0-RC1"\n')
    output = tmp_path / "out"

    assert main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"]) == 0
    values = parse_github_output(output.read_text(encoding="utf-8"))
    assert (values["version"], values["normalized-version"]) == ("1.0-RC1", "1.0rc1")



def test_main_readme_in_json_and_github_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nreadme = "docs/README.md"\n'
    )
    output = tmp_path / "out"

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["readme"] == "docs/README.md"
    assert main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"]) == 0
    assert parse_github_output(output.read_text(encoding="utf-8"))["readme"] == "docs/README.md"



def test_main_invalid_readme_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\nreadme = 1\n')

    assert main(["extract_metadata.py", str(path), "[]"]) == 1
    assert "[project].readme must be a string or a table" in capsys.readouterr().err



def test_main_license_in_json_and_github_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\nlicense = "MIT"\n')
    output = tmp_path / "out"

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["license"] == "MIT"
    assert main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"]) == 0
    assert parse_github_output(output.read_text(encoding="utf-8"))["license"] == "MIT"



def test_main_invalid_license_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\nlicense = 1\n')

    assert main(["extract_metadata.py", str(path), "[]"]) == 1
    assert "[project].license must be a string or a table" in capsys.readouterr().err



def test_main_authors_in_json_and_github_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "a"\nversion = "1"\nauthors = [{name = "Zoé", email = "z@e.org"}]\n',
    )
    output = tmp_path / "out"

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["authors"] == [{"name": "Zoé", "email": "z@e.org"}]
    assert main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"]) == 0
    assert (
        parse_github_output(output.read_text(encoding="utf-8"))["authors"]
        == '[{"name":"Zoé","email":"z@e.org"}]'
    )



def test_main_invalid_authors_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\nauthors = ["Ada"]\n')

    assert main(["extract_metadata.py", str(path), "[]"]) == 1
    assert "[project].authors[0] must be a table" in capsys.readouterr().err



def test_main_urls_in_json_and_github_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "a"\nversion = "1"\n[project.urls]\nHomepage = "https://a.org"\nDocs = "https://a.org/d"\n',
    )
    output = tmp_path / "out"

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["urls"] == {
        "Homepage": "https://a.org",
        "Docs": "https://a.org/d",
    }
    assert main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"]) == 0
    assert (
        parse_github_output(output.read_text(encoding="utf-8"))["urls"]
        == '{"Homepage":"https://a.org","Docs":"https://a.org/d"}'
    )



def test_main_invalid_urls_returns_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\nurls = 1\n')

    assert main(["extract_metadata.py", str(path), "[]"]) == 1
    assert "[project.urls] must be a table" in capsys.readouterr().err



def test_main_json_has_a_schema_version(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["schema_version"] == extract_metadata_module.SCHEMA_VERSION == 1



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
        f"{path}: no python-candidates version satisfies [project].requires-python ('>=4'): "
        "python-versions and python-matrix are empty, and a job matrix built from them is "
        "rejected by GitHub"
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



def test_main_python_versions_in_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = ">=3.11,<3.13"\n'
    )

    exit_code = main(["extract_metadata.py", str(path), "[]"])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["python_versions"] == ["3.11", "3.12"]



def test_main_python_candidates_option(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
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
    assert len(warnings) == 5
    # The metadata, the Python versions, the dependencies of the project, then the lookups.
    assert warnings[:3] == [
        f"{path}: [project].version is dynamic, the version output is empty",
        f"{path}: [project].requires-python is not a valid version specifier, "
        f"the python-versions output is empty: {_specifier_error('python3')}",
        f"x has different specifiers in {path}: ['>=1', '>=2']; using '>=1'",
    ]
    assert warnings[3].startswith(f"Ignoring invalid requirement 'not valid!' in {path}: ")
    assert warnings[4] == f"x has different specifiers in {path}: ['>=1', '>=2', '>=3']; using '>=1'"



def test_main_dependency_requirements_with_a_scope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DATA_WITH_SCOPES)

    assert main(["extract_metadata.py", str(path), "[]", '["numpy", "numpy@extra:slow", "pytest@group:dev"]']) == 0
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



def test_main_fail_on_missing_names_the_entry_with_a_scope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DATA_WITH_SCOPES)

    assert main(["extract_metadata.py", "--fail-on-missing", "true", str(path), "[]", '["tqdm", "tqdm@extra:fast"]']) == 1
    assert "['tqdm@extra:fast']" in capsys.readouterr().err



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
    # "w" for the extra), and "x>=1" and "y" for the project dependencies.
    assert dependencies_requirements_module._parse_requirement.cache_info().misses == 3
    assert dependencies_requirements_module._parse_requirement.cache_info().hits == 5



def test_build_parser_description_is_the_first_line_of_the_docstring() -> None:
    parser = extract_metadata_module._build_parser("extract_metadata.py")

    assert parser.description == extract_metadata_module.__doc__.splitlines()[0]



def test_build_parser_without_docstring(monkeypatch: pytest.MonkeyPatch) -> None:
    # Python runs with -OO strip the docstrings.
    monkeypatch.setattr(extract_metadata_module, "__doc__", None)

    assert extract_metadata_module._build_parser("extract_metadata.py").description == ""



def test_script_runs_with_stripped_docstrings(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')

    result = subprocess.run(
        [sys.executable, "-OO", str(SCRIPT_PATH), str(path), "[]"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["name"] == "coola"



def test_main_non_string_requirement_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "coola"\nversion = "1"\ndependencies = ["a", 1]\n'
    )

    assert main(["extract_metadata.py", str(path), "[]"]) == 1
    assert "[project].dependencies must contain only strings, got: 1" in capsys.readouterr().err



def test_main_project_dependencies_in_json_and_warnings_are_not_duplicated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\ndependencies = ["dup>=1", "dup>=2"]\n'
    )

    exit_code = main(["extract_metadata.py", str(path), "[]", '["dup"]'])
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert report["project_dependencies"] == {"dup": ">=1"}
    assert report["warnings"] == [f"dup has different specifiers in {path}: ['>=1', '>=2']; using '>=1'"]



def test_main_github_output_project_dependencies(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\ndependencies = ["numpy>=1.20"]\n'
    )
    output = tmp_path / "github_output"

    exit_code = main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"])

    assert exit_code == 0
    assert parse_github_output(output.read_text(encoding="utf-8"))["project-dependencies"] == (
        '{"numpy":">=1.20"}'
    )



def test_main_fail_on_dynamic_version(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\ndynamic = ["version"]\n')

    exit_code = main(["extract_metadata.py", "--fail-on-dynamic-version", "true", str(path), "[]"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "[project].version is dynamic, so it cannot be read" in captured.err
    assert captured.out == ""



def test_main_fail_on_dynamic_version_false_keeps_the_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\ndynamic = ["version"]\n')

    exit_code = main(["extract_metadata.py", "--fail-on-dynamic-version", "false", str(path), "[]"])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["version"] == ""



def test_main_invalid_fail_on_dynamic_version_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    exit_code = main(["extract_metadata.py", "--fail-on-dynamic-version", "maybe", str(path), "[]"])

    assert exit_code == 1
    assert "fail-on-dynamic-version must be 'true' or 'false'" in capsys.readouterr().err



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
    assert len(captured.out.splitlines()) == 2  # the warning for the invalid specifier, then the summary
    assert "requires-python=x\\n::error::boom\\nversion=hacked " in captured.out



def test_running_the_script_as_main_exits_with_the_code_of_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')
    output = tmp_path / "github_output"
    monkeypatch.setattr(sys, "argv", ["extract_metadata.py", "--github-output", str(output), str(path), "[]"])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(SCRIPT_PATH), run_name="__main__")

    assert exc_info.value.code == 0
    assert parse_github_output(output.read_text(encoding="utf-8"))["name"] == "coola"
    assert capsys.readouterr().out.startswith("📦 name=coola version=1.2.3 ")



def test_running_the_script_as_main_exits_with_one_on_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["extract_metadata.py", str(tmp_path / "missing.toml"), "[]"])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(SCRIPT_PATH), run_name="__main__")

    assert exc_info.value.code == 1
    assert "missing.toml" in capsys.readouterr().err



def test_running_the_package_with_dash_m_exits_with_the_code_of_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')
    monkeypatch.setattr(sys, "argv", ["__main__.py", str(path), "[]"])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("extract_pyproject_metadata", run_name="__main__")

    assert exc_info.value.code == 0
    assert json.loads(capsys.readouterr().out)["name"] == "coola"



def test_importing_the_script_does_not_run_main(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["extract_metadata.py"])  # would exit with a usage error if main() ran
    spec = importlib.util.spec_from_file_location("extract_metadata_imported", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    spec.loader.exec_module(module)

    assert module.__name__ == "extract_metadata_imported"



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
