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


def _run_preflight(
    bash_bin: str, scripts_dir: Path, project: Path, home: Path | None = None
) -> dict:
    script = scripts_dir / "javascript" / "preflight.sh"
    # Strip JFROG_TOKEN so the "env var set" path can't mask detection, and
    # pin HOME to the project (or a caller-supplied dir) so the developer's
    # real ~/.npmrc is invisible.
    env = {k: v for k, v in os.environ.items() if k != "JFROG_TOKEN"}
    env["HOME"] = str(home if home is not None else project)
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


# --- T9: npm resolution order and yarn berry npmRegistries fallback ---

# This scope registers a path-specific registry so the npm resolution walk has
# more than one level to climb ("//host/api/npm/virtual/" up to "//host/").
YARNRC_SPECIFIC_PATH = (
    "npmScopes:\n"
    "  myorg:\n"
    f'    npmRegistryServer: "https://{REGISTRY_HOST}/api/npm/virtual/"\n'
    '    npmAuthToken: "${JFROG_TOKEN}"\n'
)


def test_npm_specific_path_placeholder_wins_over_home_host_literal(
    bash_bin, scripts_dir, jq_available, tmp_path: Path
):
    """npm resolution is most-specific-first: a project entry for the exact
    registry path decides even when a less-specific home entry has a real
    token — the placeholder at the specific path must never be shadowed."""
    _make_project(tmp_path)
    (tmp_path / ".yarnrc.yml").write_text(YARNRC_SPECIFIC_PATH)
    (tmp_path / ".npmrc").write_text(
        f"//{REGISTRY_HOST}/api/npm/virtual/:_authToken=${{JFROG_TOKEN}}\n"
    )
    # HOME == the project dir would make home's ~/.npmrc the SAME file as the
    # project's .npmrc here, so use a separate home dir to keep them apart.
    home = tmp_path / "home"
    home.mkdir()
    (home / ".npmrc").write_text(f"//{REGISTRY_HOST}/:_authToken=home-literal-token\n")

    out = _run_preflight(bash_bin, scripts_dir, tmp_path, home=home)

    blocker_ids = {b["id"] for b in out["blockers"]}
    ok_ids = {o["id"] for o in out["ok"]}
    assert "env_JFROG_TOKEN_missing" in blocker_ids
    assert "registry_auth_native" not in ok_ids


YARN_NPM_REGISTRIES = (
    "npmRegistries:\n"
    f'  "https://{REGISTRY_HOST}/api/npm/virtual/":\n'
    '    npmAuthToken: "real-yarn-token"\n'
)

YARN_NPM_REGISTRIES_OTHER_HOST = (
    "npmRegistries:\n"
    '  "https://other-registry.example.com/":\n'
    '    npmAuthToken: "real-yarn-token"\n'
)


def test_yarn_home_npmregistries_entry_is_native(
    bash_bin, scripts_dir, jq_available, tmp_path: Path
):
    """A literal npmAuthToken under home ~/.yarnrc.yml's npmRegistries for the
    matching host counts as native (yarn config get fallback path, since no
    real yarn binary runs in this test)."""
    _make_project(tmp_path)
    (tmp_path / ".yarnrc.yml").write_text(YARNRC_SPECIFIC_PATH)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".yarnrc.yml").write_text(YARN_NPM_REGISTRIES)

    out = _run_preflight(bash_bin, scripts_dir, tmp_path, home=home)

    blocker_ids = {b["id"] for b in out["blockers"]}
    ok_ids = {o["id"] for o in out["ok"]}
    assert "env_JFROG_TOKEN_missing" not in blocker_ids
    assert "registry_auth_native" in ok_ids


def test_yarn_home_npmregistries_entry_for_other_host_is_not_native(
    bash_bin, scripts_dir, jq_available, tmp_path: Path
):
    """The same shape of entry, but for a different host, must not satisfy
    this registry's auth requirement."""
    _make_project(tmp_path)
    (tmp_path / ".yarnrc.yml").write_text(YARNRC_SPECIFIC_PATH)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".yarnrc.yml").write_text(YARN_NPM_REGISTRIES_OTHER_HOST)

    out = _run_preflight(bash_bin, scripts_dir, tmp_path, home=home)

    blocker_ids = {b["id"] for b in out["blockers"]}
    ok_ids = {o["id"] for o in out["ok"]}
    assert "env_JFROG_TOKEN_missing" in blocker_ids
    assert "registry_auth_native" not in ok_ids


def test_yarn_home_npmregistries_entry_for_host_collision_is_not_native(
    bash_bin, scripts_dir, jq_available, tmp_path: Path
):
    """A different registry whose host merely CONTAINS this host as a
    substring (e.g. a regional subdomain, "eu.artifactory.example.com" vs
    "artifactory.example.com") must not satisfy this registry's auth
    requirement — the match must be on the exact host, not `contains`."""
    _make_project(tmp_path)
    (tmp_path / ".yarnrc.yml").write_text(YARNRC_SPECIFIC_PATH)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".yarnrc.yml").write_text(
        "npmRegistries:\n"
        f'  "https://eu.{REGISTRY_HOST}/api/npm/virtual/":\n'
        '    npmAuthToken: "real-yarn-token"\n'
    )

    out = _run_preflight(bash_bin, scripts_dir, tmp_path, home=home)

    blocker_ids = {b["id"] for b in out["blockers"]}
    ok_ids = {o["id"] for o in out["ok"]}
    assert "env_JFROG_TOKEN_missing" in blocker_ids
    assert "registry_auth_native" not in ok_ids


def test_npm_placeholder_decision_still_lets_yarn_native_auth_apply(
    bash_bin, scripts_dir, jq_available, tmp_path: Path
):
    """npm's own resolution deciding 'not native' (a ${VAR} placeholder in
    .npmrc) must not short-circuit before yarn's own merged config is tried —
    yarn (the package manager actually in use) may already have a working
    credential for the same registry via $HOME/.yarnrc.yml's npmRegistries."""
    _make_project(tmp_path)
    (tmp_path / ".yarnrc.yml").write_text(YARNRC_SPECIFIC_PATH)
    (tmp_path / ".npmrc").write_text(
        f"//{REGISTRY_HOST}/api/npm/virtual/:_authToken=${{JFROG_TOKEN}}\n"
    )
    home = tmp_path / "home"
    home.mkdir()
    (home / ".yarnrc.yml").write_text(YARN_NPM_REGISTRIES)

    out = _run_preflight(bash_bin, scripts_dir, tmp_path, home=home)

    blocker_ids = {b["id"] for b in out["blockers"]}
    ok_ids = {o["id"] for o in out["ok"]}
    assert "env_JFROG_TOKEN_missing" not in blocker_ids
    assert "registry_auth_native" in ok_ids


def test_yarn_home_default_registry_npmauthtoken_is_native(
    bash_bin, scripts_dir, jq_available, tmp_path: Path
):
    """A literal top-level npmAuthToken for the DEFAULT registry (no
    npmRegistries entry at all) counts as native, per issue-68.md:377 ("plus
    npmAuthToken for the default registry")."""
    _make_project(tmp_path)  # YARNRC points myorg's scope at REGISTRY_HOST root
    home = tmp_path / "home"
    home.mkdir()
    (home / ".yarnrc.yml").write_text(
        f'npmRegistryServer: "https://{REGISTRY_HOST}/"\n' 'npmAuthToken: "real-default-token"\n'
    )

    out = _run_preflight(bash_bin, scripts_dir, tmp_path, home=home)

    blocker_ids = {b["id"] for b in out["blockers"]}
    ok_ids = {o["id"] for o in out["ok"]}
    assert "env_JFROG_TOKEN_missing" not in blocker_ids
    assert "registry_auth_native" in ok_ids


def test_corepack_yarn_shim_never_executed_for_native_auth_check(
    bash_bin, scripts_dir, jq_available, tmp_path: Path
):
    """A corepack-managed `.yarn/releases/*.cjs` shim is project-supplied
    code — detect_env.sh itself never executes it, deriving the version from
    the filename instead. The native-auth check must not execute it either:
    a hostile repo could ship a trojanized shim that runs the moment
    preflight asks "is a token already configured", before the user has
    approved anything."""
    _make_project(tmp_path)
    yarn_dir = tmp_path / ".yarn" / "releases"
    yarn_dir.mkdir(parents=True)
    (yarn_dir / "yarn-3.8.2.cjs").write_text("// pretend yarn release\n")

    # Record every invocation's arguments (detect_env.sh harmlessly runs
    # `node --version` regardless of this bug, so the assertion below must
    # check WHICH invocation happened, not merely whether node ran at all).
    invocations = tmp_path / "node_invocations.log"
    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    fake_node = fake_bin / "node"
    fake_node.write_text(f'#!/usr/bin/env bash\necho "$@" >> "{invocations}"\nexit 0\n')
    fake_node.chmod(0o755)

    script = scripts_dir / "javascript" / "preflight.sh"
    env = {k: v for k, v in os.environ.items() if k != "JFROG_TOKEN"}
    env["HOME"] = str(tmp_path)
    env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        [bash_bin, str(script), str(tmp_path), "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=env,
    )
    assert result.stdout.strip(), f"preflight emitted no JSON; stderr: {result.stderr}"
    logged = invocations.read_text() if invocations.exists() else ""
    assert "yarn-3.8.2.cjs" not in logged, (
        "preflight executed the project-supplied corepack yarn shim "
        f"(.yarn/releases/yarn-3.8.2.cjs via node) during native-auth "
        f"detection; it must only be read as text or skipped. Invocations:\n{logged}"
    )
