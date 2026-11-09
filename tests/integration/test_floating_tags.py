"""Tests of scripts/floating-tags.sh, which the release workflow uses to
move the floating tags."""

import re
import subprocess

import pytest

from tests.helpers import ROOT_PATH

SCRIPT = ROOT_PATH / "scripts" / "floating-tags.sh"
WORKFLOW = ROOT_PATH / ".github" / "workflows" / "release.yaml"


def floating_tags(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(SCRIPT), *args], capture_output=True, text=True, check=False
    )


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("v1.2.3", ["v1.2", "v1"]),
        ("v1.0.0", ["v1.0", "v1"]),
        ("v1.2", ["v1"]),
        ("v10.20.30", ["v10.20", "v10"]),
        ("v0.2.1", ["v0.2"]),
        ("v0.0.1", ["v0.0"]),
        ("v0.2", []),
        ("v0.10", []),
    ],
)
def test_floating_tags_of_a_release_tag(tag: str, expected: list[str]) -> None:
    result = floating_tags(tag)

    assert result.returncode == 0
    assert result.stdout.split() == expected
    assert result.stderr == ""


@pytest.mark.parametrize(
    "tag",
    [
        "v1",
        "1.2.3",
        "v1.2.3.4",
        "v01.2",
        "v1.02",
        "v1.2.x",
        "v1.2.3-rc1",
        "main",
        "",
        "v1.2.3;ls",
        "V1.2",
    ],
)
def test_floating_tags_rejects_what_is_not_a_release_tag(tag: str) -> None:
    result = floating_tags(tag)

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == f"'{tag}' is not a release tag (vMAJOR.MINOR or vMAJOR.MINOR.PATCH)\n"


@pytest.mark.parametrize("args", [[], ["v1.2.3", "v1.2.4"]])
def test_floating_tags_needs_exactly_one_argument(args: list[str]) -> None:
    result = floating_tags(*args)

    assert result.returncode == 1
    assert result.stderr == "usage: floating-tags.sh <release-tag>\n"


def test_the_release_workflow_is_triggered_by_the_tags_that_the_script_accepts() -> None:
    patterns = re.findall(
        r'^\s+- "(v\[0-9\].*)"$', WORKFLOW.read_text(encoding="utf-8"), re.MULTILINE
    )

    assert patterns == ["v[0-9]+.[0-9]+", "v[0-9]+.[0-9]+.[0-9]+"]


def test_the_release_workflow_passes_the_tag_through_the_environment() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "${{ github.ref_name }}" in workflow
    # The tag name is never interpolated in a script.
    scripts = re.findall(r"run: \|\n((?:\s{10}.*\n)+)", workflow)
    assert scripts
    assert not any("${{" in script for script in scripts)
