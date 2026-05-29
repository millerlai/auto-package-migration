#!/usr/bin/env python3
"""Claude Code Stop hook — enforces the Phase 3 provenance gate.

Wired into settings.json by grant_permissions.py. When Claude finishes a turn,
this runs verify_provenance.sh against the canonical migration report
(`<cwd>/.package-upgrade-cache/migration-report.md`, written in Phase 7.1). If
the report exists but lacks Phase 3 provenance, the hook blocks the stop and
feeds the missing markers back so Claude actually runs the skipped tracks.

Deliberately conservative — it only ever acts when a *recent* canonical report
exists, so it never interferes with unrelated sessions:
  - no report file            -> exit 0 (not a package-upgrade run)
  - report older than 30 min  -> exit 0 (stale, likely a previous run)
  - stop_hook_active == true   -> exit 0 (avoid re-block loops)
  - verify script errors       -> exit 0 (never hard-fail the user's session)

Language-agnostic: it shells out to verify_provenance.sh, which checks the
standardized provenance markers shared by every language path.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

RECENCY_SECONDS = 30 * 60
REPORT_REL = Path(".package-upgrade-cache") / "migration-report.md"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # not invoked as a hook / no input — do nothing

    if payload.get("stop_hook_active"):
        return 0

    cwd = Path(payload.get("cwd") or ".").expanduser()
    report = cwd / REPORT_REL
    if not report.is_file():
        return 0

    try:
        if (time.time() - report.stat().st_mtime) > RECENCY_SECONDS:
            return 0
    except OSError:
        return 0

    verify = Path(__file__).with_name("verify_provenance.sh")
    # Resolve bash to an absolute path: a bare "bash" can hit the WindowsApps
    # WSL stub before a real (Git/MSYS) bash on Windows.
    bash = shutil.which("bash")
    if not bash or not verify.is_file():
        return 0  # verifier unavailable — don't block the user
    try:
        proc = subprocess.run(
            [bash, str(verify), str(report)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return 0  # verifier unavailable — don't block the user

    if proc.returncode == 0:
        return 0  # provenance present (or legitimate zero_impact skip)
    if proc.returncode != 1:
        return 0  # usage/file error from verifier — don't block

    missing = []
    try:
        missing = json.loads(proc.stdout).get("missing", [])
    except (json.JSONDecodeError, ValueError):
        pass

    bullet = "\n".join(f"  - {m}" for m in missing) or "  - (see verify_provenance.sh output)"
    reason = (
        "Phase 3 provenance gate FAILED for "
        f"{report}.\n"
        "The migration report is missing evidence that the Phase 3 tracks were "
        "actually run:\n"
        f"{bullet}\n"
        "Do NOT finish from memory. Run the missing tracks — Step 3.1 "
        "fetch_changelog.py, Step 3.2 git_diff.sh, Step 3.0 api_surface_diff — "
        "then add their provenance (changelog URL, compare URL + SHAs, "
        "API-surface confidence_score) to the report. If the upgrade is a pure "
        "transitive zero_impact case, record a '## Skipped Phases' section "
        "instead. Re-run verify_provenance.sh until it passes."
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
