SHELL = /bin/bash

include .make/help.mk
include .make/makefile.mk
include .make/markdown.mk
include .make/self.mk
include .make/shell.mk
include .make/toml.mk
include .make/uv.mk
include .make/yaml.mk

.DEFAULT_GOAL := help

PYTHON_RUN ?= uv run

.PHONY: install
install: install-uv ## Install the dependencies and the dev group in .venv
	uv sync --group dev

.PHONY: format
format: format-python format-yaml format-makefile format-shell format-toml format-markdown ## Format all files

.PHONY: format-python
format-python: ## Format the Python files
	$(PYTHON_RUN) ruff format src scripts tests

.PHONY: lint
lint: lint-python lint-yaml lint-makefile lint-shell lint-markdown ## Lint all files

.PHONY: lint-python
lint-python: ## Lint the Python files
	$(PYTHON_RUN) ruff check src scripts tests
	$(PYTHON_RUN) ruff format --check src scripts tests

.PHONY: types
types: ## Check the types of the package and the script (pyright, strict)
	$(PYTHON_RUN) pyright

.PHONY: test
test: ## Run the tests with the coverage gate
	$(PYTHON_RUN) pytest -q --cov

.PHONY: docs
docs: ## Generate the tables of README.md from action.yaml
	$(PYTHON_RUN) python scripts/generate_docs.py

.PHONY: docs-check
docs-check: ## Check that the tables of README.md are generated from action.yaml
	$(PYTHON_RUN) python scripts/generate_docs.py --check

.PHONY: vendor-packaging
vendor-packaging: ## Vendor a release of packaging: make vendor-packaging VERSION=x.y
	@test -n "$(VERSION)" || { echo "usage: make vendor-packaging VERSION=x.y" >&2; exit 1; }
	python3 scripts/vendor_packaging.py "$(VERSION)"

.PHONY: check
check: lint-python types test ## Run the Python checks (lint, format, types, tests)

.PHONY: fix
fix: ## Fix the lint errors and format the Python files
	$(PYTHON_RUN) ruff check --fix src scripts tests
	$(PYTHON_RUN) ruff format src scripts tests

.PHONY: clean
clean: ## Remove the generated coverage reports and caches
	rm -rf coverage.xml .coverage htmlcov .pytest_cache .ruff_cache .hypothesis
