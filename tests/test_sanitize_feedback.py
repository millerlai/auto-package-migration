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
# HALT — credentials embedded in URLs / npm registry auth keys
# (short passwords with punctuation slip past the high-entropy heuristic)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "line, password",
    [
        (
            "npm config set registry https://ci:S3cr3t!Tok3n(x)@npm.internal.example.org/",
            "S3cr3t",
        ),
        ("https://admin:Pa$$w0rd#2024@pypi.internal.example.org/simple", "Pa$$w0rd"),
        # '@' inside the password: userinfo runs to the last '@' before the host
        ("https://user:p@ss@host.example.org/x", "p@ss"),
    ],
)
def test_halts_on_url_credentials(bash_bin, tmp_path, line, password):
    res = _run(bash_bin, tmp_path, f"Registry setup: {line}")
    assert res.returncode == HALT_EXIT, res.stderr
    assert "HALT" in res.stderr
    # The HALT report itself must not echo the credential back.
    assert password not in res.stderr
    assert password not in res.stdout


@pytest.mark.parametrize(
    "line",
    [
        "//npm.internal.example.org/:_authToken=abc123",
        "//npm.internal.example.org/repo/:_password=c2VjcmV0",
        "//npm.internal.example.org/:_auth=dXNlcjpwYXNz",
    ],
)
def test_halts_on_npm_registry_auth_key(bash_bin, tmp_path, line):
    res = _run(bash_bin, tmp_path, f"My .npmrc has {line}")
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


@pytest.mark.parametrize(
    "line",
    [
        # userinfo without a password
        "Clone via ssh://git@github.com/owner/repo.git",
        # '@' only in the query string, not in userinfo
        "See https://host.example.org/p?email=a@b.com",
        # host:port is not userinfo
        "Registry is https://registry.example.org:8443/npm/",
        # placeholders are config examples, not credentials
        "Set registry https://ci:${NPM_PASS}@npm.example.org/",
        "Use https://<user>:<token>@npm.example.org/",
        "//npm.example.org/:_authToken=${JFROG_TOKEN}",
        "//npm.example.org/:_authToken=<token>",
    ],
)
def test_url_and_npmrc_non_secrets_do_not_halt(bash_bin, tmp_path, line):
    res = _run(bash_bin, tmp_path, line)
    assert res.returncode == 0, res.stderr


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
