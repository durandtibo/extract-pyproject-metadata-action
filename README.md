# extract-pyproject-metadata-action

A composite GitHub Action that reads the project name, version,
optional-dependency extra names and the version specifiers of selected
dependencies directly from a `pyproject.toml` file. Reading these values
straight from `[project]`, `[project.optional-dependencies]` and
`[dependency-groups]` keeps downstream workflows (build, test matrices, publish
steps, ...) from drifting out of sync with what `pip install` actually
installs.

Requires the repository to already be checked out and a Python 3 interpreter
available on `PATH`. If the `packaging` package (or, on Python < 3.11 without
stdlib `tomllib`, the `tomli` backport) is missing, the action installs it in a
private virtual environment under `$RUNNER_TEMP`. It never modifies the Python
environment of the caller.

> [!NOTE]
> The action supports **Linux and macOS** runners only. **Windows runners are
> not supported**: the integration tests do not run on them, and the step
> expects `python3` and a POSIX `bash`.

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

| Name              | Description                                                                                                                                                                                                                                                                                           | Required | Default          |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | ---------------- |
| `pyproject-path`  | Path to `pyproject.toml`.                                                                                                                                                                                                                                                                             | No       | `pyproject.toml` |
| `extra-values`    | JSON array of additional values to prepend to the extras read from `pyproject.toml`, for callers that need a non-package value too (e.g. `[""]` for a "no extra" baseline, or `["all"]`).                                                                                                             | No       | `[]`             |
| `dependencies`    | JSON array of package names whose version specifier is looked up in `[project].dependencies`, `[project.optional-dependencies]`, then `[dependency-groups]` (including `include-group`); first match wins (also between requirements with different environment markers), names compared per PEP 503. | No       | `[]`             |
| `fail-on-missing` | `true` to fail when a package listed in `dependencies` is not found, instead of reporting it as `null` in `dependency-specifiers`. Must be `true` or `false`.                                                                                                                                         | No       | `false`          |

## Outputs

| Name                    | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`                  | Project name, as declared in `[project].name`.                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `normalized-name`       | Project name normalized per PEP 503: lowercase, with each run of `-`, `_` and `.` replaced by a single `-` (e.g. `My_Package.Name` gives `my-package-name`). Use it for the names of wheel/sdist files and of packages on an index.                                                                                                                                                                                                                                                         |
| `version`               | Project version, as declared in `[project].version`. Empty if `version` is listed in `[project].dynamic` (a warning is emitted).                                                                                                                                                                                                                                                                                                                                                            |
| `requires-python`       | Python version specifier, as declared in `[project].requires-python` (e.g. `>=3.10,<4`), as written. Empty if it is not declared (also if it is listed in `[project].dynamic`).                                                                                                                                                                                                                                                                                                             |
| `extras`                | JSON array of extra names, sorted by normalized name, with `extra-values` prepended. Duplicates are removed (the first occurrence is kept); names are compared per PEP 685, so `Foo_Bar` and `foo-bar` are the same extra.                                                                                                                                                                                                                                                                  |
| `groups`                | JSON array of the group names of `[dependency-groups]` (PEP 735), sorted by normalized name, without duplicates. `[]` if there is none.                                                                                                                                                                                                                                                                                                                                                     |
| `dependency-specifiers` | JSON object mapping each requested package to its specifier (e.g. `{"invoke-tasklib": ">=0.0.8,<1.0.0"}`). `null` if not found (or a failure, with `fail-on-missing`), `""` if the requirement has no specifier. A warning is emitted if different specifiers are found for requirements with the same environment marker, if a requirement string in the file is invalid and ignored, if `include-group` entries form a cycle, or if an `include-group` names a group that does not exist. |

Warnings are emitted as `::warning file=<pyproject-path>::<message>` workflow
commands, so GitHub attaches them to the file that is read (`pyproject-path` is
used as given).

## Failure modes

The action's step fails (non-zero exit) when:

- `pyproject-path` does not point to an existing file.
- The file is not valid TOML.
- `[project]` is missing the required `name` key, or the `version` key when `version` is not listed in `[project].dynamic`.
- `[project].dynamic` is not an array.
- `[project]` is not a table, `name` is not a non-empty string, or `version` is
  not a string (for example `version = 1.0` is a TOML float; write
  `version = "1.0"`).
- `[project].name` is not a valid project name: it may only contain letters,
  digits, `-`, `_` and `.`, and must start and end with a letter or a digit
  ([PEP 508](https://peps.python.org/pep-0508/#names)), for example `my pkg`.
- `[project].version` is not a valid
  [PEP 440](https://peps.python.org/pep-0440/) version (for example `latest`).
- `[project].requires-python` is not a string.
- `[project.optional-dependencies]` is not a table.
- `[dependency-groups]` is not a table.
- `[project].dependencies` or a value of `[project.optional-dependencies]` or
  `[dependency-groups]` is not an array, `[dependency-groups]` is not a table,
  or an `include-group` value is not a string.
- `extra-values` is not valid JSON, or is not a JSON array of strings.
- `dependencies` is not a JSON array of strings.
- `fail-on-missing` is not `true` or `false`, or is `true` and a package listed in
  `dependencies` is not found.

## Development

The logic is in `scripts/extract_metadata.py`; `action.yaml` only wires inputs
and outputs. Use a virtual environment:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/pytest -q
```

Formatting and linting of the non-Python files (YAML, Markdown, shell, TOML,
Makefiles) go through the `Makefile`; run `make help` to list the targets, for
example `make format` and `make lint`.

The integration workflows (`.github/workflows/test-local.yaml` and
`test-stable.yaml`) can only run on GitHub.
