#!/usr/bin/env python3
"""Fetch changelog for a package (Python or JavaScript).

Usage: python fetch_changelog.py <package_name> <git_repo_url> [<old_version> <new_version>]
Output: Raw changelog text to stdout, prefixed with HTML-comment metadata
        headers (changelog_source_label, changelog_source_url) so the consuming
        LLM can cite the exact source in the migration report.

Fallback chain (each step tries the next on failure):
  1. PyPI metadata `project_urls.Changelog`
  2. GitHub Releases API
  3. Common changelog file paths in the repo (CHANGELOG.md / CHANGES.rst / ...)
  4. (if old/new versions given) GitHub Compare API — commit messages between tags
  5. (if old/new versions given) GitHub tag annotation messages

Steps 4 and 5 require the optional old/new version arguments. They are
particularly useful for packages that don't publish formal release notes
(common for small npm libs).
"""

from __future__ import annotations

import re
import sys
from typing import Optional

import requests


def fetch_from_pypi(package_name: str) -> Optional[tuple[str, str, str]]:
    """Try to fetch changelog from PyPI metadata.

    Returns: (source_label, source_url, content) or None
    """
    try:
        url = f"https://pypi.org/pypi/{package_name}/json"
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        data = response.json()
        project_urls = data.get("info", {}).get("project_urls", {})

        # Look for common changelog URL keys
        changelog_keys = ["Changelog", "Change Log", "CHANGELOG", "Release Notes", "What's New"]
        for key in changelog_keys:
            if key in project_urls:
                changelog_url = project_urls[key]
                changelog_response = requests.get(changelog_url, timeout=10)
                if changelog_response.status_code == 200:
                    return (
                        f"PyPI project_urls[{key}]",
                        changelog_url,
                        changelog_response.text,
                    )

        return None
    except (requests.RequestException, KeyError, ValueError):
        return None


def fetch_from_github_releases(repo_url: str) -> Optional[tuple[str, str, str]]:
    """Try to fetch changelog from GitHub Releases API.

    Returns: (source_label, source_url, content) or None
    """
    try:
        # Parse GitHub repo URL
        # Supports: https://github.com/owner/repo or git@github.com:owner/repo.git
        match = re.search(r"github\.com[:/]([^/]+)/([^/\.]+)", repo_url)
        if not match:
            return None

        owner, repo = match.groups()
        api_url = f"https://api.github.com/repos/{owner}/{repo}/releases"
        human_url = f"https://github.com/{owner}/{repo}/releases"

        response = requests.get(api_url, timeout=10)
        response.raise_for_status()

        releases = response.json()
        if not releases:
            return None

        # Format releases into changelog
        changelog_parts = [f"# Changelog from GitHub Releases ({human_url})\n"]
        for release in releases[:50]:  # Limit to recent 50 releases
            tag = release.get("tag_name", "Unknown")
            name = release.get("name", tag)
            body = release.get("body", "No release notes")
            published = release.get("published_at", "")
            release_url = release.get("html_url", "")

            changelog_parts.append(f"\n## {name} ({tag})")
            if release_url:
                changelog_parts.append(f"URL: {release_url}")
            if published:
                changelog_parts.append(f"Published: {published}")
            changelog_parts.append(f"\n{body}\n")
            changelog_parts.append("---")

        return (
            "GitHub Releases API",
            human_url,
            "\n".join(changelog_parts),
        )

    except (requests.RequestException, KeyError, ValueError, IndexError):
        return None


def fetch_from_common_files(repo_url: str) -> Optional[tuple[str, str, str]]:
    """Try to fetch changelog from common file locations in repo.

    Returns: (source_label, source_url, content) or None
    """
    try:
        # Parse GitHub repo URL
        match = re.search(r"github\.com[:/]([^/]+)/([^/\.]+)", repo_url)
        if not match:
            return None

        owner, repo = match.groups()

        # Common changelog filenames
        changelog_files = [
            "CHANGELOG.md",
            "CHANGELOG.rst",
            "CHANGELOG.txt",
            "CHANGELOG",
            "CHANGES.md",
            "CHANGES.rst",
            "CHANGES.txt",
            "CHANGES",
            "HISTORY.md",
            "HISTORY.rst",
            "NEWS.md",
            "RELEASES.md",
        ]

        for filename in changelog_files:
            # Try main/master branch
            for branch in ["main", "master"]:
                raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{filename}"
                try:
                    response = requests.get(raw_url, timeout=10)
                    if response.status_code == 200:
                        human_url = f"https://github.com/{owner}/{repo}/blob/{branch}/{filename}"
                        return (
                            f"Repo file ({branch}/{filename})",
                            human_url,
                            response.text,
                        )
                except requests.RequestException:
                    continue

        return None

    except (requests.RequestException, AttributeError):
        return None


def _resolve_tag(owner: str, repo: str, version: str) -> Optional[str]:
    """Try common tag patterns and return the first that resolves on GitHub."""
    candidates = [f"v{version}", version, f"release-{version}", f"release/{version}"]
    for tag in candidates:
        url = f"https://api.github.com/repos/{owner}/{repo}/git/refs/tags/{tag}"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                return tag
        except requests.RequestException:
            continue
    return None


def fetch_from_github_compare(
    repo_url: str, old_version: str, new_version: str
) -> Optional[tuple[str, str, str]]:
    """Fallback: list commits between two version tags using the GitHub Compare API.

    Useful for packages that ship git tags but no GitHub Releases (common for
    libs maintained by individuals).
    """
    try:
        match = re.search(r"github\.com[:/]([^/]+)/([^/\.]+)", repo_url)
        if not match:
            return None
        owner, repo = match.groups()

        old_tag = _resolve_tag(owner, repo, old_version)
        new_tag = _resolve_tag(owner, repo, new_version)
        if not old_tag or not new_tag:
            return None

        api_url = f"https://api.github.com/repos/{owner}/{repo}/compare/{old_tag}...{new_tag}"
        human_url = f"https://github.com/{owner}/{repo}/compare/{old_tag}...{new_tag}"
        r = requests.get(api_url, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json()

        commits = data.get("commits", [])
        if not commits:
            return None

        lines = [
            f"# Commit log from GitHub Compare ({human_url})\n",
            f"# {len(commits)} commits between {old_tag} and {new_tag}\n",
        ]
        for c in commits[:300]:  # cap to avoid huge outputs
            sha = (c.get("sha") or "")[:12]
            msg = c.get("commit", {}).get("message", "").split("\n")[0]
            author = c.get("commit", {}).get("author", {}).get("name", "")
            lines.append(f"- {sha} ({author}): {msg}")

        return ("GitHub Compare API", human_url, "\n".join(lines))
    except (requests.RequestException, KeyError, ValueError):
        return None


def fetch_from_github_tag_annotation(repo_url: str, version: str) -> Optional[tuple[str, str, str]]:
    """Fallback: read the annotated message of a single git tag.

    Some maintainers put release notes only in `git tag -a v1.2.3 -m '...'`.
    """
    try:
        match = re.search(r"github\.com[:/]([^/]+)/([^/\.]+)", repo_url)
        if not match:
            return None
        owner, repo = match.groups()

        tag = _resolve_tag(owner, repo, version)
        if not tag:
            return None
        # Resolve the ref to the tag object SHA, then fetch the tag object
        ref_url = f"https://api.github.com/repos/{owner}/{repo}/git/refs/tags/{tag}"
        r = requests.get(ref_url, timeout=10)
        if r.status_code != 200:
            return None
        obj = r.json().get("object", {})
        if obj.get("type") != "tag":
            return None  # lightweight tag, no annotation
        tag_url = obj.get("url")
        if not tag_url:
            return None
        r = requests.get(tag_url, timeout=10)
        if r.status_code != 200:
            return None
        tag_obj = r.json()
        message = tag_obj.get("message", "").strip()
        if not message:
            return None

        human_url = f"https://github.com/{owner}/{repo}/releases/tag/{tag}"
        content = f"# Annotated tag {tag}\n\n{message}\n"
        return ("GitHub tag annotation", human_url, content)
    except (requests.RequestException, KeyError, ValueError):
        return None


def main():
    if len(sys.argv) < 3:
        print(
            "Usage: python fetch_changelog.py <package_name> <git_repo_url> [<old_version> <new_version>]",
            file=sys.stderr,
        )
        sys.exit(1)

    package_name = sys.argv[1]
    git_repo_url = sys.argv[2]
    old_version = sys.argv[3] if len(sys.argv) > 4 else None
    new_version = sys.argv[4] if len(sys.argv) > 4 else None

    result = None
    attempted = []

    print("# Attempting to fetch changelog...\n", file=sys.stderr)
    print("Trying PyPI metadata...", file=sys.stderr)
    attempted.append("PyPI project_urls.Changelog")
    result = fetch_from_pypi(package_name)

    if not result:
        print("Trying GitHub Releases API...", file=sys.stderr)
        attempted.append("GitHub Releases API")
        result = fetch_from_github_releases(git_repo_url)

    if not result:
        print("Trying common changelog files...", file=sys.stderr)
        attempted.append("Repo file (CHANGELOG.md / CHANGES.rst / HISTORY.md / ...)")
        result = fetch_from_common_files(git_repo_url)

    if not result and old_version and new_version:
        print(f"Trying GitHub Compare API ({old_version}...{new_version})...", file=sys.stderr)
        attempted.append("GitHub Compare API")
        result = fetch_from_github_compare(git_repo_url, old_version, new_version)

    if not result and new_version:
        print(f"Trying GitHub tag annotation (v{new_version})...", file=sys.stderr)
        attempted.append("GitHub tag annotation")
        result = fetch_from_github_tag_annotation(git_repo_url, new_version)

    if result:
        source_label, source_url, content = result
        print(f"\nChangelog found from: {source_label} ({source_url})\n", file=sys.stderr)
        print(f"<!-- changelog_source_label: {source_label} -->")
        print(f"<!-- changelog_source_url: {source_url} -->")
        print()
        print(content)
    else:
        print("\nNo changelog found from any source.", file=sys.stderr)
        print(f"Attempted: {', '.join(attempted)}", file=sys.stderr)
        print("You may need to manually search for breaking changes.", file=sys.stderr)
        print("<!-- changelog_source_label: NOT_FOUND -->")
        print("<!-- changelog_source_url: NOT_FOUND -->")
        print(f"<!-- changelog_attempts: {' | '.join(attempted)} -->")
        sys.exit(1)


if __name__ == "__main__":
    main()
