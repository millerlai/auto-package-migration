"""Tests for package-upgrade/scripts/dep_tree_js.js.

Drives the lockfile-first dep_tree analyzer via subprocess against minimal
package.json + lockfile fixtures in tmp_path. Asserts on the schema and
classification logic that Phase 2 strategy selection depends on.

TODO task 3.1 — second batch (test_ast_scanner_js + test_detect_env_js
already landed on test/js-go-helper-pytest).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REQUIRED_TOP_LEVEL_KEYS = {
    "package_name",
    "language",
    "pkg_manager",
    "current_version",
    "dependency_type",
    "is_direct",
    "is_transitive",
    "is_peer",
    "parent_packages",
    "version_constraints",
    "declared_in",
    "source",
    "errors",
}


def _run(node_bin: str, scripts_dir: Path, project: Path, package: str) -> dict:
    script = scripts_dir / "dep_tree_js.js"
    result = subprocess.run(
        [node_bin, str(script), str(project), package],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, f"dep_tree_js failed: {result.stderr}"
    return json.loads(result.stdout)


def _write_minimal_npm_lock(project: Path, pkg_versions: dict) -> None:
    """Write a v3-format package-lock.json with the given top-level packages."""
    packages = {"": {"name": project.name, "version": "1.0.0"}}
    for name, version in pkg_versions.items():
        packages[f"node_modules/{name}"] = {"version": version}
    lock = {
        "name": project.name,
        "version": "1.0.0",
        "lockfileVersion": 3,
        "requires": True,
        "packages": packages,
    }
    (project / "package-lock.json").write_text(json.dumps(lock))


def test_direct_dep_classified_as_direct(node_bin, scripts_dir, js_deps_installed, tmp_path: Path):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "x",
                "version": "1.0.0",
                "dependencies": {"lodash": "^4.17.20"},
            }
        )
    )
    _write_minimal_npm_lock(tmp_path, {"lodash": "4.17.20"})

    out = _run(node_bin, scripts_dir, tmp_path, "lodash")

    assert REQUIRED_TOP_LEVEL_KEYS.issubset(out.keys())
    assert out["language"] == "javascript"
    assert out["package_name"] == "lodash"
    assert out["pkg_manager"] == "npm"
    assert out["current_version"] == "4.17.20"
    assert out["is_direct"] is True
    assert out["is_transitive"] is False
    assert out["dependency_type"] in ("direct", "both")
    assert "dependencies" in out["declared_in"]


def test_dev_dependency_marked_declared_in_dev(
    node_bin, scripts_dir, js_deps_installed, tmp_path: Path
):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "x",
                "version": "1.0.0",
                "devDependencies": {"jest": "^29.0.0"},
            }
        )
    )
    _write_minimal_npm_lock(tmp_path, {"jest": "29.7.0"})

    out = _run(node_bin, scripts_dir, tmp_path, "jest")

    assert out["is_direct"] is True
    assert "devDependencies" in out["declared_in"]


def test_peer_dependency_flag(node_bin, scripts_dir, js_deps_installed, tmp_path: Path):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "x",
                "version": "1.0.0",
                "peerDependencies": {"react": ">=18"},
            }
        )
    )
    _write_minimal_npm_lock(tmp_path, {"react": "18.2.0"})

    out = _run(node_bin, scripts_dir, tmp_path, "react")

    assert out["is_peer"] is True
    assert "peerDependencies" in out["declared_in"]


def test_unknown_package_returns_unknown_type(
    node_bin, scripts_dir, js_deps_installed, tmp_path: Path
):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "x",
                "version": "1.0.0",
                "dependencies": {"lodash": "^4.17.20"},
            }
        )
    )
    _write_minimal_npm_lock(tmp_path, {"lodash": "4.17.20"})

    out = _run(node_bin, scripts_dir, tmp_path, "not-installed-pkg")

    # Schema still valid even when the package isn't found
    assert REQUIRED_TOP_LEVEL_KEYS.issubset(out.keys())
    assert out["package_name"] == "not-installed-pkg"
    # Should not classify as direct/transitive when absent
    assert out["dependency_type"] in ("unknown", "transitive")
    assert out["is_direct"] is False


def test_source_field_identifies_lockfile_format(
    node_bin, scripts_dir, js_deps_installed, tmp_path: Path
):
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "x", "dependencies": {"lodash": "^4.17.20"}})
    )
    _write_minimal_npm_lock(tmp_path, {"lodash": "4.17.20"})

    out = _run(node_bin, scripts_dir, tmp_path, "lodash")

    # source must indicate which parser was used; for npm-lock that's "npm-lock"
    assert out["source"] in ("npm-lock", "npm-ls")
