"""End-to-end tests of the size and depth of a ``pyproject.toml``.

A pathological file must give an error or a result in a bounded time, never a Python traceback
or a run that never ends.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "extract_metadata.py"
HEADER = '[project]\nname = "a"\nversion = "1"\n'


def run_script(tmp_path: Path, content: str, dependencies: str = "[]") -> subprocess.CompletedProcess[str]:
    """Write ``content`` to a pyproject.toml and run the script on it, with a time limit."""
    path = tmp_path / "pyproject.toml"
    path.write_text(content, encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT_PATH), str(path), "[]", dependencies],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def groups_toml(groups: dict[str, list[str]]) -> str:
    """Write ``groups`` as ``[dependency-groups]``; an item ``@x`` is ``{include-group = "x"}``."""
    lines = [HEADER, "[dependency-groups]"]
    for name, entries in groups.items():
        items = [
            f'{{include-group = "{entry[1:]}"}}' if entry.startswith("@") else json.dumps(entry)
            for entry in entries
        ]
        lines.append(f"{name} = [{', '.join(items)}]")
    return "\n".join(lines) + "\n"


def test_a_10_mb_file_is_parsed(tmp_path: Path) -> None:
    result = run_script(tmp_path, HEADER + f'description = "{"x" * 10_000_000}"\n')

    assert result.returncode == 0
    assert len(json.loads(result.stdout)["description"]) == 10_000_000


def test_50000_dependencies_are_looked_up(tmp_path: Path) -> None:
    dependencies = ", ".join(f'"pkg{i}>=1"' for i in range(50_000))
    names = json.dumps([f"pkg{i}" for i in range(0, 50_000, 1_000)])

    result = run_script(tmp_path, HEADER + f"dependencies = [{dependencies}]\n", names)

    assert result.returncode == 0
    assert len(json.loads(result.stdout)["dependency_specifiers"]) == 50


def test_5000_groups_are_listed(tmp_path: Path) -> None:
    content = groups_toml({f"g{i}": ["numpy>=1"] for i in range(5_000)})

    result = run_script(tmp_path, content)

    assert result.returncode == 0
    assert len(json.loads(result.stdout)["groups"]) == 5_000


def test_a_chain_of_groups_within_the_limit_is_expanded(tmp_path: Path) -> None:
    groups = {f"g{i}": [f"@g{i + 1}"] for i in range(99)} | {"g99": ["numpy>=1"]}

    result = run_script(tmp_path, groups_toml(groups), '["numpy@group:g0"]')

    assert result.returncode == 0
    assert json.loads(result.stdout)["dependency_specifiers"] == {"numpy@group:g0": ">=1"}


def test_a_chain_of_3000_groups_fails_without_a_traceback(tmp_path: Path) -> None:
    groups = {f"g{i}": [f"@g{i + 1}"] for i in range(2_999)} | {"g2999": ["numpy>=1"]}

    result = run_script(tmp_path, groups_toml(groups), '["numpy"]')

    assert result.returncode == 1
    assert result.stdout == ""
    assert "nested more than 100 levels deep" in result.stderr
    assert "Traceback" not in result.stderr


def test_a_diamond_of_25_levels_fails_quickly(tmp_path: Path) -> None:
    groups = {f"g{i}": [f"@g{i + 1}", f"@g{i + 1}"] for i in range(25)} | {"g25": ["numpy>=1"]}

    result = run_script(tmp_path, groups_toml(groups), '["numpy"]')

    assert result.returncode == 1
    assert result.stdout == ""
    assert "expand more than 10000 groups in total" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("depth", [100, 5_000])
def test_deeply_nested_arrays_do_not_end_with_a_traceback(tmp_path: Path, depth: int) -> None:
    result = run_script(tmp_path, HEADER + "x = " + "[" * depth + "]" * depth + "\n")

    assert "Traceback" not in result.stderr
    assert result.returncode in {0, 1}
    if result.returncode == 1:
        assert "nested too deeply" in result.stderr
