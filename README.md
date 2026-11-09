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
`packaging` package is missing or older than `23.0`, the action installs it in a
private virtual environment under `$RUNNER_TEMP` (removed at the end of the
step), with the versions listed in
`scripts/requirements.txt` (`packaging>=23.0,<27`; a `packaging` that is already
installed is used as it is when it is `23.0` or later, even when it is newer than
the upper bound). The step logs when it installs it. It never modifies the Python environment of the caller.

That installation needs a package index: PyPI by default, or the one that `pip`
is configured to use (`PIP_INDEX_URL`, `PIP_EXTRA_INDEX_URL`, `pip.conf`, ...). On
a runner without network access, or when you prefer not to download anything
in the job, install `packaging` in the Python of the job beforehand (for
example `python -m pip install --upgrade packaging`, from a mirror or a cache): the
action then uses it as it is and does not touch the network.

To make the install faster when it is needed, set `installer: uv` (or `auto`): the
virtual environment is then created and filled by [uv](https://docs.astral.sh/uv/),
which you can set up with `astral-sh/setup-uv`. uv reads its own configuration
(`UV_INDEX_URL`, `uv.toml`), not the one of pip, which is why `pip` stays the default.

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

| Name                      | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | Required | Default                                |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------- | -------------------------------------- |
| `pyproject-path`          | Path to `pyproject.toml`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | No       | `pyproject.toml`                       |
| `extra-values`            | JSON array of additional values to prepend to the extras read from `pyproject.toml`, for callers that need a non-package value too (e.g. `[""]` for a "no extra" baseline, or `["all"]`).                                                                                                                                                                                                                                                                                                                                            | No       | `[]`                                   |
| `dependencies`            | JSON array of package names whose version specifier is looked up in `[project].dependencies`, `[project.optional-dependencies]`, then `[dependency-groups]` (including `include-group`); first match wins (also between requirements with different environment markers), names compared per PEP 503. A name followed by `@project`, `@extra:<name>` or `@group:<name>` is looked up in `[project].dependencies`, that extra or that group only (see [Looking up a dependency in one place](#looking-up-a-dependency-in-one-place)). | No       | `[]`                                   |
| `fail-on-dynamic-version` | `true` to fail when `version` is listed in `[project].dynamic`, instead of giving an empty `version` output with a warning. Use it in release or publish jobs that need a static version.                                                                                                                                                                                                                                                                                                                                            | No       | `false`                                |
| `resolve-dynamic-version` | `true` to read a version listed in `[project].dynamic` from the file that the build backend reads it from, without running any code of the project (see [Dynamic version](#dynamic-version)). A version that is found is used as a static one.                                                                                                                                                                                                                                                                                       | No       | `false`                                |
| `python-candidates`       | JSON array of `major.minor` Python versions to choose from for the `python-versions` output (e.g. `["3.11","3.12"]`). Each must be of the form `3.12`; duplicates are removed.                                                                                                                                                                                                                                                                                                                                                       | No       | `["3.11","3.12","3.13","3.14","3.15"]` |
| `fail-on-missing`         | `true` to fail when a package listed in `dependencies` is not found, instead of reporting it as `null` in `dependency-specifiers`.                                                                                                                                                                                                                                                                                                                                                                                                   | No       | `false`                                |
| `strict`                  | `true` to fail when there is any warning (listed in the error), instead of only reporting it. Use it in CI to keep a `pyproject.toml` free of suspicious input.                                                                                                                                                                                                                                                                                                                                                                      | No       | `false`                                |
| `python-executable`       | Python interpreter that runs the action: a command found on `PATH` or a path to an executable (Python 3.11 or later, e.g. `python3.12` or `/opt/python/bin/python`), for runners where `python3` is not the interpreter to use. The private virtual environment, if one is needed, is created with it.                                                                                                                                                                                                                               | No       | `python3`                              |
| `step-summary`            | `true` to always write the outputs and the warnings to the job summary of the workflow run (a table with one row per output), `false` to never write them, or `auto` to write them only when there are warnings (a failure is always written).                                                                                                                                                                                                                                                                                       | No       | `auto`                                 |
| `installer`               | Tool that installs `packaging` in the private virtual environment when the Python lacks it: `pip` (follows the pip configuration), `uv` (faster; follows the configuration of uv, and fails if uv is not on `PATH` when an install is needed) or `auto` (`uv` if it is on `PATH`, `pip` otherwise). Nothing is installed, whatever the value, when `packaging` is available.                                                                                                                                                         | No       | `pip`                                  |

`fail-on-dynamic-version`, `resolve-dynamic-version`, `fail-on-missing` and `strict` are boolean inputs: the
value must be `true` or `false`, the case and the surrounding spaces are ignored,
and any other value fails the step. `step-summary` is the same with a third value,
`auto`.

## Outputs

| Name                      | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`                    | Project name, as declared in `[project].name`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `normalized-name`         | Project name normalized per PEP 503: lowercase, with each run of `-`, `_` and `.` replaced by a single `-` (e.g. `My_Package.Name` gives `my-package-name`). Use it for the names of wheel/sdist files and of packages on an index.                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `version`                 | Project version, as declared in `[project].version`. Empty if `version` is listed in `[project].dynamic` (a warning is emitted).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `normalized-version`      | Project version in the canonical form of [PEP 440](https://peps.python.org/pep-0440/#normalization) (e.g. `1.0rc1` for `1.0-RC1`, `1.0.post1` for `1.0-1`, `2020.1.5` for `2020.01.05`). Use it for the names of wheel/sdist files and for tags, which are built from this form. Empty if `version` is listed in `[project].dynamic`.                                                                                                                                                                                                                                                                                                                                                   |
| `description`             | Project description, as declared in `[project].description`, as written. Empty if it is not declared (also if it is listed in `[project].dynamic`). It may contain line breaks: pass it to the shell through `env:`. It is not shown in the `📦` log line.                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `readme`                  | Path of the readme file, from `[project].readme` (a string, or the `file` of a table), as written (e.g. `README.md`). Empty if it is not declared, if the readme is inline (`text`) or if it is listed in `[project].dynamic`. The action does not read the file. Not in the `📦` log line.                                                                                                                                                                                                                                                                                                                                                                                             |
| `license`                 | License, from `[project].license`: the SPDX expression ([PEP 639](https://peps.python.org/pep-0639/)) or the `text` of the table of PEP 621, as written (e.g. `MIT`, `Apache-2.0 OR MIT`). Empty if it is not declared, if it is a `file` or if it is listed in `[project].dynamic`. A string that is not a valid SPDX expression (for example `MIT License`) gives a warning, when `packaging` 24.2 or later checks it; the value is still the one written. The table of PEP 621 is not validated. Not in the `📦` log line.                                                                                                                                                           |
| `license-files`           | JSON array of the patterns of `[project].license-files` ([PEP 639](https://peps.python.org/pep-0639/)), as written and in order (e.g. `["LICENSE","licenses/*.txt"]`). `[]` if it is not declared (also if it is listed in `[project].dynamic`). The patterns are not expanded: the action does not look at the files. Not in the `📦` log line.                                                                                                                                                                                                                                                                                                                                        |
| `authors`                 | JSON array of the authors of `[project].authors`, in order, each an object with the `name` and the `email` that the author has (e.g. `[{"name":"Ada","email":"ada@example.com"},{"name":"Bob"}]`); other keys are ignored. `[]` if there is none or if `authors` is listed in `[project].dynamic`. Not in the `📦` log line.                                                                                                                                                                                                                                                                                                                                                            |
| `urls`                    | JSON object mapping each label of `[project.urls]` to its URL, as written and in the order of the file (e.g. `{"Homepage":"https://example.com"}`). `{}` if there is none. Look a label up in a workflow with `fromJSON(...)["Homepage"]`. Not in the `📦` log line.                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `keywords`                | JSON array of `[project].keywords`, as written and in order (e.g. `["toml","metadata"]`). `[]` if it is not declared (also if it is listed in `[project].dynamic`). Not in the `📦` log line.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `classifiers`             | JSON array of `[project].classifiers`, as written and in order (e.g. `["Programming Language :: Python :: 3"]`). `[]` if it is not declared (also if it is listed in `[project].dynamic`). The classifiers are not checked against the list of PyPI. Not in the `📦` log line.                                                                                                                                                                                                                                                                                                                                                                                                          |
| `scripts`                 | JSON object mapping each name of `[project.scripts]` to its entry point, as written and in the order of the file (e.g. `{"mytool":"mypkg.cli:main"}`). `{}` if there is none (also if `scripts` is listed in `[project].dynamic`). `[project.gui-scripts]` and `[project.entry-points]` are not read. Not in the `📦` log line.                                                                                                                                                                                                                                                                                                                                                         |
| `requires-python`         | Python version specifier, as declared in `[project].requires-python` (e.g. `>=3.10,<4`), as written. Empty if it is not declared (also if it is listed in `[project].dynamic`).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `python-versions`         | JSON array of the `python-candidates` that `requires-python` allows, in the order of the candidates (e.g. `["3.10","3.11"]` for `>=3.10,<3.12`), to drive a job matrix. All the candidates if `requires-python` is not declared. A minor version is allowed if some release of it satisfies the specifier (checked on `X.Y.0` to `X.Y.99` and on a very late patch release), so `>=3.10.2` allows `3.10` and `==3.12.3` allows `3.12` only (a patch number of 100 or more, such as `==3.12.150`, matches no release). `[]` (with a warning) if `requires-python` is not a valid specifier, or if none of the candidates satisfies it (for example `>=4`).                               |
| `python-min`              | The lowest of the `python-versions`, compared as numbers (`3.9` is lower than `3.10`), e.g. `3.10` for `>=3.10,<3.12`. Empty if `python-versions` is empty. Use it for the jobs that need a single Python version (lint, build, docs).                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `python-max`              | The highest of the `python-versions`, compared as numbers (`3.10` is higher than `3.9`), e.g. `3.11` for `>=3.10,<3.12`. Empty if `python-versions` is empty. Use it for the jobs that need the newest supported Python (for example a type checker or a latest-Python job).                                                                                                                                                                                                                                                                                                                                                                                                            |
| `python-matrix`           | JSON object `{"python-version": [...]}` made of the `python-versions`, to use as a job matrix as it is with `fromJSON` (see [Python version matrix](#python-version-matrix)). `{"python-version":[]}` if `python-versions` is empty: GitHub fails a job whose matrix has no value, so the action warns (and `strict` fails) when no candidate is allowed; a workflow may also check `python-versions` first. Not in the `📦` log line.                                                                                                                                                                                                                                                  |
| `extras`                  | JSON array of extra names, sorted by normalized name, with `extra-values` prepended. Duplicates are removed (the first occurrence is kept); names are compared per PEP 685, so `Foo_Bar` and `foo-bar` are the same extra.                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `groups`                  | JSON array of the group names of `[dependency-groups]` (PEP 735), sorted by normalized name, without duplicates. `[]` if there is none.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `build-backend`           | Build backend, from `[build-system].build-backend`, as written (e.g. `hatchling.build`). Empty if it is not declared or if there is no `[build-system]`. Not in the `📦` log line.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `build-requires`          | JSON array of the requirements of `[build-system].requires`, as written and in order (e.g. `["hatchling","hatch-vcs>=0.4"]`). `[]` if it is not declared. The requirements are not parsed. Not in the `📦` log line.                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `project-dependencies`    | JSON object mapping each package of `[project].dependencies` to its specifier, with the name as written in its first requirement and in the order of the file (e.g. `{"numpy": "<3,>=1.20", "Foo_Bar": ""}`), without having to list the names in `dependencies`. Extras and dependency groups are not read. The first requirement of a package wins, whatever its environment marker, as for `dependency-specifiers`. `{}` if there is none. A warning is emitted if a requirement string is invalid and ignored, if a package has different specifiers for the same environment marker, or if `dependencies` is listed in `[project].dynamic` without a static value.                 |
| `dependency-specifiers`   | JSON object mapping each requested package to its specifier (e.g. `{"invoke-tasklib": ">=0.0.8,<1.0.0"}`). `null` if not found (or a failure, with `fail-on-missing`), `""` if the requirement has no specifier. A warning is emitted if different specifiers are found for requirements with the same environment marker, if a requirement string in the file is invalid and ignored, if `include-group` entries form a cycle, if an `include-group` names a group that does not exist, or if `dependencies` or `optional-dependencies` is listed in `[project].dynamic` without a static value (the build backend computes it, so the action cannot read it and finds nothing in it). |
| `dependency-requirements` | JSON object mapping each package listed in `dependencies` to the array of **all** its requirements, in search order, each an object with its `specifier` and its environment `marker` (both `""` if it has none; e.g. `{"numpy":[{"specifier":">=1.20","marker":"python_version < \"3.12\""},{"specifier":">=1.26","marker":"python_version >= \"3.12\""}]}`). `[]` for a package that is not found. Unlike `dependency-specifiers`, nothing is dropped, so a workflow can pick the requirement that applies to its Python version (see [Environment markers](#environment-markers)). Not in the `📦` log line.                                                                         |
| `json`                    | The whole result in one value: a JSON object with the keys of the script output (the names of the other outputs with `_` instead of `-`: `normalized_name`, `python_versions`, ...), the `warnings` (an array of messages) and the `schema_version` (see [Development](#development)). Unlike the other outputs, arrays and objects are values, not strings, so `fromJSON(steps.metadata.outputs.json).extras` is the array of extras. Pass it to another job with one job output, or to a script. The step summary table leaves it out, as does the `📦` log line. `python-matrix` is not in it.                                                                                       |

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
`readme`, `license`, `license-files`, `authors`, `urls`, `keywords`, `classifiers`, `scripts`,
`build-backend`, `build-requires`, `dependency-requirements` and `json`. With
`step-summary: "true"`, the outputs and the warnings are also written to the job
summary of the run as a Markdown table (values are escaped, so a value from
`pyproject.toml` cannot add Markdown or HTML to the page). With the default,
`step-summary: "auto"`, the table is only written when there are warnings, so a
warning (and the failure of `strict`, which lists them) shows on the summary page
of the run and not only in the log; `"false"` never writes it. When the step
fails, the error message is written to the job summary instead (with `true` and
`auto`), so the reason is visible on the summary page of the run and not only in
the log of the step.

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

## Dynamic version

When `version` is listed in `[project].dynamic`, the version output is empty (with a
warning) because the build backend computes it. With `resolve-dynamic-version: "true"`,
the action first looks for it in the file that the backend reads it from. It only
**reads** that file: no code of the project is imported or run, and no build backend
is started. Two declarations are understood:

```toml
[project]
name = "pkg"
dynamic = ["version"]

# setuptools: the text of a file ...
[tool.setuptools.dynamic]
version = { file = "VERSION" }

# ... or a string literal of a module (found with `ast`, never imported)
# version = { attr = "pkg.__version__" }
```

```toml
# hatch: the first match of a regular expression (default: `__version__ = "1.2.3"`
# or `VERSION = "1.2.3"`), or of the `pattern` that has a `version` group
[tool.hatch.version]
path = "src/pkg/__about__.py"
```

- Files are looked up relative to the directory of the `pyproject.toml` and must stay
  inside it; a file larger than 1 MiB is not read. For `attr`, the module is searched
  in the `[tool.setuptools.package-dir]` directory, then in `src` and in the directory
  itself (`pkg.py` or `pkg/__init__.py`); it must assign a string literal, not a tuple
  or a call.
- The version must be a valid [PEP 440](https://peps.python.org/pep-0440/) version.
  It is then used like a static one: `version` is the text of the file and
  `normalized-version` its canonical form, there is no warning, and
  `fail-on-dynamic-version` does not fail.
- When it cannot be resolved (another backend, a version computed from git tags by
  `setuptools-scm` or `hatch-vcs`, a missing file, a pattern that does not match), the
  warning says why and the usual handling of a dynamic version applies: an empty
  `version`, or a failure with `fail-on-dynamic-version`.
- `pattern` is a regular expression of the file: a pathological one can make the step
  slow, as it can in the build. Use `strict` or a job `timeout-minutes` as usual.

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
`dependency-specifiers` and `dependency-requirements` is always the entry as written, so
`numpy` and `numpy@project` are two keys, even when they find the same requirement.

### A package declared in several places

The same package is often declared in more than one place (a runtime range in
`[project].dependencies`, a pin in a group). With the plain name, `dependency-specifiers`
reports the **first** requirement of the search order above, and the action warns when
the places disagree: all the requirements of the package that have the same environment
marker (or none) are compared, whichever place they are in, and different specifiers
give a warning (which `strict` turns into a failure). A scoped entry only looks at its own
place, so it reads the requirement of that place without such a warning. To see every
requirement of the package, in search order and with its marker, read
`dependency-requirements`.

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
the keys of `dependency-specifiers` and `dependency-requirements` are the entries as
written. The plain `numpy` also warns here, because the three places have different
specifiers (`>=1.20`, `>=2`, `>=1.26`), while the scoped entries do not. A package that the place does not declare, or a place that does not exist, gives `null`
(and an empty array in `dependency-requirements`), and fails the step with `fail-on-missing`.

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

## Warnings

A warning reports suspicious input that the action can still work with. It is shown as a
`::warning file=<pyproject-path>::` annotation of the run (and in the job summary with
`step-summary`), is in the `warnings` array of the JSON that the script prints, and
**fails the step with `strict: "true"`** (the error lists them all). These are all the
warnings.

| Message contains                                                | When                                                                                                                                    |
| --------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `is set and also listed in [project].dynamic`                   | A field of `[project]` has a value and is also in `dynamic` (forbidden by PEP 621): the static value is used.                           |
| `[project].version is dynamic, the version output is empty`     | `version` is in `dynamic` and not set: `version` and `normalized-version` are empty.                                                    |
| `is not a valid SPDX license expression`                        | `[project].license` is a string that is not a valid SPDX expression (only checked with `packaging` 24.2 or later).                      |
| `[project].requires-python is not a valid version specifier`    | `requires-python` cannot be parsed: `python-versions` is empty.                                                                         |
| `no python-candidates version satisfies`                        | No version of `python-candidates` is allowed by `requires-python`: `python-versions` and `python-matrix` are empty.                     |
| `Ignoring invalid requirement`                                  | A requirement string of `[project].dependencies`, an extra or a group cannot be parsed: it is skipped.                                  |
| `has different specifiers`                                      | A package has requirements with the same environment marker and different specifiers (see [Environment markers](#environment-markers)). |
| `has an include-group cycle`                                    | The `include-group` entries of `[dependency-groups]` include each other in a loop (when `dependencies` is not empty).                   |
| `does not match any group`                                      | An `include-group` names a group that does not exist (when `dependencies` is not empty).                                                |
| `[project].dependencies is dynamic, it cannot be read`          | `dependencies` is in `dynamic` and not set: the build backend computes it, so the action finds no requirement in it.                    |
| `[project].optional-dependencies is dynamic, it cannot be read` | The same for `optional-dependencies` (only when `dependencies` is not empty).                                                           |

The same messages can come from several places; each is reported once.

## Failure modes

The action's step fails (non-zero exit) when:

- It runs on a Windows runner (`RUNNER_OS` is `Windows`), which is not supported.
- The Python interpreter (`python3`, or `python-executable`) is older than 3.11, missing or cannot be run, or `packaging` is missing
  or older than `23.0` and cannot be installed (for example, no access to a package index).
- `pyproject-path` does not point to an existing file.
- The file is not valid TOML, is not UTF-8 or cannot be read (for example for lack of
  permission). A UTF-8 byte order mark at the start of the file is accepted and ignored
  (it used to fail with `Invalid statement (at line 1, column 1)`).
- The outputs (`$GITHUB_OUTPUT`) or, with `step-summary` (`true`, or `auto` with warnings), the job summary
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
- `[project.scripts]` is not a table, or an entry point is not a string.
- `[project].keywords` or `[project].classifiers` is not an array of strings.
- `python-candidates` is not valid JSON, is not a JSON array of strings, or
  contains a string that is not of the form `major.minor`.
- `[project.optional-dependencies]` is not a table.
- `[dependency-groups]` is not a table.
- `[build-system]` is not a table, its `build-backend` is not a string or its `requires` is not
  an array of strings.
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
- `fail-on-dynamic-version` is not `true` or `false`, or is `true` and
  `version` is listed in `[project].dynamic` and not resolved by `resolve-dynamic-version`.
- `resolve-dynamic-version` is not `true` or `false`.
- `strict` is not `true` or `false`, or is `true` and there is a warning (the
  error lists them; no output is written).
- `step-summary` is not `true`, `false` or `auto`, or is `true` and the job summary
  file (`$GITHUB_STEP_SUMMARY`) is not set.
- `installer` is not `pip`, `uv` or `auto`, or is `uv` and uv is not on `PATH` while
  `packaging` has to be installed.
- `fail-on-missing` is not `true` or `false`, or is `true` and a package listed in
  `dependencies` is not found (the error says when `[project].dependencies` or
  `[project].optional-dependencies` is dynamic and so cannot be read).

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
.venv/bin/pip install -r requirements-test.txt
.venv/bin/pytest -q --cov
```

CI fails if the unit tests do not cover 100% of `src/extract_pyproject_metadata`.

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
