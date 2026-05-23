"""Shared pytest fixtures and path setup.

The skill's scripts live under `package-upgrade/scripts/` — the hyphen in the
parent directory prevents normal package imports, so we add the scripts dir
directly to sys.path and import the script files as top-level modules.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "package-upgrade" / "scripts"

# Order matters: scripts dir first so its modules win over any same-named
# stdlib shadows; root second for grant_permissions.py at the repo root.
for p in (SCRIPTS_DIR, ROOT):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)
