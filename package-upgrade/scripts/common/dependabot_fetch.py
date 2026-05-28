#!/usr/bin/env python3
"""dependabot_fetch.py — Fetch + group GitHub Dependabot security alerts for batch upgrade.

The CLI contract and output JSON schema below are the contract SKILL.md Phase 1 情況 D
relies on; the matching design/workflow lives in
``references/common/dependabot_workflow.md``. Keep this docstring, the argparse CLI, the
``OUTPUT_SCHEMA`` constant, and that reference doc in sync.

Usage:
    python dependabot_fetch.py <host> <owner> <repo> \\
        [--state open] [--alert-number N] [--ecosystem pip,npm,go]

Example:
    python dependabot_fetch.py github.com millerlai auto-package-migration --state open

Auth (preferred → fallback):
    1. ``gh api`` — reuses the GitHub CLI's auth (incl. enterprise hosts via
       ``--hostname``). Phase 0.3 preflight already validates ``gh auth status``.
    2. ``GITHUB_TOKEN`` env + ``requests`` — fallback when ``gh`` is absent. The token
       needs the ``security_events`` scope (or ``repo`` on private repos).

Output: a single JSON object to stdout (schema = OUTPUT_SCHEMA below). Errors go to
        stderr. Exit codes: 0 ok, 1 runtime/network failure, 2 usage error.

Cross-platform: pure Python 3.8 + ``subprocess`` only — no bash-isms — so it behaves
identically on Linux, macOS, Windows (native) and Cygwin64.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# --- ecosystem → skill language ------------------------------------------------------
# The skill drives Python / JS / Go only. Other GitHub ecosystems (maven, nuget,
# rubygems, composer, rust, actions, ...) are surfaced under `unsupported_ecosystems`
# and excluded from the upgrade plan.
ECOSYSTEM_TO_LANGUAGE: Dict[str, str] = {
    "pip": "python",
    "npm": "javascript",
    "go": "go",
}
SUPPORTED_ECOSYSTEMS = frozenset(ECOSYSTEM_TO_LANGUAGE)

# Severity precedence for collapsing a package's alerts into one `max_severity`.
SEVERITY_RANK: Dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}

# --- frozen output schema (documentation only) ---------------------------------------
# normalize_and_group() must emit exactly this shape. Mirror any change here into
# references/common/dependabot_workflow.md and the SKILL.md 情況 D section.
OUTPUT_SCHEMA: Dict[str, Any] = {
    "source": {
        "host": "str",  # github.com or enterprise GHE host
        "owner": "str",
        "repo": "str",
        "alerts_url": "str",  # https://{host}/{owner}/{repo}/security/dependabot
        "fetched_at": "str (ISO-8601 UTC)",
    },
    "alert_count": "int",  # alerts considered (after the optional --ecosystem allow-list)
    "unsupported_ecosystems": ["str"],  # ecosystems present but not py/js/go
    "groups": [
        {
            "group_id": "str",  # f'{language}:{manifest_path}'
            "language": "str",  # python | javascript | go
            "ecosystem": "str",  # pip | npm | go
            "manifest_path": "str",  # e.g. requirements.txt, package.json, go.mod
            "packages": [
                {
                    "name": "str",
                    "target_version": "str|None",  # MAX(first_patched) over this pkg's alerts
                    "patched_available": "bool",  # False → cannot auto-fix
                    "is_major_jump_hint": "bool",  # best-effort; Phase 2 confirms authoritatively
                    "max_severity": "str",  # critical|high|medium|low
                    "alerts": [
                        {
                            "number": "int",
                            "ghsa_id": "str",
                            "cve_id": "str|None",
                            "severity": "str",
                            "vulnerable_range": "str",
                            "first_patched": "str|None",
                            "summary": "str",
                            "html_url": "str",
                        }
                    ],
                }
            ],
        }
    ],
}


def build_alerts_url(host: str, owner: str, repo: str) -> str:
    """The human-facing alerts page URL (echoed back into report / PR trailers)."""
    return f"https://{host}/{owner}/{repo}/security/dependabot"


# --- fetch ---------------------------------------------------------------------------


def _fetch_via_gh(
    host: str, owner: str, repo: str, state: str, alert_number: Optional[int]
) -> List[Dict[str, Any]]:
    """Fetch alerts through the ``gh`` CLI (auth, GHE, pagination handled by gh)."""
    cmd = [
        "gh",
        "api",
        "-H",
        "Accept: application/vnd.github+json",
        "-H",
        "X-GitHub-Api-Version: 2022-11-28",
    ]
    if host and host != "github.com":
        cmd += ["--hostname", host]

    if alert_number is not None:
        path = f"repos/{owner}/{repo}/dependabot/alerts/{alert_number}"
    else:
        cmd.append("--paginate")  # gh merges array pages into one JSON array
        path = f"repos/{owner}/{repo}/dependabot/alerts?state={state}&per_page=100"
    cmd.append(path)

    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"gh api failed (exit {proc.returncode}): {proc.stderr.strip()}")
    try:
        data = json.loads(proc.stdout or "null")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"could not parse gh api output as JSON: {e}") from e

    if data is None:
        return []
    if isinstance(data, dict):  # single-alert endpoint
        return [data]
    return list(data)


def _fetch_via_requests(
    host: str, owner: str, repo: str, state: str, alert_number: Optional[int]
) -> List[Dict[str, Any]]:
    """Fallback fetch using ``GITHUB_TOKEN`` + ``requests`` when ``gh`` is unavailable."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError(
            "neither gh CLI nor GITHUB_TOKEN available — run `gh auth login` "
            "or set GITHUB_TOKEN (needs the 'security_events' scope)"
        )
    try:
        import requests  # type: ignore[import-untyped]
    except ImportError as e:
        raise RuntimeError(
            "requests not installed (needed for the GITHUB_TOKEN fallback); pip install requests"
        ) from e

    base = "https://api.github.com" if host == "github.com" else f"https://{host}/api/v3"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    def _check(resp: "requests.Response") -> None:
        if resp.status_code == 401:
            raise RuntimeError("401 Unauthorized — check GITHUB_TOKEN")
        if resp.status_code == 403:
            raise RuntimeError("403 Forbidden — token likely missing the 'security_events' scope")
        if resp.status_code == 404:
            raise RuntimeError(
                f"404 Not Found — {owner}/{repo} missing, Dependabot disabled, or no access"
            )
        if not resp.ok:
            raise RuntimeError(f"{resp.status_code} from GitHub API: {resp.text[:200]}")

    try:
        if alert_number is not None:
            url: Optional[str] = f"{base}/repos/{owner}/{repo}/dependabot/alerts/{alert_number}"
            resp = requests.get(url, headers=headers, timeout=30)
            _check(resp)
            return [resp.json()]

        url = f"{base}/repos/{owner}/{repo}/dependabot/alerts"
        params: Optional[Dict[str, str]] = {"state": state, "per_page": "100"}
        alerts: List[Dict[str, Any]] = []
        while url:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            _check(resp)
            alerts.extend(resp.json())
            next_link = resp.links.get("next")
            url = next_link["url"] if next_link else None
            params = None  # the `next` URL already carries the query string
        return alerts
    except requests.RequestException as e:
        raise RuntimeError(f"network failure talking to GitHub API: {e}") from e


def fetch_alerts(
    host: str,
    owner: str,
    repo: str,
    state: str = "open",
    alert_number: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return the raw Dependabot alert objects (``gh`` preferred, ``requests`` fallback)."""
    if shutil.which("gh"):
        return _fetch_via_gh(host, owner, repo, state, alert_number)
    return _fetch_via_requests(host, owner, repo, state, alert_number)


# --- grouping ------------------------------------------------------------------------


def _version_sort_key(version: str) -> Tuple[Tuple[int, ...], int]:
    """Tolerant version key for picking the MAX patched version within one ecosystem.

    Handles a leading ``v`` (Go) and ``X.Y.Z`` semver; prereleases (``-rc1`` / ``+meta``)
    sort below the matching release. Good enough to choose the highest real release
    among a package's patched versions — exact range solving stays in Phase 2.
    """
    cleaned = version.strip().lstrip("vV")
    release = re.split(r"[-+]", cleaned, maxsplit=1)[0]
    components: List[int] = []
    for token in release.split("."):
        match = re.match(r"\d+", token)
        components.append(int(match.group(0)) if match else 0)
    has_prerelease = bool(re.search(r"[-+]", cleaned))
    return (tuple(components), 0 if has_prerelease else 1)


def _max_version(versions: List[str]) -> Optional[str]:
    candidates = [v for v in versions if v]
    if not candidates:
        return None
    return max(candidates, key=_version_sort_key)


def _max_severity(severities: List[str]) -> str:
    ranked = [s for s in severities if s]
    if not ranked:
        return "unknown"
    return max(ranked, key=lambda s: SEVERITY_RANK.get(s.lower(), -1))


def _alert_entry(alert: Dict[str, Any]) -> Dict[str, Any]:
    advisory = alert.get("security_advisory") or {}
    vuln = alert.get("security_vulnerability") or {}
    first_patched = (vuln.get("first_patched_version") or {}).get("identifier")
    severity = (vuln.get("severity") or advisory.get("severity") or "").lower()
    return {
        "number": alert.get("number"),
        "ghsa_id": advisory.get("ghsa_id"),
        "cve_id": advisory.get("cve_id"),
        "severity": severity,
        "vulnerable_range": vuln.get("vulnerable_version_range") or "",
        "first_patched": first_patched,
        "summary": advisory.get("summary") or "",
        "html_url": alert.get("html_url") or "",
    }


def normalize_and_group(
    raw_alerts: List[Dict[str, Any]],
    host: str,
    owner: str,
    repo: str,
    ecosystem_filter: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Collapse raw alerts into the frozen OUTPUT_SCHEMA shape (deterministic)."""
    groups_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
    unsupported: set = set()
    considered = 0

    for alert in raw_alerts:
        dep = alert.get("dependency") or {}
        pkg = dep.get("package") or {}
        ecosystem = (pkg.get("ecosystem") or "").lower()
        name = pkg.get("name") or ""
        manifest = dep.get("manifest_path") or ""

        if ecosystem_filter and ecosystem not in ecosystem_filter:
            continue
        considered += 1

        language = ECOSYSTEM_TO_LANGUAGE.get(ecosystem)
        if language is None:
            unsupported.add(ecosystem)
            continue

        key = (language, manifest)
        group = groups_map.setdefault(
            key,
            {
                "language": language,
                "ecosystem": ecosystem,
                "manifest_path": manifest,
                "packages": {},
            },
        )
        group["packages"].setdefault(name, []).append(_alert_entry(alert))

    groups: List[Dict[str, Any]] = []
    for (language, manifest), group in sorted(groups_map.items()):
        packages: List[Dict[str, Any]] = []
        for name, alerts in sorted(group["packages"].items()):
            target = _max_version([a["first_patched"] for a in alerts])
            packages.append(
                {
                    "name": name,
                    "target_version": target,
                    "patched_available": target is not None,
                    # The alert payload carries no installed version, so a real
                    # major-jump check is impossible here — Phase 2's dep_tree is
                    # authoritative. Kept in the schema as a deferred hint.
                    "is_major_jump_hint": False,
                    "max_severity": _max_severity([a["severity"] for a in alerts]),
                    "alerts": alerts,
                }
            )
        groups.append(
            {
                "group_id": f"{language}:{manifest}",
                "language": language,
                "ecosystem": group["ecosystem"],
                "manifest_path": manifest,
                "packages": packages,
            }
        )

    return {
        "source": {
            "host": host,
            "owner": owner,
            "repo": repo,
            "alerts_url": build_alerts_url(host, owner, repo),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
        "alert_count": considered,
        "unsupported_ecosystems": sorted(unsupported),
        "groups": groups,
    }


# --- CLI -----------------------------------------------------------------------------


def parse_ecosystems(value: Optional[str]) -> Optional[List[str]]:
    """``--ecosystem pip,npm`` → ``['pip', 'npm']``; None when unset."""
    if not value:
        return None
    return [e.strip() for e in value.split(",") if e.strip()]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dependabot_fetch.py",
        description="Fetch + group GitHub Dependabot security alerts for batch upgrade.",
    )
    parser.add_argument("host", help="github.com or an enterprise GHE host")
    parser.add_argument("owner", help="repository owner / org")
    parser.add_argument("repo", help="repository name")
    parser.add_argument(
        "--state",
        default="open",
        choices=["open", "dismissed", "fixed", "auto_dismissed"],
        help="alert state filter (default: open)",
    )
    parser.add_argument(
        "--alert-number",
        type=int,
        default=None,
        help="fetch a single alert by number (batch-of-one)",
    )
    parser.add_argument(
        "--ecosystem",
        default=None,
        help="comma-separated ecosystem allow-list, e.g. pip,npm,go",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    ecosystem_filter = parse_ecosystems(args.ecosystem)

    try:
        raw = fetch_alerts(args.host, args.owner, args.repo, args.state, args.alert_number)
        result = normalize_and_group(raw, args.host, args.owner, args.repo, ecosystem_filter)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
