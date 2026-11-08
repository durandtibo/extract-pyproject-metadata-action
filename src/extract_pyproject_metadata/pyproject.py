"""Read and parse a pyproject.toml file."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from extract_pyproject_metadata.errors import MetadataError

__all__ = ["UTF8_BOM", "load_pyproject"]

# The UTF-8 byte order mark that some editors write at the start of a file.
UTF8_BOM = b"\xef\xbb\xbf"


def load_pyproject(pyproject_path: str) -> dict[str, Any]:
    """Read and parse a pyproject.toml file.

    Args:
        pyproject_path: Path to the pyproject.toml file.

    Returns:
        The parsed TOML document. A UTF-8 byte order mark at the start of the
        file is ignored.

    Raises:
        MetadataError: If the file is missing, cannot be read (for example for
            lack of permission), is not UTF-8, is not valid TOML or has arrays or inline
            tables nested too deeply for the parser.
    """
    path = Path(pyproject_path)
    if not path.is_file():
        msg = f"pyproject.toml not found at: {pyproject_path}"
        raise MetadataError(msg)
    try:
        with path.open("rb") as f:
            content = f.read()
        # Some editors (on Windows) start a UTF-8 file with a byte order mark, which TOML rejects.
        return tomllib.loads(content.removeprefix(UTF8_BOM).decode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        msg = f"{pyproject_path} is not valid TOML: {exc}"
        raise MetadataError(msg) from exc
    except UnicodeDecodeError as exc:
        msg = f"{pyproject_path} is not valid UTF-8: {exc}"
        raise MetadataError(msg) from exc
    except RecursionError as exc:  # tomllib recurses on nested arrays and inline tables
        msg = f"{pyproject_path} is nested too deeply to be parsed"
        raise MetadataError(msg) from exc
    except OSError as exc:
        msg = f"{pyproject_path} cannot be read: {exc}"
        raise MetadataError(msg) from exc
