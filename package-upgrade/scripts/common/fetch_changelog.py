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

import argparse
import re
import sys
from typing import Optional

import requests

_GITHUB_REPO_RE = re.compile(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?(?=/|$)")


def _extract_owner_repo(url: str) -> Optional[tuple[str, str]]:
    match = _GITHUB_REPO_RE.search(url)
    if not match:
        return None
    return match.group(1).lower(), match.group(2).lower()


def _same_github_repo(url_a: str, url_b: str) -> bool:
    """Case-insensitive GitHub owner/repo comparison, ignoring `.git` and a
    trailing slash (both stripped already by `_GITHUB_REPO_RE`'s boundary)."""
    a = _extract_owner_repo(url_a)
    b = _extract_owner_repo(url_b)
    return a is not None and a == b


def fetch_from_pypi(package_name: str, git_repo_url: str) -> Optional[tuple[str, str, str]]:
    """Try to fetch changelog from PyPI metadata.

    Only trusted when the PyPI project's `project_urls` or `home_page` points
    at the same GitHub repo as `git_repo_url` — otherwise a same-named but
    unrelated PyPI project (e.g. `semver` vs. npm's `node-semver`) would be
    reported as authoritative.

    Returns: (source_label, source_url, content) or None
    """
    try:
        url = f"https://pypi.org/pypi/{package_name}/json"
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        data = response.json()
        info = data.get("info") or {}
        project_urls = info.get("project_urls") or {}
        home_page = info.get("home_page") or ""

        candidates = [u for u in list(project_urls.values()) + [home_page] if u]
        if not any(_same_github_repo(c, git_repo_url) for c in candidates):
            return None

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
    except (requests.RequestException, KeyError, ValueError, TypeError):
        return None


_RELEASE_PAGE_CAP = 10  # C9 / budgets: 10 pages x per_page=100 = 1000 releases


def _version_key(tag: str) -> tuple[int, ...]:
    """Best-effort dotted-integer key for ordering release tags (D7).

    Mirrors `python/dep_tree.py`'s `version_tuple`: strips a leading `v`,
    `release-` or `release/`, then reads dotted integers. Returns () when the
    tag does not parse, so an odd tag scheme can only over-include releases
    in the range filter, never silently drop them.
    """
    if not tag:
        return ()
    t = tag.strip()
    for prefix in ("release-", "release/", "v"):
        if t.lower().startswith(prefix):
            t = t[len(prefix) :]
            break
    match = re.match(r"^(\d+(?:\.\d+)*)", t)
    if not match:
        return ()
    parts = []
    for p in match.group(1).split("."):
        if not p.isdigit():
            return ()
        parts.append(int(p))
    return tuple(parts)


def _in_range(
    tag: str, old_key: Optional[tuple[int, ...]], new_key: Optional[tuple[int, ...]]
) -> bool:
    """Keep a tag when its key is unparseable (D7: over-include) or falls in (old, new]."""
    key = _version_key(tag)
    if not key:
        return True
    if old_key and key <= old_key:
        return False
    if new_key and key > new_key:
        return False
    return True


def fetch_from_github_releases(
    repo_url: str,
    old_version: Optional[str] = None,
    new_version: Optional[str] = None,
) -> Optional[tuple[str, str, str]]:
    """Try to fetch changelog from GitHub Releases API.

    Paginates at `per_page=100`, following `response.links["next"]`, and
    stops once a release matching `old_version` has been seen or after
    `_RELEASE_PAGE_CAP` pages. When both `old_version` and `new_version` are
    given, only releases in (old, new] are kept and the output is prefixed
    with the covered range. If `old_version` was never reached, the output
    is flagged with a partial-coverage marker instead of being reported as
    complete (issue-68.md T13).

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

        old_key = _version_key(old_version) if old_version else None
        new_key = _version_key(new_version) if new_version else None
        # Reuse _resolve_tag's candidate forms so an exact-string match still
        # works when old_version itself doesn't parse as a dotted version.
        old_candidates = (
            {f"v{old_version}", old_version, f"release-{old_version}", f"release/{old_version}"}
            if old_version
            else set()
        )

        releases: list = []
        partial = False
        url: Optional[str] = api_url
        params: Optional[dict] = {"per_page": "100"}

        for page in range(1, _RELEASE_PAGE_CAP + 1):
            assert url is not None  # only unset when we've already broken out below
            try:
                response = requests.get(url, params=params, timeout=10)
                response.raise_for_status()
            except requests.RequestException:
                if page == 1:
                    return None
                if old_version:
                    partial = True
                break

            page_releases = response.json()
            if not isinstance(page_releases, list):
                break
            releases.extend(page_releases)

            old_seen = False
            if old_version:
                for r in page_releases:
                    tag = r.get("tag_name", "")
                    rkey = _version_key(tag)
                    if tag in old_candidates or (old_key and rkey and rkey <= old_key):
                        old_seen = True
                        break
            if old_seen:
                break

            next_link = response.links.get("next")
            if not next_link:
                if old_version:
                    partial = True
                break
            url = next_link["url"]
            params = None  # the `next` URL already carries the query string
        else:
            if old_version:
                partial = True

        if not releases:
            return None

        if old_version and new_version:
            releases = [r for r in releases if _in_range(r.get("tag_name", ""), old_key, new_key)]
            if not releases:
                return None

        # Format releases into changelog
        changelog_parts = []
        if old_version and new_version:
            changelog_parts.append(f"Covered range: ({old_version}, {new_version}]")
        if partial:
            changelog_parts.append("<!-- changelog_coverage: partial -->")
        changelog_parts.append(f"# Changelog from GitHub Releases ({human_url})\n")
        for release in releases:
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


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch changelog for a package (Python, JavaScript or Go).",
    )
    parser.add_argument("package_name")
    parser.add_argument("git_repo_url")
    parser.add_argument("old_version", nargs="?", default=None)
    parser.add_argument("new_version", nargs="?", default=None)
    parser.add_argument(
        "--ecosystem",
        choices=["pypi", "npm", "go"],
        default=None,
        help="restricts step 1 (PyPI metadata) to pypi; no flag still tries it, "
        "behind the repo-identity guard",
    )
    return parser


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    args = build_arg_parser().parse_args()

    package_name = args.package_name
    git_repo_url = args.git_repo_url
    old_version = args.old_version
    new_version = args.new_version

    result = None
    attempted = []

    print("# Attempting to fetch changelog...\n", file=sys.stderr)

    if args.ecosystem in (None, "pypi"):
        print("Trying PyPI metadata...", file=sys.stderr)
        attempted.append("PyPI project_urls.Changelog")
        result = fetch_from_pypi(package_name, git_repo_url)

    if not result:
        print("Trying GitHub Releases API...", file=sys.stderr)
        attempted.append("GitHub Releases API")
        result = fetch_from_github_releases(git_repo_url, old_version, new_version)

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
