"""Tests of ``extract_pyproject_metadata.dynamic_version``: the version
that a build backend reads from a file."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from extract_pyproject_metadata.dynamic_version import (
    HATCH_DEFAULT_PATTERN,
    MAX_VERSION_FILE_BYTES,
    _literal_attribute,
    _module_candidates,
    read_dynamic_version,
)

if TYPE_CHECKING:
    from pathlib import Path


def setuptools(**version: Any) -> dict[str, Any]:
    """Build the data with ``[tool.setuptools.dynamic].version``."""
    return {"tool": {"setuptools": {"dynamic": {"version": version}}}}


def read(tmp_path: Path, data: dict[str, Any]) -> tuple[str, str]:
    return read_dynamic_version(data, str(tmp_path / "pyproject.toml"))


# ----- setuptools: file -----


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("1.2.3", "1.2.3"),
        ("1.2.3\n", "1.2.3"),
        ("\n  1.0rc1  \n\n", "1.0rc1"),
        ("1.0-RC1", "1.0-RC1"),
    ],
)
def test_setuptools_file(tmp_path: Path, content: str, expected: str) -> None:
    (tmp_path / "VERSION").write_text(content)

    assert read(tmp_path, setuptools(file="VERSION")) == (expected, "")


def test_setuptools_file_in_a_subdirectory(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "VERSION.txt").write_text("2.0\n")

    assert read(tmp_path, setuptools(file="src/VERSION.txt")) == ("2.0", "")


def test_setuptools_file_list_is_joined(tmp_path: Path) -> None:
    (tmp_path / "a").write_text("1.")
    (tmp_path / "b").write_text("0")

    assert read(tmp_path, setuptools(file=["a", "b"])) == (
        "",
        "'1.\\n0' is not a valid PEP 440 version",  # the files are joined with a line break
    )


def test_setuptools_file_list_with_one_file(tmp_path: Path) -> None:
    (tmp_path / "a").write_text("3.1\n")

    assert read(tmp_path, setuptools(file=["a"])) == ("3.1", "")


def test_setuptools_file_missing(tmp_path: Path) -> None:
    assert read(tmp_path, setuptools(file="VERSION")) == ("", "'VERSION' is not a file")


@pytest.mark.parametrize("files", [1, [], [1], ["a", 2], {"a": "b"}])
def test_setuptools_file_of_the_wrong_type(tmp_path: Path, files: object) -> None:
    version, reason = read(tmp_path, setuptools(file=files))

    assert version == ""
    assert reason.startswith("[tool.setuptools.dynamic].version file must be a string or")


def test_setuptools_file_with_an_invalid_version(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text("latest\n")

    assert read(tmp_path, setuptools(file="VERSION")) == (
        "",
        "'latest' is not a valid PEP 440 version",
    )


def test_setuptools_file_empty(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text("\n")

    assert read(tmp_path, setuptools(file="VERSION")) == ("", "'' is not a valid PEP 440 version")


def test_file_outside_the_project_is_not_read(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "VERSION").write_text("1.0\n")

    assert read(project, setuptools(file="../VERSION")) == (
        "",
        "'../VERSION' is outside the directory of the pyproject.toml",
    )


def test_symlink_to_a_file_outside_the_project_is_not_read(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "VERSION").write_text("1.0\n")
    (project / "VERSION").symlink_to(tmp_path / "VERSION")

    assert read(project, setuptools(file="VERSION"))[0] == ""


def test_absolute_path_outside_the_project_is_not_read(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "VERSION").write_text("1.0\n")

    version, reason = read(project, setuptools(file=str(tmp_path / "VERSION")))

    assert version == ""
    assert "is outside the directory of the pyproject.toml" in reason


def test_a_big_file_is_not_read(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text("1" * (MAX_VERSION_FILE_BYTES + 1))

    assert read(tmp_path, setuptools(file="VERSION")) == (
        "",
        f"'VERSION' is bigger than {MAX_VERSION_FILE_BYTES} bytes",
    )


def test_a_file_that_is_not_utf8_is_not_read(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_bytes(b"\xff\xfe1.0")

    version, reason = read(tmp_path, setuptools(file="VERSION"))

    assert version == ""
    assert reason.startswith("'VERSION' cannot be read: ")


def test_a_directory_is_not_read(tmp_path: Path) -> None:
    (tmp_path / "VERSION").mkdir()

    assert read(tmp_path, setuptools(file="VERSION")) == ("", "'VERSION' is not a file")


def test_an_unreadable_file_is_not_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "VERSION").write_text("1.0\n")
    original = type(tmp_path).open

    def fail(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.name == "VERSION":
            msg = "denied"
            raise PermissionError(msg)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(type(tmp_path), "open", fail)

    assert read(tmp_path, setuptools(file="VERSION")) == (
        "",
        "'VERSION' cannot be read: denied",
    )


# ----- setuptools: attr -----


def test_setuptools_attr_in_a_module_of_the_directory(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text('"""Doc."""\n__version__ = "1.2.3"\n')

    assert read(tmp_path, setuptools(attr="pkg.__version__")) == ("1.2.3", "")


def test_setuptools_attr_in_a_module_file(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("VERSION: str = '4.5'\n")

    assert read(tmp_path, setuptools(attr="mod.VERSION")) == ("4.5", "")


def test_setuptools_attr_in_the_src_directory(tmp_path: Path) -> None:
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "_version.py").write_text('__version__ = "0.9"\n')

    assert read(tmp_path, setuptools(attr="pkg._version.__version__")) == ("0.9", "")


def test_setuptools_attr_with_the_package_dir_of_all_the_packages(tmp_path: Path) -> None:
    (tmp_path / "lib" / "pkg").mkdir(parents=True)
    (tmp_path / "lib" / "pkg" / "__init__.py").write_text('__version__ = "7.0"\n')
    data = setuptools(attr="pkg.__version__")
    data["tool"]["setuptools"]["package-dir"] = {"": "lib"}

    assert read(tmp_path, data) == ("7.0", "")


def test_setuptools_attr_with_the_package_dir_of_the_package(tmp_path: Path) -> None:
    (tmp_path / "python" / "sub").mkdir(parents=True)
    (tmp_path / "python" / "sub" / "v.py").write_text('__version__ = "8.0"\n')
    data = setuptools(attr="pkg.sub.v.__version__")
    data["tool"]["setuptools"]["package-dir"] = {"pkg": "python"}

    assert read(tmp_path, data) == ("8.0", "")


def test_setuptools_attr_uses_the_last_assignment(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text('__version__ = "1.0"\n__version__ = "2.0"\n')

    assert read(tmp_path, setuptools(attr="mod.__version__")) == ("2.0", "")


def test_setuptools_attr_does_not_run_the_module(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    (tmp_path / "mod.py").write_text(f'open({str(marker)!r}, "w").close()\n__version__ = "1.0"\n')

    assert read(tmp_path, setuptools(attr="mod.__version__")) == ("1.0", "")
    assert not marker.exists()


@pytest.mark.parametrize(
    "source",
    ["__version__ = (1, 0)\n", "__version__ = get()\n", "__version__ = f'{x}'\n", "other = '1'\n"],
)
def test_setuptools_attr_that_is_not_a_string_literal(tmp_path: Path, source: str) -> None:
    (tmp_path / "mod.py").write_text(source)

    assert read(tmp_path, setuptools(attr="mod.__version__")) == (
        "",
        "__version__ is not a string literal in 'mod.py'",
    )


def test_setuptools_attr_in_a_module_with_a_syntax_error(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("def (:\n")

    version, reason = read(tmp_path, setuptools(attr="mod.__version__"))

    assert version == ""
    assert reason.startswith("'mod.py' is not valid Python: ")


def test_setuptools_attr_without_a_module_file(tmp_path: Path) -> None:
    version, reason = read(tmp_path, setuptools(attr="pkg.__version__"))

    assert version == ""
    assert reason.startswith("no file for the module 'pkg' (")
    assert "'src/pkg.py' is not a file" in reason


@pytest.mark.parametrize("attr", ["version", 1, "", None])
def test_setuptools_attr_of_the_wrong_form(tmp_path: Path, attr: object) -> None:
    assert read(tmp_path, setuptools(attr=attr)) == (
        "",
        f"[tool.setuptools.dynamic].version attr must be 'module.name', got: {attr!r}",
    )


def test_setuptools_attr_with_an_invalid_version(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text('__version__ = "dev"\n')

    assert read(tmp_path, setuptools(attr="mod.__version__")) == (
        "",
        "'dev' is not a valid PEP 440 version",
    )


def test_module_candidates() -> None:
    assert _module_candidates("pkg.sub", {}) == [
        "src/pkg/sub.py",
        "src/pkg/sub/__init__.py",
        "pkg/sub.py",
        "pkg/sub/__init__.py",
    ]


def test_literal_attribute_annotated_assignment_without_value() -> None:
    assert _literal_attribute("__version__: str\n", "__version__") is None


# ----- hatch -----


def hatch(**version: Any) -> dict[str, Any]:
    """Build the data with ``[tool.hatch.version]``."""
    return {"tool": {"hatch": {"version": version}}}


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ('__version__ = "1.2.3"', "1.2.3"),
        ("__version__ = '1.2.3'", "1.2.3"),
        ('VERSION = "2.0"', "2.0"),
        ('version = "2.0"', "2.0"),
        ('__version__: str = "3.0"', "3.0"),
        ('__version__="4.0"', "4.0"),
        ('__version__ = "v5.0"', "5.0"),
    ],
)
def test_hatch_default_pattern(tmp_path: Path, line: str, expected: str) -> None:
    (tmp_path / "about.py").write_text(f"# comment\n{line}\n")

    assert read(tmp_path, hatch(path="about.py")) == (expected, "")


def test_hatch_default_pattern_is_the_one_of_hatch() -> None:
    assert "(?P<version>" in HATCH_DEFAULT_PATTERN


def test_hatch_custom_pattern(tmp_path: Path) -> None:
    (tmp_path / "setup.cfg").write_text("[metadata]\nrelease = 6.1.0\n")

    assert read(tmp_path, hatch(path="setup.cfg", pattern=r"release = (?P<version>\S+)")) == (
        "6.1.0",
        "",
    )


def test_hatch_explicit_regex_source(tmp_path: Path) -> None:
    (tmp_path / "about.py").write_text('__version__ = "1.0"\n')

    assert read(tmp_path, hatch(source="regex", path="about.py")) == ("1.0", "")


def test_hatch_other_source(tmp_path: Path) -> None:
    assert read(tmp_path, hatch(source="vcs")) == (
        "",
        "[tool.hatch.version].source 'vcs' is not supported (only 'regex')",
    )


@pytest.mark.parametrize("path", [None, "", 1])
def test_hatch_without_a_path(tmp_path: Path, path: object) -> None:
    data = hatch() if path is None else hatch(path=path)

    assert read(tmp_path, data) == ("", "[tool.hatch.version] has no path")


def test_hatch_pattern_that_is_not_a_string(tmp_path: Path) -> None:
    assert read(tmp_path, hatch(path="a.py", pattern=1)) == (
        "",
        "[tool.hatch.version].pattern must be a string, got: 1",
    )


def test_hatch_pattern_that_is_not_a_regular_expression(tmp_path: Path) -> None:
    version, reason = read(tmp_path, hatch(path="a.py", pattern="("))

    assert version == ""
    assert reason.startswith("[tool.hatch.version].pattern is not a valid regular expression: ")


def test_hatch_pattern_without_a_version_group(tmp_path: Path) -> None:
    assert read(tmp_path, hatch(path="a.py", pattern=r"\d+")) == (
        "",
        "[tool.hatch.version].pattern has no group named 'version'",
    )


def test_hatch_pattern_that_does_not_match(tmp_path: Path) -> None:
    (tmp_path / "about.py").write_text("nothing\n")

    assert read(tmp_path, hatch(path="about.py")) == (
        "",
        "the pattern of [tool.hatch.version] does not match in 'about.py'",
    )


def test_hatch_file_missing(tmp_path: Path) -> None:
    assert read(tmp_path, hatch(path="about.py")) == ("", "'about.py' is not a file")


def test_hatch_with_an_invalid_version(tmp_path: Path) -> None:
    (tmp_path / "about.py").write_text('__version__ = "main"\n')

    assert read(tmp_path, hatch(path="about.py")) == (
        "",
        "'main' is not a valid PEP 440 version",
    )


# ----- which source is used -----


def test_setuptools_wins_over_hatch(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text("1.0\n")
    (tmp_path / "about.py").write_text('__version__ = "2.0"\n')
    data = {
        **setuptools(file="VERSION"),
        "tool": {**setuptools(file="VERSION")["tool"], **hatch(path="about.py")["tool"]},
    }

    assert read(tmp_path, data) == ("1.0", "")


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"tool": 1},
        {"tool": {}},
        {"tool": {"setuptools": {"dynamic": {"version": "x"}}}},
        {"tool": {"setuptools": {"dynamic": {"version": {"other": "x"}}}}},
        {"tool": {"setuptools": 1}},
        {"tool": {"hatch": {"version": "x"}}},
        {"tool": {"hatch": 1}},
        {"tool": {"setuptools_scm": {}}},
    ],
)
def test_no_static_source(tmp_path: Path, data: dict[str, Any]) -> None:
    assert read(tmp_path, data) == (
        "",
        (
            "no static source: only [tool.setuptools.dynamic].version (file or attr) and "
            "[tool.hatch.version] (path) are read"
        ),
    )


def test_a_relative_pyproject_path_is_relative_to_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "VERSION").write_text("1.0\n")
    monkeypatch.chdir(tmp_path)

    assert read_dynamic_version(setuptools(file="VERSION"), "pyproject.toml") == ("1.0", "")
