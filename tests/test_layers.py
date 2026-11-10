"""Test that the modules of ``extract_pyproject_metadata`` import one way.

A module may only import from a module of a lower rank (see the
architecture in ``CLAUDE.md``), or from its own sub-package. ``output``
is further restricted to ``types`` and ``errors``.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

import pytest

from tests.helpers import PACKAGE_PATH

if TYPE_CHECKING:
    from pathlib import Path

PACKAGE = "extract_pyproject_metadata"

# The rank of each top-level module or sub-package: a higher rank may import a lower one.
RANKS = {
    "_vendor": 0,
    "types": 0,
    "errors": 0,
    "inputs": 1,
    "checks": 1,
    "pyproject": 2,
    "metadata": 3,
    "requirements": 4,
    "python_versions": 4,
    "output": 4,
    "report": 5,
    "cli": 6,
}

# The only modules that a sub-package may import from outside itself.
ALLOWED_IMPORTS = {"output": {"types", "errors"}}

# The vendored code is not ours, and has its own imports.
MODULES = sorted(
    path
    for path in PACKAGE_PATH.rglob("*.py")
    if path.stem not in {"__init__", "__main__"} and "_vendor" not in path.parts
)


def _top_level(path_parts: tuple[str, ...]) -> str:
    """Return the top-level module or sub-package of a path relative to the package."""
    return path_parts[0].removesuffix(".py")


def _imported_modules(path: Path) -> set[str]:
    """Return the top-level modules of the package that a file imports."""
    imported: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        names: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            names = [node.module]
            if node.module == PACKAGE:
                names = [f"{PACKAGE}.{alias.name}" for alias in node.names]
        elif isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        for name in names:
            parts = name.split(".")
            if parts[0] == PACKAGE and len(parts) > 1:
                imported.add(parts[1])
    return imported


def test_every_module_has_a_rank() -> None:
    tops = {_top_level(path.relative_to(PACKAGE_PATH).parts) for path in MODULES}

    assert tops == set(RANKS) - {"_vendor"}


@pytest.mark.parametrize("path", MODULES, ids=lambda path: str(path.relative_to(PACKAGE_PATH)))
def test_a_module_imports_only_from_lower_ranks(path: Path) -> None:
    top = _top_level(path.relative_to(PACKAGE_PATH).parts)

    imported = _imported_modules(path) - {top}

    too_high = sorted(name for name in imported if RANKS[name] >= RANKS[top])
    assert too_high == []
    if top in ALLOWED_IMPORTS:
        assert sorted(imported - ALLOWED_IMPORTS[top]) == []
