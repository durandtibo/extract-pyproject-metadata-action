"""Tests of the requirements files of the repository."""

from __future__ import annotations

from tests.helpers import REQUIREMENTS_PATH


def test_script_requirements_list_the_dependencies_of_the_script() -> None:
    requirements = REQUIREMENTS_PATH.read_text(encoding="utf-8")
    lines = [line for line in requirements.splitlines() if line and not line.startswith("#")]

    assert lines == ["packaging>=23.0,<27"]
