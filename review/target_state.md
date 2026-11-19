# Target state of `extract-pyproject-metadata-action`

Review date: 2026-11-19. Reviewed commit: `f55fba2` (`main`, clean). The latest tag is
`v0.3.0`; the changes below are for **`v0.4.0`**. Windows support and floating tags (`v0`,
`STABLE_REF`) are decisions of the maintainer and are not reopened.

This file **replaces** the previous review (in the git history). Its five PRs (#267 to #271)
are merged: `static-and-dynamic` narrowed to the fields that are read, one
`lookup_dependencies`, output names derived from the report keys, the default of
`python-candidates` in `action.yaml`, the unit tests consolidated. That round was about code
shape. This one found **two behaviour defects and one broken check on `main`**, all verified by
running the code, plus three smaller simplifications. The interface (5 inputs, 13 outputs) does
not need a redesign.

Structure: **1** properties, **2** measured state, **3** findings, **4** target behaviour,
**5** target code, **6** tests, **7** CI and release, **8** what does not change, **9**
migration plan, **10** decisions for the maintainer, then what was and was not verified.

---

## 1. Properties of the action

They come from `README.md`, `CLAUDE.md` and `action.yaml`, made explicit and ordered. When two
conflict, the lower number wins. Every proposal is judged against them; a change that cannot
name the property it serves is not made.

| #   | Property                        | Meaning                                                                                                                                                                                                                                                            | How it is checked                                                                   |
| --- | ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------- |
| P1  | **Single purpose**              | Read a `pyproject.toml` and expose what drives a workflow: what to build (name, version), what to test (extras, groups, Python versions), what to install (specifiers).                                                                                            | A new output must say which of the three questions it answers.                      |
| P2  | **Read-only and safe**          | Never runs project code or a build backend; writes only `$GITHUB_OUTPUT`. A value from the file or an input cannot become shell code, a workflow command or Markdown.                                                                                              | `test_output_injection.py`; inputs go through `env:`; no `${{ }}` in `run:`.        |
| P3  | **Zero install, no network**    | Needs only a Python >= 3.11 on `PATH`. Nothing is installed or downloaded; `packaging` is vendored.                                                                                                                                                                | `run.sh` installs nothing; `test_run_sh.py`; `test_vendor.py`.                      |
| P4  | **Deterministic and immutable** | The same tag and inputs give the same outputs, whatever the date or the machine. A tag is never moved; callers pin `@vX.Y.Z`. No default depends on the clock or the network.                                                                                      | Golden cases; `CLAUDE.md` (no tag created from a PR).                               |
| P5  | **Strict, clear failures**      | Invalid input fails before anything is written, with one `<field>: <problem>` message, an `::error` annotation and never a traceback. Suspicious input is a coded warning; `strict` makes it fatal. **An output that cannot be trusted is never silent** (see F2). | `test_error_format.py`, `test_warnings.py`, `test_limits.py`.                       |
| P6  | **Reads only what it outputs**  | A field that no output uses is neither read, nor validated, nor a cause of a warning or a failure, `strict` included. The converse of P5: what an output reads is checked, what it does not read is ignored.                                                       | README "Failures"; a test per field.                                                |
| P7  | **Small, stable interface**     | Few inputs and outputs, scalars as plain strings, collections as JSON for `fromJSON`; `json` has a `schema_version`. A rename or a type change is breaking. Every default is visible in `action.yaml`.                                                             | `test_contract.py` (`action.yaml` against README and code).                         |
| P8  | **Simple and fast**             | Standard library plus vendored `packaging`; no clever code a reader must decode; **one fact has one definition** (code, docstring or README, not three); a run costs far less than starting the runner.                                                            | Measured in 2; reviewed here.                                                       |
| P9  | **Maintainable**                | One concern per module, imports go one way, 100 % coverage, docs generated from `action.yaml`, one task runner (`make`), the cheapest test level for each behaviour. **Every check is green on `main`.**                                                           | `test_layers.py`, `make check`, `make docs-check`, CI.                              |
| P10 | **Linux and macOS only**        | No Windows code, matrix cell, test or doc.                                                                                                                                                                                                                         | `CLAUDE.md`.                                                                        |
| P11 | **Ships only what it needs**    | The exported archive is `action.yaml`, `LICENSE`, `scripts/run.sh`, `scripts/extract_metadata.py` and the package. A file added to the repository is **not** shipped unless someone decides it is.                                                                 | `make check-export`, `ci-export.yaml`, `tests/integration/test_export.py` (see F1). |

Changes from the previous review: P5 gains the clause "never silent", P8 states "one fact has
one definition", P9 states "green on `main`", and P11 is new (it was in `CLAUDE.md` but not a
property, and F1 violates it).

---

## 2. Measured state

Measured on 2026-11-19, Python 3.14.10 (the venv), macOS, on `f55fba2`.

| What                      | Value                                                                                                                           |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| Package (no `_vendor`)    | 12 modules, **1,636 lines** (was 1,691)                                                                                         |
| Tests                     | **6,206 lines** (3.8x the package), **391 test functions, 1,083 cases in 12 s**: 1,082 pass, **1 fails** (`test_export.py`, F1) |
| Static checks             | `ruff check src scripts tests`: pass. `pyright`: 0 errors. (`make check`, the coverage gate and pre-commit were **not** run.)   |
| Run of the action         | **~150 ms** per `run.sh` run including `bash` (10 runs: 1.5 s). Nothing to optimize (see 8)                                     |
| Interface                 | 5 inputs, 13 outputs, 9 warning codes, `schema_version` 1                                                                       |
| Vendored `packaging`      | 28 tracked files, 12.7 k lines of Python; used: `version`, `specifiers`, `requirements`, `utils`                                |
| Largest unit-test modules | `test_requirements.py` 999 lines (78 tests), `test_pyproject.py` 862 (72), `test_cli.py` 646 (35, was 795)                      |
| Workflows                 | 16 files, 1,489 lines; `ci-action.yaml` alone is 681 lines with 17 local/released twin pairs                                    |

Conclusion: P8 holds on speed and on code size. The package shrank, the interface is stable,
and every one of the 1,082 passing tests is cheap. What does not hold is **P9 on `main`** (a red
check nobody saw because `make check` was not part of the last merge) and two violations of
P5 and P6 that the previous round's own change (#267) left behind.

---

## 3. Findings

Ordered by value. Each was checked by running the code or reading the lines named.

| #   | Finding                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | Property | Fix |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------- | --- |
| F1  | **The export check is red on `main`.** `bash dev/check_export.sh` exits 1: the archive contains `.python-version` (added in #265) and `CODEOWNERS`, which `.gitattributes` does not ignore. `pytest tests/integration/test_export.py` fails the same way, so `make check` and `ci-export.yaml` fail. Root cause: `.gitattributes` is a **deny list** (every file to hide is named), so each new root file is shipped until someone notices.                              | P11, P9  | 4.1 |
| F2  | **A dynamic `optional-dependencies` gives an empty `extras` output, silently.** Verified: `dynamic = ["optional-dependencies"]` and no lookup gives `"extras": []`, `warnings: []`, exit 0, **also with `strict: true`**. `extras` is the main input of a test matrix: the matrix is empty (or just the `extra-values` baseline) and nothing says why. The `dynamic-dependencies` warning exists but is only raised when `dependencies` (the lookup input) is not empty. | P5       | 4.2 |
| F3  | **`static-and-dynamic` fires for `dependencies` when nothing reads it.** Verified: `dependencies = ["x"]` and `dynamic = ["dependencies"]` with no lookup fails `strict` (exit 1). `dependencies` is in `READ_FIELDS` (#267), but `[project].dependencies` is only read for a lookup; `dynamic-dependencies` already says so ("only when `dependencies` is not empty"), `static-and-dynamic` does not. The same defect as the previous F1, one field left.               | P6       | 4.2 |
| F4  | **The module docstring of `cli.py` is the fourth copy of the interface.** 70 lines restate the inputs, the JSON keys, `strict`, the Python-versions rule and the failure causes, which `action.yaml`, the generated README tables and `types.Report` already define. It has already drifted once (it still describes the output list by hand after #269 derived it). A docstring that says everything is a docstring nobody keeps right.                                 | P8       | 5.2 |
| F5  | **The three largest unit-test modules did not shrink in #271.** `test_cli.py` went from 795 to 646 lines; `test_requirements.py` (993 to 999) and `test_pyproject.py` (845 to 862) grew, with the F1 tests of the last round. The ratio is 3.8x the package. The behaviours are covered; the cost is the reading and the editing of many cases that differ by a literal.                                                                                                 | P9       | 6   |
| F6  | **The README states some facts more than once.** "Python 3.11 or later" six times, the Windows decision three times, "environment markers are not evaluated" three times, "the action does not read the date or the network" twice, across Features, Prerequisites, Troubleshooting, FAQ and Limitations. Each repeat is a place to forget in the next change.                                                                                                           | P8       | 5.3 |

What was checked and found **good**, so it is not touched: the `env:` wiring of the inputs, the
random `$GITHUB_OUTPUT` delimiter and the escaping, validation of all inputs in one place
(`parse_inputs`, including the default of `python-candidates` now in `action.yaml`), requirement
tables read only for a lookup, `MetadataError` with a field prefix, `-I -B` in `run.sh`, one
entry point, the layered imports enforced by `test_layers.py`, output names derived from
`Report`, one `lookup_dependencies`, pinned actions with `ratchet` comments, no `concurrency`,
`permissions: {}`, `timeout-minutes` on every job, the local and released twin steps, the three
golden cases on the real action.

---

## 4. Target behaviour

The interface stays **5 inputs and 13 outputs**, `schema_version` stays `1` (no key is renamed,
removed or retyped). Two warnings change their condition (F2, F3). Nothing else is user visible.

### 4.1 What is shipped is an allow list (F1)

`.gitattributes` denies by default and names what the action needs. It was run in a clone with
the repository's own `dev/check_export.sh`: `✅ The exported files are the expected ones (51
entries)`.

```gitattributes
# Ship only what the action needs at runtime. Nothing is shipped unless it is listed below:
# a new file at the root (a dotfile, CODEOWNERS, a lock file, ...) stays out of the release.
# When the action starts using a new file, un-ignore it here and add it to dev/check_export.sh.
* export-ignore
/action.yaml -export-ignore
/LICENSE -export-ignore
/scripts/ -export-ignore
/scripts/run.sh -export-ignore
/scripts/extract_metadata.py -export-ignore
/src/ -export-ignore
/src/** -export-ignore
```

- It deletes the 23 lines that name what is hidden, and the class of defect behind F1: the
  failure mode of a new file becomes "not shipped" (visible at the first run of the action) and
  not "shipped by accident".
- `dev/check_export.sh` stays as it is (the expected set is the contract).
- `tests/integration/test_export.py` has tests that append one line to `.gitattributes`
  (`/action.yaml export-ignore`, ...): they keep working (the last matching line wins). The test
  "a file that the action does not need is exported" must append `/tests/ -export-ignore`
  instead of removing an ignore line; rewrite it, and run it **before** the change (it must
  fail on a mutation that exports a file) and after.
- `CLAUDE.md`: the sentence "`.gitattributes` marks everything else `export-ignore`" becomes
  literally true; add "the default is `export-ignore`".

### 4.2 A warning for every dependency field the action cannot read (F2, F3)

The rule is one sentence, and it is the one P5 and P6 already imply: **a field of `[project]`
that an output depends on is checked when that output is computed.**

| Field                                | Read when                           | `static-and-dynamic`                       | `dynamic-dependencies` (set and dynamic: no; unset and dynamic: yes) |
| ------------------------------------ | ----------------------------------- | ------------------------------------------ | -------------------------------------------------------------------- |
| `name`, `version`, `requires-python` | always                              | always                                     | n/a (`version` has `dynamic-version`; `name` is an error)            |
| `optional-dependencies`              | always (the `extras` output)        | **always**                                 | **always** (today: only with a lookup: F2)                           |
| `dependencies`                       | only with a lookup (`dependencies`) | **only with a lookup** (today: always: F3) | only with a lookup (unchanged)                                       |

- F2 is a behaviour change: a file with a dynamic `optional-dependencies` now warns on every
  run, and fails `strict`. That is the intent: `extras` is empty because the action cannot read
  them, and a release job that asked for `strict` wants to know.
- F3 is a behaviour change in the other direction: `strict` stops failing on a `dependencies`
  that is set and dynamic when no dependency is looked up.
- The code of the warning, `dynamic-dependencies`, is unchanged (stable codes, P7); its row in
  the generated README table changes to "`optional-dependencies`, or `dependencies` when
  `dependencies` is not empty, is in `dynamic` and not set".
- No new input, no new code, no new output.

### 4.3 Everything else: unchanged

Failure model (`<field>: <problem>`, `::error`, no traceback), the nine warning codes, `strict`,
the `json` schema, the lookup scopes (`name`, `@project`, `@extra:<n>`, `@group:<n>`; first match
wins; markers never evaluated). The rejected additions of the previous review stay rejected
(section 8).

---

## 5. Target code

The shape stays: a launcher, a package split by concern, imports going one way
(`tests/test_layers.py` is the only place that defines the ranks).

```text
action.yaml                      wiring only (inputs -> env, outputs <- step outputs)
scripts/run.sh                   find Python >= 3.11, exec the launcher
scripts/extract_metadata.py      launcher: sys.path.insert(src), raise SystemExit(run())
src/extract_pyproject_metadata/
  errors types warning_codes checks python_versions   (no import of the package, but types)
  inputs  pyproject                                    (parse_inputs; load_pyproject, read_project)
  requirements                                         (collect_requirements, lookup_dependencies)
  github                                               (outputs, annotations, log line)
  report  cli                                          (build_report; read_inputs, main, run)
```

### 5.1 One function for the two dynamic warnings (F2, F3)

In `pyproject.py`, the constant and the function take the fields as an argument; `read_project`
and `requirements._gather` each name the fields they read:

```python
# The fields of [project] that read_project always reads (the outputs name, version,
# requires-python and extras). [project].dependencies is read only for a lookup (_gather).
ALWAYS_READ_FIELDS = ("name", "version", "requires-python", "optional-dependencies")
LOOKUP_FIELDS = ("dependencies",)


def dynamic_field_warnings(
    project: dict[str, Any], dynamic: frozenset[str], fields: tuple[str, ...]
) -> list[ReportWarning]:
    """static-and-dynamic for a field that is set and dynamic, dynamic-dependencies for a
    dependency field that is dynamic and not set, among ``fields``."""
```

- `read_project` calls it with `ALWAYS_READ_FIELDS`; `_gather` calls it with `LOOKUP_FIELDS` and
  **no longer** builds the `dynamic-dependencies` warning of `optional-dependencies` itself (it
  moved to `read_project`: one place per field, no duplicate to deduplicate).
- `dynamic-version` stays in `_read_version` (it is an error-or-warning decision about one
  field, not a rule over a list).
- The test that keeps the two tuples equal to what the readers touch (written for #267) checks
  both: `ALWAYS_READ_FIELDS` against `read_project`, `LOOKUP_FIELDS` against
  `collect_requirements`.

Net: about +10 lines in `pyproject.py`, -8 in `requirements.py`; one rule per field.

### 5.2 A docstring that does not restate the interface (F4)

The module docstring of `cli.py` keeps what only `cli.py` knows, in about 15 lines: no
argument; the inputs are the `INPUT_*` variables (named by `env_name`, defaults in
`inputs.DEFAULT_INPUTS`); without `GITHUB_OUTPUT` the `json` object is printed, with it the outputs
are written and the annotations printed; exit code 0 or 1 with `<field>: <problem>` on stderr. It
**points to** `action.yaml` (inputs and outputs), `types.Report` (the keys of the `json`),
`warning_codes.py` (the codes) and the README (the failure causes). Delete the JSON sketch, the
description of `strict` and of `python_versions`, the failure list and the log-line paragraph:
each already has an owner. A test or a reviewer cannot keep two lists in step, and one list
cannot drift.

### 5.3 Say each fact once in the README (F6)

Keep the README's job (what it does, how to use it, the reference tables, the failure causes)
and move each repeated fact to **one** section:

| Fact                                       | Stays in                 | Removed from                                          |
| ------------------------------------------ | ------------------------ | ----------------------------------------------------- |
| Python 3.11 or later on `PATH`             | Prerequisites            | the intro, Troubleshooting, FAQ, Limitations          |
| Linux and macOS only                       | Prerequisites            | the intro, Limitations                                |
| No date, no network: new Python = an input | Inputs (below the table) | FAQ ("Why is the newest Python missing"), Limitations |
| Markers are never evaluated                | Looking up a dependency  | FAQ, Limitations                                      |
| First match wins                           | Looking up a dependency  | Limitations                                           |

- **Limitations** becomes a four-line pointer list (or disappears into Prerequisites and the
  lookup section); **FAQ** keeps only the questions that have no section (install/run, matrix);
  **Troubleshooting** keeps one entry per cause and links to Failures.
- `tests/integration/test_readme.py` pins the fixtures and the generated blocks, not the
  prose, so it keeps passing; `README.md` loses about 40 lines and nothing of the behaviour.
- The README keeps telling the current behaviour only, no history (a test checks it).

### 5.4 Unchanged on purpose

`inputs.py`, `checks.py`, `errors.py`, `python_versions.py` (the probe `X.Y.0 ... X.Y.99` and
`X.Y.9999` stays: the simplest exact rule with the public API of `SpecifierSet`), `_Expansion`
and its two limits, `github.py`, `report.py`, `run.sh` and the launcher.

---

## 6. Tests

Do not add tests for coverage's sake; the 100 % gate is met. Add and move only for the
findings:

- **Add first, check that each fails on `main`** (the repository rule for a fixed bug):
  - F2: dynamic `optional-dependencies`, no set value, no lookup: one `dynamic-dependencies`
    warning, `extras` empty, `strict` fails. Add a golden case
    `test-data/dynamic-optional-dependencies/` (`pyproject.toml` and `expected.json`): one
    directory, not a function.
  - F3: `dependencies` set and dynamic, no lookup: no warning, `strict` passes; with a lookup:
    `static-and-dynamic`.
  - F1: the existing `test_the_exported_files_...` is the failing test; it passes with 4.1. Add
    the mutation test of 4.1 (a new root file is not exported).
  - The two-tuples test of 5.1.
- **Delete with the code**: the `optional-dependencies` branch of `_gather`'s dynamic warning and
  its test; the tests of the `READ_FIELDS` constant that 5.1 replaces.
- **Consolidate (F5)**, without removing a behaviour, in the order of value:
  1. `test_requirements.py` (78 tests): the tests that assert one warning for one TOML input
     become one `parametrize` of `(toml, expected_warnings)`; the shape of `collect_requirements`
     is asserted once against a literal per source (project, extra, group, include).
  2. `test_pyproject.py` (72 tests): the type errors of each field (`name`, `version`,
     `requires-python`, `dynamic`, extras, groups) are one table `(toml, message)`, as
     `test_inputs.py` already does for the inputs.
  3. `test_cli.py` (35 tests): keep only what `cli` decides (environment to inputs, exit codes,
     UTF-8 streams, the `GITHUB_OUTPUT` switch); any "this file gives this report" is a golden
     case.
     The rule that stops regrowth: **a test of an output shape is a golden case; a unit test names
     a branch.** No target in lines, and the ratio to the package is a smell, not a gate.
- **Keep**: one behaviour per test, `match` on every `pytest.raises`, no `# pragma: no cover`,
  properties and injection tests untouched.

---

## 7. CI and release

The workflows follow `CLAUDE.md`; the only finding is that **`ci-export.yaml` is red** (F1), and
it was merged red because the merge did not require `make check` to pass locally and CI results
were not awaited. After 4.1 it is green. Process, not code: before the merge of a PR, `make
check` runs and CI is green (the PR description says which was run).

Follow-ups in the same PRs as their code:

- `ci-action.yaml`: add the golden case of F2 only if it covers a new input or output (it does
  not: the three golden cases of the real action stay `minimal`, `readme-example`,
  `python-candidates-none`; the new case is checked by `test_golden.py` alone).
- After `v0.4.0`: update the pinned SHA and tag of the released steps in `ci-action.yaml`. A
  check of a behaviour the last release does not have (F2, F3) carries
  `if: ${{ !inputs.use-released }}` until then. Today none of the 17 twin pairs checks F2 or F3,
  so nothing needs the guard.
- `maintenance.yaml` already tells the maintainer to change `python_versions.py` and
  `action.yaml` together; no change.

Releases stay manual (tag by the maintainer, GitHub release with notes, workflows pin the exact
tag). The workflows cannot be run locally: each PR says so and does not claim they pass.

---

## 8. What does not change, and why

| Candidate                                                                  | Decision | Reason                                                                                                                                                                                                    |
| -------------------------------------------------------------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A smaller interface (drop `python-min`, `python-max`, `file-name`, ...)    | **No**   | Each output answers a P1 question that a workflow **cannot compute in an expression** (the last item of an array, a string replace, PEP 440 normalization). `json` is not a substitute inside a `matrix`. |
| Preserving the written order of a specifier (`>=1.20,<3`)                  | No       | `packaging` stores a sorted set (`<3,>=1.20`); both are valid and deterministic. Keeping the text means re-parsing the requirement by hand (a second parser: P8).                                         |
| Evaluating environment markers, a warning for several different specifiers | No       | Needs an environment, or more surface (P7). `dependency_requirements` has every requirement and its marker; the workflow picks.                                                                           |
| `DependencyGroupResolver` instead of `_Expansion`                          | No       | Measured last round: its failures are errors, not warnings; the diamond is exponential; deep chains raise `RecursionError`.                                                                               |
| Deleting the unused vendored modules, or trimming `packaging.tags`         | No       | The copy is the wheel's `packaging/` verbatim, replaced by one command. A patched copy costs every update to save ~26 ms nobody sees on a runner.                                                         |
| Merging the two interpreter probes of `run.sh` (~35 ms)                    | No       | One `exec` with the check inside Python means a script that must parse on an old interpreter to print a clean error. Worse than 35 ms.                                                                    |
| A Python default derived from the date or the network                      | No       | Breaks P3 and P4. A new Python is a release, or an input.                                                                                                                                                 |
| Resolving a dynamic version, a `$GITHUB_STEP_SUMMARY`                      | No       | The first needs the build backend (P2); the second needs Markdown escaping for nothing a workflow uses.                                                                                                   |
| A typed `Source` instead of `"extra:<n>"` strings                          | No       | The string is the public `source` of the JSON; a type would be converted back at the border. Revisit with a fourth kind of place.                                                                         |
| `strict` as a list of codes, fewer warning codes                           | No       | Each code is a distinct, testable cause and the table is generated; a list is more surface (P7) for a need that `warnings` in `json` already covers.                                                      |
| Moving the `strict` check out of `build_report` into `cli`                 | No       | Would move 4 lines and one test for no gain; the report and its fatal warnings are one decision (the outputs are not written).                                                                            |
| Cutting the released (level 3) twin of the edge-case jobs                  | No       | `CLAUDE.md` requires the twin and a test checks every pair; the cost is the length of `ci-action.yaml` (681 lines), not complexity. If its upkeep ever hurts, change the rule in `CLAUDE.md` first (D4).  |
| Windows, `STABLE_REF`, a moving tag, `concurrency`                         | No       | Decisions of the maintainer (P10, P4) or forbidden by `CLAUDE.md`.                                                                                                                                        |

---

## 9. Migration plan

Independent PRs, each small and reviewable alone, from an up to date `main`, branch names per
`CLAUDE.md`. `make fix`, `make check` and `make docs` before each commit; CI green before the
merge.

| PR  | Branch                             | Content                                                                                                                                                           | Behaviour change                                                                                                                         |
| --- | ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `bugfix/export-allow-list`         | 4.1: deny-by-default `.gitattributes`, the rewritten mutation test, `CLAUDE.md` sentence. Makes `make check` and `ci-export` green.                               | none for the action; the archive is the expected set                                                                                     |
| 2   | `bugfix/dynamic-dependency-fields` | 4.2 and 5.1: `ALWAYS_READ_FIELDS`, `LOOKUP_FIELDS`, `dynamic_field_warnings`, the golden case, the tests (failing first), the README warning rows.                | **Yes**: a dynamic `optional-dependencies` warns (and fails `strict`); a `dependencies` set and dynamic no longer warns without a lookup |
| 3   | `docs/single-source-docs`          | 5.2 and 5.3: the short `cli.py` docstring; the README repeats removed. `make docs-check` unchanged.                                                               | none                                                                                                                                     |
| 4   | `test/consolidate-unit-tests-2`    | 6: parametrize `test_requirements.py` and `test_pyproject.py`, move output-shaped cases of `test_cli.py` to golden cases. After 2 (which touches the same files). | none (coverage stays 100 %)                                                                                                              |

Order: 1 first (red check), 2 second (the two defects), 3 and 4 in any order after 2. PRs 1 and 2
are independent and can be reviewed in parallel. Release only after the merges: **the maintainer**
pushes `v0.4.0` (never from a PR, never moved) and writes the release notes: the two warning
changes of PR 2 are the only user-visible entries.

**Expected result** (estimates, not measurements): a green `main`; `strict` that fails exactly
for what an output cannot trust, and never for what no output reads; the package at about the
same size (1,640 lines); one list of the interface per fact (`action.yaml`, `Report`,
`WARNING_CODES`, the README tables); a README about 40 lines shorter; unit tests smaller by the
merged cases, every behaviour kept; the same 5 inputs, 13 outputs and run time.

---

## 10. Decisions for the maintainer

| #   | Question                                                                                                                                                 | Recommendation                                                                                                                                                                                    |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | Make `.gitattributes` deny by default (4.1)?                                                                                                             | **Yes.** It fixes the red check, removes the cause, and was verified against the repository's own `check_export.sh`.                                                                              |
| D2  | Warn (and fail `strict`) when `optional-dependencies` is dynamic and not set, even with no lookup (4.2)? It makes a release job that passed before fail. | **Yes.** An empty `extras` that is silently wrong breaks a test matrix far from the cause (P5). A caller who does not care leaves `strict` off: the annotation is then the only change.           |
| D3  | Stop warning for a set-and-dynamic `dependencies` when nothing is looked up (4.2)?                                                                       | **Yes.** It is P6, and consistent with `dynamic-dependencies`.                                                                                                                                    |
| D4  | Let the released twin (level 3) run only `test` and `golden`, and the edge cases locally?                                                                | **No, not now.** The twin catches drift of the runner (Python, `bash`) on the released tag, which is its point. Revisit only if `ci-action.yaml` becomes a burden; it needs a `CLAUDE.md` change. |
| D5  | Trim the README repeats (5.3) and the `cli.py` docstring (5.2)?                                                                                          | **Yes**, as one docs PR with no behaviour change.                                                                                                                                                 |
| D6  | Consolidate the three largest unit-test modules again (6)?                                                                                               | **Yes**, last, and only by merging into tables and moving shapes to golden cases. The last pass shrank one of three modules.                                                                      |

---

## Verification status of this review

**Read**: `action.yaml`, `README.md`, `CLAUDE.md`, the previous `review/target_state.md`,
`run.sh`, the launcher, `.gitattributes`, `dev/check_export.sh`, `pyproject.toml`,
`scripts/test-helper.sh`, the head of `maintenance.yaml`, and every module of the package
except `_vendor` (`cli`, `report`, `types`, `inputs`, `pyproject`, `requirements`, `github`,
`checks`, `python_versions`, `warning_codes`). **Not read in full**: `ci-action.yaml` (steps
counted with `grep`: 17 `-local` and 17 `-released` ids), `test_layers.py` and the test modules
(sizes and test counts only), the other workflows, `generate_docs.py`.

**Run**: the full suite (1,082 passed, **1 failed**: `test_export.py`), `ruff check src
scripts tests` (pass), `pyright` (0 errors), `bash dev/check_export.sh` (**fails**, diff:
`.python-version`, `CODEOWNERS`), ten runs of `run.sh` (~150 ms each), three probes of the
program on files outside the repository: a set-and-dynamic `dependencies` with `strict` (F3:
exit 1), a dynamic `optional-dependencies` with `strict` (F2: exit 0, `extras: []`, no warning),
a file with a normalized name and a lookup (the outputs in the README are current); and the
deny-by-default `.gitattributes` in a throw-away clone with `check_export.sh` (passes, 51
entries). **Not run**: `make check` (so not the format check, the coverage gate or pre-commit),
`make docs-check`, `actionlint`, any GitHub workflow. The line counts after the changes are
estimates. None of the proposed code or tests is written; F2 and F3 are reproduced by running
the program, not by a test in the repository, and the only change made by this review is this
file (the scratch files are outside the repository).
