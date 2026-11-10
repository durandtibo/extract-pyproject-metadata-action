# extract-pyproject-metadata-action

A composite GitHub Action that reads the project name, version,
optional-dependency extra names and the version specifiers of selected
dependencies directly from a `pyproject.toml` file. Reading these values
straight from `[project]`, `[project.optional-dependencies]` and
`[dependency-groups]` keeps downstream workflows (build, test matrices, publish
steps, ...) from drifting out of sync with what `pip install` actually
installs.

Requires the repository to already be checked out and a **Python 3.11 or
later** interpreter (`python3`, or `python`) on `PATH`, for example set up with
`actions/setup-python`; the action fails with a clear message otherwise.
Nothing is installed and nothing is downloaded: the only dependency,
[`packaging`](https://github.com/pypa/packaging), is vendored in the action
(`src/extract_pyproject_metadata/_vendor/`), so the result does not depend on the
`packaging` of the runner. The action runs on **Linux, macOS and Windows**
runners (the step uses `bash`, which is Git Bash on Windows). It does not modify the
Python environment of the caller and writes no bytecode.

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

| Name                      | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | Required | Default                                |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------- | -------------------------------------- |
| `pyproject-path`          | Path to `pyproject.toml`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | No       | `pyproject.toml`                       |
| `extra-values`            | JSON array of additional values to prepend to the extras read from `pyproject.toml`, for callers that need a non-package value too (e.g. `[""]` for a "no extra" baseline, or `["all"]`).                                                                                                                                                                                                                                                                                                                                            | No       | `[]`                                   |
| `dependencies`            | JSON array of package names whose version specifier is looked up in `[project].dependencies`, `[project.optional-dependencies]`, then `[dependency-groups]` (including `include-group`); first match wins (also between requirements with different environment markers), names compared per PEP 503. A name followed by `@project`, `@extra:<name>` or `@group:<name>` is looked up in `[project].dependencies`, that extra or that group only (see [Looking up a dependency in one place](#looking-up-a-dependency-in-one-place)). | No       | `[]`                                   |
| `python-candidates`       | JSON array of `major.minor` Python versions to choose from for the `python-versions` output (e.g. `["3.11","3.12"]`). Each must be of the form `3.12`; duplicates are removed.                                                                                                                                                                                                                                                                                                                                                       | No       | `["3.11","3.12","3.13","3.14","3.15"]` |
| `strict`                  | `true` to fail when there is any warning (listed in the error), instead of only reporting it, for example a dynamic `version` or a package of `dependencies` that is not found. Use it in release jobs that need a static version. Use it in CI to keep a `pyproject.toml` free of suspicious input.                                                                                                                                                                                                                                                                                                                                                                      | No       | `false`                                |

`strict` is a boolean input: the
value must be `true` or `false`, the case and the surrounding spaces are ignored,
and any other value fails the step.

## Outputs

| Name                      | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`                    | Project name, as declared in `[project].name`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `normalized-name`         | Project name normalized per [PEP 503](https://peps.python.org/pep-0503/#normalized-names): lowercase, with each run of `-`, `_` and `.` replaced by a single `-` (e.g. `My_Package.Name` gives `my-package-name`). Use it for the URL of the project on an index and for `pip install`. It is **not** the form of the file names of wheels and sdists: use `file-name` for them. |
| `file-name`               | Project name as it is written in the file names of wheels and sdists: the normalized name with `_` instead of `-` (e.g. `My_Package.Name` gives `my_package_name`, as in `my_package_name-1.0-py3-none-any.whl`). |
| `version`                 | Project version, as declared in `[project].version`. Empty if `version` is listed in `[project].dynamic` (a warning is emitted).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `normalized-version`      | Project version in the canonical form of [PEP 440](https://peps.python.org/pep-0440/#normalization) (e.g. `1.0rc1` for `1.0-RC1`, `1.0.post1` for `1.0-1`, `2020.1.5` for `2020.01.05`). Use it for the version part of the file names of wheels and sdists, and for tags, which are built from this form. Empty if `version` is listed in `[project].dynamic`.                                                                                                                                                                                                                                                                                                                                                   |
| `requires-python`         | Python version specifier, as declared in `[project].requires-python` (e.g. `>=3.10,<4`), as written. Empty if it is not declared (also if it is listed in `[project].dynamic`).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `python-versions`         | JSON array of the `python-candidates` that `requires-python` allows, in the order of the candidates (e.g. `["3.10","3.11"]` for `>=3.10,<3.12`), to drive a job matrix. All the candidates if `requires-python` is not declared. A minor version is allowed if some release of it satisfies the specifier (checked on `X.Y.0` to `X.Y.99` and on a very late patch release), so `>=3.10.2` allows `3.10` and `==3.12.3` allows `3.12` only (a patch number of 100 or more, such as `==3.12.150`, matches no release). `[]` (with a warning) if `requires-python` is not a valid specifier, or if none of the candidates satisfies it (for example `>=4`).                               |
| `python-min`              | The lowest of the `python-versions`, compared as numbers (`3.9` is lower than `3.10`), e.g. `3.10` for `>=3.10,<3.12`. Empty if `python-versions` is empty. Use it for the jobs that need a single Python version (lint, build, docs).                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `python-max`              | The highest of the `python-versions`, compared as numbers (`3.10` is higher than `3.9`), e.g. `3.11` for `>=3.10,<3.12`. Empty if `python-versions` is empty. Use it for the jobs that need the newest supported Python (for example a type checker or a latest-Python job).                                                                                                                                                                                                                                                                                                                                                                                                            |
| `extras`                  | JSON array of extra names, sorted by normalized name, with `extra-values` prepended. Duplicates are removed (the first occurrence is kept); names are compared per PEP 685, so `Foo_Bar` and `foo-bar` are the same extra.                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `groups`                  | JSON array of the group names of `[dependency-groups]` (PEP 735), sorted by normalized name, without duplicates. `[]` if there is none.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `dependency-specifiers`   | JSON object mapping each requested package to its specifier (e.g. `{"invoke-tasklib": ">=0.0.8,<1.0.0"}`). `null` if not found (with a warning), `""` if the requirement has no specifier. A warning is emitted if a requirement string in the file is invalid and ignored, if `include-group` entries form a cycle, if an `include-group` names a group that does not exist, or if `dependencies` or `optional-dependencies` is listed in `[project].dynamic` without a static value (the build backend computes it, so the action cannot read it and finds nothing in it). |
| `json`                    | The whole result in one value: a JSON object with the keys of the script output (the names of the other outputs with `_` instead of `-`: `normalized_name`, `python_versions`, ...), the `warnings` (an array of messages) and the `schema_version` (see [Development](#development)). Unlike the other outputs, arrays and objects are values, not strings, so `fromJSON(steps.metadata.outputs.json).extras` is the array of extras. Pass it to another job with one job output, or to a script. The `📦` log line leaves it out. `python-matrix` is not in it.                                                                                       |

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
`groups`, `dependency-specifiers`; the other outputs are derived from these, or are in `json`
only.

When there are warnings, the job summary of the run gets a short list of them (values are
escaped, so a value from `pyproject.toml` cannot add Markdown or HTML to the page), so a
warning (and the failure of `strict`, which lists them) shows on the summary page of the run
and not only in the log. When the step fails, the error message is written to the job summary
instead. Nothing is written otherwise.

### The whole result in one output

The `json` output holds every value, so one job output is enough to hand the
result to another job:

```yaml
jobs:
  metadata:
    runs-on: ubuntu-latest
    outputs:
      json: ${{ steps.metadata.outputs.json }}
    steps:
      - uses: actions/checkout@v7
      - id: metadata
        uses: durandtibo/extract-pyproject-metadata-action@v0.1

  build:
    needs: metadata
    runs-on: ubuntu-latest
    steps:
      - run: echo "building $NAME $VERSION"
        env:
          NAME: ${{ fromJSON(needs.metadata.outputs.json).name }}
          VERSION: ${{ fromJSON(needs.metadata.outputs.json).version }}
```

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
          python-candidates: '["3.11","3.12","3.13","3.14","3.15"]'

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

## Dynamic version

When `version` is listed in `[project].dynamic`, the `version` and `normalized-version`
outputs are empty, with a warning, because the build backend computes the version
(`setuptools-scm`, `hatch-vcs`, a file, ...). The action never reads it from the files of
the backend. A release job that needs a version uses `strict: "true"` so that a dynamic
version fails the step, and asks the backend for it (`python -m build`, `hatch version`,
`python -m setuptools_scm`, ...).

## Looking up a dependency in one place

By default a package is searched in `[project].dependencies`, then in every extra, then
in every dependency group, and the first requirement wins. To read the requirement of one place
only, follow the name with `@` and the place: `@project` for `[project].dependencies`,
`@extra:<name>` for an extra of `[project.optional-dependencies]` or `@group:<name>` for a
dependency group (the requirements it adds with `include-group` are included). Package
names, extra names and group names are compared per PEP 503, and a package name cannot contain `@`,
so the entry is not ambiguous. An extra and a group can have the same name, which is why the kind is
part of the scope.

The entries of `dependencies` (each is a JSON string of the array) are:

| Entry              | Looked up in                                                                       | Key in the outputs |
| ------------------ | ---------------------------------------------------------------------------------- | ------------------ |
| `numpy`            | `[project].dependencies`, then every extra, then every group: the first match wins | `numpy`            |
| `numpy@project`    | `[project].dependencies` only                                                      | `numpy@project`    |
| `numpy@extra:fast` | the extra `fast` of `[project.optional-dependencies]` only                         | `numpy@extra:fast` |
| `numpy@group:dev`  | the group `dev` of `[dependency-groups]` only, with the groups it includes         | `numpy@group:dev`  |

Anything else after the `@` (`numpy@dev`, `numpy@extra:`) fails the step. The key of
`dependency-specifiers` (and of `dependency_requirements` in `json`) is always the entry as written, so
`numpy` and `numpy@project` are two keys, even when they find the same requirement.

### A package declared in several places

The same package is often declared in more than one place (a runtime range in
`[project].dependencies`, a pin in a group). With the plain name, `dependency-specifiers`
reports the **first** requirement of the search order above, without a warning, since the
places legitimately differ. A scoped entry only looks at its own place. To see every
requirement of the package, in search order, with its marker and the place that declares it
(`source`: `project`, `extra:<name>` or `group:<name>`), read `dependency_requirements` in
the `json` output (`fromJSON(...json).dependency_requirements`).

```toml
[project]
dependencies = ["numpy>=1.20"]

[project.optional-dependencies]
fast = ["numpy>=2"]

[dependency-groups]
dev = ["numpy>=1.26", "pytest"]
```

With `dependencies: '["numpy", "numpy@extra:fast", "pytest@group:dev", "pytest@project"]'`,
`dependency-specifiers` is
`{"numpy":">=1.20","numpy@extra:fast":">=2","pytest@group:dev":"","pytest@project":null}`:
the keys of `dependency-specifiers` and `dependency_requirements` are the entries as
written. The plain `numpy` is the first of the three requirements (`>=1.20`, `>=2`, `>=1.26`),
the scoped entries are explicit. A package that the place does not declare, or a place that does not exist, gives `null`
(and an empty array in `dependency_requirements`) with a warning (so `strict` fails the step).

## Environment markers

The action never evaluates environment markers: the runner's Python and
platform are not taken into account. When a package appears in several
requirements, the **first** one wins, in this search order:
`[project].dependencies`, then `[project.optional-dependencies]` (in file
order), then `[dependency-groups]` (in file order, `include-group` expanded in
place). The marker itself is not part of the `dependency-specifiers` output; the
`dependency_requirements` of the `json` output lists every requirement with its marker.

```toml
[project]
dependencies = [
  "numpy>=1.20; python_version < '3.12'",
  "numpy>=1.26; python_version >= '3.12'",
]
```

With `dependencies: '["numpy"]'`, `dependency-specifiers` is
`{"numpy":">=1.20"}` on every runner, including a Python 3.12 one. Requirements
with different markers are expected to differ. If
a workflow needs the specifier that applies to a given Python version, read it
from `dependency_requirements` in `json`, which lists all the requirements of a package
with their markers (the workflow chooses the one that applies; the action still
does not evaluate the markers), or declare the package once without markers.

With the file above and `dependencies: '["numpy"]'`, `dependency_requirements`
is:

```json
{
  "numpy": [
    { "specifier": ">=1.20", "marker": "python_version < \"3.12\"" },
    { "specifier": ">=1.26", "marker": "python_version >= \"3.12\"" }
  ]
}
```

## Warnings

A warning reports suspicious input that the action can still work with. It is shown as a
`::warning file=<pyproject-path>::` annotation of the run (and in the job summary), is in the `warnings` array of the JSON that the script prints, and
**fails the step with `strict: "true"`** (the error lists them all). These are all the
warnings.

| Message contains                                                | When                                                                                                                                    |
| --------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `is set and also listed in [project].dynamic`                   | A field of `[project]` has a value and is also in `dynamic` (forbidden by PEP 621): the static value is used.                           |
| `[project].version is dynamic, the version output is empty`     | `version` is in `dynamic` and not set: `version` and `normalized-version` are empty.                                                    |
| `[project].requires-python is not a valid version specifier`    | `requires-python` cannot be parsed: `python-versions` is empty.                                                                         |
| `no python-candidates version satisfies`                        | No version of `python-candidates` is allowed by `requires-python`: `python-versions` is empty.                     |
| `Ignoring invalid requirement`                                  | A requirement string of `[project].dependencies`, an extra or a group cannot be parsed: it is skipped.                                  |
| `has an include-group cycle`                                    | The `include-group` entries of `[dependency-groups]` include each other in a loop (when `dependencies` is not empty).                   |
| `does not match any group`                                      | An `include-group` names a group that does not exist (when `dependencies` is not empty).                                                |
| `[project].dependencies is dynamic, it cannot be read`          | `dependencies` is in `dynamic` and not set: the build backend computes it, so the action finds no requirement in it.                    |
| `[project].optional-dependencies is dynamic, it cannot be read` | The same for `optional-dependencies` (only when `dependencies` is not empty).                                                           |
| `' not found`                                                   | `dependency '<entry>' not found`: a package of `dependencies` is not in the place(s) searched, its specifier is `null`.                 |

The same messages can come from several places; each is reported once.

## Failure modes

The action's step fails (non-zero exit) when:

- Neither `python3` nor `python` on `PATH` is Python 3.11 or later (older, missing or cannot be run).
- `pyproject-path` does not point to an existing file.
- The file is not valid TOML, is not UTF-8 or cannot be read (for example for lack of
  permission). A UTF-8 byte order mark at the start of the file is accepted and ignored
  (it used to fail with `Invalid statement (at line 1, column 1)`).
- The outputs (`$GITHUB_OUTPUT`) or the job summary
  (`$GITHUB_STEP_SUMMARY`, when there is a warning or an error) cannot be written. These used to end with a Python
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
- `[project].requires-python` is not a string.
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
- The `include-group` entries of `[dependency-groups]` are nested more than 100 levels deep, or
  expand more than 10,000 groups in total (a group included several times by several
  groups). They used to end with a Python traceback (`RecursionError`) or a run that never
  ended.
- The file has arrays or inline tables nested so deeply that the TOML parser gives up (about
  a thousand levels). It used to end with a Python traceback.
- A requirement of `[project].dependencies` or of a `[project.optional-dependencies]`
  extra is not a string (for example `dependencies = ["numpy", 1]`). It used to be
  ignored silently.
- `extra-values` is not valid JSON, or is not a JSON array of strings.
- `dependencies` is not a JSON array of strings, or an entry has a scope other than `project`,
  `extra:<name>` and `group:<name>` (for example `numpy@dev`).
- `strict` is not `true` or `false`, or is `true` and there is a warning (the
  error lists them; no output is written).

## Development

The logic is in the package `src/extract_pyproject_metadata/`, started by `scripts/run.sh`
(which installs the requirements in a private virtual environment when the
interpreter lacks them); `action.yaml` only wires inputs and outputs.
The package has one module per concern (reading the file, the fields, the
dependencies, the Python versions, the output, the report and the command line);
the list of the modules and the import rules are in the docstring of
`src/extract_pyproject_metadata/__init__.py` and in `CLAUDE.md`. The tests mirror
it: `tests/unit` (one module per module), `tests/integration` and
`tests/properties`. Use a virtual environment:

```bash
python -m venv .venv
.venv/bin/pip install --group dev
.venv/bin/pytest -q --cov
```

`packaging` is vendored: update it with `make vendor-packaging VERSION=x.y`
(`scripts/vendor_packaging.py` downloads the wheel, checks its digest and records the
version in `src/extract_pyproject_metadata/_vendor/README.md`). A monthly workflow opens an
issue when a newer release exists.

CI fails if the unit tests do not cover 100% of `src/extract_pyproject_metadata`.

Run on its own, without `--github-output`, the script prints one JSON object with
the outputs (the names use `_` instead of `-`) and the `warnings`. Its `schema_version` key (currently `1`) increases when a key
is renamed, removed or changes type, not when a key is added, so that a tool that
reads the object can check it.

The `Makefile` is the only task runner; run `make help` to list the targets, for
example `make check` (lint, format check, types and tests of the Python code),
`make format` and `make lint` (also the YAML, Markdown, shell, TOML and Makefile files).

The integration workflow (`.github/workflows/ci-test-local.yaml`) can only run on
GitHub. It runs the action on each `test-data/<case>/` and compares the `json`
output with the `expected.json` of the case; `tests/integration/test_golden.py`
checks the same files without GitHub. `nightly-test-stable.yaml` (the latest
release) is generated from it by `make workflows`.
