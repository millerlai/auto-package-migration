"""Daily issue triage: score open issues with GitHub Models, post digest comment.

Runs in GitHub Actions. Uses only stdlib + GITHUB_TOKEN (no extra deps).
Output: appends one comment to the tracking issue labelled `meta:triage-digest`,
creating the issue + label on first run.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from urllib import error, parse, request

REPO = os.environ["GITHUB_REPOSITORY"]
TOKEN = os.environ["GITHUB_TOKEN"]
MODEL = os.environ.get("TRIAGE_MODEL", "openai/gpt-4o-mini")
MAX_ISSUES = int(os.environ.get("TRIAGE_MAX_ISSUES", "30"))

TRACKING_LABEL = "meta:triage-digest"
GITHUB_API = "https://api.github.com"
MODELS_API = "https://models.github.ai/inference/chat/completions"

# Polite spacing between model calls; gpt-4o-mini free tier is generous but not unlimited.
PER_CALL_DELAY_SEC = 2

SYSTEM_PROMPT = (
    "You triage GitHub issues for the package-upgrade Claude Code Skill, which "
    "automates dependency upgrades, CVE remediation, and Jira-driven maintenance "
    "across Python, JavaScript/TypeScript, and Go. Decide if each issue is worth "
    "opening a PR for. Reply with ONLY valid JSON, no prose."
)

USER_TEMPLATE = """Classify this issue.

Output schema (strict JSON):
{{
  "category": "bug" | "feature" | "enhancement" | "docs" | "question" | "duplicate" | "noise",
  "priority": integer 1-5,   // 5 = open a PR ASAP, 1 = ignore
  "effort":   "small" | "medium" | "large",
  "reason":   string,        // <= 140 chars, English, justifies the priority
  "pr_worthy": boolean       // true only if priority >= 4 AND effort != "large"
}}

Issue #{number}: {title}

Body (truncated to 2000 chars):
{body}
"""


def http(method: str, url: str, payload: dict | None = None, headers: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with request.urlopen(req) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else {}


def gh(method: str, path: str, payload: dict | None = None) -> dict:
    url = f"{GITHUB_API}{path}"
    return http(
        method,
        url,
        payload,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )


def list_open_issues() -> list[dict]:
    """Open issues, excluding PRs and the tracking issue itself."""
    issues = gh("GET", f"/repos/{REPO}/issues?state=open&per_page=100")
    filtered = [
        i for i in issues
        if "pull_request" not in i
        and not any(lbl["name"] == TRACKING_LABEL for lbl in i.get("labels", []))
    ]
    return filtered[:MAX_ISSUES]


def ensure_label() -> None:
    try:
        gh("POST", f"/repos/{REPO}/labels", {
            "name": TRACKING_LABEL,
            "color": "ededed",
            "description": "Daily triage digest tracking issue",
        })
    except error.HTTPError as e:
        if e.code != 422:  # 422 = label already exists
            raise


def find_or_create_tracking_issue() -> int:
    q = parse.urlencode({"labels": TRACKING_LABEL, "state": "open", "per_page": 1})
    issues = gh("GET", f"/repos/{REPO}/issues?{q}")
    if issues:
        return issues[0]["number"]
    ensure_label()
    created = gh("POST", f"/repos/{REPO}/issues", {
        "title": "Daily Issue Triage Digest",
        "body": (
            "This issue is the rolling log for the `Daily Issue Triage` workflow.\n\n"
            "Each scheduled run appends one comment ranking open issues by an "
            "LLM-assigned priority. **PRs remain fully manual** — use this as a "
            "decision aid, not an action."
        ),
        "labels": [TRACKING_LABEL],
    })
    return created["number"]


def score_issue(issue: dict) -> dict:
    body = (issue.get("body") or "")[:2000]
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_TEMPLATE.format(
                number=issue["number"], title=issue["title"], body=body,
            )},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    resp = http("POST", MODELS_API, payload)
    content = resp["choices"][0]["message"]["content"]
    return json.loads(content)


def render_digest(scored: list[tuple[dict, dict]]) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    run_id = os.environ.get("GITHUB_RUN_ID", "manual")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    run_link = f"{server}/{REPO}/actions/runs/{run_id}" if run_id != "manual" else ""

    lines = [
        f"## Daily Triage — {ts}",
        "",
        f"Model: `{MODEL}` · Issues scored: **{len(scored)}**"
        + (f" · [run log]({run_link})" if run_link else ""),
        "",
        "| # | Title | Category | Priority | Effort | PR? | Reason |",
        "|---|---|---|---:|---|:---:|---|",
    ]
    for issue, v in scored:
        title = issue["title"].replace("|", "\\|")[:70]
        reason = (v.get("reason") or "").replace("|", "\\|")
        pr_mark = "✅" if v.get("pr_worthy") else ""
        lines.append(
            f"| [#{issue['number']}]({issue['html_url']}) "
            f"| {title} "
            f"| {v.get('category', '?')} "
            f"| {v.get('priority', '?')} "
            f"| {v.get('effort', '?')} "
            f"| {pr_mark} "
            f"| {reason} |"
        )
    return "\n".join(lines)


def main() -> int:
    issues = list_open_issues()
    if not issues:
        print("No open issues to triage.")
        return 0

    scored: list[tuple[dict, dict]] = []
    for issue in issues:
        try:
            verdict = score_issue(issue)
        except Exception as e:  # noqa: BLE001 — one bad issue shouldn't kill the batch
            verdict = {
                "category": "error",
                "priority": 0,
                "effort": "?",
                "reason": f"scoring failed: {type(e).__name__}: {e}",
                "pr_worthy": False,
            }
        scored.append((issue, verdict))
        time.sleep(PER_CALL_DELAY_SEC)

    scored.sort(key=lambda x: int(x[1].get("priority", 0) or 0), reverse=True)

    digest = render_digest(scored)
    tracking = find_or_create_tracking_issue()
    gh("POST", f"/repos/{REPO}/issues/{tracking}/comments", {"body": digest})
    print(f"Posted digest with {len(scored)} issues to #{tracking}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
