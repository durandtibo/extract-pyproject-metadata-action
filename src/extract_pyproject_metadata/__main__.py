"""Run the command line interface with ``python -m
extract_pyproject_metadata``."""

from __future__ import annotations

import sys

from extract_pyproject_metadata.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["extract_metadata.py", *sys.argv[1:]]))
