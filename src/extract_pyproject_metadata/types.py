"""The typed dictionaries of the metadata and of the JSON report."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

__all__ = ["Inputs", "Project", "Report"]


@dataclass(frozen=True)
class Inputs:
    """The inputs of the action, validated and parsed by ``parse_inputs``."""

    pyproject_path: str
    extra_values: list[str]
    dependencies: list[str]
    python_candidates: list[str]
    strict: bool


@dataclass(frozen=True)
class Project:
    """The fields of the file that the action outputs, read and validated
    once by ``read_project``.

    Attributes:
        name: ``[project].name`` as written (a valid PEP 508 name).
        version: ``[project].version`` as written (a valid PEP 440 version), or None when the
            version is dynamic and has no static value.
        requires_python: ``[project].requires-python`` as written, empty if not declared.
        dynamic: The fields listed in ``[project].dynamic``.
        extras: The ``extra-values`` first, then the names of the extras, sorted by normalized
            name, without duplicates.
        groups: The names of the dependency groups, sorted by normalized name, without
            duplicates.
    """

    name: str
    version: str | None
    requires_python: str
    dynamic: frozenset[str]
    extras: list[str]
    groups: list[str]


class Report(TypedDict):
    """The JSON report built by ``build_report``: the metadata, the Python
    versions, the dependency specifiers and the warnings."""

    name: str
    normalized_name: str
    file_name: str
    version: str
    normalized_version: str
    requires_python: str
    extras: list[str]
    groups: list[str]
    python_versions: list[str]
    python_min: str
    python_max: str
    dependency_specifiers: dict[str, str | None]
    dependency_requirements: dict[str, list[dict[str, str]]]
    warnings: list[str]
    schema_version: int
