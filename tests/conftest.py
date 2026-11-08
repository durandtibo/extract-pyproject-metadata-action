"""Shared pytest configuration: the scripts directory is importable by the test modules."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import extract_metadata as extract_metadata_module


@pytest.fixture
def fixed_delimiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extract_metadata_module, "_new_delimiter", lambda: "DELIM")
