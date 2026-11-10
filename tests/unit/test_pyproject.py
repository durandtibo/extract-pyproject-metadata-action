"""Tests of ``extract_pyproject_metadata.pyproject``: reading the
file."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.inputs import parse_string_array
from extract_pyproject_metadata.pyproject import (
    _read_name,
    _read_version,
    _static_and_dynamic_warnings,
    load_pyproject,
    read_extra_names,
    read_group_names,
    read_project,
)
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


def test_extra_names_without_optional_dependencies() -> None:
    assert read_extra_names({}, ["all"]) == ["all"]


def test_extra_names_optional_dependencies_must_be_a_table() -> None:
    with pytest.raises(MetadataError, match=r"^\[project\].optional-dependencies: must be a table"):
        read_extra_names({"optional-dependencies": []}, [])


def test_extra_names() -> None:
    project = {"optional-dependencies": {"b": [], "A_x": [], "a-x": []}}

    assert read_extra_names(project, ["", "b"]) == ["", "b", "A_x"]


def test_group_names_are_sorted_and_deduplicated() -> None:
    data = {"dependency-groups": {"Dev": [], "test": [], "dev": [], "docs": []}}

    assert read_group_names(data) == ["Dev", "docs", "test"]


def test_read_project_missing_name_message() -> None:
    with pytest.raises(MetadataError, match=r"^\[project\]\.name: missing$"):
        read_project({"project": {"version": "1"}}, [])


def test_read_project_name_and_version(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [project]
        name = "coola"
        version = "1.2.3"
        """,
    )

    metadata = extract(path)

    assert metadata == {
        "name": "coola",
        "normalized_name": "coola",
        "file_name": "coola",
        "version": "1.2.3",
        "normalized_version": "1.2.3",
        "requires_python": "",
        "extras": [],
        "groups": [],
    }


def test_read_project_extras_are_sorted(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [project]
        name = "coola"
        version = "1.2.3"

        [project.optional-dependencies]
        pandas = ["pandas"]
        numpy = ["numpy"]
        """,
    )

    metadata = extract(path)

    assert metadata["extras"] == ["numpy", "pandas"]


def test_read_project_extra_values_are_prepended(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [project]
        name = "coola"
        version = "1.2.3"

        [project.optional-dependencies]
        numpy = ["numpy"]
        """,
    )

    metadata = extract(path, '[""]')

    assert metadata["extras"] == ["", "numpy"]


@pytest.mark.parametrize(
    ("extra_values_json", "expected"),
    [
        ('["numpy"]', ["numpy", "pandas"]),
        ('["pandas", "numpy"]', ["pandas", "numpy"]),
        ('["all", "all"]', ["all", "numpy", "pandas"]),
        ('["", ""]', ["", "numpy", "pandas"]),
        ('["all", "numpy", "all"]', ["all", "numpy", "pandas"]),
    ],
)
def test_read_project_extras_are_deduplicated(
    tmp_path: Path, extra_values_json: str, expected: list[str]
) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [project]
        name = "coola"
        version = "1.2.3"

        [project.optional-dependencies]
        pandas = ["pandas"]
        numpy = ["numpy"]
        """,
    )

    assert extract(path, extra_values_json)["extras"] == expected


def test_read_project_missing_name(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [project]
        version = "1.2.3"
        """,
    )

    with pytest.raises(MetadataError, match=r"\[project\]\.name: missing"):
        extract(path)


@pytest.mark.parametrize("dynamic", ['["name"]', '["name", "version"]', '["readme", "name"]'])
def test_read_project_dynamic_name_is_an_error(tmp_path: Path, dynamic: str) -> None:
    path = write_pyproject(tmp_path, f'[project]\nversion = "1.2.3"\ndynamic = {dynamic}\n')

    with pytest.raises(
        MetadataError, match=r"\[project\]\.name: listed in \[project\]\.dynamic.*static name"
    ):
        extract(path)


def test_read_project_static_name_wins_over_dynamic(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\ndynamic = ["name"]\n'
    )

    assert extract(path)["name"] == "coola"


@pytest.mark.parametrize(
    ("project", "match"),
    [
        ('name = 1\nversion = "1.2.3"', r"\[project\]\.name: must be a non-empty string, got: 1"),
        ('name = ""\nversion = "1.2.3"', r"\[project\]\.name: must be a non-empty string, got: ''"),
        ('name = ["a"]\nversion = "1.2.3"', r"\[project\]\.name: must be a non-empty string"),
        ('name = "coola"\nversion = 1.0', r"\[project\]\.version: must be a string, got: 1\.0"),
        ('name = "coola"\nversion = 1', r"\[project\]\.version: must be a string, got: 1"),
        ('name = "coola"\nversion = true', r"\[project\]\.version: must be a string, got: True"),
    ],
)
def test_read_project_name_and_version_must_be_strings(
    tmp_path: Path, project: str, match: str
) -> None:
    path = write_pyproject(tmp_path, f"[project]\n{project}\n")

    with pytest.raises(MetadataError, match=match):
        extract(path)


@pytest.mark.parametrize("content", ["project = 1", 'project = "coola"', "project = []"])
def test_read_project_project_must_be_a_table(tmp_path: Path, content: str) -> None:
    path = write_pyproject(tmp_path, content)

    with pytest.raises(MetadataError, match=r"\[project\]: must be a table"):
        extract(path)


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
    assert messages(warnings) == ["[project].version is dynamic, the version output is empty"]


def test_read_project_static_version_wins_over_dynamic(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "coola"\nversion = "1.2.3"\ndynamic = ["version"]\n',
    )
    metadata, warnings = extract_with_warnings(path)

    assert metadata["version"] == "1.2.3"
    assert messages(warnings) == [
        (
            "[project].version is set and also listed in [project].dynamic, "
            "which PEP 621 forbids; the static value is used"
        )
    ]


def test_read_project_static_and_dynamic_fields_warn_once_each(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [project]
        name = "coola"
        version = "1.2.3"
        dependencies = ["numpy"]
        dynamic = ["dependencies", "readme", "dependencies", "version"]
        """,
    )

    _, warnings = extract_with_warnings(path)

    assert messages(warnings) == [
        (
            "[project].dependencies is set and also listed in [project].dynamic, "
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


def test_read_project_missing_version_with_other_dynamic_fields(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\ndynamic = ["readme"]\n')

    with pytest.raises(MetadataError, match=r"\[project\]\.version: missing"):
        extract(path)


@pytest.mark.parametrize("value", ["[1]", '["readme", 2]', '[["version"]]', "[true]"])
def test_read_project_dynamic_must_contain_only_strings(tmp_path: Path, value: str) -> None:
    path = write_pyproject(
        tmp_path, f'[project]\nname = "coola"\nversion = "1"\ndynamic = {value}\n'
    )

    with pytest.raises(MetadataError, match=r"\[project\]\.dynamic: must contain only strings"):
        extract(path)


@pytest.mark.parametrize("value", ['"version"', "1", '{a = "version"}'])
def test_read_project_dynamic_must_be_an_array(tmp_path: Path, value: str) -> None:
    path = write_pyproject(
        tmp_path, f'[project]\nname = "coola"\nversion = "1"\ndynamic = {value}\n'
    )

    with pytest.raises(MetadataError, match=r"\[project\]\.dynamic: must be an array"):
        extract(path)


def test_read_project_missing_version(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [project]
        name = "coola"
        """,
    )

    with pytest.raises(MetadataError, match=r"\[project\]\.version: missing"):
        extract(path)


def test_read_project_invalid_extra_values_json(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [project]
        name = "coola"
        version = "1.2.3"
        """,
    )

    with pytest.raises(MetadataError, match="not valid JSON"):
        extract(path, "not json")


def test_read_project_extra_values_not_a_list(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [project]
        name = "coola"
        version = "1.2.3"
        """,
    )

    with pytest.raises(MetadataError, match="must be a JSON array"):
        extract(path, '{"not": "a list"}')


@pytest.mark.parametrize("value", ["[1]", "[null]", '[["a"]]', '["ok", 2]', '[{"a": 1}]'])
def test_read_project_extra_values_must_be_strings(tmp_path: Path, value: str) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')

    with pytest.raises(MetadataError, match="extra-values: must be a JSON array of strings"):
        extract(path, value)


def test_read_project_special_characters_round_trip(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [project]
        name = "my-package_v2"
        version = "1.0.0rc1+build.5"
        """,
    )

    metadata = extract(path)

    assert metadata["name"] == "my-package_v2"
    assert metadata["version"] == "1.0.0rc1+build.5"


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
    ("optional_dependencies", "expected"),
    [
        ('Foo_Bar = []\n"foo-bar" = []', ["Foo_Bar"]),
        ('"foo-bar" = []\nFoo_Bar = []', ["foo-bar"]),
        ("Foo = []\nfoo = []\nFOO = []", ["Foo"]),
        ('"a.b" = []\n"a-b" = []\n"a__b" = []', ["a.b"]),
    ],
)
def test_read_project_extras_spellings_of_the_same_extra_are_one(
    tmp_path: Path, optional_dependencies: str, expected: list[str]
) -> None:
    path = write_pyproject(
        tmp_path,
        f'[project]\nname = "p"\nversion = "1"\n[project.optional-dependencies]\n{optional_dependencies}\n',
    )

    assert extract(path)["extras"] == expected


@pytest.mark.parametrize(
    ("extra_values_json", "expected"),
    [
        ('["Foo-Bar"]', ["Foo-Bar", "baz"]),
        ('["FOO_BAR", "foo.bar"]', ["FOO_BAR", "baz"]),
        ('["", "Baz"]', ["", "Baz", "foo_bar"]),
        ('["Baz", ""]', ["Baz", "", "foo_bar"]),
    ],
)
def test_read_project_extra_values_are_deduplicated_per_pep_685(
    tmp_path: Path, extra_values_json: str, expected: list[str]
) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "p"\nversion = "1"\n[project.optional-dependencies]\nfoo_bar = []\nbaz = []\n',
    )

    assert extract(path, extra_values_json)["extras"] == expected


def test_read_project_extras_are_sorted_by_normalized_name(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [project]
        name = "p"
        version = "1"

        [project.optional-dependencies]
        Zeta = []
        alpha = []
        Beta = []
        "gamma_x" = []
        """,
    )

    assert extract(path)["extras"] == ["alpha", "Beta", "gamma_x", "Zeta"]


@pytest.mark.parametrize(
    "version",
    [
        "1",
        "1.2.3",
        "0.1.0.dev3",
        "1.0rc1",
        "2024.1.post2",
        "1!2.0",
        "1.0.0rc1+build.5",
        "v1.2",
        "1.0-1",
    ],
)
def test_read_project_valid_pep_440_versions(tmp_path: Path, version: str) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "p"\nversion = "{version}"\n')

    assert extract(path)["version"] == version


@pytest.mark.parametrize("version", ["", "latest", "1.2.x", "one", "1..2", "1.2.3 beta", "^1.2"])
def test_read_project_invalid_pep_440_version(tmp_path: Path, version: str) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "p"\nversion = "{version}"\n')

    message = f"[project].version: not a valid PEP 440 version: {version!r}"
    with pytest.raises(MetadataError, match=re.escape(message)):
        extract(path)


def test_read_project_dynamic_version_is_not_validated(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "p"\ndynamic = ["version"]\n')

    assert extract(path)["version"] == ""


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


@pytest.mark.parametrize("name", ["a", "My_Package.Name", "a-b", "a1"])
def test_read_name(name: str) -> None:
    assert _read_name({"name": name}, []) == name


def test_read_name_missing() -> None:
    with pytest.raises(MetadataError, match=r"^\[project\].name: missing$"):
        _read_name({}, ["version"])


def test_read_name_dynamic() -> None:
    with pytest.raises(MetadataError, match=r"^\[project\].name: listed in .*static name$"):
        _read_name({}, ["name"])


@pytest.mark.parametrize("name", [1, "", None, ["a"]])
def test_read_name_not_a_non_empty_string(name: object) -> None:
    with pytest.raises(
        MetadataError, match=r"^\[project\].name: must be a non-empty string, got: "
    ):
        _read_name({"name": name}, [])


@pytest.mark.parametrize("name", ["my pkg", "-a", "a-", "_a", "a.", "a/b"])
def test_read_name_not_a_project_name(name: str) -> None:
    with pytest.raises(MetadataError, match=r"^\[project\].name: not a valid project name"):
        _read_name({"name": name}, [])


def test_static_and_dynamic_warnings() -> None:
    project = {"name": "a", "version": "1", "description": "d"}

    warnings = _static_and_dynamic_warnings(project, ["version", "readme", "version", "name"])

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
    assert _static_and_dynamic_warnings({"name": "a"}, ["version"]) == []


@pytest.mark.parametrize("version", ["1.0-RC1", "1.2.3", "v1.0"])
def test_read_version_static(version: str) -> None:
    assert _read_version({"version": version}, []) == (version, [])


def test_read_version_static_wins_over_dynamic() -> None:
    assert _read_version({"version": "1.0"}, ["version"]) == ("1.0", [])


def test_read_version_dynamic_warns() -> None:
    assert _read_version({}, ["version"]) == (
        None,
        [
            ReportWarning(
                "dynamic-version", "[project].version is dynamic, the version output is empty"
            )
        ],
    )


def test_read_version_missing() -> None:
    with pytest.raises(MetadataError, match=r"^\[project\].version: missing$"):
        _read_version({}, ["readme"])


def test_read_version_not_a_string() -> None:
    with pytest.raises(MetadataError, match=r"^\[project\].version: must be a string, got: 1.0$"):
        _read_version({"version": 1.0}, [])


def test_read_version_invalid() -> None:
    with pytest.raises(
        MetadataError,
        match=r"^\[project\].version: not a valid PEP 440 version: 'latest'$",
    ):
        _read_version({"version": "latest"}, [])


def test_read_project_reports_the_name_before_the_version() -> None:
    with pytest.raises(MetadataError, match=r"^\[project\].name: not a valid project name"):
        read_project({"project": {"name": "a b", "version": "latest"}}, [])


def test_read_project_reports_an_invalid_name_before_a_missing_version() -> None:
    with pytest.raises(MetadataError, match=r"^\[project\].name: not a valid project name"):
        read_project({"project": {"name": "a b"}}, [])


@pytest.mark.parametrize(
    "name",
    [
        "a",
        "A",
        "7",
        "coola",
        "My_Package.Name",
        "a-b",
        "a_b",
        "a.b",
        "a--b__c..d",
        "zope.interface",
        "x9",
    ],
)
def test_read_project_valid_names(tmp_path: Path, name: str) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "{name}"\nversion = "1"\n')

    assert extract(path)["name"] == name


@pytest.mark.parametrize(
    "name",
    [
        "my pkg",
        "my pkg!",
        "-a",
        "a-",
        "_a",
        "a_",
        ".a",
        "a.",
        "a/b",
        "a@b",
        "ÄB",
        "a\\nb",
        " a",
        "a ",
        "a\\n",
    ],
)
def test_read_project_invalid_names(tmp_path: Path, name: str) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "{name}"\nversion = "1"\n')

    with pytest.raises(MetadataError, match=r"\[project\]\.name: not a valid project name"):
        extract(path)


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


def test_read_project_normalized_version_is_empty_when_the_version_is_dynamic(
    tmp_path: Path,
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\ndynamic = ["version"]\n')

    assert extract(path)["normalized_version"] == ""


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
    assert messages(warnings) == ["[project].version is dynamic, the version output is empty"]


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


def test_read_project_dynamic_version_is_none(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\ndynamic = ["version"]\n')

    project, _ = read_project(load_pyproject(str(path)), [])

    assert project.version is None
