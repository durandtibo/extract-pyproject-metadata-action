"""Tests of ``extract_pyproject_metadata.report``."""

from __future__ import annotations

from pathlib import Path

import pytest

from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.report import build_report
from tests.helpers import (
    DEPS_TOML,
    parse_args,
    write_pyproject,
)


def test_build_report(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)

    report = build_report(parse_args(str(path), '[""]', '["dup", "missing"]'))

    assert report == {
        "name": "p",
        "normalized_name": "p",
        "version": "1",
        "normalized_version": "1",
        "description": "",
        "readme": "",
        "license": "",
        "license_files": [],
        "authors": [],
        "urls": {},
        "keywords": [],
        "classifiers": [],
        "scripts": {},
        "requires_python": "",
        "extras": ["", "a"],
        "groups": ["base", "dev", "other"],
        "build_backend": "",
        "build_requires": [],
        "python_versions": ["3.11", "3.12", "3.13", "3.14", "3.15"],
        "python_min": "3.11",
        "python_max": "3.15",
        "project_dependencies": {"Foo_Bar": "<2,>=1", "nospec": "", "withextra": ">=3"},
        "dependency_specifiers": {"dup": ">=1", "missing": None},
        "dependency_requirements": {
            "dup": [{"specifier": ">=1", "marker": ""}, {"specifier": ">=2", "marker": ""}],
            "missing": [],
        },
        "warnings": [f"dup has different specifiers in {path}: ['>=1', '>=2']; using '>=1'"],
        "schema_version": 1,
    }


@pytest.mark.parametrize(
    ("argv", "match"),
    [
        (["--fail-on-missing", "maybe", "{path}", "[]"], r"fail-on-missing must be 'true' or 'false'"),
        (["--fail-on-dynamic-version", "maybe", "{path}", "[]"], r"fail-on-dynamic-version must be"),
        (["--python-candidates", "[3]", "{path}", "[]"], r"python-candidates must be a JSON array of strings"),
        (["--fail-on-missing", "true", "{path}", "[]", '["missing"]'], r"dependencies not found"),
        (["{path}", "nope"], r"extra-values is not valid JSON"),
        (["{path}", "[]", "nope"], r"dependencies is not valid JSON"),
        (["missing.toml", "[]"], r"pyproject\.toml not found at: missing\.toml"),
    ],
)
def test_build_report_errors(tmp_path: Path, argv: list[str], match: str) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    argv = [arg.replace("{path}", str(path)) for arg in argv]

    with pytest.raises(MetadataError, match=match):
        build_report(parse_args(*argv))


def test_build_report_strict_fails_on_warnings(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)

    with pytest.raises(
        MetadataError,
        match=r"^strict is 'true' and there are 1 warning\(s\):\n- dup has different specifiers in ",
    ):
        build_report(parse_args("--strict", "true", str(path), "[]", '["dup"]'))


def test_build_report_strict_lists_every_warning(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "a"\nversion = "1"\nrequires-python = "nope"\n'
        'dependencies = ["bad requirement!!"]\n',
    )

    with pytest.raises(MetadataError) as excinfo:
        build_report(parse_args("--strict", "true", str(path), "[]"))

    lines = str(excinfo.value).splitlines()
    assert lines[0] == "strict is 'true' and there are 2 warning(s):"
    assert lines[1].startswith("- ")
    assert lines[2].startswith("- ")


def test_build_report_strict_without_warnings(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    report = build_report(parse_args("--strict", "true", str(path), "[]"))

    assert report["warnings"] == []


def test_build_report_not_strict_keeps_the_warnings(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)

    report = build_report(parse_args("--strict", "false", str(path), "[]", '["dup"]'))

    assert len(report["warnings"]) == 1
