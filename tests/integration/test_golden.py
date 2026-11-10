"""Golden tests: every directory of ``test-data/`` with an
``expected.json`` produces that file as the ``json`` output of the action.

A case is a directory with a ``pyproject.toml``, an optional
``inputs.json`` (the action inputs of the case, by input name) and the
``expected.json`` (the value of the ``json`` output). The workflow
``ci-test-action.yaml`` runs the same cases through the real action. To
create or update the golden files, run ``UPDATE_GOLDEN=1 pytest
tests/integration/test_golden.py`` and review the diff.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest

from extract_pyproject_metadata.cli import env_name, main
from tests.helpers import ROOT_PATH, parse_github_output

if TYPE_CHECKING:
    from pathlib import Path

TEST_DATA_PATH = ROOT_PATH / "test-data"
CASES = sorted(path.parent.name for path in TEST_DATA_PATH.glob("*/expected.json"))


# The inputs that are positional arguments of the command line, with their default.
def read_inputs(case: str) -> dict[str, str]:
    """Return the inputs of a case (none when it has no ``inputs.json``)."""
    path = TEST_DATA_PATH / case / "inputs.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_environ(case: str, output: Path) -> dict[str, str]:
    """Build the environment that the action sets for a case."""
    inputs = {"pyproject-path": f"test-data/{case}/pyproject.toml", **read_inputs(case)}
    return {
        "GITHUB_OUTPUT": str(output),
        **{env_name(name): value for name, value in inputs.items()},
    }


def test_there_are_golden_cases() -> None:
    assert len(CASES) >= 10


def test_every_case_directory_has_a_pyproject() -> None:
    assert [
        path.parent.name
        for path in TEST_DATA_PATH.glob("*/expected.json")
        if not (path.parent / "pyproject.toml").exists()
    ] == []


@pytest.mark.parametrize("case", CASES)
def test_the_json_output_is_the_golden_file(
    case: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(ROOT_PATH)
    output = tmp_path / "output"
    expected_path = TEST_DATA_PATH / case / "expected.json"

    assert main(build_environ(case, output)) == 0

    capsys.readouterr()
    actual = parse_github_output(output.read_bytes().decode("utf-8"))["json"]
    if os.environ.get("UPDATE_GOLDEN") == "1":
        expected_path.write_text(
            json.dumps(json.loads(actual), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    assert json.loads(actual) == json.loads(expected_path.read_text(encoding="utf-8"))
