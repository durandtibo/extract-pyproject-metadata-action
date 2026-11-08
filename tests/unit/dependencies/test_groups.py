"""Tests of ``extract_pyproject_metadata.dependencies.groups`` and of
the groups in the requirements."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from extract_pyproject_metadata.dependencies.groups import flatten_group
from extract_pyproject_metadata.dependencies.requirements import (
    _candidate_requirements,
    extract_project_dependencies,
)
from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.fields import read_group_names
from tests.helpers import (
    GROUPS_TOML,
    chain_of_groups,
    diamond_of_groups,
    extract,
    specifiers,
    write_pyproject,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_dependency_include_group_only(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        '[dependency-groups]\nbase = ["x>=1"]\ndev = [{include-group = "base"}]\n',
    )
    assert specifiers(path, '["x"]') == {"x": ">=1"}


@pytest.mark.parametrize(
    ("groups", "name", "expected"),
    [
        ({"a": ["x>=1"]}, "a", ["x>=1"]),
        ({"a": []}, "a", []),
        ({}, "a", []),
        ({"a": ["x"]}, "missing", []),
        ({"My_Group": ["x"]}, "my-group", ["x"]),
        ({"a": [{"include-group": "b"}, "x"], "b": ["y"]}, "a", ["y", "x"]),
        ({"a": [{"include-group": "B-C"}], "b_c": ["y"]}, "a", ["y"]),
        ({"a": [{"include-group": "missing"}, "x"]}, "a", ["x"]),
        ({"a": [{"include-group": "b"}], "b": [{"include-group": "c"}], "c": ["z"]}, "a", ["z"]),
    ],
)
def test_flatten_group(groups: dict, name: str, expected: list[str]) -> None:
    assert flatten_group(groups, name)[0] == expected


@pytest.mark.parametrize(
    ("groups", "name", "expected"),
    [
        ({"a": [{"include-group": "a"}, "x"]}, "a", ["x"]),
        ({"a": [{"include-group": "b"}, "x"], "b": [{"include-group": "a"}, "y"]}, "a", ["y", "x"]),
        (
            {
                "a": [{"include-group": "b"}],
                "b": [{"include-group": "c"}, "y"],
                "c": [{"include-group": "a"}, "z"],
            },
            "a",
            ["z", "y"],
        ),
    ],
)
def test_flatten_group_include_cycles_terminate(
    groups: dict, name: str, expected: list[str]
) -> None:
    assert flatten_group(groups, name)[0] == expected


def test_candidate_requirements_expands_the_spellings_of_a_group_once() -> None:
    data = {"dependency-groups": {"Dev_Tools": ["a"], "dev-tools": ["b"], "other": ["c"]}}

    assert _candidate_requirements(data)[0] == ["a", "b", "c"]


def test_dependency_include_group_cycle_in_pyproject(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [dependency-groups]
        a = [{include-group = "b"}, "x>=1"]
        b = [{include-group = "a"}, "y>=2"]
        """,
    )

    assert specifiers(path, '["x", "y"]') == {"x": ">=1", "y": ">=2"}


def test_flatten_group_group_must_be_an_array() -> None:
    with pytest.raises(
        MetadataError, match=r"custom\.toml: \[dependency-groups\]\.a must be an array"
    ):
        flatten_group({"a": "x"}, "a", pyproject_path="custom.toml")


@pytest.mark.parametrize(
    "entry",
    [{"include_group": "b"}, {}, {"include-group": "b", "extra": 1}, 1, None, ["x"], 1.5],
)
def test_flatten_group_unknown_entry(entry: object) -> None:
    with pytest.raises(
        MetadataError,
        match=r"p\.toml: \[dependency-groups\]\.a entries must be strings or "
        r"\{'include-group': <name>\} tables, got: ",
    ):
        flatten_group({"a": ["x", entry], "b": ["y"]}, "a", pyproject_path="p.toml")


def test_flatten_group_unknown_entry_in_an_included_group() -> None:
    with pytest.raises(MetadataError, match=r"\[dependency-groups\]\.b entries must be"):
        flatten_group({"a": [{"include-group": "b"}], "b": [{"typo": 1}]}, "a")


def test_flatten_group_include_group_must_be_a_string() -> None:
    with pytest.raises(MetadataError, match=r"\.a: include-group must be a string, got: \['b'\]"):
        flatten_group({"a": [{"include-group": ["b"]}]}, "a")


def test_flatten_group_cycle_adds_a_warning() -> None:
    groups = {"a": [{"include-group": "b"}, "x"], "b": [{"include-group": "a"}, "y"]}
    result, warnings = flatten_group(groups, "a", pyproject_path="p.toml")

    assert result == ["y", "x"]
    assert warnings == ["p.toml: [dependency-groups] has an include-group cycle: a -> b -> a"]


def test_flatten_group_self_include_adds_a_warning() -> None:
    result, warnings = flatten_group({"a": [{"include-group": "a"}, "x"]}, "a")

    assert result == ["x"]
    assert warnings == ["pyproject.toml: [dependency-groups] has an include-group cycle: a -> a"]


def test_flatten_group_cycle_message_starts_at_the_smallest_group() -> None:
    groups = {
        "c": [{"include-group": "a"}],
        "a": [{"include-group": "b"}],
        "b": [{"include-group": "c"}],
    }
    _, warnings = flatten_group(groups, "b")

    assert warnings == [
        "pyproject.toml: [dependency-groups] has an include-group cycle: a -> b -> c -> a"
    ]


def test_flatten_group_cycle_does_not_include_the_path_leading_to_it() -> None:
    groups = {
        "a": [{"include-group": "b"}],
        "b": [{"include-group": "c"}],
        "c": [{"include-group": "b"}],
    }
    _, warnings = flatten_group(groups, "a")

    assert warnings == [
        "pyproject.toml: [dependency-groups] has an include-group cycle: b -> c -> b"
    ]


def test_flatten_group_cycle_uses_canonical_names() -> None:
    groups = {"My_Group": [{"include-group": "my-group"}]}
    _, warnings = flatten_group(groups, "My_Group")

    assert warnings == [
        "pyproject.toml: [dependency-groups] has an include-group cycle: my-group -> my-group"
    ]


def test_flatten_group_no_cycle_adds_no_warning() -> None:
    groups = {"a": [{"include-group": "b"}, {"include-group": "b"}], "b": ["y"]}
    result, warnings = flatten_group(groups, "a")

    assert result == ["y", "y"]
    assert warnings == []


def test_flatten_group_follows_a_chain_up_to_the_depth_limit() -> None:
    result, warnings = flatten_group(chain_of_groups(100), "g0")

    assert result == ["numpy>=1"]
    assert warnings == []


def test_flatten_group_rejects_a_chain_deeper_than_the_limit() -> None:
    with pytest.raises(
        MetadataError,
        match=r"^p.toml: \[dependency-groups\] include-group entries are nested more than 100 levels deep",
    ):
        flatten_group(chain_of_groups(101), "g0", pyproject_path="p.toml")


def test_flatten_group_rejects_a_chain_longer_than_the_recursion_limit() -> None:
    with pytest.raises(MetadataError, match="nested more than 100 levels deep"):
        flatten_group(chain_of_groups(5000), "g0")


def test_flatten_group_expands_a_diamond_within_the_budget() -> None:
    result, warnings = flatten_group(diamond_of_groups(10), "g0")

    assert result == ["numpy>=1"] * 1024
    assert warnings == []


def test_flatten_group_rejects_an_exponential_expansion() -> None:
    with pytest.raises(
        MetadataError,
        match=r"^p.toml: \[dependency-groups\] include-group entries expand more than 10000 groups in total",
    ):
        flatten_group(diamond_of_groups(25), "g0", pyproject_path="p.toml")


def test_flatten_group_shares_the_budget_between_the_included_groups() -> None:
    budget = [3]

    with pytest.raises(MetadataError, match="expand more than"):
        flatten_group(chain_of_groups(5), "g0", budget=budget)

    assert budget == [-1]


def test_flatten_group_missing_include_group_adds_a_warning() -> None:
    result, warnings = flatten_group(
        {"dev": [{"include-group": "tset"}, "x"]}, "dev", pyproject_path="p.toml"
    )

    assert result == ["x"]
    assert warnings == [
        "p.toml: [dependency-groups].dev: include-group 'tset' does not match any group"
    ]


def test_flatten_group_include_group_matches_any_pep_503_spelling_without_warning() -> None:
    result, warnings = flatten_group({"a": [{"include-group": "My-Group"}], "my_group": ["y"]}, "a")

    assert result == ["y"]
    assert warnings == []


def test_flatten_group_missing_include_group_is_reported_once_per_group() -> None:
    groups = {"a": [{"include-group": "nope"}], "b": [{"include-group": "a"}]}
    _, warnings = _candidate_requirements({"dependency-groups": groups}, "p.toml")

    assert warnings == [
        "p.toml: [dependency-groups].a: include-group 'nope' does not match any group"
    ]


def test_extract_metadata_groups_are_sorted(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, GROUPS_TOML)

    assert extract(path)["groups"] == ["Dev", "docs", "test"]


def test_extract_metadata_groups_default_to_empty(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "p"\nversion = "1"\n')

    assert extract(path)["groups"] == []


def test_extract_metadata_groups_empty_table(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "p"\nversion = "1"\n[dependency-groups]\n')

    assert extract(path)["groups"] == []


@pytest.mark.parametrize(
    ("groups", "expected"),
    [
        ('Foo_Bar = []\n"foo-bar" = []', ["Foo_Bar"]),
        ('"foo-bar" = []\nFoo_Bar = []', ["foo-bar"]),
        ("b = []\nA = []\nc = []", ["A", "b", "c"]),
    ],
)
def test_extract_metadata_groups_are_deduplicated_per_pep_503(
    tmp_path: Path, groups: str, expected: list[str]
) -> None:
    path = write_pyproject(
        tmp_path, f'[project]\nname = "p"\nversion = "1"\n[dependency-groups]\n{groups}\n'
    )

    assert extract(path)["groups"] == expected


def test_extract_metadata_groups_are_not_mixed_with_extras(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [project]
        name = "p"
        version = "1"

        [project.optional-dependencies]
        numpy = []

        [dependency-groups]
        dev = []
        """,
    )

    metadata = extract(path, '["all"]')

    assert metadata["extras"] == ["all", "numpy"]
    assert metadata["groups"] == ["dev"]


@pytest.mark.parametrize("value", ["[]", '["dev"]', '"dev"', "1"])
def test_extract_metadata_groups_must_be_a_table(tmp_path: Path, value: str) -> None:
    path = write_pyproject(
        tmp_path, f'dependency-groups = {value}\n[project]\nname = "p"\nversion = "1"\n'
    )

    with pytest.raises(MetadataError, match=r"\[dependency-groups\] must be a table, got: "):
        extract(path)


def test_group_names() -> None:
    data = {"dependency-groups": {"test": [], "Dev_Tools": [], "dev-tools": [], "docs": []}}

    assert read_group_names(data, "p.toml") == ["Dev_Tools", "docs", "test"]


def test_group_names_without_groups() -> None:
    assert read_group_names({}, "p.toml") == []


def test_group_names_must_be_a_table() -> None:
    with pytest.raises(MetadataError, match=r"^p.toml: \[dependency-groups\] must be a table"):
        read_group_names({"dependency-groups": []}, "p.toml")


def test_extract_project_dependencies_ignores_extras_and_groups() -> None:
    data = {
        "project": {"dependencies": ["a"], "optional-dependencies": {"x": ["b"]}},
        "dependency-groups": {"dev": ["c"]},
    }

    assert extract_project_dependencies(data) == ({"a": ""}, [])
