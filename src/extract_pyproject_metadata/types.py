"""The typed dictionaries of the metadata and of the JSON report."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

__all__ = ["Inputs", "Metadata", "Report"]


@dataclass(frozen=True)
class Inputs:
    """The inputs of the action, validated and parsed by ``parse_inputs``."""

    pyproject_path: str
    extra_values: list[str]
    dependencies: list[str]
    python_candidates: list[str]
    strict: bool
    resolve_dynamic_version: bool


class Metadata(TypedDict):
    """The project metadata read by ``extract_metadata``."""

    name: str
    normalized_name: str
    file_name: str
    version: str
    normalized_version: str
    requires_python: str
    extras: list[str]
    groups: list[str]


class Report(Metadata):
    """The metadata, Python versions, dependency specifiers and warnings
    built by ``build_report``."""

    python_versions: list[str]
    python_min: str
    python_max: str
    dependency_specifiers: dict[str, str | None]
    dependency_requirements: dict[str, list[dict[str, str]]]
    warnings: list[str]
    schema_version: int
