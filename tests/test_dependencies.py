"""Tests of the dependency lookup: requirements, scopes, groups and specifiers."""



import json
import re
from pathlib import Path

import pytest
from helpers import (
    DATA_WITH_REQUIREMENTS,
    DATA_WITH_SCOPES,
    DEPS_TOML,
    GROUPS_TOML,
    INVALID_TOML,
    MARKERS_TOML,
    _parse_error,
    chain_of_groups,
    diamond_of_groups,
    extract,
    specifiers,
    write_pyproject,
)
from packaging.requirements import InvalidRequirement, Requirement

import extract_pyproject_metadata.cli as extract_metadata_module
from extract_pyproject_metadata.cli import (
    _candidate_requirements,
    _conflict_warnings,
    _dynamic_dependency_fields,
    _extra_names,
    _flatten_group,
    _group_names,
    _index_dependencies,
    _index_requirements,
    _lookup_key,
    _requirements_from_index,
    _scoped_requirements,
    _specifiers_from_index,
    extract_dependency_requirements,
    extract_dependency_specifiers,
    extract_project_dependencies,
    load_pyproject,
    parse_dependencies,
)
from extract_pyproject_metadata.errors import MetadataError


def test_extract_metadata_no_optional_dependencies_table(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [project]
        name = "coola"
        version = "1.2.3"
        """,
    )

    metadata = extract(path)

    assert metadata["extras"] == []



@pytest.mark.parametrize("value", ['["a"]', '"numpy"', "1"])
def test_extract_metadata_optional_dependencies_must_be_a_table(
    tmp_path: Path, value: str
) -> None:
    path = write_pyproject(
        tmp_path,
        f"""
        [project]
        name = "coola"
        version = "1.2.3"
        optional-dependencies = {value}
        """,
    )

    with pytest.raises(
        MetadataError, match=r"\[project\]\.optional-dependencies must be a table"
    ):
        extract(path)



@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("foo.bar", "<2,>=1"),
        ("nospec", ""),
        ("withextra", ">=3"),
        ("EXTRA_pkg", "~=2.0"),
        ("grp-pkg", "==1.0"),
        ("dev-pkg", ">=0.1"),
        ("missing", None),
    ],
)
def test_dependency_specifiers(tmp_path: Path, name: str, expected: str | None) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    assert specifiers(path, json.dumps([name])) == {name: expected}



def test_dependency_include_group_only(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        '[dependency-groups]\nbase = ["x>=1"]\ndev = [{include-group = "base"}]\n',
    )
    assert specifiers(path, '["x"]') == {"x": ">=1"}



def test_dependency_duplicate_adds_a_warning(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    result, warnings = extract_dependency_specifiers(
        load_pyproject(str(path)), ["dup"], str(path))

    assert result == {"dup": ">=1"}
    assert warnings == [f"dup has different specifiers in {path}: ['>=1', '>=2']; using '>=1'"]



def test_dependency_no_duplicate_adds_no_warning(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    _, warnings = extract_dependency_specifiers(load_pyproject(str(path)), ["nospec"], str(path))

    assert warnings == []



def test_dependency_invalid_requirements_add_warnings(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, INVALID_TOML)
    result, warnings = extract_dependency_specifiers(
        load_pyproject(str(path)), ["good", "dev-pkg", "missing"], str(path))

    assert result == {"good": ">=1", "dev-pkg": ">=2", "missing": None}
    assert len(warnings) == 3
    assert warnings[0].startswith(f"Ignoring invalid requirement 'bad requirement!!' in {path}: ")
    assert warnings[1].startswith(f"Ignoring invalid requirement 'also bad>>' in {path}: ")
    assert warnings[2].startswith(f"Ignoring invalid requirement 'oops==' in {path}: ")



def test_dependency_invalid_requirements_do_not_warn_when_nothing_is_requested(
    tmp_path: Path,
) -> None:
    path = write_pyproject(tmp_path, INVALID_TOML)
    result, warnings = extract_dependency_specifiers(load_pyproject(str(path)), [], str(path))

    assert result == {}
    assert warnings == []



@pytest.mark.parametrize("value", ["nope", '{"a": 1}', "[1]"])
def test_dependency_invalid_input(tmp_path: Path, value: str) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    with pytest.raises(MetadataError):
        specifiers(path, value)



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
    assert _flatten_group(groups, name)[0] == expected



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
    assert _flatten_group(groups, name)[0] == expected



def test_candidate_requirements_search_order() -> None:
    data = {
        "project": {
            "dependencies": ["a>=1"],
            "optional-dependencies": {"x": ["b>=2"], "y": ["c>=3"]},
        },
        "dependency-groups": {"dev": ["d>=4"], "test": [{"include-group": "dev"}, "e>=5"]},
    }

    assert _candidate_requirements(data)[0] == [
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



def test_candidate_requirements_empty() -> None:
    assert _candidate_requirements({}) == ([], [])



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
def test_candidate_requirements_non_string_entries(data: dict, match: str) -> None:
    with pytest.raises(MetadataError, match=match):
        _candidate_requirements(data, "p.toml")



def test_candidate_requirements_expands_the_spellings_of_a_group_once() -> None:
    data = {"dependency-groups": {"Dev_Tools": ["a"], "dev-tools": ["b"], "other": ["c"]}}

    assert _candidate_requirements(data)[0] == ["a", "b", "c"]



def test_candidate_requirements_does_not_modify_the_data() -> None:
    data = {"project": {"dependencies": ["a"], "optional-dependencies": {"x": ["b"]}}}

    assert _candidate_requirements(data)[0] == ["a", "b"]
    assert data == {"project": {"dependencies": ["a"], "optional-dependencies": {"x": ["b"]}}}



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



def test_dependency_requested_twice_and_empty_project(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, "")

    assert specifiers(path, '["x", "x"]') == {"x": None}



def test_dependency_name_matches_across_pep_503_spellings(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\ndependencies = ["Zope.Interface>=5"]\n')

    assert specifiers(path, '["zope-interface", "ZOPE_INTERFACE"]') == {
        "zope-interface": ">=5",
        "ZOPE_INTERFACE": ">=5",
    }



@pytest.mark.parametrize(
    ("content", "match"),
    [
        ('[project]\ndependencies = "numpy"', r"\[project\]\.dependencies must be an array, got: 'numpy'"),
        ("[project]\ndependencies = 1", r"\[project\]\.dependencies must be an array, got: 1"),
        (
            '[project.optional-dependencies]\nx = "numpy"',
            r"\[project\.optional-dependencies\]\.x must be an array, got: 'numpy'",
        ),
        (
            "[project.optional-dependencies]\nx = 1",
            r"\[project\.optional-dependencies\]\.x must be an array, got: 1",
        ),
        ("[project]\noptional-dependencies = []", r"\[project\]\.optional-dependencies must be a table"),
        ("dependency-groups = []", r"\[dependency-groups\] must be a table, got: \[\]"),
        ('dependency-groups = "dev"', r"\[dependency-groups\] must be a table, got: 'dev'"),
        ('[dependency-groups]\ndev = "numpy"', r"\[dependency-groups\]\.dev must be an array, got: 'numpy'"),
        ("[dependency-groups]\ndev = 1", r"\[dependency-groups\]\.dev must be an array, got: 1"),
        (
            "[dependency-groups]\ndev = [{include-group = 1}]",
            r"\[dependency-groups\]\.dev: include-group must be a string, got: 1",
        ),
        (
            '[dependency-groups]\na = [{include-group = "b"}]\nb = "x"',
            r"\[dependency-groups\]\.b must be an array, got: 'x'",
        ),
        ("project = 1", r"\[project\] must be a table, got: 1"),
    ],
)
def test_dependency_malformed_tables_raise_metadata_error(
    tmp_path: Path, content: str, match: str
) -> None:
    path = write_pyproject(tmp_path, content)

    with pytest.raises(MetadataError, match=match):
        specifiers(path, '["numpy"]')



def test_dependency_malformed_tables_raise_even_when_nothing_is_requested(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\ndependencies = "numpy"')

    with pytest.raises(MetadataError, match=r"\[project\]\.dependencies must be an array"):
        specifiers(path, "[]")



def test_dependency_malformed_table_error_names_the_file() -> None:
    with pytest.raises(MetadataError, match=r"custom/pyproject\.toml: \[dependency-groups\] must"):
        extract_dependency_specifiers({"dependency-groups": 1}, [], "custom/pyproject.toml")



def test_flatten_group_group_must_be_an_array() -> None:
    with pytest.raises(MetadataError, match=r"custom\.toml: \[dependency-groups\]\.a must be an array"):
        _flatten_group({"a": "x"}, "a", pyproject_path="custom.toml")



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
        _flatten_group({"a": ["x", entry], "b": ["y"]}, "a", pyproject_path="p.toml")



def test_flatten_group_unknown_entry_in_an_included_group() -> None:
    with pytest.raises(MetadataError, match=r"\[dependency-groups\]\.b entries must be"):
        _flatten_group({"a": [{"include-group": "b"}], "b": [{"typo": 1}]}, "a")



def test_flatten_group_include_group_must_be_a_string() -> None:
    with pytest.raises(MetadataError, match=r"\.a: include-group must be a string, got: \['b'\]"):
        _flatten_group({"a": [{"include-group": ["b"]}]}, "a")



@pytest.mark.parametrize(
    ("data", "match"),
    [
        ({"project": 1}, r"\[project\] must be a table"),
        ({"project": {"dependencies": "a"}}, r"\[project\]\.dependencies must be an array"),
        ({"project": {"optional-dependencies": 1}}, r"optional-dependencies must be a table"),
        ({"project": {"optional-dependencies": {"x": 1}}}, r"optional-dependencies\]\.x must be an array"),
        ({"dependency-groups": 1}, r"\[dependency-groups\] must be a table"),
    ],
)
def test_candidate_requirements_wrong_types(data: dict, match: str) -> None:
    with pytest.raises(MetadataError, match=match):
        _candidate_requirements(data)



def test_flatten_group_cycle_adds_a_warning() -> None:
    groups = {"a": [{"include-group": "b"}, "x"], "b": [{"include-group": "a"}, "y"]}
    result, warnings = _flatten_group(groups, "a", pyproject_path="p.toml")

    assert result == ["y", "x"]
    assert warnings == ["p.toml: [dependency-groups] has an include-group cycle: a -> b -> a"]



def test_flatten_group_self_include_adds_a_warning() -> None:
    result, warnings = _flatten_group({"a": [{"include-group": "a"}, "x"]}, "a")

    assert result == ["x"]
    assert warnings == ["pyproject.toml: [dependency-groups] has an include-group cycle: a -> a"]



def test_flatten_group_cycle_message_starts_at_the_smallest_group() -> None:
    groups = {"c": [{"include-group": "a"}], "a": [{"include-group": "b"}], "b": [{"include-group": "c"}]}
    _, warnings = _flatten_group(groups, "b")

    assert warnings == ["pyproject.toml: [dependency-groups] has an include-group cycle: a -> b -> c -> a"]



def test_flatten_group_cycle_does_not_include_the_path_leading_to_it() -> None:
    groups = {"a": [{"include-group": "b"}], "b": [{"include-group": "c"}], "c": [{"include-group": "b"}]}
    _, warnings = _flatten_group(groups, "a")

    assert warnings == ["pyproject.toml: [dependency-groups] has an include-group cycle: b -> c -> b"]



def test_flatten_group_cycle_uses_canonical_names() -> None:
    groups = {"My_Group": [{"include-group": "my-group"}]}
    _, warnings = _flatten_group(groups, "My_Group")

    assert warnings == ["pyproject.toml: [dependency-groups] has an include-group cycle: my-group -> my-group"]



def test_flatten_group_no_cycle_adds_no_warning() -> None:
    groups = {"a": [{"include-group": "b"}, {"include-group": "b"}], "b": ["y"]}
    result, warnings = _flatten_group(groups, "a")

    assert result == ["y", "y"]
    assert warnings == []



def test_flatten_group_follows_a_chain_up_to_the_depth_limit() -> None:
    result, warnings = _flatten_group(chain_of_groups(100), "g0")

    assert result == ["numpy>=1"]
    assert warnings == []



def test_flatten_group_rejects_a_chain_deeper_than_the_limit() -> None:
    with pytest.raises(
        MetadataError, match=r"^p.toml: \[dependency-groups\] include-group entries are nested more than 100 levels deep"
    ):
        _flatten_group(chain_of_groups(101), "g0", pyproject_path="p.toml")



def test_flatten_group_rejects_a_chain_longer_than_the_recursion_limit() -> None:
    with pytest.raises(MetadataError, match="nested more than 100 levels deep"):
        _flatten_group(chain_of_groups(5000), "g0")



def test_flatten_group_expands_a_diamond_within_the_budget() -> None:
    result, warnings = _flatten_group(diamond_of_groups(10), "g0")

    assert result == ["numpy>=1"] * 1024
    assert warnings == []



def test_flatten_group_rejects_an_exponential_expansion() -> None:
    with pytest.raises(
        MetadataError, match=r"^p.toml: \[dependency-groups\] include-group entries expand more than 10000 groups in total"
    ):
        _flatten_group(diamond_of_groups(25), "g0", pyproject_path="p.toml")



def test_flatten_group_shares_the_budget_between_the_included_groups() -> None:
    budget = [3]

    with pytest.raises(MetadataError, match="expand more than"):
        _flatten_group(chain_of_groups(5), "g0", budget=budget)

    assert budget == [-1]



def test_candidate_requirements_reports_a_cycle_once() -> None:
    data = {
        "dependency-groups": {
            "a": [{"include-group": "b"}, "x"],
            "b": [{"include-group": "a"}, "y"],
        }
    }
    _, warnings = _candidate_requirements(data, "p.toml")

    assert warnings == ["p.toml: [dependency-groups] has an include-group cycle: a -> b -> a"]



def test_dependency_include_group_cycle_adds_a_warning(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [dependency-groups]
        a = [{include-group = "b"}, "x>=1"]
        b = [{include-group = "a"}, "y>=2"]
        """,
    )
    result, warnings = extract_dependency_specifiers(
        load_pyproject(str(path)), ["x", "y"], str(path))

    assert result == {"x": ">=1", "y": ">=2"}
    assert warnings == [f"{path}: [dependency-groups] has an include-group cycle: a -> b -> a"]



def test_dependency_include_group_cycle_does_not_warn_when_nothing_is_requested(
    tmp_path: Path,
) -> None:
    path = write_pyproject(tmp_path, '[dependency-groups]\na = [{include-group = "a"}]\n')
    result, warnings = extract_dependency_specifiers(load_pyproject(str(path)), [], str(path))

    assert result == {}
    assert warnings == []



def test_flatten_group_missing_include_group_adds_a_warning() -> None:
    result, warnings = _flatten_group(
        {"dev": [{"include-group": "tset"}, "x"]}, "dev", pyproject_path="p.toml")

    assert result == ["x"]
    assert warnings == ["p.toml: [dependency-groups].dev: include-group 'tset' does not match any group"]



def test_flatten_group_include_group_matches_any_pep_503_spelling_without_warning() -> None:
    result, warnings = _flatten_group(
        {"a": [{"include-group": "My-Group"}], "my_group": ["y"]}, "a")

    assert result == ["y"]
    assert warnings == []



def test_flatten_group_missing_include_group_is_reported_once_per_group() -> None:
    groups = {"a": [{"include-group": "nope"}], "b": [{"include-group": "a"}]}
    _, warnings = _candidate_requirements({"dependency-groups": groups}, "p.toml")

    assert warnings == ["p.toml: [dependency-groups].a: include-group 'nope' does not match any group"]



def test_dependency_missing_include_group_adds_a_warning(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [dependency-groups]
        dev = [{include-group = "tset"}, "x>=1"]
        """,
    )
    result, warnings = extract_dependency_specifiers(load_pyproject(str(path)), ["x"], str(path))

    assert result == {"x": ">=1"}
    assert warnings == [
        f"{path}: [dependency-groups].dev: include-group 'tset' does not match any group"
    ]



def test_dependency_missing_include_group_does_not_warn_when_nothing_is_requested(
    tmp_path: Path,
) -> None:
    path = write_pyproject(tmp_path, '[dependency-groups]\ndev = [{include-group = "tset"}]\n')
    _, warnings = extract_dependency_specifiers(load_pyproject(str(path)), [], str(path))

    assert warnings == []



def test_dependency_different_markers_do_not_warn(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, MARKERS_TOML)
    result, warnings = extract_dependency_specifiers(
        load_pyproject(str(path)), ["numpy"], str(path))

    assert result == {"numpy": ">=1.20"}
    assert warnings == []



def test_dependency_same_marker_different_specifiers_warns_with_the_marker(
    tmp_path: Path,
) -> None:
    path = write_pyproject(tmp_path, MARKERS_TOML)
    result, warnings = extract_dependency_specifiers(
        load_pyproject(str(path)), ["same"], str(path))

    assert result == {"same": ">=1"}
    assert warnings == [
        f"same has different specifiers for marker 'sys_platform == \"linux\"' in {path}: "
        "['>=1', '>=2']; using '>=1'"
    ]



def test_dependency_marker_and_no_marker_do_not_warn(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, MARKERS_TOML)
    result, warnings = extract_dependency_specifiers(
        load_pyproject(str(path)), ["mixed"], str(path))

    assert result == {"mixed": ">=1"}
    assert warnings == []



def test_dependency_same_specifier_with_different_markers_does_not_warn(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\ndependencies = ["a>=1; os_name == \'nt\'", "a>=1; os_name == \'posix\'"]\n',
    )
    _, warnings = extract_dependency_specifiers(load_pyproject(str(path)), ["a"], str(path))

    assert warnings == []



def test_dependency_one_warning_per_conflicting_marker(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [project]
        dependencies = [
            "a>=1; os_name == 'nt'", "a>=2; os_name == 'nt'",
            "a>=3", "a>=4",
        ]
        """,
    )
    _, warnings = extract_dependency_specifiers(load_pyproject(str(path)), ["a"], str(path))

    assert warnings == [
        f"a has different specifiers for marker 'os_name == \"nt\"' in {path}: "
        "['>=1', '>=2']; using '>=1'",
        f"a has different specifiers in {path}: ['>=3', '>=4']; using '>=1'",
    ]



@pytest.mark.parametrize(
    ("matches", "expected"),
    [
        ([("==1", None)], []),
        ([("==1", None), ("==1", None)], []),
        ([("==1", "os_name == 'nt'"), ("==2", "os_name == 'posix'")], []),
        ([("==1", None), ("==2", "os_name == 'nt'")], []),
        ([("==1", None), ("==2", None)], ["a has different specifiers in p.toml: ['==1', '==2']; using '==1'"]),
        ([("==2", None), ("==1", None), ("==2", None)], ["a has different specifiers in p.toml: ['==1', '==2']; using '==2'"]),
    ],
)
def test_conflict_warnings(matches: list[tuple[str, str | None]], expected: list[str]) -> None:
    assert _conflict_warnings("a", matches, matches[0][0], "p.toml") == expected



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
        ('b = []\nA = []\nc = []', ["A", "b", "c"]),
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



def test_extra_names_without_optional_dependencies() -> None:
    assert _extra_names({}, ["all"], "p.toml") == ["all"]



def test_extra_names_optional_dependencies_must_be_a_table() -> None:
    with pytest.raises(MetadataError, match=r"^p.toml: \[project\].optional-dependencies must be a table"):
        _extra_names({"optional-dependencies": []}, [], "p.toml")



def test_group_names() -> None:
    data = {"dependency-groups": {"test": [], "Dev_Tools": [], "dev-tools": [], "docs": []}}

    assert _group_names(data, "p.toml") == ["Dev_Tools", "docs", "test"]



def test_group_names_without_groups() -> None:
    assert _group_names({}, "p.toml") == []



def test_group_names_must_be_a_table() -> None:
    with pytest.raises(MetadataError, match=r"^p.toml: \[dependency-groups\] must be a table"):
        _group_names({"dependency-groups": []}, "p.toml")



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



def test_dependency_dynamic_dependencies_adds_a_warning() -> None:
    data = {"project": {"name": "a", "dynamic": ["dependencies"]}}

    result, warnings = extract_dependency_specifiers(data, ["numpy"], "p.toml")

    assert result == {"numpy": None}
    assert warnings == [
        "p.toml: [project].dependencies is dynamic, it cannot be read, so no requirement is found in it"
    ]



def test_dependency_dynamic_fields_add_one_warning_each() -> None:
    data = {"project": {"dynamic": ["dependencies", "optional-dependencies"]}}

    _, warnings = extract_dependency_specifiers(data, ["numpy"], "p.toml")

    assert warnings == [
        "p.toml: [project].dependencies is dynamic, it cannot be read, so no requirement is found in it",
        "p.toml: [project].optional-dependencies is dynamic, it cannot be read, so no requirement is found in it",
    ]



def test_dependency_dynamic_dependencies_does_not_warn_when_nothing_is_requested() -> None:
    data = {"project": {"dynamic": ["dependencies"]}}

    assert extract_dependency_specifiers(data, [], "p.toml") == ({}, [])



def test_dependency_static_value_wins_over_dynamic_without_warning() -> None:
    data = {"project": {"dynamic": ["dependencies"], "dependencies": ["numpy>=1"]}}

    assert extract_dependency_specifiers(data, ["numpy"], "p.toml") == ({"numpy": ">=1"}, [])



def test_parse_requirement_valid() -> None:
    requirement = extract_metadata_module._parse_requirement("Foo_Bar[x]>=1; python_version<'3.12'")

    assert isinstance(requirement, Requirement)
    assert (requirement.name, str(requirement.specifier)) == ("Foo_Bar", ">=1")



def test_parse_requirement_invalid_is_returned_not_raised() -> None:
    error = extract_metadata_module._parse_requirement("bad requirement!!")

    assert isinstance(error, InvalidRequirement)



def test_parse_requirement_is_called_once_per_distinct_string() -> None:
    parse = extract_metadata_module._parse_requirement
    parse.cache_clear()

    assert parse("numpy>=1") is parse("numpy>=1")
    assert parse("bad!!") is parse("bad!!")
    assert parse.cache_info().misses == 2



def test_index_dependencies() -> None:
    found, warnings = _index_dependencies(DATA_WITH_REQUIREMENTS, "p.toml")

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
        "Ignoring invalid requirement 'not valid!' in p.toml: "
        + str(_parse_error("not valid!")),
    ]



def test_index_dependencies_empty() -> None:
    assert _index_dependencies({}, "p.toml") == ({}, [])



def test_index_dependencies_wrong_type() -> None:
    with pytest.raises(MetadataError, match=r"^p.toml: \[project\].dependencies must be an array"):
        _index_dependencies({"project": {"dependencies": "numpy"}}, "p.toml")



def test_specifiers_from_index() -> None:
    found = {"numpy": [(">=1", None), ("<2", None)], "tqdm": [("", None)]}

    assert _specifiers_from_index(found, ["warning"], ["Numpy", "tqdm", "other"], "p.toml") == (
        {"Numpy": ">=1", "tqdm": "", "other": None},
        ["warning", "Numpy has different specifiers in p.toml: ['<2', '>=1']; using '>=1'"],
    )



def test_specifiers_from_index_without_dependencies_ignores_the_index_warnings() -> None:
    assert _specifiers_from_index({}, ["warning"], [], "p.toml") == ({}, [])



def test_requirements_from_index() -> None:
    found = {"numpy": [(">=1", "python_version < '3.12'"), ("", None)]}

    assert _requirements_from_index(found, ["NumPy", "other"]) == {
        "NumPy": [
            {"specifier": ">=1", "marker": "python_version < '3.12'"},
            {"specifier": "", "marker": ""},
        ],
        "other": [],
    }



@pytest.mark.parametrize(
    "raw",
    [
        "[]",
        '["numpy", "NumPy"]',
        '["numpy@project"]',
        '["numpy@extra:x", "numpy@group:dev"]',
        '["a@extra:with:colon", "a@group:Dev_Tools"]',
    ],
)
def test_parse_dependencies(raw: str) -> None:
    assert parse_dependencies(raw) == json.loads(raw)



@pytest.mark.parametrize(
    "entry",
    ["numpy@dev", "numpy@", "numpy@extra", "numpy@extra:", "numpy@group:", "numpy@Project", "numpy@feature:x", "numpy@@project"],
)
def test_parse_dependencies_invalid_scope(entry: str) -> None:
    with pytest.raises(MetadataError, match=rf"^dependencies entry {re.escape(repr(entry))} has an invalid scope: "):
        parse_dependencies(json.dumps([entry]))



@pytest.mark.parametrize("raw", ["not json", '{"a": 1}', "[1]"])
def test_parse_dependencies_not_an_array_of_strings(raw: str) -> None:
    with pytest.raises(MetadataError, match=r"^dependencies (is not valid JSON|must be a JSON array of strings)"):
        parse_dependencies(raw)



@pytest.mark.parametrize(
    ("dependency", "expected"),
    [
        ("numpy", "numpy"),
        ("Foo_Bar", "foo-bar"),
        ("Foo.Bar@project", "foo-bar@project"),
        ("numpy@extra:Dev_Tools", "numpy@extra:dev-tools"),
        ("numpy@group:Dev..Tools", "numpy@group:dev-tools"),
    ],
)
def test_lookup_key(dependency: str, expected: str) -> None:
    assert _lookup_key(dependency) == expected



@pytest.mark.parametrize(
    ("dependencies", "expected"),
    [
        ('["numpy"]', {"numpy": ">=1.20"}),
        ('["numpy@project"]', {"numpy@project": ">=1.20"}),
        ('["numpy@extra:fast"]', {"numpy@extra:fast": ">=2"}),
        ('["numpy@extra:Fast"]', {"numpy@extra:Fast": ">=2"}),
        ('["numpy@extra:slow"]', {"numpy@extra:slow": "<2"}),
        ('["NumPy@group:dev"]', {"NumPy@group:dev": ">=1.26"}),
        ('["ruff@group:dev", "ruff@group:lint"]', {"ruff@group:dev": ">=0.5", "ruff@group:lint": ">=0.5"}),
        ('["ujson@project", "ujson@extra:fast", "ujson@group:dev"]', {"ujson@project": None, "ujson@extra:fast": "", "ujson@group:dev": None}),
        ('["tqdm@extra:fast"]', {"tqdm@extra:fast": None}),
        ('["numpy@extra:missing", "numpy@group:missing"]', {"numpy@extra:missing": None, "numpy@group:missing": None}),
    ],
)
def test_dependency_specifiers_with_a_scope(
    tmp_path: Path, dependencies: str, expected: dict
) -> None:
    path = write_pyproject(tmp_path, DATA_WITH_SCOPES)

    assert specifiers(path, dependencies) == expected



def test_extract_project_dependencies() -> None:
    data = {"project": {"dependencies": ["numpy>=1.20,<3", "Foo_Bar", "tqdm[extra]~=4.0"]}}

    assert extract_project_dependencies(data) == (
        {"numpy": "<3,>=1.20", "Foo_Bar": "", "tqdm": "~=4.0"},
        [],
    )



@pytest.mark.parametrize(
    "data", [{}, {"project": {}}, {"project": {"dependencies": []}}, {"project": {"name": "a"}}]
)
def test_extract_project_dependencies_empty(data: dict) -> None:
    assert extract_project_dependencies(data) == ({}, [])



def test_extract_project_dependencies_ignores_extras_and_groups() -> None:
    data = {
        "project": {"dependencies": ["a"], "optional-dependencies": {"x": ["b"]}},
        "dependency-groups": {"dev": ["c"]},
    }

    assert extract_project_dependencies(data) == ({"a": ""}, [])



def test_extract_project_dependencies_first_requirement_wins() -> None:
    data = {
        "project": {
            "dependencies": [
                "numpy>=1.20; python_version < '3.12'",
                "numpy>=1.26; python_version >= '3.12'",
            ]
        }
    }

    assert extract_project_dependencies(data) == ({"numpy": ">=1.20"}, [])



def test_extract_project_dependencies_keeps_the_first_spelling_of_the_name() -> None:
    data = {"project": {"dependencies": ["Zope_Interface>=5", "zope.interface>=6"]}}

    result, warnings = extract_project_dependencies(data, "p.toml")

    assert result == {"Zope_Interface": ">=5"}
    assert warnings == [
        "Zope_Interface has different specifiers in p.toml: ['>=5', '>=6']; using '>=5'"
    ]



def test_extract_project_dependencies_non_string_entry() -> None:
    with pytest.raises(
        MetadataError, match=r"p\.toml: \[project\]\.dependencies must contain only strings, got: 1"
    ):
        extract_project_dependencies({"project": {"dependencies": ["a", 1]}}, "p.toml")



def test_extract_project_dependencies_invalid_requirement_warns() -> None:
    result, warnings = extract_project_dependencies(
        {"project": {"dependencies": ["good>=1", "bad requirement!!"]}}, "p.toml"
    )

    assert result == {"good": ">=1"}
    assert len(warnings) == 1
    assert warnings[0].startswith("Ignoring invalid requirement 'bad requirement!!' in p.toml: ")



def test_extract_project_dependencies_dynamic_dependencies_warns() -> None:
    data = {"project": {"dynamic": ["dependencies"]}}

    assert extract_project_dependencies(data, "p.toml") == (
        {},
        ["p.toml: [project].dependencies is dynamic, it cannot be read, so no requirement is found in it"],
    )



@pytest.mark.parametrize(
    ("data", "match"),
    [
        ({"project": 1}, r"\[project\] must be a table"),
        ({"project": {"dependencies": "a"}}, r"\[project\]\.dependencies must be an array"),
    ],
)
def test_extract_project_dependencies_wrong_type(data: dict, match: str) -> None:
    with pytest.raises(MetadataError, match=match):
        extract_project_dependencies(data)



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



def test_script_requirements_list_the_dependencies_of_the_script() -> None:
    requirements = (Path(__file__).resolve().parents[1] / "scripts" / "requirements.txt").read_text(
        encoding="utf-8"
    )
    lines = [line for line in requirements.splitlines() if line and not line.startswith("#")]

    assert lines == ["packaging>=23.0,<27"]



def test_test_requirements_include_the_script_requirements() -> None:
    requirements = (Path(__file__).resolve().parents[1] / "requirements-test.txt").read_text(
        encoding="utf-8"
    )

    assert "-r scripts/requirements.txt" in requirements.splitlines()



def test_extract_dependency_requirements_lists_every_requirement_with_its_marker(
    tmp_path: Path,
) -> None:
    path = write_pyproject(
        tmp_path,
        "[project]\n"
        'dependencies = ["numpy>=1.20; python_version < \'3.12\'", '
        '"numpy>=1.26; python_version >= \'3.12\'", "Foo_Bar"]\n\n'
        '[project.optional-dependencies]\nx = ["numpy<3"]\n\n'
        '[dependency-groups]\ndev = ["numpy>=2"]\n',
    )

    result = extract_dependency_requirements(
        load_pyproject(str(path)), ["numpy", "foo.bar"], str(path)
    )

    assert result == {
        "numpy": [
            {"specifier": ">=1.20", "marker": 'python_version < "3.12"'},
            {"specifier": ">=1.26", "marker": 'python_version >= "3.12"'},
            {"specifier": "<3", "marker": ""},
            {"specifier": ">=2", "marker": ""},
        ],
        "foo.bar": [{"specifier": "", "marker": ""}],
    }



def test_extract_dependency_requirements_not_found_is_an_empty_list() -> None:
    data = {"project": {"dependencies": ["numpy"]}}

    assert extract_dependency_requirements(data, ["missing"]) == {"missing": []}



def test_extract_dependency_requirements_without_dependencies_is_empty() -> None:
    assert extract_dependency_requirements({"project": {"dependencies": ["numpy"]}}, []) == {}



def test_extract_dependency_requirements_ignores_invalid_requirements() -> None:
    data = {"project": {"dependencies": ["not a requirement!!", "numpy>=1"]}}

    assert extract_dependency_requirements(data, ["numpy"]) == {
        "numpy": [{"specifier": ">=1", "marker": ""}]
    }



def test_extract_dependency_requirements_keeps_duplicates() -> None:
    data = {"project": {"dependencies": ["numpy>=1", "numpy>=1"]}}

    assert extract_dependency_requirements(data, ["numpy"]) == {
        "numpy": [{"specifier": ">=1", "marker": ""}, {"specifier": ">=1", "marker": ""}]
    }



def test_extract_dependency_requirements_wrong_type() -> None:
    with pytest.raises(MetadataError, match=r"custom.toml: \[project\].dependencies must be an array"):
        extract_dependency_requirements({"project": {"dependencies": 1}}, ["numpy"], "custom.toml")
