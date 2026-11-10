r"""Extract project metadata and dependency specifiers from a
pyproject.toml.

The metadata is the project name and version (and their normalized forms), the
name as it is written in the file names of wheels and sdists, ``requires-python``,
and the optional-dependency extras and dependency groups. The script also selects
the Python versions that ``requires-python`` allows, and looks up the dependencies that
it is asked to.

Usage:
    extract_metadata.py [--github-output FILE] [--resolve-dynamic-version true|false]
        [--strict true|false]
        [--python-candidates JSON] [--] <pyproject-path> <extra-values-json>
        [<dependencies-json>]

A name of ``<dependencies-json>`` may be followed by ``@project``, ``@extra:<name>`` or
``@group:<name>`` to look it up in ``[project].dependencies``, one extra or one dependency
group only (``numpy@extra:fast``); the key of the result is the entry as written.

Without ``--github-output``, prints a single JSON object to stdout (non-ASCII
characters are kept as they are, as in the action outputs):
    {"name": ..., "normalized_name": ..., "file_name": ...,
     "version": ..., "normalized_version": ..., "requires_python": ...,
     "extras": [...], "groups": [...],
     "python_versions": [...], "python_min": ..., "python_max": ...,
     "dependency_specifiers": {...}, "dependency_requirements": {...},
     "warnings": [...], "schema_version": 1}

"warnings" lists human-readable messages about suspicious but non-fatal
input.

"schema_version" is the version of this JSON object: it increases when a key is
renamed, removed or changes type, not when a key is added, so that a tool that
reads the object can check it.

With ``--github-output FILE`` (used by action.yaml), appends the action
outputs to FILE (the format of ``$GITHUB_OUTPUT``, with a delimiter so that
values may contain line breaks). They are ``name``, ``normalized-name``, ``file-name``,
``version``, ``normalized-version``, ``requires-python``, ``python-versions``,
``python-min``, ``python-max``, ``extras``, ``groups``, ``dependency-specifiers`` and
``json`` (the JSON object that is printed without the option, in compact form). It also prints to stdout one
``::warning file=<path>::`` workflow command per warning, where ``<path>`` is
the pyproject path, so that GitHub attaches the annotation to the file,
followed by a one-line summary of the outputs. Warnings are printed on stdout
because GitHub only parses workflow commands there.

When there are warnings, or when the run fails, it also appends them (or the error
message) as a short Markdown list to the file named by the ``GITHUB_STEP_SUMMARY``
environment variable (the job summary of GitHub), if it is set. Nothing is written
otherwise.

With ``--strict true``, any warning is an error instead: the outputs are not
written and the message lists the warnings. A requested dependency that is not
found (a ``null`` specifier) and a dynamic ``version`` are warnings.

With ``--resolve-dynamic-version true``, a ``version`` that is listed in
``[project].dynamic`` is looked for in the file that the build backend reads it
from, without running any code of the project: ``[tool.setuptools.dynamic].version``
(``file``, or ``attr`` for a ``__version__ = "..."`` literal) and ``[tool.hatch.version]``
(``path`` and ``pattern``). A version that is found is used as a static one (so it
is not a warning); otherwise the reason is a warning, followed by the usual
handling of a dynamic version.

``python_versions`` lists the ``--python-candidates`` (a JSON array of
"major.minor" strings) that ``[project].requires-python`` allows, and
``python_min`` is the lowest of them and ``python_max`` the highest (each an
empty string if there is none).

Exits non-zero with a message on stderr (with ``--github-output FILE``, an
``::error file=<path>::`` workflow command, so that GitHub shows an error
annotation on the file) if the file is missing, cannot be read, is not UTF-8 or
is not valid TOML, the outputs or the job summary cannot be written, [project]
is missing the required "name"/"version" keys, a field that is read ([project].name,
version, requires-python, dependencies or optional-dependencies, or
[dependency-groups]) has the wrong type, an input is not valid JSON of the expected shape, a Python candidate is not a "major.minor" string,
``--strict true`` is given and there is a warning, or a requested dependency has a scope
that is not ``project``, ``extra:<name>`` or ``group:<name>``.

A wrong command line (which the action never builds) prints the usage and the
problem on stderr and exits with the code 2, as ``argparse`` does; with
``--github-output FILE`` it is one ``::error::`` workflow command instead.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.inputs import DEFAULT_PYTHON_CANDIDATES, parse_inputs
from extract_pyproject_metadata.output.escaping import (
    escape_annotation,
)
from extract_pyproject_metadata.output.github import (
    emit_github_output,
    format_error,
)
from extract_pyproject_metadata.output.summary import (
    format_error_summary,
    format_warning_summary,
    resolve_summary_path,
    write_step_summary,
)
from extract_pyproject_metadata.report import build_report

if TYPE_CHECKING:
    from extract_pyproject_metadata.types import Inputs

__all__ = ["main", "parse_cli_inputs"]


class _ArgumentParser(argparse.ArgumentParser):
    """An argument parser whose usage errors can be GitHub error
    annotations.

    Attributes:
        annotate: Whether ``error`` prints a ``::error::`` workflow command (so that GitHub shows
            an error annotation) instead of the usage and the message.
    """

    annotate = False

    def error(self, message: str) -> NoReturn:
        """Print the usage error on stderr and exit with the code 2,
        like ``argparse``.

        Args:
            message: What is wrong with the command line.
        """
        text = f"{self.format_usage().rstrip()}\n{self.prog}: error: {message}"
        if self.annotate:
            text = f"::error::{escape_annotation(text)}"
        print(text, file=sys.stderr)
        self.exit(2)


def _build_parser(prog: str) -> _ArgumentParser:
    """Build the command line parser."""
    # ``__doc__`` is None when Python runs with -OO, which strips docstrings.
    description = (__doc__ or "").split("\n", 1)[0]
    parser = _ArgumentParser(prog=prog, description=description)
    parser.add_argument(
        "--github-output",
        metavar="FILE",
        help="append the action outputs to FILE and print workflow commands instead of JSON",
    )
    parser.add_argument(
        "--resolve-dynamic-version",
        metavar="BOOL",
        default="false",
        help="'true' to read a dynamic version from the file of the build backend (default: false)",
    )
    parser.add_argument(
        "--strict",
        metavar="BOOL",
        default="false",
        help="'true' to fail when there is a warning (default: false)",
    )
    parser.add_argument(
        "--python-candidates",
        metavar="JSON",
        default=DEFAULT_PYTHON_CANDIDATES,
        help=(
            "JSON array of 'major.minor' Python versions to select from, using requires-python "
            f"(default: {DEFAULT_PYTHON_CANDIDATES})"
        ),
    )
    parser.add_argument("pyproject_path", help="path to pyproject.toml")
    parser.add_argument("extra_values", help="JSON array of extra values to prepend")
    parser.add_argument(
        "dependencies", nargs="?", default="[]", help="JSON array of package names to look up"
    )
    return parser


def parse_cli_inputs(args: argparse.Namespace) -> Inputs:
    """Map the parsed command line to the parsed inputs of the action.

    Args:
        args: The parsed command line, as returned by ``_build_parser``.

    Returns:
        The validated inputs.

    Raises:
        MetadataError: If an input is invalid.
    """
    return parse_inputs(
        {
            "pyproject-path": args.pyproject_path,
            "extra-values": args.extra_values,
            "dependencies": args.dependencies,
            "python-candidates": args.python_candidates,
            "strict": args.strict,
            "resolve-dynamic-version": args.resolve_dynamic_version,
        }
    )


def main(argv: list[str]) -> int:
    """Run the command line interface and return the process exit
    code."""
    parser = _build_parser(Path(argv[0]).name)
    # The arguments are not parsed yet when one is wrong: look for the option as it is written.
    parser.annotate = any(arg.split("=", 1)[0] == "--github-output" for arg in argv[1:])
    try:
        args = parser.parse_args(argv[1:])
    except SystemExit as exc:  # argparse exits on bad arguments and on --help
        return exc.code if isinstance(exc.code, int) else 2

    summary_path: str | None = None
    try:
        inputs = parse_cli_inputs(args)
        summary_path = resolve_summary_path(os.environ)
        report = build_report(inputs)
        if args.github_output is None:
            # Like the action outputs, keep non-ASCII characters as they are.
            print(json.dumps(report, ensure_ascii=False))
        else:
            emit_github_output(report, args.pyproject_path, args.github_output)
        if summary_path is not None and report["warnings"]:
            write_step_summary(summary_path, format_warning_summary(report["warnings"]))
    except MetadataError as exc:
        annotate = args.github_output is not None
        print(format_error(str(exc), args.pyproject_path, annotate), file=sys.stderr)
        if summary_path is not None:
            # The error is already reported: a summary that cannot be written is not worth another.
            with contextlib.suppress(MetadataError):
                write_step_summary(summary_path, format_error_summary(str(exc)))
        return 1
    return 0
