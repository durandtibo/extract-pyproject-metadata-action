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
    extract_metadata,
    load_pyproject,
    main,
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
    assert json.loads(captured.out) == {"name": "coola", "version": "1.2.3", "extras": [], "dependency_specifiers": {}}


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


def test_dependency_duplicate_warns(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    assert specifiers(path, '["dup"]') == {"dup": ">=1"}
    assert "::warning::" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["nope", '{"a": 1}', "[1]"])
def test_dependency_invalid_input(tmp_path: Path, value: str) -> None:
    path = write_pyproject(tmp_path, DEPS_TOML)
    with pytest.raises(MetadataError):
        specifiers(path, value)
