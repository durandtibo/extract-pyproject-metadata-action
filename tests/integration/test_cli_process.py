"""End-to-end tests that start the command line in a new process or as
``__main__``."""

from __future__ import annotations

import importlib.util
import json
import runpy
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from extract_pyproject_metadata.types import Report
from tests.helpers import (
    SCRIPT_PATH,
    parse_github_output,
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


def test_cli_end_to_end_github_output(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "coola"\nversion = "1.2.3"\n[project.optional-dependencies]\nnumpy = ["numpy"]\n',
    )
    output = tmp_path / "github_output"

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--github-output", str(output), "--", str(path), '[""]'],
        capture_output=True,
        text=True,
        check=True,
    )

    outputs = parse_github_output(output.read_text(encoding="utf-8"))
    report = json.loads(outputs.pop("json"))
    assert list(report) == list(Report.__annotations__)
    assert report["name"] == "coola"
    assert report["extras"] == ["", "numpy"]
    assert outputs == {
        "name": "coola",
        "normalized-name": "coola",
        "version": "1.2.3",
        "normalized-version": "1.2.3",
        "description": "",
        "readme": "",
        "license": "",
        "license-files": "[]",
        "authors": "[]",
        "urls": "{}",
        "keywords": "[]",
        "classifiers": "[]",
        "scripts": "{}",
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


def test_running_the_script_as_main_exits_with_the_code_of_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')
    output = tmp_path / "github_output"
    monkeypatch.setattr(
        sys, "argv", ["extract_metadata.py", "--github-output", str(output), str(path), "[]"]
    )

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
    monkeypatch.setattr(
        sys, "argv", ["extract_metadata.py"]
    )  # would exit with a usage error if main() ran
    spec = importlib.util.spec_from_file_location("extract_metadata_imported", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    spec.loader.exec_module(module)

    assert module.__name__ == "extract_metadata_imported"


def test_cli_resolves_a_dynamic_version_from_a_file(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text("1.0-RC1\n")
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "a"\ndynamic = ["version"]\n'
        '[tool.setuptools.dynamic]\nversion = { file = "VERSION" }\n',
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--resolve-dynamic-version",
            "true",
            "--fail-on-dynamic-version",
            "true",
            "--strict",
            "true",
            "--",
            str(path),
            "[]",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    report = json.loads(result.stdout)
    assert (report["version"], report["normalized_version"], report["warnings"]) == (
        "1.0-RC1",
        "1.0rc1",
        [],
    )


def test_cli_does_not_resolve_a_dynamic_version_by_default(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text("1.0\n")
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "a"\ndynamic = ["version"]\n'
        '[tool.setuptools.dynamic]\nversion = { file = "VERSION" }\n',
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--", str(path), "[]"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(result.stdout)["version"] == ""
