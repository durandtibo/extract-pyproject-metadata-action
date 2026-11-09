#!/usr/bin/env bash
# Print the floating tags that a release tag moves, one per line.
#
# Usage: floating-tags.sh <release-tag>
#
# A release tag is vMAJOR.MINOR.PATCH (v1.2.3) or vMAJOR.MINOR (v1.2, the form of
# the first releases). A workflow that uses the action as @v1.2 gets the latest
# patch release of that minor version, and one that uses @v1 gets the latest minor
# release of that major version. So:
#
#   v1.2.3 moves v1.2 and v1
#   v1.2   moves v1
#   v0.2.1 moves v0.2   (0.x releases may break: there is no floating v0)
#   v0.2   moves nothing (it is the tag that users pin)
#
# Exits with 1 and a message on stderr if the argument is not a release tag.

set -euo pipefail

if [ "$#" -ne 1 ]; then
	echo "usage: floating-tags.sh <release-tag>" >&2
	exit 1
fi

tag="$1"
if [[ ! "$tag" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*))?$ ]]; then
	echo "'$tag' is not a release tag (vMAJOR.MINOR or vMAJOR.MINOR.PATCH)" >&2
	exit 1
fi

major="${BASH_REMATCH[1]}"
minor="${BASH_REMATCH[2]}"
patch="${BASH_REMATCH[4]}"

if [ -n "$patch" ]; then
	echo "v$major.$minor"
fi
if [ "$major" != "0" ]; then
	echo "v$major"
fi
