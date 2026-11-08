"""Tests of the reading and validation of the fields of pyproject.toml."""



import re
from pathlib import Path

import pytest
from helpers import extract, requires_licenses, write_pyproject

import extract_pyproject_metadata.license as license_module
import extract_pyproject_metadata.output.github as output_github_module
from extract_pyproject_metadata.checks import check_array, check_str, check_string_array, get_table
from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.fields import read_build_system, read_extra_names, read_string_table
from extract_pyproject_metadata.inputs import parse_string_array
from extract_pyproject_metadata.license import license_warnings
from extract_pyproject_metadata.metadata import (
    _required_name,
    _required_version,
    _static_and_dynamic_warnings,
    _valid_name,
    _valid_version,
    extract_metadata,
)
from extract_pyproject_metadata.pyproject import load_pyproject


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

    with pytest.raises(MetadataError, match=r"pyproject.toml is not valid TOML"):
        load_pyproject(str(path))



def test_load_pyproject_nested_too_deeply(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, "[project]\nx = " + "[" * 5000 + "]" * 5000 + "\n")

    with pytest.raises(MetadataError, match=r"pyproject.toml is nested too deeply to be parsed"):
        load_pyproject(str(path))



def test_load_pyproject_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.toml"

    with pytest.raises(MetadataError, match=r"pyproject.toml not found at: .*does-not-exist.toml"):
        load_pyproject(str(missing))



def test_load_pyproject_invalid_toml(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, "this is not [valid toml")

    with pytest.raises(MetadataError, match=r"pyproject.toml is not valid TOML"):
        load_pyproject(str(path))



def test_load_pyproject_invalid_utf8(tmp_path: Path) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_bytes(b'[project]\nname = "caf\xe9"\n')

    with pytest.raises(MetadataError, match=r"pyproject.toml is not valid UTF-8"):
        load_pyproject(str(path))



def test_load_pyproject_unreadable_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')

    def deny(self: Path, *args: object, **kwargs: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "open", deny)

    with pytest.raises(MetadataError, match=r"pyproject.toml cannot be read: .*Permission denied"):
        load_pyproject(str(path))



def test_extract_metadata_error_names_the_file() -> None:
    with pytest.raises(MetadataError, match=r"custom/pyproject.toml is missing required key"):
        extract_metadata({"project": {"version": "1"}}, [], "custom/pyproject.toml")



def test_extract_metadata_name_and_version(tmp_path: Path) -> None:
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
        "version": "1.2.3",
        "normalized_version": "1.2.3",
        "description": "",
        "readme": "",
        "license": "",
        "license_files": [],
        "authors": [],
        "urls": {},
        "keywords": [],
        "classifiers": [],
        "scripts": {},
        "requires_python": "",
        "extras": [],
        "groups": [],
        "build_backend": "",
        "build_requires": [],
    }



@pytest.mark.parametrize(
    ("project", "expected"),
    [
        ('description = "A fast library"', "A fast library"),
        ('description = ""', ""),
        ('description = "Line one\\nline two"', "Line one\nline two"),
        ('description = "Héllo ✓"', "Héllo ✓"),
        ('dynamic = ["description"]', ""),
        ("", ""),
    ],
)
def test_extract_metadata_description(tmp_path: Path, project: str, expected: str) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "coola"\nversion = "1"\n{project}\n')

    assert extract(path)["description"] == expected



@pytest.mark.parametrize("value", ["1", "true", '["a"]', "{a = 1}"])
def test_extract_metadata_description_must_be_a_string(tmp_path: Path, value: str) -> None:
    path = write_pyproject(
        tmp_path, f'[project]\nname = "coola"\nversion = "1"\ndescription = {value}\n'
    )

    with pytest.raises(MetadataError, match=r"p\.toml: \[project\]\.description must be a string, got: "):
        extract_metadata(load_pyproject(str(path)), [], "p.toml")



@pytest.mark.parametrize(
    ("project", "expected"),
    [
        ("", []),
        ('license-files = []\n', []),
        ('license-files = ["LICENSE"]\n', ["LICENSE"]),
        ('license-files = ["LICENSE", "licenses/*.txt", "LICENSE"]\n', ["LICENSE", "licenses/*.txt", "LICENSE"]),
        ('dynamic = ["license-files"]\n', []),
    ],
)
def test_extract_metadata_license_files(tmp_path: Path, project: str, expected: list[str]) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "a"\nversion = "1"\n{project}')

    assert extract(path)["license_files"] == expected



@pytest.mark.parametrize(
    ("value", "match"),
    [
        ('"LICENSE"', r"\[project\]\.license-files must be an array, got: 'LICENSE'"),
        ('{ glob = "LICENSE" }', r"\[project\]\.license-files must be an array, got: \{'glob': 'LICENSE'\}"),
        ('["LICENSE", 1]', r"\[project\]\.license-files must contain only strings, got: 1"),
    ],
)
def test_extract_metadata_license_files_must_be_an_array_of_strings(
    tmp_path: Path, value: str, match: str
) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "a"\nversion = "1"\nlicense-files = {value}\n')

    with pytest.raises(MetadataError, match=match):
        extract(path)



@pytest.mark.parametrize("key", ["keywords", "classifiers"])
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", []),
        ("[]", []),
        ('["a"]', ["a"]),
        ('["b", "a", "b"]', ["b", "a", "b"]),
    ],
)
def test_extract_metadata_keywords_and_classifiers(
    tmp_path: Path, key: str, value: str, expected: list[str]
) -> None:
    line = f"{key} = {value}\n" if value else ""
    path = write_pyproject(tmp_path, f'[project]\nname = "a"\nversion = "1"\n{line}')

    assert extract(path)[key] == expected



@pytest.mark.parametrize("key", ["keywords", "classifiers"])
@pytest.mark.parametrize(
    ("value", "match"),
    [
        ('"x"', r"must be an array, got: 'x'"),
        ('["x", 1]', r"must contain only strings, got: 1"),
    ],
)
def test_extract_metadata_keywords_and_classifiers_must_be_arrays_of_strings(
    tmp_path: Path, key: str, value: str, match: str
) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "a"\nversion = "1"\n{key} = {value}\n')

    with pytest.raises(MetadataError, match=rf"\[project\]\.{key} {match}"):
        extract(path)



def test_extract_metadata_scripts(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "a"\nversion = "1"\n\n[project.scripts]\nz = "pkg.cli:z"\na = "pkg.cli:a"\n\n'
        '[project.gui-scripts]\ng = "pkg.gui:main"\n',
    )

    assert extract(path)["scripts"] == {"z": "pkg.cli:z", "a": "pkg.cli:a"}
    assert list(extract(path)["scripts"]) == ["z", "a"]



def test_extract_metadata_scripts_default_to_empty(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    assert extract(path)["scripts"] == {}



@pytest.mark.parametrize(
    ("scripts", "match"),
    [
        ('scripts = ["a"]', r"\[project\.scripts\] must be a table, got: \['a'\]"),
        ('[project.scripts]\na = 1', r"\[project\.scripts\]\.a must be a string, got: 1"),
    ],
)
def test_extract_metadata_scripts_must_be_a_table_of_strings(
    tmp_path: Path, scripts: str, match: str
) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "a"\nversion = "1"\n{scripts}\n')

    with pytest.raises(MetadataError, match=match):
        extract(path)



def test_string_table() -> None:
    assert read_string_table({"x": {"b": "1", "a": "2"}}, "x", "p.toml") == {"b": "1", "a": "2"}



def test_string_table_absent() -> None:
    assert read_string_table({}, "x", "p.toml") == {}



def test_string_table_returns_a_copy() -> None:
    project = {"x": {"a": "1"}}

    read_string_table(project, "x", "p.toml")["b"] = "2"

    assert project == {"x": {"a": "1"}}



def test_string_table_not_a_table() -> None:
    with pytest.raises(MetadataError, match=r"^p.toml: \[project\.x\] must be a table, got: 1$"):
        read_string_table({"x": 1}, "x", "p.toml")



def test_string_table_not_a_string() -> None:
    with pytest.raises(MetadataError, match=r"^p.toml: \[project\.x\]\.a must be a string, got: 1$"):
        read_string_table({"x": {"a": 1}}, "x", "p.toml")



@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({}, ("", [])),
        ({"build-system": {}}, ("", [])),
        ({"build-system": {"requires": ["setuptools>=61", "wheel"]}}, ("", ["setuptools>=61", "wheel"])),
        ({"build-system": {"build-backend": "hatchling.build"}}, ("hatchling.build", [])),
        (
            {"build-system": {"requires": ["a", "a"], "build-backend": "a.b:c", "backend-path": ["."]}},
            ("a.b:c", ["a", "a"]),
        ),
    ],
)
def test_build_system(data: dict, expected: tuple[str, list[str]]) -> None:
    assert read_build_system(data, "p.toml") == expected



def test_build_system_returns_a_copy_of_requires() -> None:
    data = {"build-system": {"requires": ["a"]}}

    read_build_system(data, "p.toml")[1].append("b")

    assert data == {"build-system": {"requires": ["a"]}}



@pytest.mark.parametrize(
    ("data", "match"),
    [
        ({"build-system": "x"}, r"^p.toml: \[build-system\] must be a table, got: 'x'$"),
        ({"build-system": {"build-backend": 1}}, r"^p.toml: \[build-system\].build-backend must be a string, got: 1$"),
        ({"build-system": {"requires": "a"}}, r"^p.toml: \[build-system\].requires must be an array, got: 'a'$"),
        ({"build-system": {"requires": ["a", 1]}}, r"^p.toml: \[build-system\].requires must contain only strings, got: 1$"),
    ],
)
def test_build_system_wrong_type(data: dict, match: str) -> None:
    with pytest.raises(MetadataError, match=match):
        read_build_system(data, "p.toml")



def test_extract_metadata_build_system(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n\n'
        '[project]\nname = "a"\nversion = "1"\n',
    )

    metadata = extract(path)

    assert (metadata["build_backend"], metadata["build_requires"]) == ("hatchling.build", ["hatchling"])



def test_extract_metadata_without_build_system(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    metadata = extract(path)

    assert (metadata["build_backend"], metadata["build_requires"]) == ("", [])



@pytest.mark.parametrize(
    "license_",
    ["MIT", "Apache-2.0 OR MIT", "apache-2.0 or mit", "GPL-3.0-or-later WITH Classpath-exception-2.0", "LicenseRef-Foo", ""],
)
def test_license_warnings_valid_expression(license_: str) -> None:
    assert license_warnings(license_, "p.toml") == []



@requires_licenses
@pytest.mark.parametrize("license_", ["MIT License", "MIT AND", "GPL v3", "(MIT"])
def test_license_warnings_invalid_expression(license_: str) -> None:
    warnings = license_warnings(license_, "p.toml")

    assert len(warnings) == 1
    assert warnings[0].startswith(
        "p.toml: [project].license is not a valid SPDX license expression (PEP 639): "
    )
    assert repr(license_) in warnings[0]



@pytest.mark.parametrize("license_", [{"text": "MIT License"}, {"file": "LICENSE"}, 1, None, ["MIT"]])
def test_license_warnings_ignores_what_is_not_an_expression(license_: object) -> None:
    assert license_warnings(license_, "p.toml") == []



def test_license_warnings_cannot_check_with_an_old_packaging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(license_module, "canonicalize_license_expression", None)

    assert license_warnings("MIT License", "p.toml") == []



@requires_licenses
def test_extract_metadata_invalid_license_expression_warns(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\nlicense = "MIT License"\n')

    metadata, warnings = extract_metadata(load_pyproject(str(path)), [], str(path))

    assert metadata["license"] == "MIT License"
    assert len(warnings) == 1
    assert warnings[0].startswith(f"{path}: [project].license is not a valid SPDX license expression")



def test_extract_metadata_extras_are_sorted(tmp_path: Path) -> None:
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



def test_extract_metadata_extra_values_are_prepended(tmp_path: Path) -> None:
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
def test_extract_metadata_extras_are_deduplicated(
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



def test_extract_metadata_missing_name(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [project]
        version = "1.2.3"
        """,
    )

    with pytest.raises(MetadataError, match=r"missing required key \[project\]\.name"):
        extract(path)



@pytest.mark.parametrize("dynamic", ['["name"]', '["name", "version"]', '["readme", "name"]'])
def test_extract_metadata_dynamic_name_is_an_error(tmp_path: Path, dynamic: str) -> None:
    path = write_pyproject(tmp_path, f'[project]\nversion = "1.2.3"\ndynamic = {dynamic}\n')

    with pytest.raises(
        MetadataError, match=r"\[project\]\.name is listed in \[project\]\.dynamic.*static name"
    ):
        extract(path)



def test_extract_metadata_static_name_wins_over_dynamic(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\ndynamic = ["name"]\n'
    )

    assert extract(path)["name"] == "coola"



@pytest.mark.parametrize(
    ("project", "match"),
    [
        ('name = 1\nversion = "1.2.3"', r"\[project\]\.name must be a non-empty string, got: 1"),
        ('name = ""\nversion = "1.2.3"', r"\[project\]\.name must be a non-empty string, got: ''"),
        ('name = ["a"]\nversion = "1.2.3"', r"\[project\]\.name must be a non-empty string"),
        ('name = "coola"\nversion = 1.0', r"\[project\]\.version must be a string, got: 1\.0"),
        ('name = "coola"\nversion = 1', r"\[project\]\.version must be a string, got: 1"),
        ('name = "coola"\nversion = true', r"\[project\]\.version must be a string, got: True"),
    ],
)
def test_extract_metadata_name_and_version_must_be_strings(
    tmp_path: Path, project: str, match: str
) -> None:
    path = write_pyproject(tmp_path, f"[project]\n{project}\n")

    with pytest.raises(MetadataError, match=match):
        extract(path)



@pytest.mark.parametrize("content", ["project = 1", 'project = "coola"', "project = []"])
def test_extract_metadata_project_must_be_a_table(tmp_path: Path, content: str) -> None:
    path = write_pyproject(tmp_path, content)

    with pytest.raises(MetadataError, match=r"\[project\] must be a table"):
        extract(path)



def test_extract_metadata_dynamic_version_is_empty_and_warns(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [project]
        name = "coola"
        dynamic = ["version", "readme"]
        """,
    )
    metadata, warnings = extract_metadata(load_pyproject(str(path)), [], str(path))

    assert metadata == {
        "name": "coola",
        "normalized_name": "coola",
        "version": "",
        "normalized_version": "",
        "description": "",
        "readme": "",
        "license": "",
        "license_files": [],
        "authors": [],
        "urls": {},
        "keywords": [],
        "classifiers": [],
        "scripts": {},
        "requires_python": "",
        "extras": [],
        "groups": [],
        "build_backend": "",
        "build_requires": [],
    }
    assert warnings == [f"{path}: [project].version is dynamic, the version output is empty"]



def test_extract_metadata_static_version_wins_over_dynamic(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "coola"\nversion = "1.2.3"\ndynamic = ["version"]\n',
    )
    metadata, warnings = extract_metadata(load_pyproject(str(path)), [], str(path))

    assert metadata["version"] == "1.2.3"
    assert warnings == [
        f"{path}: [project].version is set and also listed in [project].dynamic, "
        "which PEP 621 forbids; the static value is used"
    ]



def test_extract_metadata_static_and_dynamic_fields_warn_once_each(tmp_path: Path) -> None:
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

    _, warnings = extract_metadata(load_pyproject(str(path)), [], str(path))

    assert warnings == [
        f"{path}: [project].dependencies is set and also listed in [project].dynamic, "
        "which PEP 621 forbids; the static value is used",
        f"{path}: [project].version is set and also listed in [project].dynamic, "
        "which PEP 621 forbids; the static value is used",
    ]



def test_extract_metadata_dynamic_fields_that_are_not_set_do_not_warn(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "coola"\nversion = "1"\ndynamic = ["readme", "license"]\n'
    )

    _, warnings = extract_metadata(load_pyproject(str(path)), [], str(path))

    assert warnings == []



def test_extract_metadata_missing_version_with_other_dynamic_fields(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\ndynamic = ["readme"]\n')

    with pytest.raises(MetadataError, match=r"missing required key \[project\]\.version"):
        extract(path)



@pytest.mark.parametrize("value", ["[1]", '["readme", 2]', '[["version"]]', "[true]"])
def test_extract_metadata_dynamic_must_contain_only_strings(tmp_path: Path, value: str) -> None:
    path = write_pyproject(
        tmp_path, f'[project]\nname = "coola"\nversion = "1"\ndynamic = {value}\n'
    )

    with pytest.raises(MetadataError, match=r"\[project\]\.dynamic must contain only strings"):
        extract(path)



@pytest.mark.parametrize("value", ['"version"', "1", '{a = "version"}'])
def test_extract_metadata_dynamic_must_be_an_array(tmp_path: Path, value: str) -> None:
    path = write_pyproject(
        tmp_path, f'[project]\nname = "coola"\nversion = "1"\ndynamic = {value}\n'
    )

    with pytest.raises(MetadataError, match=r"\[project\]\.dynamic must be an array"):
        extract(path)



def test_extract_metadata_missing_version(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [project]
        name = "coola"
        """,
    )

    with pytest.raises(MetadataError, match=r"missing required key \[project\]\.version"):
        extract(path)



def test_extract_metadata_invalid_extra_values_json(tmp_path: Path) -> None:
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



def test_extract_metadata_extra_values_not_a_list(tmp_path: Path) -> None:
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
def test_extract_metadata_extra_values_must_be_strings(tmp_path: Path, value: str) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')

    with pytest.raises(MetadataError, match="extra-values must be a JSON array of strings"):
        extract(path, value)



def test_extract_metadata_special_characters_round_trip(tmp_path: Path) -> None:
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
    [
        ([], "[]"),
        ({}, "{}"),
        (["a", "b"], '["a","b"]'),
        ({"a": [1, None], "b": {"c": True}}, '{"a":[1,null],"b":{"c":true}}'),
        (["é", "日本"], '["é","日本"]'),
        (['say "hi"\n'], '["say \\"hi\\"\\n"]'),
    ],
)
def test_compact_json(value: object, expected: str) -> None:
    assert output_github_module._compact_json(value) == expected



@pytest.mark.parametrize("value", [[], ["a"], ["a", "B_c>=1"]])
def test_check_string_array_returns_the_strings(value: list[str]) -> None:
    assert check_string_array(value, "[x]", "p.toml") == value



@pytest.mark.parametrize(
    ("value", "match"),
    [
        ("a", r"^p\.toml: \[x\] must be an array, got: 'a'"),
        (["a", 2], r"^p\.toml: \[x\] must contain only strings, got: 2$"),
        ([["a"]], r"^p\.toml: \[x\] must contain only strings, got: \['a'\]$"),
    ],
)
def test_check_string_array_wrong_types(value: object, match: str) -> None:
    with pytest.raises(MetadataError, match=match):
        check_string_array(value, "[x]", "p.toml")



@pytest.mark.parametrize(
    ("value", "expected"),
    [("[]", []), ('["a"]', ["a"]), ('["a", "B_c"]', ["a", "B_c"]), ('["a", "a"]', ["a", "a"])],
)
def test_parse_string_array(value: str, expected: list[str]) -> None:
    assert parse_string_array(value, "dependencies") == expected



@pytest.mark.parametrize("value", ["not json", ""])
def test_parse_string_array_invalid_json(value: str) -> None:
    with pytest.raises(MetadataError, match=r"^extra-values is not valid JSON: "):
        parse_string_array(value, "extra-values")



@pytest.mark.parametrize("value", ['{"a": 1}', '"a"', "1", "null", "[1]", '["a", null]', '[["a"]]'])
def test_parse_string_array_not_an_array_of_strings(value: str) -> None:
    with pytest.raises(MetadataError, match=r"^extra-values must be a JSON array of strings, got: "):
        parse_string_array(value, "extra-values")



@pytest.mark.parametrize(
    ("optional_dependencies", "expected"),
    [
        ('Foo_Bar = []\n"foo-bar" = []', ["Foo_Bar"]),
        ('"foo-bar" = []\nFoo_Bar = []', ["foo-bar"]),
        ('Foo = []\nfoo = []\nFOO = []', ["Foo"]),
        ('"a.b" = []\n"a-b" = []\n"a__b" = []', ["a.b"]),
    ],
)
def test_extract_metadata_extras_spellings_of_the_same_extra_are_one(
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
def test_extract_metadata_extra_values_are_deduplicated_per_pep_685(
    tmp_path: Path, extra_values_json: str, expected: list[str]
) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "p"\nversion = "1"\n[project.optional-dependencies]\nfoo_bar = []\nbaz = []\n',
    )

    assert extract(path, extra_values_json)["extras"] == expected



def test_extract_metadata_extras_are_sorted_by_normalized_name(tmp_path: Path) -> None:
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
    ["1", "1.2.3", "0.1.0.dev3", "1.0rc1", "2024.1.post2", "1!2.0", "1.0.0rc1+build.5", "v1.2", "1.0-1"],
)
def test_extract_metadata_valid_pep_440_versions(tmp_path: Path, version: str) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "p"\nversion = "{version}"\n')

    assert extract(path)["version"] == version



@pytest.mark.parametrize("version", ["", "latest", "1.2.x", "one", "1..2", "1.2.3 beta", "^1.2"])
def test_extract_metadata_invalid_pep_440_version(tmp_path: Path, version: str) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "p"\nversion = "{version}"\n')

    message = f"{path.name}: [project].version is not a valid PEP 440 version: {version!r}"
    with pytest.raises(MetadataError, match=re.escape(message)):
        extract(path)



def test_extract_metadata_dynamic_version_is_not_validated(tmp_path: Path) -> None:
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
def test_extract_metadata_normalized_name(tmp_path: Path, name: str, expected: str) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "{name}"\nversion = "1"\n')

    metadata = extract(path)

    assert metadata["name"] == name
    assert metadata["normalized_name"] == expected



def test_get_table() -> None:
    assert get_table({"project": {"name": "a"}}, "project", "[project]", "p.toml") == {"name": "a"}



@pytest.mark.parametrize("container", [{}, {"other": 1}])
def test_get_table_absent_is_empty(container: dict) -> None:
    assert get_table(container, "project", "[project]", "p.toml") == {}



@pytest.mark.parametrize("value", [1, "text", [], [{"a": 1}]])
def test_get_table_not_a_table(value: object) -> None:
    with pytest.raises(MetadataError, match=r"^p.toml: \[project\] must be a table, got: "):
        get_table({"project": value}, "project", "[project]", "p.toml")



@pytest.mark.parametrize("value", ["text", ""])
def test_check_str(value: str) -> None:
    assert check_str(value, "[x]", "p.toml") == value



@pytest.mark.parametrize(
    ("value", "shown"), [(1, "1"), (None, "None"), (["a"], "\\['a'\\]"), ({"a": 1}, "\\{'a': 1\\}")]
)
def test_check_str_not_a_string(value: object, shown: str) -> None:
    with pytest.raises(MetadataError, match=rf"^p.toml: \[x\] must be a string, got: {shown}$"):
        check_str(value, "[x]", "p.toml")



def test_check_array() -> None:
    assert check_array(["a", 1], "[x]", "p.toml") == ["a", 1]



@pytest.mark.parametrize("value", [{}, "text", 1])
def test_check_array_not_an_array(value: object) -> None:
    with pytest.raises(MetadataError, match=r"^p.toml: \[x\] must be an array, got: "):
        check_array(value, "[x]", "p.toml")



def test_required_name() -> None:
    assert _required_name({"name": 1}, [], "p.toml") == 1



def test_required_name_missing() -> None:
    with pytest.raises(MetadataError, match=r"^p.toml is missing required key \[project\].name$"):
        _required_name({}, ["version"], "p.toml")



def test_required_name_dynamic() -> None:
    with pytest.raises(MetadataError, match=r"^p.toml: \[project\].name is listed in .*static name$"):
        _required_name({}, ["name"], "p.toml")



def test_static_and_dynamic_warnings() -> None:
    project = {"name": "a", "version": "1", "description": "d"}

    assert _static_and_dynamic_warnings(project, ["version", "readme", "version", "name"], "p.toml") == [
        "p.toml: [project].version is set and also listed in [project].dynamic, "
        "which PEP 621 forbids; the static value is used",
        "p.toml: [project].name is set and also listed in [project].dynamic, "
        "which PEP 621 forbids; the static value is used",
    ]



def test_static_and_dynamic_warnings_none() -> None:
    assert _static_and_dynamic_warnings({"name": "a"}, ["version"], "p.toml") == []



def test_required_version_static() -> None:
    assert _required_version({"version": "1.0"}, [], "p.toml", False) == ("1.0", [])



def test_required_version_is_returned_whatever_its_type() -> None:
    assert _required_version({"version": 1.0}, [], "p.toml", True) == (1.0, [])



def test_required_version_dynamic_warns() -> None:
    assert _required_version({}, ["version"], "p.toml", False) == (
        "",
        ["p.toml: [project].version is dynamic, the version output is empty"],
    )



def test_required_version_dynamic_fails_when_requested() -> None:
    with pytest.raises(MetadataError, match=r"^p.toml: \[project\].version is dynamic, so it cannot be read"):
        _required_version({}, ["version"], "p.toml", True)



def test_required_version_missing() -> None:
    with pytest.raises(MetadataError, match=r"^p.toml is missing required key \[project\].version$"):
        _required_version({}, ["readme"], "p.toml", False)



@pytest.mark.parametrize("name", ["a", "My_Package.Name", "a-b", "a1"])
def test_valid_name(name: str) -> None:
    assert _valid_name(name, "p.toml") == name



@pytest.mark.parametrize("name", [1, "", None, ["a"]])
def test_valid_name_not_a_non_empty_string(name: object) -> None:
    with pytest.raises(MetadataError, match=r"^p.toml: \[project\].name must be a non-empty string, got: "):
        _valid_name(name, "p.toml")



@pytest.mark.parametrize("name", ["my pkg", "-a", "a-", "_a", "a.", "a/b"])
def test_valid_name_not_a_project_name(name: str) -> None:
    with pytest.raises(MetadataError, match=r"^p.toml: \[project\].name is not a valid project name"):
        _valid_name(name, "p.toml")



@pytest.mark.parametrize(
    ("version", "expected"), [("1.0-RC1", "1.0rc1"), ("1.2.3", "1.2.3"), ("v1.0", "1.0")]
)
def test_valid_version_static(version: str, expected: str) -> None:
    assert _valid_version(version, True, "p.toml") == (version, expected)



def test_valid_version_dynamic() -> None:
    assert _valid_version("", False, "p.toml") == ("", "")



def test_valid_version_not_a_string() -> None:
    with pytest.raises(MetadataError, match=r"^p.toml: \[project\].version must be a string, got: 1.0$"):
        _valid_version(1.0, True, "p.toml")



def test_valid_version_invalid() -> None:
    with pytest.raises(MetadataError, match=r"^p.toml: \[project\].version is not a valid PEP 440 version: 'latest'$"):
        _valid_version("latest", True, "p.toml")



def test_extra_names() -> None:
    project = {"optional-dependencies": {"b": [], "A_x": [], "a-x": []}}

    assert read_extra_names(project, ["", "b"], "p.toml") == ["", "b", "A_x"]



@pytest.mark.parametrize(
    "name",
    ["a", "A", "7", "coola", "My_Package.Name", "a-b", "a_b", "a.b", "a--b__c..d", "zope.interface", "x9"],
)
def test_extract_metadata_valid_names(tmp_path: Path, name: str) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "{name}"\nversion = "1"\n')

    assert extract(path)["name"] == name



@pytest.mark.parametrize(
    "name",
    ["my pkg", "my pkg!", "-a", "a-", "_a", "a_", ".a", "a.", "a/b", "a@b", "ÄB", "a\\nb", " a", "a ", "a\\n"],
)
def test_extract_metadata_invalid_names(tmp_path: Path, name: str) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "{name}"\nversion = "1"\n')

    with pytest.raises(MetadataError, match=r"\[project\]\.name is not a valid project name"):
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
def test_extract_metadata_normalized_version(tmp_path: Path, version: str, expected: str) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "a"\nversion = "{version}"\n')

    metadata = extract(path)

    assert (metadata["version"], metadata["normalized_version"]) == (version, expected)



def test_extract_metadata_normalized_version_is_empty_when_the_version_is_dynamic(
    tmp_path: Path,
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\ndynamic = ["version"]\n')

    assert extract(path)["normalized_version"] == ""



@pytest.mark.parametrize(
    ("readme", "expected"),
    [
        ('readme = "README.md"', "README.md"),
        ('readme = "docs/README.rst"', "docs/README.rst"),
        ('readme = ""', ""),
        ('readme = {file = "README.rst", content-type = "text/x-rst"}', "README.rst"),
        ('readme = {text = "Inline readme", content-type = "text/plain"}', ""),
        ("readme = {}", ""),
        ('dynamic = ["readme"]', ""),
        ("", ""),
    ],
)
def test_extract_metadata_readme(tmp_path: Path, readme: str, expected: str) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "a"\nversion = "1"\n{readme}\n')

    assert extract(path)["readme"] == expected



@pytest.mark.parametrize(
    ("readme", "match"),
    [
        ("readme = 1", r"\[project\]\.readme must be a string or a table, got: 1"),
        ('readme = ["README.md"]', r"\[project\]\.readme must be a string or a table"),
        ("readme = true", r"\[project\]\.readme must be a string or a table, got: True"),
        ("readme = {file = 1}", r"\[project\]\.readme\.file must be a string, got: 1"),
        ('readme = {file = ["a"]}', r"\[project\]\.readme\.file must be a string"),
    ],
)
def test_extract_metadata_readme_must_be_a_string_or_a_table(
    tmp_path: Path, readme: str, match: str
) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "a"\nversion = "1"\n{readme}\n')

    with pytest.raises(MetadataError, match=match):
        extract(path)



@pytest.mark.parametrize(
    ("license_", "expected"),
    [
        ('license = "MIT"', "MIT"),
        ('license = "Apache-2.0 OR MIT"', "Apache-2.0 OR MIT"),
        ('license = ""', ""),
        ('license = {text = "BSD-3-Clause"}', "BSD-3-Clause"),
        ('license = {text = "Line one\\nline two"}', "Line one\nline two"),
        ('license = {file = "LICENSE"}', ""),
        ('license = {file = "LICENSE", text = "MIT"}', "MIT"),
        ("license = {}", ""),
        ('dynamic = ["license"]', ""),
        ("", ""),
    ],
)
def test_extract_metadata_license(tmp_path: Path, license_: str, expected: str) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "a"\nversion = "1"\n{license_}\n')

    assert extract(path)["license"] == expected



@pytest.mark.parametrize(
    ("license_", "match"),
    [
        ("license = 1", r"\[project\]\.license must be a string or a table, got: 1"),
        ('license = ["MIT"]', r"\[project\]\.license must be a string or a table"),
        ("license = {text = 1}", r"\[project\]\.license\.text must be a string, got: 1"),
        ("license = {text = true}", r"\[project\]\.license\.text must be a string, got: True"),
        ("license = {file = 2}", r"\[project\]\.license\.file must be a string, got: 2"),
    ],
)
def test_extract_metadata_license_must_be_a_string_or_a_table(
    tmp_path: Path, license_: str, match: str
) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "a"\nversion = "1"\n{license_}\n')

    with pytest.raises(MetadataError, match=match):
        extract(path)



@pytest.mark.parametrize(
    ("authors", "expected"),
    [
        ("", []),
        ("authors = []", []),
        ('authors = [{name = "Ada"}]', [{"name": "Ada"}]),
        ('authors = [{email = "ada@example.com"}]', [{"email": "ada@example.com"}]),
        (
            'authors = [{email = "a@b.c", name = "Ada"}, {name = "Bob"}]',
            [{"name": "Ada", "email": "a@b.c"}, {"name": "Bob"}],
        ),
        ('authors = [{name = "Ada", url = "x"}]', [{"name": "Ada"}]),
        ("authors = [{}]", [{}]),
        ('authors = [{name = "Ada"}, {name = "Ada"}]', [{"name": "Ada"}, {"name": "Ada"}]),
        ('dynamic = ["authors"]', []),
    ],
)
def test_extract_metadata_authors(
    tmp_path: Path, authors: str, expected: list[dict[str, str]]
) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "a"\nversion = "1"\n{authors}\n')

    assert extract(path)["authors"] == expected



@pytest.mark.parametrize(
    ("authors", "match"),
    [
        ('authors = "Ada"', r"\[project\]\.authors must be an array, got: 'Ada'"),
        ('authors = {name = "Ada"}', r"\[project\]\.authors must be an array"),
        ('authors = ["Ada"]', r"\[project\]\.authors\[0\] must be a table, got: 'Ada'"),
        ('authors = [{name = "a"}, 1]', r"\[project\]\.authors\[1\] must be a table, got: 1"),
        ("authors = [{name = 1}]", r"\[project\]\.authors\[0\]\.name must be a string, got: 1"),
        (
            'authors = [{name = "a", email = ["b"]}]',
            r"\[project\]\.authors\[0\]\.email must be a string",
        ),
    ],
)
def test_extract_metadata_authors_must_be_an_array_of_tables(
    tmp_path: Path, authors: str, match: str
) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "a"\nversion = "1"\n{authors}\n')

    with pytest.raises(MetadataError, match=match):
        extract(path)



@pytest.mark.parametrize(
    ("urls", "expected"),
    [
        ("", {}),
        ("[project.urls]", {}),
        ('[project.urls]\nHomepage = "https://a.org"', {"Homepage": "https://a.org"}),
        (
            '[project.urls]\nSource = "https://a.org/s"\n"Bug Tracker" = "https://a.org/b"\n'
            'Homepage = "https://a.org"',
            {"Source": "https://a.org/s", "Bug Tracker": "https://a.org/b", "Homepage": "https://a.org"},
        ),
        ('[project.urls]\nHomepage = ""', {"Homepage": ""}),
    ],
)
def test_extract_metadata_urls(tmp_path: Path, urls: str, expected: dict[str, str]) -> None:
    path = write_pyproject(tmp_path, f'[project]\nname = "a"\nversion = "1"\n{urls}\n')

    assert extract(path)["urls"] == expected



def test_extract_metadata_urls_keep_the_order_of_the_file(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "a"\nversion = "1"\n[project.urls]\nZ = "z"\nA = "a"\nM = "m"\n',
    )

    assert list(extract(path)["urls"]) == ["Z", "A", "M"]



@pytest.mark.parametrize(
    ("urls", "match"),
    [
        ("urls = 1", r"\[project\.urls\] must be a table, got: 1"),
        ('urls = ["https://a.org"]', r"\[project\.urls\] must be a table"),
        ("[project.urls]\nHomepage = 1", r"\[project\.urls\]\.Homepage must be a string, got: 1"),
        (
            '[project.urls]\nHomepage = ["https://a.org"]',
            r"\[project\.urls\]\.Homepage must be a string",
        ),
    ],
)
def test_extract_metadata_urls_must_be_a_table_of_strings(
    tmp_path: Path, urls: str, match: str
) -> None:
    # An inline "urls = ..." must come before any table header.
    content = f'[project]\nname = "a"\nversion = "1"\n{urls}\n'
    path = write_pyproject(tmp_path, content)

    with pytest.raises(MetadataError, match=match):
        extract(path)



def test_extract_metadata_fail_on_dynamic_version_raises() -> None:
    data = {"project": {"name": "a", "dynamic": ["version"]}}

    with pytest.raises(MetadataError, match=r"^p.toml: \[project\]\.version is dynamic, so it cannot be read"):
        extract_metadata(data, [], "p.toml", fail_on_dynamic_version=True)



def test_extract_metadata_fail_on_dynamic_version_accepts_a_static_version() -> None:
    data = {"project": {"name": "a", "version": "1.0", "dynamic": ["version"]}}

    metadata, warnings = extract_metadata(data, [], "p.toml", fail_on_dynamic_version=True)

    assert metadata["version"] == "1.0"
    assert warnings == [
        "p.toml: [project].version is set and also listed in [project].dynamic, "
        "which PEP 621 forbids; the static value is used"
    ]



def test_extract_metadata_dynamic_version_warns_by_default() -> None:
    data = {"project": {"name": "a", "dynamic": ["version"]}}

    metadata, warnings = extract_metadata(data, [], "p.toml", fail_on_dynamic_version=False)

    assert metadata["version"] == ""
    assert warnings == ["p.toml: [project].version is dynamic, the version output is empty"]
