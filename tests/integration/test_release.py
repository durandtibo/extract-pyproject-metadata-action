"""Tests of the release workflow and of the release notes."""

from __future__ import annotations

import yaml

from tests.helpers import ACTION_PATH, ROOT_PATH

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
    assert RELEASE["permissions"] == {"contents": "read"}
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
