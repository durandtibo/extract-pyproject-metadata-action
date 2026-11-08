"""Property-based tests (Hypothesis) of the parsers and the escaping functions.

The examples are derandomized, so a run is reproducible: a failure on CI fails the same way
locally. The unit tests with literal inputs are in ``test_extract_metadata.py``.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from extract_metadata import (
    MetadataError,
    compatible_python_versions,
    escape_annotation,
    escape_annotation_property,
    highest_python_version,
    lowest_python_version,
    parse_bool,
    parse_dependencies,
    parse_python_candidates,
    parse_string_array,
)

settings.register_profile("derandomized", max_examples=200, deadline=None, derandomize=True)
settings.load_profile("derandomized")

minor_versions = st.builds(
    "{}.{}".format, st.integers(min_value=0, max_value=3), st.integers(min_value=0, max_value=40)
)
# Valid and invalid JSON values: any value that ``json.dumps`` can write.
json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(),
    lambda children: st.lists(children) | st.dictionaries(st.text(), children),
    max_leaves=10,
)


def unescape(message: str) -> str:
    """Invert ``escape_annotation`` in one pass (as the runner does)."""
    codes = {"%25": "%", "%0D": "\r", "%0A": "\n", "%3A": ":", "%2C": ","}
    return re.sub(r"%25|%0D|%0A|%3A|%2C", lambda match: codes[match.group()], message)


@given(st.lists(st.text()))
def test_parse_string_array_round_trips_a_list_of_strings(values: list[str]) -> None:
    assert parse_string_array(json.dumps(values), "input") == values


@given(json_values)
def test_parse_string_array_accepts_only_a_list_of_strings(value: object) -> None:
    is_valid = isinstance(value, list) and all(isinstance(item, str) for item in value)

    if is_valid:
        assert parse_string_array(json.dumps(value), "input") == value
    else:
        with pytest.raises(MetadataError, match=r"^input must be a JSON array of strings"):
            parse_string_array(json.dumps(value), "input")


@given(st.text())
def test_parse_string_array_never_fails_with_another_error(raw: str) -> None:
    try:
        result = parse_string_array(raw, "input")
    except MetadataError as exc:
        message = str(exc)
    else:
        assert all(isinstance(item, str) for item in result)
        return
    assert message.startswith("input ")


@given(st.text())
def test_parse_dependencies_never_fails_with_another_error(raw: str) -> None:
    try:
        result = parse_dependencies(raw)
    except MetadataError:
        return
    assert all(isinstance(item, str) for item in result)


@given(st.lists(minor_versions))
def test_parse_python_candidates_removes_duplicates_and_keeps_the_order(
    candidates: list[str],
) -> None:
    result = parse_python_candidates(json.dumps(candidates))

    assert result == list(dict.fromkeys(candidates))
    assert len(result) == len(set(result))


@given(st.text())
def test_parse_python_candidates_never_fails_with_another_error(raw: str) -> None:
    try:
        result = parse_python_candidates(raw)
    except MetadataError:
        return
    assert all(re.fullmatch(r"\d+\.\d+", item) for item in result)


@given(st.text(), st.lists(minor_versions, unique=True))
def test_compatible_python_versions_is_a_subsequence_of_the_candidates(
    requires_python: str, candidates: list[str]
) -> None:
    versions, warnings = compatible_python_versions(requires_python, candidates)

    remaining = iter(candidates)
    assert all(version in remaining for version in versions)  # same order, no new value
    assert all(isinstance(warning, str) for warning in warnings)
    if candidates and not versions:
        assert len(warnings) == 1  # an empty python-versions is never silent
    else:
        assert len(warnings) <= 1


@given(st.sampled_from(["", " ", "\t\n"]), st.lists(minor_versions))
def test_compatible_python_versions_allows_everything_without_requires_python(
    requires_python: str, candidates: list[str]
) -> None:
    assert compatible_python_versions(requires_python, candidates) == (candidates, [])


@given(st.lists(minor_versions, min_size=1))
def test_lowest_and_highest_python_versions_are_members_and_ordered(versions: list[str]) -> None:
    lowest = lowest_python_version(versions)
    highest = highest_python_version(versions)

    assert lowest in versions
    assert highest in versions
    key = lambda version: tuple(int(part) for part in version.split("."))  # noqa: E731
    assert key(lowest) <= key(highest)


@given(st.text())
def test_escape_annotation_has_no_line_break_and_round_trips(message: str) -> None:
    escaped = escape_annotation(message)

    assert "\r" not in escaped
    assert "\n" not in escaped
    assert unescape(escaped) == message


@given(st.text())
def test_escape_annotation_property_has_no_delimiter_and_round_trips(value: str) -> None:
    escaped = escape_annotation_property(value)

    assert not set(escaped) & {"\r", "\n", ":", ","}
    assert unescape(escaped) == value


@given(st.text())
def test_parse_bool_accepts_only_true_and_false(value: str) -> None:
    if value.strip().lower() in {"true", "false"}:
        assert parse_bool(value, "flag") == (value.strip().lower() == "true")
    else:
        with pytest.raises(MetadataError, match=r"^flag must be 'true' or 'false'"):
            parse_bool(value, "flag")
