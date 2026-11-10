# Instructions for coding agents

Guidance for coding agents working in this repository.

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
module above it (`tests/test_layers.py` holds the ranks and is the source of the graph):

1. `errors` (`MetadataError`), `types` (`Inputs`, `Project`, `Report`): no import of the
   package. Then `warning_codes` (the codes of the warnings), `checks` (type checks of the
   values read from the file) and `python_versions` (the default `python-candidates` and the
   compatible versions; it depends on `types` and the vendored `packaging` only).
2. `inputs` (`parse_inputs`: the single place that validates the input strings and builds
   `Inputs`; it imports `python_versions` for the default) and `pyproject` (read and parse the
   file; `read_project`: name, version, `requires-python`, `dynamic`, extras and groups, as a
   `Project`). Only what the action outputs is read and validated; `report` derives the
   normalized names.
3. `requirements` (the requirements of `[project].dependencies`, the extras and the
   groups with `include-group`, and the lookup of the requested dependencies).
4. `github`: the action outputs (`$GITHUB_OUTPUT`), the workflow commands (annotations),
   the log line and their escaping. It only depends on `types` and `errors`.
5. `report` (`build_report`) wires 2 to 4 together; `cli` (`main`: reads the
   inputs from the environment, `INPUT_*` and `GITHUB_OUTPUT`) is the top.

- The program has no command line: `cli.main(environ)` reads the inputs of the action from
  the variables `INPUT_PYPROJECT_PATH`, `INPUT_EXTRA_VALUES`, ... (`read_inputs`), and
  `build_report(inputs)` takes plain values. `GITHUB_OUTPUT` set means a workflow run.
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

## Supported platforms

- Linux and macOS only. **Windows is not supported, and that is a deliberate,
  final decision of the maintainer.** Do not add `windows-latest` to any matrix,
  do not add Windows-specific code, branches, tests or documentation, and do not
  propose or re-add Windows support, even as a small or optional change. If a
  failure only happens on Windows, it is out of scope.

## Environment

- Use a virtual environment in `.venv` (`python -m venv .venv`, then
  `.venv/bin/pip install --group dev --group property`, or `make install`
  which runs `uv sync --group dev --group property`) and run `.venv/bin/python`, `.venv/bin/pytest`,
  `.venv/bin/ruff check src scripts tests` (must pass) and `.venv/bin/pyright`
  (strict on `src` and `scripts`; must pass). There is no mypy and no `ty`.
- The `Makefile` is the only task runner: `make help` lists the targets, for
  example `make check` (ruff, format check, pyright, tests with the coverage gate),
  `make test`, `make fix`, `make format` and `make lint`. They run in the
  environment (`uv run`). Run `make fix`/`make format` and `make check` before committing, and
  fix what they report: ignoring an issue (`noqa`, `type: ignore`, a `cast` that hides the
  problem, a changed rule set) is not fixing it. `.make/` is shared with other repositories and synced
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
- When several PRs depend on each other, stack them: branch each PR from the branch of the
  previous one and open it with that branch as its base. Keep each PR small and reviewable on its
  own. Once a PR of the stack is merged, retarget the next one to `main` and merge `origin/main`
  into it.
- Name the branch `<type>/<short-description>` in lowercase kebab-case, with one
  of these types: `feat`, `bugfix`, `hotfix`, `docs`, `refactor`, `perf`,
  `test`, `chore`, `ci`.
- In the PR description, say what was changed, what was deliberately not
  changed, and any behaviour change (for example a changed input, default or
  output of the action).
- Releases are made by pushing a tag `vX.Y.Z` (never from a PR): `.github/workflows/release.yaml`
  creates the GitHub release from `release-notes/vX.Y.Z.md` and moves no tag: workflows pin the
  exact tag (`@v0.3.0`). The checklist is in
  the README. Do not create or move tags.
- When a PR conflicts with `main`, merge `origin/main` into the branch and resolve the
  conflicts (do not rebase and force-push). Check what `main` already contains before choosing
  a side; most conflicts are two PRs appending tests to the same file: keep both.
- Update `README.md` when inputs, outputs or failure modes change. The tables of inputs and
  outputs and the default `python-candidates` are generated from `action.yaml` and the code:
  run `make docs` (CI fails on a diff). Every YAML and TOML block of the README is a fixture
  (`tests/examples/*.yaml`, `test-data/readme-example/`) that a test compares with the
  README; the README tells the current behaviour only, no history. Release notes go to the
  GitHub release.

## Action (`action.yaml`)

- Keep the input and output names, defaults and descriptions consistent with
  `README.md`. Renaming or removing an input or output is a breaking change:
  call it out in the PR.
- Pass inputs to shell and Python through `env:`, never by interpolating
  `${{ inputs.* }}` in `run:`.
- Every `run:` step sets `shell: bash` (required in composite actions).
- Pin every third-party action to a commit SHA with a `# ratchet:<owner>/<repo>@<tag>` comment
  (`bot-pin-action.yaml` maintains them); never a tag or a branch.
- Keep the logic in `src/extract_pyproject_metadata/` and `scripts/run.sh` (which
  finds Python 3.11 or later and starts the script), not inline in
  `action.yaml`. Invalid input must fail with a clear message on stderr and a non-zero exit.
- Start each workflow with a comment saying what it does and when it runs, and update it when
  that changes. Use top-level `permissions: {}` or `contents: read`, the minimum permissions per
  job, and `timeout-minutes` on every job.
- Check workflow changes with `actionlint` when available.
- Do not use `concurrency` in the workflows (`.github/workflows/`), in any form: stale queued
  runs are cancelled by `bot-cancel-stale-queued-runs.yaml`. A test checks it.

## Workflow structure (`.github/workflows/`)

Files are prefixed by role:

- `ci.yaml`: entry point for pull requests, pushes to `main` and manual runs. It holds no steps,
  only jobs that call the reusable `ci-*.yaml` workflows below.
  - `ci-lint.yaml`: ruff, pre-commit hooks and the generated README tables.
  - `ci-type-checking.yaml`: pyright.
  - `ci-test-python.yaml`: the Python tests (unit, integration) on the OS and Python matrix.
  - `ci-test-python-properties.yaml`: the property-based tests, on the standard Python versions.
  - `ci-test-action.yaml`: runs the action from this checkout (`uses: ./`), i.e. the version not
    released yet.
- `ci-verify-workflows.yaml`: lints the workflow files themselves. It has its own triggers and is
  not called from `ci.yaml`.
- `nightly.yaml`: scheduled entry point that calls `nightly-test-released.yaml`, which tests the
  latest released action. It is not part of `ci.yaml`.
- `lib-get-test-matrix.yaml`: reusable workflow that loads the shared OS matrix once; callers pass
  it down through the `test-matrix` input.
- `bot-*.yaml`: scheduled automation that opens PRs or acts on runs (format files, pin actions,
  sync `.make/`, cancel stale runs).
- `release.yaml`: creates the GitHub release from a pushed tag.

Conventions:

- Each `ci-*` check is a `workflow_call` workflow that also has `workflow_dispatch`, so it can be
  run alone (the ones that take the `test-matrix` input have `workflow_call` only). Add a check as
  a new `ci-<name>.yaml` plus a job in `ci.yaml`.
- Name test workflows by what they test: `ci-test-action` tests the action, `ci-test-python` tests
  the Python code, `nightly-test-released` tests the published action.
- Put `make` targets in the steps rather than duplicating commands, so local runs and CI match.

## Python script

- Match the surrounding code: comment density, naming and docstring style. Look at a few
  neighbouring files first, and do not introduce a new convention or reformat code you do not
  otherwise change.
- Keep new options keyword-only (`*`).
- Keep docstrings and documentation up to date whenever the behaviour, signature or options of
  the code change.

- Keep `from __future__ import annotations`, type hints and docstrings on every
  function, including private ones. Update the module docstring when the
  usage or JSON output changes.
- Raise `MetadataError` for user-facing errors; `main` turns it into an exit
  code and a stderr message.
- Dependency names are compared per PEP 503 (`canonicalize_name`).

## Tests

- The tests mirror the package. `tests/unit/` has one module per module of
  `src/extract_pyproject_metadata/` (`tests/unit/test_pyproject.py`,
  `tests/unit/test_requirements.py`, `tests/unit/test_github.py`,
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
- Add the missing tests to keep the 100% coverage gate. Do not use `# pragma: no cover` to skip a
  line that can be tested.
- Import at the top of the test module, not inside a test body.
- Seed random data; no unseeded randomness in tests.
- When a test patches a collaborator, it only proves the logic against the stand-in. Every
  patched behaviour needs a test in `tests/integration/` that exercises the real thing.
- Test the edge cases too: empty and duplicate inputs, boundary values, error conditions (type
  and message), and that inputs are not mutated.
- When expecting a number, write the final value, not the arithmetic that produces it.
- One behaviour per test, with `pytest.mark.parametrize` for the same check on
  several values. Every `pytest.raises` defines `match`.
- Cover typical inputs, edge cases (empty, duplicates, missing keys), and error
  conditions. Assert whole outputs against a literal (`assert result == {...}`).
- `test-data/<case>/` is a golden case: a `pyproject.toml`, an optional
  `inputs.json` (the action inputs of the case, by input name) and the
  `expected.json` (the `json` output). `tests/integration/test_golden.py` checks
  every case without GitHub; `UPDATE_GOLDEN=1 pytest tests/integration/test_golden.py`
  rewrites the files (review the diff). Adding a case is adding a directory (it is checked by `test_golden.py`; add it to the
  `golden` matrix only if it covers a new input or output).
- The integration workflow `.github/workflows/ci-test-action.yaml` (`uses: ./`)
  checks only the wiring: the `golden` job runs the real action on three
  cases (`minimal`, `readme-example`, `python-candidates-none`: a three-item matrix) and
  compares the `json` output with `expected.json` (`scripts/compare_json.py`); a test checks that
  together they set every input and fill every output;
  the other jobs check what the golden files cannot see (failures, `strict`,
  what the action leaves behind). Pass values through `env:`, never interpolate
  them in `run:` (a test checks it). Add a case or a job for every new input or
  output. `nightly-test-released.yaml` (called from `nightly.yaml`) tests the latest
  published tag, pinned by SHA, with the inputs and outputs of that version; update the pin
  after each release. A tag is never moved.

## Reporting

- Report faithfully: say which checks were run (`make check`, `pytest`), which were not, and that
  the workflows and CI were not awaited.
- Mention failures that already exist on `main` instead of hiding them.
