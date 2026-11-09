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
# The install only happens when "packaging" is missing or too old: the usual
# setup-python Python and most runner images have it, and then nothing is
# downloaded. The tool that installs it is chosen by the INSTALLER environment
# variable (the installer input of the action): "pip" (the default: python -m venv
# and pip, which follow the pip configuration, PIP_INDEX_URL and pip.conf),
# "uv" (uv venv and uv pip, faster, which follow the configuration of uv: UV_INDEX_URL
# and uv.toml; it fails when uv is not on PATH and an install is needed) or "auto"
# (uv when it is on PATH, pip otherwise).
#
# The exit code is the one of extract_metadata.py, or 1 on a Windows runner, if
# the interpreter is older than 3.11 or cannot be run or if the requirements cannot be
# installed.

set -euo pipefail

export PYTHONDONTWRITEBYTECODE=1

# The interpreter to use: a command found on PATH, or a path.
python_exe="${PYTHON_EXECUTABLE:-python3}"

# How to install "packaging" when it is needed: pip, uv or auto.
installer="${INSTALLER:-pip}"
case "$installer" in
pip | uv | auto) ;;
*)
	echo "::error::The installer must be 'pip', 'uv' or 'auto', got: '$installer'" >&2
	exit 1
	;;
esac

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Only Linux and macOS are supported (a venv has Scripts/ instead of bin/ on Windows).
if [ "${RUNNER_OS:-}" = "Windows" ]; then
	echo "::error::This action does not support Windows runners. Use a Linux or macOS runner." >&2
	exit 1
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

# Create a virtual environment that sees the packages of the interpreter, in the existing
# directory $3, with the tool $1 (pip or uv) and the interpreter $2.
create_venv() {
	if [ "$1" = "uv" ]; then
		uv venv --quiet --system-site-packages --python "$2" "$3"
	else
		"$2" -m venv --system-site-packages "$3"
	fi
}

# Install the requirements file $3 in the virtual environment of the Python $2, with the tool $1.
install_requirements() {
	if [ "$1" = "uv" ]; then
		uv pip install --quiet --python "$2" -r "$3"
	else
		"$2" -m pip install --quiet --disable-pip-version-check -r "$3"
	fi
}

python="$python_exe"
if ! "$python_exe" -c "$check_packaging" "$script_dir/requirements.txt" 2>/dev/null; then
	# The requirements of the file, without the comments and the blank lines, on one line.
	requirements="$(grep -vE '^[[:space:]]*(#|$)' "$script_dir/requirements.txt" | tr '\n' ' ')"
	echo "'packaging' is missing or too old in '$python_exe': installing ${requirements% } in a private virtual environment"
	# The tool that creates the venv and installs the requirements.
	tool="pip"
	case "$installer" in
	uv)
		if ! command -v uv >/dev/null 2>&1; then
			echo "::error::The installer is 'uv' but uv was not found on PATH. Install uv (e.g. with astral-sh/setup-uv) or use the installer 'pip' or 'auto'." >&2
			exit 1
		fi
		tool="uv"
		;;
	auto)
		if command -v uv >/dev/null 2>&1; then
			tool="uv"
		fi
		;;
	esac
	if venv="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/extract-pyproject-metadata-venv.XXXXXX")" &&
		create_venv "$tool" "$python_exe" "$venv"; then
		python="$venv/bin/python"
		install_requirements "$tool" "$python" "$script_dir/requirements.txt" || python=""
	else
		python=""
	fi
	if [ -z "$python" ]; then
		echo "::error::Could not install the 'packaging' Python package (the install needs access to a package index). Check the network and the $tool configuration, or install it in the Python on PATH (e.g. 'pip install --upgrade packaging') before using this action." >&2
		exit 1
	fi
fi

"$python" "$script_dir/extract_metadata.py" "$@"
