"""Tests of scripts/run.sh, with stand-ins for the Python interpreters."""



import re
import subprocess
import sys
from pathlib import Path

import pytest
from helpers import (
    REQUIREMENTS_PATH,
    RUN_PATH,
    SCRIPT_PATH,
    STUB_SYSTEM_PYTHON,
    fake_packaging,
    parse_github_output,
    run_run_sh,
    write_pyproject,
)


def test_run_sh_uses_the_python_on_path_when_the_requirements_are_available(tmp_path: Path) -> None:
    result = run_run_sh(tmp_path, ["--flag", "a b", "", "[]"])

    assert result.process.returncode == 0
    assert result.calls == [
        ["python3", "version"],
        ["python3", "probe"],
        ["python3", str(SCRIPT_PATH), "--flag", "a b", "", "[]"],
    ]
    assert result.venvs == []



def test_run_sh_installs_the_requirements_in_a_private_venv_when_they_are_missing(tmp_path: Path) -> None:
    result = run_run_sh(tmp_path, ["--flag", "a b", "[]"], STUB_PROBE_STATUS="1")

    assert result.process.returncode == 0
    assert len(result.created_venvs) == 1
    venv = result.created_venvs[0]
    assert venv.parent == tmp_path / "runner-temp"
    assert result.calls == [
        ["python3", "version"],
        ["python3", "probe"],
        ["python3", "-m", "venv", "--system-site-packages", str(venv)],
        ["venv-python", "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", str(REQUIREMENTS_PATH)],
        ["venv-python", str(SCRIPT_PATH), "--flag", "a b", "[]"],
    ]



@pytest.mark.parametrize(("version", "installs"), [("22.9", True), ("23.0", False), ("26.1", False), ("30.0", False)])
def test_run_sh_installs_packaging_in_a_venv_only_when_it_is_older_than_the_requirement(
    tmp_path: Path, version: str, installs: bool
) -> None:
    result = run_run_sh(
        tmp_path,
        ["a"],
        STUB_REAL_PYTHON=sys.executable,
        STUB_FAKE_PACKAGING=str(fake_packaging(tmp_path, version)),
    )

    assert result.process.returncode == 0
    assert len(result.created_venvs) == int(installs)



def test_run_sh_installs_packaging_in_a_venv_when_it_cannot_be_imported(tmp_path: Path) -> None:
    broken = tmp_path / "broken"
    (broken / "packaging").mkdir(parents=True)
    (broken / "packaging" / "__init__.py").write_text("raise ImportError('no packaging')\n")

    result = run_run_sh(
        tmp_path, ["a"], STUB_REAL_PYTHON=sys.executable, STUB_FAKE_PACKAGING=str(broken)
    )

    assert result.process.returncode == 0
    assert len(result.created_venvs) == 1



def test_run_sh_says_in_the_log_that_it_installs_the_requirements(tmp_path: Path) -> None:
    result = run_run_sh(tmp_path, ["a"], STUB_PROBE_STATUS="1")

    assert result.process.stdout == (
        "'packaging' is missing or too old in 'python3': installing "
        "packaging>=23.0,<27 in a private virtual environment\n"
    )



def test_run_sh_names_the_python_executable_in_the_log(tmp_path: Path) -> None:
    custom = tmp_path / "custom-python"
    custom.write_text(STUB_SYSTEM_PYTHON.replace("python3", "custom"))
    custom.chmod(0o755)

    result = run_run_sh(tmp_path, ["a"], PYTHON_EXECUTABLE=str(custom), STUB_PROBE_STATUS="1")

    assert f"in '{custom}': installing" in result.process.stdout



def test_run_sh_does_not_say_anything_when_the_requirements_are_available(tmp_path: Path) -> None:
    assert run_run_sh(tmp_path, ["a"]).process.stdout == ""



@pytest.mark.parametrize("probe_status", ["0", "1"])
@pytest.mark.parametrize("status", [1, 2, 3])
def test_run_sh_exits_with_the_status_of_the_script(tmp_path: Path, probe_status: str, status: int) -> None:
    result = run_run_sh(tmp_path, ["a"], STUB_PROBE_STATUS=probe_status, STUB_SCRIPT_STATUS=str(status))

    assert result.process.returncode == status



def test_run_sh_uses_a_new_venv_on_every_run(tmp_path: Path) -> None:
    first = run_run_sh(tmp_path, ["a"], STUB_PROBE_STATUS="1")
    second = run_run_sh(tmp_path, ["a"], STUB_PROBE_STATUS="1")

    assert len(first.created_venvs) == len(second.created_venvs) == 1
    assert first.created_venvs != second.created_venvs



@pytest.mark.parametrize(
    "env",
    [
        {},  # success
        {"STUB_SCRIPT_STATUS": "3"},  # the script fails
        {"STUB_PIP_STATUS": "1"},  # the requirements cannot be installed
        {"STUB_VENV_STATUS": "1"},  # the venv cannot be created
    ],
)
def test_run_sh_removes_the_venv_when_it_ends(tmp_path: Path, env: dict[str, str]) -> None:
    result = run_run_sh(tmp_path, ["a"], STUB_PROBE_STATUS="1", **env)

    assert len(result.created_venvs) == 1
    assert result.venvs == []
    assert not result.created_venvs[0].exists()



def test_run_sh_does_not_remove_other_files_of_the_temporary_directory(tmp_path: Path) -> None:
    (tmp_path / "runner-temp").mkdir()
    (tmp_path / "runner-temp" / "other-file").write_text("keep")
    (tmp_path / "runner-temp" / "extract-pyproject-metadata-venv.old").mkdir()  # left by an earlier run

    run_run_sh(tmp_path, ["a"], STUB_PROBE_STATUS="1")

    assert (tmp_path / "runner-temp" / "other-file").read_text() == "keep"
    assert (tmp_path / "runner-temp" / "extract-pyproject-metadata-venv.old").is_dir()



def test_run_sh_fails_with_a_clear_message_when_the_venv_cannot_be_created(tmp_path: Path) -> None:
    result = run_run_sh(tmp_path, ["a"], STUB_PROBE_STATUS="1", STUB_VENV_STATUS="1")

    assert result.process.returncode == 1
    assert re.search(r"^::error::Could not install the 'packaging' Python package ", result.process.stderr)
    assert result.calls == [
        ["python3", "version"],
        ["python3", "probe"],
        ["python3", "-m", "venv", "--system-site-packages", str(result.created_venvs[0])],
    ]
    assert all(str(SCRIPT_PATH) not in call for call in result.calls)



def test_run_sh_fails_with_a_clear_message_when_the_requirements_cannot_be_installed(tmp_path: Path) -> None:
    result = run_run_sh(tmp_path, ["a"], STUB_PROBE_STATUS="1", STUB_PIP_STATUS="1")

    assert result.process.returncode == 1
    assert "::error::Could not install the 'packaging' Python package" in result.process.stderr
    assert all(str(SCRIPT_PATH) not in call for call in result.calls)



def test_run_sh_install_error_mentions_the_package_index(tmp_path: Path) -> None:
    result = run_run_sh(tmp_path, ["a"], STUB_PROBE_STATUS="1", STUB_PIP_STATUS="1")

    assert "needs access to a package index" in result.process.stderr
    assert "install it in the Python on PATH" in result.process.stderr



def test_run_sh_fails_when_the_temporary_directory_cannot_be_created(tmp_path: Path) -> None:
    result = run_run_sh(tmp_path, ["a"], STUB_PROBE_STATUS="1", RUNNER_TEMP=str(tmp_path / "does-not-exist"))

    assert result.process.returncode == 1
    assert "::error::Could not install" in result.process.stderr
    assert result.calls == [["python3", "version"], ["python3", "probe"]]



def test_run_sh_uses_the_python_executable_when_it_is_set(tmp_path: Path) -> None:
    custom = tmp_path / "custom-python"
    custom.write_text(STUB_SYSTEM_PYTHON.replace("python3", "custom"))
    custom.chmod(0o755)

    result = run_run_sh(tmp_path, ["a"], PYTHON_EXECUTABLE=str(custom))

    assert result.process.returncode == 0
    assert result.calls == [["custom", "version"], ["custom", "probe"], ["custom", str(SCRIPT_PATH), "a"]]



def test_run_sh_creates_the_venv_with_the_python_executable(tmp_path: Path) -> None:
    custom = tmp_path / "custom-python"
    custom.write_text(STUB_SYSTEM_PYTHON.replace("python3", "custom"))
    custom.chmod(0o755)

    result = run_run_sh(tmp_path, ["a"], PYTHON_EXECUTABLE=str(custom), STUB_PROBE_STATUS="1")

    assert result.process.returncode == 0
    assert [call[:3] for call in result.calls[:3]] == [
        ["custom", "version"],
        ["custom", "probe"],
        ["custom", "-m", "venv"],
    ]
    assert result.calls[-1][0] == "venv-python"



def test_run_sh_uses_python3_when_the_python_executable_is_empty(tmp_path: Path) -> None:
    result = run_run_sh(tmp_path, ["a"], PYTHON_EXECUTABLE="")

    assert result.calls[-1] == ["python3", str(SCRIPT_PATH), "a"]



def test_run_sh_fails_with_a_clear_message_when_the_python_executable_cannot_be_run(
    tmp_path: Path,
) -> None:
    result = run_run_sh(tmp_path, ["a"], PYTHON_EXECUTABLE=str(tmp_path / "missing-python"))

    assert result.process.returncode == 1
    assert re.search(
        r"^::error::This action requires Python 3\.11 or later, but '.*missing-python' is older, "
        r"missing or cannot be run\..*python-executable input",
        result.process.stderr,
    )
    assert result.calls == []



def test_run_sh_fails_with_a_clear_message_when_python_is_older_than_3_11(tmp_path: Path) -> None:
    result = run_run_sh(tmp_path, ["a"], STUB_VERSION_STATUS="1")

    assert result.process.returncode == 1
    assert result.process.stderr.startswith("::error::This action requires Python 3.11 or later")
    assert result.calls == [["python3", "version"]]
    assert result.venvs == []



def test_run_sh_end_to_end_with_the_real_python(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "python3").write_text(f'#!/usr/bin/env bash\nexec "{sys.executable}" "$@"\n')
    (bin_dir / "python3").chmod(0o755)
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')
    output = tmp_path / "github_output"

    process = subprocess.run(
        ["/bin/bash", str(RUN_PATH), "--github-output", str(output), "--", str(path), "[]"],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "RUNNER_TEMP": str(tmp_path)},
    )

    assert process.returncode == 0, process.stderr
    assert parse_github_output(output.read_text(encoding="utf-8"))["name"] == "coola"
    assert list(tmp_path.glob("extract-pyproject-metadata-venv.*")) == []  # the Python had packaging



def test_run_sh_fails_with_a_clear_message_on_a_windows_runner(tmp_path: Path) -> None:
    result = run_run_sh(tmp_path, ["a"], RUNNER_OS="Windows")

    assert result.process.returncode == 1
    assert result.process.stderr == "::error::This action does not support Windows runners. Use a Linux or macOS runner.\n"
    assert result.calls == []



@pytest.mark.parametrize("runner_os", ["Linux", "macOS", ""])
def test_run_sh_runs_on_the_other_runners(tmp_path: Path, runner_os: str) -> None:
    result = run_run_sh(tmp_path, ["a"], RUNNER_OS=runner_os)

    assert result.process.returncode == 0
    assert result.calls[-1] == ["python3", str(SCRIPT_PATH), "a"]
