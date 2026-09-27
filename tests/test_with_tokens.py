"""Tests for scripts/common/with_tokens.sh — the wrapper that gets a saved
registry token to a later Bash tool call (each call is a fresh shell, so an
earlier `export` is gone by the time Phase 5 runs; platform docs, R10).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _run(
    bash_bin: str, scripts_dir: Path, args: list[str], extra_env: dict[str, str] | None = None
):
    script = scripts_dir / "common" / "with_tokens.sh"
    env = {k: v for k, v in os.environ.items() if k != "JFROG_TOKEN"}
    env.update(extra_env or {})
    return subprocess.run(
        [bash_bin, str(script), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=env,
    )


def test_loads_saved_token_and_runs_command(bash_bin, scripts_dir, tmp_path: Path):
    (tmp_path / ".env.jfrog").write_text("JFROG_TOKEN='x'\n")

    result = _run(bash_bin, scripts_dir, [str(tmp_path), "js", "--", "env"])

    assert result.returncode == 0, result.stderr
    assert "JFROG_TOKEN=x" in result.stdout.splitlines()


def test_value_with_command_substitution_stays_literal(bash_bin, scripts_dir, tmp_path: Path):
    (tmp_path / ".env.jfrog").write_text("JFROG_TOKEN='a$(echo pwned)b'\n")

    result = _run(bash_bin, scripts_dir, [str(tmp_path), "js", "--", "env"])

    assert result.returncode == 0, result.stderr
    assert "JFROG_TOKEN=a$(echo pwned)b" in result.stdout.splitlines()


def test_already_set_variable_beats_the_file(bash_bin, scripts_dir, tmp_path: Path):
    (tmp_path / ".env.jfrog").write_text("JFROG_TOKEN='from-file'\n")

    result = _run(
        bash_bin,
        scripts_dir,
        [str(tmp_path), "js", "--", "env"],
        extra_env={"JFROG_TOKEN": "from-prefix"},
    )

    assert result.returncode == 0, result.stderr
    assert "JFROG_TOKEN=from-prefix" in result.stdout.splitlines()
    assert "JFROG_TOKEN=from-file" not in result.stdout.splitlines()


def test_unknown_language_exits_2(bash_bin, scripts_dir, tmp_path: Path):
    result = _run(bash_bin, scripts_dir, [str(tmp_path), "ruby", "--", "env"])

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.strip()
