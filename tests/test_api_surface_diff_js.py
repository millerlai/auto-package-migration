"""Smoke tests for package-upgrade/scripts/api_surface_diff_js.js.

The real diff requires `npm pack <pkg>@<ver>` (network access + tarball
extraction), which is too heavyweight for the default suite. The default
tests here only cover argv validation; opt in to the live diff with
RUN_API_SURFACE_DIFF=1 in CI or locally.

The schema-coverage portion of TODO task 3.1 for this helper is intentionally
deferred to TODO task 1.3 (confidence-score alignment), which will rewrite the
output shape and is the natural place to add the matching assertions.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


def _run(node_bin: str, scripts_dir: Path, *args: str) -> subprocess.CompletedProcess:
    script = scripts_dir / "api_surface_diff_js.js"
    return subprocess.run(
        [node_bin, str(script), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_usage_message_when_called_with_no_args(node_bin, scripts_dir, js_deps_installed):
    result = _run(node_bin, scripts_dir)
    assert result.returncode == 1
    assert "Usage" in result.stderr
    assert "api_surface_diff_js" in result.stderr


def test_usage_message_when_versions_missing(node_bin, scripts_dir, js_deps_installed):
    result = _run(node_bin, scripts_dir, "axios")
    assert result.returncode == 1
    assert "Usage" in result.stderr


@pytest.mark.skipif(
    not os.environ.get("RUN_API_SURFACE_DIFF"),
    reason="Live diff requires network (npm pack); set RUN_API_SURFACE_DIFF=1 to enable",
)
def test_live_diff_emits_expected_top_level_schema(node_bin, scripts_dir, js_deps_installed):
    """Live test against a stable micro-package with TS declarations."""
    # is-odd is tiny, has TS types, and its 3.0.x line is stable.
    result = _run(node_bin, scripts_dir, "is-odd", "3.0.0", "3.0.1")
    assert result.returncode == 0, result.stderr

    data = json.loads(result.stdout)
    expected_keys = {
        "package_name",
        "old_version",
        "new_version",
        "strategy",
        "removed",
        "added",
        "changed",
        "deprecated_new",
        "warnings",
        "errors",
    }
    assert expected_keys.issubset(data.keys())
    assert data["package_name"] == "is-odd"
    assert data["old_version"] == "3.0.0"
    assert data["new_version"] == "3.0.1"
    # strategy must be one of the documented values
    assert data["strategy"] in ("dts", "js", "mixed")
