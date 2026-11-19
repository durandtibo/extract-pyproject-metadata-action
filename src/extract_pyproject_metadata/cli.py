"""Entry point of the action: read the inputs from the environment, build the report and
write the outputs.

The program takes no argument (the launcher ignores any). The inputs are the ``INPUT_*``
variables of the action (named by ``env_name``; an input that is not set has its default of
``inputs.DEFAULT_INPUTS``). A local run is:

    INPUT_PYPROJECT_PATH=path/to/pyproject.toml python scripts/extract_metadata.py

Without ``GITHUB_OUTPUT``, the ``json`` object is printed to stdout. With it (set by GitHub in
a workflow), the outputs are appended to the file it names and the annotations and the log line
are printed to stdout.

The exit code is 0, or 1 with ``<field>: <problem>`` on stderr (with ``GITHUB_OUTPUT``, also an
``::error`` annotation).

The inputs and outputs are defined in ``action.yaml``, the keys of the ``json`` object in
``types.Report``, the warning codes in ``warning_codes.py``, and the causes of failure in the
README.
"""

from __future__ import annotations

import io
import json
import os
import sys
from typing import TYPE_CHECKING

from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.github import emit_github_output, format_error
from extract_pyproject_metadata.inputs import DEFAULT_INPUTS, parse_inputs
from extract_pyproject_metadata.report import build_report

if TYPE_CHECKING:
    from collections.abc import Mapping

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


def main(environ: Mapping[str, str] | None = None) -> int:
    """Run the program and return the process exit code.

    Args:
        environ: The environment variables, ``os.environ`` by default.

    Returns:
        0 on success, 1 when the input or the file is invalid (or with ``strict`` when there
        is a warning).
    """
    environ = os.environ if environ is None else environ
    github_output = environ.get("GITHUB_OUTPUT") or None

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
    """Run the program as the launcher does: UTF-8 streams and the
    environment.

    The log line has non-ASCII characters, which a non-UTF-8 locale cannot encode, so the
    standard output and error are switched to UTF-8 first. A non-UTF-8 locale also decodes
    the bytes of the environment as surrogates, so the values are decoded again as UTF-8.

    Returns:
        The exit code of ``main``.
    """
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    environ = {
        key: os.fsencode(value).decode("utf-8", errors="surrogateescape")
        for key, value in os.environ.items()
    }
    return main(environ)
