#!/usr/bin/env python3
"""
jira_fetch.py — Fetch Jira issue via REST API as fallback when Atlassian MCP
is unavailable or unauthorized.

Usage:
    ATLASSIAN_EMAIL=you@example.com ATLASSIAN_API_TOKEN=xxx \
        python jira_fetch.py <site_host> <issue_key>

Example:
    python jira_fetch.py trendmicro.atlassian.net V1E-148968

Output: JSON to stdout with summary, description, status, labels, comments.
        Errors go to stderr; exit code 0 on success, non-zero otherwise.

Auth: HTTP Basic with email + API token. Get a token at
      https://id.atlassian.com/manage-profile/security/api-tokens
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests", file=sys.stderr)
    sys.exit(2)


def fetch_issue(site: str, key: str, email: str, token: str) -> dict[str, Any]:
    url = f"https://{site}/rest/api/3/issue/{key}"
    params = {
        "fields": "summary,description,status,labels,comment,issuetype,priority",
        "expand": "renderedFields",
    }
    resp = requests.get(url, params=params, auth=(email, token), timeout=30)
    if resp.status_code == 401:
        raise RuntimeError("401 Unauthorized — check ATLASSIAN_EMAIL/ATLASSIAN_API_TOKEN")
    if resp.status_code == 403:
        raise RuntimeError(f"403 Forbidden — your account cannot view {key}")
    if resp.status_code == 404:
        raise RuntimeError(f"404 Not Found — issue {key} does not exist on {site}")
    resp.raise_for_status()
    return resp.json()


def adf_to_text(node: Any) -> str:
    """Best-effort flatten of Atlassian Document Format JSON to plain text.
    Not a full ADF renderer — just enough so the LLM can read the description."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_to_text(n) for n in node)
    if not isinstance(node, dict):
        return ""
    t = node.get("type")
    if t == "text":
        return node.get("text", "")
    if t == "hardBreak":
        return "\n"
    children = adf_to_text(node.get("content", []))
    if t in ("paragraph", "heading", "listItem", "blockquote", "codeBlock"):
        return children + "\n"
    if t in ("bulletList", "orderedList"):
        return children
    return children


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    fields = raw.get("fields", {}) or {}
    rendered = raw.get("renderedFields", {}) or {}

    desc_raw = fields.get("description")
    if isinstance(desc_raw, dict):
        description = adf_to_text(desc_raw).strip()
    elif isinstance(desc_raw, str):
        description = desc_raw
    else:
        description = rendered.get("description", "") or ""

    comments_raw = (fields.get("comment") or {}).get("comments", []) or []
    comments = []
    for c in comments_raw:
        body = c.get("body")
        if isinstance(body, dict):
            body_text = adf_to_text(body).strip()
        else:
            body_text = body or ""
        author = (c.get("author") or {}).get("displayName", "unknown")
        comments.append(
            {
                "author": author,
                "created": c.get("created", ""),
                "body": body_text,
            }
        )

    return {
        "key": raw.get("key"),
        "url": (
            f"https://{raw.get('self', '').split('/rest/')[0].split('://')[-1]}/browse/{raw.get('key')}"
            if raw.get("self")
            else None
        ),
        "summary": fields.get("summary", ""),
        "status": (fields.get("status") or {}).get("name", ""),
        "issue_type": (fields.get("issuetype") or {}).get("name", ""),
        "priority": (fields.get("priority") or {}).get("name", ""),
        "labels": fields.get("labels", []) or [],
        "description": description,
        "comments": comments,
    }


def main() -> int:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <site_host> <issue_key>", file=sys.stderr)
        print("Example: jira_fetch.py trendmicro.atlassian.net V1E-148968", file=sys.stderr)
        return 2

    site, key = sys.argv[1], sys.argv[2]
    email = os.environ.get("ATLASSIAN_EMAIL")
    token = os.environ.get("ATLASSIAN_API_TOKEN")
    if not email or not token:
        print("ERROR: ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN must be set", file=sys.stderr)
        return 2

    try:
        raw = fetch_issue(site, key, email, token)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except requests.RequestException as e:
        print(f"ERROR: network failure — {e}", file=sys.stderr)
        return 1

    normalized = normalize(raw)
    json.dump(normalized, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
