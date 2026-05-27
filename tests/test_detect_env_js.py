"""Tests for package-upgrade/scripts/detect_env_js.sh.

The detect_env_* scripts are shell helpers — invoked via subprocess. These
tests build minimal package.json fixtures and assert on the JSON schema the
script emits.  Acts as the schema-alignment regression guard pulled in by
TODO task 3.1.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REQUIRED_TOP_LEVEL_KEYS = {
    "language",
    "pkg_manager",
    "pkg_manager_bin",
    "pkg_manager_version",
    "uses_corepack",
    "lockfile_path",
    "manifest_files",
    "is_workspace",
    "workspace_globs",
    "has_typescript",
    "test_framework_hint",
    "env_var_placeholders",
    "custom_registries",
    "git_remote_host",
    "git_remote_url",
    "has_node_modules",
    "memory_hints",
}


def _run(bash_bin: str, scripts_dir: Path, project: Path) -> dict:
    script = scripts_dir / "javascript" / "detect_env.sh"
    result = subprocess.run(
        [bash_bin, str(script), str(project)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"detect_env_js failed: {result.stderr}"
    return json.loads(result.stdout)


def test_npm_project_detected(bash_bin, scripts_dir, tmp_path: Path):
    (tmp_path / "package.json").write_text(
        '{"name":"x","version":"1.0.0","scripts":{"test":"jest"}}'
    )
    (tmp_path / "package-lock.json").write_text("{}")
    out = _run(bash_bin, scripts_dir, tmp_path)

    assert REQUIRED_TOP_LEVEL_KEYS.issubset(out.keys())
    assert out["language"] == "javascript"
    assert out["pkg_manager"] == "npm"
    assert out["lockfile_path"] == "package-lock.json"
    assert out["test_framework_hint"] == "jest"


def test_yarn_project_detected(bash_bin, scripts_dir, tmp_path: Path):
    (tmp_path / "package.json").write_text('{"name":"x","version":"1.0.0"}')
    (tmp_path / "yarn.lock").write_text("# yarn lockfile\n")
    out = _run(bash_bin, scripts_dir, tmp_path)

    assert out["pkg_manager"] == "yarn"
    assert out["lockfile_path"] == "yarn.lock"


def test_workspace_detection(bash_bin, scripts_dir, tmp_path: Path):
    (tmp_path / "package.json").write_text('{"name":"root","workspaces":["packages/*"]}')
    out = _run(bash_bin, scripts_dir, tmp_path)

    assert out["is_workspace"] is True
    assert out["workspace_globs"] == ["packages/*"]
    assert "workspace" in out["memory_hints"]


def test_typescript_detection_via_tsconfig(bash_bin, scripts_dir, tmp_path: Path):
    (tmp_path / "package.json").write_text('{"name":"x"}')
    (tmp_path / "tsconfig.json").write_text('{"compilerOptions":{}}')
    out = _run(bash_bin, scripts_dir, tmp_path)

    assert out["has_typescript"] is True
    assert out["tsconfig_path"] == "tsconfig.json"


def test_custom_registry_with_env_var_in_yarnrc(bash_bin, scripts_dir, tmp_path: Path):
    (tmp_path / "package.json").write_text('{"name":"x"}')
    (tmp_path / ".yarnrc.yml").write_text(
        "npmScopes:\n"
        "  myorg:\n"
        '    npmRegistryServer: "https://artifactory.example.com/"\n'
        '    npmAuthToken: "${JFROG_TOKEN}"\n'
    )
    out = _run(bash_bin, scripts_dir, tmp_path)

    assert "JFROG_TOKEN" in out["env_var_placeholders"]
    regs = out["custom_registries"]
    assert any(r["auth_env_var"] == "JFROG_TOKEN" for r in regs)
    assert "custom_registry" in out["memory_hints"]


@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "detect_env_js.sh inlines $PROJECT_PATH into the error JSON without "
        "escaping; Windows backslash paths produce invalid JSON escapes. "
        "Tracked in TODO.md known-issues until the script switches to "
        "jq-encoded path emission."
    ),
)
def test_missing_package_json_errors(bash_bin, scripts_dir, tmp_path: Path):
    """No package.json — script should exit non-zero with a clear JSON error."""
    script = scripts_dir / "javascript" / "detect_env.sh"
    result = subprocess.run(
        [bash_bin, str(script), str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    data = json.loads(result.stdout)
    assert "error" in data
    assert data["pkg_manager"] == "unknown"
