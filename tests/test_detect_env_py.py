"""Tests for package-upgrade/scripts/detect_env.sh (Python).

The first batch of tests for this script — guards the schema task 1.1 added
(pkg_manager_bin / custom_registries / env_var_placeholders / memory_hints).

TODO task 3.3 — first item.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REQUIRED_TOP_LEVEL_KEYS = {
    "language",
    "pkg_manager",
    "pkg_manager_bin",
    "pkg_manager_version",
    "python_version",
    "lockfile_path",
    "pip_lock_file",
    "has_pip_tools",
    "dependency_files",
    "env_var_placeholders",
    "custom_registries",
    "py_config_files",
    "git_remote_host",
    "git_remote_url",
    "memory_hints",
}


def _run(bash_bin: str, scripts_dir: Path, project: Path) -> dict:
    script = scripts_dir / "detect_env.sh"
    result = subprocess.run(
        [bash_bin, str(script), str(project)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, f"detect_env.sh failed: {result.stderr}"
    return json.loads(result.stdout)


def test_poetry_project_detected(bash_bin, scripts_dir, tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "x"\nversion = "0.1.0"\n'
        '[tool.poetry.dependencies]\npython = "^3.11"\n'
    )
    (tmp_path / "poetry.lock").write_text("# poetry lock\n")

    out = _run(bash_bin, scripts_dir, tmp_path)

    assert REQUIRED_TOP_LEVEL_KEYS.issubset(out.keys())
    assert out["language"] == "python"
    assert out["pkg_manager"] == "poetry"
    assert out["lockfile_path"] == "poetry.lock"


def test_uv_project_detected(bash_bin, scripts_dir, tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0.1.0"\n[tool.uv]\n'
    )
    (tmp_path / "uv.lock").write_text("# uv lock\n")

    out = _run(bash_bin, scripts_dir, tmp_path)

    assert out["pkg_manager"] == "uv"
    assert out["lockfile_path"] == "uv.lock"


def test_pip_with_requirements_in_marks_pip_tools(bash_bin, scripts_dir, tmp_path: Path):
    (tmp_path / "requirements.in").write_text("requests>=2.31\n")
    (tmp_path / "requirements.txt").write_text("requests==2.31.0\n")

    out = _run(bash_bin, scripts_dir, tmp_path)

    assert out["pkg_manager"] == "pip"
    assert out["has_pip_tools"] is True


def test_poetry_source_extracted_as_custom_registry(bash_bin, scripts_dir, tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "x"\n\n'
        "[[tool.poetry.source]]\n"
        'name = "private"\n'
        'url = "https://${JFROG_TOKEN}@artifactory.example.com/api/pypi/private/simple"\n'
    )

    out = _run(bash_bin, scripts_dir, tmp_path)

    assert "JFROG_TOKEN" in out["env_var_placeholders"]
    regs = out["custom_registries"]
    assert any(r["auth_env_var"] == "JFROG_TOKEN" for r in regs)
    assert "private_registry" in out["memory_hints"]
    assert "poetry_source" in out["memory_hints"]


def test_pip_conf_extra_index_url_extracted(bash_bin, scripts_dir, tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("requests==2.31.0\n")
    (tmp_path / "pip.conf").write_text(
        "[global]\n"
        "index-url = https://pypi.example.com/simple\n"
        "extra-index-url = https://${PIP_TOKEN}@private.pypi.com/simple\n"
    )

    out = _run(bash_bin, scripts_dir, tmp_path)

    assert "PIP_TOKEN" in out["env_var_placeholders"]
    assert "pip_extra_index" in out["memory_hints"]


def test_pkg_manager_bin_is_absolute_when_resolved(bash_bin, scripts_dir, tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "x"\n' '[tool.poetry.dependencies]\npython = "^3.11"\n'
    )
    (tmp_path / "poetry.lock").write_text("")

    out = _run(bash_bin, scripts_dir, tmp_path)

    # pkg_manager_bin should either be empty (poetry not installed) or
    # an absolute path. The point is to not be a bare name like "poetry".
    bin_ = out["pkg_manager_bin"]
    assert bin_ == "" or "/" in bin_ or "\\" in bin_


def test_non_default_remote_in_memory_hints(bash_bin, scripts_dir, tmp_path: Path):
    """Initialize a fake git remote pointing to an internal GHE host."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    # Init a bare repo so `git remote get-url` works without network
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "remote",
            "add",
            "origin",
            "git@ghe.internal.corp:team/repo.git",
        ],
        cwd=tmp_path,
        check=True,
    )

    out = _run(bash_bin, scripts_dir, tmp_path)

    assert out["git_remote_host"] == "ghe.internal.corp"
    assert "non_default_remote" in out["memory_hints"]
