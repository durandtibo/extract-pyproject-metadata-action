# Target state of `extract-pyproject-metadata-action`

Review date: 2026-11-10. Reviewed commit: `57e2857` (`main`, clean). Target release:
**`v0.3.0`** (not tagged yet; the latest tag is `v0.2`). Windows is out of scope and
`STABLE_REF` / floating tags stay removed: both are decisions of the maintainer and are not
reopened here.

This file **replaces** the previous review (still in the git history). That round is
implemented: 5 inputs, 13 outputs, a typed package with a layered import graph, stable warning
codes, exact-tag releases. This round judges the result against the properties below. What is
left is **not scope**: it is one contract drift, some code that has no user, some CI cost that
buys nothing, and a few places where the interface can be made simpler for the caller.

Because `v0.3.0` is not tagged, every change below ships in it and breaks nobody who used a
release (`v0.2` has `pyproject-path`, `extra-values`, `name`, `version`, `extras` only).

Structure: **1** properties, **2** measured state, **3** findings, **4** target behaviour,
**5** target code, **6** tests, **7** CI and release, **8** what does not change, **9**
migration plan, **10** decisions for the maintainer.

---

## 1. Properties of the action

They come from `README.md`, `CLAUDE.md` and `action.yaml`, made explicit and ordered. When two
conflict, the lower number wins. Every proposal below is judged against them.

| #   | Property                        | Meaning                                                                                                                                                                                             | How it is checked                                                            |
| --- | ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| P1  | **Single purpose**              | Read a `pyproject.toml` and expose what drives a workflow: what to build (name, version), what to test (extras, groups, Python versions), what to install (specifiers).                             | A new output must say which of the three questions it answers.               |
| P2  | **Read-only and safe**          | Never runs project code or a build backend; writes only `$GITHUB_OUTPUT`. A value from the file or an input cannot become shell code, a workflow command or Markdown.                               | `test_output_injection.py`; inputs go through `env:`; no `${{ }}` in `run:`. |
| P3  | **Zero install, no network**    | Needs only a Python >= 3.11 on `PATH`. Nothing is installed or downloaded; `packaging` is vendored.                                                                                                 | `run.sh` installs nothing; `test_run_sh.py`; the vendored copy is hashed.    |
| P4  | **Deterministic and immutable** | The same tag and the same inputs give the same outputs, whatever the date. A tag is never moved; callers pin `@vX.Y.Z`. No default that depends on the clock or the network.                        | `release.yaml` never moves a tag; golden cases.                              |
| P5  | **Strict, clear failures**      | Invalid input fails before anything is written, with one `<field>: <problem>` message, an `::error` annotation and never a traceback. Suspicious input is a coded warning; `strict` makes it fatal. | `test_error_format.py`, `test_warnings.py`, `test_limits.py`.                |
| P6  | **Small, stable interface**     | Few inputs and outputs, scalars as plain strings, collections as JSON for `fromJSON`; `json` has a `schema_version`. A rename or a type change is breaking.                                         | `test_contract.py` (`action.yaml` against README and code).                  |
| P7  | **Simple and fast**             | Standard library plus vendored `packaging`; no clever code a reader must decode; a run is far below the cost of starting the runner.                                                                | Measured in 2.                                                               |
| P8  | **Maintainable**                | One concern per module, imports go one way, 100 % coverage, docs generated from `action.yaml`, one task runner (`make`).                                                                            | `test_layers.py`, `make check`, `make docs-check`, CI.                       |
| P9  | **Linux and macOS only**        | No Windows code, matrix cell, test or doc.                                                                                                                                                          | `CLAUDE.md`.                                                                 |

---

## 2. Measured state

All measured on 2026-11-10, Python 3.14.7, macOS, on `57e2857`.

| What                        | Value                                                                                                                                                                                                                   |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Package (without `_vendor`) | 13 modules, 1,745 lines (`requirements.py` 368, `pyproject.py` 254, `github.py` 202, `inputs.py` 183)                                                                                                                   |
| Tests                       | 6,147 lines (3.5x the package), **1,043 tests, 12.5 s**, 100 % coverage gate, all green                                                                                                                                 |
| Run of the action           | **~160 ms** per run (10 runs: 1.63 s): ~70 ms for the two interpreter probes of `run.sh`, ~50 ms for the imports (26 ms of them is the vendored `packaging.tags`, pulled in by `packaging.utils`), the rest is the work |
| Interface                   | 5 inputs, 13 outputs, 9 warning codes, `schema_version` 1                                                                                                                                                               |
| CI cost of one run          | `unit` 10 jobs, `smoke` 4, `golden` one job **per case** (18 cases), `wiring` 1, `test-old-python` 1, plus lint/types/verify: **~38 jobs**, run again every night                                                       |
| Vendored `packaging` 26.3   | 28 tracked files, SHA-256 recorded, used for `Version`, `SpecifierSet`, `Requirement`, `canonicalize_name`                                                                                                              |

Conclusion: P7 is met. 160 ms is nothing next to a runner's checkout and `setup-python`. The
~35 ms that a merged interpreter probe would save, and the 26 ms of `packaging.tags`, are **not**
worth any code (see 8).

---

## 3. Findings

Ordered by value. "Fix" points to the section of the target.

| #   | Finding                                                                                                                                                                                                                                                                                                                                                                                                                  | Property | Fix |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------- | --- |
| F1  | **Layering drift.** `CLAUDE.md` puts `inputs` at rank 1 and `python_versions` at rank 3 and says a module never imports a module above it, but `inputs.py` imports `python_versions` (`DEFAULT_PYTHON_CANDIDATES`), and `tests/test_layers.py` gives `python_versions` rank 1. The test is right, the document is wrong. A reader who follows `CLAUDE.md` gets the wrong graph.                                          | P8       | 5.1 |
| F2  | **Three entry points, one is dead.** `scripts/extract_metadata.py` (used by `run.sh`), `__main__.py` (`python -m ...`, which only works with `src` on the path) and `cli.run()`. `main()` also accepts `arguments` only to reject them with exit code 2 and its own message, for a command line that the action never passes and no documented user has. The cli docstring says `python -m`, the README says the script. | P7, P8   | 5.2 |
| F3  | **`python-versions` is in the order of the input**, so `python-min` is a function of a sort that the caller must trust, and `python-versions[0]` is not the minimum. The outputs `python-min` and `python-max` need `lowest_/highest_python_version` and a key function to compensate.                                                                                                                                   | P6, P7   | 4.2 |
| F4  | **Hand-written `include-group` expansion** (`_Expansion`, `_enter`, `_include`, `_cycle_warning`, two limits: ~150 of the 368 lines of `requirements.py` and a third of its 1,015 test lines) while the vendored `packaging` 26.3 ships `packaging.dependency_groups.DependencyGroupResolver` (PEP 735: normalization, includes, cycles). The vendored module is unused.                                                 | P7, P8   | 5.3 |
| F5  | **The `golden` job starts one runner per case (18)**, each to compare one JSON file that `test_golden.py` has already compared on the same commit. The job exists to check the wiring (every input reaches the program, every output comes back), which one maximal case and one warning case already prove. It runs again every night.                                                                                  | P8       | 7.1 |
| F6  | **`release.yaml` falls back to `--generate-notes`** when `release-notes/vX.Y.Z.md` is missing. The checklist says the file is mandatory, and an immutable tag should not get notes that nobody reviewed.                                                                                                                                                                                                                 | P4       | 7.2 |
| F7  | **Two readers of `[dependency-groups]`**: `pyproject.read_group_names` normalizes the names for the `groups` output, `requirements.read_groups` normalizes them again for the lookup. Same rule, two implementations.                                                                                                                                                                                                    | P8       | 5.3 |
| F8  | **The Python default needs a release per Python.** `DEFAULT_PYTHON_CANDIDATES` is a hard-coded list (correct under P4: a default that follows the clock would make a tag change over time), and `maintenance.yaml` opens an issue when it lags. It is a maintenance cost, not a defect, but the README does not tell a caller what to do when a new Python is out before the next release.                               | P4, P6   | 4.4 |
| F9  | **`release-notes/v0.3.0.md` will drift** from the target if 4.2 and 4.3 are applied (it describes `python-versions` as "the candidates that `requires-python` allows").                                                                                                                                                                                                                                                  | P6       | 9   |

What was checked and found **good**, so it is not touched: the `env:` wiring of inputs, the
random `$GITHUB_OUTPUT` delimiter and the escaping of annotations (`github.py`), the
validation of all inputs in one place (`inputs.py`), requirement tables read only for a
lookup, errors as `MetadataError` with a field prefix, `-I -B` in `run.sh`, pinned actions with
`ratchet` comments, no `concurrency`, top-level `permissions`, `timeout-minutes` on every job.

---

## 4. Target behaviour (the interface)

The interface stays 5 inputs and 13 outputs. Two behaviours change, two are documented.

### 4.1 Inputs: unchanged

| Input               | Default                | Note                                                                         |
| ------------------- | ---------------------- | ---------------------------------------------------------------------------- |
| `pyproject-path`    | `pyproject.toml`       |                                                                              |
| `extra-values`      | `[]`                   | prepended to the extras (`'[""]'` adds a "no extra" job)                     |
| `dependencies`      | `[]`                   | `name`, `name@project`, `name@extra:<n>`, `name@group:<n>`; first match wins |
| `python-candidates` | the list in the README | explicit, so the output depends on the tag and the inputs only (P4)          |
| `strict`            | `false`                | boolean; any warning is an error                                             |

Rejected additions: an input that selects which warnings are fatal (`strict` is a switch a
workflow understands at a glance; a workflow that wants less tests the `warnings` codes in
`json`), an input for the name of the output, an input to evaluate markers.

### 4.2 Outputs: `python-versions` is sorted

`python-versions` becomes the allowed candidates **sorted ascending as numbers, without
duplicates** (`["3.9","3.10","3.12"]`, whatever the order of `python-candidates`).

- `python-min` and `python-max` stay: `python-max` cannot be written in an expression
  (`fromJSON(x)[-1]` does not exist), and `python-min` is the common "lowest supported" value.
- The contract becomes simple to state and test: `python-min == python-versions[0]`,
  `python-max == python-versions[-1]`, empty when the list is empty.
- It is a breaking change only against the unreleased `v0.3.0` text.

### 4.3 Outputs: the rest is unchanged

`name`, `normalized-name`, `file-name`, `version`, `normalized-version`, `requires-python`,
`extras`, `groups`, `dependency-specifiers`, `json`. The `json` output keeps `schema_version`
`1` (an additive or order change does not bump it; a rename or a type change does).

### 4.4 Documented, not coded: the Python default (F8)

The default list of Python versions is part of the tag. The README states, next to the
generated list: _"A Python that is released after this tag is not in the default: pass it in
`python-candidates`. The action does not read the date or the network."_ The October task of
the release checklist stays.

### 4.5 Failure and warning model: unchanged

Same nine warning codes, same `<field>: <problem>` errors, same `strict` behaviour (the error
lists the warnings, nothing is written). If 5.3 is adopted, `include-group-cycle` and
`unknown-include-group` stay as warnings (decision D2).

---

## 5. Target architecture

The shape stays: a launcher, a package split by concern, imports going one way. The changes
are deletions and one correction of the documentation.

```
action.yaml                      wiring only (inputs -> env, outputs <- step outputs)
scripts/run.sh                   find Python >= 3.11, exec the launcher
scripts/extract_metadata.py      launcher: sys.path.insert(src), raise SystemExit(run())
src/extract_pyproject_metadata/
  errors types warning_codes checks        rank 0-1  (no import of the package)
  python_versions                          rank 1    (defines the default list; types only)
  inputs                                   rank 2    (parse_inputs)
  pyproject                                rank 2    (load_pyproject, read_project, read_groups)
  requirements                             rank 3    (collect/lookup)
  github                                   rank 3    (outputs, annotations, log line)
  report                                   rank 4    (build_report)
  cli                                      rank 5    (read_inputs, main, run)
```

### 5.1 One graph, in one place (F1)

`CLAUDE.md` and `tests/test_layers.py` must say the same thing, and the test is the source:
`python_versions` depends on `types` and the vendor only, so `inputs` may import it.
Update the numbered list in `CLAUDE.md` (move `python_versions` next to `checks`, below
`inputs`), and make `test_layers.py` the only place with the ranks. No code moves.

### 5.2 One entry point (F2)

- Delete `__main__.py` (and its test) and the `arguments` parameter of `main`, `_usage_error`
  and the exit code 2. `main(environ)` returns 0 or 1.
- `run()` stays the one function the launcher calls (UTF-8 streams, environment).
- The README "Development" and the `cli` docstring give the same local command:
  `INPUT_PYPROJECT_PATH=path/to/pyproject.toml python scripts/extract_metadata.py`.
- An argument on the command line is simply ignored by the launcher, as for any script that
  does not read `sys.argv`. The action never passes one.

Net: ~35 lines of code and ~100 lines of tests, one less way to run the program, and the exit
codes are 0 and 1.

### 5.3 Read the groups once; let `packaging` expand them (F4, F7)

1. **Always**: one `read_groups(table)` (normalized name to spellings), in `pyproject.py`, used
   by `read_group_names` and by `requirements.py`. `requirements` already sits above
   `pyproject`, so the import direction is right.
2. **Proposed, to be proven by a spike before it is merged**: replace `_Expansion` by
   `packaging.dependency_groups.DependencyGroupResolver`. The spike must show, with the
   existing tests as the oracle:
   - the same `group:<name>` requirements in the same order, with `include-group` expanded;
   - cycles and unknown groups still reported as the **warnings** `include-group-cycle` and
     `unknown-include-group` (catch `CyclicDependencyGroup` and the unknown-group error of the
     resolver **per group**, add the warning, skip the entry), never as a crash;
   - the diamond case (a group included by several groups, 25 levels) stays linear, so the
     `_MAX_GROUP_EXPANSIONS` budget can go, and the recursion-depth guard stays only if the
     resolver can still reach `RecursionError`;
   - a non-string, non-`include-group` entry is still the error `[dependency-groups].<g>:
entries must be ...`.

   If any point fails, keep `_Expansion` (the code is correct and tested) and do only step 1.
   I did not run the resolver in this review: this is a hypothesis with a clear exit, not a
   promise.

### 5.4 Python versions

`compatible_python_versions` returns the sorted, de-duplicated list. `lowest_python_version`,
`highest_python_version` and `_minor_version_key` collapse into one sort key; `python_min` is
`versions[0]` and `python_max` is `versions[-1]` in `build_report`. The probing of
`X.Y.0 ... X.Y.99` and `X.Y.9999` stays: it is the simplest exact rule with the public API of
`SpecifierSet`, and it costs about 500 `contains` calls.

### 5.5 What `types.py` says about itself

Its docstring calls its content "typed dictionaries"; four of the six are frozen dataclasses.
Fix the sentence. No code change.

---

## 6. Tests

The suite is strong (1,043 tests in 12.5 s, 100 % coverage, properties, golden cases,
injection, process-level tests) and is the reason the changes above are safe. The target is
**fewer tests per behaviour, not fewer behaviours**:

- Delete with the code: the usage-error tests (F2), the `__main__` test, the tests of
  `lowest_/highest_python_version` (replaced by one ordering test of `python-versions`, 4.2).
- Add: `python-versions` is sorted and de-duplicated for an unsorted input with duplicates
  (`["3.12","3.9","3.10","3.12"]` gives `["3.9","3.10","3.12"]`); `python-min` and
  `python-max` equal its ends; a property test of that on any list of candidates.
- Keep the rule: a test per bug fixed, checked to fail without the fix; one behaviour per test;
  `match` on every `pytest.raises`.
- If 5.3 step 2 is adopted, the 1,015 lines of `test_requirements.py` shrink around the
  expansion (the cases move to golden cases of `test-data/`, which already hold output-shaped
  checks); the limits tests of `test_limits.py` stay for whatever limit remains.
- Golden cases are the cheapest way to pin an output: prefer a `test-data/<case>/` directory
  to a unit test with a literal, when the assertion is "this file gives this `json`".

No change to the 100 % gate and no `pragma: no cover`.

---

## 7. CI, release and tooling

### 7.1 `ci-test-local.yaml`: check the wiring once, not 18 times (F5)

The integration job tests that the composite action passes its inputs and returns its outputs
(P6). The logic and the 18 golden files are tested without GitHub by `test_golden.py`, on the
same commit.

Target:

- `golden` runs **3 cases**: `minimal` (defaults), `readme-example` (every input set, every
  output filled, the case of the README) and one case with a warning (the annotation and the
  `warnings` array). `scripts/compare_json.py` stays.
- The list is explicit in the workflow (a three-item matrix) and **a test checks that each
  listed case exists** and that, together, they set every input and fill every output of
  `action.yaml` (so a new input without a case fails `make test`). The `cases` job and its
  `jq` pipeline are deleted.
- `smoke` (Linux and macOS on 3.11 and 3.15), `wiring` (failures, `strict`, nothing left
  behind) and `test-old-python` stay.

Effect: from ~38 to ~22 jobs per CI run and per night, with the same detection of a wiring
break. This changes the sentence of `CLAUDE.md` "the `golden` job runs the real action on every
case": update it in the same PR (decision D3).

### 7.2 `release.yaml`: no release without reviewed notes (F6)

Remove the `--generate-notes` branch: the job fails with `release-notes/$TAG.md: missing` when
the file does not exist, and `test_release.py` pins it. The tag is immutable (P4): its notes
must be reviewed text in the repository. Everything else stays (checks first, `--verify-tag`,
`contents: write` on the release job only, `persist-credentials: false`).

### 7.3 Unchanged workflows

`ci.yaml` (single entry point, `make` targets in the steps), `nightly.yaml` (runs the CI on the
schedule), `maintenance.yaml` (packaging and Python version issues), the four `bot-*` files,
`dependabot.yml`. Nothing here is a finding.

---

## 8. What does not change, and why

| Candidate                                                           | Decision | Reason                                                                                                                                                                  |
| ------------------------------------------------------------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Windows support                                                     | No       | Decision of the maintainer (P9).                                                                                                                                        |
| `STABLE_REF`, a moving `v0`/`v0.3` tag, a generated stable workflow | No       | Decision of the maintainer; P4: a tag never changes.                                                                                                                    |
| A Python default derived from the date or the network               | No       | Breaks P4 and P3. A new Python is a new release or an input (4.4).                                                                                                      |
| Evaluating environment markers                                      | No       | Needs an environment to evaluate against; the `dependency_requirements` list has every marker, the workflow picks.                                                      |
| Resolving a dynamic version                                         | No       | Needs the build backend: breaks P2. It is a warning, and `strict` makes it fatal.                                                                                       |
| A job summary (`$GITHUB_STEP_SUMMARY`)                              | No       | Removed on purpose; it needs Markdown escaping (P2) for no output a workflow can use.                                                                                   |
| Installing `packaging` at run time, or dropping the vendored copy   | No       | Breaks P3. The copy is verified by hash and updated by one command.                                                                                                     |
| Trimming the vendored `packaging` (tags, pylock, metadata, ...)     | No       | The copy is the wheel's `packaging/` verbatim: it is auditable against the recorded SHA-256 and costs nothing at run time. 26 ms of `tags` is not worth a patched copy. |
| Merging the two interpreter probes of `run.sh` (~35 ms)             | No       | A single `exec` with the version check inside the script means Python code that must parse on an old interpreter to print a clean error. Worse than 35 ms.              |
| `concurrency` in workflows                                          | No       | Forbidden by `CLAUDE.md`; `bot-cancel-stale-queued-runs.yaml` does it.                                                                                                  |
| Single source for `WarningCode` (the `Literal`) and `WARNING_CODES` | No       | A `Literal` cannot be built from a dict at type-check time; a test already compares them. Two lines per new code is acceptable.                                         |
| Fewer warning codes, or `strict` as a list of codes                 | No       | Each code is a distinct, testable cause; the table is generated. A list input is more surface (P6) for a need a `warnings` check already covers.                        |
| Splitting `requirements.py` further                                 | No       | It is the largest module (368 lines) but it shrinks with 5.3; split it only if it is still past a few hundred lines afterward.                                          |
| Rewriting `_PATCH_RELEASES` with `packaging.ranges`                 | No       | The public `SpecifierSet.contains` probe is exact for real releases, readable, and fast; `ranges` is new API of the vendored copy.                                      |

---

## 9. Migration plan

Stacked PRs, each small and reviewable on its own, each from an up to date `main` (or the
previous branch), branch names per `CLAUDE.md`. `make fix`, `make check` and `make docs` before
each commit. The workflows cannot be run locally: say so in each PR and do not claim they pass.

| PR  | Branch                                 | Content                                                                                                                                                                                                                                       | Behaviour change                                 |
| --- | -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| 1   | `docs/layering-and-types-docstring`    | F1 and 5.5: `CLAUDE.md` numbered list, `types.py` docstring, README "Development" command. No code.                                                                                                                                           | none                                             |
| 2   | `refactor/single-entry-point`          | 5.2: delete `__main__.py`, `arguments`, `_usage_error`, exit code 2, their tests; fix the `cli` docstring.                                                                                                                                    | none for the action (it passes no argument)      |
| 3   | `feat/sorted-python-versions`          | 4.2 and 5.4: sorted, de-duplicated `python-versions`; delete `lowest_/highest_`; tests and golden files (`UPDATE_GOLDEN=1`, review the diff); README sentence; update `release-notes/v0.3.0.md` (F9) and the README note of 4.4.              | `python-versions` is sorted (unreleased)         |
| 4   | `refactor/read-groups-once`            | 5.3 step 1: one `read_groups` in `pyproject.py`.                                                                                                                                                                                              | none                                             |
| 5   | `refactor/packaging-dependency-groups` | 5.3 step 2, **only if the spike passes**: the resolver replaces `_Expansion`; the limits that become unreachable are removed with their tests; README "Failures" updated if a limit disappears. Otherwise: close without merging and say why. | none expected; any difference is a bug of the PR |
| 6   | `ci/golden-three-cases`                | 7.1: three-case matrix, the test that checks the cases against `action.yaml`, delete the `cases` job; update `CLAUDE.md`.                                                                                                                     | none for users                                   |
| 7   | `ci/release-requires-notes`            | 7.2: no generated notes; `test_release.py`.                                                                                                                                                                                                   | none for users                                   |

Order: 1, 2, 3 first (the user-visible text of `v0.3.0` is final after 3), then 4 to 7
in any order. Release only after all merged: update the version check of the checklist, then
**the maintainer** pushes `v0.3.0` (never from a PR, never moved).

**Expected result.** Package ~1,550 lines (from 1,745) or ~1,400 with PR 5, tests ~5,400 lines
(from 6,147) with the same behaviours covered, CI ~22 jobs (from ~38), one entry point, one
dependency-group reader, a `CLAUDE.md` that agrees with `test_layers.py`, a `python-versions`
whose first and last items are `python-min` and `python-max`, and a release that cannot be
created without reviewed notes. The run stays ~160 ms.

---

## 10. Decisions for the maintainer

| #   | Question                                                                                                                 | Recommendation                                                                                                                    |
| --- | ------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| D1  | Sort `python-versions` ascending (4.2)?                                                                                  | **Yes.** It is free now and breaking later. Without it, keep the order of the input and say so in the README.                     |
| D2  | If the `packaging` resolver replaces `_Expansion`, may a cycle or an unknown group become an error instead of a warning? | **No.** Keep warnings: a cycle in a group that nobody looks up should not fail a workflow outside `strict` (P5). Catch per group. |
| D3  | Reduce the real-action `golden` matrix from 18 cases to 3 and change the sentence in `CLAUDE.md` (7.1)?                  | **Yes.** `test_golden.py` already checks all 18 on the same commit; the job's purpose is wiring.                                  |
| D4  | Make a missing `release-notes/vX.Y.Z.md` fail the release (7.2)?                                                         | **Yes.**                                                                                                                          |
| D5  | Is the hard-coded Python default plus the October release acceptable (F8, 4.4)?                                          | **Yes**, it is the price of P4; the README sentence makes it explicit.                                                            |

## Verification status of this review

Read: `action.yaml`, `README.md`, `CLAUDE.md`, `Makefile`, `run.sh`, the launcher, the whole
package except the body of `checks.py` past its first 60 lines, `ci.yaml`, `nightly.yaml`,
`maintenance.yaml`, `release.yaml`, the first and last third of `ci-test-local.yaml`, the
release notes and `pyproject.toml`. Run: the unit and integration tests (1,043 passed, 12.5 s),
ten runs of the action, an import-time profile. **Not run:** any GitHub workflow, `make check`
(lint and types), the `DependencyGroupResolver` spike of 5.3, `actionlint`. The three
numbers that depend on the proposals (package ~1,550 and ~1,400 lines, tests ~5,400 lines,
~22 CI jobs) are estimates, not measurements.
