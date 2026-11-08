"""Tests of the public names of the modules of
``extract_pyproject_metadata``."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

from tests.helpers import PACKAGE_PATH

MODULES = sorted(
    ".".join(["extract_pyproject_metadata", *path.relative_to(PACKAGE_PATH).with_suffix("").parts])
    for path in PACKAGE_PATH.rglob("*.py")
    if path.stem not in {"__init__", "__main__"}
)


def _public_names(path: Path) -> list[str]:
    """Return the public names that a module defines at its top
    level."""
    names: list[str] = []
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.FunctionDef | ast.ClassDef):
            names.append(node.name)
        elif isinstance(node, ast.Assign):
            names.extend(target.id for target in node.targets if isinstance(target, ast.Name))
    return sorted(name for name in names if not name.startswith("_"))


@pytest.mark.parametrize("module", MODULES)
def test_all_lists_the_public_names_of_the_module(module: str) -> None:
    path = PACKAGE_PATH.parent / Path(*module.split(".")).with_suffix(".py")

    assert importlib.import_module(module).__all__ == _public_names(path)


@pytest.mark.parametrize("module", ["extract_pyproject_metadata", *MODULES])
def test_all_names_can_be_imported(module: str) -> None:
    imported = importlib.import_module(module)

    assert all(hasattr(imported, name) for name in imported.__all__)


@pytest.mark.parametrize("module", MODULES)
def test_module_has_a_docstring(module: str) -> None:
    assert (importlib.import_module(module).__doc__ or "").strip()
