"""Tests of ``extract_pyproject_metadata.pyproject``: reading the
file."""

from __future__ import annotations

from pathlib import Path

import pytest

from extract_pyproject_metadata.errors import MetadataError
from extract_pyproject_metadata.pyproject import load_pyproject
from tests.helpers import write_pyproject


def test_load_pyproject(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')

    assert load_pyproject(str(path)) == {"project": {"name": "coola", "version": "1.2.3"}}


def test_load_pyproject_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_bytes(b'\xef\xbb\xbf[project]\nname = "coola"\nversion = "1.2.3"\n')

    assert load_pyproject(str(path)) == {"project": {"name": "coola", "version": "1.2.3"}}


def test_load_pyproject_bom_only_at_the_start(tmp_path: Path) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_bytes(b'[project]\n\xef\xbb\xbfname = "coola"\n')

    with pytest.raises(MetadataError, match=r"pyproject.toml is not valid TOML"):
        load_pyproject(str(path))


def test_load_pyproject_nested_too_deeply(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, "[project]\nx = " + "[" * 5000 + "]" * 5000 + "\n")

    with pytest.raises(MetadataError, match=r"pyproject.toml is nested too deeply to be parsed"):
        load_pyproject(str(path))


def test_load_pyproject_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.toml"

    with pytest.raises(MetadataError, match=r"pyproject.toml not found at: .*does-not-exist.toml"):
        load_pyproject(str(missing))


def test_load_pyproject_invalid_toml(tmp_path: Path) -> None:
    path = write_pyproject(tmp_path, "this is not [valid toml")

    with pytest.raises(MetadataError, match=r"pyproject.toml is not valid TOML"):
        load_pyproject(str(path))


def test_load_pyproject_invalid_utf8(tmp_path: Path) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_bytes(b'[project]\nname = "caf\xe9"\n')

    with pytest.raises(MetadataError, match=r"pyproject.toml is not valid UTF-8"):
        load_pyproject(str(path))


def test_load_pyproject_unreadable_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write_pyproject(tmp_path, '[project]\nname = "coola"\nversion = "1.2.3"\n')

    def deny(_self: Path, *_args: object, **_kwargs: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "open", deny)

    with pytest.raises(MetadataError, match=r"pyproject.toml cannot be read: .*Permission denied"):
        load_pyproject(str(path))
