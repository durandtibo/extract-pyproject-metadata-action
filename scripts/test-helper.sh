#!/usr/bin/env bash
# Assertion helpers for the integration workflow (ci-test-action.yaml).
# These only check wiring (inputs reach the action, outputs land in GITHUB_OUTPUT
# correctly) -- business-logic edge cases are covered by tests/unit.

set -euo pipefail

print_error() {
	echo "::error::$1" >&2
}

print_success() {
	echo "✅ $1"
}

assert_equal() {
	local field_name="$1"
	local expected="$2"
	local actual="$3"

	if [ "$actual" != "$expected" ]; then
		print_error "Expected $field_name='$expected', got '$actual'"
		exit 1
	fi
}

# Print the number of __pycache__ directories in the workspace (the action must not leave any).
count_pycache() {
	find . -name __pycache__ -not -path './.git/*' | wc -l | tr -d ' '
}
