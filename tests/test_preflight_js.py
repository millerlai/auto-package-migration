"""Tests for the registry Tier-1 native-auth detection in javascript/preflight.sh.

Capability-first token policy: when a private registry already has a real
(non-${VAR}-placeholder) credential configured natively (e.g. an _authToken in
.npmrc), preflight must NOT raise an `env_<VAR>_missing` blocker — the package
manager can authenticate without us collecting a token. When no native auth
exists, the blocker stays but its remediation must steer the user to
self-authenticate (`npm login`) before pasting a raw token (Tier-2 before
Tier-3).

These exercise the real preflight.sh end-to-end (it runs detect_env.sh itself),
so they need bash + jq. HOME is redirected to the fixture dir to keep the real
~/.npmrc from leaking into detection.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

# A .yarnrc.yml that points a scope at a private registry and references the
# JFROG_TOKEN env var for auth — this is what produces the env_var_placeholder
# and the custom_registries host that Tier-1 detection keys off of.
YARNRC = (
    "npmScopes:\n"
    "  myorg:\n"
    '    npmRegistryServer: "https://artifactory.example.com/"\n'
    '    npmAuthToken: "${JFROG_TOKEN}"\n'
)
REGISTRY_HOST = "artifactory.example.com"


@pytest.fixture(scope="session")
def jq_available() -> bool:
    if shutil.which("jq") is None:
        pytest.skip("jq not installed — preflight.sh needs it for JSON assembly")
    return True


def _run_preflight(bash_bin: str, scripts_dir: Path, project: Path) -> dict:
    script = scripts_dir / "javascript" / "preflight.sh"
    # Strip JFROG_TOKEN so the "env var set" path can't mask detection, and
    # pin HOME to the project so the developer's real ~/.npmrc is invisible.
    env = {k: v for k, v in os.environ.items() if k != "JFROG_TOKEN"}
    env["HOME"] = str(project)
    result = subprocess.run(
        [bash_bin, str(script), str(project), "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",  # script emits UTF-8 (em-dashes in remediation); avoid cp950 on Windows
        check=False,
        env=env,
    )
    # preflight exits 1 whenever ANY blocker exists (e.g. yarn not installed in
    # the test env -> pkg_manager_bin_missing). That's unrelated to the auth
    # checks under test, and the JSON is still emitted to stdout, so parse it
    # regardless of return code.
    assert result.stdout.strip(), f"preflight emitted no JSON; stderr: {result.stderr}"
    return json.loads(result.stdout)


def _make_project(project: Path) -> None:
    (project / "package.json").write_text('{"name":"x","version":"1.0.0"}')
    (project / ".yarnrc.yml").write_text(YARNRC)
    (project / "yarn.lock").write_text("# yarn lockfile\n")


def test_native_authtoken_downgrades_blocker(bash_bin, scripts_dir, jq_available, tmp_path: Path):
    """A literal _authToken in .npmrc => no env_*_missing blocker, registry_auth_native ok."""
    _make_project(tmp_path)
    (tmp_path / ".npmrc").write_text(f"//{REGISTRY_HOST}/:_authToken=realtoken123\n")

    out = _run_preflight(bash_bin, scripts_dir, tmp_path)

    blocker_ids = {b["id"] for b in out["blockers"]}
    ok_ids = {o["id"] for o in out["ok"]}
    assert "env_JFROG_TOKEN_missing" not in blocker_ids
    assert "registry_auth_native" in ok_ids


def test_placeholder_only_keeps_blocker_with_self_auth_hint(
    bash_bin, scripts_dir, jq_available, tmp_path: Path
):
    """No native credential => blocker stays, remediation leads with `npm login` (Tier-2)."""
    _make_project(tmp_path)  # no .npmrc literal token

    out = _run_preflight(bash_bin, scripts_dir, tmp_path)

    blockers = {b["id"]: b for b in out["blockers"]}
    assert "env_JFROG_TOKEN_missing" in blockers
    remediation = blockers["env_JFROG_TOKEN_missing"]["remediation"]
    assert "npm login" in remediation
    # Tier-2 must be presented before Tier-3 (raw token as last resort).
    assert remediation.index("Authenticate yourself") < remediation.index("Last resort")


def test_placeholder_token_in_npmrc_is_not_native(
    bash_bin, scripts_dir, jq_available, tmp_path: Path
):
    """A ${VAR} placeholder in .npmrc must NOT count as native auth."""
    _make_project(tmp_path)
    (tmp_path / ".npmrc").write_text(f"//{REGISTRY_HOST}/:_authToken=${{JFROG_TOKEN}}\n")

    out = _run_preflight(bash_bin, scripts_dir, tmp_path)

    blocker_ids = {b["id"] for b in out["blockers"]}
    ok_ids = {o["id"] for o in out["ok"]}
    assert "env_JFROG_TOKEN_missing" in blocker_ids
    assert "registry_auth_native" not in ok_ids
