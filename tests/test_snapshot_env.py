"""Smoke tests for snapshot_env*.sh — save / restore / clean.

Covers the three language variants:
- snapshot_env.sh    (Python)
- snapshot_env_js.sh (JS / TS)
- snapshot_env_go.sh (Go)

Each script must support the same save → mutate → restore round-trip so
Phase 5 rollback works reliably across languages.

TODO task 3.3.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _run(
    bash_bin: str, script_path: Path, project: Path, action: str
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [bash_bin, str(script_path), str(project), action],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _make_python_project(project: Path) -> Path:
    """Minimal Python project with deps files snapshot_env.sh recognizes."""
    (project / "pyproject.toml").write_text('[project]\nname = "x"\n')
    (project / "requirements.txt").write_text("requests==2.31.0\n")
    return project


def _make_js_project(project: Path) -> Path:
    (project / "package.json").write_text('{"name":"x","version":"1.0.0"}')
    (project / "package-lock.json").write_text("{}")
    return project


def _make_go_project(project: Path) -> Path:
    (project / "go.mod").write_text("module example.com/proj\n\ngo 1.21\n")
    (project / "go.sum").write_text("")
    return project


# --------------------------------------------------------------------------- #
# Python — snapshot_env.sh
# --------------------------------------------------------------------------- #


def test_snapshot_env_py_save_creates_snapshot_dir(bash_bin, scripts_dir, tmp_path: Path):
    project = _make_python_project(tmp_path)
    result = _run(bash_bin, scripts_dir / "snapshot_env.sh", project, "save")
    assert result.returncode == 0
    assert (project / ".upgrade_snapshot").is_dir()
    assert (project / ".upgrade_snapshot" / "requirements.txt").is_file()


def test_snapshot_env_py_restore_undoes_mutation(bash_bin, scripts_dir, tmp_path: Path):
    project = _make_python_project(tmp_path)
    original = (project / "requirements.txt").read_text()

    _run(bash_bin, scripts_dir / "snapshot_env.sh", project, "save")
    # Mutate the file
    (project / "requirements.txt").write_text("requests==2.32.0\n")
    # Restore
    result = _run(bash_bin, scripts_dir / "snapshot_env.sh", project, "restore")
    assert result.returncode == 0
    assert (project / "requirements.txt").read_text() == original


# --------------------------------------------------------------------------- #
# JavaScript — snapshot_env_js.sh
#
# Unlike snapshot_env.sh (Python) which writes to ./.upgrade_snapshot under the
# project, the JS and Go variants store snapshots under
# ~/.cache/package-upgrade/<repo-hash>/<timestamp>. Tests therefore validate
# behaviour (save → mutate → restore round-trip) rather than on-disk layout.
# --------------------------------------------------------------------------- #


def test_snapshot_env_js_save_reports_success(bash_bin, scripts_dir, tmp_path: Path):
    project = _make_js_project(tmp_path)
    result = _run(bash_bin, scripts_dir / "snapshot_env_js.sh", project, "save")
    assert result.returncode == 0
    # The script logs to stderr; "saved" appears once the snapshot is committed.
    assert "saved" in result.stderr.lower()


def test_snapshot_env_js_restore_undoes_mutation(bash_bin, scripts_dir, tmp_path: Path):
    project = _make_js_project(tmp_path)
    original = (project / "package.json").read_text()

    _run(bash_bin, scripts_dir / "snapshot_env_js.sh", project, "save")
    (project / "package.json").write_text('{"name":"x","version":"9.9.9"}')
    result = _run(bash_bin, scripts_dir / "snapshot_env_js.sh", project, "restore")
    assert result.returncode == 0
    assert (project / "package.json").read_text() == original


def test_snapshot_env_js_clean_exits_cleanly(bash_bin, scripts_dir, tmp_path: Path):
    project = _make_js_project(tmp_path)
    _run(bash_bin, scripts_dir / "snapshot_env_js.sh", project, "save")
    result = _run(bash_bin, scripts_dir / "snapshot_env_js.sh", project, "clean")
    assert result.returncode == 0


# --------------------------------------------------------------------------- #
# Go — snapshot_env_go.sh
# --------------------------------------------------------------------------- #


def test_snapshot_env_go_save_reports_success(bash_bin, scripts_dir, tmp_path: Path):
    project = _make_go_project(tmp_path)
    result = _run(bash_bin, scripts_dir / "snapshot_env_go.sh", project, "save")
    assert result.returncode == 0
    assert "saved" in result.stderr.lower()


def test_snapshot_env_go_restore_undoes_mutation(bash_bin, scripts_dir, tmp_path: Path):
    project = _make_go_project(tmp_path)
    original = (project / "go.mod").read_text()

    _run(bash_bin, scripts_dir / "snapshot_env_go.sh", project, "save")
    (project / "go.mod").write_text("module example.com/changed\n\ngo 1.22\n")
    result = _run(bash_bin, scripts_dir / "snapshot_env_go.sh", project, "restore")
    assert result.returncode == 0
    assert (project / "go.mod").read_text() == original


# --------------------------------------------------------------------------- #
# Cross-script: usage message when called with bad action
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "script_name",
    ["snapshot_env.sh", "snapshot_env_js.sh", "snapshot_env_go.sh"],
)
def test_usage_message_for_unknown_action(bash_bin, scripts_dir, tmp_path: Path, script_name: str):
    # Build a minimal valid project for each script so the action-dispatch path
    # is reached (otherwise the script may fail earlier on cd / missing files).
    if script_name == "snapshot_env.sh":
        _make_python_project(tmp_path)
    elif script_name == "snapshot_env_js.sh":
        _make_js_project(tmp_path)
    else:
        _make_go_project(tmp_path)

    result = _run(bash_bin, scripts_dir / script_name, tmp_path, "frobnicate")
    assert result.returncode != 0
    assert "Usage" in result.stderr or "usage" in result.stderr.lower()
