# extract-pyproject-metadata-action

A GitHub Action that reads a `pyproject.toml` and exposes the values that drive a
workflow: what to build (name, version), what to test (extras, dependency groups, Python
versions) and which dependency specifiers to install. Reading them from the file keeps
build, test and publish jobs in sync with what `pip install` installs.

The action only **reads** the file: it never runs project code or a build backend, and
values from the file cannot become shell code, workflow commands or Markdown. It needs a
Python 3.11 or later on `PATH` (for example from `actions/setup-python`) and nothing
else: no installation, no network. It runs on Linux, macOS and Windows.

## Usage

```yaml
- uses: actions/checkout@v7

- id: metadata
  uses: durandtibo/extract-pyproject-metadata-action@v0.3.0
  with:
    extra-values: '[""]'
    dependencies: '["numpy", "pytest@group:dev"]'

- run: echo "$NAME $VERSION $EXTRAS $SPECIFIERS"
  env:
    NAME: ${{ steps.metadata.outputs.name }}
    VERSION: ${{ steps.metadata.outputs.version }}
    EXTRAS: ${{ steps.metadata.outputs.extras }}
    SPECIFIERS: ${{ steps.metadata.outputs.dependency-specifiers }}
```

Pass outputs through `env:`, as above, and not by writing `${{ ... }}` in the script.
For this `pyproject.toml`:

```toml
[project]
name = "My_Package"
version = "1.2.3"
requires-python = ">=3.12"
dependencies = ["tqdm>=4"]

[project.optional-dependencies]
numpy = ["numpy>=1.20,<3"]
pandas = ["pandas"]

[dependency-groups]
dev = ["pytest>=8"]
```

the `json` output (see below) contains, among other values:

```json
{
  "name": "My_Package",
  "normalized_name": "my-package",
  "file_name": "my_package",
  "version": "1.2.3",
  "requires_python": ">=3.12",
  "extras": ["", "numpy", "pandas"],
  "groups": ["dev"],
  "python_versions": ["3.12", "3.13", "3.14", "3.15"],
  "dependency_specifiers": { "numpy": "<3,>=1.20", "pytest@group:dev": ">=8" }
}
```

## Recipes

A test matrix over the extras and the Python versions that `requires-python` allows
(`extra-values: '[""]'` adds a job without extra):

```yaml
jobs:
  metadata:
    runs-on: ubuntu-latest
    outputs:
      extras: ${{ steps.metadata.outputs.extras }}
      python-versions: ${{ steps.metadata.outputs.python-versions }}
    steps:
      - uses: actions/checkout@v7
      - id: metadata
        uses: durandtibo/extract-pyproject-metadata-action@v0.3.0
        with:
          extra-values: '[""]'

  test:
    needs: metadata
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ${{ fromJSON(needs.metadata.outputs.python-versions) }}
        extra: ${{ fromJSON(needs.metadata.outputs.extras) }}
    steps:
      - uses: actions/setup-python@v7
        with:
          python-version: ${{ matrix.python-version }}
```

A release job that fails on any warning, for example a dynamic version, and builds the
file name of the wheel (`file-name` is the name as written in file names, `my_package`):

```yaml
- id: metadata
  uses: durandtibo/extract-pyproject-metadata-action@v0.3.0
  with:
    strict: "true"

- run: pip install "dist/$FILE_NAME-$VERSION-py3-none-any.whl"
  env:
    FILE_NAME: ${{ steps.metadata.outputs.file-name }}
    VERSION: ${{ steps.metadata.outputs.normalized-version }}
```

## Inputs

<!-- inputs:start -->

| Name                | Description                                                                                                                                                                                                                                                                                                    | Default               |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- |
| `pyproject-path`    | Path to pyproject.toml                                                                                                                                                                                                                                                                                         | `pyproject.toml`      |
| `extra-values`      | JSON array of additional values to prepend to the extras read from pyproject.toml, for callers that need a non-package value in the list too (e.g. '[""]' for a "no extra" baseline, or '["all"]').                                                                                                            | `[]`                  |
| `dependencies`      | JSON array of package names whose version specifier is looked up in [project].dependencies, [project.optional-dependencies] and [dependency-groups] (e.g. '["invoke-tasklib"]'). A name followed by "@" and "project", "extra:<name>" or "group:<name>" is looked up there only (e.g. '["pytest@group:dev"]'). | `[]`                  |
| `python-candidates` | JSON array of "major.minor" Python versions to choose from for the python-versions output (e.g. '["3.11","3.12"]'); empty for the supported CPython versions, listed in the README                                                                                                                             | (see the description) |
| `strict`            | Set to "true" to fail when there is any warning (a dynamic version, a dependency that is not found, ...), instead of only reporting it ("true" or "false")                                                                                                                                                     | `false`               |

<!-- inputs:end -->

`strict` is a boolean input: the value must be `true` or `false`, the case and the
surrounding spaces are ignored, and any other value fails the step. The list of Python
candidates is yours to maintain, as the action does not know which versions exist. By
default it is:

<!-- candidates:start -->

`["3.11","3.12","3.13","3.14","3.15"]`
<!-- candidates:end -->

## Outputs

<!-- outputs:start -->

| Name                    | Description                                                                                                                                                                                                                                                                                                             |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`                  | Project name, as declared in [project].name                                                                                                                                                                                                                                                                             |
| `normalized-name`       | Project name normalized per PEP 503 (lowercase, with each run of "-", "_" and "." replaced by a single "-"), for an index URL or pip install                                                                                                                                                                            |
| `file-name`             | Project name as it is written in the file names of wheels and sdists: the normalized name with "_" instead of "-" (e.g. "my_package")                                                                                                                                                                                   |
| `version`               | Project version, as declared in [project].version                                                                                                                                                                                                                                                                       |
| `normalized-version`    | Project version in the canonical form of PEP 440 (e.g. "1.0rc1" for "1.0-RC1"; empty if the version is dynamic)                                                                                                                                                                                                         |
| `requires-python`       | Python version specifier, as declared in [project].requires-python (empty if not declared)                                                                                                                                                                                                                              |
| `python-versions`       | JSON array of the python-candidates allowed by requires-python (all of them if requires-python is not declared)                                                                                                                                                                                                         |
| `python-min`            | Lowest of the python-versions, compared as numbers (empty if there is none)                                                                                                                                                                                                                                             |
| `python-max`            | Highest of the python-versions, compared as numbers (empty if there is none)                                                                                                                                                                                                                                            |
| `extras`                | JSON array of extra names                                                                                                                                                                                                                                                                                               |
| `groups`                | JSON array of dependency group names, from [dependency-groups]                                                                                                                                                                                                                                                          |
| `dependency-specifiers` | JSON object mapping each requested package to its specifier (null if not found, empty string if it has no specifier)                                                                                                                                                                                                    |
| `json`                  | JSON object with all the other outputs, the dependency_requirements (all the requirements of each requested package, with their environment markers) and the warnings, in one value (the names use "_" instead of "-"; the arrays and objects are values, not strings), to pass the whole result to another step or job |

<!-- outputs:end -->

Scalars are plain strings; arrays and objects are compact JSON strings for `fromJSON`.
The `json` output is the whole result with real JSON values (`fromJSON(...json).extras`),
plus `dependency_requirements`, the `warnings` (items `{"code", "message"}`) and the `schema_version` (`3`). The step logs a
one-line `📦` log line of the outputs, with line breaks escaped. The line shows `name`,
`version`, `requires-python`, `python-versions`, `python-min`, `python-max`, `extras`,
`groups`, `dependency-specifiers`.

A version in `[project].dynamic` has no value in the file, so `version` and
`normalized-version` are empty, with a warning: use `strict` in a job that needs one, and
ask the build backend for it.

## Looking up a dependency in one place

`dependencies` lists the packages to look up. By default a package is searched in
`[project].dependencies`, then in every extra (in file order), then in every dependency
group (in file order, `include-group` expanded), and the **first** requirement wins;
environment markers are never evaluated. To read one place only, follow the name with `@`
and the place. Names are compared per PEP 503.

| Entry              | Searched in                                                                | Key in the result  |
| ------------------ | -------------------------------------------------------------------------- | ------------------ |
| `numpy`            | `[project].dependencies`, then the extras, then the groups: first match    | `numpy`            |
| `numpy@project`    | `[project].dependencies` only                                              | `numpy@project`    |
| `numpy@extra:fast` | the extra `fast` of `[project.optional-dependencies]` only                 | `numpy@extra:fast` |
| `numpy@group:dev`  | the group `dev` of `[dependency-groups]` only, with the groups it includes | `numpy@group:dev`  |

Anything else after the `@` (`numpy@dev`, `numpy@extra:`) fails the step. A package that
is not found has the specifier `null` and a warning. When a package has several
requirements (a range per Python version, a pin in a group), `dependency_requirements` in
the `json` output lists all of them, in search order, with their `marker` and their
`source` (`project`, `extra:<name>` or `group:<name>`), and the workflow picks one:

```yaml
- id: metadata
  uses: durandtibo/extract-pyproject-metadata-action@v0.3.0
  with:
    dependencies: '["numpy"]'

- run: echo "$REQUIREMENTS"
  env:
    REQUIREMENTS: ${{ toJSON(fromJSON(steps.metadata.outputs.json).dependency_requirements) }}
```

## Warnings

A warning reports suspicious input that the action can still work with. It is a
`::warning file=<pyproject-path>,title=<code>::` annotation, an item `{"code", "message"}`
of the `warnings` array of `json`, and **fails the step with `strict: "true"`**, whose error
lists them all (`<code>: <message>`). The `code` is stable; the `message` may be reworded,
so a workflow tests the code.

<!-- warnings:start -->

| Code                      | When                                                                                                                            | Effect                                        |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| `static-and-dynamic`      | A field of `[project]` has a value and is also in `dynamic` (forbidden by PEP 621).                                             | The static value is used.                     |
| `dynamic-version`         | `version` is in `dynamic` and not set.                                                                                          | `version` and `normalized-version` are empty. |
| `invalid-requires-python` | `requires-python` is not a valid version specifier.                                                                             | `python-versions` is empty.                   |
| `no-python-version`       | No version of `python-candidates` is allowed by `requires-python`.                                                              | `python-versions` is empty.                   |
| `invalid-requirement`     | A requirement string of `[project].dependencies`, an extra or a group cannot be parsed (only when `dependencies` is not empty). | The requirement is skipped.                   |
| `include-group-cycle`     | The `include-group` entries of `[dependency-groups]` include each other in a loop (only when `dependencies` is not empty).      | The loop is not followed.                     |
| `unknown-include-group`   | An `include-group` names a group that does not exist (only when `dependencies` is not empty).                                   | The entry is skipped.                         |
| `dynamic-dependencies`    | `dependencies` or `optional-dependencies` is in `dynamic` and not set (only when `dependencies` is not empty).                  | No requirement is found in it.                |
| `dependency-not-found`    | A package of `dependencies` is not in the place(s) searched.                                                                    | Its specifier is `null`.                      |

<!-- warnings:end -->

## Failures

Invalid input fails the step with one message `<field>: <problem>` and an
`::error file=<pyproject-path>::` annotation (the field is an input name, `pyproject-path`,
or a TOML path such as `[project].version`; the message never contains the file name, the
annotation does). The inputs are validated before the file is read, and there is never a
Python traceback. It happens when:

- no `python3` or `python` on `PATH` is Python 3.11 or later;
- `pyproject-path` is not a file, or the file is not valid UTF-8 TOML (a byte order mark is
  ignored);
- a field that is read is invalid: `[project]` is not a table, `name` is missing, is not a
  valid [PEP 508](https://peps.python.org/pep-0508/#names) name, or is in `dynamic`;
  `version` is missing (and not dynamic) or is not a valid
  [PEP 440](https://peps.python.org/pep-0440/) version; `requires-python` is not a
  string; `dynamic`, `optional-dependencies` or `dependency-groups` is not a table or an
  array of the right type;
- a requirement table is invalid, **only when `dependencies` is not empty** (without a
  lookup the requirements are not read): `[project].dependencies`, an extra or a group has
  the wrong type, an `include-group` is nested more than 100 levels or expands more than
  10,000 groups;
- an input is invalid: `extra-values`, `dependencies` or `python-candidates` is not a JSON
  array of strings, a `dependencies` scope is not `project`, `extra:<name>` or
  `group:<name>`, a candidate is not `major.minor`, or `strict` is not a boolean;
- `strict` is `true` and there is a warning (no output is written);
- the outputs (`$GITHUB_OUTPUT`) cannot be written.

Fields that the action does not output (`description`, `license`, `authors`,
`[build-system]`, ...) are not read and not validated.

## Development

The logic is in `src/extract_pyproject_metadata/`, started by `scripts/run.sh`;
`action.yaml` only wires inputs and outputs. The modules and the import rules are in
`CLAUDE.md`. `packaging` is vendored (`make vendor-packaging VERSION=x.y`). The program
reads the inputs from the environment (`INPUT_PYPROJECT_PATH`, `INPUT_EXTRA_VALUES`,
`INPUT_DEPENDENCIES`, `INPUT_PYTHON_CANDIDATES`, `INPUT_STRICT`): a local run is
`INPUT_PYPROJECT_PATH=path/to/pyproject.toml python scripts/extract_metadata.py`, which prints
the `json` output.

```bash
python -m venv .venv
.venv/bin/pip install --group dev
.venv/bin/pytest -q --cov
```

`make help` lists the targets: `make check` (lint, types, tests with the 100 % coverage
gate), `make docs` (regenerates the tables of this file from `action.yaml`), `make workflows`
(regenerates `nightly-test-stable.yaml`). `test-data/<case>/` holds the golden cases: a
`pyproject.toml`, the `inputs.json` and the `expected.json` (the `json` output), checked by
`tests/integration/test_golden.py` and, with the real action, by `ci-test-local.yaml`, which can
only run on GitHub. The `schema_version` of `json` changes only when a key is renamed,
removed or changes type.

To release: update the default `python-candidates` in `python_versions.py` (every October; `maintenance.yaml` opens an issue), check
that `packaging` is current (`make vendor-packaging`), run `make check` and `make docs`,
write `release-notes/vX.Y.Z.md`, and push the tag `vX.Y.Z`. `release.yaml` then runs the
checks and creates the GitHub release (no tag is moved: workflows pin `@vX.Y.Z`). Afterwards set `STABLE_REF` in
`scripts/generate_workflows.py` to the new tag and run `make workflows`.
