from __future__ import annotations

import argparse
import json
import importlib.util
import re
import runpy
import subprocess
import sys
from pathlib import Path

import pytest
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import extract_metadata as extract_metadata_module  # noqa: E402
from extract_metadata import (  # noqa: E402
    Metadata,
    Options,
    MetadataError,
    Report,
    build_report,
    emit_github_output,
    DEFAULT_PYTHON_CANDIDATES,
    check_no_missing_dependency,
    extract_dependency_requirements,
    extract_dependency_specifiers,
    _candidate_requirements,
    _check_array,
    _check_string_array,
    _conflict_warnings,
    _dynamic_dependency_fields,
    _flatten_group,
    _index_dependencies,
    _index_requirements,
    _requirements_from_index,
    _specifiers_from_index,
    _get_table,
    compatible_python_versions,
    escape_annotation,
    escape_annotation_property,
    format_error,
    format_error_summary,
    extract_metadata,
    extract_project_dependencies,
    format_outputs,
    format_step_summary,
    format_summary,
    load_pyproject,
    highest_python_version,
    lowest_python_version,
    main,
    parse_bool,
    parse_options,
    parse_python_candidates,
    parse_string_array,
    resolve_step_summary,
    write_github_output,
    write_step_summary,
)

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "extract_metadata.py"
RUN_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run.sh"
REQUIREMENTS_PATH = Path(__file__).resolve().parents[1] / "scripts" / "requirements.txt"


def write_pyproject(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "pyproject.toml"
    path.write_text(content)
    return path


def extract(path: Path, extra_values_json: str = "[]") -> dict:
    """Load ``path`` and extract its metadata."""
    metadata, _ = extract_metadata(
        load_pyproject(str(path)), parse_string_array(extra_values_json, "extra-values"), str(path)
    )
    return metadata


def specifiers(path: Path, dependencies_json: str) -> dict:
    """Load ``path`` and extract the specifiers of the requested dependencies."""
    result, _ = extract_dependency_specifiers(
        load_pyproject(str(path)), parse_string_array(dependencies_json, "dependencies"), str(path)
    )
    return result


def test_load_pyproject(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')

    assert load_pyproject(str(path)) == {"project": {"name": "coola", "version": "1.2.3"}}


def test_load_pyproject_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.toml"

    with pytest.raises(MetadataError, match="pyproject.toml not found at: .*does-not-exist.toml"):
        load_pyproject(str(missing))


def test_load_pyproject_invalid_toml(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, "this is not [valid toml")

    with pytest.raises(MetadataError, match="pyproject.toml is not valid TOML"):
        load_pyproject(str(path))


def test_load_pyproject_invalid_utf8(tmp_path: Path) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_bytes(b'[project]\nname = "caf\xe9"\n')

    with pytest.raises(MetadataError, match="pyproject.toml is not valid UTF-8"):
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


def test_main_returns_one_for_an_invalid_utf8_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_bytes(b"\xff\xfe")

    assert main(["extract_metadata.py", str(path), "[]"]) == 1
    assert "is not valid UTF-8" in capsys.readouterr().err


def test_write_github_output_unwritable_file(tmp_path: Path) -> None:
    with pytest.raises(MetadataError, match="cannot write the outputs to .*: "):
        write_github_output(str(tmp_path), {"name": "coola"})


def test_write_step_summary_unwritable_file(tmp_path: Path) -> None:
    with pytest.raises(MetadataError, match="cannot write the job summary to .*: "):
        write_step_summary(str(tmp_path), "# Title\n")


def test_main_returns_one_when_the_outputs_cannot_be_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')

    exit_code = main(["extract_metadata.py", "--github-output", str(tmp_path), str(path), "[]"])

    assert exit_code == 1
    assert "::error file=" in capsys.readouterr().err


def test_main_returns_one_when_the_job_summary_cannot_be_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path))
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')

    exit_code = main(["extract_metadata.py", "--step-summary", "true", str(path), "[]"])

    assert exit_code == 1
    assert "cannot write the job summary" in capsys.readouterr().err


def test_main_reports_the_error_once_when_the_job_summary_cannot_be_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path))
    path = write_pyproject(tmp_path, '[project]\nversion = "1"\n')

    exit_code = main(["extract_metadata.py", "--step-summary", "true", str(path), "[]"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "missing required key" in err
    assert "cannot write the job summary" not in err


def test_extract_metadata_error_names_the_file() -> None:
    with pytest.raises(MetadataError, match=r"custom/pyproject.toml is missing required key"):
        _, warnings = extract_metadata({"project": {"version": "1"}}, [], "custom/pyproject.toml")


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
        "authors": [],
        "urls": {},
        "requires_python": "",
        "extras": [],
        "groups": [],
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


def test_main_description_in_json_and_github_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\ndescription = "Two\\nlines"\n'
    )
    output = tmp_path / "github_output"

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["description"] == "Two\nlines"
    assert main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"]) == 0
    assert parse_github_output(output.read_text(encoding="utf-8"))["description"] == "Two\nlines"
    assert "description=" not in capsys.readouterr().out


def test_main_json_keeps_non_ascii_characters(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\ndescription = "Héllo ✓"\n'
    )

    assert main(["extract_metadata.py", str(path), "[]"]) == 0

    out = capsys.readouterr().out
    assert '"description": "Héllo ✓"' in out
    assert "\\u" not in out


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
        "authors": [],
        "urls": {},
        "requires_python": "",
        "extras": [],
        "groups": [],
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


def test_main_strict_fails_on_a_static_and_dynamic_field(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "coola"\nversion = "1"\ndynamic = ["version"]\n'
    )

    assert main(["extract_metadata.py", "--strict", "true", str(path), "[]"]) == 1
    assert "[project].version is set and also listed in [project].dynamic" in capsys.readouterr().err


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


def test_main_dynamic_version_warning_in_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\ndynamic = ["version"]\n')

    exit_code = main(["extract_metadata.py", str(path), "[]"])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "name": "coola",
        "normalized_name": "coola",
        "version": "",
        "normalized_version": "",
        "description": "",
        "readme": "",
        "license": "",
        "authors": [],
        "urls": {},
        "requires_python": "",
        "extras": [],
        "groups": [],
        "python_versions": ["3.10", "3.11", "3.12", "3.13", "3.14"],
        "python_min": "3.10",
    "python_max": "3.14",
        "python_max": "3.14",
        "project_dependencies": {},
        "dependency_specifiers": {},
        "dependency_requirements": {},
        "warnings": [f"{path}: [project].version is dynamic, the version output is empty"],
        "schema_version": 1,
    }


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


def test_main_prints_json_to_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [project]
        name = "coola"
        version = "1.2.3"
        """,
    )

    exit_code = main(["extract_metadata.py", str(path), "[]"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert json.loads(captured.out) == {
        "name": "coola",
        "normalized_name": "coola",
        "version": "1.2.3",
        "normalized_version": "1.2.3",
        "description": "",
        "readme": "",
        "license": "",
        "authors": [],
        "urls": {},
        "requires_python": "",
        "extras": [],
        "groups": [],
        "python_versions": ["3.10", "3.11", "3.12", "3.13", "3.14"],
        "python_min": "3.10",
    "python_max": "3.14",
        "python_max": "3.14",
        "project_dependencies": {},
        "dependency_specifiers": {},
        "dependency_requirements": {},
        "warnings": [],
        "schema_version": 1,
    }


def test_main_parses_the_file_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')
    calls: list[str] = []

    def counting_load(pyproject_path: str) -> dict:
        calls.append(pyproject_path)
        return load_pyproject(pyproject_path)

    monkeypatch.setattr(extract_metadata_module, "load_pyproject", counting_load)

    exit_code = main(["extract_metadata.py", str(path), "[]", '["numpy"]'])
    capsys.readouterr()

    assert exit_code == 0
    assert calls == [str(path)]


def test_main_returns_nonzero_on_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "does-not-exist.toml"

    exit_code = main(["extract_metadata.py", str(missing), "[]"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "not found" in captured.err


def test_main_returns_usage_error_on_bad_args() -> None:
    exit_code = main(["extract_metadata.py"])

    assert exit_code == 2


def test_cli_end_to_end(tmp_path: Path) -> None:
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

    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT_PATH), str(path), '[""]'],
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(result.stdout) == {
        "name": "coola",
        "normalized_name": "coola",
        "version": "1.2.3",
        "normalized_version": "1.2.3",
        "description": "",
        "readme": "",
        "license": "",
        "authors": [],
        "urls": {},
        "requires_python": "",
        "extras": ["", "numpy"],
        "groups": [],
        "python_versions": ["3.10", "3.11", "3.12", "3.13", "3.14"],
        "python_min": "3.10",
    "python_max": "3.14",
        "python_max": "3.14",
        "project_dependencies": {},
        "dependency_specifiers": {},
        "dependency_requirements": {},
        "warnings": [],
        "schema_version": 1,
    }


def test_cli_end_to_end_error_exit_code(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.toml"

    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT_PATH), str(missing), "[]"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "not found" in result.stderr


DEPS_TOML = """
[project]
name = "p"
version = "1"
dependencies = ["Foo_Bar>=1,<2; python_version>'3'", "nospec", "withextra[x]>=3"]

[project.optional-dependencies]
a = ["extra-pkg~=2.0", "dup>=1"]

[dependency-groups]
base = ["grp-pkg==1.0"]
dev = [{include-group = "base"}, "dev-pkg>=0.1"]
other = ["dup>=2"]
"""


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


def test_main_outputs_warnings_in_json_and_nothing_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)

    exit_code = main(["extract_metadata.py", str(path), "[]", '["dup"]'])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert json.loads(captured.out)["warnings"] == [
        f"dup has different specifiers in {path}: ['>=1', '>=2']; using '>=1'"
    ]
    assert captured.err == ""


INVALID_TOML = """
[project]
name = "p"
version = "1"
dependencies = ["good>=1", "bad requirement!!"]

[project.optional-dependencies]
a = ["also bad>>"]

[dependency-groups]
dev = ["oops==", "dev-pkg>=2"]
"""


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


METADATA = {
    "name": "coola",
    "normalized_name": "coola",
    "version": "1.2.3",
    "normalized_version": "1.2.3",
    "description": "",
    "readme": "",
    "license": "",
    "authors": [],
    "urls": {},
    "requires_python": ">=3.10",
    "extras": ["", "numpy"],
    "groups": ["dev", "test"],
    "python_versions": ["3.10", "3.11", "3.12", "3.13", "3.14"],
    "python_min": "3.10",
    "python_max": "3.14",
    "project_dependencies": {"numpy": ">=1", "Foo_Bar": ""},
    "dependency_specifiers": {"numpy": ">=1", "missing": None},
    "dependency_requirements": {
        "numpy": [{"specifier": ">=1", "marker": ""}],
        "missing": [],
    },
    "warnings": [],
    "schema_version": 1,
}


def test_format_outputs() -> None:
    assert format_outputs(METADATA) == {
        "name": "coola",
        "normalized-name": "coola",
        "version": "1.2.3",
        "normalized-version": "1.2.3",
        "description": "",
        "readme": "",
        "license": "",
        "authors": '[]',
        "urls": '{}',
        "requires-python": ">=3.10",
        "extras": '["","numpy"]',
        "groups": '["dev","test"]',
        "python-versions": '["3.10","3.11","3.12","3.13","3.14"]',
        "python-min": "3.10",
        "python-max": "3.14",
        "python-matrix": '{"python-version":["3.10","3.11","3.12","3.13","3.14"]}',
        "project-dependencies": '{"numpy":">=1","Foo_Bar":""}',
        "dependency-specifiers": '{"numpy":">=1","missing":null}',
        "dependency-requirements": '{"numpy":[{"specifier":">=1","marker":""}],"missing":[]}',
    }


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
    assert extract_metadata_module._compact_json(value) == expected


def test_format_outputs_keeps_non_ascii_characters() -> None:
    metadata = {**METADATA, "extras": ["é"], "dependency_specifiers": {}}

    assert format_outputs(metadata)["extras"] == '["é"]'


def parse_github_output(text: str) -> dict[str, str]:
    """Parse a ``$GITHUB_OUTPUT`` file like the runner does (``k=v`` and ``k<<DELIM``)."""
    outputs: dict[str, str] = {}
    lines = iter(text.split("\n")[:-1])
    for line in lines:
        if "<<" in line and ("=" not in line or line.index("<<") < line.index("=")):
            key, delimiter = line.split("<<", 1)
            value_lines: list[str] = []
            for value_line in lines:
                if value_line == delimiter:
                    break
                value_lines.append(value_line)
            else:
                msg = f"unterminated value for {key}"
                raise AssertionError(msg)
            outputs[key] = "\n".join(value_lines)
        else:
            key, value = line.split("=", 1)
            outputs[key] = value
    return outputs


@pytest.fixture
def fixed_delimiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extract_metadata_module, "_new_delimiter", lambda: "DELIM")


@pytest.mark.usefixtures("fixed_delimiter")
def test_write_github_output(tmp_path: Path) -> None:
    output = tmp_path / "github_output"

    write_github_output(str(output), {"name": "coola", "version": "", "extras": "[]"})

    assert output.read_text(encoding="utf-8") == (
        "name<<DELIM\ncoola\nDELIM\nversion<<DELIM\n\nDELIM\nextras<<DELIM\n[]\nDELIM\n"
    )


@pytest.mark.usefixtures("fixed_delimiter")
def test_write_github_output_appends(tmp_path: Path) -> None:
    output = tmp_path / "github_output"
    output.write_text("previous=step\n", encoding="utf-8")

    write_github_output(str(output), {"name": "coola"})

    assert output.read_text(encoding="utf-8") == "previous=step\nname<<DELIM\ncoola\nDELIM\n"


@pytest.mark.parametrize(
    "value",
    ["a\nb", "a\r\nb", "evil\nversion=hacked", "trailing\n", "\n\n", "x<<y", "k=v", "é\n"],
)
def test_write_github_output_round_trips_any_value(tmp_path: Path, value: str) -> None:
    output = tmp_path / "github_output"

    write_github_output(str(output), {"name": value, "version": "1"})

    assert parse_github_output(output.read_bytes().decode("utf-8")) == {
        "name": value,
        "version": "1",
    }


def test_write_github_output_picks_a_delimiter_not_in_the_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    delimiters = iter(["BAD", "GOOD"])
    monkeypatch.setattr(extract_metadata_module, "_new_delimiter", lambda: next(delimiters))
    output = tmp_path / "github_output"

    write_github_output(str(output), {"name": "xBADx"})

    assert output.read_text(encoding="utf-8") == "name<<GOOD\nxBADx\nGOOD\n"


def test_new_delimiter_is_random_and_not_guessable() -> None:
    first, second = extract_metadata_module._new_delimiter(), extract_metadata_module._new_delimiter()

    assert first != second
    assert first.startswith("ghadelimiter_")
    assert len(first) > 32


def test_main_github_output_writes_outputs_and_annotations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    output = tmp_path / "github_output"

    exit_code = main(
        [
            "extract_metadata.py",
            "--github-output",
            str(output),
            str(path),
            '[""]',
            '["dup", "nospec", "missing"]',
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert parse_github_output(output.read_text(encoding="utf-8")) == {
        "name": "p",
        "normalized-name": "p",
        "version": "1",
        "normalized-version": "1",
        "description": "",
        "readme": "",
        "license": "",
        "authors": '[]',
        "urls": '{}',
        "requires-python": "",
        "extras": '["","a"]',
        "groups": '["base","dev","other"]',
        "python-versions": '["3.10","3.11","3.12","3.13","3.14"]',
        "python-min": "3.10",
        "python-max": "3.14",
        "python-matrix": '{"python-version":["3.10","3.11","3.12","3.13","3.14"]}',
        "project-dependencies": '{"Foo_Bar":"<2,>=1","nospec":"","withextra":">=3"}',
        "dependency-specifiers": '{"dup":">=1","nospec":"","missing":null}',
        "dependency-requirements": (
            '{"dup":[{"specifier":">=1","marker":""},{"specifier":">=2","marker":""}],'
            '"nospec":[{"specifier":"","marker":""}],"missing":[]}'
        ),
    }
    assert captured.out == (
        f"::warning file={path}::dup has different specifiers in {path}: ['>=1', '>=2']; using '>=1'\n"
        "📦 name=p version=1 requires-python= "
        'python-versions=["3.10","3.11","3.12","3.13","3.14"] python-min=3.10 python-max=3.14 extras=["","a"] '
        'groups=["base","dev","other"] '
        'project-dependencies={"Foo_Bar":"<2,>=1","nospec":"","withextra":">=3"} '
        'dependency-specifiers={"dup":">=1","nospec":"","missing":null}\n'
    )
    assert captured.err == ""


def parse_args(*argv: str) -> argparse.Namespace:
    """Parse a command line like ``main`` does."""
    return extract_metadata_module._build_parser("extract_metadata.py").parse_args(list(argv))


def test_build_report(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)

    report = build_report(parse_args(str(path), '[""]', '["dup", "missing"]'))

    assert report == {
        "name": "p",
        "normalized_name": "p",
        "version": "1",
        "normalized_version": "1",
        "description": "",
        "readme": "",
        "license": "",
        "authors": [],
        "urls": {},
        "requires_python": "",
        "extras": ["", "a"],
        "groups": ["base", "dev", "other"],
        "python_versions": ["3.10", "3.11", "3.12", "3.13", "3.14"],
        "python_min": "3.10",
    "python_max": "3.14",
        "python_max": "3.14",
        "project_dependencies": {"Foo_Bar": "<2,>=1", "nospec": "", "withextra": ">=3"},
        "dependency_specifiers": {"dup": ">=1", "missing": None},
        "dependency_requirements": {
            "dup": [{"specifier": ">=1", "marker": ""}, {"specifier": ">=2", "marker": ""}],
            "missing": [],
        },
        "warnings": [f"dup has different specifiers in {path}: ['>=1', '>=2']; using '>=1'"],
        "schema_version": 1,
    }


@pytest.mark.parametrize(
    ("argv", "match"),
    [
        (["--fail-on-missing", "maybe", "{path}", "[]"], r"fail-on-missing must be 'true' or 'false'"),
        (["--fail-on-dynamic-version", "maybe", "{path}", "[]"], r"fail-on-dynamic-version must be"),
        (["--python-candidates", "[3]", "{path}", "[]"], r"python-candidates must be a JSON array of strings"),
        (["--fail-on-missing", "true", "{path}", "[]", '["missing"]'], r"dependencies not found"),
        (["{path}", "nope"], r"extra-values is not valid JSON"),
        (["{path}", "[]", "nope"], r"dependencies is not valid JSON"),
        (["missing.toml", "[]"], r"pyproject\.toml not found at: missing\.toml"),
    ],
)
def test_build_report_errors(tmp_path: Path, argv: list[str], match: str) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    argv = [arg.replace("{path}", str(path)) for arg in argv]

    with pytest.raises(MetadataError, match=match):
        build_report(parse_args(*argv))


def test_build_report_strict_fails_on_warnings(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)

    with pytest.raises(
        MetadataError,
        match=r"^strict is 'true' and there are 1 warning\(s\):\n- dup has different specifiers in ",
    ):
        build_report(parse_args("--strict", "true", str(path), "[]", '["dup"]'))


def test_build_report_strict_lists_every_warning(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "a"\nversion = "1"\nrequires-python = "nope"\n'
        'dependencies = ["bad requirement!!"]\n',
    )

    with pytest.raises(MetadataError) as excinfo:
        build_report(parse_args("--strict", "true", str(path), "[]"))

    lines = str(excinfo.value).splitlines()
    assert lines[0] == "strict is 'true' and there are 2 warning(s):"
    assert lines[1].startswith("- ")
    assert lines[2].startswith("- ")


def test_build_report_strict_without_warnings(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    report = build_report(parse_args("--strict", "true", str(path), "[]"))

    assert report["warnings"] == []


def test_build_report_not_strict_keeps_the_warnings(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)

    report = build_report(parse_args("--strict", "false", str(path), "[]", '["dup"]'))

    assert len(report["warnings"]) == 1


def test_main_strict_fails_without_writing_the_outputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    output = tmp_path / "out"

    exit_code = main(
        ["extract_metadata.py", "--github-output", str(output), "--strict", "true", str(path), "[]", '["dup"]']
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.err.startswith(f"::error file={path}::strict is 'true' and there are 1 warning(s):%0A- dup")
    assert captured.out == ""
    assert not output.exists()


def test_main_invalid_strict_returns_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    assert main(["extract_metadata.py", "--strict", "maybe", str(path), "[]"]) == 1
    assert "strict must be 'true' or 'false', got: 'maybe'" in capsys.readouterr().err


def test_emit_github_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "github_output"
    report = build_report(parse_args(str(write_pyproject(tmp_path, DEPS_TOML)), "[]", '["dup"]'))

    emit_github_output(report, "my,file.toml", str(output))

    out_lines = capsys.readouterr().out.splitlines()
    assert out_lines[0].startswith("::warning file=my%2Cfile.toml::dup has different specifiers")
    assert out_lines[1].startswith("📦 name=p version=1 ")
    assert len(out_lines) == 2
    assert parse_github_output(output.read_text(encoding="utf-8")) == format_outputs(report)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("coola", "<code>coola</code>"),
        ("", ""),
        ("a b", "<code>a b</code>"),
        ("a|b", "<code>a&#124;b</code>"),
        ("<b>x</b>", "<code>&#60;b&#62;x&#60;&#47;b&#62;</code>"),
        ("snake_case*", "<code>snake&#95;case&#42;</code>"),
        ("a\nb", "<code>a&#92;nb</code>"),
        ("`x`", "<code>&#96;x&#96;</code>"),
    ],
)
def test_html_cell(value: str, expected: str) -> None:
    assert extract_metadata_module._html_cell(value) == expected


def test_format_step_summary_without_warnings() -> None:
    report = Report(
        name="coola",
        normalized_name="coola",
        version="1.2.3",
        normalized_version="1.2.3",
        description="",
        readme="",
        license="",
        authors=[],
        urls={},
        requires_python="",
        extras=["", "a"],
        groups=[],
        python_versions=["3.12"],
        python_min="3.12",
        python_max="3.12",
        project_dependencies={},
        dependency_specifiers={},
        dependency_requirements={},
        warnings=[],
    )

    assert format_step_summary(report, format_outputs(report)) == (
        "### 📦 Project metadata\n"
        "\n"
        "| Output | Value |\n"
        "| --- | --- |\n"
        "| `name` | <code>coola</code> |\n"
        "| `normalized-name` | <code>coola</code> |\n"
        "| `version` | <code>1&#46;2&#46;3</code> |\n"
        "| `normalized-version` | <code>1&#46;2&#46;3</code> |\n"
        "| `description` |  |\n"
        "| `readme` |  |\n"
        "| `license` |  |\n"
        "| `authors` | <code>&#91;&#93;</code> |\n"
        "| `urls` | <code>&#123;&#125;</code> |\n"
        "| `requires-python` |  |\n"
        "| `extras` | <code>&#91;&#34;&#34;&#44;&#34;a&#34;&#93;</code> |\n"
        "| `groups` | <code>&#91;&#93;</code> |\n"
        "| `python-versions` | <code>&#91;&#34;3&#46;12&#34;&#93;</code> |\n"
        "| `python-min` | <code>3&#46;12</code> |\n"
        "| `python-max` | <code>3&#46;12</code> |\n"
        "| `python-matrix` | <code>&#123;&#34;python&#45;version&#34;&#58;&#91;&#34;3&#46;12&#34;&#93;&#125;</code> |\n"
        "| `project-dependencies` | <code>&#123;&#125;</code> |\n"
        "| `dependency-specifiers` | <code>&#123;&#125;</code> |\n"
        "| `dependency-requirements` | <code>&#123;&#125;</code> |\n"
    )


def test_format_step_summary_lists_the_warnings() -> None:
    report = Report(
        name="a",
        normalized_name="a",
        version="1",
        normalized_version="1",
        description="",
        readme="",
        license="",
        authors=[],
        urls={},
        requires_python="",
        extras=[],
        groups=[],
        python_versions=[],
        python_min="",
        python_max="",
        project_dependencies={},
        dependency_specifiers={},
        dependency_requirements={},
        warnings=["first | one", "second"],
    )

    summary = format_step_summary(report, format_outputs(report))

    assert summary.endswith(
        "\n#### ⚠️ Warnings\n\n- <code>first &#124; one</code>\n- <code>second</code>\n"
    )


def test_format_error_summary() -> None:
    summary = format_error_summary("p.toml: [project].name | bad\nsecond line")

    assert summary == (
        "### ❌ Project metadata\n"
        "\n"
        "- <code>p&#46;toml&#58; &#91;project&#93;&#46;name &#124; bad</code>\n"
        "- <code>second line</code>\n"
    )


def test_format_error_summary_removes_the_bullet_of_a_line() -> None:
    assert format_error_summary("head:\n- first\n- second") == (
        "### ❌ Project metadata\n\n"
        "- <code>head&#58;</code>\n- <code>first</code>\n- <code>second</code>\n"
    )


def test_format_error_summary_skips_blank_lines() -> None:
    assert format_error_summary("a\n\n  \nb") == (
        "### ❌ Project metadata\n\n- <code>a</code>\n- <code>b</code>\n"
    )


def test_write_step_summary_appends(tmp_path: Path) -> None:
    summary = tmp_path / "summary.md"
    summary.write_text("before\n")

    write_step_summary(str(summary), "# Title\n")
    write_step_summary(str(summary), "again\n")

    assert summary.read_text() == "before\n# Title\n\nagain\n\n"


@pytest.mark.parametrize(
    ("value", "environ", "expected"),
    [
        ("false", {}, None),
        ("false", {"GITHUB_STEP_SUMMARY": "/tmp/s.md"}, None),
        ("true", {"GITHUB_STEP_SUMMARY": "/tmp/s.md"}, "/tmp/s.md"),
        (" TRUE ", {"GITHUB_STEP_SUMMARY": "/tmp/s.md"}, "/tmp/s.md"),
    ],
)
def test_resolve_step_summary(value: str, environ: dict[str, str], expected: str | None) -> None:
    assert resolve_step_summary(parse_bool(value, "step-summary"), environ) == expected


@pytest.mark.parametrize("environ", [{}, {"GITHUB_STEP_SUMMARY": ""}])
def test_resolve_step_summary_without_the_environment_variable(environ: dict[str, str]) -> None:
    with pytest.raises(MetadataError, match=r"step-summary is 'true' but .*GITHUB_STEP_SUMMARY"):
        resolve_step_summary(True, environ)


def test_parse_options() -> None:
    args = parse_args(
        "--fail-on-missing",
        "true",
        "--fail-on-dynamic-version",
        " TRUE",
        "--step-summary",
        "true",
        "p.toml",
        "[]",
    )

    assert parse_options(args) == Options(
        fail_on_missing=True, fail_on_dynamic_version=True, strict=False, step_summary=True
    )


def test_parse_options_defaults() -> None:
    assert parse_options(parse_args("p.toml", "[]")) == Options(False, False, False, False)


@pytest.mark.parametrize(
    ("option", "name"),
    [
        ("--fail-on-missing", "fail-on-missing"),
        ("--fail-on-dynamic-version", "fail-on-dynamic-version"),
        ("--strict", "strict"),
        ("--step-summary", "step-summary"),
    ],
)
def test_parse_options_invalid_value(option: str, name: str) -> None:
    with pytest.raises(MetadataError, match=rf"{name} must be 'true' or 'false', got: 'maybe'"):
        parse_options(parse_args(option, "maybe", "p.toml", "[]"))


def test_parse_options_reports_the_first_invalid_value() -> None:
    args = parse_args("--strict", "x", "--fail-on-missing", "y", "p.toml", "[]")

    with pytest.raises(MetadataError, match=r"fail-on-missing must be"):
        parse_options(args)


def test_build_report_uses_the_given_options(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')
    args = parse_args("--strict", "maybe", str(path), "[]", '["missing"]')

    report = build_report(args, Options(False, False, False, False))

    assert report["dependency_specifiers"] == {"missing": None}


def test_main_step_summary_writes_the_job_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    path = write_pyproject(tmp_path, DEPS_TOML)

    exit_code = main(
        [
            "extract_metadata.py",
            "--github-output",
            str(tmp_path / "out"),
            "--step-summary",
            "true",
            str(path),
            "[]",
            '["dup"]',
        ]
    )

    assert exit_code == 0
    text = summary.read_text(encoding="utf-8")
    assert text.startswith("### 📦 Project metadata\n")
    assert "| `name` | <code>p</code> |" in text
    assert "#### ⚠️ Warnings" in text
    assert "<code>dup has different specifiers" in text
    capsys.readouterr()


def test_main_step_summary_reports_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    path = write_pyproject(tmp_path, '[project]\nversion = "1"\n')

    exit_code = main(["extract_metadata.py", "--step-summary", "true", str(path), "[]"])

    assert exit_code == 1
    text = summary.read_text(encoding="utf-8")
    assert text.startswith("### ❌ Project metadata\n")
    assert "missing required key" in text
    assert "&#91;project&#93;&#46;name" in text
    assert "missing required key" in capsys.readouterr().err


def test_main_step_summary_lists_the_warnings_of_a_strict_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    path = write_pyproject(tmp_path, '[project]\nname = "a"\ndynamic = ["version"]\n')

    exit_code = main(
        ["extract_metadata.py", "--step-summary", "true", "--strict", "true", str(path), "[]"]
    )

    assert exit_code == 1
    text = summary.read_text(encoding="utf-8")
    assert "there are 1 warning&#40;s&#41;&#58;</code>\n- <code>" in text
    assert "<code>&#45;" not in text
    assert "[project].version is dynamic" not in text  # escaped, not raw


def test_main_step_summary_off_writes_nothing_on_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    path = write_pyproject(tmp_path, '[project]\nversion = "1"\n')

    assert main(["extract_metadata.py", str(path), "[]"]) == 1
    assert not summary.exists()


def test_main_step_summary_misconfiguration_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    assert main(["extract_metadata.py", "--step-summary", "true", str(path), "[]"]) == 1


def test_main_step_summary_is_off_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    path = write_pyproject(tmp_path, DEPS_TOML)

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert not summary.exists()


def test_main_step_summary_without_json_output_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    path = write_pyproject(tmp_path, DEPS_TOML)

    assert main(["extract_metadata.py", "--step-summary", "true", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["name"] == "p"
    assert summary.read_text(encoding="utf-8").startswith("### 📦 Project metadata\n")


@pytest.mark.parametrize(
    ("step_summary", "has_variable", "message"),
    [
        ("maybe", True, "step-summary must be 'true' or 'false'"),
        ("true", False, "GITHUB_STEP_SUMMARY is not set"),
    ],
)
def test_main_step_summary_errors_return_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    step_summary: str,
    has_variable: bool,
    message: str,
) -> None:
    if has_variable:
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    else:
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    path = write_pyproject(tmp_path, DEPS_TOML)

    exit_code = main(["extract_metadata.py", "--step-summary", step_summary, str(path), "[]"])

    assert exit_code == 1
    assert message in capsys.readouterr().err
    assert not (tmp_path / "summary.md").exists()


@pytest.mark.parametrize(
    ("message", "pyproject_path", "annotate", "expected"),
    [
        ("boom", "p.toml", False, "boom"),
        ("a\nb", "p.toml", False, "a\nb"),
        ("boom", "p.toml", True, "::error file=p.toml::boom"),
        ("50%\nnext\r", "a,b:c.toml", True, "::error file=a%2Cb%3Ac.toml::50%25%0Anext%0D"),
    ],
)
def test_format_error(message: str, pyproject_path: str, annotate: bool, expected: str) -> None:
    assert format_error(message, pyproject_path, annotate) == expected


def test_main_error_is_a_plain_message_without_github_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "nope.toml"

    assert main(["extract_metadata.py", str(path), "[]"]) == 1
    captured = capsys.readouterr()

    assert captured.err == f"pyproject.toml not found at: {path}\n"
    assert captured.out == ""


def test_main_error_is_an_annotation_with_github_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "nope.toml"

    exit_code = main(
        ["extract_metadata.py", "--github-output", str(tmp_path / "out"), str(path), "[]"]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.err == f"::error file={path}::pyproject.toml not found at: {path}\n"


def test_main_error_annotation_cannot_inject_a_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = 3\n')

    exit_code = main(["extract_metadata.py", "--github-output", str(tmp_path / "out"), str(path), "[]"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert len(captured.err.splitlines()) == 1
    assert captured.err.startswith("::error file=")


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("plain", "plain"),
        ("", ""),
        ("100%", "100%25"),
        ("a\nb", "a%0Ab"),
        ("a\r\nb", "a%0D%0Ab"),
        ("%0A", "%250A"),
    ],
)
def test_escape_annotation(message: str, expected: str) -> None:
    assert escape_annotation(message) == expected


def test_main_github_output_error_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "github_output"

    exit_code = main(
        ["extract_metadata.py", "--github-output", str(output), str(tmp_path / "nope.toml"), "[]"]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "not found" in captured.err
    assert captured.out == ""
    assert not output.exists()


@pytest.mark.parametrize(
    "argv",
    [
        ["extract_metadata.py", "--github-output"],
        ["extract_metadata.py", "--github-output", "out"],
        ["extract_metadata.py", "--github-output", "out", "a", "[]", "[]", "extra"],
        ["extract_metadata.py", "--unknown", "a", "[]"],
    ],
)
def test_main_usage_errors_with_options(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(argv) == 2
    assert "usage:" in capsys.readouterr().err


def test_cli_end_to_end_github_output(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n[project.optional-dependencies]\nnumpy = ["numpy"]\n'
    )
    output = tmp_path / "github_output"

    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT_PATH), "--github-output", str(output), "--", str(path), '[""]'],
        capture_output=True,
        text=True,
        check=True,
    )

    assert parse_github_output(output.read_text(encoding="utf-8")) == {
        "name": "coola",
        "normalized-name": "coola",
        "version": "1.2.3",
        "normalized-version": "1.2.3",
        "description": "",
        "readme": "",
        "license": "",
        "authors": '[]',
        "urls": '{}',
        "requires-python": "",
        "extras": '["","numpy"]',
        "groups": "[]",
        "python-versions": '["3.10","3.11","3.12","3.13","3.14"]',
        "python-min": "3.10",
        "python-max": "3.14",
        "python-matrix": '{"python-version":["3.10","3.11","3.12","3.13","3.14"]}',
        "project-dependencies": "{}",
        "dependency-specifiers": "{}",
        "dependency-requirements": "{}",
    }
    assert result.stdout == (
        "📦 name=coola version=1.2.3 requires-python= "
        'python-versions=["3.10","3.11","3.12","3.13","3.14"] python-min=3.10 python-max=3.14 extras=["","numpy"] groups=[] '
        "project-dependencies={} dependency-specifiers={}\n"
    )


def test_main_github_output_multiline_name_is_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "evil\\n::error::boom\\nversion=hacked"\nversion = "1"\n',
    )
    output = tmp_path / "github_output"

    exit_code = main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert not output.exists()
    assert captured.out == ""
    assert len(captured.err.splitlines()) == 1
    assert "[project].name is not a valid project name" in captured.err


@pytest.mark.parametrize(
    ("value", "expected"),
    [("plain", "plain"), ("", ""), ("a\nb", "a\\nb"), ("a\r\nb", "a\\r\\nb"), ("a\\nb", "a\\\\nb")],
)
def test_single_line(value: str, expected: str) -> None:
    assert extract_metadata_module._single_line(value) == expected


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


@pytest.mark.parametrize("value", [[], ["a"], ["a", "B_c>=1"]])
def test_check_string_array_returns_the_strings(value: list[str]) -> None:
    assert _check_string_array(value, "[x]", "p.toml") == value


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
        _check_string_array(value, "[x]", "p.toml")


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
    ("argv_tail", "message"),
    [
        (["[]", "not json"], "dependencies is not valid JSON"),
        (["[]", '{"a": 1}'], "dependencies must be a JSON array of strings"),
        (["not json"], "extra-values is not valid JSON"),
        (["{}"], "extra-values must be a JSON array"),
        (["[1]"], "extra-values must be a JSON array of strings"),
    ],
)
def test_main_invalid_inputs_return_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv_tail: list[str], message: str
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')

    exit_code = main(["extract_metadata.py", str(path), *argv_tail])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert message in captured.err
    assert captured.out == ""


@pytest.mark.parametrize(
    "argv",
    [
        ["extract_metadata.py", "a"],
        ["extract_metadata.py", "a", "[]", "[]", "extra"],
    ],
)
def test_main_wrong_number_of_arguments_returns_two(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(argv) == 2
    assert "usage:" in capsys.readouterr().err


def test_cli_end_to_end_with_dependencies(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "coola"\nversion = "1.2.3"\ndependencies = ["numpy>=1.20"]\n',
    )

    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT_PATH), str(path), "[]", '["numpy", "pandas"]'],
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(result.stdout) == {
        "name": "coola",
        "normalized_name": "coola",
        "version": "1.2.3",
        "normalized_version": "1.2.3",
        "description": "",
        "readme": "",
        "license": "",
        "authors": [],
        "urls": {},
        "requires_python": "",
        "extras": [],
        "groups": [],
        "python_versions": ["3.10", "3.11", "3.12", "3.13", "3.14"],
        "python_min": "3.10",
    "python_max": "3.14",
        "python_max": "3.14",
        "project_dependencies": {"numpy": ">=1.20"},
        "dependency_specifiers": {"numpy": ">=1.20", "pandas": None},
        "dependency_requirements": {
            "numpy": [{"specifier": ">=1.20", "marker": ""}],
            "pandas": [],
        },
        "warnings": [],
        "schema_version": 1,
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
        _, warnings = extract_dependency_specifiers({"dependency-groups": 1}, [], "custom/pyproject.toml")


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


def test_main_unknown_group_entry_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "coola"\nversion = "1"\n\n[dependency-groups]\ndev = [{include_group = "a"}]\n',
    )

    assert main(["extract_metadata.py", str(path), "[]", '["x"]']) == 1
    assert "[dependency-groups].dev entries must be strings or" in capsys.readouterr().err


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


def test_main_malformed_dependency_table_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "p"\nversion = "1"\n[dependency-groups]\ndev = "numpy"\n'
    )

    exit_code = main(["extract_metadata.py", str(path), "[]", '["numpy"]'])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "[dependency-groups].dev must be an array" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


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


def test_main_include_group_cycle_warning_annotation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "p"\nversion = "1"\n[dependency-groups]\na = [{include-group = "a"}]\n',
    )
    output = tmp_path / "github_output"

    exit_code = main(
        ["extract_metadata.py", "--github-output", str(output), str(path), "[]", '["x"]']
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out.splitlines()[0] == (
        f"::warning file={path}::{path}: [dependency-groups] has an include-group cycle: a -> a"
    )


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


MARKERS_TOML = """
[project]
name = "p"
version = "1"
dependencies = [
    "numpy>=1.20; python_version < '3.10'",
    "numpy>=2; python_version >= '3.10'",
    "same>=1; sys_platform == 'linux'",
    "same>=2; sys_platform == 'linux'",
    "mixed>=1",
    "mixed>=2; python_version >= '3.10'",
]
"""


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
    ("value", "expected"),
    [
        ("pyproject.toml", "pyproject.toml"),
        ("", ""),
        ("sub dir/pyproject.toml", "sub dir/pyproject.toml"),
        ("C:\\pyproject.toml", "C%3A\\pyproject.toml"),
        ("a,b", "a%2Cb"),
        ("a::b", "a%3A%3Ab"),
        ("100%", "100%25"),
        ("a\nb", "a%0Ab"),
        ("a\r\nb", "a%0D%0Ab"),
        ("%3A", "%253A"),
    ],
)
def test_escape_annotation_property(value: str, expected: str) -> None:
    assert escape_annotation_property(value) == expected


def test_main_warning_annotation_escapes_the_file_property(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "a,b:c"
    directory.mkdir()
    path = directory / "pyproject.toml"
    path.write_text('[project]\nname = "p"\ndynamic = ["version"]\n')
    output = tmp_path / "github_output"

    exit_code = main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"])
    captured = capsys.readouterr()

    escaped = str(path).replace("%", "%25").replace(":", "%3A").replace(",", "%2C")
    assert exit_code == 0
    assert captured.out.splitlines()[0] == (
        f"::warning file={escaped}::{path}: [project].version is dynamic, "
        "the version output is empty"
    )


def test_main_warning_annotation_names_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    write_pyproject(tmp_path, '[project]\nname = "p"\ndynamic = ["version"]\n')
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        ["extract_metadata.py", "--github-output", str(tmp_path / "out"), "pyproject.toml", "[]"]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.splitlines()[0] == (
        "::warning file=pyproject.toml::pyproject.toml: [project].version is dynamic, "
        "the version output is empty"
    )


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


def test_main_invalid_version_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "p"\nversion = "latest"\n')

    exit_code = main(["extract_metadata.py", str(path), "[]"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "is not a valid PEP 440 version: 'latest'" in captured.err
    assert captured.out == ""


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


def test_main_github_output_normalized_name(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "My_Package.Name"\nversion = "1"\n')
    output = tmp_path / "github_output"

    exit_code = main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"])

    assert exit_code == 0
    outputs = parse_github_output(output.read_text(encoding="utf-8"))
    assert outputs["name"] == "My_Package.Name"
    assert outputs["normalized-name"] == "my-package-name"


@pytest.mark.parametrize("requires_python", [">=3.10", ">=3.10,<4", "~=3.9", "==3.*", ">= 3.10", ""])
def test_extract_metadata_requires_python(tmp_path: Path, requires_python: str) -> None:
    path = write_pyproject(
        tmp_path,
        f'[project]\nname = "p"\nversion = "1"\nrequires-python = "{requires_python}"\n',
    )

    assert extract(path)["requires_python"] == requires_python


def test_extract_metadata_requires_python_defaults_to_empty(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "p"\nversion = "1"\n')

    assert extract(path)["requires_python"] == ""


def test_extract_metadata_requires_python_dynamic_is_empty(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "p"\nversion = "1"\ndynamic = ["requires-python"]\n'
    )

    assert extract(path)["requires_python"] == ""


@pytest.mark.parametrize("value", ["3.10", "[]", '[">=3.10"]', "true", "{a = 1}"])
def test_extract_metadata_requires_python_must_be_a_string(tmp_path: Path, value: str) -> None:
    path = write_pyproject(
        tmp_path, f'[project]\nname = "p"\nversion = "1"\nrequires-python = {value}\n'
    )

    with pytest.raises(MetadataError, match=r"\[project\]\.requires-python must be a string, got: "):
        extract(path)


def test_main_github_output_requires_python(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "p"\nversion = "1"\nrequires-python = ">=3.10,<4"\n'
    )
    output = tmp_path / "github_output"

    exit_code = main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"])

    assert exit_code == 0
    assert parse_github_output(output.read_text(encoding="utf-8"))["requires-python"] == ">=3.10,<4"


def test_main_json_requires_python(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "p"\nversion = "1"\nrequires-python = ">=3.10"\n'
    )

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["requires_python"] == ">=3.10"


GROUPS_TOML = """
[project]
name = "p"
version = "1"

[dependency-groups]
test = ["pytest"]
Dev = ["ruff"]
docs = []
"""


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


def test_main_github_output_groups(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, GROUPS_TOML)
    output = tmp_path / "github_output"

    exit_code = main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"])

    assert exit_code == 0
    assert parse_github_output(output.read_text(encoding="utf-8"))["groups"] == '["Dev","docs","test"]'


def test_main_json_groups(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_pyproject(tmp_path, GROUPS_TOML)

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["groups"] == ["Dev", "docs", "test"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [("true", True), ("false", False), ("True", True), ("FALSE", False), (" true ", True)],
)
def test_parse_bool(value: str, expected: bool) -> None:
    assert parse_bool(value, "flag") is expected


@pytest.mark.parametrize("value", ["", "yes", "1", "0", "tru", "true false", "null"])
def test_parse_bool_invalid(value: str) -> None:
    with pytest.raises(MetadataError, match=rf"my-input must be 'true' or 'false', got: {value!r}"):
        parse_bool(value, "my-input")


def test_check_no_missing_dependency_all_found() -> None:
    check_no_missing_dependency({"a": ">=1", "b": ""}, "p.toml")


def test_check_no_missing_dependency_nothing_requested() -> None:
    check_no_missing_dependency({}, "p.toml")


def test_check_no_missing_dependency_lists_the_missing_packages() -> None:
    with pytest.raises(
        MetadataError, match=r"custom\.toml: dependencies not found in .*: \['b', 'd'\]$"
    ):
        check_no_missing_dependency({"a": ">=1", "b": None, "c": "", "d": None}, "custom.toml")


def test_main_fail_on_missing_true_fails_for_a_missing_dependency(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    output = tmp_path / "github_output"

    exit_code = main(
        [
            "extract_metadata.py",
            "--github-output",
            str(output),
            "--fail-on-missing",
            "true",
            str(path),
            "[]",
            '["nospec", "missing", "other"]',
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.err == (
        f"::error file={path}::{path}: dependencies not found in [project].dependencies, "
        "[project.optional-dependencies] or [dependency-groups]: ['missing', 'other']\n"
    )
    assert captured.out == ""
    assert not output.exists()


def test_main_fail_on_missing_true_passes_when_all_are_found(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)

    exit_code = main(
        ["extract_metadata.py", "--fail-on-missing", "true", str(path), "[]", '["nospec", "dup"]']
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["dependency_specifiers"] == {
        "nospec": "",
        "dup": ">=1",
    }


@pytest.mark.parametrize("argv_tail", [[], ["--fail-on-missing", "false"], ["--fail-on-missing", "FALSE"]])
def test_main_fail_on_missing_false_keeps_null(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv_tail: list[str]
) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)

    exit_code = main(["extract_metadata.py", *argv_tail, str(path), "[]", '["missing"]'])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["dependency_specifiers"] == {"missing": None}


def test_main_fail_on_missing_true_without_dependencies_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)

    assert main(["extract_metadata.py", "--fail-on-missing", "true", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["dependency_specifiers"] == {}


@pytest.mark.parametrize("value", ["", "yes", "1"])
def test_main_fail_on_missing_invalid_value_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)

    exit_code = main(["extract_metadata.py", "--fail-on-missing", value, str(path), "[]"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert f"fail-on-missing must be 'true' or 'false', got: {value!r}" in captured.err
    assert captured.out == ""


def test_main_fail_on_missing_requires_a_value(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["extract_metadata.py", "--fail-on-missing"]) == 2
    assert "usage:" in capsys.readouterr().err


def test_cli_end_to_end_fail_on_missing(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\ndependencies = ["numpy>=1.20"]\n'
    )

    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--fail-on-missing",
            "true",
            "--",
            str(path),
            "[]",
            '["numpy", "pandas"]',
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "dependencies not found" in result.stderr
    assert "['pandas']" in result.stderr
    assert result.stdout == ""


def test_get_table() -> None:
    assert _get_table({"project": {"name": "a"}}, "project", "[project]", "p.toml") == {"name": "a"}


@pytest.mark.parametrize("container", [{}, {"other": 1}])
def test_get_table_absent_is_empty(container: dict) -> None:
    assert _get_table(container, "project", "[project]", "p.toml") == {}


@pytest.mark.parametrize("value", [1, "text", [], [{"a": 1}]])
def test_get_table_not_a_table(value: object) -> None:
    with pytest.raises(MetadataError, match=r"^p.toml: \[project\] must be a table, got: "):
        _get_table({"project": value}, "project", "[project]", "p.toml")


def test_check_array() -> None:
    assert _check_array(["a", 1], "[x]", "p.toml") == ["a", 1]


@pytest.mark.parametrize("value", [{}, "text", 1])
def test_check_array_not_an_array(value: object) -> None:
    with pytest.raises(MetadataError, match=r"^p.toml: \[x\] must be an array, got: "):
        _check_array(value, "[x]", "p.toml")


def test_metadata_keys_match_the_extracted_metadata(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')

    assert list(extract(path)) == list(Metadata.__annotations__)


def test_report_keys_match_the_json_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')

    assert main(["extract_metadata.py", str(path), "[]"]) == 0

    assert list(json.loads(capsys.readouterr().out)) == list(Report.__annotations__)


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


def test_check_no_missing_dependency_points_out_dynamic_fields() -> None:
    with pytest.raises(
        MetadataError,
        match=r"\['numpy'\]; \[project\]\.dependencies is dynamic and cannot be read$",
    ):
        check_no_missing_dependency({"numpy": None}, "p.toml", ["dependencies"])


def test_main_fail_on_missing_points_out_dynamic_dependencies(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\ndynamic = ["dependencies"]\n')

    exit_code = main(["extract_metadata.py", "--fail-on-missing", "true", str(path), "[]", '["numpy"]'])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.err.endswith("; [project].dependencies is dynamic and cannot be read\n")


CANDIDATES = ["3.9", "3.10", "3.11", "3.12", "3.13"]


@pytest.mark.parametrize(
    ("requires_python", "expected"),
    [
        ("", CANDIDATES),
        ("   ", CANDIDATES),
        (">=3.10", ["3.10", "3.11", "3.12", "3.13"]),
        (">=3.10,<4", ["3.10", "3.11", "3.12", "3.13"]),
        (">=3.10, <3.13", ["3.10", "3.11", "3.12"]),
        (">3.10", ["3.10", "3.11", "3.12", "3.13"]),
        (">=3.10.2", ["3.10", "3.11", "3.12", "3.13"]),
        ("<3.12.5", ["3.9", "3.10", "3.11", "3.12"]),
        ("<3.11", ["3.9", "3.10"]),
        ("~=3.10", ["3.10", "3.11", "3.12", "3.13"]),
        ("~=3.11.0", ["3.11"]),
        ("==3.11.*", ["3.11"]),
        ("!=3.12.*", ["3.9", "3.10", "3.11", "3.13"]),
        (">=3.14", []),
        (">=3", CANDIDATES),
        ("==3.12.3", ["3.12"]),
        ("===3.12.3", ["3.12"]),
        ("==3.12.3,!=3.12.0", ["3.12"]),
        ("~=3.12.3", ["3.12"]),
        (">3.12.5,<3.12.7", ["3.12"]),
        (">3.12.5,<3.12.6", []),
        (">=3.11.4,<=3.11.4", ["3.11"]),
        ("<3.9.0", []),
        ("==3.12.*,!=3.12.3", ["3.12"]),
        ("==3.12.99", ["3.12"]),
        ("==3.12.150", []),
        (">=3.12.150", ["3.12", "3.13"]),
        ("<3.12.150", ["3.9", "3.10", "3.11", "3.12"]),
    ],
)
def test_compatible_python_versions(requires_python: str, expected: list[str]) -> None:
    assert compatible_python_versions(requires_python, CANDIDATES) == (expected, [])


def test_compatible_python_versions_keeps_the_order_of_the_candidates() -> None:
    assert compatible_python_versions(">=3.10", ["3.12", "3.10", "3.8"]) == (["3.12", "3.10"], [])


def test_compatible_python_versions_no_candidates() -> None:
    assert compatible_python_versions(">=3.10", []) == ([], [])


@pytest.mark.parametrize("requires_python", ["python3", ">=", "3.10 or later"])
def test_compatible_python_versions_invalid_specifier_warns(requires_python: str) -> None:
    versions, warnings = compatible_python_versions(requires_python, CANDIDATES, "p.toml")

    assert versions == []
    assert len(warnings) == 1
    assert warnings[0].startswith(
        "p.toml: [project].requires-python is not a valid version specifier, "
        "the python-versions output is empty: "
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("[]", []),
        ('["3.12"]', ["3.12"]),
        ('["3.10", "3.9", "3.10"]', ["3.10", "3.9"]),
        ('["0.1", "10.20"]', ["0.1", "10.20"]),
        (DEFAULT_PYTHON_CANDIDATES, ["3.10", "3.11", "3.12", "3.13", "3.14"]),
    ],
)
def test_parse_python_candidates(raw: str, expected: list[str]) -> None:
    assert parse_python_candidates(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ['["3"]', '["3.12.1"]', '["3.x"]', '["v3.12"]', '["3.12 "]', '[""]', '["3.1a"]', '["3.12\\n"]'],
)
def test_parse_python_candidates_not_major_minor(raw: str) -> None:
    with pytest.raises(MetadataError, match=r"python-candidates must contain 'major.minor' versions"):
        parse_python_candidates(raw)


@pytest.mark.parametrize("raw", ["not json", '{"a": 1}', "[3.12]"])
def test_parse_python_candidates_not_an_array_of_strings(raw: str) -> None:
    with pytest.raises(MetadataError, match=r"python-candidates (is not valid JSON|must be a JSON array)"):
        parse_python_candidates(raw)


@pytest.mark.parametrize(
    "requires_python",
    [
        ">=3.12.0,<3.12.1",
        "!=3.12.*",
        ">=3.11,!=3.12.*",
        "!=3.12.0,!=3.12.1",
        "!=3.12.0,!=3.12.1,!=3.12.2,<3.12.3",
        ">3.12.5,!=3.12.6,<3.12.8",
        ">3.12.5,!=3.12.6,!=3.12.7,<3.12.9",
        ">=3.12.5,<3.12.7,!=3.12.5,!=3.12.6",
        ">=3.12.9999",
        "<3.12.0",
        "<=3.12.0",
        "~=3.12.3",
        "===3.12.1",
        "==3.12.*,!=3.12.0",
        ">=3.10.2,<3.12.5",
    ],
)
def test_compatible_python_versions_match_a_brute_force_search(requires_python: str) -> None:
    candidates = ["3.10", "3.11", "3.12", "3.13"]
    specifier = SpecifierSet(requires_python)
    patches = [*range(100), 9999]
    expected = [
        candidate
        for candidate in candidates
        if any(specifier.contains(f"{candidate}.{patch}") for patch in patches)
    ]

    versions, warnings = compatible_python_versions(requires_python, candidates)

    assert versions == expected
    assert warnings == []


@pytest.mark.parametrize(
    ("versions", "expected"),
    [
        ([], ""),
        (["3.12"], "3.12"),
        (["3.11", "3.12", "3.13"], "3.11"),
        (["3.13", "3.11", "3.12"], "3.11"),
        (["3.10", "3.9"], "3.9"),
        (["3.10", "3.2", "2.7"], "2.7"),
        (("3.10", "3.9"), "3.9"),
    ],
)
def test_lowest_python_version(versions: list[str], expected: str) -> None:
    assert lowest_python_version(versions) == expected


@pytest.mark.parametrize(
    ("versions", "expected"),
    [
        ([], ""),
        (["3.12"], "3.12"),
        (["3.11", "3.12", "3.13"], "3.13"),
        (["3.13", "3.11", "3.12"], "3.13"),
        (["3.10", "3.9"], "3.10"),
        (["3.10", "3.2", "2.7"], "3.10"),
        (("3.9", "3.10"), "3.10"),
    ],
)
def test_highest_python_version(versions: list[str], expected: str) -> None:
    assert highest_python_version(versions) == expected


def test_format_outputs_python_matrix() -> None:
    report = Report(
        name="a",
        normalized_name="a",
        version="1",
        normalized_version="1",
        description="",
        readme="",
        license="",
        authors=[],
        urls={},
        requires_python="",
        extras=[],
        groups=[],
        python_versions=["3.11", "3.12"],
        python_min="3.11",
        python_max="3.12",
        project_dependencies={},
        dependency_specifiers={},
        dependency_requirements={},
        warnings=[],
    )

    assert format_outputs(report)["python-matrix"] == '{"python-version":["3.11","3.12"]}'


def test_format_outputs_python_matrix_without_allowed_version() -> None:
    report = Report(
        name="a",
        normalized_name="a",
        version="1",
        normalized_version="1",
        description="",
        readme="",
        license="",
        authors=[],
        urls={},
        requires_python=">=4",
        extras=[],
        groups=[],
        python_versions=[],
        python_min="",
        python_max="",
        project_dependencies={},
        dependency_specifiers={},
        dependency_requirements={},
        warnings=[],
    )

    assert format_outputs(report)["python-matrix"] == '{"python-version":[]}'


def test_main_github_output_python_matrix(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = ">=3.12"\n'
    )
    output = tmp_path / "out"

    assert main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"]) == 0
    values = parse_github_output(output.read_text(encoding="utf-8"))
    assert values["python-matrix"] == '{"python-version":["3.12","3.13","3.14"]}'
    assert json.loads(values["python-matrix"])["python-version"] == json.loads(
        values["python-versions"]
    )


def test_main_json_has_no_python_matrix(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert "python_matrix" not in json.loads(capsys.readouterr().out)


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


def test_format_outputs_normalized_version() -> None:
    report = Report(
        name="a",
        normalized_name="a",
        version="1.0-RC1",
        normalized_version="1.0rc1",
        description="",
        readme="",
        license="",
        authors=[],
        urls={},
        requires_python="",
        extras=[],
        groups=[],
        python_versions=[],
        python_min="",
        python_max="",
        project_dependencies={},
        dependency_specifiers={},
        dependency_requirements={},
        warnings=[],
    )

    outputs = format_outputs(report)

    assert (outputs["version"], outputs["normalized-version"]) == ("1.0-RC1", "1.0rc1")


def test_main_github_output_normalized_version(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1.0-RC1"\n')
    output = tmp_path / "out"

    assert main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"]) == 0
    values = parse_github_output(output.read_text(encoding="utf-8"))
    assert (values["version"], values["normalized-version"]) == ("1.0-RC1", "1.0rc1")


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


def test_main_readme_in_json_and_github_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nreadme = "docs/README.md"\n'
    )
    output = tmp_path / "out"

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["readme"] == "docs/README.md"
    assert main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"]) == 0
    assert parse_github_output(output.read_text(encoding="utf-8"))["readme"] == "docs/README.md"


def test_main_invalid_readme_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\nreadme = 1\n')

    assert main(["extract_metadata.py", str(path), "[]"]) == 1
    assert "[project].readme must be a string or a table" in capsys.readouterr().err


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


def test_main_license_in_json_and_github_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\nlicense = "MIT"\n')
    output = tmp_path / "out"

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["license"] == "MIT"
    assert main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"]) == 0
    assert parse_github_output(output.read_text(encoding="utf-8"))["license"] == "MIT"


def test_main_invalid_license_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\nlicense = 1\n')

    assert main(["extract_metadata.py", str(path), "[]"]) == 1
    assert "[project].license must be a string or a table" in capsys.readouterr().err


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


def test_main_authors_in_json_and_github_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "a"\nversion = "1"\nauthors = [{name = "Zoé", email = "z@e.org"}]\n',
    )
    output = tmp_path / "out"

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["authors"] == [{"name": "Zoé", "email": "z@e.org"}]
    assert main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"]) == 0
    assert (
        parse_github_output(output.read_text(encoding="utf-8"))["authors"]
        == '[{"name":"Zoé","email":"z@e.org"}]'
    )


def test_main_invalid_authors_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\nauthors = ["Ada"]\n')

    assert main(["extract_metadata.py", str(path), "[]"]) == 1
    assert "[project].authors[0] must be a table" in capsys.readouterr().err


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


def test_main_urls_in_json_and_github_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "a"\nversion = "1"\n[project.urls]\nHomepage = "https://a.org"\nDocs = "https://a.org/d"\n',
    )
    output = tmp_path / "out"

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["urls"] == {
        "Homepage": "https://a.org",
        "Docs": "https://a.org/d",
    }
    assert main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"]) == 0
    assert (
        parse_github_output(output.read_text(encoding="utf-8"))["urls"]
        == '{"Homepage":"https://a.org","Docs":"https://a.org/d"}'
    )


def test_main_invalid_urls_returns_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\nurls = 1\n')

    assert main(["extract_metadata.py", str(path), "[]"]) == 1
    assert "[project.urls] must be a table" in capsys.readouterr().err


def test_main_json_has_a_schema_version(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["schema_version"] == extract_metadata_module.SCHEMA_VERSION == 1


def test_github_output_has_no_schema_version(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')
    output = tmp_path / "out"

    assert main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"]) == 0
    assert "schema-version" not in parse_github_output(output.read_text(encoding="utf-8"))


def test_main_python_max_in_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = "<3.13"\n'
    )

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["python_max"] == "3.12"


def test_main_python_max_is_empty_without_allowed_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = ">=4"\n'
    )

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert (report["python_versions"], report["python_max"]) == ([], "")


def test_main_python_max_compares_versions_as_numbers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    assert (
        main(["extract_metadata.py", "--python-candidates", '["3.9","3.10"]', str(path), "[]"]) == 0
    )
    assert json.loads(capsys.readouterr().out)["python_max"] == "3.10"


def test_main_github_output_python_max(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = ">=3.11,<3.14"\n'
    )
    output = tmp_path / "out"

    assert main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"]) == 0
    assert parse_github_output(output.read_text(encoding="utf-8"))["python-max"] == "3.13"


def test_main_python_min_in_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = ">=3.11,<3.13"\n'
    )

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    assert json.loads(capsys.readouterr().out)["python_min"] == "3.11"


def test_main_python_min_is_empty_without_allowed_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = ">=4"\n'
    )

    assert main(["extract_metadata.py", str(path), "[]"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert (report["python_versions"], report["python_min"]) == ([], "")


def test_main_python_min_compares_versions_as_numbers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    exit_code = main(
        ["extract_metadata.py", "--python-candidates", '["3.10","3.9"]', str(path), "[]"]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["python_min"] == "3.9"


def test_main_github_output_python_min(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = ">=3.13"\n'
    )
    output = tmp_path / "github_output"

    assert main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"]) == 0
    assert parse_github_output(output.read_text(encoding="utf-8"))["python-min"] == "3.13"


def test_main_python_versions_in_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = ">=3.11,<3.13"\n'
    )

    exit_code = main(["extract_metadata.py", str(path), "[]"])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["python_versions"] == ["3.11", "3.12"]


def test_main_python_candidates_option(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = ">=3.9"\n'
    )

    exit_code = main(
        ["extract_metadata.py", "--python-candidates", '["3.8","3.9","3.15"]', str(path), "[]"]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["python_versions"] == ["3.9", "3.15"]


def test_main_invalid_requires_python_specifier_warns_and_gives_no_versions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = "python3"\n'
    )

    exit_code = main(["extract_metadata.py", str(path), "[]"])
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert report["python_versions"] == []
    assert len(report["warnings"]) == 1
    assert "requires-python is not a valid version specifier" in report["warnings"][0]


def test_main_github_output_python_versions(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\nrequires-python = ">=3.13"\n'
    )
    output = tmp_path / "github_output"

    exit_code = main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"])

    assert exit_code == 0
    assert parse_github_output(output.read_text(encoding="utf-8"))["python-versions"] == (
        '["3.13","3.14"]'
    )


@pytest.mark.parametrize("raw", ['["3.12.1"]', "not json"])
def test_main_invalid_python_candidates_return_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], raw: str
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    exit_code = main(["extract_metadata.py", "--python-candidates", raw, str(path), "[]"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "python-candidates" in captured.err
    assert captured.out == ""


def test_action_yaml_default_of_python_candidates_matches_the_script() -> None:
    action = (Path(__file__).resolve().parents[1] / "action.yaml").read_text(encoding="utf-8")

    assert f"default: '{DEFAULT_PYTHON_CANDIDATES}'" in action


ACTION_PATH = Path(__file__).resolve().parents[1] / "action.yaml"
README_PATH = Path(__file__).resolve().parents[1] / "README.md"


def _action_section_keys(section: str) -> list[str]:
    """Return the names under the top-level ``inputs:`` or ``outputs:`` key of action.yaml."""
    keys: list[str] = []
    in_section = False
    for line in ACTION_PATH.read_text(encoding="utf-8").splitlines():
        if re.match(r"^\S", line):
            in_section = line.startswith(f"{section}:")
        elif in_section and (match := re.match(r"^  ([a-z][a-z-]*):\s*$", line)):
            keys.append(match.group(1))
    return keys


def _readme_table_names(heading: str) -> list[str]:
    """Return the names (first column) of the table under the ``## <heading>`` of the README."""
    readme = README_PATH.read_text(encoding="utf-8")
    section = readme.split(f"\n## {heading}\n", 1)[1].split("\n#", 1)[0]
    return re.findall(r"^\| `([a-z-]+)`", section, flags=re.MULTILINE)


def test_action_section_keys_finds_the_inputs_and_outputs() -> None:
    assert "pyproject-path" in _action_section_keys("inputs")
    assert "normalized-name" in _action_section_keys("outputs")


@pytest.mark.parametrize(("section", "heading"), [("inputs", "Inputs"), ("outputs", "Outputs")])
def test_readme_documents_the_inputs_and_outputs_of_action_yaml(
    section: str, heading: str
) -> None:
    assert sorted(_readme_table_names(heading)) == sorted(_action_section_keys(section))


def test_readme_lists_the_outputs_of_the_log_line() -> None:
    readme = " ".join(README_PATH.read_text(encoding="utf-8").split())
    listed = ", ".join(f"`{field}`" for field in extract_metadata_module._SUMMARY_FIELDS)

    assert f"The line shows {listed};" in readme


def test_log_line_leaves_out_only_derived_or_long_outputs() -> None:
    omitted = set(_action_section_keys("outputs")) - set(extract_metadata_module._SUMMARY_FIELDS)

    assert omitted == {
        "normalized-name",
        "normalized-version",
        "description",
        "readme",
        "license",
        "authors",
        "urls",
        "python-matrix",
        "dependency-requirements",
    }


def test_module_docstring_lists_the_outputs_of_action_yaml() -> None:
    docstring = " ".join(extract_metadata_module.__doc__.split())
    section = docstring.split("appends the action outputs", 1)[1].split("It also prints", 1)[0]

    assert sorted(re.findall(r"``([a-z-]+)``", section)) == sorted(_action_section_keys("outputs"))


def test_module_docstring_lists_the_keys_of_the_json() -> None:
    docstring = extract_metadata_module.__doc__
    section = docstring.split("prints a single JSON object", 1)[1].split("\n\n", 1)[0]

    assert sorted(re.findall(r'"([a-z_]+)":', section)) == sorted(Report.__annotations__)


def test_readme_default_of_python_candidates_matches_the_script() -> None:
    readme = README_PATH.read_text(encoding="utf-8")

    assert f"| `{DEFAULT_PYTHON_CANDIDATES}` |" in readme


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


def _specifier_error(raw: str) -> InvalidSpecifier:
    """Return the error that ``packaging`` raises for the invalid specifier ``raw``."""
    with pytest.raises(InvalidSpecifier) as exc_info:
        SpecifierSet(raw)
    return exc_info.value


def _parse_error(raw: str) -> InvalidRequirement:
    """Return the error that ``packaging`` raises for the invalid requirement ``raw``."""
    with pytest.raises(InvalidRequirement) as exc_info:
        Requirement(raw)
    return exc_info.value


DATA_WITH_REQUIREMENTS = {
    "project": {
        "dependencies": ["numpy>=1.20; python_version < '3.12'", "not valid!", "tqdm"],
        "optional-dependencies": {"x": ["numpy>=1.26; python_version >= '3.12'"]},
    },
    "dependency-groups": {"dev": ["pytest", {"include-group": "missing"}]},
}


def test_index_dependencies() -> None:
    found, warnings = _index_dependencies(DATA_WITH_REQUIREMENTS, "p.toml")

    assert found == {
        "numpy": [(">=1.20", 'python_version < "3.12"'), (">=1.26", 'python_version >= "3.12"')],
        "tqdm": [("", None)],
        "pytest": [("", None)],
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


def test_main_warnings_are_in_the_order_of_the_sources(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "a"\ndynamic = ["version"]\nrequires-python = "python3"\n'
        'dependencies = ["x>=1", "x>=2"]\n\n[dependency-groups]\ndev = ["x>=3", "not valid!"]\n',
    )

    assert main(["extract_metadata.py", str(path), "[]", '["x"]']) == 0
    warnings = json.loads(capsys.readouterr().out)["warnings"]
    assert len(warnings) == 5
    # The metadata, the Python versions, the dependencies of the project, then the lookups.
    assert warnings[:3] == [
        f"{path}: [project].version is dynamic, the version output is empty",
        f"{path}: [project].requires-python is not a valid version specifier, "
        f"the python-versions output is empty: {_specifier_error('python3')}",
        f"x has different specifiers in {path}: ['>=1', '>=2']; using '>=1'",
    ]
    assert warnings[3].startswith(f"Ignoring invalid requirement 'not valid!' in {path}: ")
    assert warnings[4] == f"x has different specifiers in {path}: ['>=1', '>=2', '>=3']; using '>=1'"


def test_main_parses_each_requirement_once(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "a"\nversion = "1"\ndependencies = ["x>=1", "y"]\n\n'
        '[project.optional-dependencies]\nz = ["w"]\n',
    )
    extract_metadata_module._parse_requirement.cache_clear()

    assert main(["extract_metadata.py", str(path), "[]", '["x", "w"]']) == 0
    # "x>=1", "y" and "w" are parsed once, in the index of all the requirements that both lookups
    # share; "x>=1" and "y" are read again for the project dependencies.
    assert extract_metadata_module._parse_requirement.cache_info().misses == 3
    assert extract_metadata_module._parse_requirement.cache_info().hits == 2


def test_build_parser_description_is_the_first_line_of_the_docstring() -> None:
    parser = extract_metadata_module._build_parser("extract_metadata.py")

    assert parser.description == extract_metadata_module.__doc__.splitlines()[0]


def test_build_parser_without_docstring(monkeypatch: pytest.MonkeyPatch) -> None:
    # Python runs with -OO strip the docstrings.
    monkeypatch.setattr(extract_metadata_module, "__doc__", None)

    assert extract_metadata_module._build_parser("extract_metadata.py").description == ""


def test_script_runs_with_stripped_docstrings(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')

    result = subprocess.run(
        [sys.executable, "-OO", str(SCRIPT_PATH), str(path), "[]"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["name"] == "coola"


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


def test_main_non_string_requirement_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "coola"\nversion = "1"\ndependencies = ["a", 1]\n'
    )

    assert main(["extract_metadata.py", str(path), "[]"]) == 1
    assert "[project].dependencies must contain only strings, got: 1" in capsys.readouterr().err


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


def test_main_project_dependencies_in_json_and_warnings_are_not_duplicated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\ndependencies = ["dup>=1", "dup>=2"]\n'
    )

    exit_code = main(["extract_metadata.py", str(path), "[]", '["dup"]'])
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert report["project_dependencies"] == {"dup": ">=1"}
    assert report["warnings"] == [f"dup has different specifiers in {path}: ['>=1', '>=2']; using '>=1'"]


def test_main_github_output_project_dependencies(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path, '[project]\nname = "a"\nversion = "1"\ndependencies = ["numpy>=1.20"]\n'
    )
    output = tmp_path / "github_output"

    exit_code = main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"])

    assert exit_code == 0
    assert parse_github_output(output.read_text(encoding="utf-8"))["project-dependencies"] == (
        '{"numpy":">=1.20"}'
    )


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


def test_main_fail_on_dynamic_version(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\ndynamic = ["version"]\n')

    exit_code = main(["extract_metadata.py", "--fail-on-dynamic-version", "true", str(path), "[]"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "[project].version is dynamic, so it cannot be read" in captured.err
    assert captured.out == ""


def test_main_fail_on_dynamic_version_false_keeps_the_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\ndynamic = ["version"]\n')

    exit_code = main(["extract_metadata.py", "--fail-on-dynamic-version", "false", str(path), "[]"])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["version"] == ""


def test_main_invalid_fail_on_dynamic_version_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')

    exit_code = main(["extract_metadata.py", "--fail-on-dynamic-version", "maybe", str(path), "[]"])

    assert exit_code == 1
    assert "fail-on-dynamic-version must be 'true' or 'false'" in capsys.readouterr().err


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


def test_format_summary() -> None:
    assert format_summary(format_outputs(METADATA)) == (
        "📦 name=coola version=1.2.3 requires-python=>=3.10 "
        'python-versions=["3.10","3.11","3.12","3.13","3.14"] python-min=3.10 python-max=3.14 extras=["","numpy"] '
        'groups=["dev","test"] '
        'project-dependencies={"numpy":">=1","Foo_Bar":""} '
        'dependency-specifiers={"numpy":">=1","missing":null}'
    )


def test_format_summary_is_one_line_and_escapes_values() -> None:
    outputs = {**format_outputs(METADATA), "requires-python": "a\nb\r\n::error::boom\\"}

    summary = format_summary(outputs)

    assert "\n" not in summary
    assert "\r" not in summary
    assert "requires-python=a\\nb\\r\\n::error::boom\\\\ " in summary


def test_main_github_output_multiline_requires_python_cannot_inject_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "a"\nversion = "1"\nrequires-python = "x\\n::error::boom\\nversion=hacked"\n',
    )
    output = tmp_path / "github_output"

    exit_code = main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"])
    captured = capsys.readouterr()

    assert exit_code == 0
    outputs = parse_github_output(output.read_text(encoding="utf-8"))
    assert outputs["requires-python"] == "x\n::error::boom\nversion=hacked"
    assert outputs["version"] == "1"
    assert not any(line.startswith("::error") for line in captured.out.splitlines())
    assert len(captured.out.splitlines()) == 2  # the warning for the invalid specifier, then the summary
    assert "requires-python=x\\n::error::boom\\nversion=hacked " in captured.out


# --- scripts/run.sh -----------------------------------------------------------------------------
#
# run.sh is tested with stand-ins for ``python3`` (on PATH) and for the ``python`` of the private
# virtual environment. They only record their arguments in ``$STUB_LOG`` (one line per call, the
# arguments separated by \x1f) and exit with the status set in the environment, so no package is
# installed and no network is used.

STUB_SYSTEM_PYTHON = """#!/usr/bin/env bash
case "$1" in
  -c)
    case "$2" in
      *version_info*) name=version; status="${STUB_VERSION_STATUS:-0}" ;;
      *) name=probe; status="${STUB_PROBE_STATUS:-0}" ;;
    esac
    printf '%s\\037' python3 "$name" >> "$STUB_LOG"; echo >> "$STUB_LOG"
    exit "$status" ;;
  -m)
    printf '%s\\037' python3 "$@" >> "$STUB_LOG"; echo >> "$STUB_LOG"
    [ "${STUB_VENV_STATUS:-0}" = 0 ] || exit "$STUB_VENV_STATUS"
    venv="${@: -1}"
    mkdir -p "$venv/bin"
    cp "$STUB_VENV_PYTHON" "$venv/bin/python"
    chmod +x "$venv/bin/python"
    exit 0 ;;
  *) printf '%s\\037' python3 "$@" >> "$STUB_LOG"; echo >> "$STUB_LOG"; exit "${STUB_SCRIPT_STATUS:-0}" ;;
esac
"""

STUB_VENV_PYTHON = """#!/usr/bin/env bash
printf '%s\\037' venv-python "$@" >> "$STUB_LOG"; echo >> "$STUB_LOG"
if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then exit "${STUB_PIP_STATUS:-0}"; fi
exit "${STUB_SCRIPT_STATUS:-0}"
"""


class RunResult:
    """Outcome of ``run.sh``: the process, the calls to the stubs and the directory of the venvs."""

    def __init__(self, process: subprocess.CompletedProcess[str], log: Path, temp: Path) -> None:
        self.process = process
        self.calls = [line.split("\x1f")[:-1] for line in log.read_text().splitlines()] if log.exists() else []
        self.venvs = sorted(temp.glob("extract-pyproject-metadata-venv.*"))  # the ones left after the run
        self.created_venvs = [Path(call[-1]) for call in self.calls if call[:3] == ["python3", "-m", "venv"]]


def run_run_sh(tmp_path: Path, args: list[str], **env: str) -> RunResult:
    """Run ``run.sh`` with the stubs and the status codes in ``env``."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "python3").write_text(STUB_SYSTEM_PYTHON)
    (bin_dir / "python3").chmod(0o755)
    venv_python = tmp_path / "venv-python"
    venv_python.write_text(STUB_VENV_PYTHON)
    temp = tmp_path / "runner-temp"
    temp.mkdir(exist_ok=True)
    log = tmp_path / "calls.log"
    log.unlink(missing_ok=True)  # only the calls of this run
    process = subprocess.run(  # noqa: S603
        ["/bin/bash", str(RUN_PATH), *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "RUNNER_TEMP": str(temp),
            "STUB_LOG": str(log),
            "STUB_VENV_PYTHON": str(venv_python),
            **env,
        },
    )
    return RunResult(process, log, temp)


def test_run_sh_uses_the_python_on_path_when_the_requirements_are_available(tmp_path: Path) -> None:
    result = run_run_sh(tmp_path, ["--flag", "a b", "", "[]"])

    assert result.process.returncode == 0
    assert result.calls == [
        ["python3", "version"],
        ["python3", "probe"],
        ["python3", str(SCRIPT_PATH), "--flag", "a b", "", "[]"],
    ]
    assert result.venvs == []


def test_run_sh_installs_the_requirements_in_a_private_venv_when_they_are_missing(tmp_path: Path) -> None:
    result = run_run_sh(tmp_path, ["--flag", "a b", "[]"], STUB_PROBE_STATUS="1")

    assert result.process.returncode == 0
    assert len(result.created_venvs) == 1
    venv = result.created_venvs[0]
    assert venv.parent == tmp_path / "runner-temp"
    assert result.calls == [
        ["python3", "version"],
        ["python3", "probe"],
        ["python3", "-m", "venv", "--system-site-packages", str(venv)],
        ["venv-python", "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", str(REQUIREMENTS_PATH)],
        ["venv-python", str(SCRIPT_PATH), "--flag", "a b", "[]"],
    ]


@pytest.mark.parametrize("probe_status", ["0", "1"])
@pytest.mark.parametrize("status", [1, 2, 3])
def test_run_sh_exits_with_the_status_of_the_script(tmp_path: Path, probe_status: str, status: int) -> None:
    result = run_run_sh(tmp_path, ["a"], STUB_PROBE_STATUS=probe_status, STUB_SCRIPT_STATUS=str(status))

    assert result.process.returncode == status


def test_run_sh_uses_a_new_venv_on_every_run(tmp_path: Path) -> None:
    first = run_run_sh(tmp_path, ["a"], STUB_PROBE_STATUS="1")
    second = run_run_sh(tmp_path, ["a"], STUB_PROBE_STATUS="1")

    assert len(first.created_venvs) == len(second.created_venvs) == 1
    assert first.created_venvs != second.created_venvs


@pytest.mark.parametrize(
    "env",
    [
        {},  # success
        {"STUB_SCRIPT_STATUS": "3"},  # the script fails
        {"STUB_PIP_STATUS": "1"},  # the requirements cannot be installed
        {"STUB_VENV_STATUS": "1"},  # the venv cannot be created
    ],
)
def test_run_sh_removes_the_venv_when_it_ends(tmp_path: Path, env: dict[str, str]) -> None:
    result = run_run_sh(tmp_path, ["a"], STUB_PROBE_STATUS="1", **env)

    assert len(result.created_venvs) == 1
    assert result.venvs == []
    assert not result.created_venvs[0].exists()


def test_run_sh_does_not_remove_other_files_of_the_temporary_directory(tmp_path: Path) -> None:
    (tmp_path / "runner-temp").mkdir()
    (tmp_path / "runner-temp" / "other-file").write_text("keep")
    (tmp_path / "runner-temp" / "extract-pyproject-metadata-venv.old").mkdir()  # left by an earlier run

    run_run_sh(tmp_path, ["a"], STUB_PROBE_STATUS="1")

    assert (tmp_path / "runner-temp" / "other-file").read_text() == "keep"
    assert (tmp_path / "runner-temp" / "extract-pyproject-metadata-venv.old").is_dir()


def test_run_sh_fails_with_a_clear_message_when_the_venv_cannot_be_created(tmp_path: Path) -> None:
    result = run_run_sh(tmp_path, ["a"], STUB_PROBE_STATUS="1", STUB_VENV_STATUS="1")

    assert result.process.returncode == 1
    assert re.search(r"^::error::Could not install the 'packaging' Python package ", result.process.stderr)
    assert result.calls == [
        ["python3", "version"],
        ["python3", "probe"],
        ["python3", "-m", "venv", "--system-site-packages", str(result.created_venvs[0])],
    ]
    assert all(str(SCRIPT_PATH) not in call for call in result.calls)


def test_run_sh_fails_with_a_clear_message_when_the_requirements_cannot_be_installed(tmp_path: Path) -> None:
    result = run_run_sh(tmp_path, ["a"], STUB_PROBE_STATUS="1", STUB_PIP_STATUS="1")

    assert result.process.returncode == 1
    assert "::error::Could not install the 'packaging' Python package" in result.process.stderr
    assert all(str(SCRIPT_PATH) not in call for call in result.calls)


def test_run_sh_install_error_mentions_the_package_index(tmp_path: Path) -> None:
    result = run_run_sh(tmp_path, ["a"], STUB_PROBE_STATUS="1", STUB_PIP_STATUS="1")

    assert "needs access to a package index" in result.process.stderr
    assert "install it in the Python on PATH" in result.process.stderr


def test_run_sh_fails_when_the_temporary_directory_cannot_be_created(tmp_path: Path) -> None:
    result = run_run_sh(tmp_path, ["a"], STUB_PROBE_STATUS="1", RUNNER_TEMP=str(tmp_path / "does-not-exist"))

    assert result.process.returncode == 1
    assert "::error::Could not install" in result.process.stderr
    assert result.calls == [["python3", "version"], ["python3", "probe"]]


def test_run_sh_uses_the_python_executable_when_it_is_set(tmp_path: Path) -> None:
    custom = tmp_path / "custom-python"
    custom.write_text(STUB_SYSTEM_PYTHON.replace("python3", "custom"))
    custom.chmod(0o755)

    result = run_run_sh(tmp_path, ["a"], PYTHON_EXECUTABLE=str(custom))

    assert result.process.returncode == 0
    assert result.calls == [["custom", "version"], ["custom", "probe"], ["custom", str(SCRIPT_PATH), "a"]]


def test_run_sh_creates_the_venv_with_the_python_executable(tmp_path: Path) -> None:
    custom = tmp_path / "custom-python"
    custom.write_text(STUB_SYSTEM_PYTHON.replace("python3", "custom"))
    custom.chmod(0o755)

    result = run_run_sh(tmp_path, ["a"], PYTHON_EXECUTABLE=str(custom), STUB_PROBE_STATUS="1")

    assert result.process.returncode == 0
    assert [call[:3] for call in result.calls[:3]] == [
        ["custom", "version"],
        ["custom", "probe"],
        ["custom", "-m", "venv"],
    ]
    assert result.calls[-1][0] == "venv-python"


def test_run_sh_uses_python3_when_the_python_executable_is_empty(tmp_path: Path) -> None:
    result = run_run_sh(tmp_path, ["a"], PYTHON_EXECUTABLE="")

    assert result.calls[-1] == ["python3", str(SCRIPT_PATH), "a"]


def test_run_sh_fails_with_a_clear_message_when_the_python_executable_cannot_be_run(
    tmp_path: Path,
) -> None:
    result = run_run_sh(tmp_path, ["a"], PYTHON_EXECUTABLE=str(tmp_path / "missing-python"))

    assert result.process.returncode == 1
    assert re.search(
        r"^::error::This action requires Python 3\.11 or later, but '.*missing-python' is older, "
        r"missing or cannot be run\..*python-executable input",
        result.process.stderr,
    )
    assert result.calls == []


def test_run_sh_fails_with_a_clear_message_when_python_is_older_than_3_11(tmp_path: Path) -> None:
    result = run_run_sh(tmp_path, ["a"], STUB_VERSION_STATUS="1")

    assert result.process.returncode == 1
    assert result.process.stderr.startswith("::error::This action requires Python 3.11 or later")
    assert result.calls == [["python3", "version"]]
    assert result.venvs == []


def test_run_sh_end_to_end_with_the_real_python(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "python3").write_text(f'#!/usr/bin/env bash\nexec "{sys.executable}" "$@"\n')
    (bin_dir / "python3").chmod(0o755)
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')
    output = tmp_path / "github_output"

    process = subprocess.run(  # noqa: S603
        ["/bin/bash", str(RUN_PATH), "--github-output", str(output), "--", str(path), "[]"],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "RUNNER_TEMP": str(tmp_path)},
    )

    assert process.returncode == 0, process.stderr
    assert parse_github_output(output.read_text(encoding="utf-8"))["name"] == "coola"
    assert list(tmp_path.glob("extract-pyproject-metadata-venv.*")) == []  # the Python had packaging


def test_running_the_script_as_main_exits_with_the_code_of_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')
    output = tmp_path / "github_output"
    monkeypatch.setattr(sys, "argv", ["extract_metadata.py", "--github-output", str(output), str(path), "[]"])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(SCRIPT_PATH), run_name="__main__")

    assert exc_info.value.code == 0
    assert parse_github_output(output.read_text(encoding="utf-8"))["name"] == "coola"
    assert capsys.readouterr().out.startswith("📦 name=coola version=1.2.3 ")


def test_running_the_script_as_main_exits_with_one_on_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["extract_metadata.py", str(tmp_path / "missing.toml"), "[]"])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(SCRIPT_PATH), run_name="__main__")

    assert exc_info.value.code == 1
    assert "missing.toml" in capsys.readouterr().err


def test_importing_the_script_does_not_run_main(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["extract_metadata.py"])  # would exit with a usage error if main() ran
    spec = importlib.util.spec_from_file_location("extract_metadata_imported", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    spec.loader.exec_module(module)

    assert module.__name__ == "extract_metadata_imported"


def test_run_sh_fails_with_a_clear_message_on_a_windows_runner(tmp_path: Path) -> None:
    result = run_run_sh(tmp_path, ["a"], RUNNER_OS="Windows")

    assert result.process.returncode == 1
    assert result.process.stderr == "::error::This action does not support Windows runners. Use a Linux or macOS runner.\n"
    assert result.calls == []


@pytest.mark.parametrize("runner_os", ["Linux", "macOS", ""])
def test_run_sh_runs_on_the_other_runners(tmp_path: Path, runner_os: str) -> None:
    result = run_run_sh(tmp_path, ["a"], RUNNER_OS=runner_os)

    assert result.process.returncode == 0
    assert result.calls[-1] == ["python3", str(SCRIPT_PATH), "a"]


# --- extract_dependency_requirements ---------------------------------------------------------


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


def test_main_dependency_requirements_in_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "a"\nversion = "1"\n'
        "dependencies = [\"numpy>=1; python_version < '3.12'\", \"numpy>=2; python_version >= '3.12'\"]\n",
    )

    assert main(["extract_metadata.py", str(path), "[]", '["numpy", "missing"]']) == 0
    assert json.loads(capsys.readouterr().out)["dependency_requirements"] == {
        "numpy": [
            {"specifier": ">=1", "marker": 'python_version < "3.12"'},
            {"specifier": ">=2", "marker": 'python_version >= "3.12"'},
        ],
        "missing": [],
    }
