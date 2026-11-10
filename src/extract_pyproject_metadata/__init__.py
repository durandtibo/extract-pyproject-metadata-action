"""Extract project metadata and dependency specifiers from a
pyproject.toml.

The command line interface is in ``extract_pyproject_metadata.cli``. Run it with
``python scripts/extract_metadata.py`` (what ``scripts/run.sh`` does) or with
``python -m extract_pyproject_metadata``.

The modules, from the bottom of the import graph to the top:

- ``errors``, ``types``, ``warning_codes``, ``checks``, ``inputs``: the error, the typed
  values, the documentation of the warnings, the type checks of the values read from the file
  and the parsing of the inputs.
- ``pyproject``: reading the file and the fields that the action outputs.
- ``requirements``, ``python_versions``: the requirements (``[project].dependencies``, the
  extras and the groups) and their lookup, and the Python versions that ``requires-python``
  allows.
- ``github``: the action outputs, the workflow commands (annotations) and the log line.
- ``report``: builds the report from the parts above.
- ``cli``: ``main``, which reads the inputs from the environment.
"""

from __future__ import annotations

from extract_pyproject_metadata.errors import MetadataError

__all__ = ["MetadataError"]
