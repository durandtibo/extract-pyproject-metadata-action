"""Build the report from the parsed command line and the
pyproject.toml."""

from __future__ import annotations

from typing import TYPE_CHECKING

from extract_pyproject_metadata.dependencies.lookup import (
    check_no_missing_dependency,
    parse_dependencies,
    requirements_from_index,
    specifiers_from_index,
)
from extract_pyproject_metadata.dependencies.requirements import (
    dynamic_dependency_fields,
    extract_project_dependencies,
    index_dependencies,
)
from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.inputs import Options, parse_options, parse_string_array
from extract_pyproject_metadata.metadata import extract_metadata
from extract_pyproject_metadata.pyproject import load_pyproject
from extract_pyproject_metadata.python_versions import (
    compatible_python_versions,
    highest_python_version,
    lowest_python_version,
    parse_python_candidates,
)
from extract_pyproject_metadata.types import Report

if TYPE_CHECKING:
    import argparse

__all__ = ["SCHEMA_VERSION", "build_report"]

# The version of the JSON printed to stdout (the ``schema_version`` key of the report).
SCHEMA_VERSION = 1


def build_report(args: argparse.Namespace, options: Options | None = None) -> Report:
    """Read the pyproject.toml and the inputs of the command line, and
    build the report.

    Args:
        args: The parsed command line, as returned by ``_build_parser``.
        options: The parsed boolean inputs. Parsed from ``args`` when omitted.

    Returns:
        The report: the metadata, the Python versions, the dependency
        specifiers and the warnings (without duplicates).

    Raises:
        MetadataError: If an input or the pyproject.toml is invalid, the version
            is dynamic with ``--fail-on-dynamic-version true``, a dependency
            is not found with ``--fail-on-missing true``, or there is a
            warning with ``--strict true``.
    """
    if options is None:
        options = parse_options(args)
    data = load_pyproject(args.pyproject_path)
    extra_values = parse_string_array(args.extra_values, "extra-values")
    dependencies = parse_dependencies(args.dependencies)
    python_candidates = parse_python_candidates(args.python_candidates)
    metadata, warnings = extract_metadata(
        data, extra_values, args.pyproject_path, options.fail_on_dynamic_version
    )
    # Computed in the order of their warnings in the report: the metadata, the Python versions,
    # the dependencies of the project, then the lookups of the requested dependencies.
    python_versions, python_warnings = compatible_python_versions(
        metadata["requires_python"], python_candidates, args.pyproject_path
    )
    project_dependencies, project_warnings = extract_project_dependencies(data, args.pyproject_path)
    # The requirements of the file are read and parsed once, for both lookups.
    found, index_warnings = index_dependencies(data, args.pyproject_path)
    specifiers, specifier_warnings = specifiers_from_index(
        found, index_warnings, dependencies, args.pyproject_path
    )
    requirements = requirements_from_index(found, dependencies)
    warnings.extend(python_warnings)
    warnings.extend(project_warnings)
    warnings.extend(specifier_warnings)
    if options.fail_on_missing:
        check_no_missing_dependency(
            specifiers, args.pyproject_path, dynamic_dependency_fields(data)
        )
    warnings = list(dict.fromkeys(warnings))
    if options.strict and warnings:
        listed = "".join(f"\n- {warning}" for warning in warnings)
        msg = f"strict is 'true' and there are {len(warnings)} warning(s):{listed}"
        raise MetadataError(msg)
    return Report(
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
