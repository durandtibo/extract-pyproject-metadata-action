"""Tests of ``extract_pyproject_metadata.report``."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.report import build_report
from tests.helpers import (
    DEPS_TOML,
    parse_inputs_args,
    write_pyproject,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_build_report(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)

    report = build_report(parse_inputs_args(str(path), '[""]', '["dup", "missing"]'))

    assert report == {
        "name": "p",
        "normalized_name": "p",
        "file_name": "p",
        "version": "1",
        "normalized_version": "1",
        "requires_python": "",
        "extras": ["", "a"],
        "groups": ["base", "dev", "other"],
        "python_versions": ["3.11", "3.12", "3.13", "3.14", "3.15"],
        "python_min": "3.11",
        "python_max": "3.15",
        "dependency_specifiers": {"dup": ">=1", "missing": None},
        "dependency_requirements": {
            "dup": [
                {"specifier": ">=1", "marker": "", "source": "extra:a"},
                {"specifier": ">=2", "marker": "", "source": "group:other"},
            ],
            "missing": [],
        },
        "warnings": [{"code": "dependency-not-found", "message": "dependency 'missing' not found"}],
        "schema_version": 1,
    }


@pytest.mark.parametrize(
    ("candidates", "requires_python", "versions", "python_min", "python_max"),
    [
        ('["3.12","3.9","3.10","3.12"]', "", ["3.9", "3.10", "3.12"], "3.9", "3.12"),
        ('["3.12","3.9","3.10"]', ">=3.10", ["3.10", "3.12"], "3.10", "3.12"),
        ('["3.11"]', ">=3.11", ["3.11"], "3.11", "3.11"),
        ('["3.11"]', ">=4", [], "", ""),
        ("[]", "", [], "", ""),
    ],
)
def test_build_report_python_min_and_max_are_the_ends_of_the_sorted_python_versions(
    tmp_path: Path,
    candidates: str,
    requires_python: str,
    versions: list[str],
    python_min: str,
    python_max: str,
) -> None:
    requires = f'requires-python = "{requires_python}"\n' if requires_python else ""
    path = write_pyproject(tmp_path, f'[project]\nname = "a"\nversion = "1"\n{requires}')

    report = build_report(parse_inputs_args("--python-candidates", candidates, str(path), "[]"))

    assert report["python_versions"] == versions
    assert report["python_min"] == python_min
    assert report["python_max"] == python_max


@pytest.mark.parametrize(
    ("argv", "match"),
    [
        (["--strict", "maybe", "{path}", "[]"], r"strict: must be 'true' or 'false'"),
        (
            ["--python-candidates", "[3]", "{path}", "[]"],
            r"python-candidates: must be a JSON array of strings",
        ),
        (["--strict", "true", "{path}", "[]", '["missing"]'], r"dependency 'missing' not found"),
        (["{path}", "nope"], r"extra-values: not valid JSON"),
        (["{path}", "[]", "nope"], r"dependencies: not valid JSON"),
        (["missing.toml", "[]"], r"pyproject-path: not a file"),
    ],
)
def test_build_report_errors(tmp_path: Path, argv: list[str], match: str) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    argv = [arg.replace("{path}", str(path)) for arg in argv]

    with pytest.raises(MetadataError, match=match):
        build_report(parse_inputs_args(*argv))


def test_build_report_strict_fails_on_warnings(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)

    with pytest.raises(
        MetadataError,
        match=r"^strict: true and there are 1 warning\(s\):\n- dependency-not-found: dependency 'missing' not found$",
    ):
        build_report(parse_inputs_args("--strict", "true", str(path), "[]", '["missing"]'))


def test_build_report_strict_lists_every_warning(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "a"\nversion = "1"\nrequires-python = "nope"\n'
        'dependencies = ["bad requirement!!"]\n',
    )

    with pytest.raises(MetadataError) as excinfo:
        build_report(parse_inputs_args("--strict", "true", str(path), "[]", '["x"]'))

    lines = str(excinfo.value).splitlines()
    assert lines[0] == "strict: true and there are 3 warning(s):"
    assert len([line for line in lines if line.startswith("- ")]) == 3


def test_build_report_strict_without_warnings(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    report = build_report(parse_inputs_args("--strict", "true", str(path), "[]"))

    assert report["warnings"] == []


def test_build_report_not_strict_keeps_the_warnings(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)

    report = build_report(parse_inputs_args("--strict", "false", str(path), "[]", '["missing"]'))

    assert len(report["warnings"]) == 1
