"""Tests for package-upgrade-feedback/scripts/sanitize_feedback.sh.

This script is the last gate before feedback is posted to a *public* GitHub
issue, so the important properties are:
  - it HALTs (exit 5) on anything that looks like a real credential, including
    the opaque tokens this skill actually handles (JFROG / Atlassian / Bearer);
  - it does NOT halt on the things that legitimately appear in upgrade feedback
    (git SHAs, version numbers, plain prose);
  - lower-confidence PII (paths, KEY=VALUE secrets) is redacted, not halted.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SANITIZER = ROOT / "package-upgrade-feedback" / "scripts" / "sanitize_feedback.sh"

HALT_EXIT = 5


def _run(bash_bin: str, tmp_path: Path, body: str) -> subprocess.CompletedProcess:
    f = tmp_path / "draft.md"
    f.write_text(body, encoding="utf-8")
    return subprocess.run(
        [bash_bin, str(SANITIZER), str(f)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


# --------------------------------------------------------------------------- #
# HALT — opaque tokens the skill handles (the gap this fix closes)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "secret",
    [
        # Atlassian modern API token (prefix ATATT, opaque tail)
        "ATATT3xFfGF0abcDEF123ghiJKL456mnoPQR789stuVWX",
        # JFROG / Artifactory API key (prefix AKCp)
        "AKCp" + "8aB3cD4eF5gH6iJ7kL8mN9oP0qR1sT2uV3wX4yZ5aB6cD7eF8gH9iJ0kL1mN2",
        # Generic high-entropy opaque token (no known prefix): mixed case + digit
        "x7Kp9QmZ2rT4vL8nW1sJ6dF3bH5gC0yA9eU2iO4pL7kM3nB",
    ],
)
def test_halts_on_opaque_tokens(bash_bin, tmp_path, secret):
    res = _run(bash_bin, tmp_path, f"The upgrade failed, token was {secret} when calling registry.")
    assert res.returncode == HALT_EXIT, res.stderr
    assert "HALT" in res.stderr


def test_halts_on_bearer_header(bash_bin, tmp_path):
    res = _run(bash_bin, tmp_path, "I set Authorization: Bearer abcDEF123ghiJKL456mnoPQR789stu")
    assert res.returncode == HALT_EXIT, res.stderr


# --------------------------------------------------------------------------- #
# Must NOT halt — things that legitimately appear in upgrade feedback
# --------------------------------------------------------------------------- #


def test_git_sha_does_not_halt(bash_bin, tmp_path):
    # 40-char lowercase hex commit SHA — extremely common in upgrade reports.
    res = _run(
        bash_bin,
        tmp_path,
        "Fixed in commit 9f2c1 a, full sha a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
    )
    assert res.returncode == 0, res.stderr


def test_plain_prose_does_not_halt(bash_bin, tmp_path):
    res = _run(
        bash_bin,
        tmp_path,
        "The dependency-tree analysis step felt slow and the changelog fetch "
        "timed out twice; consider adding a retry.",
    )
    assert res.returncode == 0, res.stderr
    assert "retry" in res.stdout


# --------------------------------------------------------------------------- #
# Lower-confidence redaction (exit 0, value scrubbed)
# --------------------------------------------------------------------------- #


def test_redacts_token_env_line(bash_bin, tmp_path):
    res = _run(bash_bin, tmp_path, "MY_API_TOKEN=short_but_named_secret_value")
    assert res.returncode == 0, res.stderr
    assert "<redacted>" in res.stdout
    assert "short_but_named_secret_value" not in res.stdout


def test_windows_path_with_spaces_fully_redacted(bash_bin, tmp_path):
    # Regression for the malformed [^\\s...] character class: the path tail
    # (after the username) must not leak.
    res = _run(bash_bin, tmp_path, r"Saved to C:\Users\alice\creds.txt today")
    assert res.returncode == 0, res.stderr
    assert "<path>" in res.stdout
    assert "creds.txt" not in res.stdout
