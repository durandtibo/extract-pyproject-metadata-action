"""Tests of ``extract_pyproject_metadata.pyproject``: reading the
file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.inputs import parse_string_array
from extract_pyproject_metadata.pyproject import (
    ALWAYS_READ_FIELDS,
    LOOKUP_FIELDS,
    _read_name,
    _read_version,
    dynamic_field_warnings,
    load_pyproject,
    read_extra_names,
    read_group_names,
    read_groups,
    read_project,
)
from extract_pyproject_metadata.requirements import collect_requirements
from extract_pyproject_metadata.types import Project, ReportWarning
from tests.helpers import extract, extract_with_warnings, messages, write_pyproject


def test_load_pyproject(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')

    assert load_pyproject(str(path)) == {"project": {"name": "coola", "version": "1.2.3"}}


def test_load_pyproject_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_bytes(b'\xef\xbb\xbf[project]\nname = "coola"\nversion = "1.2.3"\n')

    assert load_pyproject(str(path)) == {"project": {"name": "coola", "version": "1.2.3"}}


def test_load_pyproject_bom_only_at_the_start(tmp_path: Path) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_bytes(b'[project]\n\xef\xbb\xbfname = "coola"\n')

    with pytest.raises(MetadataError, match=r"pyproject-path: not valid TOML"):
        load_pyproject(str(path))


def test_load_pyproject_nested_too_deeply(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, "[project]\nx = " + "[" * 5000 + "]" * 5000 + "\n")

    with pytest.raises(MetadataError, match=r"pyproject-path: nested too deeply to be parsed"):
        load_pyproject(str(path))


def test_load_pyproject_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.toml"

    with pytest.raises(MetadataError, match=r"pyproject-path: not a file"):
        load_pyproject(str(missing))


def test_load_pyproject_invalid_toml(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, "this is not [valid toml")

    with pytest.raises(MetadataError, match=r"pyproject-path: not valid TOML"):
        load_pyproject(str(path))


def test_load_pyproject_invalid_utf8(tmp_path: Path) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_bytes(b'[project]\nname = "caf\xe9"\n')

    with pytest.raises(MetadataError, match=r"pyproject-path: not valid UTF-8"):
        load_pyproject(str(path))


def test_load_pyproject_unreadable_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')

    def deny(_self: Path, *_args: object, **_kwargs: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "open", deny)

    with pytest.raises(MetadataError, match=r"pyproject-path: cannot be read: .*Permission denied"):
        load_pyproject(str(path))


def test_extra_names_optional_dependencies_must_be_a_table() -> None:
    with pytest.raises(MetadataError, match=r"^\[project\].optional-dependencies: must be a table"):
        read_extra_names({"optional-dependencies": []}, [])


@pytest.mark.parametrize(
    ("optional_dependencies", "extra_values", "expected"),
    [
        (None, ["all"], ["all"]),
        ({"pandas": [], "numpy": []}, [], ["numpy", "pandas"]),
        ({"pandas": [], "numpy": []}, [""], ["", "numpy", "pandas"]),
        ({"pandas": [], "numpy": []}, ["numpy"], ["numpy", "pandas"]),
        ({"pandas": [], "numpy": []}, ["pandas", "numpy"], ["pandas", "numpy"]),
        ({"pandas": [], "numpy": []}, ["all", "all"], ["all", "numpy", "pandas"]),
        ({"pandas": [], "numpy": []}, ["", ""], ["", "numpy", "pandas"]),
        ({"pandas": [], "numpy": []}, ["all", "numpy", "all"], ["all", "numpy", "pandas"]),
        (
            {"Zeta": [], "alpha": [], "Beta": [], "gamma_x": []},
            [],
            ["alpha", "Beta", "gamma_x", "Zeta"],
        ),
        ({"b": [], "A_x": [], "a-x": []}, ["", "b"], ["", "b", "A_x"]),
        ({"Foo_Bar": [], "foo-bar": []}, [], ["Foo_Bar"]),
        ({"foo-bar": [], "Foo_Bar": []}, [], ["foo-bar"]),
        ({"Foo": [], "foo": [], "FOO": []}, [], ["Foo"]),
        ({"a.b": [], "a-b": [], "a__b": []}, [], ["a.b"]),
        ({"foo_bar": [], "baz": []}, ["Foo-Bar"], ["Foo-Bar", "baz"]),
        ({"foo_bar": [], "baz": []}, ["FOO_BAR", "foo.bar"], ["FOO_BAR", "baz"]),
        ({"foo_bar": [], "baz": []}, ["", "Baz"], ["", "Baz", "foo_bar"]),
        ({"foo_bar": [], "baz": []}, ["Baz", ""], ["Baz", "", "foo_bar"]),
    ],
    ids=[
        "no-table",
        "sorted",
        "empty-value-first",
        "already-there",
        "given-order",
        "repeated-value",
        "repeated-empty-value",
        "repeated-around-a-name",
        "sorted-by-normalized-name",
        "first-spelling-of-values",
        "spellings-of-an-extra",
        "spellings-reversed",
        "case",
        "separators",
        "value-spelled-differently",
        "two-spellings-of-a-value",
        "empty-then-name",
        "name-then-empty",
    ],
)
def test_read_extra_names(
    optional_dependencies: dict | None, extra_values: list[str], expected: list[str]
) -> None:
    project = (
        {} if optional_dependencies is None else {"optional-dependencies": optional_dependencies}
    )

    assert read_extra_names(project, extra_values) == expected


def test_group_names_are_sorted_and_deduplicated() -> None:
    data = {"dependency-groups": {"Dev": [], "test": [], "dev": [], "docs": []}}

    assert read_group_names(data) == ["Dev", "docs", "test"]


def project_toml(body: str) -> str:
    """A pyproject.toml with the lines ``body`` in ``[project]``."""
    return f"[project]\n{body}\n"


@pytest.mark.parametrize(
    ("toml", "match"),
    [
        # name
        (project_toml('version = "1"'), r"^\[project\]\.name: missing$"),
        (
            project_toml('version = "1"\ndynamic = ["readme", "name"]'),
            r"\[project\]\.name: listed in \[project\]\.dynamic.*static name",
        ),
        (project_toml('name = 1\nversion = "1"'), r"\.name: must be a non-empty string, got: 1"),
        (project_toml('name = ""\nversion = "1"'), r"\.name: must be a non-empty string, got: ''"),
        (project_toml('name = ["a"]\nversion = "1"'), r"\.name: must be a non-empty string"),
        # version
        (project_toml('name = "a"'), r"\[project\]\.version: missing"),
        (project_toml('name = "a"\ndynamic = ["readme"]'), r"\[project\]\.version: missing"),
        (project_toml('name = "a"\nversion = 1.0'), r"\.version: must be a string, got: 1\.0"),
        (project_toml('name = "a"\nversion = true'), r"\.version: must be a string, got: True"),
        (
            project_toml('name = "a"\nversion = "1.2.x"'),
            r"\.version: not a valid PEP 440 version: '1\.2\.x'",
        ),
        (project_toml('name = "a"\nversion = ""'), r"\.version: not a valid PEP 440 version: ''"),
        # dynamic
        (
            project_toml('name = "a"\nversion = "1"\ndynamic = ["readme", 2]'),
            r"\[project\]\.dynamic: must contain only strings",
        ),
        (
            project_toml('name = "a"\nversion = "1"\ndynamic = [["version"]]'),
            r"\[project\]\.dynamic: must contain only strings",
        ),
        (
            project_toml('name = "a"\nversion = "1"\ndynamic = "version"'),
            r"\[project\]\.dynamic: must be an array",
        ),
        (
            project_toml('name = "a"\nversion = "1"\ndynamic = {a = "version"}'),
            r"\[project\]\.dynamic: must be an array",
        ),
        # tables
        ("project = 1", r"\[project\]: must be a table"),
        ('project = "coola"', r"\[project\]: must be a table"),
        ("project = []", r"\[project\]: must be a table"),
    ],
)
def test_read_project_invalid_fields(tmp_path: Path, toml: str, match: str) -> None:
    path = write_pyproject(tmp_path, toml)

    with pytest.raises(MetadataError, match=match):
        extract(path)


def test_read_project_static_name_wins_over_dynamic(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\ndynamic = ["name"]\n'
    )

    assert extract(path)["name"] == "coola"


def test_read_project_dynamic_version_is_empty_and_warns(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [project]
        name = "coola"
        dynamic = ["version", "description"]
        """,
    )
    metadata, warnings = extract_with_warnings(path)

    assert metadata == {
        "name": "coola",
        "normalized_name": "coola",
        "file_name": "coola",
        "version": "",
        "normalized_version": "",
        "requires_python": "",
        "extras": [],
        "groups": [],
    }
    assert messages(warnings) == [
        (
            "[project].version is dynamic, the action cannot read it: "
            "version and normalized-version are empty"
        )
    ]


def test_read_project_static_and_dynamic_fields_warn_once_each(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [project]
        name = "coola"
        version = "1.2.3"
        optional-dependencies = {test = ["pytest"]}
        dynamic = ["optional-dependencies", "readme", "optional-dependencies", "version"]
        """,
    )

    _, warnings = extract_with_warnings(path)

    assert messages(warnings) == [
        (
            "[project].optional-dependencies is set and also listed in [project].dynamic, "
            "which PEP 621 forbids; the static value is used"
        ),
        (
            "[project].version is set and also listed in [project].dynamic, "
            "which PEP 621 forbids; the static value is used"
        ),
    ]


def test_read_project_dynamic_fields_that_are_not_set_do_not_warn(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "coola"\nversion = "1"\ndynamic = ["readme", "license"]\n'
    )

    _, warnings = extract_with_warnings(path)

    assert messages(warnings) == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [("[]", []), ('["a"]', ["a"]), ('["a", "B_c"]', ["a", "B_c"]), ('["a", "a"]', ["a", "a"])],
)
def test_parse_string_array(value: str, expected: list[str]) -> None:
    assert parse_string_array(value, "dependencies") == expected


@pytest.mark.parametrize("value", ["not json", ""])
def test_parse_string_array_invalid_json(value: str) -> None:
    with pytest.raises(MetadataError, match=r"^extra-values: not valid JSON: "):
        parse_string_array(value, "extra-values")


@pytest.mark.parametrize("value", ['{"a": 1}', '"a"', "1", "null", "[1]", '["a", null]', '[["a"]]'])
def test_parse_string_array_not_an_array_of_strings(value: str) -> None:
    with pytest.raises(
        MetadataError, match=r"^extra-values: must be a JSON array of strings, got: "
    ):
        parse_string_array(value, "extra-values")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("coola", "coola"),
        ("Coola", "coola"),
        ("My_Package.Name", "my-package-name"),
        ("a--b__c..d", "a-b-c-d"),
        ("a-._b", "a-b"),
        ("Zope.Interface", "zope-interface"),
        ("pkg2", "pkg2"),
    ],
)
def test_read_project_normalized_name(tmp_path: Path, name: str, expected: str) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "{name}"\nversion = "1"\n')

    metadata = extract(path)

    assert metadata["name"] == name
    assert metadata["normalized_name"] == expected


@pytest.mark.parametrize(
    "name",
    ["a", "A", "7", "coola", "My_Package.Name", "a-b", "a_b", "a.b", "a--b__c..d", "a1", "x9"],
)
def test_read_name(name: str) -> None:
    assert _read_name({"name": name}, []) == name


@pytest.mark.parametrize(
    "name",
    [
        *["my pkg", "my pkg!", "-a", "a-", "_a", "a_", ".a", "a.", "a/b", "a@b", "ÄB"],
        *["a\nb", " a", "a ", "a\n"],
    ],
)
def test_read_name_not_a_project_name(name: str) -> None:
    with pytest.raises(MetadataError, match=r"^\[project\].name: not a valid project name"):
        _read_name({"name": name}, [])


def test_static_and_dynamic_warnings() -> None:
    project = {"name": "a", "version": "1", "description": "d"}

    warnings = dynamic_field_warnings(
        project, ["version", "readme", "version", "name"], ALWAYS_READ_FIELDS
    )

    assert {w.code for w in warnings} == {"static-and-dynamic"}
    assert messages(warnings) == [
        (
            "[project].version is set and also listed in [project].dynamic, "
            "which PEP 621 forbids; the static value is used"
        ),
        (
            "[project].name is set and also listed in [project].dynamic, "
            "which PEP 621 forbids; the static value is used"
        ),
    ]


def test_static_and_dynamic_warnings_none() -> None:
    assert dynamic_field_warnings({"name": "a"}, ["description"], ALWAYS_READ_FIELDS) == []


@pytest.mark.parametrize(
    "version",
    [
        *["1", "1.2.3", "0.1.0.dev3", "1.0rc1", "2024.1.post2", "1!2.0"],
        *["1.0.0rc1+build.5", "v1.0", "1.0-1", "1.0-RC1"],
    ],
)
def test_read_version_static(version: str) -> None:
    assert _read_version({"version": version}, []) == version


def test_read_version_static_wins_over_dynamic() -> None:
    assert _read_version({"version": "1.0"}, ["version"]) == "1.0"


def test_read_version_dynamic_is_none() -> None:
    assert _read_version({}, ["version"]) is None


@pytest.mark.parametrize("project", [{"name": "a b", "version": "latest"}, {"name": "a b"}])
def test_read_project_reports_an_invalid_name_before_the_version(project: dict) -> None:
    with pytest.raises(MetadataError, match=r"^\[project\].name: not a valid project name"):
        read_project({"project": project}, [])


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("1.2.3", "1.2.3"),
        ("1.0", "1.0"),
        ("1.0-RC1", "1.0rc1"),
        ("1.0.0.RC.1", "1.0.0rc1"),
        ("v1.2", "1.2"),
        ("1.0.post1", "1.0.post1"),
        ("1.0-1", "1.0.post1"),
        ("2020.01.05", "2020.1.5"),
        ("1.0+Local_1", "1.0+local.1"),
        ("1!2.0.DEV3", "1!2.0.dev3"),
    ],
)
def test_read_project_normalized_version(tmp_path: Path, version: str, expected: str) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "a"\nversion = "{version}"\n')

    metadata = extract(path)

    assert (metadata["version"], metadata["normalized_version"]) == (version, expected)


def test_read_project_static_version_listed_as_dynamic_warns() -> None:
    data = {"project": {"name": "a", "version": "1.0", "dynamic": ["version"]}}

    project, warnings = read_project(data, [])

    assert project.version == "1.0"
    assert messages(warnings) == [
        (
            "[project].version is set and also listed in [project].dynamic, "
            "which PEP 621 forbids; the static value is used"
        )
    ]


def test_read_project_dynamic_version_warns() -> None:
    data = {"project": {"name": "a", "dynamic": ["version"]}}

    project, warnings = read_project(data, [])

    assert project.version is None
    assert messages(warnings) == [
        (
            "[project].version is dynamic, the action cannot read it: "
            "version and normalized-version are empty"
        )
    ]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("coola", "coola"),
        ("My_Package.Name", "my_package_name"),
        ("a-b", "a_b"),
        ("Foo--Bar__baz..qux", "foo_bar_baz_qux"),
        ("A", "a"),
    ],
)
def test_read_project_file_name(tmp_path: Path, name: str, expected: str) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "{name}"\nversion = "1"\n')

    assert extract(path)["file_name"] == expected


def test_read_project_fields(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [project]
        name = "My_Package"
        version = "1.0-RC1"
        requires-python = ">=3.12"
        dynamic = ["description"]

        [project.optional-dependencies]
        b = []
        a = []

        [dependency-groups]
        dev = []
        """,
    )

    project, warnings = read_project(load_pyproject(str(path)), [""])

    assert project == Project(
        name="My_Package",
        version="1.0-RC1",
        requires_python=">=3.12",
        dynamic=frozenset({"description"}),
        extras=["", "a", "b"],
        groups=["dev"],
    )
    assert messages(warnings) == []


def test_read_groups_merges_the_spellings_in_file_order() -> None:
    table = {"Dev": ["a"], "other": ["x"], "dev": ["b"], "DEV": ["c"]}

    assert read_groups(table) == {
        "dev": [("Dev", ["a"]), ("dev", ["b"]), ("DEV", ["c"])],
        "other": [("other", ["x"])],
    }


def test_read_groups_does_not_check_the_values() -> None:
    assert read_groups({"a": "x"}) == {"a": [("a", "x")]}


def test_read_groups_does_not_change_the_table() -> None:
    table = {"Dev": ["a"], "dev": ["b"]}

    read_groups(table)

    assert table == {"Dev": ["a"], "dev": ["b"]}


SET_VALUES: dict[str, Any] = {
    "name": "a",
    "version": "1.0",
    "requires-python": ">=3.11",
    "dependencies": ["numpy"],
    "optional-dependencies": {"test": ["pytest"]},
}


@pytest.mark.parametrize("field", ["description", "classifiers", "readme", "license", "urls"])
def test_read_project_a_field_that_is_not_read_does_not_warn_when_static_and_dynamic(
    field: str,
) -> None:
    data = {"project": {"name": "a", "version": "1.0", "dynamic": [field], field: "x"}}

    _, warnings = read_project(data, [])

    assert warnings == []


@pytest.mark.parametrize("field", ["version", "requires-python", "optional-dependencies"])
def test_read_project_a_field_that_is_read_warns_when_static_and_dynamic(field: str) -> None:
    project = {"name": "a", "version": "1.0", "dynamic": [field], field: SET_VALUES[field]}

    _, warnings = read_project({"project": project}, [])

    assert [w.code for w in warnings] == ["static-and-dynamic"]
    assert f"[project].{field} is set and also listed" in warnings[0].message


def test_read_project_a_dependencies_field_does_not_warn_without_a_lookup() -> None:
    project = {"name": "a", "version": "1.0", "dynamic": ["dependencies"], "dependencies": ["x"]}

    _, warnings = read_project({"project": project}, [])

    assert warnings == []


def test_read_project_a_dynamic_optional_dependencies_warns_that_it_cannot_be_read() -> None:
    project = {"name": "a", "version": "1.0", "dynamic": ["optional-dependencies"]}

    _, warnings = read_project({"project": project}, [])

    assert warnings == [
        ReportWarning(
            "dynamic-field",
            "[project].optional-dependencies is dynamic, the action cannot read it: "
            "extras has no extra name from it",
        )
    ]


def test_dynamic_field_warnings_for_every_field() -> None:
    fields = (*ALWAYS_READ_FIELDS, *LOOKUP_FIELDS)

    warnings = dynamic_field_warnings(SET_VALUES, sorted(fields), fields)

    assert [w.code for w in warnings] == ["static-and-dynamic"] * len(fields)


def test_dynamic_field_warnings_ignores_the_fields_outside_fields() -> None:
    assert dynamic_field_warnings(SET_VALUES, ["dependencies"], ALWAYS_READ_FIELDS) == []
    assert dynamic_field_warnings({}, ["dependencies"], ALWAYS_READ_FIELDS) == []


@pytest.mark.parametrize("field", [*ALWAYS_READ_FIELDS[1:], *LOOKUP_FIELDS])
def test_dynamic_field_warnings_a_dynamic_field_that_is_not_set_warns(field: str) -> None:
    warnings = dynamic_field_warnings({}, [field], (*ALWAYS_READ_FIELDS, *LOOKUP_FIELDS))

    assert [w.code for w in warnings] == ["dynamic-field"]
    assert warnings[0].message.startswith(f"[project].{field} is dynamic, ")


def test_dynamic_field_warnings_a_dynamic_name_that_is_not_set_does_not_warn() -> None:
    assert dynamic_field_warnings({}, ["name"], ALWAYS_READ_FIELDS) == []


def test_read_project_a_dynamic_requires_python_warns_that_it_cannot_be_read() -> None:
    project = {"name": "a", "version": "1.0", "dynamic": ["requires-python"]}

    _, warnings = read_project({"project": project}, [])

    assert warnings == [
        ReportWarning(
            "dynamic-field",
            "[project].requires-python is dynamic, the action cannot read it: "
            "python-versions is every candidate",
        )
    ]


class Recorder(dict[str, Any]):
    """A ``[project]`` table that records the keys that are read."""

    accessed: set[str]

    def get(self, key: str, default: Any = None) -> Any:
        self.accessed.add(key)
        return super().get(key, default)

    def __getitem__(self, key: str) -> Any:
        self.accessed.add(key)
        return super().__getitem__(key)

    def __contains__(self, key: object) -> bool:
        self.accessed.add(str(key))
        return super().__contains__(key)


def record_accesses() -> tuple[Recorder, dict[str, Any]]:
    """A recorder of the keys of ``[project]`` and the parsed data that holds it."""
    project = Recorder(SET_VALUES)
    project.accessed = set()
    return project, {"project": project}


def test_always_read_fields_are_the_fields_that_read_project_reads() -> None:
    project, data = record_accesses()

    read_project(data, [])

    assert project.accessed - {"dynamic"} == set(ALWAYS_READ_FIELDS)


def test_lookup_fields_are_the_fields_that_collect_requirements_reads() -> None:
    project, data = record_accesses()

    collect_requirements(data, frozenset())

    assert project.accessed - set(ALWAYS_READ_FIELDS) == set(LOOKUP_FIELDS)
