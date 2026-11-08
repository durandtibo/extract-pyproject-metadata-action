from __future__ import annotations

import importlib.util
import json
import re
import runpy
import subprocess
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import extract_metadata as extract_metadata_module  # noqa: E402
from extract_metadata import (  # noqa: E402
    Metadata,
    MetadataError,
    Report,
    DEFAULT_PYTHON_CANDIDATES,
    check_no_missing_dependency,
    extract_dependency_specifiers,
    _candidate_requirements,
    _check_array,
    _conflict_warnings,
    _dynamic_dependency_fields,
    _flatten_group,
    _index_requirements,
    _get_table,
    compatible_python_versions,
    escape_annotation,
    escape_annotation_property,
    extract_metadata,
    extract_project_dependencies,
    format_outputs,
    format_summary,
    load_pyproject,
    main,
    parse_bool,
    parse_python_candidates,
    parse_string_array,
    write_github_output,
)

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "extract_metadata.py"


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

    assert metadata == {"name": "coola", "normalized_name": "coola", "version": "1.2.3", "requires_python": "", "extras": [], "groups": []}


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

    assert metadata == {"name": "coola", "normalized_name": "coola", "version": "", "requires_python": "", "extras": [], "groups": []}
    assert warnings == [f"{path}: [project].version is dynamic, the version output is empty"]


def test_extract_metadata_static_version_wins_over_dynamic(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "coola"\nversion = "1.2.3"\ndynamic = ["version"]\n',
    )
    metadata, warnings = extract_metadata(load_pyproject(str(path)), [], str(path))

    assert metadata["version"] == "1.2.3"
    assert warnings == []


def test_extract_metadata_missing_version_with_other_dynamic_fields(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\ndynamic = ["readme"]\n')

    with pytest.raises(MetadataError, match=r"missing required key \[project\]\.version"):
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
        "requires_python": "",
        "extras": [],
        "groups": [],
        "python_versions": ["3.10", "3.11", "3.12", "3.13", "3.14"],
        "project_dependencies": {},
        "dependency_specifiers": {},
        "warnings": [f"{path}: [project].version is dynamic, the version output is empty"],
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
        "requires_python": "",
        "extras": [],
        "groups": [],
        "python_versions": ["3.10", "3.11", "3.12", "3.13", "3.14"],
        "project_dependencies": {},
        "dependency_specifiers": {},
        "warnings": [],
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
        "requires_python": "",
        "extras": ["", "numpy"],
        "groups": [],
        "python_versions": ["3.10", "3.11", "3.12", "3.13", "3.14"],
        "project_dependencies": {},
        "dependency_specifiers": {},
        "warnings": [],
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
    "requires_python": ">=3.10",
    "extras": ["", "numpy"],
    "groups": ["dev", "test"],
    "python_versions": ["3.10", "3.11", "3.12", "3.13", "3.14"],
    "project_dependencies": {"numpy": ">=1", "Foo_Bar": ""},
    "dependency_specifiers": {"numpy": ">=1", "missing": None},
    "warnings": [],
}


def test_format_outputs() -> None:
    assert format_outputs(METADATA) == {
        "name": "coola",
        "normalized-name": "coola",
        "version": "1.2.3",
        "requires-python": ">=3.10",
        "extras": '["","numpy"]',
        "groups": '["dev","test"]',
        "python-versions": '["3.10","3.11","3.12","3.13","3.14"]',
        "project-dependencies": '{"numpy":">=1","Foo_Bar":""}',
        "dependency-specifiers": '{"numpy":">=1","missing":null}',
    }


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
        "requires-python": "",
        "extras": '["","a"]',
        "groups": '["base","dev","other"]',
        "python-versions": '["3.10","3.11","3.12","3.13","3.14"]',
        "project-dependencies": '{"Foo_Bar":"<2,>=1","nospec":"","withextra":">=3"}',
        "dependency-specifiers": '{"dup":">=1","nospec":"","missing":null}',
    }
    assert captured.out == (
        f"::warning file={path}::dup has different specifiers in {path}: ['>=1', '>=2']; using '>=1'\n"
        "📦 name=p version=1 requires-python= "
        'python-versions=["3.10","3.11","3.12","3.13","3.14"] extras=["","a"] '
        'groups=["base","dev","other"] '
        'project-dependencies={"Foo_Bar":"<2,>=1","nospec":"","withextra":">=3"} '
        'dependency-specifiers={"dup":">=1","nospec":"","missing":null}\n'
    )
    assert captured.err == ""


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
        "requires-python": "",
        "extras": '["","numpy"]',
        "groups": "[]",
        "python-versions": '["3.10","3.11","3.12","3.13","3.14"]',
        "project-dependencies": "{}",
        "dependency-specifiers": "{}",
    }
    assert result.stdout == (
        "📦 name=coola version=1.2.3 requires-python= "
        'python-versions=["3.10","3.11","3.12","3.13","3.14"] extras=["","numpy"] groups=[] '
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
        ({"a": [1, None, {"other": "b"}, "x"]}, "a", ["x"]),
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


def test_candidate_requirements_ignores_non_string_entries() -> None:
    data = {
        "project": {"dependencies": ["a", 1, None], "optional-dependencies": {"x": [{"b": 1}, "c"]}}
    }

    assert _candidate_requirements(data)[0] == ["a", "c"]


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
        "requires_python": "",
        "extras": [],
        "groups": [],
        "python_versions": ["3.10", "3.11", "3.12", "3.13", "3.14"],
        "project_dependencies": {"numpy": ">=1.20"},
        "dependency_specifiers": {"numpy": ">=1.20", "pandas": None},
        "warnings": [],
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
        f"{path}: dependencies not found in [project].dependencies, "
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
    ["my pkg", "my pkg!", "-a", "a-", "_a", "a_", ".a", "a.", "a/b", "a@b", "ÄB", "a\\nb", " a", "a "],
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
    "raw", ['["3"]', '["3.12.1"]', '["3.x"]', '["v3.12"]', '["3.12 "]', '[""]', '["3.1a"]']
)
def test_parse_python_candidates_not_major_minor(raw: str) -> None:
    with pytest.raises(MetadataError, match=r"python-candidates must contain 'major.minor' versions"):
        parse_python_candidates(raw)


@pytest.mark.parametrize("raw", ["not json", '{"a": 1}', "[3.12]"])
def test_parse_python_candidates_not_an_array_of_strings(raw: str) -> None:
    with pytest.raises(MetadataError, match=r"python-candidates (is not valid JSON|must be a JSON array)"):
        parse_python_candidates(raw)


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


def test_extract_project_dependencies_ignores_non_string_entries() -> None:
    assert extract_project_dependencies({"project": {"dependencies": ["a", 1, None, {"b": 1}]}}) == (
        {"a": ""},
        [],
    )


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
    assert warnings == []


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

    assert lines == ["packaging>=23.0", 'tomli>=2.0.1; python_version < "3.11"']


def test_test_requirements_include_the_script_requirements() -> None:
    requirements = (Path(__file__).resolve().parents[1] / "requirements-test.txt").read_text(
        encoding="utf-8"
    )

    assert "-r scripts/requirements.txt" in requirements.splitlines()


def test_format_summary() -> None:
    assert format_summary(format_outputs(METADATA)) == (
        "📦 name=coola version=1.2.3 requires-python=>=3.10 "
        'python-versions=["3.10","3.11","3.12","3.13","3.14"] extras=["","numpy"] '
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


def _load_script_as(name: str) -> types.ModuleType:
    """Execute a fresh copy of the script as the module ``name``."""
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tomli_is_used_when_tomllib_is_not_available(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_tomli = types.ModuleType("tomli")
    monkeypatch.setitem(sys.modules, "tomllib", None)  # makes ``import tomllib`` raise ModuleNotFoundError
    monkeypatch.setitem(sys.modules, "tomli", fake_tomli)

    module = _load_script_as("extract_metadata_without_tomllib")

    assert module.tomllib is fake_tomli


def test_tomllib_is_preferred_over_tomli_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_tomllib = types.ModuleType("tomllib")
    monkeypatch.setitem(sys.modules, "tomllib", fake_tomllib)
    monkeypatch.setitem(sys.modules, "tomli", types.ModuleType("tomli"))

    module = _load_script_as("extract_metadata_with_tomllib")

    assert module.tomllib is fake_tomllib


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
    monkeypatch.setattr(sys, "argv", ["extract_metadata.py"])  # would exit with usage if main() ran

    module = _load_script_as("extract_metadata_imported")

    assert module.__name__ == "extract_metadata_imported"
