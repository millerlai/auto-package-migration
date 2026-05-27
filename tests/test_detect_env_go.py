"""Tests for package-upgrade/scripts/detect_env_go.sh.

Skipped automatically when go is missing (the script shells out to
`go env`, so happy-path coverage requires a working toolchain).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REQUIRED_TOP_LEVEL_KEYS = {
    "language",
    "pkg_manager",
    "go_version",
    "module_path",
    "lockfile_path",
    "manifest_files",
    "has_workspace",
    "workspace_modules",
    "is_vendored",
    "has_replace_directives",
    "replace_directives",
    "has_exclude_directives",
    "go_env",
    "govulncheck_available",
    "apidiff_available",
    "netrc_present",
    "git_remote_host",
    "git_remote_url",
    "memory_hints",
}


def _run(bash_bin: str, scripts_dir: Path, project: Path) -> dict:
    script = scripts_dir / "detect_env_go.sh"
    result = subprocess.run(
        [bash_bin, str(script), str(project)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"detect_env_go failed: {result.stderr}"
    return json.loads(result.stdout)


def test_minimal_module_detected(go_bin, bash_bin, scripts_dir, tmp_path: Path):
    (tmp_path / "go.mod").write_text("module example.com/proj\n\ngo 1.21\n")
    out = _run(bash_bin, scripts_dir, tmp_path)

    assert REQUIRED_TOP_LEVEL_KEYS.issubset(out.keys())
    assert out["language"] == "go"
    assert out["pkg_manager"] == "gomod"
    assert out["module_path"] == "example.com/proj"
    assert out["go_directive"] == "1.21"


def test_vendored_project(go_bin, bash_bin, scripts_dir, tmp_path: Path):
    (tmp_path / "go.mod").write_text("module example.com/proj\n\ngo 1.21\n")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "modules.txt").write_text("# explicit\n")
    out = _run(bash_bin, scripts_dir, tmp_path)

    assert out["is_vendored"] is True
    assert "vendored" in out["memory_hints"]


def test_replace_directive_parsed(go_bin, bash_bin, scripts_dir, tmp_path: Path):
    (tmp_path / "go.mod").write_text(
        "module example.com/proj\n\n"
        "go 1.21\n\n"
        "require github.com/foo/bar v1.0.0\n\n"
        "replace github.com/foo/bar => github.com/forked/bar v1.0.1\n"
    )
    out = _run(bash_bin, scripts_dir, tmp_path)

    assert out["has_replace_directives"] is True
    assert "replace_directives" in out["memory_hints"]
    assert len(out["replace_directives"]) >= 1


def test_go_workspace_detected(go_bin, bash_bin, scripts_dir, tmp_path: Path):
    (tmp_path / "go.work").write_text("go 1.21\n\nuse (\n    ./a\n    ./b\n)\n")
    (tmp_path / "go.mod").write_text("module example.com/proj\n\ngo 1.21\n")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "go.mod").write_text("module example.com/proj/a\n\ngo 1.21\n")
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "go.mod").write_text("module example.com/proj/b\n\ngo 1.21\n")
    out = _run(bash_bin, scripts_dir, tmp_path)

    assert out["has_workspace"] is True
    assert "workspace" in out["memory_hints"]


def test_non_go_directory_is_unknown(go_bin, bash_bin, scripts_dir, tmp_path: Path):
    """No go.mod / Gopkg.toml / etc — pkg_manager stays `unknown`."""
    (tmp_path / "README.md").write_text("# not a Go project\n")
    out = _run(bash_bin, scripts_dir, tmp_path)

    assert out["pkg_manager"] == "unknown"
