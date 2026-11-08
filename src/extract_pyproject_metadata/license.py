"""The license of [project]: its text and the validation of an SPDX expression."""

from __future__ import annotations

from extract_pyproject_metadata.checks import check_str
from extract_pyproject_metadata.errors import MetadataError

try:
    from packaging.licenses import InvalidLicenseExpression, canonicalize_license_expression
except ImportError:  # packaging before 24.2 cannot validate license expressions
    # Only the None checks of ``license_warnings`` use these names without the import.
    InvalidLicenseExpression = None  # type: ignore[assignment,misc]
    canonicalize_license_expression = None  # type: ignore[assignment]


def read_license_text(license_: object, pyproject_path: str) -> str:
    """Return the license declared by ``[project].license``.

    Args:
        license_: The value of ``[project].license``: an SPDX license expression
            (a string, PEP 639), or the table of PEP 621 with a ``text`` (the
            name or the text of the license) or a ``file`` (path).
        pyproject_path: Path of the file, used in the error message.

    Returns:
        The expression or the ``text`` as written, or an empty string if
        ``license_`` is empty, is not declared, or is a table without ``text``
        (a ``file``).

    Raises:
        MetadataError: If ``license_`` is neither a string nor a table, or its
            ``text`` or ``file`` is not a string.
    """
    if isinstance(license_, str):
        return license_
    if not isinstance(license_, dict):
        msg = f"{pyproject_path}: [project].license must be a string or a table, got: {license_!r}"
        raise MetadataError(msg)
    file = check_str(license_.get("text", ""), "[project].license.text", pyproject_path)
    check_str(license_.get("file", ""), "[project].license.file", pyproject_path)
    return file


def license_warnings(license_: object, pyproject_path: str) -> list[str]:
    """Describe a ``[project].license`` that is not a valid SPDX license expression.

    Only an expression (a string, PEP 639) is checked: not the table of PEP 621, and not an
    empty string. The check needs ``packaging`` 24.2 or later; with an older one, nothing is
    checked.

    Args:
        license_: The value of ``[project].license``.
        pyproject_path: Path of the file, used in the message.

    Returns:
        One warning if ``license_`` is a string that is not a valid expression, none otherwise.
    """
    if canonicalize_license_expression is None or not isinstance(license_, str) or not license_:
        return []
    try:
        canonicalize_license_expression(license_)
    except InvalidLicenseExpression as exc:
        return [
            f"{pyproject_path}: [project].license is not a valid SPDX license expression "
            f"(PEP 639): {exc}"
        ]
    return []
