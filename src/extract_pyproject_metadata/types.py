"""The typed dictionaries of the metadata and of the JSON report."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

__all__ = ["Inputs", "Metadata", "Report", "StepSummary"]

# The values of the ``step-summary`` input: always, never, or only when there are warnings
# (or when the run fails).
StepSummary = Literal["true", "false", "auto"]


@dataclass(frozen=True)
class Inputs:
    """The inputs of the action, validated and parsed by ``parse_inputs``."""

    pyproject_path: str
    extra_values: list[str]
    dependencies: list[str]
    python_candidates: list[str]
    fail_on_missing: bool
    fail_on_dynamic_version: bool
    strict: bool
    step_summary: StepSummary
    resolve_dynamic_version: bool


class Metadata(TypedDict):
    """The project metadata read by ``extract_metadata``."""

    name: str
    normalized_name: str
    version: str
    normalized_version: str
    description: str
    readme: str
    license: str
    license_files: list[str]
    authors: list[dict[str, str]]
    urls: dict[str, str]
    keywords: list[str]
    classifiers: list[str]
    scripts: dict[str, str]
    requires_python: str
    extras: list[str]
    groups: list[str]
    build_backend: str
    build_requires: list[str]


class Report(Metadata):
    """The metadata, Python versions, lowest Python version, dependency
    specifiers and warnings built by ``build_report``."""

    python_versions: list[str]
    python_min: str
    python_max: str
    project_dependencies: dict[str, str]
    dependency_specifiers: dict[str, str | None]
    dependency_requirements: dict[str, list[dict[str, str]]]
    warnings: list[str]
    schema_version: int
