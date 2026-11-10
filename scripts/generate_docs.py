"""Generate the tables of ``README.md`` from ``action.yaml`` and the code.

Usage: generate_docs.py [--check]

Rewrites the blocks between ``<!-- NAME:start -->`` and ``<!-- NAME:end -->``
of the README: ``inputs`` and ``outputs`` (the tables of ``action.yaml``) and
``warnings`` (the codes of ``warning_codes.py``) and ``candidates`` (the default of
``python-candidates``, defined in the code).
With ``--check``, writes nothing and exits with 1 when the README is not up
to date. It is a development tool: it needs PyYAML, the action does not.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT_PATH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_PATH / "src"))

from extract_pyproject_metadata.inputs import DEFAULT_PYTHON_CANDIDATES  # noqa: E402
from extract_pyproject_metadata.warning_codes import WARNING_CODES  # noqa: E402

ACTION_PATH = ROOT_PATH / "action.yaml"
README_PATH = ROOT_PATH / "README.md"


def format_table(header: list[str], rows: list[list[str]]) -> str:
    """Format a Markdown table with padded columns, like Prettier does."""
    widths = [max(len(row[i]) for row in [header, *rows]) for i in range(len(header))]

    def line(cells: list[str]) -> str:
        return (
            "| "
            + " | ".join(cell.ljust(width) for cell, width in zip(cells, widths, strict=True))
            + " |"
        )

    separator = "| " + " | ".join("-" * width for width in widths) + " |"
    return "\n".join([line(header), separator, *(line(row) for row in rows)])


def _cell(text: str) -> str:
    """Return a description on one line, safe in a table cell."""
    return " ".join(str(text).split()).replace("|", "\\|")


def render_inputs(action: dict[str, Any]) -> str:
    """Return the table of the inputs of the action."""
    rows = []
    for name, spec in action["inputs"].items():
        default = spec.get("default", "")
        shown = f"`{default}`" if default != "" else "(see the description)"
        rows.append([f"`{name}`", _cell(spec["description"]), shown])
    return format_table(["Name", "Description", "Default"], rows)


def render_outputs(action: dict[str, Any]) -> str:
    """Return the table of the outputs of the action."""
    rows = [[f"`{name}`", _cell(spec["description"])] for name, spec in action["outputs"].items()]
    return format_table(["Name", "Description"], rows)


def render_warnings() -> str:
    """Return the table of the warning codes."""
    rows = [[f"`{code}`", when, effect] for code, (when, effect) in WARNING_CODES.items()]
    return format_table(["Code", "When", "Effect"], rows)


def render_candidates() -> str:
    """Return the default ``python-candidates``, as code."""
    return f"`{DEFAULT_PYTHON_CANDIDATES}`"


def replace_block(text: str, name: str, content: str, *, table: bool = True) -> str:
    """Replace what is between the ``name`` markers of ``text``.

    Prettier puts a blank line after an HTML comment and before a table that follows it, so the
    block is written that way (a table also gets a blank line before the end marker), and
    formatting the README does not change it.
    """
    pattern = re.compile(rf"(<!-- {name}:start -->).*?(<!-- {name}:end -->)", re.DOTALL)
    if not pattern.search(text):
        msg = f"README.md has no <!-- {name}:start --> ... <!-- {name}:end --> block"
        raise SystemExit(msg)
    end = "\n\n" if table else "\n"
    return pattern.sub(lambda match: f"{match.group(1)}\n\n{content}{end}{match.group(2)}", text)


def generate(readme: str, action: dict[str, Any]) -> str:
    """Return the README with its generated blocks up to date."""
    readme = replace_block(readme, "inputs", render_inputs(action))
    readme = replace_block(readme, "outputs", render_outputs(action))
    readme = replace_block(readme, "warnings", render_warnings())
    return replace_block(readme, "candidates", render_candidates(), table=False)


def main(argv: list[str]) -> int:
    """Write the generated blocks, or check them with ``--check``."""
    action = yaml.safe_load(ACTION_PATH.read_text(encoding="utf-8"))
    current = README_PATH.read_text(encoding="utf-8")
    updated = generate(current, action)
    if "--check" in argv:
        if updated != current:
            print("::error::README.md is out of date: run `make docs`")
            return 1
        return 0
    README_PATH.write_text(updated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
