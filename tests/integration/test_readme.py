"""Tests that the examples and the generated tables of ``README.md`` are
the real ones."""

from __future__ import annotations

import json
import re
import sys
from typing import TYPE_CHECKING

import pytest
import yaml

from extract_pyproject_metadata.types import Report
from tests.helpers import ACTION_PATH, README_PATH, ROOT_PATH
from tests.integration.test_workflows import load_script

if TYPE_CHECKING:
    from pathlib import Path

generate_docs = load_script("generate_docs")

EXAMPLES = sorted((ROOT_PATH / "tests" / "examples").glob("*.yaml"))
FIXTURES = [*EXAMPLES, *(ROOT_PATH / "test-data").glob("*/pyproject.toml")]
README = README_PATH.read_text(encoding="utf-8")
ACTION = yaml.safe_load(ACTION_PATH.read_text(encoding="utf-8"))
CODE_BLOCKS = re.findall(r"```(\w+)\n(.*?)```", README, flags=re.DOTALL)
ACTION_USES = "durandtibo/extract-pyproject-metadata-action@v1"


def _fixture_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in FIXTURES)


@pytest.mark.parametrize(
    "block", [code for language, code in CODE_BLOCKS if language in {"yaml", "toml"}]
)
def test_every_yaml_and_toml_block_is_a_fixture(block: str) -> None:
    assert block in _fixture_text()


def test_the_readme_has_the_examples() -> None:
    languages = [language for language, _ in CODE_BLOCKS]

    assert languages.count("yaml") == len(EXAMPLES)
    assert languages.count("toml") == 1


def _steps(document: object) -> list[dict[str, object]]:
    """Return the steps of an example: a list of steps, or the steps of the jobs."""
    if isinstance(document, list):
        return document
    return [step for job in document["jobs"].values() for step in job.get("steps", [])]


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda path: path.name)
def test_the_examples_only_use_inputs_and_outputs_of_the_action(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    uses = [step for step in _steps(yaml.safe_load(text)) if step.get("uses") == ACTION_USES]

    assert uses
    for step in uses:
        assert set(step.get("with", {})) <= set(ACTION["inputs"])
    assert set(re.findall(r"steps\.\w+\.outputs\.([a-z-]+)", text)) <= set(ACTION["outputs"])
    assert set(re.findall(r"fromJSON\([^)]*\.json\)\.(\w+)", text)) <= set(Report.__annotations__)


def test_the_json_example_is_a_part_of_the_golden_file() -> None:
    (block,) = [code for language, code in CODE_BLOCKS if language == "json"]
    expected = json.loads(
        (ROOT_PATH / "test-data" / "readme-example" / "expected.json").read_text(encoding="utf-8")
    )

    shown = json.loads(block)

    assert shown == {key: expected[key] for key in shown}
    assert len(shown) >= 8


def test_the_toml_example_is_the_input_of_the_golden_case() -> None:
    (block,) = [code for language, code in CODE_BLOCKS if language == "toml"]
    fixture = ROOT_PATH / "test-data" / "readme-example" / "pyproject.toml"

    assert block == fixture.read_text(encoding="utf-8")


def test_the_generated_blocks_are_up_to_date() -> None:
    assert generate_docs.generate(README, ACTION) == README


def test_the_readme_does_not_tell_the_history() -> None:
    assert "used to" not in README
    assert "@v0" not in README
    assert "later than" not in README


def test_generate_docs_check_fails_when_the_readme_is_out_of_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(README.replace("`strict`", "`stale`", 1), encoding="utf-8")
    monkeypatch.setattr(generate_docs, "README_PATH", readme)
    monkeypatch.setattr(sys, "argv", ["generate_docs.py"])

    assert generate_docs.main(["--check"]) == 1

    assert "out of date" in capsys.readouterr().out
    assert generate_docs.main([]) == 0
    assert generate_docs.main(["--check"]) == 0


def test_generate_docs_requires_the_markers() -> None:
    with pytest.raises(SystemExit, match="has no <!-- inputs:start -->"):
        generate_docs.replace_block("no markers", "inputs", "x")


def test_a_pipe_in_a_description_is_escaped_in_the_table() -> None:
    action = {"inputs": {"a": {"description": "x | y", "default": ""}}}

    assert "x \\| y" in generate_docs.render_inputs(action)
