"""Helpers shared by the test modules: paths, fixtures files and
builders of inputs."""

import argparse
import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

import packaging
import pytest
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet

import extract_pyproject_metadata.cli as extract_metadata_module
from extract_pyproject_metadata.dependencies.lookup import extract_dependency_specifiers
from extract_pyproject_metadata.inputs import parse_string_array
from extract_pyproject_metadata.metadata import extract_metadata
from extract_pyproject_metadata.pyproject import load_pyproject
from extract_pyproject_metadata.types import Inputs, Metadata, Report

ROOT_PATH = Path(__file__).resolve().parents[1]
SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "extract_metadata.py"
PACKAGE_PATH = Path(__file__).resolve().parents[1] / "src" / "extract_pyproject_metadata"
RUN_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run.sh"


REQUIREMENTS_PATH = Path(__file__).resolve().parents[1] / "scripts" / "requirements.txt"


# ``packaging.licenses`` (which checks the license expressions) needs packaging 24.2 or later.
requires_licenses = pytest.mark.skipif(
    importlib.util.find_spec("packaging.licenses") is None,
    reason="packaging before 24.2 cannot validate license expressions",
)


def write_pyproject(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "pyproject.toml"
    path.write_text(content)
    return path


def extract(path: Path, extra_values_json: str = "[]") -> Metadata:
    """Load ``path`` and extract its metadata."""
    metadata, _ = extract_metadata(
        load_pyproject(str(path)), parse_string_array(extra_values_json, "extra-values"), str(path)
    )
    return metadata


def specifiers(path: Path, dependencies_json: str) -> dict:
    """Load ``path`` and extract the specifiers of the requested
    dependencies."""
    result, _ = extract_dependency_specifiers(
        load_pyproject(str(path)), parse_string_array(dependencies_json, "dependencies"), str(path)
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
    "requires_python": ">=3.10",
    "extras": ["", "numpy"],
    "groups": ["dev", "test"],
    "build_backend": "",
    "build_requires": [],
    "python_versions": ["3.11", "3.12", "3.13", "3.14", "3.15"],
    "python_min": "3.11",
    "python_max": "3.15",
    "project_dependencies": {"numpy": ">=1", "Foo_Bar": ""},
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


def parse_args(*argv: str) -> argparse.Namespace:
    """Parse a command line like ``main`` does."""
    return extract_metadata_module._build_parser("extract_metadata.py").parse_args(list(argv))


def parse_inputs_args(*argv: str) -> Inputs:
    """Parse a command line like ``main`` does and validate the inputs."""
    return extract_metadata_module.parse_cli_inputs(parse_args(*argv))


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


def _action_section_keys(section: str) -> list[str]:
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


def _readme_table_names(heading: str) -> list[str]:
    """Return the names (first column) of the table under the ``##
    <heading>`` of the README."""
    readme = README_PATH.read_text(encoding="utf-8")
    section = readme.split(f"\n## {heading}\n", 1)[1].split("\n#", 1)[0]
    return re.findall(r"^\| `([a-z-]+)`", section, flags=re.MULTILINE)


def _specifier_error(raw: str) -> InvalidSpecifier:
    """Return the error that ``packaging`` raises for the invalid
    specifier ``raw``."""
    with pytest.raises(InvalidSpecifier) as exc_info:
        SpecifierSet(raw)
    return exc_info.value


def _parse_error(raw: str) -> InvalidRequirement:
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


STUB_SYSTEM_PYTHON = """#!/usr/bin/env bash
case "$1" in
  -c)
    case "$2" in
      *version_info*) name=version; status="${STUB_VERSION_STATUS:-0}" ;;
      *)
        name=probe
        if [ -n "${STUB_REAL_PYTHON:-}" ]; then
          # The real check of run.sh, run by a real Python with a "packaging" of another version.
          PYTHONPATH="$STUB_FAKE_PACKAGING" "$STUB_REAL_PYTHON" -c "$2" "${@:3}" 2>/dev/null
          status=$?
        else
          status="${STUB_PROBE_STATUS:-0}"
        fi ;;
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
  *) printf '%s\\037' python3 "$@" >> "$STUB_LOG"; echo >> "$STUB_LOG"
     echo "${PYTHONDONTWRITEBYTECODE-unset}" > "$STUB_LOG.bytecode"
     exit "${STUB_SCRIPT_STATUS:-0}" ;;
esac
"""


STUB_VENV_PYTHON = """#!/usr/bin/env bash
printf '%s\\037' venv-python "$@" >> "$STUB_LOG"; echo >> "$STUB_LOG"
if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then exit "${STUB_PIP_STATUS:-0}"; fi
exit "${STUB_SCRIPT_STATUS:-0}"
"""


STUB_UV = """#!/usr/bin/env bash
printf '%s\\037' uv "$@" >> "$STUB_LOG"; echo >> "$STUB_LOG"
case "$1" in
  venv)
    [ "${STUB_VENV_STATUS:-0}" = 0 ] || exit "$STUB_VENV_STATUS"
    venv="${@: -1}"
    mkdir -p "$venv/bin"
    cp "$STUB_VENV_PYTHON" "$venv/bin/python"
    chmod +x "$venv/bin/python"
    exit 0 ;;
  pip) exit "${STUB_PIP_STATUS:-0}" ;;
esac
"""


class RunResult:
    """Outcome of ``run.sh``: the process, the calls to the stubs and
    the directory of the venvs."""

    def __init__(self, process: subprocess.CompletedProcess[str], log: Path, temp: Path) -> None:
        self.process = process
        self.calls = (
            [line.split("\x1f")[:-1] for line in log.read_text().splitlines()]
            if log.exists()
            else []
        )
        self.venvs = sorted(
            temp.glob("extract-pyproject-metadata-venv.*")
        )  # the ones left after the run
        self.created_venvs = [
            Path(call[-1])
            for call in self.calls
            if call[:3] == ["python3", "-m", "venv"] or call[:2] == ["uv", "venv"]
        ]


def run_run_sh(tmp_path: Path, args: list[str], *, with_uv: bool = False, **env: str) -> RunResult:
    """Run ``run.sh`` with the stubs and the status codes in ``env``.

    Args:
        tmp_path: The directory of the test.
        args: The arguments of ``run.sh``.
        with_uv: Whether a stub of ``uv`` is on ``PATH``.
        env: The environment variables of the run.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "python3").write_text(STUB_SYSTEM_PYTHON)
    (bin_dir / "python3").chmod(0o755)
    if with_uv:
        (bin_dir / "uv").write_text(STUB_UV)
        (bin_dir / "uv").chmod(0o755)
    venv_python = tmp_path / "venv-python"
    venv_python.write_text(STUB_VENV_PYTHON)
    temp = tmp_path / "runner-temp"
    temp.mkdir(exist_ok=True)
    log = tmp_path / "calls.log"
    log.unlink(missing_ok=True)  # only the calls of this run
    process = subprocess.run(
        ["/bin/bash", str(RUN_PATH), *args],
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


def fake_packaging(tmp_path: Path, version: str) -> Path:
    """Return a directory with a copy of ``packaging`` that says it is
    ``version``."""
    fake = tmp_path / f"fake-packaging-{version}"
    shutil.copytree(Path(packaging.__file__).parent, fake / "packaging")
    init = fake / "packaging" / "__init__.py"
    init.write_text(re.sub(r"__version__ = .*", f'__version__ = "{version}"', init.read_text()))
    return fake
