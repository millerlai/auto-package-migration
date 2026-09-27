"""Tests for package-upgrade/scripts/ast_scanner_js.js.

Drives the script via subprocess (the helper is a Node program). Every test
builds a minimal fixture project in tmp_path and asserts on the top-level
JSON schema, especially the verdict field added for cross-language Phase 4.0
short-circuit (TODO task 1.2).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REQUIRED_TOP_LEVEL_KEYS = {
    "scan_results",
    "total_files",
    "files_scanned",
    "import_count",
    "usage_count",
    "package_name",
    "language",
    "warnings",
    "verdict",
    "verdict_reason",
}


def _run(node_bin: str, scripts_dir: Path, project: Path, package: str) -> dict:
    script = scripts_dir / "javascript" / "ast_scanner.js"
    result = subprocess.run(
        [node_bin, str(script), str(project), package],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"scanner failed: {result.stderr}"
    return json.loads(result.stdout)


def test_zero_impact_when_no_matching_imports(
    node_bin, scripts_dir, js_deps_installed, tmp_path: Path
):
    (tmp_path / "a.js").write_text("const fs = require('fs');\nfs.existsSync('x');\n")
    out = _run(node_bin, scripts_dir, tmp_path, "axios")

    assert REQUIRED_TOP_LEVEL_KEYS.issubset(out.keys())
    assert out["verdict"] == "zero_impact"
    assert out["language"] == "javascript"
    assert out["import_count"] == 0
    assert out["usage_count"] == 0
    assert out["scan_results"] == []
    assert out["warnings"] == []
    assert out["files_scanned"] >= 1
    assert out["total_files"] == out["files_scanned"]


def test_has_impact_when_package_imported(node_bin, scripts_dir, js_deps_installed, tmp_path: Path):
    (tmp_path / "a.js").write_text("import axios from 'axios';\naxios.get('http://x');\n")
    out = _run(node_bin, scripts_dir, tmp_path, "axios")

    assert out["verdict"] == "has_impact"
    assert out["import_count"] >= 1
    assert out["usage_count"] >= 1
    assert len(out["scan_results"]) == 1


def test_scan_errored_when_only_unparseable_files(
    node_bin, scripts_dir, js_deps_installed, tmp_path: Path
):
    # Hard syntax error — even babel's errorRecovery fallback chokes on this.
    (tmp_path / "bad.js").write_text("function bad( {\n")
    out = _run(node_bin, scripts_dir, tmp_path, "axios")

    assert out["verdict"] == "scan_errored"
    assert out["warnings"], "expected a parse-failure warning"
    assert "failed to parse" in out["warnings"][0]


def test_cjs_require_records_match(node_bin, scripts_dir, js_deps_installed, tmp_path: Path):
    (tmp_path / "a.js").write_text("const axios = require('axios');\naxios.get('x');\n")
    out = _run(node_bin, scripts_dir, tmp_path, "axios")

    assert out["verdict"] == "has_impact"
    import_types = {imp["type"] for imp in out["scan_results"][0]["imports"]}
    assert "cjs_default" in import_types


def test_submodule_import_matches_root_package(
    node_bin, scripts_dir, js_deps_installed, tmp_path: Path
):
    (tmp_path / "a.js").write_text("import adapter from 'axios/lib/adapter';\n")
    out = _run(node_bin, scripts_dir, tmp_path, "axios")

    assert out["verdict"] == "has_impact"
    assert out["scan_results"][0]["imports"][0]["module"] == "axios/lib/adapter"


def test_package_name_prefix_only_matches_full_segment(
    node_bin, scripts_dir, js_deps_installed, tmp_path: Path
):
    # "axios-retry" must NOT match a search for "axios"
    (tmp_path / "a.js").write_text("import x from 'axios-retry';\n")
    out = _run(node_bin, scripts_dir, tmp_path, "axios")

    assert out["verdict"] == "zero_impact"


def test_skips_node_modules(node_bin, scripts_dir, js_deps_installed, tmp_path: Path):
    nm = tmp_path / "node_modules" / "axios"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("import axios from 'axios';\n")
    (tmp_path / "real.js").write_text("// no usage\n")
    out = _run(node_bin, scripts_dir, tmp_path, "axios")

    assert out["verdict"] == "zero_impact"


def test_typescript_file_parsed(node_bin, scripts_dir, js_deps_installed, tmp_path: Path):
    (tmp_path / "a.ts").write_text(
        "import axios, { AxiosInstance } from 'axios';\n"
        "const client: AxiosInstance = axios.create();\n"
    )
    out = _run(node_bin, scripts_dir, tmp_path, "axios")

    assert out["verdict"] == "has_impact"
    assert out["import_count"] >= 2  # default + named


def test_export_all_reexport(node_bin, scripts_dir, js_deps_installed, tmp_path: Path):
    (tmp_path / "a.js").write_text("export * from 'axios';\n")
    out = _run(node_bin, scripts_dir, tmp_path, "axios")

    assert out["verdict"] == "has_impact"
    imp = out["scan_results"][0]["imports"][0]
    assert imp["type"] == "esm_reexport_all"
    assert imp["module"] == "axios"


def test_export_all_as_namespace_reexport(node_bin, scripts_dir, js_deps_installed, tmp_path: Path):
    # @babel/parser parses `export * as ns from 'pkg'` as ExportNamedDeclaration
    # with an ExportNamespaceSpecifier, not ExportAllDeclaration.
    (tmp_path / "a.js").write_text("export * as ns from 'axios';\n")
    out = _run(node_bin, scripts_dir, tmp_path, "axios")

    assert out["verdict"] == "has_impact"
    imp = out["scan_results"][0]["imports"][0]
    assert imp["type"] == "esm_reexport_namespace"
    assert imp["exported"] == "ns"


def test_export_named_reexport_with_alias(node_bin, scripts_dir, js_deps_installed, tmp_path: Path):
    (tmp_path / "a.js").write_text("export { a, default as b } from 'axios';\n")
    out = _run(node_bin, scripts_dir, tmp_path, "axios")

    assert out["verdict"] == "has_impact"
    imports = out["scan_results"][0]["imports"]
    types = {imp["type"] for imp in imports}
    assert types == {"esm_reexport_named"}
    pairs = {(imp["imported"], imp["exported"]) for imp in imports}
    assert pairs == {("a", "a"), ("default", "b")}


def test_export_type_only_reexport(node_bin, scripts_dir, js_deps_installed, tmp_path: Path):
    (tmp_path / "a.ts").write_text("export type { T } from 'axios';\n")
    out = _run(node_bin, scripts_dir, tmp_path, "axios")

    assert out["verdict"] == "has_impact"
    imp = out["scan_results"][0]["imports"][0]
    assert imp["type"] == "esm_type_only"


def test_reexport_creates_no_local_binding(
    node_bin, scripts_dir, js_deps_installed, tmp_path: Path
):
    (tmp_path / "a.js").write_text("export { a } from 'axios';\nconst a = 1;\na;\n")
    out = _run(node_bin, scripts_dir, tmp_path, "axios")

    # `a` here is a fresh local binding, not tied to the re-export, so the
    # usage tracker must not attribute it to axios.
    assert out["verdict"] == "has_impact"
    assert out["usage_count"] == 0


def test_barrel_only_project_has_impact(node_bin, scripts_dir, js_deps_installed, tmp_path: Path):
    (tmp_path / "index.js").write_text("export * from 'axios';\nexport { a } from 'axios';\n")
    out = _run(node_bin, scripts_dir, tmp_path, "axios")

    assert out["verdict"] == "has_impact"
    assert out["import_count"] == 2


def test_require_member_access_init(node_bin, scripts_dir, js_deps_installed, tmp_path: Path):
    (tmp_path / "a.js").write_text("const get = require('axios').get;\n")
    out = _run(node_bin, scripts_dir, tmp_path, "axios")

    assert out["verdict"] == "has_impact"
    imp = out["scan_results"][0]["imports"][0]
    assert imp["type"] == "cjs_member"


def test_require_member_access_usage_tracked(
    node_bin, scripts_dir, js_deps_installed, tmp_path: Path
):
    # const get = require('axios').get; get('/status');
    # `get` is a real local binding (unlike a re-export), so a later call
    # through it must be attributed to axios's usage tracking.
    (tmp_path / "a.js").write_text("const get = require('axios').get;\nget('/status');\n")
    out = _run(node_bin, scripts_dir, tmp_path, "axios")

    assert out["verdict"] == "has_impact"
    assert out["usage_count"] == 1
    assert out["scan_results"][0]["usages"][0]["symbol"] == "axios.get"


def test_require_module_exports_reexport(node_bin, scripts_dir, js_deps_installed, tmp_path: Path):
    (tmp_path / "a.js").write_text("module.exports = require('axios');\n")
    out = _run(node_bin, scripts_dir, tmp_path, "axios")

    assert out["verdict"] == "has_impact"
    imp = out["scan_results"][0]["imports"][0]
    assert imp["type"] == "cjs_reexport"


def test_require_bare_statement(node_bin, scripts_dir, js_deps_installed, tmp_path: Path):
    (tmp_path / "a.js").write_text("require('axios');\n")
    out = _run(node_bin, scripts_dir, tmp_path, "axios")

    assert out["verdict"] == "has_impact"
    imp = out["scan_results"][0]["imports"][0]
    assert imp["type"] == "cjs_side_effect"
