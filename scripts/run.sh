#!/usr/bin/env bash
# Run scripts/extract_metadata.py with the Python 3.11 or later found on PATH.
#
# Usage: run.sh (no argument: the inputs of the action are the variables INPUT_*)
#
# The interpreter is the first of "python3" and "python" that is Python 3.11 or later (a
# runner may only have one of them, and "python3" can be an older or a stub interpreter).
# Nothing is installed: the only dependency, "packaging", is vendored in the package.
#
# -I runs Python in isolated mode: the workspace of the caller, the user site and the
# PYTHON* variables are not on the module search path, so nothing there can shadow a module.
# -B does not write bytecode, so the action leaves no __pycache__ in the workspace of the
# caller (or in the action directory, which is often read-only or cached).
#
# The exit code is the one of extract_metadata.py, or 1 if no interpreter is usable.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for python in python3 python; do
	if command -v "$python" >/dev/null 2>&1 &&
		"$python" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
		exec "$python" -I -B "$script_dir/extract_metadata.py"
	fi
done

echo "::error::This action requires Python 3.11 or later, but neither 'python3' nor 'python' on PATH is Python 3.11 or later (or they are missing or cannot be run). Set up Python 3.11 or later (e.g. with actions/setup-python) before using this action." >&2
exit 1
