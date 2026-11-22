#!/usr/bin/env bash
# Put the action as it is shipped (the git archive of a ref, with the export-ignore rules of the
# working tree) in a directory, so that `uses: ./<dir>` runs what a consumer gets.
# Usage: stage-action.sh <ref> <dir>
set -euo pipefail

if [ "$#" -ne 2 ] || [ -z "$1" ]; then
	echo "usage: stage-action.sh <ref> <dir>" >&2
	exit 2
fi

mkdir -p "$2"
git archive --worktree-attributes "$1" | tar -x -C "$2"
