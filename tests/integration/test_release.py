"""Tests of the release workflow and of the release notes."""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

import yaml

from tests.helpers import ACTION_PATH, ROOT_PATH

if TYPE_CHECKING:
    from pathlib import Path

WORKFLOWS_PATH = ROOT_PATH / ".github" / "workflows"
NOTES = (ROOT_PATH / "release-notes" / "v0.3.0.md").read_text(encoding="utf-8")
ACTION = yaml.safe_load(ACTION_PATH.read_text(encoding="utf-8"))
RELEASE = yaml.safe_load((WORKFLOWS_PATH / "release.yaml").read_text(encoding="utf-8"))


def test_the_notes_do_not_claim_windows_support() -> None:
    assert "Windows is not supported" in NOTES
    assert "Windows runners are supported" not in NOTES


def test_the_notes_have_no_table_of_removed_names() -> None:
    assert "Removed" not in NOTES


def test_the_notes_list_the_current_inputs_and_outputs() -> None:
    for name in [*ACTION["inputs"], *ACTION["outputs"]]:
        assert f"`{name}`" in NOTES


def test_the_release_runs_on_a_version_tag_only() -> None:
    patterns = RELEASE[True]["push"]["tags"]

    assert patterns == ["v[0-9]+.[0-9]+.[0-9]+"]
    assert "branches" not in RELEASE[True]["push"]


def test_the_release_runs_the_checks_first_and_only_it_can_write() -> None:
    jobs = RELEASE["jobs"]

    assert jobs["checks"]["uses"] == "./.github/workflows/ci.yaml"
    assert jobs["release"]["needs"] == "checks"
    assert "permissions" not in RELEASE
    assert jobs["checks"]["permissions"] == {"contents": "read"}
    assert jobs["release"]["permissions"] == {"contents": "write"}


def test_ci_can_be_called_by_the_release() -> None:
    ci = yaml.safe_load((WORKFLOWS_PATH / "ci.yaml").read_text(encoding="utf-8"))

    assert "workflow_call" in ci[True]


def test_the_release_creates_the_release_and_moves_no_tag() -> None:
    steps = RELEASE["jobs"]["release"]["steps"]
    commands = " ".join(step.get("run", "") for step in steps)

    assert "gh release create" in commands
    assert "git tag" not in commands
    assert "git push" not in commands


def test_dependabot_groups_the_updates() -> None:
    config = yaml.safe_load((ROOT_PATH / ".github" / "dependabot.yml").read_text(encoding="utf-8"))

    assert {update["package-ecosystem"] for update in config["updates"]} == {
        "pip",
        "github-actions",
    }
    assert all("groups" in update for update in config["updates"])


def run_release_step(tmp_path: Path, tag: str) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run the ``run`` script of the release step in ``tmp_path`` with a ``gh`` that only logs
    its arguments, and return the result and what ``gh`` was called with."""
    (step,) = [
        step
        for step in RELEASE["jobs"]["release"]["steps"]
        if step.get("name") == "Create the GitHub release"
    ]
    bin_path = tmp_path / "bin"
    bin_path.mkdir()
    gh = bin_path / "gh"
    gh.write_text('#!/bin/sh\necho "$@" >> "$GH_LOG"\n', encoding="utf-8")
    gh.chmod(0o755)
    log = tmp_path / "gh.log"
    environ = {
        "PATH": f"{bin_path}{os.pathsep}{os.environ['PATH']}",
        "GH_LOG": str(log),
        "TAG": tag,
    }
    result = subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env=environ,
        cwd=tmp_path,
    )
    return result, log.read_text(encoding="utf-8") if log.exists() else ""


def test_the_release_fails_without_reviewed_notes(tmp_path: Path) -> None:
    result, gh_calls = run_release_step(tmp_path, "v9.9.9")

    assert result.returncode == 1
    assert "release-notes/v9.9.9.md: missing" in result.stderr
    assert gh_calls == ""


def test_the_release_uses_the_notes_file_of_the_tag(tmp_path: Path) -> None:
    (tmp_path / "release-notes").mkdir()
    (tmp_path / "release-notes" / "v9.9.9.md").write_text("# v9.9.9\n", encoding="utf-8")

    result, gh_calls = run_release_step(tmp_path, "v9.9.9")

    assert result.returncode == 0, result.stderr
    assert gh_calls == (
        "release create v9.9.9 --title v9.9.9 --notes-file release-notes/v9.9.9.md --verify-tag\n"
    )


def test_the_release_does_not_generate_notes() -> None:
    text = (WORKFLOWS_PATH / "release.yaml").read_text(encoding="utf-8")

    assert "--generate-notes" not in text
