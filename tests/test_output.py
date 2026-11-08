"""Tests of the outputs: GitHub outputs, workflow commands, log line and job summary."""



import json
from pathlib import Path

import pytest
from helpers import (
    ACTION_PATH,
    DEPS_TOML,
    METADATA,
    README_PATH,
    _action_section_keys,
    parse_args,
    parse_github_output,
    write_pyproject,
)

import extract_pyproject_metadata.cli as extract_metadata_module
from extract_pyproject_metadata.cli import (
    build_report,
    emit_github_output,
    escape_annotation,
    escape_annotation_property,
    format_outputs,
    format_step_summary,
    format_summary,
    main,
    write_github_output,
    write_step_summary,
)
from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.types import Report


def test_write_github_output_unwritable_file(tmp_path: Path) -> None:
    with pytest.raises(MetadataError, match=r"cannot write the outputs to .*: "):
        write_github_output(str(tmp_path), {"name": "coola"})



def test_write_step_summary_unwritable_file(tmp_path: Path) -> None:
    with pytest.raises(MetadataError, match=r"cannot write the job summary to .*: "):
        write_step_summary(str(tmp_path), "# Title\n")



def test_format_outputs() -> None:
    assert format_outputs(METADATA) == {
        "name": "coola",
        "normalized-name": "coola",
        "version": "1.2.3",
        "normalized-version": "1.2.3",
        "description": "",
        "readme": "",
        "license": "",
        "license-files": '[]',
        "authors": '[]',
        "urls": '{}',
        "keywords": '[]',
        "classifiers": '[]',
        "scripts": '{}',
        "requires-python": ">=3.10",
        "extras": '["","numpy"]',
        "groups": '["dev","test"]',
        "build-backend": "",
        "build-requires": '[]',
        "python-versions": '["3.11","3.12","3.13","3.14","3.15"]',
        "python-min": "3.11",
        "python-max": "3.15",
        "python-matrix": '{"python-version":["3.11","3.12","3.13","3.14","3.15"]}',
        "project-dependencies": '{"numpy":">=1","Foo_Bar":""}',
        "dependency-specifiers": '{"numpy":">=1","missing":null}',
        "dependency-requirements": '{"numpy":[{"specifier":">=1","marker":""}],"missing":[]}',
    }



def test_format_outputs_keeps_non_ascii_characters() -> None:
    metadata = {**METADATA, "extras": ["é"], "dependency_specifiers": {}}

    assert format_outputs(metadata)["extras"] == '["é"]'



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
        license_files=[],
        authors=[],
        urls={},
        keywords=[],
        classifiers=[],
        scripts={},
        requires_python="",
        extras=["", "a"],
        groups=[],
        build_backend="",
        build_requires=[],
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
        "| `license-files` | <code>&#91;&#93;</code> |\n"
        "| `authors` | <code>&#91;&#93;</code> |\n"
        "| `urls` | <code>&#123;&#125;</code> |\n"
        "| `keywords` | <code>&#91;&#93;</code> |\n"
        "| `classifiers` | <code>&#91;&#93;</code> |\n"
        "| `scripts` | <code>&#123;&#125;</code> |\n"
        "| `requires-python` |  |\n"
        "| `extras` | <code>&#91;&#34;&#34;&#44;&#34;a&#34;&#93;</code> |\n"
        "| `groups` | <code>&#91;&#93;</code> |\n"
        "| `build-backend` |  |\n"
        "| `build-requires` | <code>&#91;&#93;</code> |\n"
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
        license_files=[],
        authors=[],
        urls={},
        keywords=[],
        classifiers=[],
        scripts={},
        requires_python="",
        extras=[],
        groups=[],
        build_backend="",
        build_requires=[],
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



def test_write_step_summary_appends(tmp_path: Path) -> None:
    summary = tmp_path / "summary.md"
    summary.write_text("before\n")

    write_step_summary(str(summary), "# Title\n")
    write_step_summary(str(summary), "again\n")

    assert summary.read_text() == "before\n# Title\n\nagain\n\n"



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



@pytest.mark.parametrize(
    ("value", "expected"),
    [("plain", "plain"), ("", ""), ("a\nb", "a\\nb"), ("a\r\nb", "a\\r\\nb"), ("a\\nb", "a\\\\nb")],
)
def test_single_line(value: str, expected: str) -> None:
    assert extract_metadata_module._single_line(value) == expected



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



def test_report_keys_match_the_json_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')

    assert main(["extract_metadata.py", str(path), "[]"]) == 0

    assert list(json.loads(capsys.readouterr().out)) == list(Report.__annotations__)



def test_format_outputs_python_matrix() -> None:
    report = Report(
        name="a",
        normalized_name="a",
        version="1",
        normalized_version="1",
        description="",
        readme="",
        license="",
        license_files=[],
        authors=[],
        urls={},
        keywords=[],
        classifiers=[],
        scripts={},
        requires_python="",
        extras=[],
        groups=[],
        build_backend="",
        build_requires=[],
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
        license_files=[],
        authors=[],
        urls={},
        keywords=[],
        classifiers=[],
        scripts={},
        requires_python=">=4",
        extras=[],
        groups=[],
        build_backend="",
        build_requires=[],
        python_versions=[],
        python_min="",
        python_max="",
        project_dependencies={},
        dependency_specifiers={},
        dependency_requirements={},
        warnings=[],
    )

    assert format_outputs(report)["python-matrix"] == '{"python-version":[]}'



def test_format_outputs_normalized_version() -> None:
    report = Report(
        name="a",
        normalized_name="a",
        version="1.0-RC1",
        normalized_version="1.0rc1",
        description="",
        readme="",
        license="",
        license_files=[],
        authors=[],
        urls={},
        keywords=[],
        classifiers=[],
        scripts={},
        requires_python="",
        extras=[],
        groups=[],
        build_backend="",
        build_requires=[],
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



def test_github_output_has_no_schema_version(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "a"\nversion = "1"\n')
    output = tmp_path / "out"

    assert main(["extract_metadata.py", "--github-output", str(output), str(path), "[]"]) == 0
    assert "schema-version" not in parse_github_output(output.read_text(encoding="utf-8"))



def test_the_format_of_the_boolean_inputs_is_stated_once_in_the_readme() -> None:
    readme = " ".join(README_PATH.read_text(encoding="utf-8").split())

    assert readme.count("the case and the surrounding spaces are ignored") == 1
    assert "case and surrounding spaces are ignored" not in readme
    assert "surrounding" not in ACTION_PATH.read_text(encoding="utf-8")



def test_action_section_keys_finds_the_inputs_and_outputs() -> None:
    assert "pyproject-path" in _action_section_keys("inputs")
    assert "normalized-name" in _action_section_keys("outputs")



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
        "license-files",
        "authors",
        "urls",
        "keywords",
        "classifiers",
        "scripts",
        "build-backend",
        "build-requires",
        "python-matrix",
        "dependency-requirements",
    }



def test_format_summary() -> None:
    assert format_summary(format_outputs(METADATA)) == (
        "📦 name=coola version=1.2.3 requires-python=>=3.10 "
        'python-versions=["3.11","3.12","3.13","3.14","3.15"] python-min=3.11 python-max=3.15 extras=["","numpy"] '
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
