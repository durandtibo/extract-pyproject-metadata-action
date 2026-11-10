"""Build the report from the parsed inputs and the pyproject.toml."""

from __future__ import annotations

from extract_pyproject_metadata.dependencies.lookup import (
    requirements_from_index,
    specifiers_from_index,
)
from extract_pyproject_metadata.dependencies.requirements import (
    extract_project_dependencies,
    index_dependencies,
)
from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.metadata import extract_metadata
from extract_pyproject_metadata.output.github import format_outputs, oversized_outputs
from extract_pyproject_metadata.pyproject import load_pyproject
from extract_pyproject_metadata.python_versions import (
    compatible_python_versions,
    highest_python_version,
    lowest_python_version,
)
from extract_pyproject_metadata.types import Inputs, Report

__all__ = ["SCHEMA_VERSION", "build_report"]

# The version of the JSON printed to stdout (the ``schema_version`` key of the report).
SCHEMA_VERSION = 1


def build_report(inputs: Inputs) -> Report:
    """Read the pyproject.toml and build the report.

    Args:
        inputs: The parsed inputs, as returned by ``parse_inputs``.

    Returns:
        The report: the metadata, the Python versions, the dependency
        specifiers and the warnings (without duplicates).

    Raises:
        MetadataError: If the pyproject.toml is invalid, or there is a
            warning with ``strict``.
    """
    data = load_pyproject(inputs.pyproject_path)
    metadata, warnings = extract_metadata(
        data,
        inputs.extra_values,
        inputs.pyproject_path,
        inputs.resolve_dynamic_version,
    )
    # Computed in the order of their warnings in the report: the metadata, the Python versions,
    # the dependencies of the project, then the lookups of the requested dependencies.
    python_versions, python_warnings = compatible_python_versions(
        metadata["requires_python"], inputs.python_candidates, inputs.pyproject_path
    )
    project_dependencies, project_warnings = extract_project_dependencies(
        data, inputs.pyproject_path
    )
    # The requirements of the file are read and parsed once, for both lookups.
    found, index_warnings = index_dependencies(data, inputs.pyproject_path)
    specifiers, specifier_warnings = specifiers_from_index(
        found, index_warnings, inputs.dependencies, inputs.pyproject_path
    )
    requirements = requirements_from_index(found, inputs.dependencies)
    warnings.extend(python_warnings)
    warnings.extend(project_warnings)
    warnings.extend(specifier_warnings)
    report = Report(
        **metadata,
        python_versions=python_versions,
        python_min=lowest_python_version(python_versions),
        python_max=highest_python_version(python_versions),
        project_dependencies=project_dependencies,
        dependency_specifiers=specifiers,
        dependency_requirements=requirements,
        warnings=warnings,
        schema_version=SCHEMA_VERSION,
    )
    large = oversized_outputs(format_outputs(report))
    if large:
        names = ", ".join(large)
        warnings.append(
            f"The output(s) {names} are close to the size limit of a GitHub step output "
            "(1 MiB): the step may fail to set them"
        )
    report["warnings"] = list(dict.fromkeys(warnings))
    if inputs.strict and report["warnings"]:
        listed = "".join(f"\n- {warning}" for warning in report["warnings"])
        msg = f"strict is 'true' and there are {len(report['warnings'])} warning(s):{listed}"
        raise MetadataError(msg)
    return report
