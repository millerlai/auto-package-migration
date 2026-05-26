"""Shared pytest fixtures and path setup.

The skill's scripts live under `package-upgrade/scripts/` — the hyphen in the
parent directory prevents normal package imports, so we add the scripts dir
directly to sys.path and import the script files as top-level modules.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "package-upgrade" / "scripts"

# Order matters: scripts dir first so its modules win over any same-named
# stdlib shadows; root second for grant_permissions.py at the repo root.
# Insert in reverse because each path is prepended at index 0.
for p in (ROOT, SCRIPTS_DIR):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)


# --------------------------------------------------------------------------- #
# Fixtures shared by the JS / Go helper tests (task 3.1 + 3.2).
# Each one skips the entire test module when the required toolchain isn't
# available, so the suite stays green on machines (or CI jobs) that only
# have Python.
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def scripts_dir() -> Path:
    """Absolute path to the helper scripts directory."""
    return SCRIPTS_DIR


@pytest.fixture(scope="session")
def node_bin() -> str:
    bin_ = shutil.which("node")
    if bin_ is None:
        pytest.skip("node not installed", allow_module_level=False)
    return bin_


@pytest.fixture(scope="session")
def go_bin() -> str:
    bin_ = shutil.which("go")
    if bin_ is None:
        pytest.skip("go not installed", allow_module_level=False)
    return bin_


@pytest.fixture(scope="session")
def bash_bin() -> str:
    bin_ = shutil.which("bash")
    if bin_ is None:
        pytest.skip("bash not installed", allow_module_level=False)
    return bin_


@pytest.fixture(scope="session")
def js_deps_installed(scripts_dir: Path, node_bin: str) -> bool:
    """Skip the test if @babel/parser is missing from scripts/node_modules.

    The JS helpers ship with their own package.json; install.sh runs
    `npm install` there. Tests should not silently fail when that step
    was skipped.
    """
    if not (scripts_dir / "node_modules" / "@babel" / "parser").exists():
        pytest.skip("JS helper deps not installed (run `npm install` in scripts/)")
    return True
