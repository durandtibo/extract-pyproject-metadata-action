"""Tests that every warning code is documented, produced and fails the step
with ``strict``."""

import re
from pathlib import Path
from typing import NamedTuple, get_args

import pytest

from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.report import build_report
from extract_pyproject_metadata.types import Report, WarningCode
from extract_pyproject_metadata.warning_codes import WARNING_CODES
from tests.helpers import README_PATH, parse_inputs_args, write_pyproject

PROJECT = '[project]\nname = "a"\n'


class Case(NamedTuple):
    """A pyproject.toml that gives a warning with the ``code``."""

    code: str
    toml: str
    dependencies: str = "[]"


CASES = [
    Case("static-and-dynamic", PROJECT + 'version = "1"\ndynamic = ["version"]\n'),
    Case("dynamic-version", PROJECT + 'dynamic = ["version"]\n'),
    Case("invalid-requires-python", PROJECT + 'version = "1"\nrequires-python = "3"\n'),
    Case("no-python-version", PROJECT + 'version = "1"\nrequires-python = ">=4"\n'),
    Case(
        "invalid-requirement",
        PROJECT + 'version = "1"\ndependencies = ["numpy>="]\n',
        '["numpy"]',
    ),
    Case(
        "include-group-cycle",
        PROJECT
        + 'version = "1"\n[dependency-groups]\na = [{include-group = "b"}]\n'
        + 'b = [{include-group = "a"}]\n',
        '["numpy"]',
    ),
    Case(
        "unknown-include-group",
        PROJECT + 'version = "1"\n[dependency-groups]\na = [{include-group = "zz"}]\n',
        '["numpy"]',
    ),
    Case(
        "dynamic-dependencies",
        PROJECT + 'version = "1"\ndynamic = ["dependencies"]\n',
        '["numpy"]',
    ),
    Case(
        "dependency-not-found",
        PROJECT + 'version = "1"\ndependencies = ["pandas"]\n',
        '["numpy"]',
    ),
]


PARAMS = [pytest.param(case, id=case.code) for case in CASES]


def _readme_codes() -> list[str]:
    """Return the codes of the table of the "Warnings" section of the README."""
    readme = README_PATH.read_text(encoding="utf-8")
    section = readme.split("\n## Warnings\n", 1)[1].split("\n## ", 1)[0]
    return re.findall(r"^\| `(.+?)` +\|", section, flags=re.MULTILINE)


def _own_codes(report: Report, case: Case) -> list[str]:
    """Return the codes of the warnings of a case, without the "not found" ones of the
    dependencies that the case requests only to have the warnings of the tables reported."""
    codes = [warning["code"] for warning in report["warnings"]]
    if case.code == "dependency-not-found":
        return codes
    return [code for code in codes if code != "dependency-not-found"]


def _report(tmp_path: Path, case: Case, strict: bool) -> Report:
    path = write_pyproject(tmp_path, case.toml)
    options = ["--strict", "true"] if strict else []
    return build_report(parse_inputs_args(*options, str(path), "[]", case.dependencies))


@pytest.mark.parametrize("case", PARAMS)
def test_the_warning_is_produced_with_its_code(tmp_path: Path, case: Case) -> None:
    report = _report(tmp_path, case, strict=False)

    assert _own_codes(report, case) == [case.code]


@pytest.mark.parametrize("case", PARAMS)
def test_the_warning_fails_the_step_with_strict(tmp_path: Path, case: Case) -> None:
    count = len(_report(tmp_path, case, strict=False)["warnings"])

    with pytest.raises(
        MetadataError,
        match=rf"strict: true and there are {count} warning\(s\):\n- [a-z-]+: ",
    ):
        _report(tmp_path, case, strict=True)


def test_every_code_is_documented_once() -> None:
    assert list(WARNING_CODES) == list(get_args(WarningCode))


def test_every_code_has_a_case() -> None:
    assert [case.code for case in CASES] == list(WARNING_CODES)


def test_the_readme_lists_every_code_in_order() -> None:
    assert _readme_codes() == list(WARNING_CODES)
