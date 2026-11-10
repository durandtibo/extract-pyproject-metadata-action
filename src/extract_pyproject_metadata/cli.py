r"""Extract project metadata and dependency specifiers from a
pyproject.toml.

The metadata is the project name and version (and their normalized forms), the
name as it is written in the file names of wheels and sdists, ``requires-python``,
and the optional-dependency extras and dependency groups. The program also selects
the Python versions that ``requires-python`` allows, and looks up the dependencies that
it is asked to.

Usage:
    The program takes no argument. The inputs of the action are read from the environment
    variables ``INPUT_PYPROJECT_PATH``, ``INPUT_EXTRA_VALUES``, ``INPUT_DEPENDENCIES``,
    ``INPUT_PYTHON_CANDIDATES`` and ``INPUT_STRICT`` (an input that is not set has the default
    of ``action.yaml``). A local run is:

        INPUT_PYPROJECT_PATH=path/to/pyproject.toml python -m extract_pyproject_metadata

A name of ``INPUT_DEPENDENCIES`` (a JSON array) may be followed by ``@project``,
``@extra:<name>`` or ``@group:<name>`` to look it up in ``[project].dependencies``, one
extra or one dependency group only (``numpy@extra:fast``); the key of the result is the entry
as written.

Without ``GITHUB_OUTPUT``, prints a single JSON object to stdout (non-ASCII
characters are kept as they are, as in the action outputs):
    {"name": ..., "normalized_name": ..., "file_name": ...,
     "version": ..., "normalized_version": ..., "requires_python": ...,
     "extras": [...], "groups": [...],
     "python_versions": [...], "python_min": ..., "python_max": ...,
     "dependency_specifiers": {...}, "dependency_requirements": {...},
     "warnings": [...], "schema_version": 1}

"warnings" lists the suspicious but non-fatal input as objects with a ``code`` (a stable
identifier, see ``warning_codes.py``) and a ``message`` (for a human, it may be reworded).

"schema_version" is the version of this JSON object: it increases when a key is
renamed, removed or changes type, not when a key is added, so that a tool that
reads the object can check it.

With ``GITHUB_OUTPUT`` (set by GitHub in a workflow), appends the action
outputs to the file it names (with a delimiter so that values may contain line breaks).
They are ``name``, ``normalized-name``, ``file-name``,
``version``, ``normalized-version``, ``requires-python``, ``python-versions``,
``python-min``, ``python-max``, ``extras``, ``groups``, ``dependency-specifiers`` and
``json`` (the JSON object that is printed without the variable, in compact form). It also
prints to stdout one ``::warning file=<path>,title=<code>::`` workflow command per warning,
where ``<path>`` is the pyproject path, so that GitHub attaches the annotation to the file,
followed by a one-line log line of the outputs. Warnings are printed on stdout
because GitHub only parses workflow commands there.

With ``INPUT_STRICT=true``, any warning is an error instead: the outputs are not
written and the message lists the warnings. A requested dependency that is not
found (a ``null`` specifier) and a dynamic ``version`` are warnings.

``python_versions`` lists the ``INPUT_PYTHON_CANDIDATES`` (a JSON array of
"major.minor" strings) that ``[project].requires-python`` allows, and
``python_min`` is the lowest of them and ``python_max`` the highest (each an
empty string if there is none).

Exits with 1 and a message ``<field>: <problem>`` on stderr (with ``GITHUB_OUTPUT``, an
``::error file=<path>::`` workflow command, so that GitHub shows an error annotation on the
file) if an input is invalid, the file is missing, cannot be read, is not UTF-8 or is not
valid TOML, a field that is read has the wrong type or is missing, ``INPUT_STRICT=true`` and
there is a warning, or the outputs cannot be written.

An argument on the command line (which the action never passes) is a usage error: the
message goes to stderr (as an ``::error::`` workflow command with ``GITHUB_OUTPUT``) and the
exit code is 2.
"""

from __future__ import annotations

import io
import json
import os
import sys
from typing import TYPE_CHECKING

from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.github import emit_github_output, escape_annotation, format_error
from extract_pyproject_metadata.inputs import DEFAULT_INPUTS, parse_inputs
from extract_pyproject_metadata.report import build_report

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from extract_pyproject_metadata.types import Inputs

__all__ = ["env_name", "main", "read_inputs", "run"]


def env_name(input_name: str) -> str:
    """Return the environment variable of an input of the action.

    Args:
        input_name: The name of the input, such as ``pyproject-path``.

    Returns:
        ``INPUT_`` and the name in upper case with ``_`` instead of ``-``
        (``INPUT_PYPROJECT_PATH``).
    """
    return "INPUT_" + input_name.upper().replace("-", "_")


def read_inputs(environ: Mapping[str, str]) -> Inputs:
    """Read and validate the inputs of the action from the environment.

    Args:
        environ: The environment variables. An input whose variable is not set takes its
            default.

    Returns:
        The validated inputs.

    Raises:
        MetadataError: If an input is invalid.
    """
    raw = {name: environ[env_name(name)] for name in DEFAULT_INPUTS if env_name(name) in environ}
    return parse_inputs(raw)


def _usage_error(arguments: Sequence[str], annotate: bool) -> int:
    """Print the usage error of a command line with arguments and return
    the exit code 2."""
    message = (
        f"extract_pyproject_metadata: error: unexpected arguments {list(arguments)!r}: the "
        "inputs are read from the environment variables "
        + ", ".join(env_name(name) for name in DEFAULT_INPUTS)
    )
    print(f"::error::{escape_annotation(message)}" if annotate else message, file=sys.stderr)
    return 2


def main(environ: Mapping[str, str] | None = None, arguments: Sequence[str] = ()) -> int:
    """Run the program and return the process exit code.

    Args:
        environ: The environment variables, ``os.environ`` by default.
        arguments: The arguments of the command line, which must be empty.

    Returns:
        0 on success, 1 when the input or the file is invalid (or with ``strict`` when there
        is a warning), 2 when there are arguments.
    """
    environ = os.environ if environ is None else environ
    github_output = environ.get("GITHUB_OUTPUT") or None
    if arguments:
        return _usage_error(arguments, annotate=github_output is not None)

    pyproject_path = environ.get(env_name("pyproject-path"), DEFAULT_INPUTS["pyproject-path"])
    try:
        inputs = read_inputs(environ)
        report = build_report(inputs)
        if github_output is None:
            # Like the action outputs, keep non-ASCII characters as they are.
            print(json.dumps(report, ensure_ascii=False))
        else:
            emit_github_output(report, inputs.pyproject_path, github_output)
    except MetadataError as exc:
        print(
            format_error(str(exc), pyproject_path, annotate=github_output is not None),
            file=sys.stderr,
        )
        return 1
    return 0


def run() -> int:
    """Run the program as the entry points do: UTF-8 streams, the
    environment and the arguments.

    The log line has non-ASCII characters, which a non-UTF-8 locale cannot encode, so the
    standard output and error are switched to UTF-8 first.

    Returns:
        The exit code of ``main``.
    """
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    return main(os.environ, sys.argv[1:])
