#!/usr/bin/env python3
"""
jira_comment.py — Post a comment to a Jira issue via REST API as fallback
when Atlassian MCP is unavailable or unauthorized.

Usage:
    ATLASSIAN_EMAIL=you@example.com ATLASSIAN_API_TOKEN=xxx \
        python jira_comment.py <site_host> <issue_key> <comment_file>

    # Or pass body via stdin:
    cat report.md | ATLASSIAN_EMAIL=... ATLASSIAN_API_TOKEN=... \
        python jira_comment.py <site_host> <issue_key> -

Output: JSON to stdout with the created comment's id, url, author, created.
        Errors go to stderr; exit code 0 on success, non-zero otherwise.

The comment is sent as ADF (Atlassian Document Format) wrapping the markdown
in a single codeBlock — preserves formatting verbatim. If the user wants the
markdown rendered as native Jira formatting, they should post via MCP with
contentFormat=markdown instead.
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


def markdown_to_adf(md: str) -> dict:
    """Wrap markdown text in a minimal ADF document.

    We don't try to translate markdown → ADF nodes (that's a big undertaking).
    Instead each blank-line-separated block becomes a paragraph; lines stay as
    plain text. This loses formatting but is reliable. For full markdown
    rendering, use the MCP path with contentFormat=markdown.
    """
    blocks = [b.rstrip() for b in md.split("\n\n") if b.strip()]
    content = []
    for block in blocks:
        text = block.replace("\r\n", "\n")
        content.append({
            "type": "paragraph",
            "content": [{"type": "text", "text": text}],
        })
    if not content:
        content = [{"type": "paragraph", "content": [{"type": "text", "text": md or " "}]}]
    return {"version": 1, "type": "doc", "content": content}


def post_comment(site: str, key: str, body_md: str, email: str, token: str) -> dict:
    url = f"https://{site}/rest/api/3/issue/{key}/comment"
    payload = {"body": markdown_to_adf(body_md)}
    resp = requests.post(
        url,
        json=payload,
        auth=(email, token),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        timeout=30,
    )
    if resp.status_code == 401:
        raise RuntimeError("401 Unauthorized — check ATLASSIAN_EMAIL/ATLASSIAN_API_TOKEN")
    if resp.status_code == 403:
        raise RuntimeError(f"403 Forbidden — your account cannot comment on {key}")
    if resp.status_code == 404:
        raise RuntimeError(f"404 Not Found — issue {key} does not exist on {site}")
    resp.raise_for_status()
    data = resp.json()
    return {
        "id": data.get("id"),
        "created": data.get("created"),
        "author": (data.get("author") or {}).get("displayName"),
        "url": f"https://{site}/browse/{key}?focusedCommentId={data.get('id')}",
    }


def main() -> int:
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <site_host> <issue_key> <comment_file_or_->", file=sys.stderr)
        return 2

    site, key, comment_path = sys.argv[1], sys.argv[2], sys.argv[3]
    email = os.environ.get("ATLASSIAN_EMAIL")
    token = os.environ.get("ATLASSIAN_API_TOKEN")
    if not email or not token:
        print("ERROR: ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN must be set", file=sys.stderr)
        return 2

    if comment_path == "-":
        body = sys.stdin.read()
    else:
        try:
            with open(comment_path, encoding="utf-8") as f:
                body = f.read()
        except OSError as e:
            print(f"ERROR: cannot read {comment_path}: {e}", file=sys.stderr)
            return 2

    if not body.strip():
        print("ERROR: comment body is empty", file=sys.stderr)
        return 2

    try:
        result = post_comment(site, key, body, email, token)
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
