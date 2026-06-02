"""Tests for save_token.sh + load_token_files.sh.

The pair persists and re-loads auth tokens. The security-critical property is
that a token value is treated as opaque data on BOTH ends: written
single-quoted, and loaded by a textual KEY=VALUE parser — never `source`d. A
value containing `$(...)` must round-trip literally and must NOT execute.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAVE = ROOT / "package-upgrade" / "scripts" / "common" / "save_token.sh"
LOADER = ROOT / "package-upgrade" / "scripts" / "common" / "load_token_files.sh"


def _save(bash_bin, project, name, key, value, *extra):
    # Pass the value through an env var rather than argv: Git Bash / MSYS on
    # Windows re-parses single quotes in the Windows command line, which would
    # mangle test values like "ab'cd". Env vars are not re-parsed.
    env = {**os.environ, "TOKVAL": value}
    inner = f'"{SAVE}" "$1" "$2" "$3" "$TOKVAL" "$4"'
    cmd = [bash_bin, "-c", inner, "_", str(project), name, key, (extra[0] if extra else "")]
    return subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _load_value(bash_bin, project, name, key):
    """Source load_token_files.sh, load `name`, echo the resulting env var."""
    script = (
        f'. "{LOADER}"; '
        f'load_token_files "{project}" "{name}" >/dev/null 2>&1; '
        f'printf "%s" "${{{key}:-<UNSET>}}"'
    )
    res = subprocess.run(
        [bash_bin, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return res.stdout


# --------------------------------------------------------------------------- #
# save_token.sh
# --------------------------------------------------------------------------- #


def test_create_is_single_quoted_and_600(bash_bin, tmp_path):
    res = _save(bash_bin, tmp_path, ".env.jfrog", "JFROG_TOKEN", "cmVkYWN0ZWQ=")
    assert res.returncode == 0, res.stderr
    f = tmp_path / ".env.jfrog"
    assert f.read_text().strip() == "JFROG_TOKEN='cmVkYWN0ZWQ='"
    mode = stat.S_IMODE(f.stat().st_mode)
    if os.name != "nt":  # Windows has no POSIX perms
        assert mode == 0o600, oct(mode)
    assert ".env.jfrog" in (tmp_path / ".gitignore").read_text()


def test_conflict_then_force_replaces(bash_bin, tmp_path):
    _save(bash_bin, tmp_path, ".env.jfrog", "JFROG_TOKEN", "old")
    conflict = _save(bash_bin, tmp_path, ".env.jfrog", "JFROG_TOKEN", "new")
    assert conflict.returncode == 2, conflict.stderr
    forced = _save(bash_bin, tmp_path, ".env.jfrog", "JFROG_TOKEN", "new", "--force")
    assert forced.returncode == 0, forced.stderr
    assert (tmp_path / ".env.jfrog").read_text().strip() == "JFROG_TOKEN='new'"


def test_append_second_key(bash_bin, tmp_path):
    _save(bash_bin, tmp_path, ".env.jfrog", "JFROG_TOKEN", "a")
    _save(bash_bin, tmp_path, ".env.jfrog", "NPM_TOKEN", "b")
    body = (tmp_path / ".env.jfrog").read_text()
    assert "JFROG_TOKEN='a'" in body and "NPM_TOKEN='b'" in body


def test_rejects_single_quote_value(bash_bin, tmp_path):
    res = _save(bash_bin, tmp_path, ".env.jfrog", "JFROG_TOKEN", "ab'cd")
    assert res.returncode == 1, res.stderr
    assert not (tmp_path / ".env.jfrog").exists()


# --------------------------------------------------------------------------- #
# RCE regression — value with $(...) must not execute on save OR load
# --------------------------------------------------------------------------- #


def test_dangerous_value_round_trips_literally(bash_bin, tmp_path):
    sentinel = tmp_path / "PWNED"
    payload = f"abc$(touch {sentinel})def"
    res = _save(bash_bin, tmp_path, ".env.jfrog", "JFROG_TOKEN", payload)
    assert res.returncode == 0, res.stderr
    assert not sentinel.exists(), "command substitution executed on save"

    loaded = _load_value(bash_bin, tmp_path, ".env.jfrog", "JFROG_TOKEN")
    assert not sentinel.exists(), "command substitution executed on load"
    assert loaded == payload, f"value did not round-trip literally: {loaded!r}"


def test_planted_env_file_is_not_executed(bash_bin, tmp_path):
    """A token file the skill did NOT write (e.g. planted in a cloned repo)
    must be parsed, not sourced."""
    sentinel = tmp_path / "PLANTED"
    (tmp_path / ".env.jfrog").write_text(f"JFROG_TOKEN=x$(touch {sentinel})y\n")
    loaded = _load_value(bash_bin, tmp_path, ".env.jfrog", "JFROG_TOKEN")
    assert not sentinel.exists(), "planted .env file was sourced (RCE)"
    assert loaded == f"x$(touch {sentinel})y"
