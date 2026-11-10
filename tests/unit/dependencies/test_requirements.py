"""Tests of ``extract_pyproject_metadata.dependencies.requirements``."""

from __future__ import annotations

import pytest

import extract_pyproject_metadata.dependencies.requirements as dependencies_requirements_module
from extract_pyproject_metadata._vendor.packaging.requirements import (
    InvalidRequirement,
    Requirement,
)
from extract_pyproject_metadata.dependencies.requirements import (
    _dynamic_dependency_fields,
    _index_requirements,
    _scoped_requirements,
    candidate_requirements,
    conflict_warnings,
    index_dependencies,
)
from extract_pyproject_metadata.errors import MetadataError
from tests.helpers import (
    DATA_WITH_REQUIREMENTS,
    _parse_error,
)


def testcandidate_requirements_search_order() -> None:
    data = {
        "project": {
            "dependencies": ["a>=1"],
            "optional-dependencies": {"x": ["b>=2"], "y": ["c>=3"]},
        },
        "dependency-groups": {"dev": ["d>=4"], "test": [{"include-group": "dev"}, "e>=5"]},
    }

    assert candidate_requirements(data)[0] == [
        "a>=1",
        "b>=2",
        "c>=3",
        "d>=4",
        "d>=4",
        "e>=5",
    ]


def test_scoped_requirements() -> None:
    data = {
        "project": {
            "dependencies": ["a"],
            "optional-dependencies": {"Extra_One": ["b"], "two": ["c", "d"]},
        },
        "dependency-groups": {"Dev_Tools": ["e", {"include-group": "lint"}], "lint": ["f"]},
    }

    assert _scoped_requirements(data) == (
        [
            ("project", "a"),
            ("extra:extra-one", "b"),
            ("extra:two", "c"),
            ("extra:two", "d"),
            ("group:dev-tools", "e"),
            ("group:dev-tools", "f"),
            ("group:lint", "f"),
        ],
        [],
    )


def test_scoped_requirements_share_a_scope_between_the_spellings_of_a_name() -> None:
    data = {"project": {"optional-dependencies": {"Foo_Bar": ["a"], "foo-bar": ["b"]}}}

    assert _scoped_requirements(data)[0] == [("extra:foo-bar", "a"), ("extra:foo-bar", "b")]


def test_scoped_requirements_empty() -> None:
    assert _scoped_requirements({}) == ([], [])


def test_scoped_requirements_wrong_type() -> None:
    with pytest.raises(MetadataError, match=r"^p.toml: \[project\].dependencies must be an array"):
        _scoped_requirements({"project": {"dependencies": "a"}}, "p.toml")


def testcandidate_requirements_empty() -> None:
    assert candidate_requirements({}) == ([], [])


@pytest.mark.parametrize(
    ("data", "match"),
    [
        (
            {"project": {"dependencies": ["a", 1]}},
            r"p\.toml: \[project\]\.dependencies must contain only strings, got: 1",
        ),
        (
            {"project": {"dependencies": [None]}},
            r"\[project\]\.dependencies must contain only strings, got: None",
        ),
        (
            {"project": {"optional-dependencies": {"x": ["c", {"b": 1}]}}},
            r"\[project\.optional-dependencies\]\.x must contain only strings, got: \{'b': 1\}",
        ),
    ],
)
def testcandidate_requirements_non_string_entries(data: dict, match: str) -> None:
    with pytest.raises(MetadataError, match=match):
        candidate_requirements(data, "p.toml")


def testcandidate_requirements_does_not_modify_the_data() -> None:
    data = {"project": {"dependencies": ["a"], "optional-dependencies": {"x": ["b"]}}}

    assert candidate_requirements(data)[0] == ["a", "b"]
    assert data == {"project": {"dependencies": ["a"], "optional-dependencies": {"x": ["b"]}}}


@pytest.mark.parametrize(
    ("data", "match"),
    [
        ({"project": 1}, r"\[project\] must be a table"),
        ({"project": {"dependencies": "a"}}, r"\[project\]\.dependencies must be an array"),
        ({"project": {"optional-dependencies": 1}}, r"optional-dependencies must be a table"),
        (
            {"project": {"optional-dependencies": {"x": 1}}},
            r"optional-dependencies\]\.x must be an array",
        ),
        ({"dependency-groups": 1}, r"\[dependency-groups\] must be a table"),
    ],
)
def testcandidate_requirements_wrong_types(data: dict, match: str) -> None:
    with pytest.raises(MetadataError, match=match):
        candidate_requirements(data)


def testcandidate_requirements_reports_a_cycle_once() -> None:
    data = {
        "dependency-groups": {
            "a": [{"include-group": "b"}, "x"],
            "b": [{"include-group": "a"}, "y"],
        }
    }
    _, warnings = candidate_requirements(data, "p.toml")

    assert warnings == ["p.toml: [dependency-groups] has an include-group cycle: a -> b -> a"]


@pytest.mark.parametrize(
    ("matches", "expected"),
    [
        ([("==1", None)], []),
        ([("==1", None), ("==1", None)], []),
        ([("==1", "os_name == 'nt'"), ("==2", "os_name == 'posix'")], []),
        ([("==1", None), ("==2", "os_name == 'nt'")], []),
        (
            [("==1", None), ("==2", None)],
            ["a has different specifiers in p.toml: ['==1', '==2']; using '==1'"],
        ),
        (
            [("==2", None), ("==1", None), ("==2", None)],
            ["a has different specifiers in p.toml: ['==1', '==2']; using '==2'"],
        ),
    ],
)
def test_conflict_warnings(matches: list[tuple[str, str | None]], expected: list[str]) -> None:
    assert conflict_warnings("a", matches, matches[0][0], "p.toml") == expected


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({}, []),
        ({"project": {}}, []),
        ({"project": {"dynamic": ["version"]}}, []),
        ({"project": {"dynamic": ["dependencies"]}}, ["dependencies"]),
        ({"project": {"dynamic": ["optional-dependencies"]}}, ["optional-dependencies"]),
        (
            {"project": {"dynamic": ["optional-dependencies", "dependencies"]}},
            ["dependencies", "optional-dependencies"],
        ),
        ({"project": {"dynamic": ["dependencies"], "dependencies": ["a"]}}, []),
        ({"project": {"dynamic": "dependencies"}}, []),
        ({"project": 1}, []),
    ],
)
def test_dynamic_dependency_fields(data: dict, expected: list[str]) -> None:
    assert _dynamic_dependency_fields(data) == expected


def test_parse_requirement_valid() -> None:
    requirement = dependencies_requirements_module._parse_requirement(
        "Foo_Bar[x]>=1; python_version<'3.12'"
    )

    assert isinstance(requirement, Requirement)
    assert (requirement.name, str(requirement.specifier)) == ("Foo_Bar", ">=1")


def test_parse_requirement_invalid_is_returned_not_raised() -> None:
    error = dependencies_requirements_module._parse_requirement("bad requirement!!")

    assert isinstance(error, InvalidRequirement)


def test_parse_requirement_is_called_once_per_distinct_string() -> None:
    parse = dependencies_requirements_module._parse_requirement
    parse.cache_clear()

    assert parse("numpy>=1") is parse("numpy>=1")
    assert parse("bad!!") is parse("bad!!")
    assert parse.cache_info().misses == 2


def test_index_dependencies() -> None:
    found, warnings = index_dependencies(DATA_WITH_REQUIREMENTS, "p.toml")

    assert found == {
        "numpy": [(">=1.20", 'python_version < "3.12"'), (">=1.26", 'python_version >= "3.12"')],
        "tqdm": [("", None)],
        "pytest": [("", None)],
        "numpy@project": [(">=1.20", 'python_version < "3.12"')],
        "tqdm@project": [("", None)],
        "numpy@extra:x": [(">=1.26", 'python_version >= "3.12"')],
        "pytest@group:dev": [("", None)],
    }
    assert warnings == [
        "p.toml: [dependency-groups].dev: include-group 'missing' does not match any group",
        "Ignoring invalid requirement 'not valid!' in p.toml: " + str(_parse_error("not valid!")),
    ]


def test_index_dependencies_empty() -> None:
    assert index_dependencies({}, "p.toml") == ({}, [])


def test_index_dependencies_wrong_type() -> None:
    with pytest.raises(MetadataError, match=r"^p.toml: \[project\].dependencies must be an array"):
        index_dependencies({"project": {"dependencies": "numpy"}}, "p.toml")


def test_index_requirements() -> None:
    found, names, warnings = _index_requirements(
        ["Foo_Bar>=1; os_name == 'nt'", "foo-bar<3", "oops==", "x"], "p.toml"
    )

    assert found == {
        "foo-bar": [(">=1", 'os_name == "nt"'), ("<3", None)],
        "x": [("", None)],
    }
    assert names == {"foo-bar": "Foo_Bar", "x": "x"}
    assert len(warnings) == 1
    assert warnings[0].startswith("Ignoring invalid requirement 'oops==' in p.toml: ")


def test_index_requirements_empty() -> None:
    assert _index_requirements([], "p.toml") == ({}, {}, [])
