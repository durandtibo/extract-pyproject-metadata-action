"""Tests of the workflows and of the scripts that they run."""

from __future__ import annotations

import importlib.util
import re
import sys
from typing import TYPE_CHECKING

import pytest

from extract_pyproject_metadata.inputs import DEFAULT_INPUTS
from tests.helpers import ROOT_PATH

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

WORKFLOWS_PATH = ROOT_PATH / ".github" / "workflows"
ACTION_PATH = ROOT_PATH / "action.yaml"
LOCAL_PATH = WORKFLOWS_PATH / "ci-test-local.yaml"


def load_script(name: str) -> ModuleType:
    """Import a module of ``scripts/`` (it is not a package)."""
    spec = importlib.util.spec_from_file_location(name, ROOT_PATH / "scripts" / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


generate_workflows = load_script("generate_workflows")
compare_json = load_script("compare_json")

WORKFLOWS = sorted(WORKFLOWS_PATH.glob("*.yaml"))


def _run_blocks(text: str) -> list[tuple[int, str]]:
    """Return the (line number, line) of the lines inside a ``run:`` block."""
    lines: list[tuple[int, str]] = []
    block_indent: int | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        indent = len(line) - len(line.lstrip())
        if block_indent is not None:
            if line.strip() and indent <= block_indent:
                block_indent = None
            else:
                lines.append((number, line))
                continue
        stripped = line.strip().removeprefix("- ")
        if stripped.startswith("run:"):
            block_indent = indent
            rest = stripped.removeprefix("run:").strip()
            if rest and rest not in {"|", ">", "|-", ">-"}:
                lines.append((number, rest))
    return lines


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_no_expression_is_interpolated_in_a_run_block(path: Path) -> None:
    offenders = [
        f"{path.name}:{number}: {line.strip()}"
        for number, line in _run_blocks(path.read_text(encoding="utf-8"))
        if "${{" in line
    ]

    assert offenders == []


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_a_reusable_workflow_that_is_called_exists(path: Path) -> None:
    called = re.findall(r"(?m)^\s*uses: \./\.github/workflows/([\w.-]+)$", path.read_text("utf-8"))

    assert [name for name in called if not (WORKFLOWS_PATH / name).exists()] == []


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_no_workflow_uses_concurrency(path: Path) -> None:
    assert not re.search(r"(?m)^\s*concurrency:", path.read_text(encoding="utf-8"))


def test_ci_runs_every_night_through_the_nightly_workflow_only() -> None:
    ci = (WORKFLOWS_PATH / "ci.yaml").read_text(encoding="utf-8")
    nightly = (WORKFLOWS_PATH / "nightly.yaml").read_text(encoding="utf-8")

    assert "schedule:" not in ci
    assert "schedule:" in nightly
    assert "uses: ./.github/workflows/ci.yaml" in nightly
    assert "uses: ./.github/workflows/nightly-test-stable.yaml" in nightly


def test_the_shared_matrix_workflow_is_gone() -> None:
    assert not (WORKFLOWS_PATH / "lib-get-test-matrix.yaml").exists()


def test_the_local_workflow_repeats_the_defaults_of_the_inputs() -> None:
    action = ACTION_PATH.read_text(encoding="utf-8")
    local = LOCAL_PATH.read_text(encoding="utf-8")

    for name, default in DEFAULT_INPUTS.items():
        if name == "pyproject-path":
            continue
        # The action takes its own default for an empty python-candidates.
        shown = "" if name == "python-candidates" else default
        assert f"fromJSON(steps.case.outputs.inputs)['{name}'] || '{shown}'" in local
        assert re.search(rf"(?m)^  {re.escape(name)}:$", action)


def test_the_local_workflow_passes_every_input_of_the_action() -> None:
    action = ACTION_PATH.read_text(encoding="utf-8")
    inputs = action[action.index("\ninputs:") : action.index("\noutputs:")]
    names = re.findall(r"(?m)^  ([a-z-]+):$", inputs)
    golden = LOCAL_PATH.read_text(encoding="utf-8")
    golden = golden[golden.index("\n  golden:") : golden.index("\n  wiring:")]

    passed = re.findall(r"(?m)^          ([a-z-]+): \$\{\{", golden)
    assert sorted(passed) == sorted(names)
    assert sorted(DEFAULT_INPUTS) == sorted(names)


def test_the_stable_workflow_is_generated_from_the_local_one() -> None:
    generated = generate_workflows.generate(LOCAL_PATH.read_text(encoding="utf-8"))

    assert (WORKFLOWS_PATH / "nightly-test-stable.yaml").read_text(encoding="utf-8") == generated


def test_the_stable_workflow_uses_the_release_and_no_local_job() -> None:
    text = (WORKFLOWS_PATH / "nightly-test-stable.yaml").read_text(encoding="utf-8")

    assert "uses: ./" not in text
    assert "local-only" not in text.replace("`local-only`", "")
    assert f"uses: {generate_workflows.STABLE_REF}" in text


SOURCE = """name: Test Local Action
on:
  workflow_call:

jobs:
  # about stable
  stable:
    steps:
      - uses: ./
        # a step comment
  # about the other job
  other:
    # local-only
    steps:
      - uses: ./

  last:
    steps:
      - run: echo
"""


def test_generate_keeps_the_jobs_that_are_not_local_only() -> None:
    assert generate_workflows.generate(SOURCE) == (
        "# Generated by scripts/generate_workflows.py from ci-test-local.yaml: do not edit.\n"
        "# Run `make workflows` after changing ci-test-local.yaml.\n"
        "name: Test Stable Action\n"
        "on:\n"
        "  workflow_call:\n"
        "\n"
        "jobs:\n"
        "  # about stable\n"
        "  stable:\n"
        "    steps:\n"
        f"      - uses: {generate_workflows.STABLE_REF}\n"
        "        # a step comment\n"
        "  last:\n"
        "    steps:\n"
        "      - run: echo\n"
    )


def test_generate_workflows_check_fails_when_the_file_is_out_of_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "nightly.yaml"
    target.write_text("old\n", encoding="utf-8")
    monkeypatch.setattr(generate_workflows, "TARGET_PATH", target)

    assert generate_workflows.main(["--check"]) == 1

    assert "out of date" in capsys.readouterr().out


def test_generate_workflows_writes_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "nightly.yaml"
    monkeypatch.setattr(generate_workflows, "TARGET_PATH", target)

    assert generate_workflows.main([]) == 0

    assert generate_workflows.main(["--check"]) == 0
    assert target.read_text(encoding="utf-8").startswith("# Generated by")


def test_compare_json_accepts_equal_values(tmp_path: Path) -> None:
    expected = tmp_path / "expected.json"
    expected.write_text('{"b": [1, 2], "a": "é"}', encoding="utf-8")

    assert compare_json.main(["compare_json.py", str(expected), '{"a":"é","b":[1,2]}']) == 0


def test_compare_json_prints_the_difference(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    expected = tmp_path / "expected.json"
    expected.write_text('{"a": 1}', encoding="utf-8")

    assert compare_json.main(["compare_json.py", str(expected), '{"a": 2}']) == 1

    err = capsys.readouterr().err
    assert '-  "a": 1' in err
    assert '+  "a": 2' in err
    assert "::error::the output differs from" in err


def test_compare_json_rejects_invalid_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    expected = tmp_path / "expected.json"
    expected.write_text("{}", encoding="utf-8")

    assert compare_json.main(["compare_json.py", str(expected), "not json"]) == 1

    assert "::error::the actual output is not valid JSON" in capsys.readouterr().err


def test_compare_json_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert compare_json.main(["compare_json.py"]) == 2

    assert "usage: compare_json.py" in capsys.readouterr().err
