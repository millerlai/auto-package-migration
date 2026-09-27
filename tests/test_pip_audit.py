"""Tests for package-upgrade/scripts/python/pip_audit.sh's scan_status handling.

A stub `pip-audit` executable is put first on PATH so the wrapper's behavior
can be exercised without a real scan. Covers issue-68.md T1 cases (a)/(b)/(c):
a failed scan must never yield `match: "not_present"`.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _make_pip_audit_stub(bin_dir: Path, body: str) -> None:
    """Write a fake `pip-audit` executable that dispatches on its args.

    `body` is the shell snippet run for the real scan invocation; `--version`
    is always handled the same way so PA_VERSION parsing doesn't interfere.
    """
    stub = bin_dir / "pip-audit"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "--version" ]; then\n'
        '    echo "pip-audit 2.7.0"\n'
        "    exit 0\n"
        "fi\n"
        f"{body}\n"
    )
    stub.chmod(0o755)


def _run_pip_audit(
    bash_bin: str, scripts_dir: Path, project: Path, bin_dir: Path, *extra_args: str
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    return subprocess.run(
        [bash_bin, str(scripts_dir / "python" / "pip_audit.sh"), str(project), *extra_args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )


def test_scan_failure_empty_stdout_never_yields_not_present(bash_bin, scripts_dir, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_pip_audit_stub(bin_dir, 'echo "boom: could not resolve dependency" >&2\nexit 1')
    project = tmp_path / "project"
    project.mkdir()

    result = _run_pip_audit(bash_bin, scripts_dir, project, bin_dir, "--cve", "CVE-2024-99999")

    data = json.loads(result.stdout)
    assert data["scan_status"] == "failed"
    assert data["errors"]
    assert all(f["match"] != "not_present" for f in data["findings"])
    assert data["summary"]["not_present"] == 0


def test_scan_exit1_with_valid_json_is_ok(bash_bin, scripts_dir, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    audit_json = json.dumps(
        {
            "dependencies": [
                {
                    "name": "pillow",
                    "version": "9.5.0",
                    "vulns": [
                        {
                            "id": "PYSEC-2023-1",
                            "aliases": ["CVE-2023-1111"],
                            "fix_versions": ["10.0.1"],
                            "description": "Buffer overflow in ImageFont.truetype",
                        }
                    ],
                }
            ]
        }
    )
    _make_pip_audit_stub(bin_dir, f"cat <<'JSON'\n{audit_json}\nJSON\nexit 1")
    project = tmp_path / "project"
    project.mkdir()

    result = _run_pip_audit(bash_bin, scripts_dir, project, bin_dir)

    data = json.loads(result.stdout)
    assert data["scan_status"] == "ok"
    assert len(data["findings"]) == 1
    assert data["findings"][0]["osv_id"] == "PYSEC-2023-1"


def test_scan_exit0_no_findings_is_ok(bash_bin, scripts_dir, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_pip_audit_stub(bin_dir, "echo '{\"dependencies\": []}'\nexit 0")
    project = tmp_path / "project"
    project.mkdir()

    result = _run_pip_audit(bash_bin, scripts_dir, project, bin_dir)

    data = json.loads(result.stdout)
    assert data["scan_status"] == "ok"
    assert data["findings"] == []


def test_dependencies_not_a_list_reports_failed_instead_of_crashing(
    bash_bin, scripts_dir, tmp_path
):
    """A malformed `dependencies` value (present but not a list) must still
    produce valid scan_status:"failed" JSON, not an unhandled Python
    exception with empty stdout.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_pip_audit_stub(bin_dir, 'echo \'{"dependencies": {"oops": "not-a-list"}}\'\nexit 0')
    project = tmp_path / "project"
    project.mkdir()

    result = _run_pip_audit(bash_bin, scripts_dir, project, bin_dir)

    data = json.loads(result.stdout)
    assert data["scan_status"] == "failed"
    assert all(f["match"] != "not_present" for f in data["findings"])


def test_stderr_credentials_are_redacted_from_errors(bash_bin, scripts_dir, tmp_path):
    """A failing request against a credentialed private index (e.g.
    `https://svc:TOKEN@host/simple/`) must not leak the token into the
    wrapper's own kept stdout via the captured stderr tail.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_pip_audit_stub(
        bin_dir,
        'echo "ConnectionError: https://svc:s3cr3t-token@jfrog.example.com/simple/ 401" >&2\nexit 1',
    )
    project = tmp_path / "project"
    project.mkdir()

    result = _run_pip_audit(bash_bin, scripts_dir, project, bin_dir)

    data = json.loads(result.stdout)
    assert data["scan_status"] == "failed"
    assert "s3cr3t-token" not in json.dumps(data)


def test_skip_reason_entries_become_warnings(bash_bin, scripts_dir, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    audit_json = json.dumps(
        {
            "dependencies": [
                {"name": "some-editable-pkg", "version": "", "skip_reason": "no version found"}
            ]
        }
    )
    _make_pip_audit_stub(bin_dir, f"cat <<'JSON'\n{audit_json}\nJSON\nexit 0")
    project = tmp_path / "project"
    project.mkdir()

    result = _run_pip_audit(bash_bin, scripts_dir, project, bin_dir)

    data = json.loads(result.stdout)
    assert data["scan_status"] == "ok"
    assert len(data["warnings"]) == 1
    assert "no version found" in data["warnings"][0]
