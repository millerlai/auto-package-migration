"""Tests for package-upgrade/scripts/go/govulncheck.sh's scan_status handling.

A stub `govulncheck` executable is put first on PATH so the wrapper's
behavior can be exercised without a real Go toolchain. Covers issue-68.md T1
cases (a)/(b)/(c): a failed scan must never yield `match: "not_present"`.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _make_govulncheck_stub(bin_dir: Path, body: str) -> None:
    stub = bin_dir / "govulncheck"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "-version" ]; then\n'
        '    echo "govulncheck v1.1.3"\n'
        "    exit 0\n"
        "fi\n"
        f"{body}\n"
    )
    stub.chmod(0o755)


def _run_govulncheck(
    bash_bin: str, scripts_dir: Path, project: Path, bin_dir: Path, *extra_args: str
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    (project / "go.mod").write_text("module example.com/app\n\ngo 1.21\n")
    return subprocess.run(
        [bash_bin, str(scripts_dir / "go" / "govulncheck.sh"), str(project), *extra_args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )


def test_scan_failure_exit1_empty_stdout_never_yields_not_present(bash_bin, scripts_dir, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_govulncheck_stub(bin_dir, 'echo "build failed: no go.sum" >&2\nexit 1')
    project = tmp_path / "project"
    project.mkdir()

    result = _run_govulncheck(bash_bin, scripts_dir, project, bin_dir, "--cve", "CVE-2024-99999")

    data = json.loads(result.stdout)
    assert data["scan_status"] == "failed"
    assert data["errors"]
    assert all(f["match"] != "not_present" for f in data["findings"])
    assert data["summary"]["not_present"] == 0


def test_stderr_credentials_are_redacted_from_errors(bash_bin, scripts_dir, tmp_path):
    """A failing module-proxy fetch against a credentialed GOPROXY
    (scheme://user:pass@host, a documented Go capability for corporate
    proxies) must not leak the credential into the wrapper's own kept
    stdout via the captured stderr tail.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_govulncheck_stub(
        bin_dir,
        'echo "go: module fetch failed: https://svc:s3cr3t-token@proxy.example.com/mod 401" >&2\nexit 1',
    )
    project = tmp_path / "project"
    project.mkdir()

    result = _run_govulncheck(bash_bin, scripts_dir, project, bin_dir)

    data = json.loads(result.stdout)
    assert data["scan_status"] == "failed"
    assert "s3cr3t-token" not in json.dumps(data)


def test_scan_exit0_with_findings_is_ok(bash_bin, scripts_dir, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    osv_obj = json.dumps(
        {
            "osv": {
                "id": "GO-2024-2611",
                "aliases": ["CVE-2024-24786"],
                "summary": "protojson unmarshal issue",
            }
        }
    )
    finding_obj = json.dumps(
        {
            "finding": {
                "osv": "GO-2024-2611",
                "fixed_version": "v1.33.0",
                "trace": [],
            }
        }
    )
    _make_govulncheck_stub(bin_dir, f"cat <<'JSON'\n{osv_obj}\n{finding_obj}\nJSON\nexit 0")
    project = tmp_path / "project"
    project.mkdir()

    result = _run_govulncheck(bash_bin, scripts_dir, project, bin_dir)

    data = json.loads(result.stdout)
    assert data["scan_status"] == "ok"
    assert len(data["findings"]) == 1
    assert data["findings"][0]["osv_id"] == "GO-2024-2611"


def test_scan_exit0_no_findings_is_ok(bash_bin, scripts_dir, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_govulncheck_stub(bin_dir, "exit 0")
    project = tmp_path / "project"
    project.mkdir()

    result = _run_govulncheck(bash_bin, scripts_dir, project, bin_dir)

    data = json.loads(result.stdout)
    assert data["scan_status"] == "ok"
    assert data["findings"] == []
