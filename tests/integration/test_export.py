"""Tests of the files shipped to the consumers of the action (``dev/check_export.sh``)."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from tests.helpers import ROOT_PATH

if TYPE_CHECKING:
    from pathlib import Path

SCRIPT_PATH = ROOT_PATH / "dev" / "check_export.sh"
GIT = ["git", "-c", "user.name=test", "-c", "user.email=test@example.com"]


def make_repository(path: Path, *, attributes: str) -> None:
    """Commit a minimal action in ``path`` with the given ``.gitattributes``."""
    for name in (
        "LICENSE",
        "action.yaml",
        "README.md",
        "scripts/run.sh",
        "scripts/extract_metadata.py",
        "scripts/compare_json.py",
        "src/extract_pyproject_metadata/__init__.py",
        "src/extract_pyproject_metadata/_vendor/licenses/LICENSE",
    ):
        file = path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("x\n", encoding="utf-8")
    (path / ".gitattributes").write_text(attributes, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run([*GIT, "add", "-A"], cwd=path, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", "init"], cwd=path, check=True)


def run_check(cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run the export check in ``cwd``."""
    return subprocess.run(
        ["bash", str(SCRIPT_PATH)], cwd=cwd, capture_output=True, text=True, check=False
    )


ATTRIBUTES = "/.gitattributes export-ignore\n/README.md export-ignore\n/scripts/compare_json.py export-ignore\n"


def test_the_exported_files_of_this_repository_are_the_files_the_action_needs() -> None:
    result = run_check(ROOT_PATH)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "✅ The exported files are the expected ones" in result.stdout


def test_the_check_passes_when_only_the_runtime_files_are_exported(tmp_path: Path) -> None:
    make_repository(tmp_path, attributes=ATTRIBUTES)

    result = run_check(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "✅ The exported files are the expected ones (11 entries)" in result.stdout


@pytest.mark.parametrize(
    "extra",
    [
        "/action.yaml export-ignore\n",
        "/scripts/run.sh export-ignore\n",
        "/src/extract_pyproject_metadata/__init__.py export-ignore\n",
    ],
)
def test_the_check_fails_when_a_runtime_file_is_not_exported(tmp_path: Path, extra: str) -> None:
    make_repository(tmp_path, attributes=ATTRIBUTES + extra)

    result = run_check(tmp_path)

    assert result.returncode == 1
    assert "::error::The exported files differ from the files the action needs" in result.stdout


def test_the_check_fails_when_a_file_that_the_action_does_not_need_is_exported(
    tmp_path: Path,
) -> None:
    make_repository(
        tmp_path, attributes="/.gitattributes export-ignore\n/README.md export-ignore\n"
    )

    result = run_check(tmp_path)

    assert result.returncode == 1
    assert "> scripts/compare_json.py" in result.stdout
