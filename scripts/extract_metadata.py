"""Start the command line interface of the
``extract_pyproject_metadata`` package.

This file is the entry point of ``scripts/run.sh``. The logic is in
``src/extract_pyproject_metadata``; see
``extract_pyproject_metadata/cli.py`` for the usage.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from extract_pyproject_metadata.cli import main

if __name__ == "__main__":
    # The log line has non-ASCII characters; a non-UTF-8 locale cannot encode them.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    raise SystemExit(main(os.environ, sys.argv[1:]))
