#!/usr/bin/env python3
"""Merge the package-upgrade skill's recommended permissions into a Claude Code settings file.

Usage:
    python3 grant_permissions.py --settings <path> --mode <global|project> [--dry-run]

The script is idempotent: re-running adds nothing if every entry already exists.
Existing settings outside `permissions.allow` / `permissions.ask` are left untouched.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


COMMON_ALLOW = [
    "Bash(git status:*)",
    "Bash(git rev-parse:*)",
    "Bash(git remote:*)",
    "Bash(git log:*)",
    "Bash(git diff:*)",
    "Bash(git checkout -b *)",
    "Bash(git add pyproject.toml poetry.lock)",
    "Bash(git add package.json package-lock.json)",
    "Bash(git commit -m *)",
    # --- Python package managers ---
    "Bash(poetry add *)",
    "Bash(poetry update *)",
    "Bash(poetry lock:*)",
    "Bash(poetry show:*)",
    "Bash(pip install:*)",
    "Bash(pip show:*)",
    "Bash(pip list:*)",
    "Bash(pip freeze:*)",
    "Bash(pip check:*)",
    "Bash(pip-compile:*)",
    "Bash(pip-sync:*)",
    "Bash(uv add:*)",
    "Bash(uv remove:*)",
    "Bash(uv lock:*)",
    "Bash(uv sync:*)",
    "Bash(uv pip:*)",
    # --- JavaScript package managers (MVP: npm; others when supported) ---
    "Bash(node:*)",
    "Bash(npm install:*)",
    "Bash(npm ci:*)",
    "Bash(npm update:*)",
    "Bash(npm ls:*)",
    "Bash(npm show:*)",
    "Bash(npm view:*)",
    "Bash(npm pack:*)",
    "Bash(npm outdated:*)",
    "Bash(npm rebuild:*)",
    "Bash(npm audit:*)",
    "Bash(npx --no-install:*)",
    "Bash(npx --yes:*)",
    # yarn (incl. yarn 3 Berry via .yarn/releases)
    "Bash(yarn:*)",
    "Bash(corepack:*)",
    # pnpm
    "Bash(pnpm:*)",
    # bun
    "Bash(bun install:*)",
    "Bash(bun pm:*)",
    "Bash(bun outdated:*)",
    # --- GitHub CLI (PR creation, auth status checks for GHE) ---
    "Bash(gh auth status:*)",
    "Bash(gh pr create:*)",
    "Bash(gh pr view:*)",
    "Bash(gh api:*)",
    # --- Shared utilities ---
    "Bash(grep:*)",
    "Bash(docker ps:*)",
    "Bash(command -v *)",
    "Bash(tar -xzf:*)",
    "Bash(shasum:*)",
    # --- Web fetches ---
    "WebFetch(domain:pypi.org)",
    "WebFetch(domain:registry.npmjs.org)",
    "WebFetch(domain:www.npmjs.com)",
    "WebFetch(domain:github.com)",
    "WebFetch(domain:raw.githubusercontent.com)",
    "WebFetch(domain:api.github.com)",
    # OSV API + BlackDuck (internal) for vulnerability lookups
    "WebFetch(domain:api.osv.dev)",
    "WebFetch(domain:osv.dev)",
    "WebFetch(domain:nvd.nist.gov)",
    "WebFetch(domain:blackduck.trendmicro.com)",
    "WebSearch",
    "mcp__claude_ai_Atlassian_Rovo__getJiraIssue",
    "mcp__claude_ai_Atlassian_Rovo__getTransitionsForJiraIssue",
    "mcp__claude_ai_Atlassian_Rovo__getAccessibleAtlassianResources",
]

COMMON_ASK = [
    "Bash(git push:*)",
    "Bash(git commit:*)",
    "mcp__claude_ai_Atlassian_Rovo__addCommentToJiraIssue",
    "mcp__claude_ai_Atlassian_Rovo__transitionJiraIssue",
]

SCRIPT_ALLOW_BY_MODE = {
    "global": [
        "Bash(bash ~/.claude/skills/package-upgrade/scripts/*:*)",
        "Bash(python3 ~/.claude/skills/package-upgrade/scripts/*:*)",
        "Bash(node ~/.claude/skills/package-upgrade/scripts/*:*)",
    ],
    "project": [
        "Bash(bash .claude/skills/package-upgrade/scripts/*:*)",
        "Bash(python3 .claude/skills/package-upgrade/scripts/*:*)",
        "Bash(node .claude/skills/package-upgrade/scripts/*:*)",
    ],
}


def desired_entries(mode: str) -> tuple[list[str], list[str]]:
    allow = SCRIPT_ALLOW_BY_MODE[mode] + COMMON_ALLOW
    return allow, list(COMMON_ASK)


def load_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"error: {path} is not valid JSON: {exc}\n")
        sys.exit(2)


def merge(existing: list, additions: list) -> tuple[list, list]:
    """Append items from additions that aren't already in existing. Returns (new_list, added)."""
    seen = set(existing)
    added = []
    for item in additions:
        if item not in seen:
            existing.append(item)
            seen.add(item)
            added.append(item)
    return existing, added


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", required=True, help="Path to settings.json (created if missing)")
    parser.add_argument("--mode", required=True, choices=["global", "project"])
    parser.add_argument("--dry-run", action="store_true", help="Print what would change without writing")
    args = parser.parse_args()

    settings_path = Path(args.settings).expanduser()
    settings = load_settings(settings_path)

    permissions = settings.setdefault("permissions", {})
    allow_list = permissions.setdefault("allow", [])
    ask_list = permissions.setdefault("ask", [])

    desired_allow, desired_ask = desired_entries(args.mode)
    _, added_allow = merge(allow_list, desired_allow)
    _, added_ask = merge(ask_list, desired_ask)

    print(f"Target: {settings_path}")
    print(f"Mode:   {args.mode}")
    print(f"Allow:  +{len(added_allow)} new (total {len(allow_list)})")
    print(f"Ask:    +{len(added_ask)} new (total {len(ask_list)})")

    if added_allow:
        print("\nNewly allowed:")
        for item in added_allow:
            print(f"  + {item}")
    if added_ask:
        print("\nNewly gated (will prompt):")
        for item in added_ask:
            print(f"  + {item}")
    if not added_allow and not added_ask:
        print("\nNothing to add — settings already contain every recommended entry.")
        return 0

    if args.dry_run:
        print("\n--dry-run: settings file not modified.")
        return 0

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"\nUpdated {settings_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
