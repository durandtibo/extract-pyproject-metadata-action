"""Tests that action.yaml, README.md and the module docstring agree with the script."""



import ast
import re
from pathlib import Path

import pytest
from helpers import (
    ACTION_PATH,
    PACKAGE_PATH,
    README_PATH,
    _action_section_keys,
    _readme_table_names,
    extract,
    write_pyproject,
)

import extract_pyproject_metadata.cli as extract_metadata_module
from extract_pyproject_metadata.cli import DEFAULT_PYTHON_CANDIDATES
from extract_pyproject_metadata.types import Metadata, Report


def test_metadata_keys_match_the_extracted_metadata(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')

    assert list(extract(path)) == list(Metadata.__annotations__)



def test_action_yaml_default_of_python_candidates_matches_the_script() -> None:
    action = (Path(__file__).resolve().parents[1] / "action.yaml").read_text(encoding="utf-8")

    assert f"default: '{DEFAULT_PYTHON_CANDIDATES}'" in action



def test_action_yaml_separates_the_inputs_with_a_blank_line() -> None:
    lines = ACTION_PATH.read_text(encoding="utf-8").splitlines()
    inputs = lines[lines.index("inputs:") : lines.index("outputs:")]
    starts = [index for index, line in enumerate(inputs) if re.match(r"^  [a-z][a-z-]*:\s*$", line)]

    assert len(starts) == len(_action_section_keys("inputs"))
    assert [inputs[index - 1] for index in starts[1:]] == [""] * (len(starts) - 1)



def test_action_yaml_inputs_do_not_repeat_the_default_of_required() -> None:
    action = ACTION_PATH.read_text(encoding="utf-8")

    assert "required:" not in action



def test_action_yaml_every_input_has_a_default() -> None:
    lines = ACTION_PATH.read_text(encoding="utf-8").splitlines()
    inputs = "\n".join(lines[lines.index("inputs:") : lines.index("outputs:")])

    assert inputs.count("    default:") == len(_action_section_keys("inputs"))



def test_the_readme_lists_the_boolean_inputs_of_parse_options() -> None:
    readme = " ".join(README_PATH.read_text(encoding="utf-8").split())
    names = ", ".join(f"`{name}`" for name in ("fail-on-dynamic-version", "fail-on-missing", "strict"))

    assert f"{names} and `step-summary` are boolean inputs" in readme



@pytest.mark.parametrize(("section", "heading"), [("inputs", "Inputs"), ("outputs", "Outputs")])
def test_readme_documents_the_inputs_and_outputs_of_action_yaml(
    section: str, heading: str
) -> None:
    assert sorted(_readme_table_names(heading)) == sorted(_action_section_keys(section))



def test_module_docstring_lists_the_outputs_of_action_yaml() -> None:
    docstring = " ".join(extract_metadata_module.__doc__.split())
    section = docstring.split("appends the action outputs", 1)[1].split("It also prints", 1)[0]

    assert sorted(re.findall(r"``([a-z-]+)``", section)) == sorted(_action_section_keys("outputs"))



def test_module_docstring_lists_the_keys_of_the_json() -> None:
    docstring = extract_metadata_module.__doc__
    section = docstring.split("prints a single JSON object", 1)[1].split("\n\n", 1)[0]

    assert sorted(re.findall(r'"([a-z_]+)":', section)) == sorted(Report.__annotations__)


@pytest.mark.parametrize("path", sorted(PACKAGE_PATH.rglob("*.py")), ids=lambda path: path.name)
def test_module_defines_each_top_level_name_once(path: Path) -> None:
    names = [
        target.id
        for node in ast.parse(path.read_text(encoding="utf-8")).body
        for target in _defined_names(node)
    ]

    assert [name for name in names if names.count(name) > 1] == []


def _defined_names(node: ast.stmt) -> list[ast.Name]:
    """Return the names that a top-level statement assigns."""
    if isinstance(node, ast.Assign):
        return [target for target in node.targets if isinstance(target, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target]
    return []
