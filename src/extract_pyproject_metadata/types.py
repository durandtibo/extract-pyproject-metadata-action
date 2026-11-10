"""The typed dictionaries of the metadata and of the JSON report."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

__all__ = [
    "Inputs",
    "Lookup",
    "Project",
    "Report",
    "ReportWarning",
    "Requirement",
    "WarningCode",
    "WarningItem",
]


# The stable identifiers of the warnings; ``warning_codes.WARNING_CODES`` documents each.
WarningCode = Literal[
    "static-and-dynamic",
    "dynamic-version",
    "invalid-requires-python",
    "no-python-version",
    "invalid-requirement",
    "include-group-cycle",
    "unknown-include-group",
    "dynamic-dependencies",
    "dependency-not-found",
]


@dataclass(frozen=True)
class ReportWarning:
    """A suspicious but usable input.

    Attributes:
        code: The stable identifier of the kind of warning.
        message: What is wrong, for a human (it may be reworded).
    """

    code: WarningCode
    message: str


class WarningItem(TypedDict):
    """A warning in the report: the ``code`` and the ``message``."""

    code: str
    message: str


@dataclass(frozen=True)
class Lookup:
    """One entry of the ``dependencies`` input, parsed by ``parse_dependencies``.

    Attributes:
        text: The entry as written, which is its key in the outputs.
        name: The package name, normalized per PEP 503.
        source: The only place to search (``"project"``, ``"extra:<name>"`` or
            ``"group:<name>"``, with the name normalized), or None to search every place.
    """

    text: str
    name: str
    source: str | None


@dataclass(frozen=True)
class Requirement:
    """A requirement of a package, as declared in one place of the file.

    Attributes:
        name: The package name, normalized per PEP 503.
        specifier: The version specifier, empty if there is none.
        marker: The environment marker, empty if there is none.
        source: The place that declares it (``"project"``, ``"extra:<name>"`` or
            ``"group:<name>"``).
    """

    name: str
    specifier: str
    marker: str
    source: str


@dataclass(frozen=True)
class Inputs:
    """The inputs of the action, validated and parsed by ``parse_inputs``."""

    pyproject_path: str
    extra_values: list[str]
    dependencies: list[Lookup]
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
    warnings: list[WarningItem]
    schema_version: int
