"""Regression test for issue #68 T4: python/run_tests.sh emitted invalid
JSON on the green path.

`grep -c PATTERN file || echo "0"` prints the count *and* "0" when the
pattern has zero matches (grep -c exits 1 on no matches), so a passing run
produced `"failed": 0\n0,` -- invalid JSON exactly when everything passed.

Covers all-pass, one-failure and a collection-error fixture: assert
`json.loads` succeeds and the passed/failed/errors counts are exact.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _run_tests_sh(scripts_dir: Path) -> Path:
    return scripts_dir / "python" / "run_tests.sh"


def _run(
    bash_bin: str,
    scripts_dir: Path,
    project: Path,
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [bash_bin, str(_run_tests_sh(scripts_dir)), str(project)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=env,
    )


def _to_posix(path: str) -> str:
    """Windows path -> POSIX-style path git-bash's own PATH search understands
    (e.g. "C:\\Git\\usr\\bin" -> "/c/Git/usr/bin")."""
    posix = path.replace("\\", "/")
    if len(posix) >= 2 and posix[1] == ":":
        posix = "/" + posix[0].lower() + posix[2:]
    return posix


def _unittest_env(bash_bin: str, tmp_path: Path) -> dict:
    """Environment that forces run_tests.sh onto its `python3 -m unittest`
    branch instead of pytest: a PATH with no `pytest` binary on it, plus a
    `python3` shim whose `-m pytest --version` fails (as if pytest weren't
    installed) but which otherwise execs the real interpreter running this
    test suite."""
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    shim = shim_dir / "python3"
    real_python = _to_posix(sys.executable)
    with shim.open("w", newline="\n") as f:
        f.write(
            "#!/usr/bin/env bash\n"
            'if [ "$1" = "-m" ] && [ "$2" = "pytest" ]; then\n'
            "    exit 1\n"
            "fi\n"
            f'exec "{real_python}" "$@"\n'
        )
    shim.chmod(0o755)

    coreutils_dir = _to_posix(str(Path(bash_bin).parent))
    jq_bin = shutil.which("jq")
    if jq_bin is None:
        pytest.skip("jq not installed")
    jq_dir = _to_posix(str(Path(jq_bin).parent))

    env = dict(os.environ)
    env["PATH"] = ":".join([_to_posix(str(shim_dir)), coreutils_dir, jq_dir])
    return env


def _all_pass_project(tmp_path: Path) -> Path:
    project = tmp_path / "all_pass"
    project.mkdir()
    (project / "test_ok.py").write_text(
        "def test_a():\n    assert 1 == 1\n\n\ndef test_b():\n    assert 2 == 2\n"
    )
    return project


def _one_failure_project(tmp_path: Path) -> Path:
    project = tmp_path / "one_failure"
    project.mkdir()
    (project / "test_mix.py").write_text(
        "def test_a():\n    assert 1 == 1\n\n\ndef test_b():\n    assert 1 == 2\n"
    )
    return project


def _collection_error_project(tmp_path: Path) -> Path:
    project = tmp_path / "collection_error"
    project.mkdir()
    # Invalid syntax: pytest can't even collect this file.
    (project / "test_broken.py").write_text("def test_bad(:\n    pass\n")
    return project


def test_all_pass_gives_exact_counts(bash_bin, scripts_dir, tmp_path):
    project = _all_pass_project(tmp_path)

    result = _run(bash_bin, scripts_dir, project)

    payload = json.loads(result.stdout)
    assert payload["passed"] == 2
    assert payload["failed"] == 0
    assert payload["errors"] == 0
    assert payload["exit_code"] == 0
    assert result.returncode == 0


def test_one_failure_gives_exact_counts(bash_bin, scripts_dir, tmp_path):
    project = _one_failure_project(tmp_path)

    result = _run(bash_bin, scripts_dir, project)

    payload = json.loads(result.stdout)
    assert payload["passed"] == 1
    assert payload["failed"] == 1
    assert payload["errors"] == 0
    assert payload["exit_code"] != 0
    assert "test_b" in payload["traceback"]


def test_collection_error_gives_exact_counts(bash_bin, scripts_dir, tmp_path):
    project = _collection_error_project(tmp_path)

    result = _run(bash_bin, scripts_dir, project)

    payload = json.loads(result.stdout)
    assert payload["passed"] == 0
    assert payload["failed"] == 0
    assert payload["errors"] == 1
    assert payload["exit_code"] != 0
    assert "SyntaxError" in payload["traceback"]


def _unittest_skip_project(tmp_path: Path) -> Path:
    project = tmp_path / "unittest_skip"
    project.mkdir()
    (project / "test_skip.py").write_text(
        "import unittest\n\n\n"
        "class T(unittest.TestCase):\n"
        "    def test_pass(self):\n"
        "        self.assertEqual(1, 1)\n\n"
        "    @unittest.skip('not needed')\n"
        "    def test_skipped(self):\n"
        "        self.fail('should not run')\n"
    )
    return project


def _unittest_expected_failure_project(tmp_path: Path) -> Path:
    project = tmp_path / "unittest_xfail"
    project.mkdir()
    (project / "test_xfail.py").write_text(
        "import unittest\n\n\n"
        "class T(unittest.TestCase):\n"
        "    def test_pass(self):\n"
        "        self.assertEqual(1, 1)\n\n"
        "    @unittest.expectedFailure\n"
        "    def test_known_broken(self):\n"
        "        self.assertEqual(1, 2)\n"
    )
    return project


def test_unittest_skipped_test_is_not_counted_as_passed(bash_bin, scripts_dir, tmp_path):
    project = _unittest_skip_project(tmp_path)
    env = _unittest_env(bash_bin, tmp_path)

    result = _run(bash_bin, scripts_dir, project, env=env)

    assert "python3 -m unittest" in result.stderr
    payload = json.loads(result.stdout)
    assert payload["passed"] == 1
    assert payload["failed"] == 0
    assert payload["errors"] == 0
    assert payload["exit_code"] == 0


def test_unittest_expected_failure_is_not_counted_as_failed(bash_bin, scripts_dir, tmp_path):
    project = _unittest_expected_failure_project(tmp_path)
    env = _unittest_env(bash_bin, tmp_path)

    result = _run(bash_bin, scripts_dir, project, env=env)

    assert "python3 -m unittest" in result.stderr
    payload = json.loads(result.stdout)
    assert payload["passed"] == 2
    assert payload["failed"] == 0
    assert payload["errors"] == 0
    assert payload["exit_code"] == 0
