"""Tests of the workflows and of the scripts that they run."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from typing import TYPE_CHECKING

import pytest
import yaml

from extract_pyproject_metadata.inputs import DEFAULT_INPUTS
from tests.helpers import PACKAGE_PATH, ROOT_PATH

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

WORKFLOWS_PATH = ROOT_PATH / ".github" / "workflows"
ACTION_PATH = ROOT_PATH / "action.yaml"
LOCAL_PATH = WORKFLOWS_PATH / "ci-test-local.yaml"
MAKEFILE_PATH = ROOT_PATH / "Makefile"


def load_script(name: str) -> ModuleType:
    """Import a module of ``scripts/`` (it is not a package)."""
    spec = importlib.util.spec_from_file_location(name, ROOT_PATH / "scripts" / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


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


def test_the_stable_workflow_tests_the_pinned_published_action_only() -> None:
    text = (WORKFLOWS_PATH / "nightly-test-stable.yaml").read_text(encoding="utf-8")

    assert re.search(
        r"uses: durandtibo/extract-pyproject-metadata-action@[0-9a-f]{40} # ratchet:\S+@v\d+\.\d+",
        text,
    )
    assert "uses: ./" not in text


def test_ci_only_calls_the_reusable_workflows() -> None:
    jobs = load_workflow("ci.yaml")["jobs"]

    assert all("uses" in job for job in jobs.values())
    assert sorted(job["uses"] for job in jobs.values()) == [
        "./.github/workflows/ci-lint.yaml",
        "./.github/workflows/ci-test-local.yaml",
        "./.github/workflows/ci-test.yaml",
        "./.github/workflows/ci-type-checking.yaml",
        "./.github/workflows/ci-verify-workflows.yaml",
        "./.github/workflows/lib-get-test-matrix.yaml",
    ]


def test_the_shared_matrix_workflow_reads_the_workflow_config_action() -> None:
    text = (WORKFLOWS_PATH / "lib-get-test-matrix.yaml").read_text(encoding="utf-8")

    assert "uses: durandtibo/workflow-config-action@" in text
    assert "python_versions_standard" in text
    assert "os_unix" in text


def test_the_maintenance_workflow_reads_the_default_candidates_where_they_are_defined() -> None:
    text = (WORKFLOWS_PATH / "maintenance.yaml").read_text(encoding="utf-8")
    module = (PACKAGE_PATH / "python_versions.py").read_text(encoding="utf-8")

    assert (
        "from extract_pyproject_metadata.python_versions import DEFAULT_PYTHON_CANDIDATES" in text
    )
    assert "DEFAULT_PYTHON_CANDIDATES = " in module
    assert not (WORKFLOWS_PATH / "packaging-update.yaml").exists()


def load_workflow(name: str) -> dict:
    """Parse a workflow of ``.github/workflows``."""
    return yaml.safe_load((WORKFLOWS_PATH / name).read_text(encoding="utf-8"))


def python_matrices(workflow: dict) -> list[list[str]]:
    """The ``python-version`` matrix of every job of a workflow that has one."""
    return [
        job["strategy"]["matrix"]["python-version"]
        for job in workflow["jobs"].values()
        if "python-version" in job.get("strategy", {}).get("matrix", {})
    ]


MATRIX_WORKFLOWS = ["ci-test.yaml", "ci-test-local.yaml", "nightly-test-stable.yaml"]


@pytest.mark.parametrize("name", MATRIX_WORKFLOWS)
def test_the_matrix_jobs_use_the_shared_matrix(name: str) -> None:
    matrices = [
        job["strategy"]["matrix"]
        for job in load_workflow(name)["jobs"].values()
        if "os" in job.get("strategy", {}).get("matrix", {})
    ]

    assert matrices
    for matrix in matrices:
        assert matrix["os"] == "${{ fromJson(inputs.test-matrix).os_matrix }}"
        assert (
            matrix["python-version"]
            == "${{ fromJson(inputs.test-matrix).python_versions_standard }}"
        )


@pytest.mark.parametrize(
    ("name", "caller"),
    [
        ("ci-test.yaml", "ci.yaml"),
        ("ci-test-local.yaml", "ci.yaml"),
        ("nightly-test-stable.yaml", "nightly.yaml"),
    ],
)
def test_the_callers_pass_the_shared_matrix(name: str, caller: str) -> None:
    jobs = load_workflow(caller)["jobs"]
    job = next(job for job in jobs.values() if job.get("uses", "").endswith(f"/{name}"))

    assert job["needs"] == "get-matrix"
    assert job["with"] == {"test-matrix": "${{ needs.get-matrix.outputs.test_matrix }}"}


def test_ci_runs_the_checks_through_make() -> None:
    commands = [
        step["run"]
        for name in ("ci-lint.yaml", "ci-test.yaml", "ci-type-checking.yaml")
        for job in load_workflow(name)["jobs"].values()
        for step in job.get("steps", [])
        if "run" in step
    ]

    for tool in ("pytest", "pyright", "ruff", "generate_docs"):
        assert not [command for command in commands if tool in command.replace("make ", "")]
    assert "make test PYTHON_RUN=" in commands
    assert "make lint-python PYTHON_RUN=" in commands
    assert "make docs-check PYTHON_RUN=" in commands
    assert 'make types "PYTHON_RUN=.venv/bin/python -m"' in commands


def test_the_docs_check_target_runs_the_generator_with_check() -> None:
    makefile = MAKEFILE_PATH.read_text(encoding="utf-8")

    assert re.search(r"^docs-check:.*\n\t.*generate_docs.py --check$", makefile, re.MULTILINE)


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


def golden_cases() -> list[str]:
    """Return the cases of the ``golden`` job of the local workflow."""
    return load_workflow("ci-test-local.yaml")["jobs"]["golden"]["strategy"]["matrix"]["case"]


def test_the_golden_job_lists_its_cases() -> None:
    assert golden_cases() == ["minimal", "readme-example", "python-candidates-none"]


def test_every_golden_case_of_the_workflow_exists() -> None:
    for case in golden_cases():
        assert (ROOT_PATH / "test-data" / case / "pyproject.toml").is_file()
        assert (ROOT_PATH / "test-data" / case / "expected.json").is_file()


def test_the_golden_cases_set_every_input_of_the_action() -> None:
    set_inputs = {"pyproject-path"}  # the workflow passes the path of every case
    for case in golden_cases():
        inputs_file = ROOT_PATH / "test-data" / case / "inputs.json"
        if inputs_file.is_file():
            set_inputs |= set(json.loads(inputs_file.read_text(encoding="utf-8")))

    assert set_inputs == set(DEFAULT_INPUTS)


def test_the_golden_cases_fill_every_output_of_the_action() -> None:
    filled: set[str] = set()
    for case in golden_cases():
        expected = json.loads(
            (ROOT_PATH / "test-data" / case / "expected.json").read_text(encoding="utf-8")
        )
        filled |= {f"{key.replace('_', '-')}" for key, value in expected.items() if value}
    outputs = set(yaml.safe_load(ACTION_PATH.read_text(encoding="utf-8"))["outputs"])

    assert outputs - {"json"} <= filled


def test_a_golden_case_has_a_warning() -> None:
    warnings = [
        json.loads((ROOT_PATH / "test-data" / case / "expected.json").read_text(encoding="utf-8"))[
            "warnings"
        ]
        for case in golden_cases()
    ]

    assert any(warnings)
