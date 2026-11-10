"""Run the command line interface with ``python -m
extract_pyproject_metadata``."""

from __future__ import annotations

import os
import sys

from extract_pyproject_metadata.cli import main

if __name__ == "__main__":
    raise SystemExit(main(os.environ, sys.argv[1:]))
