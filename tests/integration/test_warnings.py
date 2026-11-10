"""Tests that the README lists every warning, and that each one is
produced (and fails the step with ``strict``)."""

import re
from pathlib import Path
from typing import NamedTuple

import pytest

from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.report import build_report
from extract_pyproject_metadata.types import Report
from tests.helpers import README_PATH, parse_inputs_args, write_pyproject

PROJECT = '[project]\nname = "a"\n'


class Case(NamedTuple):
    """A pyproject.toml that gives a warning that contains
    ``message``."""

    message: str
    toml: str
    dependencies: str = "[]"


CASES = [
    Case(
        "is set and also listed in [project].dynamic",
        PROJECT + 'version = "1"\ndynamic = ["version"]\n',
    ),
    Case(
        "[project].version is dynamic, the version output is empty",
        PROJECT + 'dynamic = ["version"]\n',
    ),
    Case(
        "[project].requires-python is not a valid version specifier",
        PROJECT + 'version = "1"\nrequires-python = "3"\n',
    ),
    Case(
        "no python-candidates version satisfies",
        PROJECT + 'version = "1"\nrequires-python = ">=4"\n',
    ),
    Case(
        "Ignoring invalid requirement",
        PROJECT + 'version = "1"\ndependencies = ["numpy>="]\n',
        '["numpy"]',
    ),
    Case(
        "has an include-group cycle",
        PROJECT
        + 'version = "1"\n[dependency-groups]\na = [{include-group = "b"}]\n'
        + 'b = [{include-group = "a"}]\n',
        '["numpy"]',
    ),
    Case(
        "does not match any group",
        PROJECT + 'version = "1"\n[dependency-groups]\na = [{include-group = "zz"}]\n',
        '["numpy"]',
    ),
    Case(
        "[project].dependencies is dynamic, it cannot be read",
        PROJECT + 'version = "1"\ndynamic = ["dependencies"]\n',
        '["numpy"]',
    ),
    Case(
        "[project].optional-dependencies is dynamic, it cannot be read",
        PROJECT + 'version = "1"\ndynamic = ["optional-dependencies"]\n',
        '["numpy"]',
    ),
    Case(
        "' not found",
        PROJECT + 'version = "1"\ndependencies = ["pandas"]\n',
        '["numpy"]',
    ),
]


PARAMS = [pytest.param(case, id=case.message) for case in CASES]


def _readme_warnings() -> list[str]:
    """Return the messages of the table of the "Warnings" section of the
    README."""
    readme = README_PATH.read_text(encoding="utf-8")
    section = readme.split("\n## Warnings\n", 1)[1].split("\n## ", 1)[0]
    return re.findall(r"^\| `(.+?)` +\|", section, flags=re.MULTILINE)


def _own_warnings(report: Report, case: Case) -> list[str]:
    """Return the warnings of a case, without the "not found" ones of the dependencies that the
    case requests only to have the warnings of the dependency tables reported."""
    if case.message == "' not found":
        return report["warnings"]
    return [message for message in report["warnings"] if "' not found" not in message]


def _report(tmp_path: Path, case: Case, strict: bool) -> Report:
    path = write_pyproject(tmp_path, case.toml)
    options = ["--strict", "true"] if strict else []
    return build_report(parse_inputs_args(*options, str(path), "[]", case.dependencies))


@pytest.mark.parametrize("case", PARAMS)
def test_the_warning_is_produced(tmp_path: Path, case: Case) -> None:
    messages = _own_warnings(_report(tmp_path, case, strict=False), case)

    assert len(messages) == 1
    assert case.message in messages[0]


@pytest.mark.parametrize("case", PARAMS)
def test_the_warning_fails_the_step_with_strict(tmp_path: Path, case: Case) -> None:
    count = len(_report(tmp_path, case, strict=False)["warnings"])

    with pytest.raises(
        MetadataError, match=rf"strict: true and there are {count} warning\(s\):\n- "
    ):
        _report(tmp_path, case, strict=True)


def test_the_readme_lists_every_warning_in_order() -> None:
    assert _readme_warnings() == [case.message for case in CASES]
