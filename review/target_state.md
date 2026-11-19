# Target state of `extract-pyproject-metadata-action`

Review date: 2026-11-19. Reviewed commit: `a8f7f17` (`main`, clean). The latest tag is
`v0.3.0`, so every change below is a breaking or additive change for **`v0.4.0`**.
Windows support and floating tags (`v0`, `STABLE_REF`) are decisions of the maintainer and are
not reopened.

This file **replaces** the previous review (still in the git history). That round is
implemented and released in `v0.3.0`: 5 inputs, 13 outputs, a sorted `python-versions`, one entry
point, a layered package, three golden cases on the real action. What is left is small. One
**behaviour defect** against the properties, one **hypothesis disproved** by measurement (the
`packaging` group resolver), some **dead or duplicated code**, and one **convention** (the empty
default of `python-candidates`) that hides the real default. The action does not need a
redesign; it needs a few corrections and a rule against growth.

Structure: **1** properties, **2** measured state, **3** findings, **4** target behaviour,
**5** target code, **6** tests, **7** CI and release, **8** what does not change, **9**
migration plan, **10** decisions for the maintainer.

---

## 1. Properties of the action

They come from `README.md`, `CLAUDE.md` and `action.yaml`, made explicit and ordered. When two
conflict, the lower number wins. Every proposal below is judged against them, and a change that
cannot name the property it serves is not made.

| #   | Property                        | Meaning                                                                                                                                                                                              | How it is checked                                                            |
| --- | ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| P1  | **Single purpose**              | Read a `pyproject.toml` and expose what drives a workflow: what to build (name, version), what to test (extras, groups, Python versions), what to install (specifiers).                              | A new output must say which of the three questions it answers.               |
| P2  | **Read-only and safe**          | Never runs project code or a build backend; writes only `$GITHUB_OUTPUT`. A value from the file or an input cannot become shell code, a workflow command or Markdown.                                | `test_output_injection.py`; inputs go through `env:`; no `${{ }}` in `run:`. |
| P3  | **Zero install, no network**    | Needs only a Python >= 3.11 on `PATH`. Nothing is installed or downloaded; `packaging` is vendored.                                                                                                  | `run.sh` installs nothing; `test_run_sh.py`; `test_vendor.py`.               |
| P4  | **Deterministic and immutable** | The same tag and the same inputs give the same outputs, whatever the date or the machine. A tag is never moved; callers pin `@vX.Y.Z`. No default depends on the clock or the network.               | Golden cases; `CLAUDE.md` (no tag created from a PR).                        |
| P5  | **Strict, clear failures**      | Invalid input fails before anything is written, with one `<field>: <problem>` message, an `::error` annotation and never a traceback. Suspicious input is a coded warning; `strict` makes it fatal. | `test_error_format.py`, `test_warnings.py`, `test_limits.py`.                |
| P6  | **Reads only what it outputs**  | A field that no output uses is neither read, nor validated, nor a cause of a warning or of a failure, `strict` included.                                                                             | `README.md` ("Failures"); a test per field (see F1: **not met today**).      |
| P7  | **Small, stable interface**     | Few inputs and outputs, scalars as plain strings, collections as JSON for `fromJSON`; `json` has a `schema_version`. A rename or a type change is breaking. Every default is visible in `action.yaml`. | `test_contract.py` (`action.yaml` against README and code).                  |
| P8  | **Simple and fast**             | Standard library plus vendored `packaging`; no clever code a reader must decode; one name or one rule has one definition; a run costs far less than starting the runner.                            | Measured in 2; reviewed here.                                                |
| P9  | **Maintainable**                | One concern per module, imports go one way, 100 % coverage, docs generated from `action.yaml`, one task runner (`make`), the cheapest test level for each behaviour.                                 | `test_layers.py`, `make check`, `make docs-check`, CI.                       |
| P10 | **Linux and macOS only**        | No Windows code, matrix cell, test or doc.                                                                                                                                                           | `CLAUDE.md`.                                                                 |

P6 was implicit in the README ("Fields that the action does not output ... are not read and not
validated"); it is promoted to a property because F1 is a violation of it.

---

## 2. Measured state

Measured on 2026-11-19, Python 3.15.2, macOS, on `a8f7f17`.

| What                      | Value                                                                                                                                                         |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Package (no `_vendor`)    | 12 modules, **1,691 lines** (`requirements.py` 350, `pyproject.py` 276, `github.py` 202, `inputs.py` 183, `cli.py` 166)                                       |
| Tests                     | **6,332 lines** (3.7x the package), **1,080 tests in 10.2 s**, all green                                                                                      |
| Static checks             | `ruff check src scripts tests`: pass. `pyright`: 0 errors. (`make check` and the coverage gate were **not** run in this review.)                              |
| Run of the action         | **~96 ms** per run (10 runs: 0.96 s). The import is ~83 ms with `-X importtime`, of which 26 ms is `packaging.tags`, pulled in by `packaging.utils`           |
| Interface                 | 5 inputs, 13 outputs, 9 warning codes, `schema_version` 1                                                                                                     |
| Vendored `packaging` 26.3 | 28 tracked files, 11.7 k lines; used: `version`, `specifiers`, `requirements`, `utils` (and what they import). Not used: `dependency_groups`, `pylock`, `metadata` |
| Workflows                 | `ci.yaml` calls lint, types, python (unit on the OS x Python matrix, properties), action (local) and export; `nightly.yaml` runs the released action; 3 golden cases |

Conclusion: P8 holds on speed. 96 ms is nothing next to a checkout and `setup-python`; the 26 ms
of `packaging.tags` is not worth a patched vendored copy (see 8). The cost that matters is
reading and maintenance cost, which is what the findings below address.

---

## 3. Findings

Ordered by value. "Fix" points to the section of the target. Each one was checked by running the
code or reading the lines named.

| #   | Finding                                                                                                                                                                                                                                                                                                                                                                                                                                                        | Property | Fix |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | --- |
| F1  | **`static-and-dynamic` fails `strict` for fields that no output uses.** `pyproject._static_and_dynamic_warnings` warns for **any** field that is set and also in `dynamic`. Verified: a file with `classifiers` and `description` both set and in `dynamic` gives two warnings, and `strict: true` fails with exit 1, although neither field is read. The README says such fields are "not read and not validated".                                                  | P6, P5   | 4.2 |
| F2  | **The group resolver of `packaging` is not a replacement for `_Expansion`** (hypothesis F4 of the previous review, now measured). `DependencyGroupResolver` turns a cycle, an unknown group, an invalid requirement, a typo (`include_group`) and two spellings of one group name into an `ExceptionGroup` (errors, not the warnings of P5); on the 25-level diamond it returns **33,554,432** requirements in 0.6 s (the `_MAX_GROUP_EXPANSIONS` guard exists for this); a 3,000-level chain raises `RecursionError`. | P5, P8   | 8   |
| F3  | **`flatten_group` is dead code in production.** It is public (`__all__`), and only `tests/unit/test_requirements.py` calls it; `_gather` builds `_Expansion` itself. A public function with no caller invites a second way to do the same thing.                                                                                                                                                                                                                 | P8, P9   | 5.1 |
| F4  | **Two lookups over one list.** `lookup_specifiers` and `lookup_requirements` both call `find_requirements` for each entry; the specifier is the first requirement of the same list. `build_report` calls both and merges their warnings by hand.                                                                                                                                                                                                                | P8       | 5.1 |
| F5  | **The output names have six definitions**: `types.Report` keys (`snake_case`), `github.format_outputs` (the same names again in `kebab-case`, one line each), `github._SUMMARY_FIELDS`, the `cli.py` docstring, `action.yaml` and the README. Tests keep them equal; a new output is a change in six places.                                                                                                                                                      | P8, P9   | 5.2 |
| F6  | **`python-candidates` has a hidden default.** `action.yaml` gives `""` and the README table says "(see the description)"; the real list is a constant in `python_versions.py`, applied by `parse_inputs` (`values[...] or DEFAULT_PYTHON_CANDIDATES`) and rendered by a special case in `generate_docs.py`. It is the only input whose default is not the value in `action.yaml`.                                                                                  | P7, P8   | 4.3 |
| F7  | **Unit tests are large for what they cover**: `test_cli.py` 795 lines for a 166-line module, `test_requirements.py` 993 for 350, `test_pyproject.py` 845 for 276. They hold many one-assertion tests that differ by a literal, and part of `test_cli.py` re-tests what `test_golden.py` and `test_cli_process.py` already prove.                                                                                                                                   | P9       | 6   |
| F8  | **Stringly-typed `source`.** `"project"`, `"extra:<n>"` and `"group:<n>"` are built in `inputs.parse_dependencies` and again in `requirements._gather`, and compared as strings. It works and is covered by tests; it is a risk only when a fourth kind of place appears.                                                                                                                                                                                       | P8       | 8   |

What was checked and found **good**, so it is not touched: the `env:` wiring of inputs, the
random `$GITHUB_OUTPUT` delimiter and the escaping (`github.py`), validation of all inputs in
one place (`inputs.py`), requirement tables read only for a lookup, `MetadataError` with a field
prefix, `-I -B` in `run.sh`, one entry point (`cli.run`), the layered imports enforced by
`test_layers.py` and now described identically in `CLAUDE.md`, pinned actions with `ratchet`
comments, no `concurrency`, `permissions: {}`, `timeout-minutes` on every job, three golden
cases for the real action, and the local and released twin steps.

---

## 4. Target behaviour (the interface)

The interface stays **5 inputs and 13 outputs**. One behaviour is narrowed (F1), one default
becomes visible (F6), and the rest is unchanged.

### 4.1 Inputs and outputs: unchanged

| Input               | Default                | Note                                                                         |
| ------------------- | ---------------------- | ---------------------------------------------------------------------------- |
| `pyproject-path`    | `pyproject.toml`       |                                                                              |
| `extra-values`      | `[]`                   | prepended to the extras (`'[""]'` adds a "no extra" job)                     |
| `dependencies`      | `[]`                   | `name`, `name@project`, `name@extra:<n>`, `name@group:<n>`; first match wins |
| `python-candidates` | the list (see 4.3)     | explicit, so the output depends on the tag and the inputs only (P4)          |
| `strict`            | `false`                | boolean; any warning is an error                                             |

Outputs: `name`, `normalized-name`, `file-name`, `version`, `normalized-version`,
`requires-python`, `python-versions`, `python-min`, `python-max`, `extras`, `groups`,
`dependency-specifiers`, `json`. `schema_version` stays `1`: no key is renamed, removed or
retyped.

Rejected additions, each a new surface (P7) for a need that `json` already covers: an input
that selects which warnings are fatal; a warning for an unscoped lookup that matches several
different specifiers (`dependency_requirements` lists them all); marker evaluation; an output
for the Python classifiers.

### 4.2 `static-and-dynamic` only concerns the fields the action reads (F1)

A field of `[project]` that is set and listed in `dynamic` is a warning **only if the action
reads it**: `name`, `version`, `requires-python`, `dependencies`, `optional-dependencies`. Any
other field (`description`, `classifiers`, `readme`, ...) is ignored, as the rest of the
file. The `dynamic-version` and `dynamic-dependencies` warnings are unchanged.

- It is a behaviour change: a file that failed `strict` only because of `classifiers` or
  `description` now passes. Call it out in the PR and the release notes.
- The list of fields is one constant next to the code that reads them (`pyproject.py`), and a
  test checks that each field of it is read by `read_project` or `collect_requirements`, so the
  list cannot drift.
- The README warning table row changes to "A field that the action reads is set and also in
  `dynamic`".

### 4.3 The default of `python-candidates` is in `action.yaml` (F6)

`action.yaml` carries the real default, `'["3.11","3.12","3.13","3.14","3.15"]'`; the README
table shows it (no "see the description"); the empty string stops meaning "the default" and
becomes an invalid value (`python-candidates: not valid JSON: ''`), like every other empty
JSON input. `[]` still means "no candidate".

- The constant `DEFAULT_PYTHON_CANDIDATES` stays, for a local run without `INPUT_*`;
  `test_contract.py` checks that it equals the default of `action.yaml`, as it already does for
  the other four inputs.
- Deleted: the `or DEFAULT_PYTHON_CANDIDATES` line of `parse_inputs`, the empty default and the
  sentence "empty for the supported CPython versions" in `action.yaml`, the `candidates` block
  and `render_candidates` of `generate_docs.py`, and the `|| ''` of the golden steps in
  `ci-action.yaml`.
- The October task is unchanged, with one more line to edit; a test fails if the two differ.
- A caller that passes `python-candidates: ""` explicitly (nobody documented does) gets a clear
  error and removes the line. This is the only breaking part.

### 4.4 Failure and warning model: unchanged

Nine warning codes (the wording of one changes, 4.2), the same `<field>: <problem>` errors, the
same `strict` behaviour (the error lists the warnings, nothing is written).

---

## 5. Target architecture

The shape stays: a launcher, a package split by concern, imports going one way. The changes
are deletions, and one table that replaces six.

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

The ranks are the ones of `tests/test_layers.py`, which stays the only place that defines them.

### 5.1 One lookup, no dead function (F3, F4)

- Delete `flatten_group`. The tests of the expansion go through `collect_requirements` (the
  public path), or through `_Expansion` when they test the expansion alone, as the package's own
  tests do for private classes.
- Replace `lookup_specifiers`, `lookup_requirements` and `find_requirements` by one
  `lookup_dependencies(requirements, lookups) -> tuple[dict[str, list[Requirement]], list[ReportWarning]]`:
  every match of each entry in search order, plus one `dependency-not-found` warning per empty
  list. `build_report` derives the two outputs from it:
  `specifiers[text] = matches[0].specifier if matches else None`, and
  `dependency_requirements[text] = [asdict-like dict of each match]`.
- `Requirement` keeps its fields; the `dict[str, str]` of `dependency_requirements` is built
  in one place (`build_report`), not in the lookup.

Net: ~30 lines of code and the tests of two functions; one rule ("what is a match") in one
function.

### 5.2 One table for the output names (F5)

`format_outputs` is derived from the `Report` keys, not written twice:

```python
# The keys of the report that are not outputs of their own: they are only in the json output.
_JSON_ONLY = {"dependency_requirements", "warnings", "schema_version"}

def format_outputs(report: Report) -> dict[str, str]:
    outputs = {
        key.replace("_", "-"): value if isinstance(value, str) else _compact_json(value)
        for key, value in report.items()
        if key not in _JSON_ONLY
    }
    return {**outputs, "json": _compact_json(report)}
```

- The rule is stated once: an output is a report key in `kebab-case`, a string as is, any other
  value as compact JSON. `test_contract.py` already checks the result against `action.yaml`,
  so a missing or extra output still fails a test.
- `_SUMMARY_FIELDS` stays (it is a choice of what to log, not a copy of the names). The `cli.py`
  docstring stops listing the outputs and points to `action.yaml`; the README keeps its
  generated table. That is four definitions instead of six, and only one of them written by hand
  in code (`Report`).
- If the key order of `Report` is the output order of the action, nothing else changes: the
  golden `expected.json` files are byte-identical (a test, `test_golden.py`, proves it).

### 5.3 Fields read by the action, once (F1)

`pyproject.py` holds `READ_FIELDS = frozenset({...})`, used by `_static_and_dynamic_warnings`
and by the test that keeps it in step with the readers (4.2). No other module changes.

### 5.4 Unchanged on purpose

`inputs.py` (the one place that validates the input strings), `checks.py`, `errors.py`,
`warning_codes.py`, `python_versions.py` (the probe of `X.Y.0 ... X.Y.99` and `X.Y.9999` stays: the
simplest exact rule with the public API of `SpecifierSet`), `_Expansion` and its two limits
(see F2), `run.sh` and the launcher.

---

## 6. Tests

The suite is the reason these changes are safe: 1,080 tests, 10 s, properties, golden cases,
injection, process-level tests. The target is **fewer tests per behaviour, not fewer behaviours**,
and a rule against growth:

- **Add**: the three tests of F1 (a field that is not read, set and dynamic, gives no warning
  and `strict` passes; a field that is read still warns, one case per field of `READ_FIELDS`;
  `READ_FIELDS` equals the set the readers use). Write each one first, check that it fails on
  `main`.
- **Add**: `python-candidates: ""` is an error (4.3); `test_contract.py` compares the
  default of `action.yaml` with `DEFAULT_PYTHON_CANDIDATES`.
- **Delete with the code**: the tests of `flatten_group`, `lookup_specifiers`,
  `lookup_requirements` and `find_requirements` (replaced by tests of `lookup_dependencies` that
  assert whole results against a literal), the empty-default branch of `test_inputs.py`.
- **Consolidate** (F7), without removing a behaviour: in `test_cli.py`, keep what only `cli`
  decides (the environment to inputs mapping, the exit codes, UTF-8 streams, the `GITHUB_OUTPUT`
  switch) and move output-shaped checks ("this file gives this `json`") to a `test-data/<case>/`
  golden case, which is one directory instead of one function. Merge tests that differ by a
  literal into `pytest.mark.parametrize`. No target in lines: the rule is that a new test does not
  re-test an assertion that a golden case or another test already makes.
- **Keep**: a test per bug fixed, checked to fail without the fix; one behaviour per test;
  `match` on every `pytest.raises`; the 100 % gate; no `# pragma: no cover`.

---

## 7. CI, release and tooling

The workflows follow `CLAUDE.md` and have no finding. In particular, the testing strategy is
met: logic at level 1 (`ci-python`), wiring at level 2 (`ci-action`, `use-released: false`) and
level 3 (nightly, `use-released: true`), with local and released twin steps; the OS x Python
matrix comes from `durandtibo/workflow-config-action` through `lib-get-test-matrix.yaml`;
`make` targets in steps.

Two follow-ups of section 4, in the same PRs as their code:

- `ci-action.yaml`: with 4.3 the golden steps pass `python-candidates` from `inputs.json` or
  the default of the action; remove the `|| ''` fallback and check with `actionlint` when
  available. The `golden` cases keep `minimal`, `readme-example` and `python-candidates-none`.
- `maintenance.yaml`: the weekly Python check compares the released CPython versions with the
  default in `python_versions.py`; it should also say that `action.yaml` must change (4.3).
  The release checklist in the README gets the same sentence.

Releases stay manual (tag by the maintainer, GitHub release with notes, workflows pin the exact
tag). After `v0.4.0`, update the pinned SHA and tag of the released steps in `ci-action.yaml`;
a check of a feature the last release does not have carries `if: ${{ !inputs.use-released }}`
until then (F1 changes a behaviour and `python-candidates: ""` becomes an error, so the
released twin of these checks needs it).

The workflows cannot be run locally: each PR says so and does not claim they pass.

---

## 8. What does not change, and why

| Candidate                                                              | Decision | Reason                                                                                                                                                                                                   |
| ---------------------------------------------------------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `DependencyGroupResolver` instead of `_Expansion`                      | **No**   | Measured (F2): its failures are errors, not the warnings of P5; two spellings of a group raise; the diamond is exponential; deep chains raise `RecursionError`. Keep `_Expansion` and its limits.          |
| Deleting the unused vendored modules (`dependency_groups`, `pylock`)   | No       | The copy is the wheel's `packaging/` verbatim, auditable against the recorded SHA-256 and replaced by one command. 11.7 k lines in a tag tarball cost nothing at run time; a patched copy costs every update. |
| Trimming `packaging.tags` out of the import (26 ms of ~96 ms)          | No       | Needs a patched vendored copy, or an import trick, to save time nobody sees on a runner.                                                                                                                 |
| Merging the two interpreter probes of `run.sh` (~35 ms)                | No       | One `exec` with the check inside the script means Python that must parse on an old interpreter to print a clean error. Worse than 35 ms.                                                                |
| A Python default derived from the date or the network                  | No       | Breaks P3 and P4. A new Python is a release, or an input.                                                                                                                                                |
| Python versions from the `Programming Language :: Python` classifiers  | No       | Not mandatory and not validated; a second source for what `requires-python` and `python-candidates` already say (P1, P7).                                                                                |
| Evaluating environment markers                                         | No       | Needs an environment to evaluate against; `dependency_requirements` has every marker, the workflow picks.                                                                                                |
| Resolving a dynamic version                                            | No       | Needs the build backend: breaks P2. It is a warning, and `strict` makes it fatal.                                                                                                                        |
| A `$GITHUB_STEP_SUMMARY`                                               | No       | Needs Markdown escaping (P2) for nothing a workflow can use.                                                                                                                                             |
| A typed `Source` instead of the `"extra:<n>"` strings (F8)             | No       | The string is also the public `source` value of the JSON; a type would be converted back at the border. Revisit when a fourth kind of place exists.                                                      |
| `strict` as a list of codes, or fewer warning codes                    | No       | Each code is a distinct, testable cause and the table is generated; a list input is more surface (P7) for a need that checking `warnings` in `json` already covers.                                      |
| One definition for `WarningCode` (`Literal`) and `WARNING_CODES`       | No       | A `Literal` cannot be built from a dict for the type checker; a test compares them. Two lines per new code.                                                                                              |
| Folding the twin `local` / `released` steps of `ci-action.yaml`        | No       | `CLAUDE.md` requires them (the `uses:` of a step cannot be an expression) and a test checks every pair. The cost is length, not complexity.                                                              |
| Windows, `STABLE_REF`, a moving tag                                    | No       | Decisions of the maintainer (P10, P4).                                                                                                                                                                   |
| `concurrency` in workflows                                             | No       | Forbidden by `CLAUDE.md`; `bot-cancel-stale-queued-runs.yaml` does it.                                                                                                                                   |

---

## 9. Migration plan

Stacked or independent PRs, each small and reviewable on its own, from an up to date `main`,
branch names per `CLAUDE.md`. `make fix`, `make check` and `make docs` before each commit.

| PR  | Branch                              | Content                                                                                                                                                              | Behaviour change                                             |
| --- | ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| 1   | `bugfix/static-and-dynamic-scope`   | 4.2 and 5.3: `READ_FIELDS`, the narrowed warning, three tests (failing first), README row, golden case if one covers it.                                              | **Yes**: no warning for a field the action does not read     |
| 2   | `refactor/single-dependency-lookup` | 5.1: delete `flatten_group`; one `lookup_dependencies`; `build_report` derives the two outputs; tests move to the new function.                                       | none (outputs identical, checked by the golden cases)        |
| 3   | `refactor/derive-output-names`      | 5.2: `format_outputs` derived from `Report`; the `cli.py` docstring points to `action.yaml`.                                                                          | none (`expected.json` files unchanged)                       |
| 4   | `feat/visible-python-default`       | 4.3 and 7: default in `action.yaml`, `parse_inputs` and `generate_docs.py` simplified, `ci-action.yaml` and `maintenance.yaml` updated, contract test, README.         | **Yes**: `python-candidates: ""` is an error                 |
| 5   | `test/consolidate-unit-tests`       | 6: parametrize and move output-shaped checks to golden cases; no behaviour removed, coverage stays 100 %. Do it after 2 and 3, which delete tests of their own.      | none                                                         |

Order: 1 first (the only defect), then 2 and 3 in any order, 4 alone (it is the breaking one and
touches `action.yaml`), 5 last. Release only after all merged: **the maintainer** updates the
checklist, pushes `v0.4.0` (never from a PR, never moved) and writes the release notes: F1 and
the empty `python-candidates` are the two entries that need a sentence each.

**Expected result** (estimates, not measurements): package ~1,640 lines (from 1,691), tests
smaller by the deleted and merged tests with every behaviour kept, one rule for "what is a match",
one rule for output names, a README table that shows the real default of every input, and a
`strict` that never fails on a field the action does not output. The run stays ~96 ms and the
interface stays 5 inputs and 13 outputs.

---

## 10. Decisions for the maintainer

| #   | Question                                                                                                                           | Recommendation                                                                                                                                                                         |
| --- | ---------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | Narrow `static-and-dynamic` to the fields the action reads (4.2)? It lets a `strict` run pass on a file that failed before.         | **Yes.** It is the README's own rule (P6); a field the action does not output cannot be the reason a release job fails.                                                                |
| D2  | Put the default list of `python-candidates` in `action.yaml` and make `""` an error (4.3)?                                         | **Yes.** One more line to edit each October, guarded by a test, against a README that finally shows the real default and no special case in the generator. Keep the sentinel if you prefer one edit. |
| D3  | Derive the output names from `Report` (5.2) at the price of a rule ("kebab-case of the key; a string as is, the rest as JSON")?   | **Yes.** The rule is simple, and `test_contract.py` still checks the result against `action.yaml`.                                                                                      |
| D4  | Consolidate the unit tests (6) without a target in lines?                                                                          | **Yes**, but last, and only by merging and moving: no behaviour loses its test, coverage stays 100 %.                                                                                  |
| D5  | Warn when an unscoped lookup matches several different specifiers?                                                                 | **No** (4.1). `dependency_requirements` lists every match with its marker; a warning is more surface for a case a workflow can already test.                                            |

---

## Verification status of this review

**Read**: `action.yaml`, `README.md`, `CLAUDE.md`, `run.sh`, the launcher, `pyproject.toml`,
`.gitattributes`, `dev/check_export.sh`, `ci.yaml`, `ci-python.yaml`, `nightly.yaml`, the head of
`maintenance.yaml`, the job and step list of `ci-action.yaml`, `test_layers.py`, and the whole
package except `checks.py`, `errors.py` and `warning_codes.py`. **Run**: the full test suite (1,080
passed, 10.2 s), `ruff check src scripts tests` (pass), `pyright` (0 errors), ten runs of the
launcher, an import-time profile, a `strict` run on a file with `classifiers` and `description`
(F1: two warnings, exit 1), and the `DependencyGroupResolver` spike (F2) with a script outside the
repository. **Not run**: `make check` (so not the coverage gate, format check or pre-commit),
`make docs-check`, `actionlint`, any GitHub workflow. The line counts after the changes are
estimates. The tests that 4.2 and 4.3 add have not been written: F1 and F2 are reproduced by
running the code, not by a test in the repository.
