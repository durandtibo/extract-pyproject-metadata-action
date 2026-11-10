"""Static resolution of a version listed in ``[project].dynamic``.

Some build backends read the version from a file of the project: the action can
find it there without running any code of the project (no import, no build
backend, no ``setuptools-scm``). Two declarations are understood:

- ``[tool.setuptools.dynamic].version`` with ``file`` (the text of the file) or
  ``attr`` (a ``__version__ = "1.2.3"`` literal of a module, found by parsing it
  with ``ast``, never by importing it);
- ``[tool.hatch.version]`` with ``path`` (and optionally ``pattern``), the
  default source ``regex`` of Hatch.

The files must be inside the directory of the pyproject.toml. A version that is
computed (from git tags, for example) cannot be resolved.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, cast

from extract_pyproject_metadata._vendor.packaging.version import InvalidVersion, Version

__all__ = ["HATCH_DEFAULT_PATTERN", "MAX_VERSION_FILE_BYTES", "read_dynamic_version"]

# The pattern of Hatch's ``regex`` version source when ``pattern`` is not set.
HATCH_DEFAULT_PATTERN = r"(?i)^(__version__|VERSION)(?: ?\: ?str)? *= *(['\"])v?(?P<version>.+?)\2"

# A file that holds a version is small: a bigger one is not read.
MAX_VERSION_FILE_BYTES = 1024 * 1024


def _table(parent: dict[str, Any], key: str) -> dict[str, Any]:
    """Return ``parent[key]`` if it is a table, an empty dict
    otherwise."""
    value = parent.get(key)
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def _read_text(base: Path, relative: str) -> str:
    """Read a text file of the project.

    Args:
        base: The directory of the pyproject.toml.
        relative: The path of the file, relative to ``base``.

    Returns:
        The content of the file.

    Raises:
        ValueError: If the file is outside ``base``, is missing, is too big,
            cannot be read or is not UTF-8. The message says why.
    """
    root = base.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        msg = f"{relative!r} is outside the directory of the pyproject.toml"
        raise ValueError(msg)
    if not path.is_file():
        msg = f"{relative!r} is not a file"
        raise ValueError(msg)
    try:
        with path.open("rb") as f:
            content = f.read(MAX_VERSION_FILE_BYTES + 1)
        if len(content) > MAX_VERSION_FILE_BYTES:
            msg = f"{relative!r} is bigger than {MAX_VERSION_FILE_BYTES} bytes"
            raise ValueError(msg)
        return content.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        msg = f"{relative!r} cannot be read: {exc}"
        raise ValueError(msg) from exc


def _module_candidates(module: str, package_dir: dict[str, Any]) -> list[str]:
    """List the files that can hold the module ``module``, in the order
    where setuptools looks for them.

    Args:
        module: The dotted name of the module (``pkg.sub``).
        package_dir: ``[tool.setuptools.package-dir]``.

    Returns:
        The paths, relative to ``base``, of ``<module>.py`` and
        ``<module>/__init__.py`` in the package directory that applies, then
        in ``src`` and in ``base`` itself when no directory is declared.
    """
    parts = module.split(".")
    roots: list[str] = []
    head = package_dir.get(parts[0])
    if isinstance(head, str):
        roots.append(head)
        parts = parts[1:]
    elif isinstance(package_dir.get(""), str):
        roots.append(package_dir[""])
    else:
        roots.extend(["src", "."])
    paths: list[str] = []
    for root in roots:
        prefix = Path(root, *parts)
        paths.extend([f"{prefix}.py", str(prefix / "__init__.py")])
    return paths


def _literal_attribute(source: str, name: str) -> str | None:
    """Return the string literal assigned to the module-level ``name``.

    Args:
        source: The source code of a module.
        name: The name of the variable.

    Returns:
        The value of the last assignment ``name = "..."`` (also annotated), or
        None if there is none or the value is not a string literal.

    Raises:
        SyntaxError: If ``source`` is not valid Python.
    """
    found: str | None = None
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            found = (
                value.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
                else None
            )
    return found


def _setuptools_attr(base: Path, attr: object, package_dir: dict[str, Any]) -> str:
    """Read the version from ``attr = "pkg.__version__"``.

    Raises:
        ValueError: With the reason why the version cannot be read.
    """
    if not isinstance(attr, str) or "." not in attr:
        msg = f"[tool.setuptools.dynamic].version attr must be 'module.name', got: {attr!r}"
        raise ValueError(msg)
    module, _, name = attr.rpartition(".")
    errors: list[str] = []
    for candidate in _module_candidates(module, package_dir):
        try:
            source = _read_text(base, candidate)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        try:
            value = _literal_attribute(source, name)
        except SyntaxError as exc:
            msg = f"{candidate!r} is not valid Python: {exc.msg}"
            raise ValueError(msg) from exc
        if value is None:
            msg = f"{name} is not a string literal in {candidate!r}"
            raise ValueError(msg)
        return value
    msg = f"no file for the module {module!r} ({'; '.join(errors)})"
    raise ValueError(msg)


def _setuptools_file(base: Path, files: object) -> str:
    """Read the version from ``file = "VERSION"`` (or a list of files).

    Raises:
        ValueError: With the reason why the version cannot be read.
    """
    names: object = [files] if isinstance(files, str) else files
    items = cast("list[Any]", names) if isinstance(names, list) else []
    if not items or not all(isinstance(item, str) for item in items):
        msg = f"[tool.setuptools.dynamic].version file must be a string or an array of strings, got: {files!r}"
        raise ValueError(msg)
    return "\n".join(_read_text(base, cast("str", name)) for name in items).strip()


def _hatch_regex(base: Path, hatch: dict[str, Any]) -> str:
    """Read the version with the ``regex`` source of Hatch.

    Raises:
        ValueError: With the reason why the version cannot be read.
    """
    source = hatch.get("source", "regex")
    path = hatch.get("path")
    pattern = hatch.get("pattern", HATCH_DEFAULT_PATTERN)
    if source != "regex":
        msg = f"[tool.hatch.version].source {source!r} is not supported (only 'regex')"
        raise ValueError(msg)
    if not isinstance(path, str) or not path:
        msg = "[tool.hatch.version] has no path"
        raise ValueError(msg)
    if not isinstance(pattern, str):
        msg = f"[tool.hatch.version].pattern must be a string, got: {pattern!r}"
        raise ValueError(msg)  # noqa: TRY004 (every reason is a ValueError)
    try:
        regex = re.compile(pattern, re.MULTILINE)
    except re.error as exc:
        msg = f"[tool.hatch.version].pattern is not a valid regular expression: {exc}"
        raise ValueError(msg) from exc
    if "version" not in regex.groupindex:
        msg = "[tool.hatch.version].pattern has no group named 'version'"
        raise ValueError(msg)
    match = regex.search(_read_text(base, path))
    if match is None:
        msg = f"the pattern of [tool.hatch.version] does not match in {path!r}"
        raise ValueError(msg)
    return match.group("version")


def read_dynamic_version(data: dict[str, Any], pyproject_path: str) -> tuple[str, str]:
    """Find the version that a build backend reads from a file of the
    project.

    Args:
        data: The parsed pyproject.toml.
        pyproject_path: Path of the file; the files of the version are looked
            up relative to its directory.

    Returns:
        A tuple ``(version, reason)``. ``version`` is the version, as written
        in the file (it is a valid PEP 440 version), or ``""`` when it cannot
        be resolved, and ``reason`` then says why (it is ``""`` otherwise).
    """
    base = Path(pyproject_path).parent
    tool = _table(data, "tool")
    setuptools = _table(tool, "setuptools")
    spec: object = _table(setuptools, "dynamic").get("version")
    hatch: object = _table(tool, "hatch").get("version")
    raw = ""
    try:
        spec_table = cast("dict[str, Any]", spec) if isinstance(spec, dict) else {}
        if "file" in spec_table:
            raw = _setuptools_file(base, spec_table["file"])
        elif "attr" in spec_table:
            raw = _setuptools_attr(base, spec_table["attr"], _table(setuptools, "package-dir"))
        elif isinstance(hatch, dict):
            raw = _hatch_regex(base, cast("dict[str, Any]", hatch))
        else:
            return "", (
                "no static source: only [tool.setuptools.dynamic].version (file or attr) and "
                "[tool.hatch.version] (path) are read"
            )
    except ValueError as exc:
        return "", str(exc)
    try:
        Version(raw)
    except InvalidVersion:
        return "", f"{raw!r} is not a valid PEP 440 version"
    return raw, ""
