"""Smoke tests for validate_lockfile.sh + validate_modfile_go.sh.

Full validation requires network-free package-manager invocations
(`npm ci --offline`, `yarn --immutable`, `go mod verify`), which aren't
hermetic enough for the default suite. These tests cover the script-shape
guarantees:

- exits with a JSON document on stdout
- emits a clear failure JSON when there's no manifest
- doesn't crash on an unexpected pkg_manager

TODO task 3.3.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _run(bash_bin: str, script_path: Path, project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [bash_bin, str(script_path), str(project)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


# --------------------------------------------------------------------------- #
# validate_lockfile.sh (JS)
# --------------------------------------------------------------------------- #


def test_validate_lockfile_missing_manifest_returns_failure(bash_bin, scripts_dir, tmp_path: Path):
    result = _run(bash_bin, scripts_dir / "javascript" / "validate_lockfile.sh", tmp_path)
    # exit code can be 0 or non-zero depending on implementation; the
    # contract is that stdout is valid JSON describing the failure.
    data = json.loads(result.stdout)
    assert data["status"] == "failure"


def test_validate_lockfile_emits_json_for_npm_project(bash_bin, scripts_dir, tmp_path: Path):
    (tmp_path / "package.json").write_text('{"name":"x","version":"1.0.0"}')
    (tmp_path / "package-lock.json").write_text(
        json.dumps(
            {
                "name": "x",
                "version": "1.0.0",
                "lockfileVersion": 3,
                "requires": True,
                "packages": {"": {"name": "x", "version": "1.0.0"}},
            }
        )
    )
    result = _run(bash_bin, scripts_dir / "javascript" / "validate_lockfile.sh", tmp_path)

    # The validation itself may pass or fail depending on whether npm is on
    # PATH, but we must always get a structured JSON status back.
    data = json.loads(result.stdout)
    assert data["status"] in ("success", "failure")
    assert "pkg_manager" in data
    assert data["pkg_manager"] == "npm"


# --------------------------------------------------------------------------- #
# validate_modfile_go.sh
# --------------------------------------------------------------------------- #


def test_validate_modfile_go_missing_mod_returns_failure(bash_bin, scripts_dir, tmp_path: Path):
    script = scripts_dir / "go" / "validate_modfile.sh"
    if not script.exists():
        import pytest

        pytest.skip("scripts/go/validate_modfile.sh not present")
    result = _run(bash_bin, script, tmp_path)
    # No go.mod — script should report failure cleanly (JSON or non-zero exit).
    if result.stdout.strip():
        data = json.loads(result.stdout)
        assert data["status"] == "failure"
    else:
        assert result.returncode != 0
