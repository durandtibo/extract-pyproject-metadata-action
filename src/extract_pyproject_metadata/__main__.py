"""Run the command line interface with ``python -m
extract_pyproject_metadata``."""

from __future__ import annotations

from extract_pyproject_metadata.cli import run

if __name__ == "__main__":
    raise SystemExit(run())
