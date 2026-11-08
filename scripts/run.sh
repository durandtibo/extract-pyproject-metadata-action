#!/usr/bin/env bash
# Run scripts/extract_metadata.py with a Python that has its requirements.
#
# Usage: run.sh <arguments of extract_metadata.py>...
#
# The script needs Python 3.11 or later (for tomllib) and "packaging"
# (scripts/requirements.txt). If "packaging" is missing from the python3 on
# PATH, it is installed in a private virtual environment instead of
# pip-installing into the caller's Python: that would modify the caller's
# environment and fails on "externally managed" Pythons (PEP 668).
# --system-site-packages reuses whatever is already there.
#
# The venv is created in a new directory on every run, so a stale or broken one
# left by an earlier run is never reused. It is removed when the script ends
# (self-hosted runners keep $RUNNER_TEMP between jobs), whether it succeeds or
# not.
#
# On failure, the pip output (for example a network error) is shown before the error.
#
# The exit code is the one of extract_metadata.py, or 1 on a Windows runner, if
# the python3 on PATH is older than 3.11 or if the requirements cannot be
# installed.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Only Linux and macOS are supported (a venv has Scripts/ instead of bin/ on Windows).
if [ "${RUNNER_OS:-}" = "Windows" ]; then
	echo "::error::This action does not support Windows runners. Use a Linux or macOS runner." >&2
	exit 1
fi

if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
	echo "::error::This action requires Python 3.11 or later, but the python3 on PATH is older or missing. Set up Python 3.11 or later (e.g. with actions/setup-python) before using this action." >&2
	exit 1
fi

venv=""
cleanup() {
	if [ -n "$venv" ]; then
		rm -rf "$venv"
	fi
}
trap cleanup EXIT

python=python3
if ! python3 -c 'import packaging' 2>/dev/null; then
	if venv="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/extract-pyproject-metadata-venv.XXXXXX")" &&
		python3 -m venv --system-site-packages "$venv"; then
		python="$venv/bin/python"
		"$python" -m pip install --quiet --disable-pip-version-check \
			-r "$script_dir/requirements.txt" || python=""
	else
		python=""
	fi
	if [ -z "$python" ]; then
		echo "::error::Could not install the 'packaging' Python package (the install needs access to a package index). Check the network and the pip configuration, or install it in the Python on PATH (e.g. 'pip install packaging') before using this action." >&2
		exit 1
	fi
fi

"$python" "$script_dir/extract_metadata.py" "$@"
