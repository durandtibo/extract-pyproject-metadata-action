# Target state of `extract-pyproject-metadata-action`

Review date: 2026-11-10. Reviewed commit: `e92a16a` (`main`). Target release: **`v0.3.0`**
(not tagged yet; the latest tag is `v0.2`). Windows is out of scope, by decision of the
maintainer.

This document **replaces** the previous review (`e66a1f2`, still in the git history). That
round is implemented: the interface is small (5 inputs, 13 outputs), the entry point reads
the environment, the warnings have codes, the requirement tables are read only on demand,
the job summary is gone, the tag is exact. This round judges the result. What is left is
mostly **unfinished cleanup, a few contract gaps, and drift between the code, the CI and
the release text**, not scope.

Two recommendations of the previous review are **withdrawn** because `CLAUDE.md` forbids
them: `concurrency` in the workflows, and deleting
`bot-cancel-stale-queued-runs.yaml` (see 7).

Structure: the **properties** (1), the **measured state** (2), the **findings** (3), the
**target behaviour** (4), the **target architecture** (5), the **tests** (6), **CI, release
and tooling** (7), what is **deliberately not changed** (8), the **migration plan** (9), the
**expected result** (10) and the **decisions** (11).

Breaking changes are accepted, and all of them ship in `v0.3.0`: the action had no `json`
output, no `file-name`, no `python-versions`, no `strict` and no `dependencies` input in any
released version (`v0.2` has `pyproject-path`, `extra-values`, `name`, `version`,
`extras`), so nothing below breaks a caller of `v0.3.0` that did not exist before.

---

## 1. Properties of the action

The design is judged by these properties. They come from `README.md`, `CLAUDE.md` and
`action.yaml`, made explicit, ordered and checkable. When two conflict, the lower number
wins. "How to check" is what a maintainer or a test does to verify the property.

| #   | Property                       | Meaning                                                                                                                                                                                                  | How to check                                                                                                           |
| --- | ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| P1  | **Single purpose**             | Read a `pyproject.toml` and expose the values that drive a workflow: what to build (name, version), what to test (extras, groups, Python versions), what to install (specifiers).                        | Every output answers one of these three questions; a new output must say which.                                        |
| P2  | **Read-only and safe**         | Never runs project code or a build backend. Writes only `$GITHUB_OUTPUT`. A value from the file or from an input can never become shell code, a workflow command or Markdown.                            | `test_output_injection.py`; inputs go through `env:`; no `${{ }}` in a `run:` (a test checks it).                      |
| P3  | **Zero setup**                 | Needs only Python >= 3.11 on `PATH`. No network, no install, no change to the caller's Python, nothing left in the workspace. Same behaviour on Linux and macOS. Windows is not supported.              | `run.sh` has no install branch; `-I -B`; the CI matrix has both systems; a "leaves nothing behind" job.                |
| P4  | **Fast**                       | Adds well under a second to a job.                                                                                                                                                                       | Measured 60 to 90 ms per run (20 ms is the bare interpreter). Keep it under 250 ms on a runner.                        |
| P5  | **Deterministic**              | Same file and inputs give the same outputs. Order is the file order or a documented sort. Nothing depends on the runner but the interpreter.                                                             | Golden files; property tests.                                                                                          |
| P6  | **Reads only what it outputs** | A field that no output needs is neither read nor validated. The requirement tables are read only when `dependencies` is not empty.                                                                       | A broken `description`, or a broken `dependencies` with `dependencies: []`, still works (tested).                      |
| P7  | **Fails loudly, early**        | Invalid input fails with **one** message `<field>: <problem>` and an `::error file=...` annotation. Inputs are validated **completely** before the file is read: a value that cannot match is an error. Never a traceback. | One error format, tested once per field; process tests check exit code and stderr. Finding N3 is a breach of this.    |
| P8  | **Warns, never hides**         | Suspicious but usable input is a warning with a stable **code**. `strict` turns every warning into a failure. No silent fallback.                                                                        | Every code has a row in the README (generated) and a golden or unit case.                                              |
| P9  | **Small surface**              | Few inputs and outputs, each with one meaning and a safe default. Everything else is in the structured `json` output. A released name is never reused for another meaning.                               | 5 inputs, 13 outputs today; the target does not grow them.                                                             |
| P10 | **Single source**              | Each fact (an input, an output, a default, a warning, the supported Python versions) is defined once; docs, workflows and tests are generated from it or checked against it.                             | `make docs`, `make workflows`, `test_contract.py` fail on a diff. Finding N2 is a breach of this.                      |
| P11 | **Easy to maintain**           | Small modules, one-way imports, strict typing, no suppressed lint (`noqa`, `type: ignore`), one task runner used by the CI. One behaviour is asserted by one test.                                       | Layer test; `make check` with no suppression in `src/` and `scripts/`; no two tests with the same assertion.           |
| P12 | **Honest docs**                | The README and the release notes describe the current contract only, with no history of unreleased states, and every example in the README is run by a test.                                             | `test_readme.py`; release notes describe `v0.2` to `v0.3.0` only. Findings N1 and N14 are breaches of this.            |

Changes from the previous review: P3 says "nothing left in the workspace" and names the
job that checks it; P6 is now implemented, not a goal; P7 gains "validated completely";
P9 gains "a released name is never reused"; P10 adds the Python versions; P11 drops the
"tests below 1.5 times the source" ratio (never reachable under the rules of `CLAUDE.md`)
for "one behaviour, one test"; P12 covers the release notes.

---

## 2. Measured state

| Measure                         | Value                                                                                                                        |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Tests                           | 1,054 pass in 10 s, coverage 100 % (488 statements, 102 branches)                                                            |
| Source, without `_vendor/`      | 1,682 lines in 13 modules (`requirements` 314, `pyproject` 292, `github` 202, `inputs` 178, `cli` 163, `types` 142)           |
| Vendored `packaging` 26.3       | 12,716 lines (the whole package, pristine)                                                                                   |
| Tests                           | 6,336 lines, 3.8 times the source (`test_cli` 1,069, `test_requirements` 973, `test_pyproject` 832, `helpers` 421)           |
| Workflows                       | 10 files, 867 lines (`ci-test-local` 298, `ci` 109, `nightly-test-stable` 89, `bot-pin-action` 79)                           |
| Interface                       | 5 inputs, 13 outputs, 9 warning codes, `schema_version` 3                                                                    |
| README                          | 284 lines, tables generated                                                                                                  |
| Golden cases                    | 16 directories in `test-data/` (15 with `expected.json`)                                                                     |
| Run time (macOS, Python 3.14)   | 60 to 90 ms with `-I -B`; 20 ms for `python -c pass`. The import of `cli` is 30 ms, half of it `packaging.tags` through `utils`. |
| `python-versions` computation   | 0.13 ms for 5 candidates (505 `contains` calls): not a cost                                                                  |
| Suppressions in `src/`, `scripts/` | 1 `noqa: C901` (`flatten_group`), 1 `type: ignore` (`extract_metadata.py`), 2 `noqa: E402`, 2 `noqa: S310` (scripts)       |

Probes run on the current code (not on the tests):

| Input                                              | Result today                                                                 | Verdict                    |
| -------------------------------------------------- | ---------------------------------------------------------------------------- | -------------------------- |
| `dependencies: '[""]'`                             | succeeds, key `""`, warning `dependency-not-found`                           | silent fallback (N3)       |
| `dependencies: '["not a name!"]'`                  | succeeds, warning `dependency-not-found`                                     | silent fallback (N3)       |
| `python-candidates: '["03.012","3.12"]'`           | accepted; `python_min` and `python_max` are `"03.012"`                       | not canonical (N3)         |
| a positional argument to the program              | exit 2 and a message that names the variables                                | good, keep (8)             |
| `[project] dependencies = [1]`, `dependencies: []` | succeeds                                                                     | P6 holds                   |

---

## 3. Findings

| ID  | Finding                                                                                                                                                                                                                                                                                                                                                                                                                                                       | Property |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| N1  | **The release notes contradict the code.** `release-notes/v0.3.0.md` ends with "Linux, macOS and Windows runners are supported" (Windows is out of scope, finally). It also lists "Removed" inputs and outputs (`fail-on-missing`, `installer`, `python-matrix`, `description`, ...) that **no released version ever had**: `v0.2` has two inputs and three outputs. A reader of the GitHub release cannot tell what changed for them.                          | P12      |
| N2  | **The Python versions are defined in four places that nothing ties together.** `DEFAULT_PYTHON_CANDIDATES` has `3.11` to `3.15`; the `unit` matrix of `ci.yaml` stops at `3.14`; `ci-test-local.yaml` and the generated `nightly-test-stable.yaml` say "the oldest and the newest supported version" and use `3.14`. 3.15 is released (October 2026) and in the default list, but no job runs on it. `maintenance.yaml` only opens an issue about the list.   | P10, P5  |
| N3  | **Input validation has three gaps.** (a) A `dependencies` entry that is not a valid package name (`""`, `"not a name!"`, `"@project"`) is accepted and reported as `dependency-not-found`, a misleading warning for a typo. (b) `python-candidates` accepts `"03.012"` and returns it as written. (c) `parse_dependencies` validates the scope but not the name.                                                                                              | P7       |
| N4  | **`flatten_group` suppresses the complexity rule.** `requirements.py:47` has `# noqa: C901`, which `CLAUDE.md` forbids ("ignoring an issue is not fixing it"). The function also threads a mutable `budget` list, rescans every group and re-normalizes every name for each entry (O(groups) per `include-group`), carries three `cast`s, and `_gather` repeats the first-spelling logic that `read_group_names` has.                                           | P11      |
| N5  | **`pyproject.py` reads name and version in two steps each, through `object`.** `_required_name` then `_valid_name`, `_required_version` then `_valid_version`; the first returns `(object, bool, warnings)` and the second takes the `bool` back. The types are erased between the two calls and the reader must follow four functions for two fields.                                                                                                         | P11      |
| N6  | **A warning has two types.** `ReportWarning` (dataclass) and `WarningItem` (`TypedDict`) hold the same two strings, and `report.py` converts by hand. (The codes are listed twice, in `WarningCode` and in `WARNING_CODES`, but `test_warnings.py:106` ties them: keep.)                                                                                                                                                                                       | P11      |
| N7  | **Two entry points repeat the same call, and only one is correct.** `scripts/extract_metadata.py` reconfigures stdout and stderr to UTF-8 (with `# type: ignore[union-attr]`, forbidden by `CLAUDE.md`); `__main__.py`, used by `python -m extract_pyproject_metadata` in the README, does not. Both call `main(os.environ, sys.argv[1:])`.                                                                                                                      | P11, P3  |
| N8  | **`schema_version` is `3`, but versions 1 and 2 never shipped.** `json` appears for the first time in `v0.3.0`. The number only has a meaning for a reader who has seen an earlier shape. It sits in the README, the golden files (15), `report.py`, the program docstring and the release notes.                                                                                                                                                              | P12, P9  |
| N9  | **The CI does not use the task runner.** `CLAUDE.md`: "Put `make` targets in the steps rather than duplicating commands". `ci.yaml` runs `pip install --group dev`, `pre-commit`, `pyright` and `pytest` directly, so the flags of the CI and of `make check` can drift (`--cov-report=term-missing` only in the CI).                                                                                                                                          | P11, P10 |
| N10 | **The tests are 3.8 times the source, with duplicated assertions.** `test_cli.py` has 71 tests for a 163-line module: one test per output and per format (`test_main_github_output_python_max`, `_python_min`, `_groups`, `_normalized_name`, `_requires_python`, plus the same in `_json`), which the 16 golden cases and `test_report.py` already assert on whole outputs. `tests/helpers.py` is imported with a private name (`_specifier_error`).              | P11      |
| N11 | **Stale references.** `tests/test_layers.py` talks about an `output` sub-package that no longer exists; `CLAUDE.md` lists the layers without `warning_codes`; `STABLE_REF` is `@v0.2`, so `nightly-test-stable.yaml` runs the old action until the release (a planned step, but not in the checklist as a check).                                                                                                                                              | P12      |

Findings N1 to N11 are verified on the code (probes in 2, line numbers in the text).

### 3.1 What is good and must be kept

- Inputs through `env:`, random output delimiters, escaped annotations (P2).
- One `MetadataError`, one error format, one `main` that turns it into an exit code (P7).
- The golden cases and the real-action job that runs every one of them (P5, P10).
- Generated README tables and README examples that are fixtures (P10, P12).
- One-way layers enforced by `tests/test_layers.py`, strict pyright, the 100 % gate.
- `-I -B` and the vendored, pristine `packaging` (P3, P4); `run.sh` finding `python3` then `python`.
- The usage error on a stray argument (the one footgun of a local run: `python script.py path` would silently read `pyproject.toml`).

---

## 4. Target behaviour

### 4.1 Inputs: same names and defaults, stricter validation (N3)

| Input               | Target validation                                                                                                                                                                         |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pyproject-path`    | Unchanged.                                                                                                                                                                                |
| `extra-values`      | Unchanged: a JSON array of strings (`""` is allowed on purpose: the "no extra" baseline).                                                                                                 |
| `dependencies`      | A JSON array of entries `<name>` or `<name>@<scope>`. **`<name>` must be a valid PEP 508 name** (the rule that `[project].name` already uses). Error: `dependencies: entry 'x y' is not a valid package name`. |
| `python-candidates` | A JSON array of **canonical** `major.minor` strings: `(0\|[1-9][0-9]*)\.(0\|[1-9][0-9]*)` (`3.12`, not `03.012`). Duplicates are removed as today.                                          |
| `strict`            | Unchanged: `true` or `false`, case and spaces ignored.                                                                                                                                    |

The two name rules move into one function used by `pyproject.py` and `inputs.py` (a
`check_package_name` in `checks.py`), so the file and the input cannot disagree.

### 4.2 Outputs: unchanged names, one changed number

The 13 outputs keep their names and values. In `json`, `schema_version` is **`1`** (N8):
`json` is new in `v0.3.0`, so the first published shape is version 1. The rule stays: it
increases only when a key is renamed, removed or changes type. The golden files, the README
and the docstrings say `1`.

### 4.3 Warnings: unchanged

Nine codes, as in the README table (generated from `warning_codes.py`). No code is added: a
suspicious input that the action can still use is a warning, and an input that cannot match
anything is an error (N3).

### 4.4 Errors: unchanged format

`<field>: <problem>`, the file name only in the annotation (or the plain stderr prefix).
New messages: the two of 4.1.

### 4.5 Release notes (N1)

`release-notes/v0.3.0.md` is rewritten as **`v0.2` to `v0.3.0`**: what a caller of `v0.2`
sees. Shape:

1. The pin: `@v0.3.0`; no moving tag.
2. New inputs (`dependencies`, `python-candidates`, `strict`) and new outputs (the 10 that
   `v0.2` did not have), each with its purpose in one line.
3. Changed behaviour of what `v0.2` had: the normalized `extras` (PEP 685, sorted), the
   errors (`<field>: <problem>`), the `::error`/`::warning` annotations with a code.
4. Platforms: Linux and macOS; Windows is not supported.
5. What the action does not do (never runs project code, no dynamic version resolution).

No "Removed" table: nothing that `v0.2` had is removed.

---

## 5. Target architecture

### 5.1 Execution flow (unchanged)

```
action.yaml --env INPUT_*--> scripts/run.sh --exec--> python -I -B scripts/extract_metadata.py
                                                        cli.run()
                                                          cli.main(environ, argv)
                                                            parse_inputs  -> Inputs
                                                            build_report  -> Report
                                                            emit_github_output / print JSON
```

### 5.2 Modules

Same 13 modules, same layers. `warning_codes.py` is added to the layer list of
`CLAUDE.md` (N11).

```
errors, types, checks (+ check_package_name), warning_codes
inputs        parse_inputs (strict names and candidates)
pyproject     load_pyproject, read_project (name and version in one step each)
requirements  collect_requirements, find_requirements, lookup_* (a normalized group table)
python_versions, github
report        build_report
cli           main(environ, argv), run()   (new: the two entry points call run())
```

### 5.3 `flatten_group` without suppression (N4)

Normalize the group table **once**, then expand a normalized table:

```python
def read_groups(data) -> dict[str, list[object]]:
    """key = canonical name; value = the entries of every spelling, in file order."""


@dataclass
class _Expansion:  # one per collect_requirements call
    groups: dict[str, list[object]]
    warnings: dict[ReportWarning, None]  # insertion-ordered set
    budget: int = _MAX_GROUP_EXPANSIONS

    def expand(self, key: str, path: tuple[str, ...] = ()) -> list[str]: ...
    def _include(self, label: str, entry: dict, path) -> list[str]: ...
```

- A dict lookup replaces the rescans; `_gather` loses the first-spelling loop (the
  normalized table has one key per group, in first-spelling order).
- Each method stays under the complexity limit **without** `noqa`: `expand` loops over the
  entries and calls `_include` for a table; `_include` validates and recurses.
- The three `cast`s go: the entry type is `object`, narrowed by `isinstance`.
- Behaviour is unchanged: same limits (100 levels, 10,000 expansions), same cycle,
  unknown-group and type errors, same warning order. The existing tests in
  `test_requirements.py` and `test_limits.py` prove it.

### 5.4 `pyproject.py`: one step per field (N5)

```python
def _read_name(project, dynamic) -> str: ...  # missing, dynamic, not a string, invalid
def _read_version(project, dynamic) -> tuple[str | None, list[ReportWarning]]: ...
```

`_read_version` returns `None` plus the `dynamic-version` warning, or the validated string.
No `object`, no `is_known` flag. Consequence, to put in the PR description: when both
`name` and `version` are wrong, the **name** error is reported first (today: missing name,
missing version, invalid name, invalid version). The file is invalid either way.

### 5.5 One warning type (N6)

Delete `WarningItem`. `Report.warnings` is `list[dict[str, str]]` built with
`dataclasses.asdict`. `ReportWarning`, `WarningCode` and `WARNING_CODES` stay, tied by the
existing test.

### 5.6 One entry point function (N7)

```python
# cli.py
def run() -> int:
    """Entry point of the program: UTF-8 streams, the environment and the arguments."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):  # no type: ignore
            stream.reconfigure(encoding="utf-8")
    return main(os.environ, sys.argv[1:])
```

`scripts/extract_metadata.py` and `__main__.py` become `raise SystemExit(run())` after the
import line. The local run of the README then behaves like the action with a non-UTF-8
locale. `main(environ, arguments)` keeps its signature and the usage error (8).

### 5.7 Rules that stay

Module docstring and `from __future__ import annotations` everywhere; public names in
`__all__` (checked by `test_package.py`); verb prefixes; type hints and docstrings on every
function; collaborators that a test replaces are arguments with a default; `MetadataError`
is the only user-facing exception. **New:** no `noqa` or `type: ignore` in `src/` (the
`# noqa: E402` of `scripts/generate_docs.py` and the `S310` of `scripts/vendor_packaging.py`
are about a launcher `sys.path` and a fixed `https` URL; they stay, each with its reason).

---

## 6. Test target

- Keep the layout and every rule of `CLAUDE.md` (mirror of the package, `tmp_path`,
  `match` on every `raises`, one behaviour per test, whole outputs against a literal).
- **One behaviour, one test (N10).** Delete from `test_cli.py` the per-output tests that
  repeat a golden case or `test_report.py` (`..._github_output_python_max`, `_python_min`,
  `_groups`, `_normalized_name`, `_requires_python`, and their `_json` twins): about 20
  tests. A behaviour that needs a new output check gets a **golden case** (a directory),
  not a Python test. `test_cli.py` keeps what only `main` does: the exit codes, the
  channel (stdout JSON or `GITHUB_OUTPUT`), the annotation format, strict, the usage error.
- **New tests**, each checked to fail before the change:
  - `dependencies: '["not a name!"]'`, `'[""]'`, `'["@project"]'` fail with
    `dependencies: entry ... is not a valid package name`; `'["Numpy_x"]'` still works.
  - `python-candidates: '["03.12"]'`, `'["3.012"]'`, `'["3."]'` fail; `'["3.0","10.11"]'` pass.
  - `flatten_group` through the new expansion: the existing cases plus one that proves the
    lookup is by normalized name when two spellings of a group exist (`Dev` and `dev`).
  - `run()` reconfigures the streams: a process test with `LC_ALL=C PYTHONUTF8=0` and a
    non-ASCII name, through `python -m extract_pyproject_metadata` (an existing process
    test class can take it).
  - `schema_version` is `1` in the golden files and in the README.
  - The workflow tests of 7.1: the Python versions of the matrices come from
    `DEFAULT_PYTHON_CANDIDATES`.
- **Property tests** stay as they are (already on every Python since the previous round).
- Rename `_specifier_error` in `tests/helpers.py` (public name, as `CLAUDE.md` asks for
  shared helpers) and fix the `output` sub-package sentence of `tests/test_layers.py`.
- Target: about 4,500 lines (from 6,336), coverage stays at 100 %.

---

## 7. CI, release and tooling target

The workflows cannot be run locally. Every change below is checked with `actionlint` and
by `tests/integration/test_workflows.py`; the first run on GitHub is the real test, and the
pull request says so.

### 7.1 One list of Python versions (N2)

- `DEFAULT_PYTHON_CANDIDATES` stays the single definition.
- `ci.yaml` `unit` matrix: every candidate, `3.11` to `3.15`. `ci-test-local.yaml` and
  `nightly-test-stable.yaml`: `["3.11", "3.15"]` (the oldest and the newest candidate).
- `test_workflows.py` gets one test: the `unit` matrix equals the default candidates, and
  the `local` matrices equal their minimum and maximum. A new candidate then fails the
  test until the workflows follow, and `maintenance.yaml` keeps telling the maintainer
  that a version is missing.
- If `actions/setup-python` has no 3.15 on a runner, the job fails visibly: that is the
  point of the matrix; the fix is `allow-prereleases` or removing 3.15 from the defaults.

### 7.2 The CI calls the task runner (N9)

| Job            | Target steps                                                                                          |
| -------------- | ----------------------------------------------------------------------------------------------------- |
| `lint`         | setup-python 3.11, `pip install --group dev`, `make lint-python`, pre-commit (without pyright), `make docs-check`, `make workflows-check` |
| `types`        | setup-python 3.11, `pip install --group dev`, `make types`                                            |
| `unit`         | matrix of 7.1, `pip install --group dev`, `make test`                                                 |

The Makefile uses `uv run`; the CI sets `PYTHON_RUN=` on the command line (`make test
PYTHON_RUN=`), so the target is the same command without `uv` (the variable already exists:
`PYTHON_RUN ?= uv run`). Two new targets, `docs-check` and `workflows-check`, run the
scripts with `--check`, which the CI runs today by hand. `.make/` is not edited.

### 7.3 Workflows that stay as they are

`bot-cancel-stale-queued-runs.yaml` (required, and a test checks that no workflow uses
`concurrency`), `nightly.yaml` (the only schedule besides `maintenance.yaml` and the bots),
`maintenance.yaml` (packaging and Python checks), `release.yaml` (no moving tag),
`ci-test-local.yaml` (design unchanged), `bot-pin-action.yaml`, `bot-format-files.yaml`,
`bot-sync-shared-makefile.yaml`, `dependabot.yml`.

### 7.4 Release (N1, N8, N11)

1. The steps of 9 are merged, `make check` and `make docs` pass, `release-notes/v0.3.0.md`
   is rewritten (4.5).
2. The owner pushes `v0.3.0` (the agent never tags).
3. After the release: `STABLE_REF = "durandtibo/extract-pyproject-metadata-action@v0.3.0"`,
   `make workflows`, README and examples already pin `@v0.3.0`.

Add to the checklist in the README (one sentence): the `STABLE_REF` is updated **after** the
tag exists, because the stable job needs the tag to resolve.

---

## 8. Deliberately not changed

| Topic                                         | Why it stays                                                                                                                                                                                                                  |
| --------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The vendored `packaging`, whole               | Importing 30 ms and running 60 to 90 ms meet P4. Half of the import is `packaging.tags` (through `utils`, which `specifiers` needs), so no lazy import avoids it; pruning or patching modules would make `make vendor-packaging` a merge job. |
| `-B` (no bytecode)                            | Costs about 30 ms, keeps the workspace and a cached action directory clean (P3). A job runs the action once.                                                                                                                  |
| The scripts `generate_docs.py`, `vendor_packaging.py` | Small, tested, and the source of P10.                                                                                                                                                                         |
| The usage error on a stray argument           | 15 lines and a footgun removed. Silently ignoring `python script.py path` would read `pyproject.toml` instead.                                                                                                                |
| First match wins, markers ignored             | Evaluating markers needs the target Python and platform. `dependency_requirements` and the `@scope` entries answer "which one".                                                                                              |
| `concurrency` and removing the cancel bot     | `CLAUDE.md` forbids `concurrency`; the bot is the chosen mechanism (the previous review was wrong).                                                                                                                           |
| Windows                                       | Out of scope, by decision. No code, matrix, test or doc.                                                                                                                                                                      |
| The 5 inputs and 13 outputs                   | Each answers P1. Candidate additions were looked at and rejected: `description`, `license`, `urls` (read the file with `tomllib`), a resolved dynamic version (the build backend knows it), a marker-evaluated specifier.    |
| `python-candidates` default `""` in `action.yaml` | The list is defined in the code (P10); the README shows it, generated. Putting it in `action.yaml` would need a second copy for local runs.                                                                               |
| Failure and strict jobs of `ci-test-local.yaml` | A composite step exposes only its outcome, not stderr, so they cannot become golden cases. They check the wiring, which is their job.                                                                                       |
| Publishing to PyPI, a cache, a job summary    | Not what the action is for.                                                                                                                                                                                                   |

---

## 9. Migration plan

One branch and one pull request per step, names as `CLAUDE.md` asks, each leaves `main`
green, each description says what is not changed. **B** marks a change a caller can see.
Steps 2 to 6 can be stacked or parallel (no file in common except tests); 1 is first, 8 is
last.

| Step | Branch                                   | Change                                                                                                                                              | Finding | Breaking                |
| ---- | ---------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ------- | ----------------------- |
| 1    | `docs/release-notes-v0-2-to-v0-3-0`      | Rewrite `release-notes/v0.3.0.md` as 4.5 (Windows line gone, no "Removed" tables). Stale sentences of `test_layers.py` and `CLAUDE.md` (`warning_codes`). | N1, N11 |                         |
| 2    | `refactor/schema-version-1`              | `SCHEMA_VERSION = 1`; golden files (`UPDATE_GOLDEN=1`, review the diff), README, docstring.                                                          | N8      | B (`json`, unreleased)  |
| 3    | `bugfix/validate-input-names`            | `check_package_name`, strict `python-candidates`; tests of 6.                                                                                       | N3      | B (stricter)            |
| 4    | `refactor/group-expansion`               | Normalized group table, `_Expansion`, no `noqa`, no cast.                                                                                           | N4      |                         |
| 5    | `refactor/pyproject-name-version`        | `_read_name`, `_read_version`; the one changed error order is in the description.                                                                    | N5      | B (which error is first) |
| 6    | `refactor/run-entry-point`               | `cli.run()`, two-line entry points, delete `WarningItem`, no `type: ignore`.                                                                         | N6, N7  |                         |
| 7    | `test/one-behaviour-one-test`            | Trim `test_cli.py` and the other duplicates, move per-output checks to golden cases, rename the private helper.                                      | N10     |                         |
| 8    | `ci/python-matrix-and-make`              | 7.1 and 7.2, the workflow tests, `docs-check` and `workflows-check` targets. Not awaited locally: say so.                                            | N2, N9  |                         |
| 9    | `chore/release-v0.3.0`                   | Final check of the notes and the README. The owner pushes the tag; then a small PR sets `STABLE_REF` and runs `make workflows`.                     | N11     |                         |

Steps 1, 4, 5, 6, 7 change nothing a caller can see. Step 3 turns a misleading warning into
an error for a typo; the new behaviour is easier to explain than the old one.

---

## 10. Expected result

| Measure                         | Today (`e92a16a`)                        | Target                                           |
| ------------------------------- | ---------------------------------------- | ------------------------------------------------ |
| Inputs / outputs / warnings     | 5 / 13 / 9                               | 5 / 13 / 9                                       |
| `schema_version`                | 3 (never published)                      | 1                                                |
| Invalid `dependencies` name     | warning `dependency-not-found`           | error `dependencies: entry ... not a valid package name` |
| `python-candidates: ["03.012"]` | accepted as written                      | error                                            |
| Suppressions in `src/`          | 1 `noqa`, 1 `type: ignore`, 3 `cast` in `requirements.py` | none                                |
| Source, without `_vendor/`      | 1,682 lines                              | about 1,560 lines                                |
| Warning types                   | 2 (`ReportWarning`, `WarningItem`)       | 1                                                |
| Entry points that fix the encoding | 1 of 2                                | 2 of 2 (one function)                            |
| Tests                           | 6,336 lines (3.8 times the source)       | about 4,500 lines (2.9 times), 100 % coverage     |
| Python versions in the CI       | 3.11 to 3.14 (3.15 untested)             | every default candidate, checked by a test       |
| CI commands                     | `pip`, `pytest`, `pyright` by hand       | `make` targets                                   |
| Release notes                   | Windows supported; removes what never shipped | `v0.2` to `v0.3.0`, Linux and macOS         |
| Run time                        | 60 to 90 ms                              | unchanged                                        |
| Caller pin                      | `@v0.3.0`                                | `@v0.3.0`                                        |

---

## 11. Decisions to take

Each has a recommendation; the plan assumes they are accepted.

1. **Reset `schema_version` to `1`** (step 2). _Recommended:_ yes. No caller has seen `1`,
   `2` or `3`; starting at `3` tells a reader about a history that does not exist.
   _Alternative:_ keep `3`.
2. **Make an invalid dependency name or a non-canonical candidate an error** (step 3).
   _Recommended:_ yes (P7: a value that can never match is not a "not found"). Cost: a
   workflow that passes `"my pkg"` fails instead of getting `null`.
3. **Run the unit tests on 3.15 and name 3.15 as "the newest"** (step 8). _Recommended:_
   yes; the default list says 3.15 is supported, so a job must run it.
   _Alternative:_ drop 3.15 from the defaults until a job exists.
4. **CI through `make`** (step 8). _Recommended:_ yes (`CLAUDE.md` asks for it).
   _Cost:_ the `PYTHON_RUN=` override on the command line in three jobs.
5. **Trim the redundant tests** (step 7). _Recommended:_ yes, but only tests whose whole
   assertion is covered elsewhere (check with a coverage run before and after: the gate
   must stay at 100 % and no behaviour may lose its only test).
