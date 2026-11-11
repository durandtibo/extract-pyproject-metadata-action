# Contributing

Thank you for your interest in contributing to `extract-pyproject-metadata-action`.
This project follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## Reporting issues

- Search the existing issues first.
- If none matches, open a new issue with a clear title, the `pyproject.toml` and the
  action inputs that reproduce the problem, the expected and the actual result, and the
  runner (Linux or macOS).

## Submitting changes

- Fork the repository and branch from an up to date `main`. Name the branch
  `<type>/<short-description>` in lowercase kebab-case, with a type among `feat`,
  `bugfix`, `hotfix`, `docs`, `refactor`, `perf`, `test`, `chore` and `ci`.
- One branch and one pull request per logical change.
- Match the style of the surrounding code, and add or update the tests: every new or
  changed function and every fixed bug needs one, and the coverage gate is 100 %.
- Run `make fix` and `make check` before you push.
- Write clear commit messages.
- In the pull request description, say what changed, what you deliberately did not change,
  and any change of behaviour (an input, a default or an output of the action).
- Workflows cannot be run locally: say so in the pull request instead of claiming they pass.

Windows is not supported, on purpose; changes that add it are not accepted.

## Development setup

- Python 3.11 or later, on Linux or macOS.
- `uv` for the `make` targets (`make install` creates `.venv`).

```bash
make install
make check
```

`make help` lists the targets. To run the action locally, point it at a file:

```bash
INPUT_PYPROJECT_PATH=path/to/pyproject.toml python scripts/extract_metadata.py
```

The architecture, the conventions and the tests are described in [CLAUDE.md](CLAUDE.md).
Do not edit `.make/` (synced by a bot) or the vendored `packaging` (use
`make vendor-packaging VERSION=x.y`).

## Documentation to update

- `README.md` for a change of inputs, outputs or failures; run `make docs` to regenerate
  its tables.
- `test-data/<case>/` for a new golden case.

Release notes go to the GitHub release, there is no changelog file.
