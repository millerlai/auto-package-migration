#!/usr/bin/env python3
"""
jira_transition.py — List or apply a Jira issue status transition via REST
API as fallback when Atlassian MCP is unavailable or unauthorized.

Usage:
    # List available transitions for an issue:
    ATLASSIAN_EMAIL=... ATLASSIAN_API_TOKEN=... \
        python jira_transition.py list <site_host> <issue_key>

    # Apply a transition (with optional resolution):
    ATLASSIAN_EMAIL=... ATLASSIAN_API_TOKEN=... \
        python jira_transition.py apply <site_host> <issue_key> <transition_id> [resolution_name]

Output: JSON to stdout. Errors go to stderr; exit code 0 on success.
"""

from __future__ import annotations

import json
import os
import sys

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests", file=sys.stderr)
    sys.exit(2)


def _auth() -> tuple[str, str]:
    email = os.environ.get("ATLASSIAN_EMAIL")
    token = os.environ.get("ATLASSIAN_API_TOKEN")
    if not email or not token:
        print("ERROR: ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN must be set", file=sys.stderr)
        sys.exit(2)
    return email, token


def _check(resp: requests.Response, key: str) -> None:
    if resp.status_code == 401:
        raise RuntimeError("401 Unauthorized — check ATLASSIAN_EMAIL/ATLASSIAN_API_TOKEN")
    if resp.status_code == 403:
        raise RuntimeError(f"403 Forbidden — your account cannot transition {key}")
    if resp.status_code == 404:
        raise RuntimeError(f"404 Not Found — issue {key} or transition does not exist")
    resp.raise_for_status()


def list_transitions(site: str, key: str) -> dict:
    email, token = _auth()
    url = f"https://{site}/rest/api/3/issue/{key}/transitions"
    resp = requests.get(url, auth=(email, token), timeout=30)
    _check(resp, key)
    data = resp.json()
    transitions = []
    for t in data.get("transitions", []) or []:
        transitions.append(
            {
                "id": t.get("id"),
                "name": t.get("name"),
                "to_status": (t.get("to") or {}).get("name"),
                "to_category": ((t.get("to") or {}).get("statusCategory") or {}).get("key"),
                "has_screen": t.get("hasScreen", False),
            }
        )
    return {"issue": key, "transitions": transitions}


def apply_transition(site: str, key: str, transition_id: str, resolution: str | None) -> dict:
    email, token = _auth()
    url = f"https://{site}/rest/api/3/issue/{key}/transitions"
    payload: dict = {"transition": {"id": transition_id}}
    if resolution:
        payload["fields"] = {"resolution": {"name": resolution}}

    resp = requests.post(
        url,
        json=payload,
        auth=(email, token),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        timeout=30,
    )
    if resp.status_code == 400:
        # Likely a workflow validation error; surface the body so the caller
        # can show the user which field the workflow is rejecting.
        try:
            body = resp.json()
        except ValueError:
            body = {"raw": resp.text}
        raise RuntimeError(
            f"400 Bad Request — workflow rejected the transition: {json.dumps(body, ensure_ascii=False)}"
        )
    _check(resp, key)
    # transition endpoint returns 204 No Content on success
    return {
        "issue": key,
        "transition_id": transition_id,
        "resolution": resolution,
        "status": "applied",
    }


def main() -> int:
    if len(sys.argv) < 4:
        print("Usage:", file=sys.stderr)
        print(f"  {sys.argv[0]} list <site_host> <issue_key>", file=sys.stderr)
        print(
            f"  {sys.argv[0]} apply <site_host> <issue_key> <transition_id> [resolution_name]",
            file=sys.stderr,
        )
        return 2

    cmd = sys.argv[1]
    try:
        if cmd == "list":
            if len(sys.argv) != 4:
                print(f"Usage: {sys.argv[0]} list <site_host> <issue_key>", file=sys.stderr)
                return 2
            result = list_transitions(sys.argv[2], sys.argv[3])
        elif cmd == "apply":
            if len(sys.argv) not in (5, 6):
                print(
                    f"Usage: {sys.argv[0]} apply <site_host> <issue_key> <transition_id> [resolution_name]",
                    file=sys.stderr,
                )
                return 2
            resolution = sys.argv[5] if len(sys.argv) == 6 else None
            result = apply_transition(sys.argv[2], sys.argv[3], sys.argv[4], resolution)
        else:
            print(f"ERROR: unknown command '{cmd}' (expected 'list' or 'apply')", file=sys.stderr)
            return 2
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except requests.RequestException as e:
        print(f"ERROR: network failure — {e}", file=sys.stderr)
        return 1

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
