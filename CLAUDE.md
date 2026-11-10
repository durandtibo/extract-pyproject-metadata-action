# Instructions for coding agents

## Repository

This repository is a GitHub composite action (`action.yaml`) that reads the
project name, version, extra names and dependency specifiers from a
`pyproject.toml`. The logic lives in the package `src/extract_pyproject_metadata/`, started by
`scripts/run.sh` through the launcher `scripts/extract_metadata.py`; the action
only wires its inputs and outputs. `test-data/` holds the `pyproject.toml`
fixtures used by the integration workflows.

## Architecture

The package `src/extract_pyproject_metadata/` is split by concern. Imports go one
way, from the bottom of this list to the top, and a module never imports from a
module above it:

1. `errors` (`MetadataError`), `types` (`Inputs`, `Metadata`, `Report`), `checks`
   (type checks of the values read from the file), `inputs` (`parse_inputs`: the
   single place that validates the input strings and builds `Inputs`).
2. `pyproject` (read and parse the file, the names of the extras and groups),
   `dynamic_version` (a dynamic version read statically from the file of the build
   backend), `metadata` (`extract_metadata`: name, version, `requires-python`, extras
   and groups). Only what the action outputs is read and validated.
3. `requirements` (the requirements of `[project].dependencies`, the extras and the
   groups with `include-group`, and the lookup of the requested dependencies) and
   `python_versions`.
4. `output/` (`escaping`, `github`, `summary`): action outputs, workflow
   commands and job summary. It only depends on `types` and `errors`.
5. `report` (`build_report`) wires 2 to 4 together; `cli` (argument parser and
   `main`) is the top.

- The core never sees `argparse`: `cli` maps the command line to `Inputs`
  (`parse_cli_inputs`), and `build_report(inputs)` takes plain values.
- Put a new function in the module of its concern; create a module (and its
  test module) instead of growing one past a few hundred lines. A constant
  lives in the module that uses it.
- A name used by another module is public (no leading underscore) and listed in
  the `__all__` of its module; `tests/unit/test_package.py` checks the lists.
  Use a verb prefix (`read_`, `parse_`, `format_`) so that a function is not
  shadowed by the variable that holds its result.
- Pass a collaborator that a test needs to replace (a delimiter factory, a
  path) as an argument with a default, instead of monkeypatching a module.
- Every module has a docstring, and `from __future__ import annotations`.

## Environment

- Use a virtual environment in `.venv` (`python -m venv .venv`, then
  `.venv/bin/pip install --group dev`, or `make install`
  which runs `uv sync --group dev`) and run `.venv/bin/python`, `.venv/bin/pytest`,
  `.venv/bin/ruff check src scripts tests` (must pass) and `.venv/bin/pyright`
  (strict on `src` and `scripts`; must pass). There is no mypy and no `ty`.
- The `Makefile` is the only task runner: `make help` lists the targets, for
  example `make check` (ruff, format check, pyright, tests with the coverage gate),
  `make test`, `make fix`, `make format` and `make lint`. They run in the
  environment (`uv run`). `.make/` is shared with other repositories and synced
  by a bot: do not edit it here.
- `pyproject.toml` holds the tool configuration and the `dev` group; the repository
  is not a Python distribution (`[tool.uv] package = false`) and the action has no
  runtime dependency: `packaging` is vendored in
  `src/extract_pyproject_metadata/_vendor/` (excluded from ruff, pyright, coverage and
  codespell). Import it as `extract_pyproject_metadata._vendor.packaging`, never as
  `packaging` (a test checks it). Do not edit the vendored files: update them with
  `make vendor-packaging VERSION=x.y`.
- `pre-commit` (`.pre-commit-config.yaml`) runs ruff, shfmt, shellcheck,
  codespell and pyright. The layering of the architecture above is enforced by
  `tests/test_layers.py` (a rank per module): update it with the architecture.
- Run the unit tests with `.venv/bin/pytest -q`. Some tests may fail on `main`;
  check with `git stash` before blaming your change.
- Only Python >= 3.11 is supported (the script uses `tomllib`). The script may only use the
  standard library and the vendored `packaging`. `run.sh` installs nothing.
- Workflows cannot be run locally. Say so in the PR instead of claiming they
  pass.

## Workflow

- One branch and one pull request per logical change. Branch from an up to date
  `main`, and do not commit or push to `main`.
- Name the branch `<type>/<short-description>` in lowercase kebab-case, with one
  of these types: `feat`, `bugfix`, `hotfix`, `docs`, `refactor`, `perf`,
  `test`, `chore`, `ci`.
- In the PR description, say what was changed, what was deliberately not
  changed, and any behaviour change (for example a changed input, default or
  output of the action).
- When a PR conflicts with `main`, merge `origin/main` into the branch (do not
  rebase and force-push).
- Update `README.md` when inputs, outputs or failure modes change.

## Action (`action.yaml`)

- Keep the input and output names, defaults and descriptions consistent with
  `README.md`. Renaming or removing an input or output is a breaking change:
  call it out in the PR.
- Pass inputs to shell and Python through `env:`, never by interpolating
  `${{ inputs.* }}` in `run:`.
- Every `run:` step sets `shell: bash` (required in composite actions).
- Pin every third-party action to a commit SHA or the major tag already used in
  the repository's workflows; do not use a branch.
- Keep the logic in `src/extract_pyproject_metadata/` and `scripts/run.sh` (which
  finds Python 3.11 or later and starts the script), not inline in
  `action.yaml`. Invalid input must fail with a clear message on stderr and a non-zero exit.

## Python script

- Keep `from __future__ import annotations`, type hints and docstrings on every
  function, including private ones. Update the module docstring when the
  usage or JSON output changes.
- Raise `MetadataError` for user-facing errors; `main` turns it into an exit
  code and a stderr message.
- Dependency names are compared per PEP 503 (`canonicalize_name`).

## Tests

- The tests mirror the package. `tests/unit/` has one module per module of
  `src/extract_pyproject_metadata/` (`tests/unit/test_metadata.py`,
  `tests/unit/test_requirements.py`, `tests/unit/output/test_github.py`,
  ...). `tests/integration/` runs the command line in a new process
  (`test_cli_process.py`, `test_cli_invalid_arguments.py`, `test_limits.py`),
  `run.sh` (`test_run_sh.py`) and checks that `action.yaml` and `README.md`
  agree with the code (`test_contract.py`); `tests/properties/` has the
  property-based tests. Put a new test in the module of its area. Write one
  for every new or changed function, including private ones, and for every bug
  fixed (check that it fails without the fix).
- Shared builders and constants are in `tests/helpers.py` (import them with
  `from tests.helpers import ...`; every test directory has an `__init__.py`).
  The import path of `src/` is the `pythonpath` of `pyproject.toml`.
- Build `pyproject.toml` contents with `tmp_path` and `write_pyproject`; no
  network, no sleeps.
- One behaviour per test, with `pytest.mark.parametrize` for the same check on
  several values. Every `pytest.raises` defines `match`.
- Cover typical inputs, edge cases (empty, duplicates, missing keys), and error
  conditions. Assert whole outputs against a literal (`assert result == {...}`).
- `test-data/<case>/` is a golden case: a `pyproject.toml`, an optional
  `inputs.json` (the action inputs of the case, by input name) and the
  `expected.json` (the `json` output). `tests/integration/test_golden.py` checks
  every case without GitHub; `UPDATE_GOLDEN=1 pytest tests/integration/test_golden.py`
  rewrites the files (review the diff). Adding a case is adding a directory.
- The integration workflow `.github/workflows/ci-test-local.yaml` (`uses: ./`)
  checks only the wiring: the `golden` job runs the real action on every case and
  compares the `json` output with `expected.json` (`scripts/compare_json.py`);
  the other jobs check what the golden files cannot see (failures, `strict`,
  what the action leaves behind). Pass values through `env:`, never interpolate
  them in `run:` (a test checks it). A job that tests something added after the
  latest release has a `# local-only` comment; the others are copied to
  `nightly-test-stable.yaml` (the latest release) by `make workflows`, and CI
  fails when the copy is out of date. Add a case or a job for every new input or
  output, and update `STABLE_REF` in `scripts/generate_workflows.py` with every
  release.

## Reporting

- Report faithfully: say which tests were run, which were not, and that the
  workflows and CI were not awaited.
- Mention failures that already exist on `main` instead of hiding them.
