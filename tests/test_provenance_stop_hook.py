"""Tests for package-upgrade/scripts/common/provenance_stop_hook.py.

The Stop hook enforces the Phase 3 provenance gate. It is deliberately
conservative — it must only ever block when a *recent* canonical migration
report exists but lacks provenance, and must never hard-fail an unrelated
session. These tests pin that contract.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "package-upgrade" / "scripts" / "common" / "provenance_stop_hook.py"
REPORT_REL = Path(".package-upgrade-cache") / "migration-report.md"

# The hook shells out to verify_provenance.sh, which needs bash.
pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")

_GOOD_REPORT = """\
## References
- Changelog: https://github.com/psf/requests/releases

## Breaking Change 分析來源
### 📚 Changelog 來源
- URL: https://github.com/psf/requests/releases  狀態: ✅
### 🔬 Git Diff 雙軌分析
- Compare URL: https://github.com/psf/requests/compare/v2.28.0...v2.32.0
- old commit abc123def456 / new commit 789012345678
### 🔧 API Surface Diff 來源
- confidence_score: 0.95  狀態: ✅

## Breaking Changes
None — three tracks ran, no API break detected.
"""

_BAD_REPORT = "## Summary\nUpgraded requests. (no provenance recorded)\n"


def _run(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )


def _write_report(cwd: Path, body: str, age_seconds: float = 0) -> Path:
    report = cwd / REPORT_REL
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(body, encoding="utf-8")
    if age_seconds:
        old = time.time() - age_seconds
        os.utime(report, (old, old))
    return report


def test_no_report_is_noop(tmp_path):
    res = _run({"cwd": str(tmp_path)})
    assert res.returncode == 0
    assert res.stdout.strip() == ""


def test_non_json_stdin_is_noop():
    res = subprocess.run(
        [sys.executable, str(HOOK)], input="not json", capture_output=True, text=True, check=False
    )
    assert res.returncode == 0
    assert res.stdout.strip() == ""


def test_stop_hook_active_is_noop(tmp_path):
    _write_report(tmp_path, _BAD_REPORT)
    res = _run({"cwd": str(tmp_path), "stop_hook_active": True})
    assert res.returncode == 0
    assert res.stdout.strip() == ""


def test_stale_report_is_noop(tmp_path):
    _write_report(tmp_path, _BAD_REPORT, age_seconds=31 * 60)
    res = _run({"cwd": str(tmp_path)})
    assert res.returncode == 0
    assert res.stdout.strip() == ""


def test_missing_provenance_blocks(tmp_path):
    _write_report(tmp_path, _BAD_REPORT)
    res = _run({"cwd": str(tmp_path)})
    assert res.returncode == 0  # hook never hard-fails
    decision = json.loads(res.stdout)
    assert decision["decision"] == "block"
    assert "provenance" in decision["reason"].lower()


def test_complete_provenance_does_not_block(tmp_path):
    _write_report(tmp_path, _GOOD_REPORT)
    res = _run({"cwd": str(tmp_path)})
    assert res.returncode == 0
    assert res.stdout.strip() == ""
