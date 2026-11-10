# Target state of `extract-pyproject-metadata-action`

Review date: 2026-11-10. Reviewed commit: `e66a1f2` (`main`, release notes of `v0.3.0`).

This document **replaces** the review written at commit `2f853c5` (still in the git
history). That review is implemented: the install step, the pass-through outputs, the
dynamic-version resolution, the extra inputs and the conflict warning are gone, and the
README, the golden fixtures and the release workflow exist. This review judges the result
and proposes the next, smaller, round.

Structure: the **properties** (1), the **measured state** and the **findings** (2), the
**target behaviour** (3), the **target architecture** (4), **tests** (5), **CI, release and
tooling** (6), what is **deliberately left out** (7), the **migration plan** (8), the
**expected result** (9) and the **decisions** to take (10).

Breaking changes are accepted. The release that carries them is `v1.0.0` (see 6.3).

---

## 1. Properties of the action

The design is judged by these properties. They come from `README.md`, `CLAUDE.md` and
`action.yaml`, made explicit, ordered and checkable. When two conflict, the lower number
wins. "How to check" is what a maintainer or a test does to verify the property.

| #   | Property                | Meaning                                                                                                                                                                       | How to check                                                                                                  |
| --- | ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| P1  | **Single purpose**      | Read a `pyproject.toml` and expose the values that drive a workflow: what to build (name, version), what to test (extras, groups, Python versions), what to install (specifiers). | Every output answers one of these three questions; a new output must say which.                               |
| P2  | **Read-only and safe**  | Never runs project code or a build backend. Writes only `$GITHUB_OUTPUT`. A value from the file can never become shell code, a workflow command or Markdown.                   | Injection tests (`test_output_injection.py`); inputs go through `env:`; the workflows follow the same rule.   |
| P3  | **Zero setup**          | Needs only Python >= 3.11 on `PATH`. No network, no install, no change to the caller's Python. Same behaviour on Linux, macOS and Windows.                                    | `run.sh` has no install branch; the CI matrix has the three systems.                                          |
| P4  | **Fast**                | Adds well under a second to a job.                                                                                                                                            | Measured: about 100 ms per run (23 ms is the bare interpreter). Keep it under 250 ms on a runner.             |
| P5  | **Deterministic**       | Same file and inputs give the same outputs. Order is the file order or a documented sort. Nothing depends on the runner but the interpreter.                                   | Golden files; property tests.                                                                                 |
| P6  | **Reads only what it outputs** | A field that no output needs is neither read nor validated. A lookup that is not requested does not read the requirement tables.                                       | A `pyproject.toml` with a broken `description`, or a broken `dependencies` when `dependencies: []`, still works. |
| P7  | **Fails loudly, early** | Invalid input fails with **one** message `<field>: <problem>` and an `::error file=...` annotation. Inputs are validated before the file is read. Never a traceback.          | One error format, tested once per field; the process tests check exit code and stderr.                        |
| P8  | **Warns, never hides**  | Suspicious but usable input is a warning with a stable **code**. `strict` turns every warning into a failure. No silent fallback.                                             | Every warning has a code, a row in the README and a golden case.                                              |
| P9  | **Small surface**       | Few inputs and outputs, each with one meaning and a safe default. Everything else is in the structured `json` output.                                                         | 5 inputs, 13 outputs today; the target does not grow them.                                                    |
| P10 | **Single source**       | Each fact (an input, an output, a default, a warning) is defined once; the docs and the tests are generated from it or checked against it.                                    | `make docs`, `make workflows` and the contract tests fail on a diff.                                          |
| P11 | **Easy to maintain**    | Small modules, one-way imports, strict typing, one task runner. A new maintainer reads all the source in an hour. Test code is smaller than 1.5 times the source.             | Source lines (without the vendored tree) below 1,500; layer test; `make check`.                               |
| P12 | **Honest docs**         | The README describes the current behaviour only, with no history, and every example in it is run by a test.                                                                   | `test_readme.py`; release notes hold the history.                                                             |

P6 and the "one warning code" part of P8 are **new** compared with the previous review: the
code does not fully respect P6 today (finding G1), and P8 cannot be checked without codes
(finding G7).

---

## 2. Review of the current state

### 2.1 Measured state

| Measure                                  | Value                                                                                                          |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Source, without `_vendor/`               | 2,210 lines in 17 modules (`requirements.py` 408, `metadata.py` 225, `cli.py` 220, `github.py` 179)           |
| Vendored `packaging`                     | 11,700 lines shipped; 13 modules and 6,800 lines are loaded at run time                                        |
| Tests                                    | 6,440 lines, 2.9 times the source (`test_cli.py` 1,217, `test_requirements.py` 1,020, `test_metadata.py` 714)  |
| Workflows                                | 11 files, 942 lines (`ci-test-local.yaml` 309, plus its generated copy `nightly-test-stable.yaml` 95)         |
| Interface                                | 5 inputs, 13 outputs, 10 warnings, `schema_version` 2                                                           |
| README                                   | 266 lines, tables generated, no history                                                                        |
| Run time (macOS, Python 3.14, `-I -B`)   | 100 ms per run; 68 ms with bytecode; 23 ms for `python -c pass`. 30 ms of it is the imports of `cli`.         |
| Functions that take `pyproject_path`     | 25 signatures in 10 modules, only to build messages                                                            |

The previous round worked: the interface is small, the layers hold, the checks are strict.
What is left is **internal duplication** and **a few contract gaps**, not scope.

### 2.2 Findings

| ID  | Finding                                                                                                                                                                                                                                                                                                                                                                                                                                        | Property   |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| G1  | **The requirement tables are read and validated on every run, even when `dependencies` is `[]`.** Verified: `[project] dependencies = [1]` with `dependencies: '[]'` fails with `[project].dependencies must contain only strings`. A broken `include-group` also raises the depth and expansion limits. `report.py` calls `index_dependencies` unconditionally. This contradicts the README ("only what the action outputs is read") and wastes time. | P6, P4     |
| G2  | **Three modules each read `[project]`, `dynamic` and `optional-dependencies` from the raw dict.** `metadata.py`, `pyproject.py` and `requirements.py` all call `get_table` on the same keys, and `_dynamic_dependency_fields` re-checks the types of `dynamic` defensively because the validation lives elsewhere. `flatten_group` is full of `cast`. The raw `dict[str, Any]` travels through the whole core.                                  | P11        |
| G3  | **`pyproject_path` is threaded through 25 signatures** only to put the file name in the text of errors and warnings, although the annotation (`::error file=...`) already carries the file. Every function has a default `"pyproject.toml"` that hides a forgotten argument.                                                                                                                                                                  | P11, P7    |
| G4  | **The dependency index is two-pass and string-keyed.** `index_dependencies` builds one index for all places and one per place under keys such as `"numpy@extra:x"`; `_lookup_key` re-normalises the entry to rebuild the key; entries are bare tuples `(specifier, marker, scope)`; a `functools.cache` exists because each string is parsed twice. The same information is a flat list of records with a `source`.                              | P11        |
| G5  | **The command line is an argparse layer for a program with one caller.** The action already passes its inputs as environment variables, then `run.sh` turns them into one flag, two options and three positional JSON strings, and `cli.py` (220 lines, with an `_ArgumentParser` subclass for annotated usage errors, and 1,217 lines of tests) turns them back into `Inputs`. `--github-output` is a mode switch that could be `$GITHUB_OUTPUT`. | P11, P9    |
| G6  | **The Markdown job summary repeats the annotations.** GitHub already lists every `::warning` and `::error` on the run page. `output/summary.py` (102 lines, a numeric-character-reference escaper, 90 lines of tests, the `GITHUB_STEP_SUMMARY` handling in `main`) produces a second copy of the same list and a second place where escaping can go wrong.                                                                                  | P11, P2    |
| G7  | **Warnings are free text.** The README table is keyed by "Message contains" fragments (`' not found`), the tests match substrings, and a workflow that reads `fromJSON(...json).warnings` can only do the same. Two rows (`dynamic dependencies` and `dynamic optional-dependencies`) are one case. A reworded message silently breaks the docs.                                                                                               | P8, P10    |
| G8  | **The error format is not uniform, and the README promises one.** The README says `<file>: <field> <problem>`. The code produces `pyproject.toml not found at: x`, `x is not valid TOML`, `x is missing required key [project].name`, `x: [project].version is not a valid ...`, and input errors with no file at all (`strict must be 'true' or 'false'`). The file name is also in the text and in the annotation.                              | P7, P12    |
| G9  | **`v0.x` with a moving `v0.3` tag.** Every minor release makes the callers edit `@v0.3` to `@v0.4`, and `STABLE_REF` in `generate_workflows.py` is edited by hand after every release. The interface has been stable and documented, which is what `v1` means.                                                                                                                                                                              | P12, P11   |
| G10 | **Tests are 2.9 times the source.** Most of the weight is one test per message and per argparse path (`test_cli.py` 1,217 lines for a 220-line module). The golden cases already assert whole outputs; the error paths could be one table-driven test per module.                                                                                                                                                                              | P11        |
| G11 | **The workflows still carry indirection that the platform replaces.** `bot-cancel-stale-queued-runs.yaml` (59 lines, hourly) does what `concurrency` does and no workflow uses `concurrency`. `lib-get-test-matrix.yaml` and a shared config action are used to build a matrix of two Pythons and three systems. `ci.yaml` and `nightly.yaml` both run on a schedule, ten minutes apart.                                                       | P11        |
| G12 | **`python-candidates` goes stale every October** and nothing warns. It is one list in `inputs.py` (good), but the only reminder is a README checklist line. A new Python minor is missing from `python-versions` until a release.                                                                                                                                                                                                                | P5, P12    |
| G13 | **Property tests run on one Python version.** `hypothesis` is installed only for `python_version >= '3.14'`, so on 3.11 to 3.13 the property tests skip, although the action supports 3.11. The `pyproject.toml` does not say why.                                                                                                                                                                                                              | P11        |

### 2.3 Considered and left unchanged

| Topic                               | Why it stays                                                                                                                                                                                                                                                             |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Vendoring all of `packaging`        | 11,700 lines are shipped but only 6,800 are loaded, and the cost is 30 ms. Pruning modules makes `make vendor-packaging` a patch-and-check job and a future import of `packaging.tags` break. A pristine copy updates in one command. P4 is met.                          |
| `-B` (no bytecode)                  | It costs about 30 ms per run (measured) and keeps `__pycache__` out of the workspace and of a cached action directory. A job runs the action once. Not worth a cache.                                                                                                     |
| First match wins, markers ignored   | Evaluating markers needs the target Python and platform. The scoped entries (`@project`, `@extra:x`, `@group:x`) and `dependency_requirements` (all matches, with `marker` and `source`) already answer "which one". No change.                                           |
| The 13 outputs and the 5 inputs     | Each answers P1. `json` carries the rest. No output is added or removed in the target.                                                                                                                                                                                      |
| Python 3.11 as the minimum          | `tomllib` is the reason; the oldest runner images still ship it.                                                                                                                                                                                                          |

### 2.4 What is good and must be kept

- Inputs through `env:`, random output delimiters, escaped annotations (P2).
- `MetadataError` as the only user-facing failure, turned into an exit code by one `main` (P7).
- The golden cases: `test-data/<case>/` with `inputs.json` and `expected.json`, run by pytest and by the real action (P5, P10).
- The generated README tables and the README examples that are fixtures (P10, P12).
- One-way layers enforced by `tests/test_layers.py`, strict pyright, a 100 % coverage gate.
- Failing on a malformed field **that is read**, with the field named.

---

## 3. Target behaviour

### 3.1 Inputs: unchanged

`pyproject-path`, `extra-values`, `dependencies`, `python-candidates`, `strict`, with the
same names, defaults and syntax. Booleans stay exactly `true` or `false`.

### 3.2 Outputs: unchanged names, one changed shape

The 13 outputs keep their names and values. Only the `warnings` array of `json` changes:

```json
"warnings": [
  { "code": "dependency-not-found", "message": "dependency 'numpy' not found" }
],
"schema_version": 3
```

`message` no longer starts with the file name (the annotation carries it, see 3.5).
`schema_version` becomes `3` because an item type changes.

### 3.3 Warnings: one code each (fixes G7)

Nine codes, down from ten rows, with the two "dynamic" rows merged. The code is the stable
identifier; the message is for humans and may be reworded.

| Code                      | When                                                                                         | Effect                                                    |
| ------------------------- | -------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| `static-and-dynamic`      | A field of `[project]` has a value and is also in `dynamic` (forbidden by PEP 621).          | The static value is used.                                 |
| `dynamic-version`         | `version` is in `dynamic` and not set.                                                       | `version` and `normalized-version` are empty.             |
| `invalid-requires-python` | `requires-python` is not a valid specifier.                                                  | `python-versions` is empty.                               |
| `no-python-version`       | No candidate is allowed by `requires-python`.                                                | `python-versions` is empty.                               |
| `invalid-requirement`     | A requirement string cannot be parsed (only when `dependencies` is not empty).               | It is skipped.                                            |
| `include-group-cycle`     | The `include-group` entries include each other in a loop (only when `dependencies` is not empty). | The loop is not followed.                            |
| `unknown-include-group`   | An `include-group` names a group that does not exist (only when `dependencies` is not empty). | It is skipped.                                            |
| `dynamic-dependencies`    | `dependencies` or `optional-dependencies` is dynamic and not set (only when `dependencies` is not empty). | No requirement is found in it.              |
| `dependency-not-found`    | A requested package is not in the place(s) searched.                                         | Its specifier is `null`.                                  |

The README table is **generated** from the code that defines the codes (a tuple of
`(code, when, effect)` in `warnings.py`), so the docs cannot drift; a golden case exists for
each code. The `::warning` annotation gets `title=<code>`, which GitHub shows as the
heading of the annotation.

### 3.4 Dependency lookup: read nothing unless asked (fixes G1)

- `dependencies: []` skips the requirement tables entirely: no read, no validation, no
  limits, no warnings. This is the default, so most runs get cheaper and more tolerant.
- When entries are given, the semantics are the ones documented today: unscoped entry,
  first match in the order `[project].dependencies`, extras (file order), groups (file
  order, `include-group` expanded); scoped entry (`@project`, `@extra:<n>`,
  `@group:<n>`) looks in one place. Names are compared per PEP 503.
- A malformed requirement table fails the step **only** in that case, with the field named.

### 3.5 Errors and the file name (fixes G3, G8)

One format: `<field>: <problem>`, where the field is an input name (`strict`,
`dependencies`) or a TOML path (`[project].version`, `[dependency-groups].dev`).
File-level problems use the input that names the file:

```
pyproject-path: no such file
pyproject-path: not valid TOML: Invalid value (at line 3, column 5)
pyproject-path: not valid UTF-8: ...
[project].name: missing
[project].version: not a valid PEP 440 version: '1.x'
strict: must be 'true' or 'false', got: 'yes'
```

The text never contains the file name. `main` knows the path, so the annotation and the
plain stderr line add it once: `::error file=<path>::<message>`, or `<path>: <message>`
when the run is local. Warnings follow the same rule.

### 3.6 Reporting channels (fixes G6)

- **Annotations** (`::warning`, `::error`) with `file` and `title=<code>`: the one place
  where a human reads warnings and errors on GitHub.
- **The one-line `📦` log line**: kept, it is the quickest way to read the result in a log.
- **The job summary is removed.** `GITHUB_STEP_SUMMARY` is no longer written. GitHub shows
  the annotations on the run page.
- **`warnings` in `json`**: for workflows that react to a code.

### 3.7 Python versions, dynamic version, extras: unchanged

Same algorithm (a minor is allowed if some release of it satisfies the specifier; numeric
order for min and max), same empty values, same extras and groups ordering (PEP 685 and
PEP 503 normalised, first spelling kept).

### 3.8 Keeping `python-candidates` current (fixes G12)

The default list stays in one place (`python_versions.py`, moved from `inputs.py` because
it is data about Python versions). `packaging-update.yaml` becomes `maintenance.yaml` and
gains a weekly step that reads the supported CPython minors from
`https://endoflife.date/api/python.json`, and opens an issue when the newest one is not in
the default list. It needs the network, so it lives in CI only (P3 is about the action).

---

## 4. Target architecture

### 4.1 Execution flow

```
action.yaml  --env INPUT_*-->  scripts/run.sh  --exec-->  python -I -B scripts/extract_metadata.py
                                                           cli.main(os.environ)
                                                             parse_inputs      -> Inputs
                                                             build_report      -> Report        (pure but for reading the file)
                                                             write_outputs / print JSON
```

- **The command line is the environment (fixes G5).** `main(environ)` reads
  `INPUT_PYPROJECT_PATH`, `INPUT_EXTRA_VALUES`, `INPUT_DEPENDENCIES`,
  `INPUT_PYTHON_CANDIDATES` and `INPUT_STRICT` (the naming that GitHub uses for the inputs
  of its own actions), and the already existing `GITHUB_OUTPUT`.
  - `GITHUB_OUTPUT` set: write the outputs, print the annotations and the log line.
  - `GITHUB_OUTPUT` not set (a local run): print the `json` to stdout and the errors as
    plain text on stderr.
  - No argparse, no flags, no positional JSON, no `_ArgumentParser`, no `--help`. A local
    run is `INPUT_PYPROJECT_PATH=path python -m extract_pyproject_metadata`. The module
    docstring says so.
- `run.sh` drops `"$@"` and stays at about 20 lines (find the interpreter, `exec`).
- `action.yaml` keeps one step, `shell: bash`, five `env:` entries (now named `INPUT_*`)
  and the command `bash "$GITHUB_ACTION_PATH/scripts/run.sh"`.

### 4.2 Modules

Imports go one way, from the bottom of the list to the top. `tests/test_layers.py` keeps
the rank of each module.

```
src/extract_pyproject_metadata/
  errors.py            MetadataError(field, problem)             ~15
  warnings.py          Warning(code, message), the code table    ~50     (new; the README table comes from it)
  types.py             Inputs, Lookup, Project, Requirement, Report      ~70
  checks.py            type checks of values read from the file  ~60
  inputs.py            parse_inputs(Mapping) -> Inputs           ~130
  pyproject.py         load_pyproject, read_project -> Project   ~170    (name, version, requires-python, dynamic, extras, groups)
  requirements.py      collect + look up requirements            ~200
  python_versions.py   candidates, compatible, min, max          ~100    (+ the default candidates)
  github.py            outputs table, GITHUB_OUTPUT, annotations, log line, escaping   ~150
  report.py            build_report(Inputs) -> Report, strict     ~60
  cli.py               main(environ)                              ~60
  __init__.py, __main__.py
  _vendor/packaging/   (unchanged)
```

About 1,150 lines in 13 modules (from 2,210 in 17), none above 200. Deleted:
`metadata.py` (merged into `pyproject.py`), `output/summary.py`, the `output/` package
(`escaping.py` and `github.py` merge into one flat `github.py`; it still imports only
`types`, `errors` and `warnings`), the argparse half of `cli.py`.

### 4.3 One validated project, no raw dict in the core (fixes G2)

`pyproject.py` reads the document **once** into a typed value and the rest of the core
never sees `dict[str, Any]` except `requirements.py`, which is the only reader of the
dependency tables:

```python
@dataclass(frozen=True)
class Project:
    name: str                     # as written, validated (PEP 508)
    version: str | None           # None when dynamic
    requires_python: str
    dynamic: frozenset[str]
    extras: list[str]             # names only, PEP 685 normalised, sorted
    groups: list[str]

def read_project(data: dict[str, Any]) -> tuple[Project, list[Warning]]: ...
```

`normalized_name`, `file_name` and `normalized_version` are derived in `report.py` from the
`Project`, not stored. `dynamic` is validated here and passed on, so
`_dynamic_dependency_fields` disappears.

### 4.4 Requirements as a flat list (fixes G4)

```python
@dataclass(frozen=True)
class Requirement:
    name: str          # canonical (PEP 503)
    specifier: str
    marker: str        # "" if none
    source: str        # "project", "extra:<n>", "group:<n>"

@dataclass(frozen=True)
class Lookup:          # one entry of the `dependencies` input
    text: str          # as written, the key of the result
    name: str          # canonical
    source: str | None # None: search everywhere

def collect_requirements(data) -> tuple[list[Requirement], list[Warning]]: ...
def find(requirements, lookup) -> list[Requirement]:
    return [r for r in requirements
            if r.name == lookup.name and lookup.source in (None, r.source)]
```

- `parse_dependencies` builds the `Lookup` list, so the `@` syntax is parsed once, in
  `inputs.py`, and `_lookup_key`, the `"name@scope"` index keys and the per-place second
  index disappear.
- `dependency_specifiers[text]` is `find(...)[0].specifier`, or `None` with a
  `dependency-not-found` warning; `dependency_requirements[text]` is the whole list as
  dicts. Both come from the same `find`, so they cannot disagree.
- `collect_requirements` is called **only** when `inputs.dependencies` is not empty (G1).
  Parsing is once per requirement, so `functools.cache` goes.
- `flatten_group` keeps the depth and expansion limits, the cycle and unknown-group
  warnings, but becomes a small recursive generator over a typed `dict[str, list[...]]`
  checked once at the top of `collect_requirements` (the casts go).

### 4.5 `pyproject_path` leaves the core (fixes G3)

`MetadataError` and `Warning` carry no path. `report.py` and the core functions take no
`pyproject_path` argument; only `load_pyproject(path)` and `github.py` use it. This removes
the parameter from 23 of the 25 signatures, and with it a class of untested defaults.

### 4.6 Rules that stay

Module docstring and `from __future__ import annotations` everywhere; a public name is in
`__all__` and checked by `test_package.py`; verb prefixes (`read_`, `parse_`, `format_`);
type hints and docstrings on every function; a collaborator that a test replaces is an
argument with a default (the delimiter factory); `MetadataError` is the only user-facing
exception.

---

## 5. Test target

- Keep the layout (`tests/unit` mirrors the package, `integration`, `properties`,
  `test_layers.py`) and every rule of `CLAUDE.md`.
- **Delete with the code:** the argparse tests (about 1,000 of the 1,217 lines of
  `test_cli.py`, replaced by about 150 lines on `main(environ)`), `test_summary.py`, the
  `_lookup_key` and per-scope index tests, the "file name in the message" assertions.
- **Table-driven errors.** One parametrised test per module lists `(toml, field, problem)`
  for every error, instead of one function per message. Warnings are asserted by **code**,
  and the message only in the golden files.
- **One golden case per warning code** (nine) and per error class that the process tests
  need; adding behaviour is adding a directory.
- New tests for the changed contract: a broken `[project].dependencies` with
  `dependencies: []` passes (G1; check that it fails on `e66a1f2`); the error format
  `<field>: <problem>` for every `MetadataError` (a test walks the raising sites through
  the table above); the `title=` of annotations; `GITHUB_OUTPUT` unset prints JSON.
- **Property tests on all Pythons (G13).** Remove the `python_version >= '3.14'` marker of
  `hypothesis` (it supports 3.11) and run the property tests in the CI matrix. If a
  concrete reason for the marker turns up, write it next to it.
- Target: about 3,300 lines (from 6,440), and the coverage gate stays at 100 %.

---

## 6. CI, release and tooling target

### 6.1 Workflows (fixes G11)

| File                  | Target                                                                                                                                                                                                                           |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ci.yaml`             | `concurrency: { group: ${{ github.workflow }}-${{ github.ref }}, cancel-in-progress: true }`. The matrix is written in the file: systems `[ubuntu-latest, macos-latest, windows-latest]`, Pythons `["3.11", "3.14"]` (oldest and newest, kept in step with the default candidates by a comment and the maintenance check). No `schedule`. |
| `nightly.yaml`        | The only scheduled workflow: calls `ci.yaml` (to catch changes of the runner images and of the dependencies) and the generated stable copy.                                                                                    |
| `ci-test-local.yaml`  | Unchanged in design (golden matrix plus wiring jobs).                                                                                                                                                                            |
| `nightly-test-stable.yaml` | Generated; `STABLE_REF` becomes `v1` and never changes again (6.3).                                                                                                                                                         |
| `release.yaml`        | On `vX.Y.Z`: run `ci.yaml`, create the release from `release-notes/vX.Y.Z.md`, move `vX.Y` **and** `vX`.                                                                                                                         |
| `maintenance.yaml`    | Renamed from `packaging-update.yaml`: new `packaging` release, and the new-Python check of 3.8.                                                                                                                                  |
| Bots                  | Delete `bot-cancel-stale-queued-runs.yaml` and `lib-get-test-matrix.yaml`. Keep `bot-sync-shared-makefile.yaml` (it serves other repositories), `bot-pin-action.yaml` and `bot-format-files.yaml` while no other mechanism pins or formats. |

Net: 11 files and 942 lines become 9 files and about 780 lines. Third-party actions stay
pinned to a commit SHA.

### 6.2 Tooling

Already minimal (`make`, `ruff`, `pyright`, `pytest`, `pre-commit`, `codespell`, `pyyaml`).
Two changes: `hypothesis` loses its version marker (G13); `scripts/generate_docs.py` also
writes the warnings table from `warnings.py` (3.3). `.make/` is not edited.

### 6.3 Versioning (fixes G9)

Release the target as **`v1.0.0`**, with `v1` and `v1.0` moved by `release.yaml`. The
README uses `@v1`. After this, a breaking change is `v2`, and the nightly stable job no
longer needs a manual `STABLE_REF` edit. The release notes list every breaking change with
its replacement (the tables of 8 are the notes).

---

## 7. Deliberately not in the target

- Evaluating environment markers; running a build backend or project code; reading
  `tool.*` tables, `gui-scripts` or `entry-points`; validating the whole of PEP 621.
- Resolving a dynamic version (the backend is the right tool).
- A cache or any state between steps; a job summary; new outputs.
- Pruning the vendored `packaging` (2.3).
- Publishing to PyPI.

---

## 8. Migration plan

One branch and one pull request per step, in this order. Each leaves `main` green. **B**
marks a change of behaviour that the release notes must list.

| Step | Branch                                  | Change                                                                                                                                                                                | Breaking |
| ---- | --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| 1    | `bugfix/lazy-requirement-tables`        | Skip the requirement tables when `dependencies` is empty (G1). Test: a broken `dependencies` with `[]` passes. Update the README sentence on what is read.                           | B (more tolerant) |
| 2    | `refactor/project-dataclass`            | `Project`, `read_project`; merge `metadata.py` into `pyproject.py`; `dynamic` validated once (G2).                                                                                    |          |
| 3    | `refactor/flat-requirements`            | `Requirement`, `Lookup`, `collect_requirements`, `find`; drop the two-pass index, `_lookup_key` and the cache (G4).                                                                  |          |
| 4    | `refactor/drop-pyproject-path-argument` | `MetadataError` and warnings without the path; `main` adds it; one error format `<field>: <problem>` (G3, G8). Update the README failure list and the golden error cases.            | B (messages) |
| 5    | `feat/warning-codes`                    | `warnings.py`, `Warning(code, message)`, `title=<code>`, `schema_version` 3, README table generated, one golden case per code (G7). Merge the two dynamic-dependency warnings.       | B (`json`) |
| 6    | `refactor/env-only-cli`                 | `main(environ)` with `INPUT_*` and `GITHUB_OUTPUT`; delete argparse, `--github-output`, `run.sh` argument passing; rewrite `test_cli.py` (G5, G10).                                   | B (internal; local runs) |
| 7    | `refactor/remove-job-summary`           | Delete `output/summary.py`, the summary handling in `main` and its tests; flatten `output/` into `github.py` (G6).                                                                   | B (job summary) |
| 8    | `ci/concurrency-and-matrix`             | `concurrency`, inline matrix, one scheduled workflow, delete the cancel bot and `lib-get-test-matrix`, ungate `hypothesis` (G11, G13).                                               |          |
| 9    | `ci/maintenance-python-check`           | Rename the workflow, add the new-Python check, move the default candidates to `python_versions.py` (G12).                                                                             |          |
| 10   | `chore/release-v1`                      | Release notes, `release.yaml` moves `vX`, README `@v1`, `STABLE_REF = v1`; tag `v1.0.0` (G9). The tag is pushed by the owner.                                                       | B (version) |

Steps 1 and 8 to 9 are worth doing even if the rest is rejected. Steps 2 to 4 only change
the inside. Steps 5 to 7 change what a caller can see and are the reason for `v1`.

---

## 9. Expected result

| Measure                         | Today (`e66a1f2`)                      | Target                                              |
| ------------------------------- | -------------------------------------- | --------------------------------------------------- |
| Inputs / outputs                | 5 / 13                                 | 5 / 13 (unchanged names)                            |
| Warnings                        | 10 free-text rows                      | 9 coded warnings, generated table                   |
| Source, without `_vendor/`      | 2,210 lines, 17 modules                | about 1,150 lines, 13 modules, none above 200       |
| Functions with `pyproject_path` | 25                                     | 2                                                   |
| Entry point                     | argparse, 1 flag, 2 options, 3 strings | environment (`INPUT_*`, `GITHUB_OUTPUT`)            |
| Tests                           | 6,440 lines (2.9 times the source)     | about 3,300 lines (2.9 times, then below 3)         |
| Workflows                       | 11 files, 942 lines                    | 9 files, about 780 lines                            |
| Run with `dependencies: []`     | reads and validates all requirement tables | reads none                                      |
| Run time                        | about 100 ms                           | about 90 ms (fewer imports, no argparse)            |
| Caller pin                      | `@v0.3`, edited at every minor         | `@v1`                                               |

---

## 10. Decisions to take

Each has a recommendation; the migration plan assumes they are accepted.

1. **Environment-only entry point** (step 6) instead of keeping the flags. *Recommended:*
   yes. The only caller is the action, which already uses `env:`. Cost: a local run uses
   `INPUT_PYPROJECT_PATH=... python -m ...` instead of a positional argument.
2. **Remove the job summary** (step 7). *Recommended:* yes. The annotations already appear
   on the run page. Cost: a caller who read the summary sees the same list in the
   annotations.
3. **Structured warnings** (step 5). *Recommended:* yes. Cost: `schema_version` 3 and a
   changed `warnings` item; nobody can depend on the message text today, since it is not
   documented as stable.
4. **Call the result `v1.0.0`** (step 10). *Recommended:* yes, after steps 1 to 9.
   Alternative: `v0.4.0` and keep the manual edits at each minor.
5. **Network check for new Python versions in CI** (step 9). *Recommended:* yes, as an
   issue opener only. Alternative: keep the README reminder.
