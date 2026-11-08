"""Tests of ``extract_pyproject_metadata.dependencies.lookup``: the
requested dependencies."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import pytest

from extract_pyproject_metadata.dependencies.lookup import (
    _lookup_key,
    check_no_missing_dependency,
    extract_dependency_requirements,
    extract_dependency_specifiers,
    parse_dependencies,
    requirements_from_index,
    specifiers_from_index,
)
from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.pyproject import load_pyproject
from tests.helpers import (
    DATA_WITH_SCOPES,
    DEPS_TOML,
    INVALID_TOML,
    MARKERS_TOML,
    extract,
    specifiers,
    write_pyproject,
)

if TYPE_CHECKING:
    from pathlib import Path


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
def test_extract_metadata_optional_dependencies_must_be_a_table(tmp_path: Path, value: str) -> None:
    path = write_pyproject(
        tmp_path,
        f"""
        [project]
        name = "coola"
        version = "1.2.3"
        optional-dependencies = {value}
        """,
    )

    with pytest.raises(MetadataError, match=r"\[project\]\.optional-dependencies must be a table"):
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


def test_dependency_duplicate_adds_a_warning(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    result, warnings = extract_dependency_specifiers(load_pyproject(str(path)), ["dup"], str(path))

    assert result == {"dup": ">=1"}
    assert warnings == [f"dup has different specifiers in {path}: ['>=1', '>=2']; using '>=1'"]


def test_dependency_no_duplicate_adds_no_warning(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    _, warnings = extract_dependency_specifiers(load_pyproject(str(path)), ["nospec"], str(path))

    assert warnings == []


def test_dependency_invalid_requirements_add_warnings(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, INVALID_TOML)
    result, warnings = extract_dependency_specifiers(
        load_pyproject(str(path)), ["good", "dev-pkg", "missing"], str(path)
    )

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
            r"\[project\]\.dependencies must be an array, got: 'numpy'",
        ),
        ("[project]\ndependencies = 1", r"\[project\]\.dependencies must be an array, got: 1"),
        (
            '[project.optional-dependencies]\nx = "numpy"',
            r"\[project\.optional-dependencies\]\.x must be an array, got: 'numpy'",
        ),
        (
            "[project.optional-dependencies]\nx = 1",
            r"\[project\.optional-dependencies\]\.x must be an array, got: 1",
        ),
        (
            "[project]\noptional-dependencies = []",
            r"\[project\]\.optional-dependencies must be a table",
        ),
        ("dependency-groups = []", r"\[dependency-groups\] must be a table, got: \[\]"),
        ('dependency-groups = "dev"', r"\[dependency-groups\] must be a table, got: 'dev'"),
        (
            '[dependency-groups]\ndev = "numpy"',
            r"\[dependency-groups\]\.dev must be an array, got: 'numpy'",
        ),
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
        load_pyproject(str(path)), ["x", "y"], str(path)
    )

    assert result == {"x": ">=1", "y": ">=2"}
    assert warnings == [f"{path}: [dependency-groups] has an include-group cycle: a -> b -> a"]


def test_dependency_include_group_cycle_does_not_warn_when_nothing_is_requested(
    tmp_path: Path,
) -> None:
    path = write_pyproject(tmp_path, '[dependency-groups]\na = [{include-group = "a"}]\n')
    result, warnings = extract_dependency_specifiers(load_pyproject(str(path)), [], str(path))

    assert result == {}
    assert warnings == []


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
        load_pyproject(str(path)), ["numpy"], str(path)
    )

    assert result == {"numpy": ">=1.20"}
    assert warnings == []


def test_dependency_same_marker_different_specifiers_warns_with_the_marker(
    tmp_path: Path,
) -> None:
    path = write_pyproject(tmp_path, MARKERS_TOML)
    result, warnings = extract_dependency_specifiers(load_pyproject(str(path)), ["same"], str(path))

    assert result == {"same": ">=1"}
    assert warnings == [
        (
            f"same has different specifiers for marker 'sys_platform == \"linux\"' in {path}: "
            "['>=1', '>=2']; using '>=1'"
        )
    ]


def test_dependency_marker_and_no_marker_do_not_warn(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, MARKERS_TOML)
    result, warnings = extract_dependency_specifiers(
        load_pyproject(str(path)), ["mixed"], str(path)
    )

    assert result == {"mixed": ">=1"}
    assert warnings == []


def test_dependency_same_specifier_with_different_markers_does_not_warn(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        "[project]\ndependencies = [\"a>=1; os_name == 'nt'\", \"a>=1; os_name == 'posix'\"]\n",
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
        (
            f"a has different specifiers for marker 'os_name == \"nt\"' in {path}: "
            "['>=1', '>=2']; using '>=1'"
        ),
        f"a has different specifiers in {path}: ['>=3', '>=4']; using '>=1'",
    ]


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


def test_specifiers_from_index() -> None:
    found = {"numpy": [(">=1", None), ("<2", None)], "tqdm": [("", None)]}

    assert specifiers_from_index(found, ["warning"], ["Numpy", "tqdm", "other"], "p.toml") == (
        {"Numpy": ">=1", "tqdm": "", "other": None},
        ["warning", "Numpy has different specifiers in p.toml: ['<2', '>=1']; using '>=1'"],
    )


def test_specifiers_from_index_without_dependencies_ignores_the_index_warnings() -> None:
    assert specifiers_from_index({}, ["warning"], [], "p.toml") == ({}, [])


def test_requirements_from_index() -> None:
    found: dict[str, list[tuple[str, str | None]]] = {
        "numpy": [(">=1", "python_version < '3.12'"), ("", None)]
    }

    assert requirements_from_index(found, ["NumPy", "other"]) == {
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
    [
        "numpy@dev",
        "numpy@",
        "numpy@extra",
        "numpy@extra:",
        "numpy@group:",
        "numpy@Project",
        "numpy@feature:x",
        "numpy@@project",
    ],
)
def test_parse_dependencies_invalid_scope(entry: str) -> None:
    with pytest.raises(
        MetadataError, match=rf"^dependencies entry {re.escape(repr(entry))} has an invalid scope: "
    ):
        parse_dependencies(json.dumps([entry]))


@pytest.mark.parametrize("raw", ["not json", '{"a": 1}', "[1]"])
def test_parse_dependencies_not_an_array_of_strings(raw: str) -> None:
    with pytest.raises(
        MetadataError, match=r"^dependencies (is not valid JSON|must be a JSON array of strings)"
    ):
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
    with pytest.raises(
        MetadataError, match=r"custom.toml: \[project\].dependencies must be an array"
    ):
        extract_dependency_requirements({"project": {"dependencies": 1}}, ["numpy"], "custom.toml")


def test_check_no_missing_dependency_all_found() -> None:
    check_no_missing_dependency({"a": ">=1", "b": ""}, "p.toml")


def test_check_no_missing_dependency_nothing_requested() -> None:
    check_no_missing_dependency({}, "p.toml")


def test_check_no_missing_dependency_lists_the_missing_packages() -> None:
    with pytest.raises(
        MetadataError, match=r"custom\.toml: dependencies not found in .*: \['b', 'd'\]$"
    ):
        check_no_missing_dependency({"a": ">=1", "b": None, "c": "", "d": None}, "custom.toml")


def test_check_no_missing_dependency_points_out_dynamic_fields() -> None:
    with pytest.raises(
        MetadataError,
        match=r"\['numpy'\]; \[project\]\.dependencies is dynamic and cannot be read$",
    ):
        check_no_missing_dependency({"numpy": None}, "p.toml", ["dependencies"])
