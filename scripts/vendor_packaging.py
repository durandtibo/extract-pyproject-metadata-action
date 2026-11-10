"""Vendor a release of ``packaging`` into the package.

Usage: vendor_packaging.py VERSION

Downloads the wheel of ``packaging`` VERSION from PyPI, checks its
SHA-256 digest against the one that PyPI publishes, replaces
``src/extract_pyproject_metadata/_vendor/packaging`` with the
``packaging`` directory of the wheel, copies its licenses, and records the
version and the digest in ``_vendor/README.md``. It only uses the
standard library.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

VENDOR_PATH = Path(__file__).resolve().parents[1] / "src" / "extract_pyproject_metadata" / "_vendor"
PYPI_URL = "https://pypi.org/pypi/packaging/{version}/json"


def find_wheel(version: str) -> tuple[str, str]:
    """Return the URL and the SHA-256 digest of the wheel of a release."""
    with urllib.request.urlopen(PYPI_URL.format(version=version), timeout=30) as response:  # noqa: S310
        files = json.load(response)["urls"]
    wheels = [item for item in files if item["packagetype"] == "bdist_wheel"]
    if len(wheels) != 1:
        msg = f"expected one wheel for packaging {version}, found {len(wheels)}"
        raise SystemExit(msg)
    return wheels[0]["url"], wheels[0]["digests"]["sha256"]


def unpack(wheel: bytes, destination: Path) -> None:
    """Replace ``destination/packaging`` and the licenses with the ones of a wheel."""
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
        for name in archive.namelist():
            parts = Path(name).parts
            if parts[0] == "packaging" and not name.endswith("/"):
                target = destination / name
            elif len(parts) > 2 and parts[0].endswith(".dist-info") and parts[1] == "licenses":
                target = destination / "licenses" / Path(*parts[2:])
            else:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))


def main(argv: list[str]) -> int:
    """Vendor the release named on the command line."""
    if len(argv) != 2:
        print("usage: vendor_packaging.py VERSION", file=sys.stderr)
        return 2
    version = argv[1]
    url, digest = find_wheel(version)
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310
        wheel = response.read()
    if hashlib.sha256(wheel).hexdigest() != digest:
        print("::error::the digest of the wheel is not the one of PyPI", file=sys.stderr)
        return 1
    unpack(wheel, VENDOR_PATH)
    (VENDOR_PATH / "README.md").write_text(
        "# Vendored dependencies\n\n"
        "Do not edit: run `make vendor-packaging VERSION=x.y` "
        "(`scripts/vendor_packaging.py`).\n\n"
        f"- `packaging` {version}, `{url.rsplit('/', 1)[-1]}`, SHA-256 `{digest}`.\n"
        "  Licenses: `licenses/` (Apache-2.0 OR BSD-2-Clause).\n"
        "  Excluded from ruff, pyright, coverage and the spell checker.\n",
        encoding="utf-8",
    )
    (VENDOR_PATH / "__init__.py").write_text(
        '"""Third-party code copied into the package (see ``README.md``)."""\n', encoding="utf-8"
    )
    print(f"vendored packaging {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
