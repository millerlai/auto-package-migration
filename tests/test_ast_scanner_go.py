"""Tests for package-upgrade/scripts/ast_scanner_go.go.

Drives the scanner via `go run` against a minimal Go module built in tmp_path.
Asserts the verdict + schema added for cross-language Phase 4.0 short-circuit
(TODO task 1.2).

Skipped automatically when `go` is not installed (controlled by the `go_bin`
fixture in conftest.py).
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


def _make_module(tmp_path: Path, module_path: str = "example.com/proj") -> Path:
    """Create a minimal `go.mod` so `go run` and `go/parser` are happy."""
    (tmp_path / "go.mod").write_text(f"module {module_path}\n\ngo 1.21\n")
    return tmp_path


def _run(go_bin: str, scripts_dir: Path, project: Path, target: str) -> dict:
    script = scripts_dir / "ast_scanner_go.go"
    result = subprocess.run(
        [go_bin, "run", str(script), str(project), target],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"scanner failed: {result.stderr}"
    return json.loads(result.stdout)


def test_zero_impact_when_no_imports(go_bin, scripts_dir, tmp_path: Path):
    _make_module(tmp_path)
    (tmp_path / "main.go").write_text(
        'package main\n\nimport "fmt"\n\nfunc main() { fmt.Println("hi") }\n'
    )
    out = _run(go_bin, scripts_dir, tmp_path, "github.com/spf13/cobra")

    assert REQUIRED_TOP_LEVEL_KEYS.issubset(out.keys())
    assert out["verdict"] == "zero_impact"
    assert out["language"] == "go"
    assert out["import_count"] == 0
    assert out["usage_count"] == 0
    assert out["scan_results"] == []
    assert out["files_scanned"] >= 1
    assert out["total_files"] == out["files_scanned"]


def test_has_impact_when_target_imported(go_bin, scripts_dir, tmp_path: Path):
    _make_module(tmp_path)
    (tmp_path / "main.go").write_text(
        "package main\n\n"
        'import "github.com/spf13/cobra"\n\n'
        "func main() {\n"
        '    cmd := &cobra.Command{Use: "x"}\n'
        "    _ = cmd\n"
        "}\n"
    )
    out = _run(go_bin, scripts_dir, tmp_path, "github.com/spf13/cobra")

    assert out["verdict"] == "has_impact"
    assert out["import_count"] >= 1
    assert out["usage_count"] >= 1


def test_scan_errored_when_only_unparseable(go_bin, scripts_dir, tmp_path: Path):
    _make_module(tmp_path)
    # Intentionally broken syntax — go/parser will reject it.
    (tmp_path / "bad.go").write_text("package main\n\nfunc bad(\n")
    out = _run(go_bin, scripts_dir, tmp_path, "github.com/spf13/cobra")

    assert out["verdict"] == "scan_errored"
    assert out["warnings"] or "failed to parse" in out["verdict_reason"]


def test_major_version_path_matches_base(go_bin, scripts_dir, tmp_path: Path):
    """`import "pkg/v2"` should match a search for "pkg"."""
    _make_module(tmp_path)
    (tmp_path / "main.go").write_text(
        "package main\n\n"
        'import cobra "github.com/spf13/cobra/v2"\n\n'
        "func main() { _ = cobra.Command{} }\n"
    )
    out = _run(go_bin, scripts_dir, tmp_path, "github.com/spf13/cobra")

    assert out["verdict"] == "has_impact"
    # The module path should retain the /v2 suffix in the recorded import.
    modules = {imp["module"] for r in out["scan_results"] for imp in r["imports"]}
    assert any(m.endswith("/v2") for m in modules)


def test_submodule_import_recorded(go_bin, scripts_dir, tmp_path: Path):
    _make_module(tmp_path)
    (tmp_path / "main.go").write_text(
        "package main\n\n"
        'import "github.com/spf13/cobra/doc"\n\n'
        "func main() { _ = doc.GenManTree }\n"
    )
    out = _run(go_bin, scripts_dir, tmp_path, "github.com/spf13/cobra")

    assert out["verdict"] == "has_impact"
    types = {imp["type"] for r in out["scan_results"] for imp in r["imports"]}
    assert "submodule_import" in types


def test_blank_import_flagged(go_bin, scripts_dir, tmp_path: Path):
    _make_module(tmp_path)
    (tmp_path / "main.go").write_text(
        "package main\n\n" 'import _ "github.com/lib/pq"\n\n' "func main() {}\n"
    )
    out = _run(go_bin, scripts_dir, tmp_path, "github.com/lib/pq")

    assert out["verdict"] == "has_impact"
    types = {imp["type"] for r in out["scan_results"] for imp in r["imports"]}
    assert "blank_import" in types
    # blank imports record no usage symbol — pure side-effect import.
    assert out["usage_count"] == 0


def test_skips_vendor_dir(go_bin, scripts_dir, tmp_path: Path):
    _make_module(tmp_path)
    vendor_pq = tmp_path / "vendor" / "github.com" / "lib" / "pq"
    vendor_pq.mkdir(parents=True)
    (vendor_pq / "pq.go").write_text(
        'package pq\n\nimport "github.com/lib/pq"\n\nvar _ = pq.Open\n'
    )
    (tmp_path / "main.go").write_text("package main\n\nfunc main() {}\n")
    out = _run(go_bin, scripts_dir, tmp_path, "github.com/lib/pq")

    # The hit inside vendor/ must not count.
    assert out["verdict"] == "zero_impact"
