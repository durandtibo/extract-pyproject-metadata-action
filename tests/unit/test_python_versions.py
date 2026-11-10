"""Tests of ``extract_pyproject_metadata.python_versions``."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from extract_pyproject_metadata._vendor.packaging.specifiers import SpecifierSet
from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.python_versions import (
    compatible_python_versions,
    highest_python_version,
    lowest_python_version,
)
from tests.helpers import CANDIDATES, extract, write_pyproject

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    "requires_python", [">=3.10", ">=3.10,<4", "~=3.9", "==3.*", ">= 3.10", ""]
)
def test_extract_metadata_requires_python(tmp_path: Path, requires_python: str) -> None:
    path = write_pyproject(
        tmp_path,
        f'[project]\nname = "p"\nversion = "1"\nrequires-python = "{requires_python}"\n',
    )

    assert extract(path)["requires_python"] == requires_python


def test_extract_metadata_requires_python_defaults_to_empty(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "p"\nversion = "1"\n')

    assert extract(path)["requires_python"] == ""


def test_extract_metadata_requires_python_dynamic_is_empty(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "p"\nversion = "1"\ndynamic = ["requires-python"]\n'
    )

    assert extract(path)["requires_python"] == ""


@pytest.mark.parametrize("value", ["3.10", "[]", '[">=3.10"]', "true", "{a = 1}"])
def test_extract_metadata_requires_python_must_be_a_string(tmp_path: Path, value: str) -> None:
    path = write_pyproject(
        tmp_path, f'[project]\nname = "p"\nversion = "1"\nrequires-python = {value}\n'
    )

    with pytest.raises(
        MetadataError, match=r"\[project\]\.requires-python: must be a string, got: "
    ):
        extract(path)


@pytest.mark.parametrize(
    ("requires_python", "expected"),
    [
        ("", CANDIDATES),
        ("   ", CANDIDATES),
        (">=3.10", ["3.10", "3.11", "3.12", "3.13"]),
        (">=3.10,<4", ["3.10", "3.11", "3.12", "3.13"]),
        (">=3.10, <3.13", ["3.10", "3.11", "3.12"]),
        (">3.10", ["3.10", "3.11", "3.12", "3.13"]),
        (">=3.10.2", ["3.10", "3.11", "3.12", "3.13"]),
        ("<3.12.5", ["3.9", "3.10", "3.11", "3.12"]),
        ("<3.11", ["3.9", "3.10"]),
        ("~=3.10", ["3.10", "3.11", "3.12", "3.13"]),
        ("~=3.11.0", ["3.11"]),
        ("==3.11.*", ["3.11"]),
        ("!=3.12.*", ["3.9", "3.10", "3.11", "3.13"]),
        (">=3", CANDIDATES),
        ("==3.12.3", ["3.12"]),
        ("===3.12.3", ["3.12"]),
        ("==3.12.3,!=3.12.0", ["3.12"]),
        ("~=3.12.3", ["3.12"]),
        (">3.12.5,<3.12.7", ["3.12"]),
        (">=3.11.4,<=3.11.4", ["3.11"]),
        ("==3.12.*,!=3.12.3", ["3.12"]),
        ("==3.12.99", ["3.12"]),
        (">=3.12.150", ["3.12", "3.13"]),
        ("<3.12.150", ["3.9", "3.10", "3.11", "3.12"]),
    ],
)
def test_compatible_python_versions(requires_python: str, expected: list[str]) -> None:
    assert compatible_python_versions(requires_python, CANDIDATES) == (expected, [])


@pytest.mark.parametrize(
    "requires_python",
    [">=3.14", ">3.12.5,<3.12.6", "<3.9.0", "==3.12.150", ">=3.12.5,<3.12.7,!=3.12.5,!=3.12.6"],
)
def test_compatible_python_versions_none_allowed_warns(requires_python: str) -> None:
    assert compatible_python_versions(requires_python, CANDIDATES) == (
        [],
        [
            (
                "no python-candidates version satisfies [project].requires-python "
                f"({requires_python!r}): python-versions is empty, and a job "
                "matrix built from it is rejected by GitHub"
            )
        ],
    )


def test_compatible_python_versions_none_allowed_warning_message() -> None:
    _, warnings = compatible_python_versions(">=4", CANDIDATES)

    assert warnings[0].startswith("no python-candidates version")


def test_compatible_python_versions_keeps_the_order_of_the_candidates() -> None:
    assert compatible_python_versions(">=3.10", ["3.12", "3.10", "3.8"]) == (["3.12", "3.10"], [])


def test_compatible_python_versions_no_candidates_does_not_warn() -> None:
    assert compatible_python_versions(">=3.10", []) == ([], [])


@pytest.mark.parametrize("requires_python", ["python3", ">=", "3.10 or later"])
def test_compatible_python_versions_invalid_specifier_warns(requires_python: str) -> None:
    versions, warnings = compatible_python_versions(requires_python, CANDIDATES)

    assert versions == []
    assert len(warnings) == 1
    assert warnings[0].startswith(
        "[project].requires-python is not a valid version specifier, "
        "the python-versions output is empty: "
    )


@pytest.mark.parametrize(
    "requires_python",
    [
        ">=3.12.0,<3.12.1",
        "!=3.12.*",
        ">=3.11,!=3.12.*",
        "!=3.12.0,!=3.12.1",
        "!=3.12.0,!=3.12.1,!=3.12.2,<3.12.3",
        ">3.12.5,!=3.12.6,<3.12.8",
        ">3.12.5,!=3.12.6,!=3.12.7,<3.12.9",
        ">=3.12.9999",
        "<3.12.0",
        "<=3.12.0",
        "~=3.12.3",
        "===3.12.1",
        "==3.12.*,!=3.12.0",
        ">=3.10.2,<3.12.5",
    ],
)
def test_compatible_python_versions_match_a_brute_force_search(requires_python: str) -> None:
    candidates = ["3.10", "3.11", "3.12", "3.13"]
    specifier = SpecifierSet(requires_python)
    patches = [*range(100), 9999]
    expected = [
        candidate
        for candidate in candidates
        if any(specifier.contains(f"{candidate}.{patch}") for patch in patches)
    ]

    versions, warnings = compatible_python_versions(requires_python, candidates)

    assert versions == expected
    assert warnings == []


@pytest.mark.parametrize(
    ("versions", "expected"),
    [
        ([], ""),
        (["3.12"], "3.12"),
        (["3.11", "3.12", "3.13"], "3.11"),
        (["3.13", "3.11", "3.12"], "3.11"),
        (["3.10", "3.9"], "3.9"),
        (["3.10", "3.2", "2.7"], "2.7"),
        (("3.10", "3.9"), "3.9"),
    ],
)
def test_lowest_python_version(versions: list[str], expected: str) -> None:
    assert lowest_python_version(versions) == expected


@pytest.mark.parametrize(
    ("versions", "expected"),
    [
        ([], ""),
        (["3.12"], "3.12"),
        (["3.11", "3.12", "3.13"], "3.13"),
        (["3.13", "3.11", "3.12"], "3.13"),
        (["3.10", "3.9"], "3.10"),
        (["3.10", "3.2", "2.7"], "3.10"),
        (("3.9", "3.10"), "3.10"),
    ],
)
def test_highest_python_version(versions: list[str], expected: str) -> None:
    assert highest_python_version(versions) == expected
