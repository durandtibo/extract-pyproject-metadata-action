"""Tests of ``extract_pyproject_metadata.requirements``: the requirements, the
include-group expansion and the lookup of the requested dependencies."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.inputs import parse_dependencies
from extract_pyproject_metadata.pyproject import load_pyproject, read_groups
from extract_pyproject_metadata.requirements import (
    _Expansion,
    collect_requirements,
    lookup_dependencies,
)
from extract_pyproject_metadata.types import Lookup, ReportWarning, Requirement
from tests.helpers import (
    DATA_WITH_REQUIREMENTS,
    DATA_WITH_SCOPES,
    DEPS_TOML,
    GROUPS_TOML,
    INVALID_TOML,
    MARKERS_TOML,
    chain_of_groups,
    diamond_of_groups,
    dynamic_fields,
    extract,
    extract_dependency_requirements,
    extract_dependency_specifiers,
    messages,
    parse_error,
    specifiers,
    write_pyproject,
)

if TYPE_CHECKING:
    from pathlib import Path


def collect(data: dict) -> tuple[list[Requirement], list[str]]:
    """Collect the requirements of parsed data."""
    return collect_requirements(data, dynamic_fields(data))


def spelled(requirements: list[Requirement]) -> list[str]:
    """The name and specifier of each requirement."""
    return [f"{req.name}{req.specifier}" for req in requirements]


def placed(requirements: list[Requirement]) -> list[tuple[str, str]]:
    """The source and the name and specifier of each requirement."""
    return [(req.source, f"{req.name}{req.specifier}") for req in requirements]


def flatten(groups: dict, name: str) -> tuple[list[str], list[ReportWarning]]:
    """Expand a group of a ``[dependency-groups]`` table alone."""
    expansion = _Expansion(read_groups(groups))
    requirements = expansion.expand(name)
    return requirements, list(expansion.warnings)


MISSING_X = "[dependency-groups].a: include-group 'missing' does not match any group"


@pytest.mark.parametrize(
    ("groups", "name", "expected", "warnings"),
    [
        ({"a": ["x>=1"]}, "a", ["x>=1"], []),
        ({"a": []}, "a", [], []),
        ({}, "a", [], []),
        ({"a": ["x"]}, "missing", [], []),
        ({"My_Group": ["x"]}, "my-group", ["x"], []),
        ({"a": [{"include-group": "b"}, "x"], "b": ["y"]}, "a", ["y", "x"], []),
        ({"a": [{"include-group": "B-C"}], "b_c": ["y"]}, "a", ["y"], []),
        ({"a": [{"include-group": "My-Group"}], "my_group": ["y"]}, "a", ["y"], []),
        (
            {"a": [{"include-group": "b"}], "b": [{"include-group": "c"}], "c": ["z"]},
            "a",
            ["z"],
            [],
        ),
        ({"a": [{"include-group": "b"}, {"include-group": "b"}], "b": ["y"]}, "a", ["y", "y"], []),
        ({"a": [{"include-group": "missing"}, "x"]}, "a", ["x"], [MISSING_X]),
        (
            {"dev": [{"include-group": "tset"}, "x"]},
            "dev",
            ["x"],
            ["[dependency-groups].dev: include-group 'tset' does not match any group"],
        ),
        (
            {"a": [{"include-group": "b"}, "x"], "b": [{"include-group": "a"}, "y"]},
            "a",
            ["y", "x"],
            ["[dependency-groups] has an include-group cycle: a -> b -> a"],
        ),
        (
            {"a": [{"include-group": "a"}, "x"]},
            "a",
            ["x"],
            ["[dependency-groups] has an include-group cycle: a -> a"],
        ),
        (
            {
                "a": [{"include-group": "b"}],
                "b": [{"include-group": "c"}, "y"],
                "c": [{"include-group": "a"}, "z"],
            },
            "a",
            ["z", "y"],
            ["[dependency-groups] has an include-group cycle: a -> b -> c -> a"],
        ),
    ],
    ids=[
        "one-group",
        "empty-group",
        "no-table",
        "unknown-name",
        "normalized-name",
        "include",
        "include-normalized",
        "include-spelling",
        "chain",
        "repeated-include",
        "missing-include-group",
        "unknown-group-with-a-typo",
        "cycle",
        "self-include",
        "long-cycle",
    ],
)
def test_flatten(groups: dict, name: str, expected: list[str], warnings: list[str]) -> None:
    result, found = flatten(groups, name)

    assert result == expected
    assert messages(found) == warnings


@pytest.mark.parametrize(
    "entry",
    [{"include_group": "b"}, {}, {"include-group": "b", "extra": 1}, 1, None, ["x"], 1.5],
)
def test_expansion_flatten_unknown_entry(entry: object) -> None:
    with pytest.raises(
        MetadataError,
        match=r"\[dependency-groups\]\.a: entries must be strings or "
        r"\{'include-group': <name>\} tables, got: ",
    ):
        flatten({"a": ["x", entry], "b": ["y"]}, "a")


@pytest.mark.parametrize(
    ("groups", "name", "match"),
    [
        ({"a": "x"}, "a", r"\[dependency-groups\]\.a: must be an array"),
        (
            {"a": [{"include-group": "b"}], "b": [{"typo": 1}]},
            "a",
            r"\[dependency-groups\]\.b: entries must be",
        ),
        (
            {"a": [{"include-group": ["b"]}]},
            "a",
            r"\.a: include-group must be a string, got: \['b'\]",
        ),
        ({"Dev": ["a"], "dev": [1]}, "DEV", r"^\[dependency-groups\]\.dev: entries must be"),
    ],
    ids=[
        "not-an-array",
        "bad-entry-in-an-included-group",
        "bad-include-group",
        "spelling-in-error",
    ],
)
def test_expansion_flatten_invalid_groups(groups: dict, name: str, match: str) -> None:
    with pytest.raises(MetadataError, match=match):
        flatten(groups, name)


@pytest.mark.parametrize(
    ("groups", "name", "expected"),
    [
        (
            {
                "c": [{"include-group": "a"}],
                "a": [{"include-group": "b"}],
                "b": [{"include-group": "c"}],
            },
            "b",
            "a -> b -> c -> a",
        ),
        (
            {
                "a": [{"include-group": "b"}],
                "b": [{"include-group": "c"}],
                "c": [{"include-group": "b"}],
            },
            "a",
            "b -> c -> b",
        ),
        ({"My_Group": [{"include-group": "my-group"}]}, "My_Group", "my-group -> my-group"),
    ],
    ids=["starts-at-the-smallest-group", "not-the-path-leading-to-it", "canonical-names"],
)
def test_expansion_flatten_cycle_message(groups: dict, name: str, expected: str) -> None:
    _, warnings = flatten(groups, name)

    assert messages(warnings) == [f"[dependency-groups] has an include-group cycle: {expected}"]


def test_expansion_flatten_follows_a_chain_up_to_the_depth_limit() -> None:
    result, warnings = flatten(chain_of_groups(100), "g0")

    assert result == ["numpy>=1"]
    assert messages(warnings) == []


def test_expansion_flatten_rejects_a_chain_deeper_than_the_limit() -> None:
    with pytest.raises(
        MetadataError,
        match=r"^\[dependency-groups\]: include-group entries are nested more than 100 levels deep",
    ):
        flatten(chain_of_groups(101), "g0")


def test_expansion_flatten_rejects_a_chain_longer_than_the_recursion_limit() -> None:
    with pytest.raises(MetadataError, match="nested more than 100 levels deep"):
        flatten(chain_of_groups(5000), "g0")


def test_expansion_flatten_expands_a_diamond_within_the_budget() -> None:
    result, warnings = flatten(diamond_of_groups(10), "g0")

    assert result == ["numpy>=1"] * 1024
    assert messages(warnings) == []


def test_expansion_flatten_rejects_an_exponential_expansion() -> None:
    with pytest.raises(
        MetadataError,
        match=r"^\[dependency-groups\]: include-group entries expand more than 10000 groups in total",
    ):
        flatten(diamond_of_groups(25), "g0")


def test_expansion_shares_the_budget_between_the_included_groups() -> None:
    expansion = _Expansion(read_groups(chain_of_groups(5)), budget=3)

    with pytest.raises(MetadataError, match="expand more than"):
        expansion.expand("g0")

    assert expansion.budget == -1


def test_expansion_reads_the_groups_by_normalized_name() -> None:
    expansion = _Expansion(read_groups({"Dev": ["a"], "dev": ["b"], "Other_Group": ["c"]}))

    assert expansion.expand("DEV") == ["a", "b"]
    assert expansion.expand("other-group") == ["c"]
    assert expansion.expand("missing") == []


def test_expansion_flatten_expands_every_spelling_of_the_group() -> None:
    groups = {"Dev": ["a", {"include-group": "x_y"}], "dev": ["b"], "X.Y": ["c"]}

    assert flatten(groups, "dev")[0] == ["a", "c", "b"]


def test_expansion_flatten_missing_include_group_is_reported_once_per_group() -> None:
    groups = {"a": [{"include-group": "nope"}], "b": [{"include-group": "a"}]}
    _, warnings = collect({"dependency-groups": groups})

    assert messages(warnings) == [
        "[dependency-groups].a: include-group 'nope' does not match any group"
    ]


HEADER = '[project]\nname = "p"\nversion = "1"\n'


@pytest.mark.parametrize(
    ("toml", "expected"),
    [
        (GROUPS_TOML, ["Dev", "docs", "test"]),
        (HEADER, []),
        (HEADER + "[dependency-groups]\n", []),
        (HEADER + '[dependency-groups]\nFoo_Bar = []\n"foo-bar" = []', ["Foo_Bar"]),
        (HEADER + '[dependency-groups]\n"foo-bar" = []\nFoo_Bar = []', ["foo-bar"]),
        (HEADER + "[dependency-groups]\nb = []\nA = []\nc = []", ["A", "b", "c"]),
    ],
    ids=["sorted", "no-table", "empty-table", "first-spelling", "first-spelling-reversed", "case"],
)
def test_extract_metadata_groups(tmp_path: Path, toml: str, expected: list[str]) -> None:
    path = write_pyproject(tmp_path, toml)

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


@pytest.mark.parametrize(
    ("data", "match"),
    [
        ({"project": 1}, r"\[project\]: must be a table"),
        ({"project": {"dependencies": "a"}}, r"\[project\]\.dependencies: must be an array"),
        ({"project": {"optional-dependencies": 1}}, r"optional-dependencies: must be a table"),
        (
            {"project": {"optional-dependencies": {"x": 1}}},
            r"optional-dependencies\]\.x: must be an array",
        ),
        ({"dependency-groups": 1}, r"\[dependency-groups\]: must be a table"),
        (
            {"project": {"dependencies": ["a", 1]}},
            r"\[project\]\.dependencies: must contain only strings, got: 1",
        ),
        (
            {"project": {"dependencies": [None]}},
            r"\[project\]\.dependencies: must contain only strings, got: None",
        ),
        (
            {"project": {"optional-dependencies": {"x": ["c", {"b": 1}]}}},
            r"\[project\.optional-dependencies\]\.x: must contain only strings, got: \{'b': 1\}",
        ),
    ],
)
def test_collect_requirements_wrong_types(data: dict, match: str) -> None:
    with pytest.raises(MetadataError, match=match):
        collect(data)


def test_collect_requirements_reports_a_cycle_once() -> None:
    data = {
        "dependency-groups": {
            "a": [{"include-group": "b"}, "x"],
            "b": [{"include-group": "a"}, "y"],
        }
    }
    _, warnings = collect(data)

    assert messages(warnings) == ["[dependency-groups] has an include-group cycle: a -> b -> a"]


@pytest.mark.parametrize(
    ("data", "fields"),
    [
        ({}, []),
        ({"project": {}}, []),
        ({"project": {"dynamic": ["version"]}}, []),
        ({"project": {"dynamic": ["dependencies"]}}, ["dependencies"]),
        # optional-dependencies is checked by read_project, not here.
        ({"project": {"dynamic": ["optional-dependencies"]}}, []),
        ({"project": {"dynamic": ["optional-dependencies", "dependencies"]}}, ["dependencies"]),
    ],
)
def test_collect_requirements_warns_about_the_dynamic_fields(data: dict, fields: list[str]) -> None:
    assert collect(data)[1] == [
        ReportWarning(
            "dynamic-field",
            f"[project].{field} is dynamic, the action cannot read it: "
            "no requirement is found in it",
        )
        for field in fields
    ]


def test_collect_requirements_parses_a_requirement() -> None:
    data = {"project": {"dependencies": ["Foo_Bar[x]>=1; python_version<'3.12'"]}}

    assert collect(data)[0] == [
        Requirement(
            name="foo-bar", specifier=">=1", marker='python_version < "3.12"', source="project"
        )
    ]


def test_collect_requirements_skips_an_invalid_requirement_with_a_warning() -> None:
    requirements, warnings = collect({"project": {"dependencies": ["oops==", "a"]}})

    assert spelled(requirements) == ["a"]
    assert len(warnings) == 1
    assert warnings[0].message.startswith("Ignoring invalid requirement 'oops==': ")


def test_collect_requirements_of_the_file() -> None:
    requirements, warnings = collect(DATA_WITH_REQUIREMENTS)

    assert requirements == [
        Requirement("numpy", ">=1.20", 'python_version < "3.12"', "project"),
        Requirement("tqdm", "", "", "project"),
        Requirement("numpy", ">=1.26", 'python_version >= "3.12"', "extra:x"),
        Requirement("pytest", "", "", "group:dev"),
    ]
    assert messages(warnings) == [
        "[dependency-groups].dev: include-group 'missing' does not match any group",
        "Ignoring invalid requirement 'not valid!': " + str(parse_error("not valid!")),
    ]


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


def test_dependency_no_duplicate_adds_no_warning(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    _, warnings = extract_dependency_specifiers(load_pyproject(str(path)), ["nospec"])

    assert messages(warnings) == []


def test_dependency_invalid_requirements_add_warnings(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, INVALID_TOML)
    result, warnings = extract_dependency_specifiers(
        load_pyproject(str(path)), ["good", "dev-pkg", "missing"]
    )

    assert result == {"good": ">=1", "dev-pkg": ">=2", "missing": None}
    assert len(warnings) == 4
    assert warnings[0].message.startswith("Ignoring invalid requirement 'bad requirement!!': ")
    assert warnings[1].message.startswith("Ignoring invalid requirement 'also bad>>': ")
    assert warnings[2].message.startswith("Ignoring invalid requirement 'oops==': ")
    assert warnings[3] == ReportWarning("dependency-not-found", "dependency 'missing' not found")


@pytest.mark.parametrize("value", ["nope", '{"a": 1}', "[1]"])
def test_dependency_invalid_input(tmp_path: Path, value: str) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    with pytest.raises(MetadataError):
        specifiers(path, value)


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
        (
            '[project]\ndependencies = "numpy"',
            r"\[project\]\.dependencies: must be an array, got: 'numpy'",
        ),
        ("[project]\ndependencies = 1", r"\[project\]\.dependencies: must be an array, got: 1"),
        (
            '[project.optional-dependencies]\nx = "numpy"',
            r"\[project\.optional-dependencies\]\.x: must be an array, got: 'numpy'",
        ),
        (
            "[project.optional-dependencies]\nx = 1",
            r"\[project\.optional-dependencies\]\.x: must be an array, got: 1",
        ),
        (
            "[project]\noptional-dependencies = []",
            r"\[project\]\.optional-dependencies: must be a table",
        ),
        ("dependency-groups = []", r"\[dependency-groups\]: must be a table, got: \[\]"),
        ('dependency-groups = ["dev"]', r"\[dependency-groups\]: must be a table, got: \['dev'\]"),
        ("dependency-groups = 1", r"\[dependency-groups\]: must be a table, got: 1"),
        (
            '[project]\noptional-dependencies = "numpy"',
            r"\[project\]\.optional-dependencies: must be a table, got: 'numpy'",
        ),
        ('dependency-groups = "dev"', r"\[dependency-groups\]: must be a table, got: 'dev'"),
        (
            '[dependency-groups]\ndev = "numpy"',
            r"\[dependency-groups\]\.dev: must be an array, got: 'numpy'",
        ),
        ("[dependency-groups]\ndev = 1", r"\[dependency-groups\]\.dev: must be an array, got: 1"),
        (
            "[dependency-groups]\ndev = [{include-group = 1}]",
            r"\[dependency-groups\]\.dev: include-group must be a string, got: 1",
        ),
        (
            '[dependency-groups]\na = [{include-group = "b"}]\nb = "x"',
            r"\[dependency-groups\]\.b: must be an array, got: 'x'",
        ),
        ("project = 1", r"\[project\]: must be a table, got: 1"),
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

    with pytest.raises(MetadataError, match=r"\[project\]\.dependencies: must be an array"):
        specifiers(path, "[]")


@pytest.mark.parametrize(
    ("toml", "result", "warnings"),
    [
        (
            '[dependency-groups]\nbase = ["x>=1"]\ndev = [{include-group = "base"}]\n',
            {"x": ">=1"},
            [],
        ),
        (
            (
                '[dependency-groups]\na = [{include-group = "b"}, "x>=1"]\nb = [{include-group = "a"}, "y>=2"]\n'
            ),
            {"x": ">=1", "y": ">=2"},
            ["[dependency-groups] has an include-group cycle: a -> b -> a"],
        ),
        (
            '[dependency-groups]\ndev = [{include-group = "tset"}, "x>=1"]\n',
            {"x": ">=1"},
            ["[dependency-groups].dev: include-group 'tset' does not match any group"],
        ),
    ],
    ids=["include", "cycle", "unknown-group"],
)
def test_dependency_include_group_lookups(
    tmp_path: Path, toml: str, result: dict[str, str], warnings: list[str]
) -> None:
    path = write_pyproject(tmp_path, toml)

    found, found_warnings = extract_dependency_specifiers(load_pyproject(str(path)), sorted(result))

    assert found == result
    assert messages(found_warnings) == warnings


@pytest.mark.parametrize(
    "toml",
    [
        INVALID_TOML,
        '[dependency-groups]\na = [{include-group = "a"}]\n',
        '[dependency-groups]\ndev = [{include-group = "tset"}]\n',
    ],
    ids=["invalid-requirement", "include-group-cycle", "unknown-include-group"],
)
def test_the_warnings_of_the_tables_are_not_reported_when_nothing_is_requested(
    tmp_path: Path, toml: str
) -> None:
    path = write_pyproject(tmp_path, toml)
    result, warnings = extract_dependency_specifiers(load_pyproject(str(path)), [])

    assert result == {}
    assert messages(warnings) == []


@pytest.mark.parametrize(
    ("toml", "name", "expected"),
    [
        (MARKERS_TOML, "numpy", ">=1.20"),
        (MARKERS_TOML, "mixed", ">=1"),
        (
            "[project]\ndependencies = [\"a>=1; os_name == 'nt'\", \"a>=1; os_name == 'posix'\"]\n",
            "a",
            ">=1",
        ),
    ],
    ids=["different-markers", "marker-and-no-marker", "same-specifier-different-markers"],
)
def test_dependency_markers_do_not_warn(
    tmp_path: Path, toml: str, name: str, expected: str
) -> None:
    path = write_pyproject(tmp_path, toml)
    result, warnings = extract_dependency_specifiers(load_pyproject(str(path)), [name])

    assert result == {name: expected}
    assert messages(warnings) == []


def test_dependency_dynamic_dependencies_adds_a_warning() -> None:
    data = {"project": {"name": "a", "dynamic": ["dependencies"]}}

    result, warnings = extract_dependency_specifiers(data, ["numpy"])

    assert result == {"numpy": None}
    assert messages(warnings) == [
        (
            "[project].dependencies is dynamic, the action cannot read it: "
            "no requirement is found in it"
        ),
        "dependency 'numpy' not found",
    ]


def test_dependency_dynamic_dependencies_does_not_warn_when_nothing_is_requested() -> None:
    data = {"project": {"dynamic": ["dependencies"]}}

    assert extract_dependency_specifiers(data, []) == ({}, [])


def test_dependency_static_value_wins_over_dynamic_with_a_warning() -> None:
    data = {"project": {"dynamic": ["dependencies"], "dependencies": ["numpy>=1"]}}

    specifiers, warnings = extract_dependency_specifiers(data, ["numpy"])

    assert specifiers == {"numpy": ">=1"}
    assert [w.code for w in warnings] == ["static-and-dynamic"]


REQUIREMENTS = [
    Requirement("numpy", ">=1", "python_version < '3.12'", "project"),
    Requirement("tqdm", "", "", "project"),
    Requirement("numpy", "<3", "", "extra:fast"),
    Requirement("numpy", "", "", "group:dev"),
]


def lookups(*entries: str) -> list[Lookup]:
    """Parse entries of the ``dependencies`` input."""
    return parse_dependencies(json.dumps(list(entries)))


def test_lookup_dependencies() -> None:
    assert lookup_dependencies(
        REQUIREMENTS, lookups("NumPy", "numpy@extra:fast", "numpy@extra:slow", "other")
    ) == (
        {
            "NumPy": [REQUIREMENTS[0], REQUIREMENTS[2], REQUIREMENTS[3]],
            "numpy@extra:fast": [REQUIREMENTS[2]],
            "numpy@extra:slow": [],
            "other": [],
        },
        [
            ReportWarning("dependency-not-found", "dependency 'numpy@extra:slow' not found"),
            ReportWarning("dependency-not-found", "dependency 'other' not found"),
        ],
    )


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ("numpy", [REQUIREMENTS[0], REQUIREMENTS[2], REQUIREMENTS[3]]),
        ("Numpy@project", [REQUIREMENTS[0]]),
        ("numpy@extra:Fast", [REQUIREMENTS[2]]),
        ("numpy@group:dev", [REQUIREMENTS[3]]),
        ("tqdm@group:dev", []),
    ],
)
def test_lookup_dependencies_matches_the_place_of_the_entry(
    entry: str, expected: list[Requirement]
) -> None:
    assert lookup_dependencies(REQUIREMENTS, lookups(entry))[0] == {entry: expected}


def test_lookup_dependencies_keeps_every_match_and_does_not_warn_on_a_conflict() -> None:
    requirements = [
        Requirement("a", "==2", "", "project"),
        Requirement("a", "==1", "", "group:dev"),
    ]

    assert lookup_dependencies(requirements, lookups("a")) == ({"a": requirements}, [])


def test_lookup_dependencies_does_not_mutate_its_arguments() -> None:
    requirements = list(REQUIREMENTS)
    entries = lookups("numpy", "other")

    lookup_dependencies(requirements, entries)

    assert requirements == REQUIREMENTS
    assert entries == lookups("numpy", "other")


@pytest.mark.parametrize(
    ("dependencies", "expected"),
    [
        ('["numpy"]', {"numpy": ">=1.20"}),
        ('["numpy@project"]', {"numpy@project": ">=1.20"}),
        ('["numpy@extra:fast"]', {"numpy@extra:fast": ">=2"}),
        ('["numpy@extra:Fast"]', {"numpy@extra:Fast": ">=2"}),
        ('["numpy@extra:slow"]', {"numpy@extra:slow": "<2"}),
        ('["NumPy@group:dev"]', {"NumPy@group:dev": ">=1.26"}),
        (
            '["ruff@group:dev", "ruff@group:lint"]',
            {"ruff@group:dev": ">=0.5", "ruff@group:lint": ">=0.5"},
        ),
        (
            '["ujson@project", "ujson@extra:fast", "ujson@group:dev"]',
            {"ujson@project": None, "ujson@extra:fast": "", "ujson@group:dev": None},
        ),
        ('["tqdm@extra:fast"]', {"tqdm@extra:fast": None}),
        (
            '["numpy@extra:missing", "numpy@group:missing"]',
            {"numpy@extra:missing": None, "numpy@group:missing": None},
        ),
    ],
)
def test_dependency_specifiers_with_a_scope(
    tmp_path: Path, dependencies: str, expected: dict
) -> None:
    path = write_pyproject(tmp_path, DATA_WITH_SCOPES)

    assert specifiers(path, dependencies) == expected


def test_extract_dependency_requirements_lists_every_requirement_with_its_marker(
    tmp_path: Path,
) -> None:
    path = write_pyproject(
        tmp_path,
        "[project]\n"
        "dependencies = [\"numpy>=1.20; python_version < '3.12'\", "
        '"numpy>=1.26; python_version >= \'3.12\'", "Foo_Bar"]\n\n'
        '[project.optional-dependencies]\nx = ["numpy<3"]\n\n'
        '[dependency-groups]\ndev = ["numpy>=2"]\n',
    )

    result = extract_dependency_requirements(load_pyproject(str(path)), ["numpy", "foo.bar"])

    assert result == {
        "numpy": [
            {"specifier": ">=1.20", "marker": 'python_version < "3.12"', "source": "project"},
            {"specifier": ">=1.26", "marker": 'python_version >= "3.12"', "source": "project"},
            {"specifier": "<3", "marker": "", "source": "extra:x"},
            {"specifier": ">=2", "marker": "", "source": "group:dev"},
        ],
        "foo.bar": [{"specifier": "", "marker": "", "source": "project"}],
    }


@pytest.mark.parametrize(
    ("data", "names", "expected"),
    [
        ({"project": {"dependencies": ["numpy"]}}, ["missing"], {"missing": []}),
        ({"project": {"dependencies": ["numpy"]}}, [], {}),
        (
            {"project": {"dependencies": ["not a requirement!!", "numpy>=1"]}},
            ["numpy"],
            {"numpy": [{"specifier": ">=1", "marker": "", "source": "project"}]},
        ),
        (
            {"project": {"dependencies": ["numpy>=1", "numpy>=1"]}},
            ["numpy"],
            {
                "numpy": [
                    {"specifier": ">=1", "marker": "", "source": "project"},
                    {"specifier": ">=1", "marker": "", "source": "project"},
                ]
            },
        ),
    ],
    ids=["not-found-is-empty", "nothing-requested", "invalid-requirement-ignored", "duplicates"],
)
def test_extract_dependency_requirements(data: dict, names: list[str], expected: dict) -> None:
    assert extract_dependency_requirements(data, names) == expected


def test_extract_dependency_requirements_wrong_type() -> None:
    with pytest.raises(MetadataError, match=r"\[project\].dependencies: must be an array"):
        extract_dependency_requirements({"project": {"dependencies": 1}}, ["numpy"])
