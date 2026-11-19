#!/usr/bin/env bash
# Check that the files shipped to the consumers of the action (git archive, which applies the
# export-ignore rules of .gitattributes) are exactly the files the action needs at runtime:
# action.yaml, LICENSE, scripts/run.sh, scripts/extract_metadata.py and every tracked file of
# src/extract_pyproject_metadata/. `uses: ./` runs the whole checkout, so a file marked
# export-ignore by mistake would pass the tests and break the release. When the action starts
# using a new file outside src/, add it to EXPECTED here and un-ignore it in .gitattributes.
set -euo pipefail

EXPECTED="LICENSE
action.yaml
scripts/
scripts/extract_metadata.py
scripts/run.sh
src/
src/extract_pyproject_metadata/"

actual=$(git archive --worktree-attributes HEAD | tar t | LC_ALL=C sort)
# The package: every tracked file of src/ and its directories, which `git ls-files` does not list.
package=$(git ls-files src | LC_ALL=C sort)
package_dirs=$(printf '%s\n' "$package" | while IFS= read -r file; do
	dir=$(dirname "$file")
	while [ "$dir" != "src/extract_pyproject_metadata" ] && [ "$dir" != "." ]; do
		printf '%s/\n' "$dir"
		dir=$(dirname "$dir")
	done
done)
expected=$(printf '%s\n%s\n%s\n' "$EXPECTED" "$package" "$package_dirs" | sed '/^$/d' | LC_ALL=C sort -u)

if [ "$actual" != "$expected" ]; then
	echo "::error::The exported files differ from the files the action needs (see dev/check_export.sh)"
	diff <(printf '%s\n' "$expected") <(printf '%s\n' "$actual") || true
	exit 1
fi
echo "✅ The exported files are the expected ones ($(printf '%s\n' "$actual" | wc -l | tr -d ' ') entries)"
