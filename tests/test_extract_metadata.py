from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import extract_metadata as extract_metadata_module  # noqa: E402
from extract_metadata import (  # noqa: E402
    MetadataError,
    extract_dependency_specifiers,
    _candidate_requirements,
    _conflict_warnings,
    _flatten_group,
    _parse_dependencies,
    escape_annotation,
    extract_metadata,
    format_outputs,
    load_pyproject,
    main,
    write_github_output,
)

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "extract_metadata.py"


def write_pyproject(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "pyproject.toml"
    path.write_text(content)
    return path


def extract(path: Path, extra_values_json: str = "[]") -> dict:
    """Load ``path`` and extract its metadata."""
    return extract_metadata(load_pyproject(str(path)), extra_values_json, str(path))


def specifiers(path: Path, dependencies_json: str) -> dict:
    """Load ``path`` and extract the specifiers of the requested dependencies."""
    return extract_dependency_specifiers(load_pyproject(str(path)), dependencies_json, str(path))


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
        extract_metadata({"project": {"version": "1"}}, "[]", "custom/pyproject.toml")


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

    assert metadata == {"name": "coola", "version": "1.2.3", "extras": []}


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
    warnings: list[str] = []

    metadata = extract_metadata(load_pyproject(str(path)), "[]", str(path), warnings)

    assert metadata == {"name": "coola", "version": "", "extras": []}
    assert warnings == [f"{path}: [project].version is dynamic, the version output is empty"]


def test_extract_metadata_dynamic_version_without_warnings_list(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\ndynamic = ["version"]\n')

    assert extract(path) == {"name": "coola", "version": "", "extras": []}


def test_extract_metadata_static_version_wins_over_dynamic(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "coola"\nversion = "1.2.3"\ndynamic = ["version"]\n',
    )
    warnings: list[str] = []

    metadata = extract_metadata(load_pyproject(str(path)), "[]", str(path), warnings)

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
        "version": "",
        "extras": [],
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
    assert json.loads(captured.out) == {"name": "coola", "version": "1.2.3", "extras": [], "dependency_specifiers": {}, "warnings": []}


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
        "version": "1.2.3",
        "extras": ["", "numpy"],
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
    warnings: list[str] = []

    result = extract_dependency_specifiers(
        load_pyproject(str(path)), '["dup"]', str(path), warnings
    )

    assert result == {"dup": ">=1"}
    assert warnings == [f"dup has different specifiers in {path}: ['>=1', '>=2']; using '>=1'"]


def test_dependency_no_duplicate_adds_no_warning(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    warnings: list[str] = []

    extract_dependency_specifiers(load_pyproject(str(path)), '["nospec"]', str(path), warnings)

    assert warnings == []


def test_dependency_warnings_are_optional(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)

    assert specifiers(path, '["dup"]') == {"dup": ">=1"}


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
    warnings: list[str] = []

    result = extract_dependency_specifiers(
        load_pyproject(str(path)), '["good", "dev-pkg", "missing"]', str(path), warnings
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
    warnings: list[str] = []

    result = extract_dependency_specifiers(load_pyproject(str(path)), "[]", str(path), warnings)

    assert result == {}
    assert warnings == []


@pytest.mark.parametrize("value", ["nope", '{"a": 1}', "[1]"])
def test_dependency_invalid_input(tmp_path: Path, value: str) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    with pytest.raises(MetadataError):
        specifiers(path, value)


METADATA = {
    "name": "coola",
    "version": "1.2.3",
    "extras": ["", "numpy"],
    "dependency_specifiers": {"numpy": ">=1", "missing": None},
    "warnings": [],
}


def test_format_outputs() -> None:
    assert format_outputs(METADATA) == {
        "name": "coola",
        "version": "1.2.3",
        "extras": '["","numpy"]',
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
        "version": "1",
        "extras": '["","a"]',
        "dependency-specifiers": '{"dup":">=1","nospec":"","missing":null}',
    }
    assert captured.out == (
        f"::warning::dup has different specifiers in {path}: ['>=1', '>=2']; using '>=1'\n"
        '📦 name=p version=1 extras=["","a"]\n'
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
        "version": "1.2.3",
        "extras": '["","numpy"]',
        "dependency-specifiers": "{}",
    }
    assert result.stdout == '📦 name=coola version=1.2.3 extras=["","numpy"]\n'


def test_main_github_output_multiline_name_cannot_inject_outputs_or_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\nname = "evil\\n::error::boom\\nversion=hacked"\nversion = "1"\n',
    )
    output = tmp_path / "github_output"

    exit_code = main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert parse_github_output(output.read_text(encoding="utf-8")) == {
        "name": "evil\n::error::boom\nversion=hacked",
        "version": "1",
        "extras": "[]",
        "dependency-specifiers": "{}",
    }
    assert captured.out == '📦 name=evil\\n::error::boom\\nversion=hacked version=1 extras=[]\n'
    assert not any(line.startswith("::") for line in captured.out.splitlines())


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
    assert _flatten_group(groups, name) == expected


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
    assert _flatten_group(groups, name) == expected


def test_candidate_requirements_search_order() -> None:
    data = {
        "project": {
            "dependencies": ["a>=1"],
            "optional-dependencies": {"x": ["b>=2"], "y": ["c>=3"]},
        },
        "dependency-groups": {"dev": ["d>=4"], "test": [{"include-group": "dev"}, "e>=5"]},
    }

    assert _candidate_requirements(data) == [
        "a>=1",
        "b>=2",
        "c>=3",
        "d>=4",
        "d>=4",
        "e>=5",
    ]


def test_candidate_requirements_empty() -> None:
    assert _candidate_requirements({}) == []


def test_candidate_requirements_ignores_non_string_entries() -> None:
    data = {
        "project": {"dependencies": ["a", 1, None], "optional-dependencies": {"x": [{"b": 1}, "c"]}}
    }

    assert _candidate_requirements(data) == ["a", "c"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [("[]", []), ('["a"]', ["a"]), ('["a", "B_c"]', ["a", "B_c"]), ('["a", "a"]', ["a", "a"])],
)
def test_parse_dependencies(value: str, expected: list[str]) -> None:
    assert _parse_dependencies(value) == expected


@pytest.mark.parametrize(
    ("value", "match"),
    [
        ("not json", "dependencies is not valid JSON"),
        ("", "dependencies is not valid JSON"),
        ('{"a": 1}', "dependencies must be a JSON array of strings"),
        ('"a"', "dependencies must be a JSON array of strings"),
        ("[1]", "dependencies must be a JSON array of strings"),
        ('["a", null]', "dependencies must be a JSON array of strings"),
        ('[["a"]]', "dependencies must be a JSON array of strings"),
    ],
)
def test_parse_dependencies_invalid(value: str, match: str) -> None:
    with pytest.raises(MetadataError, match=match):
        _parse_dependencies(value)


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
        "version": "1.2.3",
        "extras": [],
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
        extract_dependency_specifiers({"dependency-groups": 1}, "[]", "custom/pyproject.toml")


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
    warnings: list[str] = []

    result = _flatten_group(groups, "a", pyproject_path="p.toml", warnings=warnings)

    assert result == ["y", "x"]
    assert warnings == ["p.toml: [dependency-groups] has an include-group cycle: a -> b -> a"]


def test_flatten_group_self_include_adds_a_warning() -> None:
    warnings: list[str] = []

    result = _flatten_group({"a": [{"include-group": "a"}, "x"]}, "a", warnings=warnings)

    assert result == ["x"]
    assert warnings == ["pyproject.toml: [dependency-groups] has an include-group cycle: a -> a"]


def test_flatten_group_cycle_message_starts_at_the_smallest_group() -> None:
    groups = {"c": [{"include-group": "a"}], "a": [{"include-group": "b"}], "b": [{"include-group": "c"}]}
    warnings: list[str] = []

    _flatten_group(groups, "b", warnings=warnings)

    assert warnings == ["pyproject.toml: [dependency-groups] has an include-group cycle: a -> b -> c -> a"]


def test_flatten_group_cycle_does_not_include_the_path_leading_to_it() -> None:
    groups = {"a": [{"include-group": "b"}], "b": [{"include-group": "c"}], "c": [{"include-group": "b"}]}
    warnings: list[str] = []

    _flatten_group(groups, "a", warnings=warnings)

    assert warnings == ["pyproject.toml: [dependency-groups] has an include-group cycle: b -> c -> b"]


def test_flatten_group_cycle_uses_canonical_names() -> None:
    groups = {"My_Group": [{"include-group": "my-group"}]}
    warnings: list[str] = []

    _flatten_group(groups, "My_Group", warnings=warnings)

    assert warnings == ["pyproject.toml: [dependency-groups] has an include-group cycle: my-group -> my-group"]


def test_flatten_group_no_cycle_adds_no_warning() -> None:
    groups = {"a": [{"include-group": "b"}, {"include-group": "b"}], "b": ["y"]}
    warnings: list[str] = []

    assert _flatten_group(groups, "a", warnings=warnings) == ["y", "y"]
    assert warnings == []


def test_candidate_requirements_reports_a_cycle_once() -> None:
    data = {
        "dependency-groups": {
            "a": [{"include-group": "b"}, "x"],
            "b": [{"include-group": "a"}, "y"],
        }
    }
    warnings: list[str] = []

    _candidate_requirements(data, "p.toml", warnings)

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
    warnings: list[str] = []

    result = extract_dependency_specifiers(
        load_pyproject(str(path)), '["x", "y"]', str(path), warnings
    )

    assert result == {"x": ">=1", "y": ">=2"}
    assert warnings == [f"{path}: [dependency-groups] has an include-group cycle: a -> b -> a"]


def test_dependency_include_group_cycle_does_not_warn_when_nothing_is_requested(
    tmp_path: Path,
) -> None:
    path = write_pyproject(tmp_path, '[dependency-groups]\na = [{include-group = "a"}]\n')
    warnings: list[str] = []

    result = extract_dependency_specifiers(load_pyproject(str(path)), "[]", str(path), warnings)

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
        f"::warning::{path}: [dependency-groups] has an include-group cycle: a -> a"
    )


def test_flatten_group_missing_include_group_adds_a_warning() -> None:
    warnings: list[str] = []

    result = _flatten_group(
        {"dev": [{"include-group": "tset"}, "x"]}, "dev", pyproject_path="p.toml", warnings=warnings
    )

    assert result == ["x"]
    assert warnings == ["p.toml: [dependency-groups].dev: include-group 'tset' does not match any group"]


def test_flatten_group_include_group_matches_any_pep_503_spelling_without_warning() -> None:
    warnings: list[str] = []

    result = _flatten_group(
        {"a": [{"include-group": "My-Group"}], "my_group": ["y"]}, "a", warnings=warnings
    )

    assert result == ["y"]
    assert warnings == []


def test_flatten_group_missing_include_group_is_reported_once_per_group() -> None:
    groups = {"a": [{"include-group": "nope"}], "b": [{"include-group": "a"}]}
    warnings: list[str] = []

    _candidate_requirements({"dependency-groups": groups}, "p.toml", warnings)

    assert warnings == ["p.toml: [dependency-groups].a: include-group 'nope' does not match any group"]


def test_dependency_missing_include_group_adds_a_warning(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        """
        [dependency-groups]
        dev = [{include-group = "tset"}, "x>=1"]
        """,
    )
    warnings: list[str] = []

    result = extract_dependency_specifiers(load_pyproject(str(path)), '["x"]', str(path), warnings)

    assert result == {"x": ">=1"}
    assert warnings == [
        f"{path}: [dependency-groups].dev: include-group 'tset' does not match any group"
    ]


def test_dependency_missing_include_group_does_not_warn_when_nothing_is_requested(
    tmp_path: Path,
) -> None:
    path = write_pyproject(tmp_path, '[dependency-groups]\ndev = [{include-group = "tset"}]\n')
    warnings: list[str] = []

    extract_dependency_specifiers(load_pyproject(str(path)), "[]", str(path), warnings)

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
    warnings: list[str] = []

    result = extract_dependency_specifiers(
        load_pyproject(str(path)), '["numpy"]', str(path), warnings
    )

    assert result == {"numpy": ">=1.20"}
    assert warnings == []


def test_dependency_same_marker_different_specifiers_warns_with_the_marker(
    tmp_path: Path,
) -> None:
    path = write_pyproject(tmp_path, MARKERS_TOML)
    warnings: list[str] = []

    result = extract_dependency_specifiers(
        load_pyproject(str(path)), '["same"]', str(path), warnings
    )

    assert result == {"same": ">=1"}
    assert warnings == [
        f"same has different specifiers for marker 'sys_platform == \"linux\"' in {path}: "
        "['>=1', '>=2']; using '>=1'"
    ]


def test_dependency_marker_and_no_marker_do_not_warn(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, MARKERS_TOML)
    warnings: list[str] = []

    result = extract_dependency_specifiers(
        load_pyproject(str(path)), '["mixed"]', str(path), warnings
    )

    assert result == {"mixed": ">=1"}
    assert warnings == []


def test_dependency_same_specifier_with_different_markers_does_not_warn(tmp_path: Path) -> None:
    path = write_pyproject(
        tmp_path,
        '[project]\ndependencies = ["a>=1; os_name == \'nt\'", "a>=1; os_name == \'posix\'"]\n',
    )
    warnings: list[str] = []

    extract_dependency_specifiers(load_pyproject(str(path)), '["a"]', str(path), warnings)

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
    warnings: list[str] = []

    extract_dependency_specifiers(load_pyproject(str(path)), '["a"]', str(path), warnings)

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
