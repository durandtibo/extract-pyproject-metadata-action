# extract-pyproject-metadata-action

A composite GitHub Action that reads the project name, version, and
optional-dependency extra names directly from a `pyproject.toml` file. Reading
these values straight from `[project]` and `[project.optional-dependencies]`
keeps downstream workflows (build, test matrices, publish steps, ...) from
drifting out of sync with what `pip install` actually installs.

Requires the repository to already be checked out and a Python 3 interpreter
available on `PATH`. On Python < 3.11 (no stdlib `tomllib`), the action
installs the `tomli` backport on the fly.

## Usage

```yaml
- uses: actions/checkout@v7

- id: metadata
  uses: durandtibo/extract-pyproject-metadata-action@v0.1
  with:
    pyproject-path: pyproject.toml
    extra-values: '[""]'

- run: |
    echo "name=${{ steps.metadata.outputs.name }}"
    echo "version=${{ steps.metadata.outputs.version }}"
    echo "extras=${{ steps.metadata.outputs.extras }}"
```

Given a `pyproject.toml` such as:

```toml
[project]
name = "coola"
version = "1.2.3"

[project.optional-dependencies]
numpy = ["numpy"]
pandas = ["pandas"]
```

the example above outputs:

- `name`: `coola`
- `version`: `1.2.3`
- `extras`: `["","numpy","pandas"]`

## Inputs

| Name             | Description                                                                                                                                                                                                                            | Required | Default          |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | ---------------- |
| `pyproject-path` | Path to `pyproject.toml`.                                                                                                                                                                                                              | No       | `pyproject.toml` |
| `extra-values`   | JSON array of additional values to prepend to the extras read from `pyproject.toml`, for callers that need a non-package value too (e.g. `[""]` for a "no extra" baseline, or `["all"]`).                                              | No       | `[]`             |
| `dependencies`   | JSON array of package names whose version specifier is looked up in `[project].dependencies`, `[project.optional-dependencies]`, then `[dependency-groups]` (including `include-group`); first match wins, names compared per PEP 503. | No       | `[]`             |

## Outputs

| Name                    | Description                                                                                                                                                                                                                       |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`                  | Project name, as declared in `[project].name`.                                                                                                                                                                                    |
| `version`               | Project version, as declared in `[project].version`.                                                                                                                                                                              |
| `extras`                | JSON array of extra names, sorted, with `extra-values` prepended.                                                                                                                                                                 |
| `dependency-specifiers` | JSON object mapping each requested package to its specifier (e.g. `{"invoke-tasklib": ">=0.0.8,<1.0.0"}`). `null` if not found, `""` if the requirement has no specifier. A warning is emitted if different specifiers are found. |

## Failure modes

The action's step fails (non-zero exit) when:

- `pyproject-path` does not point to an existing file.
- The file is not valid TOML.
- `[project]` is missing the required `name` or `version` key.
- `[project]` is not a table, `name` is not a non-empty string, or `version` is
  not a string (for example `version = 1.0` is a TOML float; write
  `version = "1.0"`).
- `[project.optional-dependencies]` is not a table.
- `extra-values` is not valid JSON, or is not a JSON array of strings.
- `dependencies` is not a JSON array of strings.

## Development

```bash
pip install -r requirements-test.txt
python -m pytest -v
```
