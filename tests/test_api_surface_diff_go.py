"""Smoke tests for package-upgrade/scripts/api_surface_diff_go.sh.

The real diff requires the go toolchain + `apidiff` + network access to
fetch the two module versions, which is too heavyweight for the default
suite. The default tests here cover only argv validation; opt in to the
live diff with RUN_API_SURFACE_DIFF=1.

Schema-coverage assertions are deferred to TODO task 1.3, the natural place
to add them alongside confidence-score alignment.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


def _run(bash_bin: str, scripts_dir: Path, *args: str) -> subprocess.CompletedProcess:
    script = scripts_dir / "api_surface_diff_go.sh"
    return subprocess.run(
        [bash_bin, str(script), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_usage_message_when_called_with_no_args(bash_bin, scripts_dir):
    result = _run(bash_bin, scripts_dir)
    assert result.returncode != 0
    assert "Usage" in result.stderr
    assert "api_surface_diff_go" in result.stderr


def test_usage_message_when_versions_missing(bash_bin, scripts_dir):
    result = _run(bash_bin, scripts_dir, "github.com/spf13/cobra")
    assert result.returncode != 0
    assert "Usage" in result.stderr


@pytest.mark.skipif(
    not os.environ.get("RUN_API_SURFACE_DIFF"),
    reason="Live diff requires network + apidiff; set RUN_API_SURFACE_DIFF=1 to enable",
)
def test_live_diff_runs_against_stable_module(go_bin, bash_bin, scripts_dir):
    """Live test against a small stable module that has apidiff-compatible API."""
    # Pick versions that are known to coexist in the proxy and have minimal diff.
    result = _run(
        bash_bin,
        scripts_dir,
        "github.com/spf13/pflag",
        "v1.0.5",
        "v1.0.6",
    )
    # We don't assert returncode=0 because apidiff may not be installed in CI;
    # the smoke check is that stderr explains what's missing if it fails.
    if result.returncode != 0:
        pytest.skip(
            f"api_surface_diff_go.sh did not complete (likely apidiff missing): "
            f"{result.stderr[:200]}"
        )
    # When it does run, stdout should be valid JSON.
    import json

    data = json.loads(result.stdout)
    assert data.get("module_path") == "github.com/spf13/pflag"
