"""Compare the ``json`` output of the action with a golden file.

Usage: compare_json.py EXPECTED_FILE ACTUAL_JSON

``EXPECTED_FILE`` is the path of the golden file, ``ACTUAL_JSON`` is the
JSON text itself (the value of the output, passed through ``env:`` by
the workflow). Exits with 0 when they are equal, otherwise prints a
diff and exits with 1.
"""

from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path


def format_json(value: object) -> list[str]:
    """Return the lines of a stable, readable form of a JSON value."""
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).splitlines()


def main(argv: list[str]) -> int:
    """Compare the golden file and the actual JSON; return the exit code."""
    if len(argv) != 3:
        print("usage: compare_json.py EXPECTED_FILE ACTUAL_JSON", file=sys.stderr)
        return 2
    expected = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    try:
        actual = json.loads(argv[2])
    except json.JSONDecodeError as exc:
        print(f"::error::the actual output is not valid JSON: {exc}", file=sys.stderr)
        return 1
    if actual == expected:
        print(f"✅ {argv[1]}")
        return 0
    diff = difflib.unified_diff(
        format_json(expected), format_json(actual), "expected", "actual", lineterm=""
    )
    print("\n".join(diff), file=sys.stderr)
    print(f"::error::the output differs from {argv[1]}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
