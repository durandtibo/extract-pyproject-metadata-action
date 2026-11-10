"""Build the report from the parsed inputs and the pyproject.toml."""

from __future__ import annotations

from extract_pyproject_metadata._vendor.packaging.utils import canonicalize_name
from extract_pyproject_metadata._vendor.packaging.version import Version
from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.pyproject import load_pyproject, read_project
from extract_pyproject_metadata.python_versions import (
    compatible_python_versions,
    highest_python_version,
    lowest_python_version,
)
from extract_pyproject_metadata.requirements import (
    collect_requirements,
    lookup_requirements,
    lookup_specifiers,
)
from extract_pyproject_metadata.types import Inputs, Report

__all__ = ["SCHEMA_VERSION", "build_report"]

# The version of the JSON printed to stdout (the ``schema_version`` key of the report).
SCHEMA_VERSION = 2


def build_report(inputs: Inputs) -> Report:
    """Read the pyproject.toml and build the report.

    Args:
        inputs: The parsed inputs, as returned by ``parse_inputs``.

    Returns:
        The report: the project fields, the Python versions, the dependency
        specifiers and the warnings (without duplicates).

    Raises:
        MetadataError: If the pyproject.toml is invalid, or there is a
            warning with ``strict``.
    """
    data = load_pyproject(inputs.pyproject_path)
    project, warnings = read_project(data, inputs.extra_values, inputs.pyproject_path)
    # Computed in the order of their warnings in the report: the metadata, the Python versions,
    # then the lookups of the requested dependencies.
    python_versions, python_warnings = compatible_python_versions(
        project.requires_python, inputs.python_candidates, inputs.pyproject_path
    )
    # The requirement tables are read only for a lookup: without one, a broken table is not
    # the business of the action.
    specifiers: dict[str, str | None] = {}
    requirements: dict[str, list[dict[str, str]]] = {}
    lookup_warnings: list[str] = []
    if inputs.dependencies:
        # The requirements of the file are read and parsed once, for both lookups.
        found, found_warnings = collect_requirements(data, project.dynamic, inputs.pyproject_path)
        specifiers, missing_warnings = lookup_specifiers(
            found, inputs.dependencies, inputs.pyproject_path
        )
        requirements = lookup_requirements(found, inputs.dependencies)
        lookup_warnings = [*found_warnings, *missing_warnings]
    warnings.extend(python_warnings)
    warnings.extend(lookup_warnings)
    unique_warnings = list(dict.fromkeys(warnings))
    normalized_name = canonicalize_name(project.name)
    report = Report(
        name=project.name,
        normalized_name=normalized_name,
        file_name=normalized_name.replace("-", "_"),
        version=project.version or "",
        normalized_version=str(Version(project.version)) if project.version else "",
        requires_python=project.requires_python,
        extras=project.extras,
        groups=project.groups,
        python_versions=python_versions,
        python_min=lowest_python_version(python_versions),
        python_max=highest_python_version(python_versions),
        dependency_specifiers=specifiers,
        dependency_requirements=requirements,
        warnings=unique_warnings,
        schema_version=SCHEMA_VERSION,
    )
    if inputs.strict and unique_warnings:
        listed = "".join(f"\n- {warning}" for warning in unique_warnings)
        msg = f"strict is 'true' and there are {len(unique_warnings)} warning(s):{listed}"
        raise MetadataError(msg)
    return report
