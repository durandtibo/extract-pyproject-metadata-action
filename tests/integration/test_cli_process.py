"""End-to-end tests that start the launcher script in a new process or as
``__main__``."""

from __future__ import annotations

import importlib.util
import json
import os
import runpy
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from extract_pyproject_metadata.types import Report
from tests.helpers import (
    PACKAGE_PATH,
    SCRIPT_PATH,
    parse_github_output,
    run_script,
    write_pyproject,
)

if TYPE_CHECKING:
    from pathlib import Path


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

    result = run_script([str(path), '[""]'], flags=(), check=True)

    assert json.loads(result.stdout) == {
        "name": "coola",
        "normalized_name": "coola",
        "file_name": "coola",
        "version": "1.2.3",
        "normalized_version": "1.2.3",
        "requires_python": "",
        "extras": ["", "numpy"],
        "groups": [],
        "python_versions": ["3.11", "3.12", "3.13", "3.14", "3.15"],
        "python_min": "3.11",
        "python_max": "3.15",
        "dependency_specifiers": {},
        "dependency_requirements": {},
        "warnings": [],
        "schema_version": 1,
    }


def test_cli_end_to_end_error_exit_code(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.toml"

    result = run_script([str(missing), "[]"], flags=(), check=False)

    assert result.returncode == 1
    assert "not a file" in result.stderr


def test_cli_end_to_end_github_output(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "coola"\nversion = "1.2.3"\n[project.optional-dependencies]\nnumpy = ["numpy"]\n',
    )
    output = tmp_path / "github_output"

    result = run_script(
        ["--github-output", str(output), "--", str(path), '[""]'], flags=(), check=True
    )

    outputs = parse_github_output(output.read_text(encoding="utf-8"))
    report = json.loads(outputs.pop("json"))
    assert list(report) == list(Report.__annotations__)
    assert report["name"] == "coola"
    assert report["extras"] == ["", "numpy"]
    assert outputs == {
        "name": "coola",
        "normalized-name": "coola",
        "file-name": "coola",
        "version": "1.2.3",
        "normalized-version": "1.2.3",
        "requires-python": "",
        "extras": '["","numpy"]',
        "groups": "[]",
        "python-versions": '["3.11","3.12","3.13","3.14","3.15"]',
        "python-min": "3.11",
        "python-max": "3.15",
        "dependency-specifiers": "{}",
    }
    assert result.stdout == (
        "📦 name=coola version=1.2.3 requires-python= "
        'python-versions=["3.11","3.12","3.13","3.14","3.15"] python-min=3.11 python-max=3.15 extras=["","numpy"] groups=[] '
        "dependency-specifiers={}\n"
    )


def test_cli_end_to_end_with_dependencies(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "coola"\nversion = "1.2.3"\ndependencies = ["numpy>=1.20"]\n',
    )

    result = run_script([str(path), "[]", '["numpy", "pandas"]'], flags=(), check=True)

    assert json.loads(result.stdout) == {
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
        "dependency_specifiers": {"numpy": ">=1.20", "pandas": None},
        "dependency_requirements": {
            "numpy": [{"specifier": ">=1.20", "marker": "", "source": "project"}],
            "pandas": [],
        },
        "warnings": [{"code": "dependency-not-found", "message": "dependency 'pandas' not found"}],
        "schema_version": 1,
    }


def test_cli_end_to_end_missing_dependency_is_a_warning(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\ndependencies = ["numpy>=1.20"]\n'
    )
    result = run_script([str(path), "[]", '["numpy", "pandas"]'], flags=(), check=True)

    report = json.loads(result.stdout)
    assert report["dependency_specifiers"] == {"numpy": ">=1.20", "pandas": None}
    assert report["warnings"] == [
        {"code": "dependency-not-found", "message": "dependency 'pandas' not found"}
    ]


def test_cli_end_to_end_strict_fails_on_a_missing_dependency(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\ndependencies = ["numpy>=1.20"]\n'
    )

    result = run_script(
        ["--strict", "true", "--", str(path), "[]", '["pandas"]'], flags=(), check=False
    )

    assert result.returncode == 1
    assert "dependency 'pandas' not found" in result.stderr
    assert result.stdout == ""


def test_script_runs_with_stripped_docstrings(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')

    result = run_script([str(path), "[]"], flags=("-OO",), check=False)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["name"] == "coola"


def test_running_the_script_as_main_exits_with_the_code_of_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')
    output = tmp_path / "github_output"
    monkeypatch.setattr(sys, "argv", ["extract_metadata.py"])
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("INPUT_PYPROJECT_PATH", str(path))

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(SCRIPT_PATH), run_name="__main__")

    assert exc_info.value.code == 0
    assert parse_github_output(output.read_text(encoding="utf-8"))["name"] == "coola"
    assert capsys.readouterr().out.startswith("📦 name=coola version=1.2.3 ")


def test_running_the_script_as_main_exits_with_one_on_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["extract_metadata.py"])
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setenv("INPUT_PYPROJECT_PATH", str(tmp_path / "missing.toml"))

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(SCRIPT_PATH), run_name="__main__")

    assert exc_info.value.code == 1
    assert "missing.toml" in capsys.readouterr().err


def test_the_script_writes_non_ascii_text_with_a_non_utf8_locale(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')
    command = [sys.executable, "-I", "-X", "utf8=0", str(SCRIPT_PATH)]
    environ = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("INPUT_", "PYTHON")) and key != "GITHUB_OUTPUT"
    }
    environ.update(
        {
            "LC_ALL": "C",
            "PYTHONCOERCECLOCALE": "0",
            "PYTHONPATH": str(PACKAGE_PATH.parent),
            "INPUT_PYPROJECT_PATH": str(path),
            "INPUT_EXTRA_VALUES": '["é"]',
        }
    )

    result = subprocess.run(
        command, capture_output=True, check=False, timeout=60, env=environ, cwd=tmp_path
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.decode("utf-8"))["extras"] == ["é"]


def test_importing_the_script_does_not_run_main(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["extract_metadata.py"])
    spec = importlib.util.spec_from_file_location("extract_metadata_imported", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    spec.loader.exec_module(module)

    assert module.__name__ == "extract_metadata_imported"


def test_the_script_ignores_an_argument_on_the_command_line(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')
    environ = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("INPUT_") and key != "GITHUB_OUTPUT"
    }
    environ["INPUT_PYPROJECT_PATH"] = str(path)

    result = subprocess.run(
        [sys.executable, "-I", str(SCRIPT_PATH), "unused"],
        capture_output=True,
        check=False,
        timeout=60,
        env=environ,
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.decode("utf-8"))["name"] == "coola"
