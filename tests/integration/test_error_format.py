"""Tests that every error of the action has the form ``<field>: <problem>``,
without the name of the file."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from tests.helpers import run_script as start_script

if TYPE_CHECKING:
    import subprocess
    from pathlib import Path

# An input name, "pyproject-path", or a TOML path such as "[project].version" or
# "[project.optional-dependencies].x", then a colon and the problem.
FORMAT = re.compile(r"(\[[\w.\-]+\](\.[\w\-]+)*|[a-z\-]+): \S")

PROJECT = '[project]\nname = "a"\nversion = "1"\n'
ARGS = ["{path}", "[]"]

CASES = [
    pytest.param("", ARGS, r"\[project\]\.name", id="empty-file"),
    pytest.param("[project\n", ARGS, "pyproject-path", id="invalid-toml"),
    pytest.param("[project]\n", ARGS, r"\[project\]\.name", id="missing-name"),
    pytest.param('[project]\nname = "a"\n', ARGS, r"\[project\]\.version", id="missing-version"),
    pytest.param(
        '[project]\nname = "a"\nversion = "x y"\n', ARGS, r"\[project\]\.version", id="bad-version"
    ),
    pytest.param(
        '[project]\nname = "-a"\nversion = "1"\n', ARGS, r"\[project\]\.name", id="bad-name"
    ),
    pytest.param(PROJECT + "requires-python = 1\n", ARGS, r"\[project\]\.requires-python", id="rp"),
    pytest.param(PROJECT + "dynamic = 1\n", ARGS, r"\[project\]\.dynamic", id="dynamic"),
    pytest.param("dependency-groups = 1\n" + PROJECT, ARGS, r"\[dependency-groups\]", id="groups"),
    pytest.param(PROJECT, ["--strict", "maybe", *ARGS], "strict", id="strict"),
    pytest.param(PROJECT, ["--python-candidates", "3.12", *ARGS], "python-candidates", id="cand"),
    pytest.param(PROJECT, ["{path}", "[1]"], "extra-values", id="extras"),
    pytest.param(PROJECT, ["{path}", "[]", '["a@dev"]'], "dependencies", id="dependencies"),
]


def run(tmp_path: Path, content: str | None, args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run the script on a pyproject.toml with ``content`` (none if None)."""
    path = tmp_path / "pyproject.toml"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    argv = [arg.replace("{path}", str(path)) for arg in args]
    return start_script(argv)


@pytest.mark.parametrize(("content", "args", "field"), CASES)
def test_an_error_is_field_colon_problem(
    tmp_path: Path, content: str, args: list[str], field: str
) -> None:
    result = run(tmp_path, content, args)

    assert result.returncode == 1
    message = result.stderr.strip().removeprefix(f"{tmp_path / 'pyproject.toml'}: ")
    assert FORMAT.match(message), message
    assert re.match(field, message), message
    assert str(tmp_path) not in message


def test_a_missing_file_is_reported_on_pyproject_path(tmp_path: Path) -> None:
    result = run(tmp_path, None, ARGS)

    assert result.returncode == 1
    assert result.stderr.strip().endswith(": pyproject-path: not a file")


def test_an_annotation_carries_the_file_and_not_the_path_in_the_message(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run(tmp_path, "[project]\n", ["--github-output", str(out), *ARGS])

    assert result.returncode == 1
    assert (
        result.stderr.strip()
        == f"::error file={tmp_path / 'pyproject.toml'}::[project].name: missing"
    )
