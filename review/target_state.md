# Target state of `extract-pyproject-metadata-action`

Review date: 2026-11-10. Reviewed commit: `2f853c5` (`main`).

This document has three parts: the **properties** the action must have
(section 1), a **review of the current state** against them (section 2), and
the **target state** with a migration path (sections 3 to 10). Breaking changes
are accepted: the target is released as `v1`, and the current `v0.x` tags stay
as they are.

---

## 1. Properties of the action

These are the properties the design is judged by. They come from the current
`README.md`, `CLAUDE.md` and `action.yaml`, made explicit and ordered. When two
conflict, the lower number wins.

| #   | Property                | Meaning                                                                                                                                                                             |
| --- | ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| P1  | **Single purpose**      | Read a `pyproject.toml` and expose the values that drive a workflow: what to build, what to test (extras, groups, Python versions) and which dependency specifiers to install.      |
| P2  | **Read-only and safe**  | Never runs project code, never builds, never writes outside `$GITHUB_OUTPUT` / `$GITHUB_STEP_SUMMARY`. Values from the file can never become shell code, workflow commands or Markdown. |
| P3  | **Zero setup**          | Needs only a Python >= 3.11 on `PATH`. No network access, no install, no virtual environment, no change to the caller's Python. Same behaviour on Linux, macOS and Windows.         |
| P4  | **Fast**                | Adds well under a second to a job (interpreter start plus parsing a small file). Nothing is downloaded.                                                                             |
| P5  | **Deterministic**       | Same file, same inputs, same outputs. Order is the file order or a documented sort. No dependence on the runner except the interpreter.                                             |
| P6  | **Fails loudly, early** | Invalid input (a wrong input value, a malformed field that is read) fails with one message that names the field and the file (`::error file=...`). No Python traceback, ever.      |
| P7  | **Warns, never hides**  | Suspicious but usable input is a warning (annotation, job summary). `strict` turns every warning into a failure. No silent fallback.                                                |
| P8  | **Small surface**       | Few inputs, few outputs, each with one meaning and a safe default. Everything else is reachable through one structured `json` output.                                                |
| P9  | **Single source**       | Each fact (an input, an output, a default, a message) is defined once; docs, tests and the action file are checked against it or generated from it.                                 |
| P10 | **Easy to maintain**    | Small modules, one-way imports, strict typing, one task runner, one type checker, tests that mirror the code. A new maintainer reads the whole source in an hour.                    |
| P11 | **Honest docs**         | The README describes the current behaviour only (no history, no "it used to"), is short, and its tables are generated from `action.yaml`.                                           |

---

## 2. Review of the current state

Size today: `action.yaml` 245 lines, `README.md` 534 lines, `src/` 3,000
lines in 20 modules, `scripts/run.sh` 159 lines, `tests/` 7,700 lines, 14
workflows (1,700 lines, of which `ci-test-local.yaml` is 1,086), `.make/`
488 lines, 11 inputs, 27 outputs.

The code quality is good (strict typing, one-way layers, 100 % coverage,
careful escaping). The problems are about **scope and surface**, not
correctness: the action does much more than P1 asks for, and each extra
feature carries its own validation, warnings, docs, tests and workflow jobs.

### 2.1 Findings

| ID  | Finding                                                                                                                                                                                                                                                                                                                                                               | Property |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| F1  | **Install step on the hot path.** If `packaging` is missing (it was on the machine of this review) the action creates a venv and runs `pip` or `uv`: seconds, network access, a failure mode, and 159 lines of shell with `PYTHONSAFEPATH`, `trap`, `mktemp`, three installer modes. The Python work itself takes about 80 ms.                                          | P3, P4   |
| F2  | **Windows is unsupported** only because of the venv layout (`Scripts/` vs `bin/`) and the `python3` name. It is a side effect of F1, not a real constraint.                                                                                                                                                                                                            | P3       |
| F3  | **27 outputs, 11 inputs.** Ten outputs are plain pass-throughs that no matrix or release step needs (`readme`, `license`, `license-files`, `authors`, `urls`, `keywords`, `classifiers`, `scripts`, `build-backend`, `build-requires`). Each has a type check, docs, tests, a summary row and a workflow job.                                                           | P1, P8   |
| F4  | **Three outputs for one question** ("what does the file require for package X?"): `project-dependencies`, `dependency-specifiers`, `dependency-requirements`. They share one index but have different shapes, null/empty conventions and warnings.                                                                                                                    | P8       |
| F5  | **Three inputs for one concept.** `fail-on-missing`, `fail-on-dynamic-version` and `strict` all mean "turn a warning into a failure", with different scopes. `step-summary` is a 3-valued input with a 130-line table renderer, for information already in the log and in the annotations.                                                                            | P7, P8   |
| F6  | **Dynamic-version resolution** (`resolve-dynamic-version`, 253 lines) re-implements parts of setuptools and hatch (`file`, `attr`, `path`, `pattern`), including path-containment checks, a size limit and an acknowledged ReDoS risk. It covers a minority of dynamic projects (the common ones use `setuptools-scm` or `hatch-vcs`, which it cannot read).        | P1, P2   |
| F7  | **Marker-blind "first match wins"** for `dependency-specifiers`, plus a conflict-warning engine (same marker, different specifiers, across places). It is hard to explain (the README needs three sections) and the answer is arbitrary when markers differ.                                                                                                          | P5, P8   |
| F8  | **`normalized-name` / `normalized-version` are documented for file names, which is wrong.** Wheel and sdist file names use `_` in the name (`my_package-1.0-py3-none-any.whl`), not the PEP 503 form with `-`. A user following the README builds a wrong path.                                                                                                       | P11      |
| F9  | **The core takes `argparse.Namespace`** (`build_report(args, options)`), and `Options | None` is parsed twice. The CLI leaks into the logic; the logic cannot be called with plain values.                                                                                                                                                                      | P10      |
| F10 | **Duplicated documentation of the same facts** in `action.yaml` (descriptions), `README.md` (tables, 534 lines), the `cli.py` docstring (100 lines), `types.py`, `format_outputs` and `output/summary.py`. `test_contract.py` keeps them aligned by checking, which is a symptom of F10 rather than a cure.                                                             | P9       |
| F11 | **History inside the docs.** The failure list says "It used to end with a Python traceback", "It used to be ignored silently", "(it used to fail with `Invalid statement`)". The README also says `@v0.1` and "needs a release later than `v0.2`". That is release-note content, and it confuses readers.                                                              | P11      |
| F12 | **Integration workflows break the action's own rule.** `ci-test-local.yaml` (1,086 lines, 95 `assert_equal`) interpolates `${{ steps.x.outputs.y }}` directly into `run:` in 97 places, although `CLAUDE.md` and the README say to pass values through `env:`. It is also duplicated by hand in `nightly-test-stable.yaml` ("keep identical except the `uses:` line"). | P2, P9   |
| F13 | **Tooling overlap.** Two task runners (`Makefile` + `.make/` and `invoke` + `tasks.py`, the latter on a pre-release `invoke-tasklib>=0.1.0a0`), two type checkers (`ty` and `pyright`), `import-linter` and `hypothesis` installed only on Python >= 3.14, `docformatter` (which produces the odd split docstring summaries), `xdoctest`.                              | P10      |
| F14 | **The repo is built as a Python distribution for no reason.** `pyproject.toml` has a `hatchling` build system, `hatch-requirements-txt` and a wheel target, but the project is never published (`version = "0.0.0"`). The only purpose is to read `scripts/requirements.txt`.                                                                                        | P10      |
| F15 | **Bots that the platform already provides.** `bot-cancel-stale-queued-runs.yaml` (59 lines) does what `concurrency: { cancel-in-progress: true }` does, and no CI workflow uses `concurrency`. `ci.yaml` fans out into `ci-lint`, `ci-test`, `ci-type-check`, `ci-verify-workflows`, `lib-get-test-matrix`, `ci-test-local` through reusable workflows.              | P10      |
| F16 | **Size-limit machinery** (`oversized_outputs`, 900 KB warning) exists because `json` repeats every other output, so a big `classifiers` list doubles. With F3 fixed the problem disappears.                                                                                                                                                                           | P8       |
| F17 | **`python-candidates` default is a hard-coded list** (`3.11` to `3.15`) in code, `action.yaml` and the README (three copies). It goes stale every October.                                                                                                                                                                                                            | P9       |

### 2.2 What is good and must be kept

- Inputs go through `env:`; outputs are written with a random delimiter; annotations and summaries are escaped (P2).
- `MetadataError` plus a single `main` that turns it into an exit code and an annotation (P6).
- PEP 503 / PEP 685 / PEP 440 handling through `packaging`, not regexes.
- Layered package, strict pyright, 100 % coverage gate, property tests on the parsers.
- Unknown input fails; booleans are exactly `true` / `false`.

---

## 3. Target interface

### 3.1 Inputs (5, down from 11)

| Input               | Default                    | Meaning                                                                                                                                                                  |
| ------------------- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `pyproject-path`    | `pyproject.toml`           | File to read.                                                                                                                                                            |
| `extra-values`      | `[]`                       | JSON array of strings put before the extras (for example `[""]` for a "no extra" job).                                                                                   |
| `dependencies`      | `[]`                       | JSON array of package names to look up, optionally scoped (`numpy`, `numpy@project`, `numpy@extra:fast`, `pytest@group:dev`). Same syntax as today.                     |
| `python-candidates` | maintained list (see 3.4)  | JSON array of `major.minor` strings to filter with `requires-python`.                                                                                                    |
| `strict`            | `false`                    | `true` fails the step when there is any warning. This is the only switch for "fail instead of warn".                                                                     |

**Removed inputs and what replaces them**

| Removed                   | Replacement                                                                                                                                                                                                         |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `fail-on-missing`         | A requested dependency that is not found is a **warning** (`dependency X not found`) and `null` in the output. `strict: true` makes it a failure.                                                                   |
| `fail-on-dynamic-version` | A dynamic version is a **warning**. `strict: true` makes it a failure. A release job uses `strict: true`.                                                                                                           |
| `resolve-dynamic-version` | Removed with the feature (see 3.5).                                                                                                                                                                                 |
| `step-summary`            | The job summary is always written when there is a warning or an error (today's `auto`), and only then. It is a short list, not a table of every output. No input.                                                   |
| `installer`               | Removed: nothing is installed (see 4.1).                                                                                                                                                                            |
| `python-executable`       | Removed. The action uses `python3` or, if absent, `python` from `PATH`; use `actions/setup-python` to choose a version, as every other action does.                                                                |

Booleans stay strict: exactly `true` or `false` (case and surrounding spaces
ignored), anything else fails.

### 3.2 Outputs (13 including `json`, down from 27)

Scalars are plain strings. Arrays and objects are compact JSON strings, ready
for `fromJSON`. All keys are listed in `action.yaml` and nowhere else by hand.

| Output                  | Value                                                                                                              |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `name`                  | `[project].name`, as written.                                                                                      |
| `normalized-name`       | PEP 503 form (`my-package`): for index URLs and `pip install`.                                                     |
| `file-name`             | Name as used in wheel and sdist file names (`my_package`). **New**, fixes F8.                                      |
| `version`               | `[project].version`, as written (empty when dynamic, with a warning).                                              |
| `normalized-version`    | PEP 440 canonical form: for file names and tags.                                                                   |
| `requires-python`       | `[project].requires-python`, as written (empty if absent).                                                         |
| `python-versions`       | JSON array: the candidates allowed by `requires-python`, in candidate order.                                       |
| `python-min`            | Lowest of `python-versions` (numeric order), empty if none.                                                        |
| `python-max`            | Highest of `python-versions`, empty if none.                                                                       |
| `extras`                | JSON array: `extra-values`, then the extras sorted by normalized name, no duplicates (PEP 685).                    |
| `groups`                | JSON array: dependency groups sorted by normalized name.                                                           |
| `dependency-specifiers` | JSON object: each requested entry to its specifier (`""` if none, `null` if not found).                            |
| `json`                  | The whole result (all the above plus `dependency_requirements`, `warnings`, `schema_version`), as real JSON values. |

`json` is the structured escape hatch; the 12 others are the individual outputs.

**Removed outputs**

| Removed                                                                                                                                  | Why / where to get it                                                                                                                            |
| ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `description`, `readme`, `license`, `license-files`, `authors`, `urls`, `keywords`, `classifiers`, `scripts`, `build-backend`, `build-requires` | Pass-through of fields that never drive a matrix or a release (F3). A workflow that needs one reads it with `tomllib` in one line. Not read, so not validated and no SPDX check. |
| `project-dependencies`                                                                                                                   | `dependencies: '["numpy"]'` answers the same question for the packages the workflow cares about. Listing all the project dependencies is the job of `pip`.                      |
| `python-matrix`                                                                                                                          | `{"python-version": python-versions}` is one expression: `matrix: python-version: ${{ fromJSON(...python-versions) }}`.                                                         |
| `dependency-requirements` (as its own output)                                                                                            | Kept **inside `json`** (`fromJSON(...json).dependency_requirements`) for the marker use case; it is no longer a top-level output (F4).                                           |

Net effect: the questions the action answers are exactly P1's: *what is it
(name/version), what do I test (extras, groups, Python versions), what do I
install (specifiers)*.

### 3.3 Dependency lookup (simplified semantics)

- Search order is unchanged and documented in one sentence: `[project].dependencies`, each extra (file order), each group (file order, `include-group` expanded).
- An unscoped name returns the **first** requirement found. Markers are never evaluated (unchanged).
- A scoped name (`@project`, `@extra:<n>`, `@group:<n>`) looks in that place only. Unchanged syntax, since it is the practical answer to "first match is arbitrary".
- **Removed:** the cross-place "different specifiers" conflict warning (F7). If a package is declared in two places with different specifiers, the unscoped answer is the first one, the scoped answers are explicit, and `dependency_requirements` in `json` lists all of them with their source. Warning on every legitimate difference (a runtime range plus a dev pin) is noise.
- **Added:** each item of `dependency_requirements` gets a `source` (`project`, `extra:<n>`, `group:<n>`), so a workflow can tell the entries apart without guessing from the order.
- **Kept:** `Ignoring invalid requirement` (warning), `include-group` cycle and unknown group (warnings), the nesting and expansion limits (errors), dynamic `dependencies` / `optional-dependencies` (warning).
- A missing package is a warning (see 3.1), so `strict` is the single policy switch.

### 3.4 Python versions

- Algorithm unchanged (a minor is allowed if some release of it satisfies the specifier; numeric ordering for min and max).
- The default candidate list is defined **once**, in `python_versions.py`. `action.yaml` documents "the supported CPython versions, see the README" without repeating the list, and the README prints it from the code (generated block, 5.4). Updating it is a release-checklist item every October.
- `python-versions` empty (invalid or unsatisfiable `requires-python`) stays a warning.

### 3.5 Dynamic version

- `resolve-dynamic-version` and `dynamic_version.py` are **deleted** (F6).
- Behaviour: `version` and `normalized-version` are empty, with the warning `[project].version is dynamic`. `strict: true` fails.
- Justification: the feature re-implements two build backends, needs a path-safety layer and a ReDoS caveat, and does not cover the common cases. A workflow with a dynamic version should ask the backend (`python -m build`, `hatch version`, `uvx hatch version`, `python -m setuptools_scm`).
- Fallback if this turns out to hurt users: re-add **only** `tool.setuptools.dynamic.version.file` and `tool.hatch.version.path` with the default pattern, behind no input (always on, a warning if not found). That is under 60 lines. Do not re-add `attr` (needs `ast` and module search) or user regular expressions.

### 3.6 Error and warning policy (P6, P7)

- **Validate only what is read.** A malformed `authors` is not the action's concern any more. The remaining checks are: `[project]` is a table, `name` valid (PEP 508 name), `version` valid (PEP 440) unless dynamic, `requires-python` is a string, `dynamic` is an array of strings, the extras / groups / dependency tables have the right shape.
- Every message has the form `<field>: <problem>` and is emitted as `::error file=<path>::...` (or a warning annotation). The README lists the **rule**, not each message (F11).
- `strict` failure lists every warning in one error.
- Warnings in the target: field both static and listed in `dynamic`, dynamic version, `requires-python` invalid or unsatisfiable by the candidates, invalid requirement ignored, `include-group` cycle, unknown included group, dynamic dependencies, requested dependency not found. Eight, down from twelve.

### 3.7 Versioning

- Breaking release `v1.0.0` with a moving `v1` tag, created by a release workflow (see 8). `v0.1` / `v0.2` stay available.
- `schema_version` of the `json` output becomes `2` (keys removed, `source` added). From then on it changes only on a rename, a removal or a type change.

---

## 4. Target architecture

### 4.1 No install step: vendor `packaging`

The only third-party dependency is `packaging` (requirement parsing, specifiers, versions, name canonicalization). Everything else is standard library (`tomllib`, `json`, `re`).

**Decision: vendor a pinned copy of `packaging` inside the package.**

```
src/extract_pyproject_metadata/_vendor/packaging/   (pure Python, Apache-2.0 OR BSD-2-Clause, licences included)
```

Consequences:

- `scripts/run.sh` shrinks from 159 lines to about 15: find `python3` or `python`, check the version, `exec python -I -B extract_metadata.py "$@"`. `-I` removes the current directory, the user site and `PYTHON*` variables from the path, which replaces `PYTHONSAFEPATH` and the shadowing comments. The launcher inserts `src/` into `sys.path` itself (as today).
- No network, no venv, no `pip`, no `uv`, no `installer` input, no `trap`, no temp directory, no `packaging>=23,<27` version window to test (P3, P4, P5): the behaviour no longer depends on whichever `packaging` the runner has. Today the output can differ between `packaging` 23 and 26 (for example the SPDX check only runs from 24.2).
- Windows works: nothing depends on `bin/` vs `Scripts/` (F2). The CI matrix adds `windows-latest`.
- `scripts/requirements.txt`, `hatch-requirements-txt`, the build system and the wheel target are deleted (F14).
- Cost: the vendored tree (about 300 KB) is excluded from ruff, pyright and coverage, and must be updated by hand. Provide `make vendor-packaging VERSION=x.y` (download the wheel, unpack the `packaging/` directory, update `_vendor/README.md` with the version and the hash) and a monthly scheduled workflow that opens an issue when a newer `packaging` exists. `packaging` has a small API surface and a good security record; this is a low-frequency task.

**Fallback (if vendoring is rejected):** keep a venv install but drop `uv`/`auto`/`installer` and `python-executable`, keep the "use the installed `packaging` if >= 23" check, and accept network on the cold path. This keeps F1 and F2 but removes most of the shell. It is the second-best option.

### 4.2 Package layout

Fewer, flatter modules. Imports still go one way, from the bottom of this list to the top; a module never imports from one above it. The `dependencies/` and `output/` sub-packages disappear because each concern fits in one module of a few hundred lines.

```
src/extract_pyproject_metadata/
  __init__.py          docstring (map of the modules) + MetadataError
  __main__.py          python -m extract_pyproject_metadata
  errors.py            MetadataError
  types.py             Report (TypedDict), Inputs (frozen dataclass)
  checks.py            type checks of values read from the file
  inputs.py            parse the action inputs (JSON arrays, booleans) -> Inputs
  pyproject.py         load_pyproject + read name, version, requires-python, extras, groups, dynamic
  requirements.py      parse, index and look up requirements (scopes, include-group, limits)
  python_versions.py   candidates, compatible versions, min, max
  report.py            build_report(inputs: Inputs) -> Report   (wires the above, applies strict)
  output.py            GITHUB_OUTPUT writer, annotations, escaping, log line, job summary
  cli.py               argparse, main
  _vendor/packaging/
```

About 12 modules and 1,000 to 1,200 lines (from 20 modules and 3,000 lines). Deleted: `license.py`, `fields.py` (the useful 40 lines move to `pyproject.py`), `dynamic_version.py`, `dependencies/groups.py` + `lookup.py` merged into `requirements.py`, `output/summary.py` (replaced by a list in `output.py`).

Rules that change:

- **The core never sees `argparse`.** `inputs.parse_inputs(raw: Mapping[str, str]) -> Inputs` is the single place that validates input strings; `build_report(inputs)` takes the dataclass (F9). `cli.py` maps the command line to `Inputs`. The action can pass the inputs as `--option value` flags (clearer than the current positional JSON strings), and tests call `build_report(Inputs(...))` with plain values.
- **`output.py` depends only on `types` and `errors`** (kept; enforced by `pyright` plus a single test that parses imports, see 7.2).
- A public name is listed in `__all__`; a verb prefix for functions; module docstring and `from __future__ import annotations` everywhere. Unchanged.
- The `cli.py` docstring is reduced to the usage (10 to 15 lines); the full contract lives in `action.yaml` and the README (P9).
- `json` is `json.dumps(report)` plus nothing else. Individual outputs are derived from `Report` by one table in `output.py` whose keys are checked against `action.yaml` by a test.

### 4.3 Execution flow

```
action.yaml  --env-->  scripts/run.sh  --exec-->  python -I -B scripts/extract_metadata.py
                                                   cli.main(argv)
                                                     parse_inputs -> Inputs
                                                     build_report(Inputs) -> Report      (pure, no I/O except reading the file)
                                                     output.write(Report)                (GITHUB_OUTPUT, annotations, log line, summary)
```

Pure core, I/O at the edge. `build_report` is the only function a library user or a test needs.

### 4.4 `action.yaml`

- One step, `shell: bash`, five `env:` entries, one command. No logic. Unchanged in spirit; shorter.
- Windows runs the same step (`shell: bash` is Git Bash there).
- Descriptions are one sentence each; the detail is in the README, which is generated from this file (5.4).

---

## 5. Documentation target (P9, P11)

1. **README of about 150 lines**: what it is, a 10-line usage example, three recipes (extras matrix, Python matrix, release with `strict`), the generated inputs / outputs tables, the dependency scopes in one table, the warnings list, and a short "Development" section pointing at `CONTRIBUTING`-style commands.
2. **No history.** "It used to ..." goes to GitHub release notes. The failure-mode list becomes: *"Invalid input fails the step with `<field>: <problem>` and an annotation on the file. The inputs are validated before the file is read."* plus the few cases that need a sentence (Python < 3.11, missing file, invalid TOML, strict).
3. **Examples are runnable.** Every YAML and TOML block in the README is a fixture under `test-data/` or `tests/`, and a test checks that the README block equals the fixture (replaces most of `test_contract.py`).
4. **Generated tables.** `scripts/generate_docs.py` (a dev-only script that reads `action.yaml` with `PyYAML`) rewrites the blocks between `<!-- inputs:start -->` / `<!-- inputs:end -->` and the same for outputs and the default candidates. `make docs` writes, CI fails on a diff. The action itself still has no runtime dependency.
5. Fix F8: the README says `normalized-name` is for index URLs and `file-name` is for wheel and sdist file names.
6. `CLAUDE.md` is updated with the new architecture, the vendored dependency and the single task runner. It keeps the same sections and shrinks accordingly.

---

## 6. Repository and tooling target (P10)

| Area                     | Today                                                                                       | Target                                                                                                                                                                                              |
| ------------------------ | ------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Task runner              | `Makefile` + `.make/` (shared, synced by a bot) **and** `invoke` + `tasks.py` + `invoke.yaml` | **One: the `Makefile`.** It already covers the non-Python files and is shared with other repos. Add `make check` (ruff, format check, pyright, tests), `make test`, `make fix`, `make docs`, `make vendor-packaging`. Drop `invoke`, `invoke-tasklib` (pre-release) and `tasks.py`. *(Owner decision: if the `coola` convention of `invoke` must stay, keep invoke and drop the Python part of `.make/` instead. Either way, one.)* |
| Type checker             | `pyright` strict **and** `ty`                                                               | **`pyright` strict** on `src` and `scripts` (it is the one `CLAUDE.md` requires). Drop `ty`.                                                                                                        |
| Layer checks             | `import-linter` (Python >= 3.14 only), 2 contracts                                          | Drop. With 12 flat modules a 20-line test (parse the imports of each module with `ast`, assert the rank order from a dict) enforces the same rule on every Python version, with no dependency.     |
| Docstring formatting     | `docformatter` (re-wraps summaries oddly)                                                   | Drop; `ruff format` plus the `D` rules are enough.                                                                                                                                                  |
| Doctests                 | `xdoctest` in the dev group                                                                 | Drop unless doctests exist; examples live in tests.                                                                                                                                                 |
| Property tests           | `hypothesis`, Python >= 3.14 only                                                           | Keep, but run on **all** supported Pythons (find out why it is gated; if it is a wheel problem on free-threaded builds, gate by `sys._is_gil_enabled`, not by version).                            |
| Build system             | `hatchling`, `hatch-requirements-txt`, wheel target                                         | None. `pyproject.toml` holds tool configuration and the `dev` group. Keep a minimal `[project]` (name, `requires-python`, `dependencies = []`) with `[tool.uv] package = false` so `uv sync --group dev` works. |
| Runtime requirements     | `scripts/requirements.txt` read by hatch                                                    | None (vendored).                                                                                                                                                                                    |
| Dev dependencies         | 16 entries                                                                                  | `pytest`, `pytest-cov`, `pytest-timeout`, `hypothesis`, `ruff`, `pyright`, `pre-commit`, `codespell`, `pyyaml` (docs generation). 9 entries.                                                         |
| Pre-commit               | ruff, docformatter, shfmt, shellcheck, codespell, ty, import-linter                         | ruff (lint + format), shfmt, shellcheck, codespell, prettier / yamllint for YAML and Markdown (already in `.make`). CI runs `pre-commit run -a` so local and CI use the same definition.           |
| Fixtures                 | 17 files in `test-data/`                                                                    | One directory per case with `pyproject.toml` **and** `expected.json` (the expected `json` output). Used by unit, integration and workflow tests (see 7.3).                                          |

---

## 7. Test strategy target

### 7.1 Principles

- Keep the existing rules (mirror the package, one behaviour per test, `pytest.raises(match=...)`, whole-output asserts, no network, no sleeps, 100 % coverage of `src` excluding `_vendor`).
- **Delete tests with the code they cover** (about 40 % of the 7,700 lines go with the removed outputs, inputs and dynamic-version feature). Do not keep tests for removed behaviour.
- Add a test for every bug fixed and **check that it fails without the fix**, as `CLAUDE.md` says.

### 7.2 Layout

```
tests/unit/            one module per module of src (12)
tests/integration/     test_cli_process.py (new process, stdout / stderr / exit codes),
                       test_run_sh.py (python3/python lookup, version check, -I isolation),
                       test_action_contract.py (action.yaml <-> output table <-> README blocks <-> fixtures),
                       test_golden.py (every test-data/<case> produces its expected.json)
tests/properties/      parsers: normalization, ordering, escaping round trips
tests/test_layers.py   rank-order check of the imports (replaces import-linter)
```

### 7.3 Golden fixtures

- Each `test-data/<case>/` has `pyproject.toml`, optional `inputs.json` (the action inputs for that case) and `expected.json` (the `json` output).
- The golden test runs `main` for every case and compares the whole object. Adding a case is adding a directory; no new test code, no new workflow job.
- The same directories drive the workflow job (7.4), so the unit tests and the real action are checked against the same expectations.

### 7.4 Workflow-level test (wiring only)

- One job per OS (`ubuntu-latest`, `macos-latest`, `windows-latest`) with the lowest and the highest supported Python.
- One matrix over the case directories; the step `uses: ./` with the case's `inputs.json` mapped by a small `fromJSON` expression, then **one** shell step:

```yaml
- name: Compare the json output with the golden file
  run: python scripts/compare_json.py "$EXPECTED" "$ACTUAL"
  env:
    EXPECTED: test-data/${{ matrix.case }}/expected.json
    ACTUAL: ${{ steps.action.outputs.json }}
```

  Values go through `env:` (fixes F12), there are no hand-written `assert_equal` per output, and the file shrinks from 1,086 lines to about 80.
- Wiring checks that the golden file cannot see stay as separate small steps: a failure case (`continue-on-error` + check of the outcome), `strict`, no `__pycache__` left in the workspace, no directory left in `$RUNNER_TEMP`.
- `nightly-test-stable.yaml` is **generated** from `ci-test-local.yaml` by `make workflows` (change the `uses:` line and the name) and checked with `git diff --exit-code` in CI. `uses:` cannot be an expression, so a generated copy is the least bad option.

---

## 8. CI and release target

| Workflow            | Content                                                                                                                                                                                                                       |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ci.yaml`           | One file with `concurrency: { group: ${{ github.workflow }}-${{ github.ref }}, cancel-in-progress: true }`. Jobs: `lint` (`pre-commit run -a`, `make docs` diff check, `make workflows` diff check), `types` (`pyright`), `unit` (matrix Python 3.11 to latest, Ubuntu; plus macOS and Windows on the lowest and highest), `action` (the golden workflow test, 7.4). |
| `nightly.yaml`      | The generated stable-release copy of the action test, plus the check that a newer `packaging` has not been released (opens an issue).                                                                                         |
| `release.yaml`      | On a `v*.*.*` tag: run the checks, create the GitHub release with notes, move the `v<major>` tag.                                                                                                                             |
| `dependabot.yml`    | `github-actions` and `pip` (dev group), weekly, grouped.                                                                                                                                                                      |

Removed: `bot-cancel-stale-queued-runs` (replaced by `concurrency`), `lib-get-test-matrix`, `ci-lint`, `ci-test`, `ci-type-check`, `ci-verify-workflows` as separate reusable workflows (folded into jobs of `ci.yaml`; a workflow file per job adds indirection without reuse). To check before deleting: `bot-pin-action`, `bot-format-files` and `bot-sync-shared-makefile`. Keep the one that keeps the shared `.make/` in sync (it serves other repositories), and drop the others if `pre-commit.ci` or Dependabot already does their job. Third-party actions stay pinned to a commit SHA with the ratchet comment.

Release checklist (in `CONTRIBUTING`-style section of the README): update the default `python-candidates` (October), check `packaging` for a newer release, run `make check`, tag.

---

## 9. What is deliberately not in the target

- Evaluating environment markers (needs the target Python and platform; a workflow can pick from `dependency_requirements`).
- Running a build backend or project code, in any form.
- Reading other tools' tables (`tool.*`), `gui-scripts`, `entry-points`.
- A cache, a daemon, or any state between steps.
- Validating the whole of PEP 621. Fields that are not read are not checked.
- Publishing the package to PyPI.

---

## 10. Migration plan

One branch and one PR per step, in this order (each leaves `main` green; breaking steps are marked **B**).

| Step | Branch                                   | Change                                                                                                                                                                              | Breaking |
| ---- | ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| 1    | `refactor/inputs-dataclass`              | `Inputs` dataclass, `parse_inputs`, `build_report(inputs)`; the CLI maps to it. Core no longer imports `argparse`.                                                                    |          |
| 2    | `chore/single-tooling`                   | Drop `ty`, `import-linter` (add the layer test), `docformatter`, `xdoctest`; choose one task runner; drop the build system. Update `CLAUDE.md` and the pre-commit file.               |          |
| 3    | `ci/concurrency-and-golden-tests`        | `concurrency`, fold the reusable workflows into `ci.yaml`, add `expected.json` fixtures and the golden test, rewrite the action test with `env:`, generate the nightly copy.          |          |
| 4    | `feat/vendor-packaging`                  | Vendor `packaging`, shrink `run.sh`, delete `requirements.txt`, `installer`, `python-executable`; add Windows to the matrix.                                                          | **B** (inputs removed) |
| 5    | `feat/single-strict-switch`              | Remove `fail-on-missing`, `fail-on-dynamic-version`, `step-summary`; missing dependency becomes a warning; summary is warnings and errors only.                                       | **B**    |
| 6    | `feat/remove-passthrough-outputs`        | Remove the 11 pass-through outputs, `project-dependencies`, `python-matrix`, `license.py`, `fields.py` leftovers, the size-limit warning; add `file-name`.                              | **B**    |
| 7    | `feat/simplify-dependency-lookup`        | Remove the conflict warning, move `dependency-requirements` into `json` with `source`, merge the `dependencies/` modules.                                                            | **B**    |
| 8    | `feat/remove-dynamic-version-resolution` | Delete `dynamic_version.py`, the input and its tests and fixtures.                                                                                                                    | **B**    |
| 9    | `docs/generated-readme`                  | New README (about 150 lines), `scripts/generate_docs.py`, `make docs`, CI diff check, `schema_version` 2.                                                                             |          |
| 10   | `chore/release-v1`                       | `release.yaml`, release notes listing every breaking change with its replacement (tables 3.1 and 3.2 are the notes), tag `v1.0.0` and `v1`.                                          | **B**    |

Steps 4 to 8 can be squashed into a single `v1` branch if no intermediate release is wanted. Steps 1 to 3 are worth doing even if the rest is rejected: they are pure maintainability gains.

---

## 11. Expected result

| Measure                         | Today                                    | Target                                              |
| ------------------------------- | ---------------------------------------- | --------------------------------------------------- |
| Inputs / outputs                | 11 / 27                                  | 5 / 13 (including `json`)                           |
| Warnings                        | 12                                       | 8                                                   |
| Source modules / lines          | 20 / about 3,000                         | about 12 / about 1,100 (plus the vendored tree)     |
| `run.sh`                        | 159 lines, venv, pip or uv               | about 15 lines, nothing installed                   |
| Cold path of a run              | interpreter plus (when needed) venv and a network install | interpreter plus parsing, about 80 ms, offline |
| Supported runners               | Linux, macOS                             | Linux, macOS, Windows                               |
| Tests                           | 7,700 lines                              | about 3,500 lines, golden files for the wiring      |
| Workflows                       | 14 files, 1,730 lines                    | 4 files, about 350 lines                            |
| README                          | 534 lines, hand-written tables, history  | about 150 lines, generated tables, no history       |
| Dev tools                       | ruff, pyright, ty, import-linter, docformatter, xdoctest, invoke, make | ruff, pyright, make                      |

## 12. Decisions that belong to the owner

1. **Vendor `packaging`** (recommended) or keep the venv install (fallback in 4.1).
2. **Drop the pass-through outputs and dynamic-version resolution** (recommended), or keep either as `json`-only fields. The `json`-only option keeps the code but removes the individual outputs; it is the middle path if there are known users.
3. **`Makefile` or `invoke` as the single task runner** (recommended: `Makefile`).
4. **One `strict` switch** instead of three fail flags (recommended). If a release job must fail on a dynamic version but tolerate other warnings, add back `fail-on-dynamic-version` only.
