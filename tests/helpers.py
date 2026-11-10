"""Helpers shared by the test modules: paths, fixtures files and
builders of inputs."""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import extract_pyproject_metadata.cli as extract_metadata_module
from extract_pyproject_metadata._vendor.packaging.requirements import (
    InvalidRequirement,
    Requirement,
)
from extract_pyproject_metadata._vendor.packaging.specifiers import InvalidSpecifier, SpecifierSet
from extract_pyproject_metadata.inputs import parse_dependencies, parse_string_array
from extract_pyproject_metadata.pyproject import load_pyproject
from extract_pyproject_metadata.report import build_report
from extract_pyproject_metadata.requirements import (
    collect_requirements,
    lookup_requirements,
    lookup_specifiers,
)
from extract_pyproject_metadata.types import Inputs, Report

ROOT_PATH = Path(__file__).resolve().parents[1]
SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "extract_metadata.py"
PACKAGE_PATH = Path(__file__).resolve().parents[1] / "src" / "extract_pyproject_metadata"
RUN_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run.sh"


def write_pyproject(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "pyproject.toml"
    path.write_text(content)
    return path


METADATA_KEYS = (
    "name",
    "normalized_name",
    "file_name",
    "version",
    "normalized_version",
    "requires_python",
    "extras",
    "groups",
)


def extract_with_warnings(path: Path, extra_values_json: str = "[]") -> tuple[dict, list[str]]:
    """Build the report of ``path`` and return the project fields and the warnings."""
    report = build_report(
        Inputs(
            pyproject_path=str(path),
            extra_values=parse_string_array(extra_values_json, "extra-values"),
            dependencies=[],
            python_candidates=[],
            strict=False,
        )
    )
    return {key: report[key] for key in METADATA_KEYS}, report["warnings"]


def extract(path: Path, extra_values_json: str = "[]") -> dict:
    """Build the report of ``path`` and return the project fields."""
    return extract_with_warnings(path, extra_values_json)[0]


def messages(warnings: list) -> list[str]:
    """The messages of warnings (``ReportWarning`` or the items of a report)."""
    return [w["message"] if isinstance(w, dict) else w.message for w in warnings]


def dynamic_fields(data: dict) -> frozenset[str]:
    """The fields of ``[project].dynamic`` of parsed data, empty if it is not a valid array."""
    project = data.get("project")
    dynamic = project.get("dynamic", []) if isinstance(project, dict) else []
    return frozenset(dynamic) if isinstance(dynamic, list) else frozenset()


def extract_dependency_specifiers(
    data: dict, dependencies: list[str]
) -> tuple[dict[str, str | None], list[str]]:
    """Look up the specifiers of ``dependencies`` in parsed data, with the warnings (the
    ones of the requirements, then the ones of the lookup)."""
    dynamic = dynamic_fields(data)
    requirements, warnings = collect_requirements(data, dynamic)
    result, lookup_warnings = lookup_specifiers(
        requirements, parse_dependencies(json.dumps(dependencies))
    )
    return result, [*(warnings if dependencies else []), *lookup_warnings]


def extract_dependency_requirements(
    data: dict, dependencies: list[str]
) -> dict[str, list[dict[str, str]]]:
    """List all the requirements of ``dependencies`` in parsed data."""
    dynamic = dynamic_fields(data)
    requirements, _ = collect_requirements(data, dynamic)
    return lookup_requirements(requirements, parse_dependencies(json.dumps(dependencies)))


def specifiers(path: Path, dependencies_json: str) -> dict:
    """Load ``path`` and extract the specifiers of the requested
    dependencies."""
    result, _ = extract_dependency_specifiers(
        load_pyproject(str(path)), parse_string_array(dependencies_json, "dependencies")
    )
    return result


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


METADATA: Report = {
    "name": "coola",
    "normalized_name": "coola",
    "file_name": "coola",
    "version": "1.2.3",
    "normalized_version": "1.2.3",
    "requires_python": ">=3.10",
    "extras": ["", "numpy"],
    "groups": ["dev", "test"],
    "python_versions": ["3.11", "3.12", "3.13", "3.14", "3.15"],
    "python_min": "3.11",
    "python_max": "3.15",
    "dependency_specifiers": {"numpy": ">=1", "missing": None},
    "dependency_requirements": {
        "numpy": [{"specifier": ">=1", "marker": ""}],
        "missing": [],
    },
    "warnings": [],
    "schema_version": 1,
}


def parse_github_output(text: str) -> dict[str, str]:
    """Parse a ``$GITHUB_OUTPUT`` file like the runner does (``k=v`` and
    ``k<<DELIM``)."""
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


OPTION_VARIABLES = {
    "--strict": "INPUT_STRICT",
    "--python-candidates": "INPUT_PYTHON_CANDIDATES",
    "--github-output": "GITHUB_OUTPUT",
}
POSITIONAL_VARIABLES = ("INPUT_PYPROJECT_PATH", "INPUT_EXTRA_VALUES", "INPUT_DEPENDENCIES")


def env_from_args(*argv: str) -> dict[str, str]:
    """Build the environment of the program from a short form that the tests use: options
    ``--strict``, ``--python-candidates`` and ``--github-output`` followed by their value, then
    the path of the file, the extra values and the dependencies (the last is optional)."""
    environ: dict[str, str] = {}
    positional: list[str] = []
    items = iter(argv)
    for item in items:
        if item in OPTION_VARIABLES:
            environ[OPTION_VARIABLES[item]] = next(items)
        elif item != "--":
            positional.append(item)
    environ.update(zip(POSITIONAL_VARIABLES, positional, strict=False))
    return environ


def run_main(argv: list[str], environ: dict[str, str] | None = None) -> int:
    """Run ``main`` on the environment built by ``env_from_args``."""
    return extract_metadata_module.main({**env_from_args(*argv), **(environ or {})})


def run_script(
    argv: list[str], flags: tuple[str, ...] = ("-I",), check: bool = False
) -> subprocess.CompletedProcess[str]:
    """Start ``scripts/extract_metadata.py`` in a new process, with the environment built by
    ``env_from_args`` (and the variables of the test without ``INPUT_*`` and the file of
    GitHub). ``flags`` are the options of the interpreter."""
    base = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("INPUT_") and key != "GITHUB_OUTPUT"
    }
    return subprocess.run(
        [sys.executable, *flags, str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        check=check,
        timeout=60,
        env={**base, **env_from_args(*argv)},
    )


def parse_inputs_args(*argv: str) -> Inputs:
    """Validate the inputs of a short command line (see ``env_from_args``)."""
    return extract_metadata_module.read_inputs(env_from_args(*argv))


def chain_of_groups(length: int) -> dict[str, list]:
    """Groups ``g0`` to ``g<length-1>``, each including the next one;
    the last has a requirement."""
    groups: dict[str, list] = {f"g{i}": [{"include-group": f"g{i + 1}"}] for i in range(length - 1)}
    groups[f"g{length - 1}"] = ["numpy>=1"]
    return groups


def diamond_of_groups(levels: int) -> dict[str, list]:
    """Groups that each include the next one twice: ``g0`` expands to
    ``2**levels`` entries."""
    groups: dict[str, list] = {
        f"g{i}": [{"include-group": f"g{i + 1}"}, {"include-group": f"g{i + 1}"}]
        for i in range(levels)
    }
    groups[f"g{levels}"] = ["numpy>=1"]
    return groups


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


GROUPS_TOML = """
[project]
name = "p"
version = "1"

[dependency-groups]
test = ["pytest"]
Dev = ["ruff"]
docs = []
"""


CANDIDATES = ["3.9", "3.10", "3.11", "3.12", "3.13"]


ACTION_PATH = Path(__file__).resolve().parents[1] / "action.yaml"


README_PATH = Path(__file__).resolve().parents[1] / "README.md"


def action_section_keys(section: str) -> list[str]:
    """Return the names under the top-level ``inputs:`` or ``outputs:``
    key of action.yaml."""
    keys: list[str] = []
    in_section = False
    for line in ACTION_PATH.read_text(encoding="utf-8").splitlines():
        if re.match(r"^\S", line):
            in_section = line.startswith(f"{section}:")
        elif in_section and (match := re.match(r"^  ([a-z][a-z-]*):\s*$", line)):
            keys.append(match.group(1))
    return keys


def readme_table_names(heading: str) -> list[str]:
    """Return the names (first column) of the table under the ``##
    <heading>`` of the README."""
    readme = README_PATH.read_text(encoding="utf-8")
    section = readme.split(f"\n## {heading}\n", 1)[1].split("\n#", 1)[0]
    return re.findall(r"^\| `([a-z-]+)`", section, flags=re.MULTILINE)


def specifier_error(raw: str) -> InvalidSpecifier:
    """Return the error that ``packaging`` raises for the invalid
    specifier ``raw``."""
    with pytest.raises(InvalidSpecifier) as exc_info:
        SpecifierSet(raw)
    return exc_info.value


def parse_error(raw: str) -> InvalidRequirement:
    """Return the error that ``packaging`` raises for the invalid
    requirement ``raw``."""
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


DATA_WITH_SCOPES = """\
[project]
name = "a"
version = "1"
dependencies = ["numpy>=1.20", "tqdm"]

[project.optional-dependencies]
Fast = ["numpy>=2", "ujson"]
slow = ["numpy<2"]

[dependency-groups]
lint = ["ruff>=0.5"]
dev = ["numpy>=1.26", {include-group = "lint"}, "pytest"]
"""


STUB_PYTHON = """#!/usr/bin/env bash
# A stand-in for a Python interpreter: logs the calls, answers the version check with
# STUB_VERSION_STATUS_<NAME> (0 = Python 3.11 or later) and runs the script with the
# status STUB_SCRIPT_STATUS.
if [ "$1" = "-c" ]; then
  status="STATUS_VAR"
  exit "${!status:-0}"
fi
printf '%s\\037' NAME "$@" >> "$STUB_LOG"; echo >> "$STUB_LOG"
echo "from-$$" >&2
exit "${STUB_SCRIPT_STATUS:-0}"
"""


def run_run_sh(
    tmp_path: Path, *, pythons: tuple[str, ...] = ("python3",), **env: str
) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    """Run ``run.sh`` with stand-ins for the interpreters ``pythons`` on ``PATH``.

    Args:
        tmp_path: The directory of the test.
        pythons: The names of the interpreters that exist (``python3``, ``python``).
        env: The environment variables of the run: ``STUB_VERSION_STATUS_<NAME>`` (the status of
            the version check of an interpreter, in capitals) and ``STUB_SCRIPT_STATUS``.

    Returns:
        The process, and the calls that ran the script: the name of the interpreter, then its
        arguments.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name in pythons:
        stub = bin_dir / name
        stub.write_text(
            STUB_PYTHON.replace("NAME", name).replace(
                "STATUS_VAR", f"STUB_VERSION_STATUS_{name.upper()}"
            )
        )
        stub.chmod(0o755)
    # Only the tools of the scripts are on PATH, so a real python3 of the machine is not found.
    tools_dir = bin_dir / "tools"
    tools_dir.mkdir(exist_ok=True)
    for tool in ("bash", "dirname"):
        link = tools_dir / tool
        if not link.exists():
            link.symlink_to(shutil.which(tool) or f"/usr/bin/{tool}")
    log = tmp_path / "calls.log"
    log.unlink(missing_ok=True)  # only the calls of this run
    process = subprocess.run(
        ["/bin/bash", str(RUN_PATH)],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": f"{bin_dir}:{tools_dir}", "STUB_LOG": str(log), **env},
    )
    calls = (
        [line.split("\x1f")[:-1] for line in log.read_text().splitlines()] if log.exists() else []
    )
    return process, calls
