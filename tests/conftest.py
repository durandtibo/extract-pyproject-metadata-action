"""Shared pytest configuration: the scripts directory is importable by the test modules."""

from __future__ import annotations

import pytest

import extract_pyproject_metadata.cli as extract_metadata_module


@pytest.fixture
def fixed_delimiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extract_metadata_module, "_new_delimiter", lambda: "DELIM")
