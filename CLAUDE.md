# Instructions for coding agents

## Repository

This repository is a GitHub composite action (`action.yaml`) that reads the
project name, version, extra names and dependency specifiers from a
`pyproject.toml`. The logic lives in `scripts/extract_metadata.py`; the action
only wires its inputs and outputs. `test-data/` holds the `pyproject.toml`
fixtures used by the integration workflows.

## Environment

- Use a virtual environment in `.venv` (`python -m venv .venv`, then
  `.venv/bin/pip install -r requirements-test.txt`) and run `.venv/bin/python`,
  `.venv/bin/pytest`.
- Run the unit tests with `.venv/bin/pytest -q`. Some tests may fail on `main`;
  check with `git stash` before blaming your change.
- The script must keep working on Python < 3.11 (`tomli` fallback) and must
  only depend on `packaging` (and `tomli` on old Pythons).
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
- Keep the logic in `scripts/extract_metadata.py`, not inline in `action.yaml`.
  Invalid input must fail with a clear message on stderr and a non-zero exit.

## Python script

- Keep `from __future__ import annotations`, type hints and docstrings on every
  function, including private ones. Update the module docstring when the
  usage or JSON output changes.
- Raise `MetadataError` for user-facing errors; `main` turns it into an exit
  code and a stderr message.
- Dependency names are compared per PEP 503 (`canonicalize_name`).

## Tests

- Unit tests are in `tests/test_extract_metadata.py`; write one for every new
  or changed function, including private ones, and for every bug fixed (check
  that it fails without the fix).
- Build `pyproject.toml` contents with `tmp_path` and `write_pyproject`; no
  network, no sleeps.
- One behaviour per test, with `pytest.mark.parametrize` for the same check on
  several values. Every `pytest.raises` defines `match`.
- Cover typical inputs, edge cases (empty, duplicates, missing keys), and error
  conditions. Assert whole outputs against a literal (`assert result == {...}`).
- The integration workflows (`.github/workflows/test-local.yaml` with `uses:
  ./`, and `test-stable.yaml` with the last release) check only the wiring,
  using `scripts/test-helper.sh` and the fixtures in `test-data/`. Keep the two
  files identical except for the name and the `uses:` line, and add a job for
  every new input or output. A job that tests something added after the latest
  release goes only in `test-local.yaml`.

## Reporting

- Report faithfully: say which tests were run, which were not, and that the
  workflows and CI were not awaited.
- Mention failures that already exist on `main` instead of hiding them.
