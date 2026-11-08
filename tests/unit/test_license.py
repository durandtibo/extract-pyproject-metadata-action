"""Tests of ``extract_pyproject_metadata.license``."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

import extract_pyproject_metadata.license as license_module
from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.license import license_warnings
from tests.helpers import extract, requires_licenses, write_pyproject

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("project", "expected"),
    [
        ("", []),
        ("license-files = []\n", []),
        ('license-files = ["LICENSE"]\n', ["LICENSE"]),
        (
            'license-files = ["LICENSE", "licenses/*.txt", "LICENSE"]\n',
            ["LICENSE", "licenses/*.txt", "LICENSE"],
        ),
        ('dynamic = ["license-files"]\n', []),
    ],
)
def test_extract_metadata_license_files(tmp_path: Path, project: str, expected: list[str]) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "a"\nversion = "1"\n{project}')

    assert extract(path)["license_files"] == expected


@pytest.mark.parametrize(
    ("value", "match"),
    [
        ('"LICENSE"', r"\[project\]\.license-files must be an array, got: 'LICENSE'"),
        (
            '{ glob = "LICENSE" }',
            r"\[project\]\.license-files must be an array, got: \{'glob': 'LICENSE'\}",
        ),
        ('["LICENSE", 1]', r"\[project\]\.license-files must contain only strings, got: 1"),
    ],
)
def test_extract_metadata_license_files_must_be_an_array_of_strings(
    tmp_path: Path, value: str, match: str
) -> None:
    path = write_pyproject(
        tmp_path, f'[project]\nname = "a"\nversion = "1"\nlicense-files = {value}\n'
    )

    with pytest.raises(MetadataError, match=match):
        extract(path)


@pytest.mark.parametrize(
    "license_",
    [
        "MIT",
        "Apache-2.0 OR MIT",
        "apache-2.0 or mit",
        "GPL-3.0-or-later WITH Classpath-exception-2.0",
        "LicenseRef-Foo",
        "",
    ],
)
def test_license_warnings_valid_expression(license_: str) -> None:
    assert license_warnings(license_, "p.toml") == []


@requires_licenses
@pytest.mark.parametrize("license_", ["MIT License", "MIT AND", "GPL v3", "(MIT"])
def test_license_warnings_invalid_expression(license_: str) -> None:
    warnings = license_warnings(license_, "p.toml")

    assert len(warnings) == 1
    assert warnings[0].startswith(
        "p.toml: [project].license is not a valid SPDX license expression (PEP 639): "
    )
    assert repr(license_) in warnings[0]


@pytest.mark.parametrize(
    "license_", [{"text": "MIT License"}, {"file": "LICENSE"}, 1, None, ["MIT"]]
)
def test_license_warnings_ignores_what_is_not_an_expression(license_: object) -> None:
    assert license_warnings(license_, "p.toml") == []


def test_license_warnings_cannot_check_with_an_old_packaging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(license_module, "canonicalize_license_expression", None)

    assert license_warnings("MIT License", "p.toml") == []


@pytest.mark.parametrize(
    ("license_", "expected"),
    [
        ('license = "MIT"', "MIT"),
        ('license = "Apache-2.0 OR MIT"', "Apache-2.0 OR MIT"),
        ('license = ""', ""),
        ('license = {text = "BSD-3-Clause"}', "BSD-3-Clause"),
        ('license = {text = "Line one\\nline two"}', "Line one\nline two"),
        ('license = {file = "LICENSE"}', ""),
        ('license = {file = "LICENSE", text = "MIT"}', "MIT"),
        ("license = {}", ""),
        ('dynamic = ["license"]', ""),
        ("", ""),
    ],
)
def test_extract_metadata_license(tmp_path: Path, license_: str, expected: str) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "a"\nversion = "1"\n{license_}\n')

    assert extract(path)["license"] == expected


@pytest.mark.parametrize(
    ("license_", "match"),
    [
        ("license = 1", r"\[project\]\.license must be a string or a table, got: 1"),
        ('license = ["MIT"]', r"\[project\]\.license must be a string or a table"),
        ("license = {text = 1}", r"\[project\]\.license\.text must be a string, got: 1"),
        ("license = {text = true}", r"\[project\]\.license\.text must be a string, got: True"),
        ("license = {file = 2}", r"\[project\]\.license\.file must be a string, got: 2"),
    ],
)
def test_extract_metadata_license_must_be_a_string_or_a_table(
    tmp_path: Path, license_: str, match: str
) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "a"\nversion = "1"\n{license_}\n')

    with pytest.raises(MetadataError, match=match):
        extract(path)
