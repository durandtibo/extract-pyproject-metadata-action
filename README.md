# extract-pyproject-metadata-action

A composite GitHub Action that reads the project name, version,
optional-dependency extra names and the version specifiers of selected
dependencies directly from a `pyproject.toml` file. Reading these values
straight from `[project]`, `[project.optional-dependencies]` and
`[dependency-groups]` keeps downstream workflows (build, test matrices, publish
steps, ...) from drifting out of sync with what `pip install` actually
installs.

Requires the repository to already be checked out and a **Python 3.11 or
later** interpreter (`python3`, or the one named by the `python-executable` input) available on `PATH`, for example set up with
`actions/setup-python`; the action fails with a clear message otherwise. If the
`packaging` package is missing, the action installs it in a
private virtual environment under `$RUNNER_TEMP` (removed at the end of the
step), with the versions listed in
`scripts/requirements.txt` (`packaging>=23.0,<27`; a `packaging` that is already
installed is used as it is, whatever its version). It never modifies the Python
environment of the caller.

That installation needs a package index: PyPI by default, or the one that `pip`
is configured to use (`PIP_INDEX_URL`, `PIP_EXTRA_INDEX_URL`, `pip.conf`, ...). On
a runner without network access, or when you prefer not to download anything
in the job, install `packaging` in the Python of the job beforehand (for
example `python -m pip install packaging`, from a mirror or a cache): the
action then uses it as it is and does not touch the network.

> [!NOTE]
> The action supports **Linux and macOS** runners only. **Windows runners are
> not supported**: the step expects `python3` and a POSIX `bash`, and fails
> with an explicit error on them.

## Usage

```yaml
- uses: actions/checkout@v7

- id: metadata
  uses: durandtibo/extract-pyproject-metadata-action@v0.1
  with:
    pyproject-path: pyproject.toml
    extra-values: '[""]'
    dependencies: '["numpy", "invoke-tasklib"]'

- run: |
    echo "name=$NAME"
    echo "version=$VERSION"
    echo "extras=$EXTRAS"
    echo "dependency-specifiers=$DEPENDENCY_SPECIFIERS"
  env:
    NAME: ${{ steps.metadata.outputs.name }}
    VERSION: ${{ steps.metadata.outputs.version }}
    EXTRAS: ${{ steps.metadata.outputs.extras }}
    DEPENDENCY_SPECIFIERS: ${{ steps.metadata.outputs.dependency-specifiers }}
```

Outputs are passed to the shell through `env:` instead of being interpolated in
the script, so a value from `pyproject.toml` can never be interpreted as shell
code. The `dependencies` input and `dependency-specifiers` output need a
release that includes them (later than `v0.2`).

Given a `pyproject.toml` such as:

```toml
[project]
name = "coola"
version = "1.2.3"
dependencies = ["tqdm>=4"]

[project.optional-dependencies]
numpy = ["numpy>=1.20,<3"]
pandas = ["pandas"]
```

the example above outputs:

- `name`: `coola`
- `version`: `1.2.3`
- `extras`: `["","numpy","pandas"]`
- `dependency-specifiers`: `{"numpy":"<3,>=1.20","invoke-tasklib":null}`

The `extras` output is a JSON array, so it can drive a job matrix:

```yaml
jobs:
  metadata:
    runs-on: ubuntu-latest
    outputs:
      extras: ${{ steps.metadata.outputs.extras }}
    steps:
      - uses: actions/checkout@v7
      - id: metadata
        uses: durandtibo/extract-pyproject-metadata-action@v0.1

  test:
    needs: metadata
    runs-on: ubuntu-latest
    strategy:
      matrix:
        extra: ${{ fromJSON(needs.metadata.outputs.extras) }}
    steps:
      - run: echo "testing extra $EXTRA"
        env:
          EXTRA: ${{ matrix.extra }}
```

## Inputs

| Name                      | Description                                                                                                                                                                                                                                                                                            | Required | Default                                |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------- | -------------------------------------- |
| `pyproject-path`          | Path to `pyproject.toml`.                                                                                                                                                                                                                                                                              | No       | `pyproject.toml`                       |
| `extra-values`            | JSON array of additional values to prepend to the extras read from `pyproject.toml`, for callers that need a non-package value too (e.g. `[""]` for a "no extra" baseline, or `["all"]`).                                                                                                              | No       | `[]`                                   |
| `dependencies`            | JSON array of package names whose version specifier is looked up in `[project].dependencies`, `[project.optional-dependencies]`, then `[dependency-groups]` (including `include-group`); first match wins (also between requirements with different environment markers), names compared per PEP 503.  | No       | `[]`                                   |
| `fail-on-dynamic-version` | `true` to fail when `version` is listed in `[project].dynamic`, instead of giving an empty `version` output with a warning. Use it in release or publish jobs that need a static version. Must be `true` or `false` (case and surrounding spaces are ignored).                                         | No       | `false`                                |
| `python-candidates`       | JSON array of `major.minor` Python versions to choose from for the `python-versions` output (e.g. `["3.11","3.12"]`). Each must be of the form `3.12`; duplicates are removed.                                                                                                                         | No       | `["3.10","3.11","3.12","3.13","3.14"]` |
| `fail-on-missing`         | `true` to fail when a package listed in `dependencies` is not found, instead of reporting it as `null` in `dependency-specifiers`. Must be `true` or `false` (case and surrounding spaces are ignored).                                                                                                | No       | `false`                                |
| `strict`                  | `true` to fail when there is any warning (listed in the error), instead of only reporting it. Use it in CI to keep a `pyproject.toml` free of suspicious input. Must be `true` or `false` (case and surrounding spaces are ignored).                                                                   | No       | `false`                                |
| `python-executable`       | Python interpreter that runs the action: a command found on `PATH` or a path to an executable (Python 3.11 or later, e.g. `python3.12` or `/opt/python/bin/python`), for runners where `python3` is not the interpreter to use. The private virtual environment, if one is needed, is created with it. | No       | `python3`                              |
| `step-summary`            | `true` to also write the outputs and the warnings to the job summary of the workflow run (a table with one row per output). Must be `true` or `false` (case and surrounding spaces are ignored).                                                                                                       | No       | `false`                                |

## Outputs

| Name                      | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`                    | Project name, as declared in `[project].name`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `normalized-name`         | Project name normalized per PEP 503: lowercase, with each run of `-`, `_` and `.` replaced by a single `-` (e.g. `My_Package.Name` gives `my-package-name`). Use it for the names of wheel/sdist files and of packages on an index.                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `version`                 | Project version, as declared in `[project].version`. Empty if `version` is listed in `[project].dynamic` (a warning is emitted).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `normalized-version`      | Project version in the canonical form of [PEP 440](https://peps.python.org/pep-0440/#normalization) (e.g. `1.0rc1` for `1.0-RC1`, `1.0.post1` for `1.0-1`, `2020.1.5` for `2020.01.05`). Use it for the names of wheel/sdist files and for tags, which are built from this form. Empty if `version` is listed in `[project].dynamic`.                                                                                                                                                                                                                                                                                                                                                   |
| `description`             | Project description, as declared in `[project].description`, as written. Empty if it is not declared (also if it is listed in `[project].dynamic`). It may contain line breaks: pass it to the shell through `env:`. It is not shown in the `📦` log line.                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `readme`                  | Path of the readme file, from `[project].readme` (a string, or the `file` of a table), as written (e.g. `README.md`). Empty if it is not declared, if the readme is inline (`text`) or if it is listed in `[project].dynamic`. The action does not read the file. Not in the `📦` log line.                                                                                                                                                                                                                                                                                                                                                                                             |
| `license`                 | License, from `[project].license`: the SPDX expression ([PEP 639](https://peps.python.org/pep-0639/)) or the `text` of the table of PEP 621, as written (e.g. `MIT`, `Apache-2.0 OR MIT`). Empty if it is not declared, if it is a `file` or if it is listed in `[project].dynamic`. The action does not validate the expression. Not in the `📦` log line.                                                                                                                                                                                                                                                                                                                             |
| `license-files`           | JSON array of the patterns of `[project].license-files` ([PEP 639](https://peps.python.org/pep-0639/)), as written and in order (e.g. `["LICENSE","licenses/*.txt"]`). `[]` if it is not declared (also if it is listed in `[project].dynamic`). The patterns are not expanded: the action does not look at the files. Not in the `📦` log line.                                                                                                                                                                                                                                                                                                                                        |
| `authors`                 | JSON array of the authors of `[project].authors`, in order, each an object with the `name` and the `email` that the author has (e.g. `[{"name":"Ada","email":"ada@example.com"},{"name":"Bob"}]`); other keys are ignored. `[]` if there is none or if `authors` is listed in `[project].dynamic`. Not in the `📦` log line.                                                                                                                                                                                                                                                                                                                                                            |
| `urls`                    | JSON object mapping each label of `[project.urls]` to its URL, as written and in the order of the file (e.g. `{"Homepage":"https://example.com"}`). `{}` if there is none. Look a label up in a workflow with `fromJSON(...)["Homepage"]`. Not in the `📦` log line.                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `requires-python`         | Python version specifier, as declared in `[project].requires-python` (e.g. `>=3.10,<4`), as written. Empty if it is not declared (also if it is listed in `[project].dynamic`).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `python-versions`         | JSON array of the `python-candidates` that `requires-python` allows, in the order of the candidates (e.g. `["3.10","3.11"]` for `>=3.10,<3.12`), to drive a job matrix. All the candidates if `requires-python` is not declared. A minor version is allowed if some release of it satisfies the specifier (checked on `X.Y.0` to `X.Y.99` and on a very late patch release), so `>=3.10.2` allows `3.10` and `==3.12.3` allows `3.12` only (a patch number of 100 or more, such as `==3.12.150`, matches no release). `[]` (with a warning) if `requires-python` is not a valid specifier.                                                                                              |
| `python-min`              | The lowest of the `python-versions`, compared as numbers (`3.9` is lower than `3.10`), e.g. `3.10` for `>=3.10,<3.12`. Empty if `python-versions` is empty. Use it for the jobs that need a single Python version (lint, build, docs).                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `python-max`              | The highest of the `python-versions`, compared as numbers (`3.10` is higher than `3.9`), e.g. `3.11` for `>=3.10,<3.12`. Empty if `python-versions` is empty. Use it for the jobs that need the newest supported Python (for example a type checker or a latest-Python job).                                                                                                                                                                                                                                                                                                                                                                                                            |
| `python-matrix`           | JSON object `{"python-version": [...]}` made of the `python-versions`, to use as a job matrix as it is with `fromJSON` (see [Python version matrix](#python-version-matrix)). `{"python-version":[]}` if `python-versions` is empty: GitHub fails a job whose matrix has no value, so a workflow may check `python-versions` first. Not in the `📦` log line.                                                                                                                                                                                                                                                                                                                           |
| `extras`                  | JSON array of extra names, sorted by normalized name, with `extra-values` prepended. Duplicates are removed (the first occurrence is kept); names are compared per PEP 685, so `Foo_Bar` and `foo-bar` are the same extra.                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `groups`                  | JSON array of the group names of `[dependency-groups]` (PEP 735), sorted by normalized name, without duplicates. `[]` if there is none.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `project-dependencies`    | JSON object mapping each package of `[project].dependencies` to its specifier, with the name as written in its first requirement and in the order of the file (e.g. `{"numpy": "<3,>=1.20", "Foo_Bar": ""}`), without having to list the names in `dependencies`. Extras and dependency groups are not read. The first requirement of a package wins, whatever its environment marker, as for `dependency-specifiers`. `{}` if there is none. A warning is emitted if a requirement string is invalid and ignored, if a package has different specifiers for the same environment marker, or if `dependencies` is listed in `[project].dynamic` without a static value.                 |
| `dependency-specifiers`   | JSON object mapping each requested package to its specifier (e.g. `{"invoke-tasklib": ">=0.0.8,<1.0.0"}`). `null` if not found (or a failure, with `fail-on-missing`), `""` if the requirement has no specifier. A warning is emitted if different specifiers are found for requirements with the same environment marker, if a requirement string in the file is invalid and ignored, if `include-group` entries form a cycle, if an `include-group` names a group that does not exist, or if `dependencies` or `optional-dependencies` is listed in `[project].dynamic` without a static value (the build backend computes it, so the action cannot read it and finds nothing in it). |
| `dependency-requirements` | JSON object mapping each package listed in `dependencies` to the array of **all** its requirements, in search order, each an object with its `specifier` and its environment `marker` (both `""` if it has none; e.g. `{"numpy":[{"specifier":">=1.20","marker":"python_version < \"3.12\""},{"specifier":">=1.26","marker":"python_version >= \"3.12\""}]}`). `[]` for a package that is not found. Unlike `dependency-specifiers`, nothing is dropped, so a workflow can pick the requirement that applies to its Python version (see [Environment markers](#environment-markers)). Not in the `📦` log line.                                                                         |

Warnings are emitted as `::warning file=<pyproject-path>::<message>` workflow
commands, so GitHub attaches them to the file that is read (`pyproject-path` is
used as given). Failures (see [Failure modes](#failure-modes)) are emitted the
same way, as `::error file=<pyproject-path>::<message>`, so they show as an
annotation of the run and not only in the log of the step.

A field that is set in `[project]` and also listed in `[project].dynamic` (for
example `version = "1.2.3"` with `dynamic = ["version"]`) is invalid per
[PEP 621](https://peps.python.org/pep-0621/#dynamic): the action warns and reads
the static value. With `strict: "true"` this warning fails the step.

The step also prints a one-line `📦` summary of the outputs in the log, with line
breaks in the values escaped, to help debugging a workflow. The line shows
`name`, `version`, `requires-python`, `python-versions`, `python-min`, `python-max`, `extras`,
`groups`, `project-dependencies`, `dependency-specifiers`; it leaves out
`normalized-name` and `normalized-version` (derived from `name` and `version`),
`python-matrix` (derived from `python-versions`), `description` (it may be long),
`readme`, `license`, `license-files`, `authors`, `urls` and `dependency-requirements`. With
`step-summary: "true"`, the outputs and the warnings are also written to the job
summary of the run as a Markdown table (values are escaped, so a value from
`pyproject.toml` cannot add Markdown or HTML to the page). When the step fails,
the error message is written to the job summary instead, so the reason is visible
on the summary page of the run and not only in the log of the step.

### Python version matrix

`python-versions` can drive a test matrix that follows `requires-python`:

```yaml
jobs:
  metadata:
    runs-on: ubuntu-latest
    outputs:
      python-versions: ${{ steps.metadata.outputs.python-versions }}
    steps:
      - uses: actions/checkout@v7
      - id: metadata
        uses: durandtibo/extract-pyproject-metadata-action@v0.1
        with:
          python-candidates: '["3.10","3.11","3.12","3.13","3.14","3.15"]'

  test:
    needs: metadata
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ${{ fromJSON(needs.metadata.outputs.python-versions) }}
    steps:
      - uses: actions/setup-python@v7
        with:
          python-version: ${{ matrix.python-version }}
```

The list of candidates is yours to maintain: the action does not know which
Python versions exist.

`python-matrix` is the same list as an object, so the matrix of the example can
also be written without the `python-version` key of your own:

```yaml
test:
  needs: metadata
  runs-on: ubuntu-latest
  strategy:
    matrix: ${{ fromJSON(needs.metadata.outputs.python-matrix) }}
  steps:
    - uses: actions/setup-python@v7
      with:
        python-version: ${{ matrix.python-version }}
```

## Environment markers

The action never evaluates environment markers: the runner's Python and
platform are not taken into account. When a package appears in several
requirements, the **first** one wins, in this search order:
`[project].dependencies`, then `[project.optional-dependencies]` (in file
order), then `[dependency-groups]` (in file order, `include-group` expanded in
place). The marker itself is not part of the `dependency-specifiers` output; the
`dependency-requirements` output lists every requirement with its marker.

```toml
[project]
dependencies = [
  "numpy>=1.20; python_version < '3.12'",
  "numpy>=1.26; python_version >= '3.12'",
]
```

With `dependencies: '["numpy"]'`, `dependency-specifiers` is
`{"numpy":">=1.20"}` on every runner, including a Python 3.12 one. Requirements
with different markers are expected to differ, so they do not trigger a
warning; two requirements with the same marker and different specifiers do. If
a workflow needs the specifier that applies to a given Python version, read it
from `dependency-requirements`, which lists all the requirements of a package
with their markers (the workflow chooses the one that applies; the action still
does not evaluate the markers), or declare the package once without markers.

With the file above and `dependencies: '["numpy"]'`, `dependency-requirements`
is:

```json
{
  "numpy": [
    { "specifier": ">=1.20", "marker": "python_version < \"3.12\"" },
    { "specifier": ">=1.26", "marker": "python_version >= \"3.12\"" }
  ]
}
```

## Failure modes

The action's step fails (non-zero exit) when:

- It runs on a Windows runner (`RUNNER_OS` is `Windows`), which is not supported.
- The Python interpreter (`python3`, or `python-executable`) is older than 3.11, missing or cannot be run, or `packaging` is missing
  and cannot be installed (for example, no access to a package index).
- `pyproject-path` does not point to an existing file.
- The file is not valid TOML, is not UTF-8 or cannot be read (for example for lack of
  permission).
- The outputs (`$GITHUB_OUTPUT`) or, with `step-summary`, the job summary
  (`$GITHUB_STEP_SUMMARY`) cannot be written. These used to end with a Python
  traceback, like the unreadable file.
- `[project]` is missing the required `name` key, or the `version` key when `version` is not listed in `[project].dynamic`.
- `[project].dynamic` is not an array of strings (for example `dynamic = [1]`).
- `name` is listed in `[project].dynamic` and not set in `[project]` (PEP 621 requires
  a static name; the error says so instead of reporting a missing key).
- `[project]` is not a table, `name` is not a non-empty string, or `version` is
  not a string (for example `version = 1.0` is a TOML float; write
  `version = "1.0"`).
- `[project].name` is not a valid project name: it may only contain letters,
  digits, `-`, `_` and `.`, and must start and end with a letter or a digit
  ([PEP 508](https://peps.python.org/pep-0508/#names)), for example `my pkg`.
- `[project].version` is not a valid
  [PEP 440](https://peps.python.org/pep-0440/) version (for example `latest`).
- `[project].description` or `[project].requires-python` is not a string.
- `[project].readme` is neither a string nor a table, or the `file` of the table is not
  a string.
- `[project].license` is neither a string nor a table, or the `text` or the `file` of
  the table is not a string.
- `[project].license-files` is not an array of strings.
- `[project].authors` is not an array of tables, or the `name` or the `email` of an
  author is not a string.
- `[project.urls]` is not a table, or a URL is not a string.
- `python-candidates` is not valid JSON, is not a JSON array of strings, or
  contains a string that is not of the form `major.minor`.
- `[project.optional-dependencies]` is not a table.
- `[dependency-groups]` is not a table.
- `[project].dependencies` or a value of `[project.optional-dependencies]` or
  `[dependency-groups]` is not an array, `[dependency-groups]` is not a table,
  or an `include-group` value is not a string.
- An entry of a `[dependency-groups]` group is neither a string nor a table whose
  only key is `include-group` (for example a typo such as
  `{include_group = "lint"}`). It used to be ignored silently.
- A requirement of `[project].dependencies` or of a `[project.optional-dependencies]`
  extra is not a string (for example `dependencies = ["numpy", 1]`). It used to be
  ignored silently.
- `extra-values` is not valid JSON, or is not a JSON array of strings.
- `dependencies` is not a JSON array of strings.
- `fail-on-dynamic-version` is not `true` or `false`, or is `true` and
  `version` is listed in `[project].dynamic`.
- `strict` is not `true` or `false`, or is `true` and there is a warning (the
  error lists them; no output is written).
- `step-summary` is not `true` or `false`.
- `fail-on-missing` is not `true` or `false`, or is `true` and a package listed in
  `dependencies` is not found (the error says when `[project].dependencies` or
  `[project].optional-dependencies` is dynamic and so cannot be read).

## Development

The logic is in `scripts/extract_metadata.py`, started by `scripts/run.sh`
(which installs the requirements in a private virtual environment when the
interpreter lacks them); `action.yaml` only wires inputs and outputs. Use a virtual environment:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/pytest -q --cov
```

CI fails if the unit tests do not cover 100% of `scripts/extract_metadata.py`.

Run on its own, without `--github-output`, the script prints one JSON object with
the outputs (the names use `_` instead of `-`, and `python-matrix` is not in it)
and the `warnings`. Its `schema_version` key (currently `1`) increases when a key
is renamed, removed or changes type, not when a key is added, so that a tool that
reads the object can check it.

Formatting and linting of the non-Python files (YAML, Markdown, shell, TOML,
Makefiles) go through the `Makefile`; run `make help` to list the targets, for
example `make format` and `make lint`.

The integration workflows (`.github/workflows/ci-test-local.yaml` and
`nightly-test-stable.yaml`) can only run on GitHub.
