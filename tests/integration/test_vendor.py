"""Tests of the vendored ``packaging`` and of the script that vendors it."""

from __future__ import annotations

import ast
import io
import re
import zipfile
from typing import TYPE_CHECKING

import pytest

from extract_pyproject_metadata._vendor import packaging
from tests.helpers import PACKAGE_PATH, ROOT_PATH
from tests.integration.test_workflows import load_script

if TYPE_CHECKING:
    from pathlib import Path

vendor_packaging = load_script("vendor_packaging")

VENDOR_PATH = PACKAGE_PATH / "_vendor"
OWN_FILES = sorted(
    path
    for folder in (PACKAGE_PATH, ROOT_PATH / "scripts", ROOT_PATH / "tests")
    for path in folder.rglob("*.py")
    if "_vendor" not in path.relative_to(folder).parts
)


def test_the_readme_records_the_vendored_version_and_digest() -> None:
    readme = (VENDOR_PATH / "README.md").read_text(encoding="utf-8")

    assert f"`packaging` {packaging.__version__}," in readme
    assert re.search(r"SHA-256 `[0-9a-f]{64}`", readme)


def test_the_licenses_of_packaging_are_included() -> None:
    names = sorted(path.name for path in (VENDOR_PATH / "licenses").iterdir())

    assert names == ["LICENSE", "LICENSE.APACHE", "LICENSE.BSD"]


def test_the_vendored_packaging_is_typed() -> None:
    assert (VENDOR_PATH / "packaging" / "py.typed").exists()


@pytest.mark.parametrize("path", OWN_FILES, ids=lambda path: path.name)
def test_nothing_imports_the_installed_packaging(path: Path) -> None:
    imported = [
        name
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        for name in (
            [node.module or ""]
            if isinstance(node, ast.ImportFrom) and node.level == 0
            else [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else []
        )
        if name.split(".")[0] == "packaging"
    ]

    assert imported == []


def _wheel(files: dict[str, str]) -> bytes:
    """Build a wheel (a zip file) in memory."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_unpack_replaces_the_vendored_copy(tmp_path: Path) -> None:
    destination = tmp_path / "_vendor"
    (destination / "packaging").mkdir(parents=True)
    (destination / "packaging" / "stale.py").write_text("old", encoding="utf-8")
    wheel = _wheel(
        {
            "packaging/__init__.py": "__version__ = '1'",
            "packaging/sub/mod.py": "x = 1",
            "packaging-1.dist-info/METADATA": "ignored",
            "packaging-1.dist-info/licenses/LICENSE": "license",
        }
    )

    vendor_packaging.unpack(wheel, destination)

    assert sorted(
        str(path.relative_to(destination)) for path in destination.rglob("*") if path.is_file()
    ) == ["licenses/LICENSE", "packaging/__init__.py", "packaging/sub/mod.py"]


def test_main_requires_a_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert vendor_packaging.main(["vendor_packaging.py"]) == 2

    assert "usage: vendor_packaging.py VERSION" in capsys.readouterr().err
