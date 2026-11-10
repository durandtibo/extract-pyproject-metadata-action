"""End-to-end tests of the command line with malformed arguments.

Each test starts the script in a new process, like ``scripts/run.sh``
does, and checks the contract of a bad input: exit code 1, an error on
stderr without a Python traceback and nothing on stdout. Errors of the
individual parsers are tested in ``tests/unit``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from tests.helpers import SCRIPT_PATH

if TYPE_CHECKING:
    from pathlib import Path

VALID = '[project]\nname = "coola"\nversion = "1.2.3"\n'


def run_script(
    tmp_path: Path, args: list[str], content: str = VALID
) -> subprocess.CompletedProcess[str]:
    """Write ``content`` to a pyproject.toml, then run the script with
    ``args``.

    ``{path}`` in ``args`` is replaced by the path of the file.
    """
    path = tmp_path / "pyproject.toml"
    path.write_text(content, encoding="utf-8")
    argv = [arg.replace("{path}", str(path)) for arg in args]
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT_PATH), *argv],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


@pytest.mark.parametrize(
    ("args", "message"),
    [
        # extra-values
        (["{path}", ""], "extra-values: not valid JSON"),
        (["{path}", " "], "extra-values: not valid JSON"),
        (["{path}", "[1, 2"], "extra-values: not valid JSON"),
        (["{path}", "['a']"], "extra-values: not valid JSON"),
        (["{path}", "null"], "extra-values: must be a JSON array of strings"),
        (["{path}", "{}"], "extra-values: must be a JSON array of strings"),
        (["{path}", '"a"'], "extra-values: must be a JSON array of strings"),
        (["{path}", "[null]"], "extra-values: must be a JSON array of strings"),
        (["{path}", '["a", ["b"]]'], "extra-values: must be a JSON array of strings"),
        (["{path}", "NaN"], "extra-values: must be a JSON array of strings"),
        # dependencies
        (["{path}", "[]", ""], "dependencies: not valid JSON"),
        (["{path}", "[]", "coola"], "dependencies: not valid JSON"),
        (["{path}", "[]", '{"a": 1}'], "dependencies: must be a JSON array of strings"),
        (["{path}", "[]", "[1]"], "dependencies: must be a JSON array of strings"),
        # python-candidates
        (["--python-candidates", "3.12", "{path}", "[]"], "python-candidates"),
        (["--python-candidates", "[3.12]", "{path}", "[]"], "python-candidates"),
        (["--python-candidates", '["3"]', "{path}", "[]"], "python-candidates"),
        (["--python-candidates", '["x.y"]', "{path}", "[]"], "python-candidates"),
        # booleans
        (["--strict", "0", "{path}", "[]"], "strict"),
        # the file
        (["", "[]"], "not a file"),
        (["{path}.missing", "[]"], "not a file"),
    ],
)
def test_invalid_argument_fails_cleanly(tmp_path: Path, args: list[str], message: str) -> None:
    result = run_script(tmp_path, args)

    assert result.returncode == 1
    assert result.stdout == ""
    assert message in result.stderr
    assert "Traceback" not in result.stderr


def test_a_directory_instead_of_a_file_fails_cleanly(tmp_path: Path) -> None:
    result = run_script(tmp_path, [str(tmp_path), "[]"])

    assert result.returncode == 1
    assert result.stdout == ""
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "content",
    [
        "",  # no [project] table
        "[project]\n",
        '[project]\nname = ""\nversion = "1"\n',
        '[project]\nname = 1\nversion = "1"\n',
        '[project]\nname = "a"\nversion = []\n',
        '[project]\nname = "a"\nversion = "1"\noptional-dependencies = []\n',
        "[project]\nname = 'a'\nversion = 'unterminated\n",
        "project = 1\n",
        "\x00",
    ],
)
def test_a_malformed_pyproject_fails_cleanly(tmp_path: Path, content: str) -> None:
    result = run_script(tmp_path, ["{path}", "[]"], content)

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.strip() != ""
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "content",
    [
        '[project]\nname = "a"\nversion = "1"\ndependencies = "numpy"\n',
        '[project]\nname = "a"\nversion = "1"\ndependencies = [1]\n',
        '[project]\nname = "a"\nversion = "1"\n[project.optional-dependencies]\nx = [1]\n',
        '[project]\nname = "a"\nversion = "1"\n[dependency-groups]\ndev = [{include-group = 1}]\n',
    ],
)
def test_a_malformed_requirement_table_fails_only_for_a_lookup(
    tmp_path: Path, content: str
) -> None:
    without_lookup = run_script(tmp_path, ["{path}", "[]", "[]"], content)
    with_lookup = run_script(tmp_path, ["{path}", "[]", '["numpy"]'], content)

    assert without_lookup.returncode == 0
    assert json.loads(without_lookup.stdout)["dependency_specifiers"] == {}
    assert with_lookup.returncode == 1
    assert with_lookup.stdout == ""
    assert "Traceback" not in with_lookup.stderr


# 5000 items stay below the 128 KiB limit of one argument on Linux (MAX_ARG_STRLEN).
@pytest.mark.parametrize("count", [1, 1000, 5000])
def test_a_long_valid_array_is_accepted(tmp_path: Path, count: int) -> None:
    extras = json.dumps([f"extra{i}" for i in range(count)])

    result = run_script(tmp_path, ["{path}", extras])

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout)["extras"] == [f"extra{i}" for i in range(count)]


def test_non_ascii_values_round_trip(tmp_path: Path) -> None:
    content = '[project]\nname = "cafe"\nversion = "1"\nrequires-python = "naïve ☕"\n'

    result = run_script(tmp_path, ["{path}", '["é"]'], content)

    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["requires_python"] == "naïve ☕"
    assert report["extras"] == ["é"]


@pytest.mark.parametrize("value", ["TRUE", " True ", "false"])
def test_booleans_are_case_insensitive_and_trimmed(tmp_path: Path, value: str) -> None:
    result = run_script(tmp_path, ["--strict", value, "{path}", "[]"])

    assert result.returncode == 0


CYCLE = (
    '[project]\nname = "a"\nversion = "1"\n[dependency-groups]\ndev = [{include-group = "dev"}]\n'
)


def test_a_dependency_group_cycle_is_a_warning(tmp_path: Path) -> None:
    result = run_script(tmp_path, ["{path}", "[]", '["dev"]'], CYCLE)

    assert result.returncode == 0
    assert "include-group cycle: dev -> dev" in json.loads(result.stdout)["warnings"][0]


def test_a_dependency_group_cycle_fails_with_strict(tmp_path: Path) -> None:
    result = run_script(tmp_path, ["--strict", "true", "{path}", "[]", '["dev"]'], CYCLE)

    assert result.returncode == 1
    assert result.stdout == ""
    assert "include-group cycle" in result.stderr
    assert "Traceback" not in result.stderr
