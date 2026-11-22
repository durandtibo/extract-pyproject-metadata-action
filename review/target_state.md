# Target state of `extract-pyproject-metadata-action`

Review date: 2026-11-22. Reviewed commit: `9d0b68c` (`main`, clean). The latest tag is
`v0.3.0`; the changes below are for **`v0.4.0`**. Windows support and floating tags (`v0`,
`STABLE_REF`) are decisions of the maintainer and are not reopened.

This file **replaces** the previous review (in the git history). Its PRs are merged (#276 the
export allow list, #277 the dependency-field warnings, #278 one place per fact in the `cli.py`
docstring and the README, #279 the first consolidation of the unit tests, #281 CLAUDE.md), and
`main` is green again (see section 2). The code is in good shape and the interface (5 inputs,
13 outputs) does not need a redesign. This round found **one behaviour defect of the same class
as last time**, which also shows that three warning rules can be one, and **one structural cost
in CI**: every run of the action is written twice. Everything else is small.

Structure: **1** properties, **2** measured state, **3** findings, **4** target behaviour,
**5** target code, **6** tests, **7** CI and release, **8** what does not change, **9**
migration plan, **10** decisions for the maintainer, then what was and was not verified.

---

## 1. Properties of the action

They come from `README.md`, `CLAUDE.md` and `action.yaml`, made explicit and ordered. When two
conflict, the lower number wins. Every proposal is judged against them; a change that cannot
name the property it serves is not made.

| #   | Property                        | Meaning                                                                                                                                                                                                                                      | How it is checked                                                                   |
| --- | ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| P1  | **Single purpose**              | Read a `pyproject.toml` and expose what drives a workflow: what to build (name, version), what to test (extras, groups, Python versions), what to install (specifiers).                                                                      | A new output must say which of the three questions it answers.                      |
| P2  | **Read-only and safe**          | Never runs project code or a build backend; writes only `$GITHUB_OUTPUT`. A value from the file or an input cannot become shell code, a workflow command or Markdown.                                                                        | `test_output_injection.py`; inputs go through `env:`; no `${{ }}` in `run:`.        |
| P3  | **Zero install, no network**    | Needs only a Python >= 3.11 on `PATH`. Nothing is installed or downloaded; `packaging` is vendored.                                                                                                                                          | `run.sh` installs nothing; `test_run_sh.py`; `test_vendor.py`.                      |
| P4  | **Deterministic and immutable** | The same tag and inputs give the same outputs, whatever the date or the machine. A tag is never moved; callers pin `@vX.Y.Z`. No default depends on the clock or the network.                                                                | Golden cases; `CLAUDE.md` (no tag created from a PR).                               |
| P5  | **Strict, clear failures**      | Invalid input fails before anything is written, with one `<field>: <problem>` message, an `::error` annotation and never a traceback. Suspicious input is a coded warning; `strict` makes it fatal. **An output that cannot be trusted is never silent.** | `test_error_format.py`, `test_warnings.py`, `test_limits.py`.                       |
| P6  | **Reads only what it outputs**  | A field that no output uses is neither read, nor validated, nor a cause of a warning or a failure, `strict` included. The converse of P5: what an output reads is checked, what it does not read is ignored.                                 | README "Failures"; a test per field.                                                |
| P7  | **Small, stable interface**     | Few inputs and outputs, scalars as plain strings, collections as JSON for `fromJSON`; `json` has a `schema_version`. A rename or a type change is breaking. Every default is visible in `action.yaml`.                                       | `test_contract.py` (`action.yaml` against README and code).                         |
| P8  | **Simple and fast**             | Standard library plus vendored `packaging`; no clever code a reader must decode; **one fact, one rule and one definition** (in code, docstring or README, not three); a run costs far less than starting the runner.                           | Measured in 2; reviewed here.                                                       |
| P9  | **Maintainable**                | One concern per module, imports go one way, 100 % coverage, docs generated from `action.yaml`, one task runner (`make`), the cheapest test level for each behaviour. Every check is green on `main`. **A chore is done once, in one place.**    | `test_layers.py`, `make check`, `make docs-check`, CI.                              |
| P10 | **Linux and macOS only**        | No Windows code, matrix cell, test or doc.                                                                                                                                                                                                   | `CLAUDE.md`.                                                                        |
| P11 | **Ships only what it needs, and is tested as shipped** | The exported archive is `action.yaml`, `LICENSE`, `scripts/run.sh`, `scripts/extract_metadata.py` and the package; a new file is not shipped unless listed. **The integration tests run that archive**, not the checkout. | `make check-export`, `ci-export.yaml`, `test_export.py`; section 5.3 for the second half. |

Changes from the previous review: P8 says "one rule" (F2 is three rules for one situation), P9
says "a chore is done once" (F3: every release edits 17 steps), and P11 gains "tested as
shipped" (F3: `uses: ./` runs the whole checkout, which is why a separate export check exists).

---

## 2. Measured state

Measured on 2026-11-22, Python 3.14, macOS, on `9d0b68c`.

| What                      | Value                                                                                                                                                 |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Package (no `_vendor`)    | 12 modules, **1,609 lines** (1,636 last review)                                                                                                       |
| Tests                     | **5,899 lines** (3.7x the package, 6,206 before), **1,041 tests, all pass in 11 s**; unit test functions: requirements 58, pyproject 60, cli 26      |
| Static checks             | `ruff check src scripts tests`: pass. `pyright`: 0 errors. `bash dev/check_export.sh`: pass (51 entries). (`make check`, `make docs-check`, pre-commit were **not** run: `uv`/`make` tooling not exercised here.) |
| Run of the action         | **~115 ms** per `run.sh` run including `bash` (5 runs). Nothing to optimize                                                                           |
| Interface                 | 5 inputs, 13 outputs, 9 warning codes, `schema_version` 1                                                                                             |
| Largest unit-test modules | `test_requirements.py` 897 lines (was 999), `test_pyproject.py` 780 (was 862), `test_cli.py` 468 (was 646)                                            |
| Workflows                 | 16 files, 1,489 lines; **`ci-action.yaml` is 681 lines (46 %)**, 17 local/released twin pairs, 8 jobs                                                 |

Previous findings: F1 (export red) fixed by #276; F2 and F3 (dependency warnings) by #277; F4
and F6 (docstring, README repeats) by #278; F5 (test size) halfway by #279. Nothing from the
previous review is open except the last item of it, which continues as F5 below.

Conclusion: P8 holds on speed and size, P9 holds on `main`. What is left is one P5 violation
(F1), the way the warnings are expressed (F2), and the cost of the action tests in CI (F3).

---

## 3. Findings

Ordered by value. Each was checked by running the code or reading the lines named.

| #   | Finding                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | Property | Fix |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | --- |
| F1  | **A dynamic `requires-python` gives a wrong `python-versions`, silently.** Verified: `dynamic = ["requires-python"]` and no value gives `requires_python: ""`, `python_versions: ["3.11" ... "3.15"]` (every candidate), `warnings: []`, exit 0, **also with `strict: true`**. A test matrix is built from `python-versions`; it now includes versions the project may not support, and nothing says why. This is the same defect as the dynamic `optional-dependencies` of the last review (empty `extras`, fixed by #277), left for the one remaining field. | P5       | 4.1 |
| F2  | **Three rules say "this field is dynamic".** `dynamic-version` (in `_read_version`), `dynamic-dependencies` (in `dynamic_field_warnings`, limited to `_REQUIREMENT_FIELDS`) and `static-and-dynamic`. The first two are the same situation (a read field is in `dynamic` and has no value, so an output is empty or incomplete) with a different message and a hand-kept list of which fields qualify. F1 shows the cost: adding a field means finding which of the lists to touch, and it was missed once already. | P8, P5   | 4.1, 5.1 |
| F3  | **Every run of the action in `ci-action.yaml` is written twice, and `uses: ./` does not test what is shipped.** 17 pairs (`<id>-local`, `<id>-released`) with the same `with:`, a verify step that reads `a.outputs.x \|\| b.outputs.x` for each of 13 outputs, a test that checks the pairs, and a chore after each release (update the SHA and tag in 17 steps). `uses: ./` runs the whole checkout, so a file missing from the export is hidden; that is why `ci-export.yaml` exists as a second check. 681 lines, 46 % of all workflow code, for what is one idea ("run the action under test"). | P9, P11  | 4.3, 5.3 |
| F4  | **The default of `python-candidates` is defined in `action.yaml` and in `DEFAULT_PYTHON_CANDIDATES`**, and the text of the issue that `maintenance.yaml` opens says "add them in both places". A test keeps them equal, so it cannot drift; it is still two edits per October for one fact. `scripts/test-helper.sh` already has `action_default`, the reader of the one in `action.yaml`.                                                                                                                                              | P8       | 5.2 |
| F5  | **The unit tests are still 3.7x the package.** `test_requirements.py` (897 lines, 58 functions) and `test_pyproject.py` (780, 60) hold many cases that differ by a literal; `test_cli.py` (468) still has "this file gives this report" cases that a golden case states with one directory.                                                                                                                                                                                                                                  | P9       | 6   |
| F6  | **`scripts/extract_metadata.py` says "see `cli.py` for the usage"**, and the `cli.py` docstring (after #278) no longer has a usage section: it points to `action.yaml` and the README. One dead pointer.                                                                                                                                                                                                                                                                                                                      | P8       | 5.2 |

What was checked and found **good**, so it is not touched: the `env:` wiring of the inputs, the
random `$GITHUB_OUTPUT` delimiter and the escaping, validation of all inputs in one place
(`parse_inputs`), requirement tables read only for a lookup, `MetadataError` with a field
prefix, `-I -B` in `run.sh`, one entry point, the layered imports enforced by `test_layers.py`,
output names derived from `Report`, one `lookup_dependencies`, the allow-list `.gitattributes`,
pinned actions with `ratchet` comments, no `concurrency`, `permissions: {}`, `timeout-minutes`
on every job, the three golden cases on the real action, the README that tells each fact once.
Probes run on files outside the repository gave the documented results: a normalized extra
(`Foo_Bar` is `foo-bar`) found by a lookup, `name@group:dev` scoped, markers kept in
`dependency_requirements` and never evaluated, `extra-values` first and without duplicates.

---

## 4. Target behaviour

The interface stays **5 inputs and 13 outputs**; `schema_version` stays `1` (no key of `json` is
renamed, removed or retyped). **One warning code is removed and one is renamed** (4.1): that is
the breaking change of `v0.4.0`, for the callers that test a code. Nothing else is user visible.

### 4.1 One rule for a dynamic field (F1, F2)

The rule is one sentence, and it is the one P5 and P6 already imply: **a field of `[project]`
that an output depends on is checked when that output is computed.** For a field in `dynamic`:

- with a static value too: `static-and-dynamic` (PEP 621 forbids it; the static value is used);
- without a value: **`dynamic-field`**, because the build backend computes it and the action
  cannot read it.

| Field                                | Read when                           | In `dynamic` with a value | In `dynamic`, no value                                                          |
| ------------------------------------ | ----------------------------------- | ------------------------- | ------------------------------------------------------------------------------- |
| `name`                               | always                              | `static-and-dynamic`      | an error (PEP 621 forbids it; the message says so)                              |
| `version`                            | always                              | `static-and-dynamic`      | **`dynamic-field`** (was `dynamic-version`): `version`, `normalized-version` empty |
| `requires-python`                    | always                              | `static-and-dynamic`      | **`dynamic-field`** (new, F1): `python-versions` is all the candidates, wrongly |
| `optional-dependencies`              | always (the `extras` output)        | `static-and-dynamic`      | **`dynamic-field`** (was `dynamic-dependencies`): `extras` has no extra name    |
| `dependencies`                       | only with a lookup (`dependencies`) | only with a lookup        | only with a lookup: **`dynamic-field`** (was `dynamic-dependencies`)            |

- A field the action does not read (`description`, `license`, ...) never warns (P6, unchanged).
- The message names the field and what is affected: `[project].requires-python is dynamic, the
  action cannot read it: python-versions is every candidate`. The code is the same for each
  field; the field is in the message, as `static-and-dynamic` already does.
- With a dynamic `requires-python`, `python-versions` stays "every candidate": the action has no
  better answer, and the warning (fatal with `strict`) is the honest signal. No new output.
- The README warning table loses a row (`dynamic-version` and `dynamic-dependencies` become
  `dynamic-field`): 9 codes become 8. Breaking for a workflow that tests
  `dynamic-version` or `dynamic-dependencies`: call it out in the PR and in the release notes
  (D1). The `message` has never been stable; the codes were.

### 4.2 Everything else: unchanged

Failure model (`<field>: <problem>`, `::error`, no traceback), `strict`, the `json` schema, the
lookup scopes (`name`, `@project`, `@extra:<n>`, `@group:<n>`; first match wins; markers never
evaluated), the defaults. The rejected additions of the previous reviews stay rejected (section
8).

### 4.3 The integration test runs the shipped archive (F3)

Not user visible; it changes **what CI proves**. Both levels of the action tests (CLAUDE.md,
"Testing strategy") use one `uses:` step per run, `uses: ./.action`, where `.action/` is the
action **as shipped**, put there by one step before it:

| Level                  | What `.action/` holds                                              | Created by                                  |
| ---------------------- | ------------------------------------------------------------------ | ------------------------------------------- |
| 2, local (`ci.yaml`)   | `git archive --worktree-attributes HEAD` of this checkout          | `scripts/stage-action.sh HEAD .action`      |
| 3, released (nightly)  | `git archive` of the latest `v*` tag                               | `scripts/stage-action.sh <latest tag> .action` |

I ran the archive of `HEAD` into a throw-away directory and `bash <dir>/scripts/run.sh` on a
fixture: it works from the archive alone (16 files besides `_vendor`). Consequences:

- **No twin steps.** One step per run, no `if:`, no `|| ` in the verify step, no test that
  pairs the steps, and no "update 17 pins after a release": the nightly takes the newest tag
  (`git tag --list 'v*' --sort=-v:refname | head -n1`, an error if there is none).
- **The local level now tests the export** (P11): a file that the action needs and
  `.gitattributes` hides makes the integration run fail where it ran green before. The
  `ci-export.yaml` check stays (it is cheap, explicit and tells the file by name).
- **Level 3 still tests the released code**, from the tag's own archive: what a consumer gets.
  What it no longer exercises is GitHub's resolution of `uses: owner/repo@sha`. Keep **one**
  smoke step for that in `nightly.yaml` (the minimal case, pinned with a `ratchet` comment, kept
  by `bot-pin-action.yaml`); it is the only place that needs the chore (D2).
- A check of a feature the latest tag does not have yet keeps `if: ${{ !inputs.use-released }}`
  on its job.

The workflows cannot be run locally: this is the part of the plan that has to be checked on
GitHub, in the PR, before it is trusted (section 7 lists what to look at).

---

## 5. Target code

The shape stays: a launcher, a package split by concern, imports going one way
(`tests/test_layers.py` is the only place that defines the ranks).

```text
action.yaml                      wiring only (inputs -> env, outputs <- step outputs)
scripts/run.sh                   find Python >= 3.11, exec the launcher
scripts/extract_metadata.py      launcher: sys.path.insert(src), raise SystemExit(run())
scripts/stage-action.sh          (new, CI only, not shipped) archive a git ref into a directory
src/extract_pyproject_metadata/
  errors types warning_codes checks python_versions   (no import of the package, but types)
  inputs  pyproject                                    (parse_inputs; load_pyproject, read_project)
  requirements                                         (collect_requirements, lookup_dependencies)
  github                                               (outputs, annotations, log line)
  report  cli                                          (build_report; read_inputs, main, run)
```

### 5.1 One function, one warning for a dynamic field (F1, F2)

In `pyproject.py`, `dynamic_field_warnings` is the only place that knows about `dynamic`. It
takes the fields to check, and `read_project` and `requirements._gather` each name the fields
they read (the two tuples already exist):

```python
ALWAYS_READ_FIELDS = ("name", "version", "requires-python", "optional-dependencies")
LOOKUP_FIELDS = ("dependencies",)

def dynamic_field_warnings(project, dynamic, fields) -> list[ReportWarning]:
    """static-and-dynamic for a field that is set and dynamic, dynamic-field for one that is
    dynamic and not set, among ``fields``. ``name`` that is not set is an error (_read_name)."""
    for field in dict.fromkeys(dynamic):
        if field not in fields or field == "name" and field not in project:
            continue
        ...
```

- `_REQUIREMENT_FIELDS` is deleted (every field qualifies), and so is the `dynamic-version`
  branch of `_read_version`, which becomes "return the version, or `None` when it is not set
  and dynamic, or raise": about -12 lines. `version` that is neither set nor dynamic stays an
  error.
- `types.WarningCode` and `warning_codes.WARNING_CODES` lose two codes and gain `dynamic-field`;
  the `static-and-dynamic` row stays and `make docs` regenerates the README table.
- The test that keeps the two tuples equal to what the readers touch (written for #267 and
  extended by #277) is unchanged; it now also guards `requires-python`.

Net: about -15 lines in the package. One rule, so the next field costs one word in a tuple.

### 5.2 One definition of the Python default, no dead pointer (F4, F6)

- `maintenance.yaml` reads the default from `action.yaml` (the owner, visible to users) with
  the same `action_default` logic as `scripts/test-helper.sh`, not from the Python constant, and
  its issue text says "update `action.yaml` and `DEFAULT_PYTHON_CANDIDATES`" (the constant stays
  because a local run without the action has no `action.yaml` to read; the existing test keeps
  the two equal, so a stale one fails CI, not a user).
- `scripts/extract_metadata.py`: "the logic is in `src/extract_pyproject_metadata`; the inputs
  and outputs are in `action.yaml`" (F6).

### 5.3 The CI of the action: one step per run (F3)

`scripts/stage-action.sh` (about 10 lines, `shellcheck` and `shfmt` clean like the others):

```bash
#!/usr/bin/env bash
# Put the action as it is shipped (the git archive of a ref, with the export-ignore rules of the
# working tree) in a directory, so that `uses: ./<dir>` runs what a consumer gets.
# Usage: stage-action.sh <ref> <dir>
set -euo pipefail
mkdir -p "$2"
git archive --worktree-attributes "$1" | tar -x -C "$2"
```

`ci-action.yaml` takes the ref as the input it already has, `use-released`, and a first step of
each job resolves it once:

```yaml
- name: Stage the action under test
  env:
    USE_RELEASED: ${{ inputs.use-released }}
  run: |
    ref=HEAD
    if [ "$USE_RELEASED" = "true" ]; then ref="$(git tag --list 'v*' --sort=-v:refname | head -n1)"; fi
    bash scripts/stage-action.sh "$ref" .action
```

with `actions/checkout` set to `fetch-depth: 0` (tags) when the input is true. Every run becomes
`uses: ./.action` (id `action`, no twin, no `if:`); the verify step reads `steps.action.outputs.x`
and `steps.action.outcome`. Estimated size: `ci-action.yaml` from 681 to about 380 lines (each
of the 17 runs loses its twin, about 12 lines, and each verify step loses its `||`).
`scripts/test-helper.sh` is unchanged. `nightly.yaml` keeps `use-released: true`.

`CLAUDE.md` changes in four places (the twin rule, the post-release chore, the level 2 and 3
descriptions, the `uses: ./` sentence in "Check what is shipped"); a test that now checks "every
run of the action is `uses: ./.action` and follows a stage step" replaces the twin tests of
`tests/integration/test_workflows.py` (about -60 lines).

---

## 6. Tests

Do not add tests for coverage's sake; the 100 % gate is met. Add and move only for the
findings:

- **Add first, check that each fails on `main`** (the repository rule for a fixed bug):
  - F1: dynamic `requires-python`, no value: one `dynamic-field` warning, `python_versions` all
    the candidates, `strict` fails. A golden case `test-data/dynamic-requires-python/`
    (`pyproject.toml` and `expected.json`): one directory, not a function.
  - F2: the three existing dynamic cases (`dynamic-version`, `dynamic-optional-dependencies`,
    `dynamic-dependencies-not-found`) change their expected code (`UPDATE_GOLDEN=1`, review the
    diff); `test_warnings.py` and the README fixtures follow the rename.
  - The two-tuples test: add `requires-python` to what it checks.
  - F3: a test that every `uses: ./.action` step follows the stage step of its job.
- **Delete with the code**: the `dynamic-version` branch of `_read_version` and its unit test;
  the `_REQUIREMENT_FIELDS` test; the twin-pair tests of `test_workflows.py`.
- **Consolidate (F5)**, without removing a behaviour, in the order of value:
  1. `test_requirements.py` (58 tests): the tests that assert one warning for one TOML input
     become one `parametrize` of `(toml, expected_warnings)`; the shape of `collect_requirements`
     is asserted once against a literal per source (project, extra, group, include).
  2. `test_pyproject.py` (60 tests): the type errors of each field (`name`, `version`,
     `requires-python`, `dynamic`, extras, groups) are one table `(toml, message)`, as
     `test_inputs.py` already does for the inputs.
  3. `test_cli.py` (26 tests): keep only what `cli` decides (environment to inputs, exit codes,
     UTF-8 streams, the `GITHUB_OUTPUT` switch); a case of the form "this file gives this
     report" is a golden case.
     The rule that stops regrowth: **a test of an output shape is a golden case; a unit test
     names a branch.** No target in lines; the ratio to the package is a smell, not a gate.
- **Keep**: one behaviour per test, `match` on every `pytest.raises`, no `# pragma: no cover`,
  properties and injection tests untouched.

---

## 7. CI and release

The workflows follow `CLAUDE.md`. The one structural change is 5.3. Because the workflows cannot
be run locally, the PR of 5.3 says so and is **not merged before** a run of `ci.yaml` and a
manual `nightly.yaml` are green. What to look at in those runs:

- `git archive` has a `.gitattributes` to read in the checkout (`--worktree-attributes`), and
  `fetch-depth: 0` gives the tags to the nightly; both are assumptions about `actions/checkout`
  that the first run proves or disproves.
- `uses: ./.action` runs from a directory that is not the repository root; `GITHUB_ACTION_PATH`
  then points into `.action`, `run.sh` finds its sibling files from its own path (verified
  locally with the archive), and the `count_pycache` assertion still sees none (`-B`).
- The `test-old-python` and `golden` jobs read fixtures from the checkout (`test-data/`), which
  is not in the archive and is not meant to be: the action reads only its `pyproject-path` input.

After a release there is nothing to edit (the nightly takes the newest tag), except the one
pinned smoke step of D2, which `bot-pin-action.yaml` keeps current. `maintenance.yaml` stays,
with the text of 5.2. Releases stay manual (tag by the maintainer, GitHub release with notes,
workflows pin the exact tag).

---

## 8. What does not change, and why

| Candidate                                                                  | Decision | Reason                                                                                                                                                                                                    |
| -------------------------------------------------------------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A smaller interface (drop `python-min`, `python-max`, `file-name`, ...)    | **No**   | Each output answers a P1 question that a workflow **cannot compute in an expression** (the last item of an array, a string replace, PEP 440 normalization). `json` is not a substitute inside a `matrix`. |
| `kebab-case` keys in `json` to match the outputs                           | No       | `fromJSON(x).normalized_name` is an expression; `.normalized-name` is not (it needs `['normalized-name']`). The `snake_case` is deliberate and documented.                                                |
| Renaming `extra-values`, `dependencies`                                    | No       | The names are documented and used; a rename is a breaking change with no new capability.                                                                                                                  |
| A default of `python-candidates` that is derived (date, network, `sys`)    | No       | Breaks P3 and P4. A new Python is a release, or an input. F4 reduces the cost of the release; it does not remove it.                                                                                      |
| Preserving the written order of a specifier (`>=1.20,<3`)                  | No       | `packaging` stores a sorted set (`<3,>=1.20`); both are valid and deterministic. Keeping the text means re-parsing the requirement by hand (a second parser: P8).                                         |
| Evaluating environment markers, a warning for several different specifiers | No       | Needs an environment, or more surface (P7). `dependency_requirements` has every requirement and its marker; the workflow picks.                                                                           |
| `DependencyGroupResolver` instead of `_Expansion`                          | No       | Its failures are errors, not warnings; the diamond is exponential; deep chains raise `RecursionError` (measured in an earlier round).                                                                     |
| Deleting the unused vendored modules, or trimming `packaging.tags`         | No       | The copy is the wheel's `packaging/` verbatim, replaced by one command. A patched copy costs every update to save ~26 ms nobody sees on a runner.                                                         |
| Merging the two interpreter probes of `run.sh` (~35 ms)                    | No       | One `exec` with the check inside Python means a script that must parse on an old interpreter to print a clean error. Worse than 35 ms.                                                                    |
| Resolving a dynamic version or `requires-python`, `$GITHUB_STEP_SUMMARY`  | No       | The first needs the build backend (P2); the second needs Markdown escaping for nothing a workflow uses. F1 warns; it does not guess.                                                                       |
| A typed `Source` instead of `"extra:<n>"` strings                          | No       | The string is the public `source` of the JSON; a type would be converted back at the border. Revisit with a fourth kind of place.                                                                         |
| `strict` as a list of codes                                                | No       | `warnings` in `json` already covers the need; a list is more surface (P7).                                                                                                                                |
| Moving the `strict` check out of `build_report` into `cli`                 | No       | Would move 4 lines and one test for no gain; the report and its fatal warnings are one decision (the outputs are not written).                                                                            |
| Merging modules (`errors`, `checks`, `warning_codes` are small)            | No       | Each is one concern with its own tests and a rank in `test_layers.py`; the sizes (10 to 116 lines) are the result of the rule "one concern per module", not a defect.                                      |
| Windows, `STABLE_REF`, a moving tag, `concurrency`                         | No       | Decisions of the maintainer (P10, P4) or forbidden by `CLAUDE.md`.                                                                                                                                        |

---

## 9. Migration plan

Independent PRs, each small and reviewable alone, from an up to date `main`, branch names per
`CLAUDE.md`. `make fix`, `make check` and `make docs` before each commit; CI green before the
merge.

| PR  | Branch                           | Content                                                                                                                                                              | Behaviour change                                                                                                                          |
| --- | -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `bugfix/dynamic-field-warning`   | 4.1 and 5.1: `dynamic-field`, the dynamic `requires-python` warning, the golden case, the renamed codes in the tests, fixtures and README (`make docs`), tests failing first. | **Yes**: `dynamic-version` and `dynamic-dependencies` become `dynamic-field`; a dynamic `requires-python` warns (and fails `strict`)        |
| 2   | `ci/test-the-shipped-action`     | 4.3 and 5.3: `stage-action.sh`, one step per run in `ci-action.yaml`, the new `test_workflows.py` test, `CLAUDE.md`, the one smoke step in `nightly.yaml`. Needs a green GitHub run first. | none for the action; CI tests the archive                                                                                                  |
| 3   | `docs/one-python-default`        | 5.2: `maintenance.yaml` reads `action.yaml`; the launcher docstring.                                                                                                 | none                                                                                                                                      |
| 4   | `test/consolidate-unit-tests-3`  | 6: parametrize `test_requirements.py` and `test_pyproject.py`, move output-shaped cases of `test_cli.py` to golden cases. After 1 (it changes the same files).            | none (coverage stays 100 %)                                                                                                               |

Order: 1 and 2 are independent (1 is code, 2 is CI) and can be reviewed in parallel; 3 any time;
4 last. Release only after the merges: **the maintainer** pushes `v0.4.0` (never from a PR,
never moved) and writes the release notes. The only user-visible entries are the warning
changes of PR 1: a renamed code, and a dynamic `requires-python` that now warns.

**Expected result** (estimates, not measurements): the package about 15 lines smaller (about
1,595); `ci-action.yaml` about 300 lines shorter and one definition of "run the action under
test"; the integration tests prove what is shipped; no edit of 17 steps after a release; `strict`
that fails for every field an output cannot trust, with one rule and one code; unit tests smaller
by the merged cases, every behaviour kept; the same 5 inputs, 13 outputs and ~115 ms run.

---

## 10. Decisions for the maintainer

| #   | Question                                                                                                                                                                              | Recommendation                                                                                                                                                                                                                       |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| D1  | Merge `dynamic-version` and `dynamic-dependencies` into one code `dynamic-field`, and warn for a dynamic `requires-python` (4.1)? Breaking for a caller that tests the old codes.      | **Yes.** One rule that cannot miss a field (F1 was a missed field), one row less, and v0.x allows it. The alternative (keep the codes, add `dynamic-requires-python`) fixes F1 only and leaves three rules.                         |
| D2  | Replace the 17 twin steps by a staged archive (4.3, 5.3), keeping one pinned `uses: owner/repo@sha` smoke step in the nightly? It changes `CLAUDE.md` ("Testing strategy").            | **Yes**, after a green GitHub run of the PR. It removes the largest duplication of the repository and makes level 2 test the shipped set. Keep the smoke step: it is the only test of GitHub's own resolution of the released action. |
| D3  | Should the nightly test the newest tag automatically (no edit after a release), or a tag written in the workflow?                                                                     | **The newest tag.** "Latest release" is the stated intent; a written tag is a chore that can be forgotten and then tests an old release.                                                                                             |
| D4  | Let `maintenance.yaml` read the default of `python-candidates` from `action.yaml` (5.2)?                                                                                               | **Yes.** `action.yaml` is the owner users read (P7); the constant stays for local runs and a test keeps them equal.                                                                                                                  |
| D5  | Consolidate the unit tests again (6)?                                                                                                                                                  | **Yes**, last, and only by merging into tables and moving shapes to golden cases. The last pass shrank the three modules by 8 to 28 %.                                                                                               |

---

## Verification status of this review

**Read**: `action.yaml`, `README.md`, `CLAUDE.md` (the sections on workflows and testing
strategy by grep for the twin rule, the rest as given in context), the previous
`review/target_state.md`, `run.sh`, the launcher, `.gitattributes`, `scripts/test-helper.sh`,
the head and the job list of `ci-action.yaml` (first 110 lines in full, the rest by job name and
`grep`), `nightly.yaml`, the twin tests of `test_workflows.py` by `grep`, and every module of
the package except `_vendor`: `cli`, `report`, `types`, `inputs`, `pyproject`, `requirements`,
`github`, `checks`, `python_versions`, `warning_codes`. **Not read in full**: the test modules
(sizes and function counts only), the other workflows, `generate_docs.py`, `CONTRIBUTING.md`.

**Run**: the full suite (1,041 passed), `ruff check src scripts tests` (pass), `pyright` (0
errors), `bash dev/check_export.sh` (pass, 51 entries), five runs of `run.sh` (~115 ms each),
the archive of `HEAD` extracted into a scratch directory and `run.sh` started from it on a
fixture (works), and four probes of the program on files outside the repository: a dynamic
`requires-python` with `strict` (F1: exit 0, every candidate, no warning), a set-and-dynamic
`optional-dependencies` (warns, as #277 intends), and a file with a normalized extra, markers,
and scoped and unscoped lookups (the documented results). **Not run**: `make check` (so not the
format check, the coverage gate or pre-commit), `make docs-check` (`timeout` is missing on this
machine, the command was not retried), `actionlint`, **any GitHub workflow**: 4.3 and 5.3 are a
design checked only against the local `git archive`, and their size and the three assumptions of
section 7 are **unverified until a GitHub run**. The line counts after the changes are
estimates. None of the proposed code or tests is written; the only change made by this review
is this file (the scratch files are outside the repository).
