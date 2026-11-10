"""Tests of scripts/run.sh, with stand-ins for the Python
interpreters."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers import (
    ROOT_PATH,
    RUN_PATH,
    SCRIPT_PATH,
    parse_github_output,
    run_run_sh,
    write_pyproject,
)


def test_run_sh_isolates_python_and_runs_the_script_with_python3(tmp_path: Path) -> None:
    process, calls = run_run_sh(tmp_path)

    assert process.returncode == 0
    assert calls == [["python3", "-I", "-B", str(SCRIPT_PATH)]]


def test_run_sh_falls_back_to_python_when_python3_is_missing(tmp_path: Path) -> None:
    process, calls = run_run_sh(tmp_path, pythons=("python",))

    assert process.returncode == 0
    assert calls == [["python", "-I", "-B", str(SCRIPT_PATH)]]


def test_run_sh_falls_back_to_python_when_python3_is_older_than_3_11(tmp_path: Path) -> None:
    process, calls = run_run_sh(
        tmp_path, pythons=("python3", "python"), STUB_VERSION_STATUS_PYTHON3="1"
    )

    assert process.returncode == 0
    assert calls == [["python", "-I", "-B", str(SCRIPT_PATH)]]


def test_run_sh_prefers_python3(tmp_path: Path) -> None:
    _, calls = run_run_sh(tmp_path, pythons=("python3", "python"))

    assert [call[0] for call in calls] == ["python3"]


@pytest.mark.parametrize(
    ("pythons", "env"),
    [
        ((), {}),
        (("python3",), {"STUB_VERSION_STATUS_PYTHON3": "1"}),
        (
            ("python3", "python"),
            {"STUB_VERSION_STATUS_PYTHON3": "1", "STUB_VERSION_STATUS_PYTHON": "1"},
        ),
    ],
)
def test_run_sh_fails_with_a_clear_message_without_python_3_11(
    tmp_path: Path, pythons: tuple[str, ...], env: dict[str, str]
) -> None:
    process, calls = run_run_sh(tmp_path, pythons=pythons, **env)

    assert process.returncode == 1
    assert process.stderr.startswith(
        "::error::This action requires Python 3.11 or later, but neither 'python3' nor 'python' "
        "on PATH is Python 3.11 or later"
    )
    assert process.stderr.count("\n") == 1  # one annotation, no traceback
    assert calls == []


@pytest.mark.parametrize("status", ["1", "2", "7"])
def test_run_sh_exits_with_the_status_of_the_script(tmp_path: Path, status: str) -> None:
    process, _ = run_run_sh(tmp_path, STUB_SCRIPT_STATUS=status)

    assert process.returncode == int(status)


def test_run_sh_installs_nothing_and_needs_no_temporary_directory(tmp_path: Path) -> None:
    process, calls = run_run_sh(tmp_path)

    assert process.returncode == 0
    assert process.stdout == ""
    assert [call[1:3] for call in calls] == [["-I", "-B"]]  # no "-m pip", no "-m venv"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["bin", "calls.log"]


def _real_python_path(tmp_path: Path) -> Path:
    """Return a ``bin`` directory whose ``python3`` is the Python of the tests."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "python3").write_text(f'#!/usr/bin/env bash\nexec "{sys.executable}" "$@"\n')
    (bin_dir / "python3").chmod(0o755)
    return bin_dir


def test_run_sh_end_to_end_with_the_real_python(tmp_path: Path) -> None:
    bin_dir = _real_python_path(tmp_path)
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')
    output = tmp_path / "github_output"

    process = subprocess.run(
        ["/bin/bash", str(RUN_PATH)],
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "GITHUB_OUTPUT": str(output),
            "INPUT_PYPROJECT_PATH": str(path),
        },
    )

    assert process.returncode == 0, process.stderr
    assert parse_github_output(output.read_text(encoding="utf-8"))["name"] == "coola"


def test_run_sh_ignores_modules_and_variables_of_the_caller(tmp_path: Path) -> None:
    bin_dir = _real_python_path(tmp_path)
    workspace = tmp_path / "workspace"
    for name in ("json", "tomllib"):
        (workspace / name).mkdir(parents=True)
        (workspace / name / "__init__.py").write_text('raise RuntimeError("shadowed")\n')
    hostile = tmp_path / "hostile"
    hostile.mkdir()
    (hostile / "re.py").write_text('raise RuntimeError("shadowed by PYTHONPATH")\n')
    path = write_pyproject(workspace, '[project]\nname = "coola"\nversion = "1.2.3"\n')
    output = tmp_path / "github_output"

    process = subprocess.run(
        ["/bin/bash", str(RUN_PATH)],
        capture_output=True,
        text=True,
        check=False,
        cwd=workspace,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "PYTHONPATH": str(hostile),
            "GITHUB_OUTPUT": str(output),
            "INPUT_PYPROJECT_PATH": str(path),
        },
    )

    assert process.returncode == 0, process.stderr
    assert parse_github_output(output.read_text(encoding="utf-8"))["name"] == "coola"


def test_run_sh_writes_no_bytecode(tmp_path: Path) -> None:
    # Run a copy of the action, so that bytecode left by other tests cannot hide a failure.
    action = tmp_path / "action"
    ignore = shutil.ignore_patterns("__pycache__")
    shutil.copytree(ROOT_PATH / "scripts", action / "scripts", ignore=ignore)
    shutil.copytree(ROOT_PATH / "src", action / "src", ignore=ignore)
    bin_dir = _real_python_path(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = write_pyproject(workspace, '[project]\nname = "coola"\nversion = "1.2.3"\n')

    process = subprocess.run(
        ["/bin/bash", str(action / "scripts" / "run.sh")],
        capture_output=True,
        text=True,
        check=False,
        cwd=workspace,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "INPUT_PYPROJECT_PATH": str(path)},
    )

    assert process.returncode == 0, process.stderr
    assert list(tmp_path.rglob("__pycache__")) == []
