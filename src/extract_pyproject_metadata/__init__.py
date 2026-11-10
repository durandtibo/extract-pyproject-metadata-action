"""Extract project metadata and dependency specifiers from a
pyproject.toml.

The command line interface is in ``extract_pyproject_metadata.cli``. Run it with
``python scripts/extract_metadata.py`` (what ``scripts/run.sh`` does) or with
``python -m extract_pyproject_metadata``.

The modules, from the bottom of the import graph to the top:

- ``errors``, ``types``, ``checks``, ``inputs``: the error, the typed report, the type checks
  of the values read from the file and the parsing of the inputs.
- ``pyproject``, ``metadata``: reading the file and its fields.
- ``requirements``, ``python_versions``: the requirements (``[project].dependencies``, the
  extras and the groups) and their lookup, and the Python versions that ``requires-python``
  allows.
- ``output`` (``escaping``, ``github``, ``summary``): the action outputs, the workflow
  commands and the job summary.
- ``report``: builds the report from the parts above.
- ``cli``: the argument parser and ``main``.
"""

from __future__ import annotations

from extract_pyproject_metadata.errors import MetadataError

__all__ = ["MetadataError"]
