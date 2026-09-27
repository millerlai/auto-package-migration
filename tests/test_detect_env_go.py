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
    script = scripts_dir / "go" / "detect_env.sh"
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


def test_replace_single_line_trailing_comment(bash_bin, scripts_dir, tmp_path: Path):
    # T2 (#68): a trailing `// comment` on a `replace` line must not drop
    # the entry from replace_directives. This exercises the regex fallback
    # path (no go_bin fixture — the `go mod edit -json` path degrades
    # gracefully when `go` isn't on PATH).
    (tmp_path / "go.mod").write_text(
        "module example.com/proj\n\n"
        "go 1.21\n\n"
        "require golang.org/x/net v0.17.0\n\n"
        "replace golang.org/x/net v0.17.0 => golang.org/x/net v0.23.0 "
        "// CVE-2023-45288 pin\n"
    )
    out = _run(bash_bin, scripts_dir, tmp_path)

    assert out["has_replace_directives"] is True
    assert len(out["replace_directives"]) == 1
    r = out["replace_directives"][0]
    assert r["old"] == "golang.org/x/net"
    assert r["old_version"] == "v0.17.0"
    assert r["new"] == "golang.org/x/net"
    assert r["new_version"] == "v0.23.0"


def test_replace_block_entry_trailing_comment(bash_bin, scripts_dir, tmp_path: Path):
    (tmp_path / "go.mod").write_text(
        "module example.com/proj\n\n"
        "go 1.21\n\n"
        "replace (\n"
        "    golang.org/x/text => golang.org/x/text v0.14.0 // pinned\n"
        ")\n"
    )
    out = _run(bash_bin, scripts_dir, tmp_path)

    assert out["has_replace_directives"] is True
    assert len(out["replace_directives"]) == 1
    r = out["replace_directives"][0]
    assert r["old"] == "golang.org/x/text"
    assert r["new"] == "golang.org/x/text"
    assert r["new_version"] == "v0.14.0"


def test_replace_single_line_trailing_comment_via_toolchain(
    go_bin, bash_bin, scripts_dir, tmp_path: Path
):
    # (#68 fix-up) test_replace_single_line_trailing_comment above only
    # exercises the regex fallback (no `go_bin` fixture). This exercises the
    # primary `go mod edit -json | jq` path (detect_env.sh:127-141) so a
    # broken jq field mapping doesn't pass unnoticed in CI, per detail-design
    # R2's "integration, CI (`go mod edit -json`, detect_env.sh)" row.
    (tmp_path / "go.mod").write_text(
        "module example.com/proj\n\n"
        "go 1.21\n\n"
        "require golang.org/x/net v0.17.0\n\n"
        "replace golang.org/x/net v0.17.0 => golang.org/x/net v0.23.0 "
        "// CVE-2023-45288 pin\n"
    )
    out = _run(bash_bin, scripts_dir, tmp_path)

    assert out["has_replace_directives"] is True
    assert len(out["replace_directives"]) == 1
    r = out["replace_directives"][0]
    assert r["old"] == "golang.org/x/net"
    assert r["old_version"] == "v0.17.0"
    assert r["new"] == "golang.org/x/net"
    assert r["new_version"] == "v0.23.0"


def test_replace_block_entry_trailing_comment_via_toolchain(
    go_bin, bash_bin, scripts_dir, tmp_path: Path
):
    # (#68 fix-up) same as above, block form.
    (tmp_path / "go.mod").write_text(
        "module example.com/proj\n\n"
        "go 1.21\n\n"
        "replace (\n"
        "    golang.org/x/text => golang.org/x/text v0.14.0 // pinned\n"
        ")\n"
    )
    out = _run(bash_bin, scripts_dir, tmp_path)

    assert out["has_replace_directives"] is True
    assert len(out["replace_directives"]) == 1
    r = out["replace_directives"][0]
    assert r["old"] == "golang.org/x/text"
    assert r["new"] == "golang.org/x/text"
    assert r["new_version"] == "v0.14.0"


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
