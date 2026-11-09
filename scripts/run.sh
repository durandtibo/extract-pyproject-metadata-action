#!/usr/bin/env bash
# Run scripts/extract_metadata.py with a Python that has its requirements.
#
# Usage: run.sh <arguments of extract_metadata.py>...
#
# The script needs Python 3.11 or later (for tomllib) and "packaging"
# (scripts/requirements.txt). The interpreter is the command or path in the
# PYTHON_EXECUTABLE environment variable (the python-executable input of the
# action), "python3" by default. If "packaging" is missing from it, or older than
# the lower bound of scripts/requirements.txt (the oldest version the unit tests
# were run with), it is installed in a private virtual environment instead of
# pip-installing into the caller's Python: that would modify the caller's
# environment and fails on "externally managed" Pythons (PEP 668). A newer
# version than the upper bound of the requirements is used as it is, so that a
# runner without network access keeps working.
# --system-site-packages reuses whatever is already there.
#
# The venv is created in a new directory on every run, so a stale or broken one
# left by an earlier run is never reused. It is removed when the script ends
# (self-hosted runners keep $RUNNER_TEMP between jobs), whether it succeeds or
# not.
#
# When it installs "packaging", it first says so in the log, with the requirements.
#
# On failure, the pip output (for example a network error) is shown before the error.
#
# Python does not write bytecode (__pycache__) while the script runs, so the
# action leaves nothing in the workspace of the caller (the action directory is
# usually read-only or cached, and a stray __pycache__ can end up in an artifact
# or a cache of the job).
#
# On a Windows runner (RUNNER_OS is "Windows") the script runs in the bash of Git
# for Windows, with the Python of the job. Its virtual environment has Scripts/python.exe
# instead of bin/python, and, when the default python3 is not there (setup-python only
# puts python on PATH), "python" is used.
#
# The exit code is the one of extract_metadata.py, or 1 if the interpreter is older than
# 3.11 or cannot be run or if the requirements cannot be installed.

set -euo pipefail

export PYTHONDONTWRITEBYTECODE=1

# The interpreter to use: a command found on PATH, or a path.
python_exe="${PYTHON_EXECUTABLE:-python3}"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The layout of a virtual environment, and the Python that Windows runners have.
if [ "${RUNNER_OS:-}" = "Windows" ]; then
	venv_python_path="Scripts/python.exe"
	# setup-python only puts "python" on PATH, and the python3 of the Microsoft Store
	# (a stub that does nothing) can come first: use "python" when python3 does not run.
	if [ "$python_exe" = "python3" ] && ! python3 -c 'import sys' >/dev/null 2>&1; then
		python_exe="python"
	fi
else
	venv_python_path="bin/python"
fi

if ! "$python_exe" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
	echo "::error::This action requires Python 3.11 or later, but '$python_exe' is older, missing or cannot be run. Set up Python 3.11 or later (e.g. with actions/setup-python), or set the python-executable input, before using this action." >&2
	exit 1
fi

venv=""
cleanup() {
	if [ -n "$venv" ]; then
		rm -rf "$venv"
	fi
}
trap cleanup EXIT

# Exit status 0 if "packaging" can be imported and satisfies the lower bound (">=") of the first
# requirement of the file in $1. The upper bound is not checked.
check_packaging='
import sys
from pathlib import Path

import packaging
from packaging.requirements import Requirement
from packaging.version import Version

lines = [line.split("#")[0].strip() for line in Path(sys.argv[1]).read_text().splitlines()]
requirement = Requirement(next(line for line in lines if line))
installed = Version(packaging.__version__)
sys.exit(any(s.operator == ">=" and installed < Version(s.version) for s in requirement.specifier))
'

python="$python_exe"
if ! "$python_exe" -c "$check_packaging" "$script_dir/requirements.txt" 2>/dev/null; then
	# The requirements of the file, without the comments and the blank lines, on one line.
	requirements="$(grep -vE '^[[:space:]]*(#|$)' "$script_dir/requirements.txt" | tr '\n' ' ')"
	echo "'packaging' is missing or too old in '$python_exe': installing ${requirements% } in a private virtual environment"
	temp_dir="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
	# RUNNER_TEMP is a Windows path (D:\a\_temp) on Windows runners: bash needs a POSIX one.
	if [ "${RUNNER_OS:-}" = "Windows" ] && command -v cygpath >/dev/null 2>&1; then
		temp_dir="$(cygpath -u "$temp_dir")"
	fi
	if venv="$(mktemp -d "$temp_dir/extract-pyproject-metadata-venv.XXXXXX")" &&
		"$python_exe" -m venv --system-site-packages "$venv"; then
		python="$venv/$venv_python_path"
		"$python" -m pip install --quiet --disable-pip-version-check \
			-r "$script_dir/requirements.txt" || python=""
	else
		python=""
	fi
	if [ -z "$python" ]; then
		echo "::error::Could not install the 'packaging' Python package (the install needs access to a package index). Check the network and the pip configuration, or install it in the Python on PATH (e.g. 'pip install --upgrade packaging') before using this action." >&2
		exit 1
	fi
fi

"$python" "$script_dir/extract_metadata.py" "$@"
