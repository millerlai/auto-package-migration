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


# --------------------------------------------------------------------------- #
# pnpm fixtures — task 4 verification.
# v6/v7 inline deps under `packages:`; v9 splits them out to `snapshots:`.
# parsePnpm in dep_tree_js.js reads both blocks so the same downstream logic
# works for either lockfile version.
# --------------------------------------------------------------------------- #


PNPM_LOCK_V6 = """\
lockfileVersion: '6.0'

dependencies:
  axios:
    specifier: ^1.6.0
    version: 1.6.0

packages:

  /axios@1.6.0:
    resolution: {integrity: sha512-aaaa==}
    dependencies:
      follow-redirects: 1.15.3
      form-data: 4.0.0
    dev: false

  /follow-redirects@1.15.3:
    resolution: {integrity: sha512-bbbb==}
    dev: false

  /form-data@4.0.0:
    resolution: {integrity: sha512-cccc==}
    dev: false
"""


PNPM_LOCK_V9 = """\
lockfileVersion: '9.0'

importers:

  .:
    dependencies:
      axios:
        specifier: ^1.6.0
        version: 1.6.0

packages:

  axios@1.6.0:
    resolution: {integrity: sha512-aaaa==}
    engines: {node: '>=14'}

  follow-redirects@1.15.3:
    resolution: {integrity: sha512-bbbb==}

  form-data@4.0.0:
    resolution: {integrity: sha512-cccc==}

snapshots:

  axios@1.6.0:
    dependencies:
      follow-redirects: 1.15.3
      form-data: 4.0.0

  follow-redirects@1.15.3: {}

  form-data@4.0.0: {}
"""


def test_pnpm_v6_lockfile_parses_direct_dep(
    node_bin, scripts_dir, js_deps_installed, tmp_path: Path
):
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "x", "dependencies": {"axios": "^1.6.0"}})
    )
    (tmp_path / "pnpm-lock.yaml").write_text(PNPM_LOCK_V6)

    out = _run(node_bin, scripts_dir, tmp_path, "axios")

    assert out["pkg_manager"] == "pnpm"
    assert out["source"] == "pnpm-lock"
    assert out["current_version"] == "1.6.0"
    assert out["is_direct"] is True


def test_pnpm_v6_transitive_parent_chain(node_bin, scripts_dir, js_deps_installed, tmp_path: Path):
    """form-data is transitive via axios — recommended strategy should be bump_parent."""
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "x", "dependencies": {"axios": "^1.6.0"}})
    )
    (tmp_path / "pnpm-lock.yaml").write_text(PNPM_LOCK_V6)

    out = _run(node_bin, scripts_dir, tmp_path, "form-data")

    assert out["pkg_manager"] == "pnpm"
    assert out["is_direct"] is False
    assert out["is_transitive"] is True
    assert "axios" in out["parent_packages"]
    assert "axios" in out["direct_parents"]
    assert out["recommended_strategy"] == "bump_parent"


def test_pnpm_v9_lockfile_parses_via_snapshots_block(
    node_bin, scripts_dir, js_deps_installed, tmp_path: Path
):
    """v9 splits deps into `snapshots:`; parser must merge both blocks."""
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "x", "dependencies": {"axios": "^1.6.0"}})
    )
    (tmp_path / "pnpm-lock.yaml").write_text(PNPM_LOCK_V9)

    out = _run(node_bin, scripts_dir, tmp_path, "axios")

    assert out["pkg_manager"] == "pnpm"
    assert out["source"] == "pnpm-lock"
    assert out["current_version"] == "1.6.0"
    assert out["is_direct"] is True


def test_pnpm_v9_transitive_parent_from_snapshots(
    node_bin, scripts_dir, js_deps_installed, tmp_path: Path
):
    """The dependency edge axios→form-data lives only in the snapshots block in v9."""
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "x", "dependencies": {"axios": "^1.6.0"}})
    )
    (tmp_path / "pnpm-lock.yaml").write_text(PNPM_LOCK_V9)

    out = _run(node_bin, scripts_dir, tmp_path, "form-data")

    assert out["pkg_manager"] == "pnpm"
    assert out["is_transitive"] is True
    assert "axios" in out["parent_packages"]
    assert "axios" in out["direct_parents"]


def test_pnpm_overrides_pin_detected(node_bin, scripts_dir, js_deps_installed, tmp_path: Path):
    """pnpm.overrides should be surfaced so Phase 2 picks bump_override over hand-edit."""
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "x",
                "dependencies": {"axios": "^1.6.0"},
                "pnpm": {"overrides": {"form-data": "4.0.4"}},
            }
        )
    )
    (tmp_path / "pnpm-lock.yaml").write_text(PNPM_LOCK_V9)

    out = _run(node_bin, scripts_dir, tmp_path, "form-data")

    pin = out["package_json_pin"]["pnpm_overrides"]
    assert pin is not None
    assert pin["kind"] == "pnpm-overrides"
    assert pin["value"] == "4.0.4"
    assert out["recommended_strategy"] == "bump_override"


def test_pnpm_workspace_locations_detected(
    node_bin, scripts_dir, js_deps_installed, tmp_path: Path
):
    """pnpm-workspace.yaml globs should be expanded into workspace_info.locations."""
    (tmp_path / "package.json").write_text(json.dumps({"name": "root", "private": True}))
    (tmp_path / "pnpm-workspace.yaml").write_text("packages:\n  - 'packages/*'\n")
    (tmp_path / "pnpm-lock.yaml").write_text(PNPM_LOCK_V9)

    ws_a = tmp_path / "packages" / "a"
    ws_a.mkdir(parents=True)
    (ws_a / "package.json").write_text(
        json.dumps({"name": "@x/a", "dependencies": {"axios": "^1.6.0"}})
    )
    ws_b = tmp_path / "packages" / "b"
    ws_b.mkdir(parents=True)
    (ws_b / "package.json").write_text(
        json.dumps({"name": "@x/b", "dependencies": {"lodash": "^4.17.0"}})
    )

    out = _run(node_bin, scripts_dir, tmp_path, "axios")
    ws_info = out["workspace_info"]
    assert ws_info["is_workspace_root"] is True
    locations = {loc["name"] for loc in ws_info["locations"]}
    assert "@x/a" in locations
    assert "@x/b" not in locations
