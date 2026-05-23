"""Tests for package-upgrade/scripts/fetch_changelog.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests as _requests

import fetch_changelog as fc


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _resp(status: int = 200, body: str = "", json_data=None) -> MagicMock:
    m = MagicMock()
    m.status_code = status
    m.text = body
    if json_data is not None:
        m.json.return_value = json_data
    else:
        m.json.side_effect = ValueError("no json")
    if status >= 400:
        m.raise_for_status.side_effect = _requests.HTTPError(f"HTTP {status}")
    return m


# --------------------------------------------------------------------------- #
# fetch_from_pypi
# --------------------------------------------------------------------------- #

class TestFetchFromPypi:
    def test_returns_content_when_pypi_has_changelog_url(self):
        pypi_resp = _resp(200, json_data={
            "info": {"project_urls": {"Changelog": "https://example.com/CHANGES"}}
        })
        changelog_resp = _resp(200, body="# Changelog\n- v1: bug fix")
        with patch.object(fc.requests, "get", side_effect=[pypi_resp, changelog_resp]):
            result = fc.fetch_from_pypi("requests")
        assert result is not None
        label, url, content = result
        assert "PyPI" in label
        assert url == "https://example.com/CHANGES"
        assert "Changelog" in content

    def test_returns_none_when_no_changelog_url(self):
        pypi_resp = _resp(200, json_data={"info": {"project_urls": {}}})
        with patch.object(fc.requests, "get", return_value=pypi_resp):
            assert fc.fetch_from_pypi("requests") is None

    def test_returns_none_when_pypi_404(self):
        bad = _resp(404)
        with patch.object(fc.requests, "get", return_value=bad):
            assert fc.fetch_from_pypi("nonexistent") is None

    def test_returns_none_on_network_error(self):
        with patch.object(fc.requests, "get",
                          side_effect=_requests.ConnectionError("dns")):
            assert fc.fetch_from_pypi("requests") is None

    def test_uses_first_matching_key(self):
        # `Changelog` should win over `Release Notes` because of catalogue order
        pypi_resp = _resp(200, json_data={
            "info": {
                "project_urls": {
                    "Changelog": "https://a.com/CHANGES",
                    "Release Notes": "https://b.com/NOTES",
                }
            }
        })
        changelog_resp = _resp(200, body="A")
        with patch.object(fc.requests, "get", side_effect=[pypi_resp, changelog_resp]):
            result = fc.fetch_from_pypi("x")
        assert result is not None
        assert result[1] == "https://a.com/CHANGES"

    def test_skips_unreachable_changelog_url(self):
        pypi_resp = _resp(200, json_data={
            "info": {"project_urls": {"Changelog": "https://broken.example.com/CHANGES"}}
        })
        bad_changelog = _resp(500)
        with patch.object(fc.requests, "get", side_effect=[pypi_resp, bad_changelog]):
            assert fc.fetch_from_pypi("x") is None


# --------------------------------------------------------------------------- #
# fetch_from_github_releases
# --------------------------------------------------------------------------- #

class TestFetchFromGithubReleases:
    def test_returns_formatted_releases(self):
        releases = [
            {
                "tag_name": "v1.0.0",
                "name": "Release 1.0",
                "body": "First stable release",
                "published_at": "2024-01-01T00:00:00Z",
                "html_url": "https://github.com/o/r/releases/tag/v1.0.0",
            }
        ]
        with patch.object(fc.requests, "get", return_value=_resp(200, json_data=releases)):
            result = fc.fetch_from_github_releases("https://github.com/owner/repo")
        assert result is not None
        label, url, content = result
        assert label == "GitHub Releases API"
        assert url == "https://github.com/owner/repo/releases"
        assert "Release 1.0" in content
        assert "First stable release" in content

    def test_returns_none_for_non_github_url(self):
        assert fc.fetch_from_github_releases("https://gitlab.com/o/r") is None
        assert fc.fetch_from_github_releases("https://bitbucket.org/o/r") is None

    def test_returns_none_when_no_releases(self):
        with patch.object(fc.requests, "get", return_value=_resp(200, json_data=[])):
            assert fc.fetch_from_github_releases("https://github.com/o/r") is None

    def test_parses_ssh_style_url(self):
        with patch.object(fc.requests, "get",
                          return_value=_resp(200, json_data=[
                              {"tag_name": "v1", "name": "v1", "body": "x"}
                          ])):
            result = fc.fetch_from_github_releases("git@github.com:owner/repo.git")
        assert result is not None
        assert "owner/repo" in result[1]

    def test_returns_none_on_http_error(self):
        with patch.object(fc.requests, "get", return_value=_resp(500)):
            assert fc.fetch_from_github_releases("https://github.com/o/r") is None

    def test_caps_at_50_releases(self):
        many = [{"tag_name": f"v{i}", "name": f"r{i}", "body": "b"} for i in range(100)]
        with patch.object(fc.requests, "get",
                          return_value=_resp(200, json_data=many)):
            result = fc.fetch_from_github_releases("https://github.com/o/r")
        # Each release adds a header like "## r{i} (v{i})" — count them
        assert result is not None
        # Should NOT include r50 (only r0..r49)
        assert "## r0 " in result[2]
        assert "## r49 " in result[2]
        assert "## r50 " not in result[2]


# --------------------------------------------------------------------------- #
# fetch_from_common_files
# --------------------------------------------------------------------------- #

class TestFetchFromCommonFiles:
    def test_returns_first_matching_file(self):
        # First file/branch tried: CHANGELOG.md @ main → return 200
        with patch.object(fc.requests, "get",
                          return_value=_resp(200, body="# Changelog\n")):
            result = fc.fetch_from_common_files("https://github.com/owner/repo")
        assert result is not None
        label, url, content = result
        assert "CHANGELOG.md" in label
        assert "main" in label
        assert "owner/repo" in url
        assert "# Changelog" in content

    def test_falls_back_to_master_when_main_404(self):
        # main 404 → master 200 for CHANGELOG.md (first filename)
        responses = [_resp(404), _resp(200, body="content from master")]
        with patch.object(fc.requests, "get", side_effect=responses):
            result = fc.fetch_from_common_files("https://github.com/owner/repo")
        assert result is not None
        assert "master" in result[0]

    def test_returns_none_for_non_github(self):
        assert fc.fetch_from_common_files("https://gitlab.com/o/r") is None

    def test_returns_none_when_all_files_404(self):
        # 12 filenames × 2 branches = 24 attempts
        with patch.object(fc.requests, "get", return_value=_resp(404)):
            assert fc.fetch_from_common_files("https://github.com/o/r") is None


# --------------------------------------------------------------------------- #
# _resolve_tag
# --------------------------------------------------------------------------- #

class TestResolveTag:
    def test_resolves_v_prefix_first(self):
        # `v1.2.3` succeeds on first try
        with patch.object(fc.requests, "get", return_value=_resp(200)):
            tag = fc._resolve_tag("o", "r", "1.2.3")
        assert tag == "v1.2.3"

    def test_falls_back_to_plain_version(self):
        # v1.2.3 fails, 1.2.3 succeeds
        with patch.object(fc.requests, "get",
                          side_effect=[_resp(404), _resp(200)]):
            tag = fc._resolve_tag("o", "r", "1.2.3")
        assert tag == "1.2.3"

    def test_returns_none_when_no_tag_resolves(self):
        with patch.object(fc.requests, "get", return_value=_resp(404)):
            assert fc._resolve_tag("o", "r", "1.2.3") is None

    def test_swallows_request_exception(self):
        with patch.object(fc.requests, "get",
                          side_effect=_requests.ConnectionError("dns")):
            assert fc._resolve_tag("o", "r", "1.2.3") is None


# --------------------------------------------------------------------------- #
# fetch_from_github_compare
# --------------------------------------------------------------------------- #

class TestFetchFromGithubCompare:
    def test_returns_commit_list(self):
        # _resolve_tag: 2 calls (one per version), each succeeds on first try
        tag_resp = _resp(200)
        compare = _resp(200, json_data={
            "commits": [
                {"sha": "abc123def456", "commit": {
                    "message": "fix: thing\n\nmore detail",
                    "author": {"name": "Alice"},
                }}
            ]
        })
        with patch.object(fc.requests, "get",
                          side_effect=[tag_resp, tag_resp, compare]):
            result = fc.fetch_from_github_compare(
                "https://github.com/o/r", "1.0.0", "1.1.0"
            )
        assert result is not None
        label, url, content = result
        assert label == "GitHub Compare API"
        assert "v1.0.0...v1.1.0" in url
        assert "abc123def456" in content
        assert "Alice" in content
        # Only the first line of the commit msg
        assert "fix: thing" in content
        assert "more detail" not in content

    def test_returns_none_when_tag_cant_resolve(self):
        with patch.object(fc.requests, "get", return_value=_resp(404)):
            result = fc.fetch_from_github_compare(
                "https://github.com/o/r", "1.0", "1.1"
            )
        assert result is None

    def test_returns_none_for_non_github(self):
        assert fc.fetch_from_github_compare("https://gitlab.com/o/r", "1", "2") is None

    def test_returns_none_when_no_commits(self):
        tag = _resp(200)
        compare = _resp(200, json_data={"commits": []})
        with patch.object(fc.requests, "get", side_effect=[tag, tag, compare]):
            result = fc.fetch_from_github_compare(
                "https://github.com/o/r", "1.0", "1.1"
            )
        assert result is None


# --------------------------------------------------------------------------- #
# fetch_from_github_tag_annotation
# --------------------------------------------------------------------------- #

class TestFetchFromGithubTagAnnotation:
    def test_returns_annotation_message(self):
        # 1) resolve tag (200), 2) ref lookup → object{type=tag,url=...}, 3) tag obj fetch
        resolve = _resp(200)
        ref = _resp(200, json_data={"object": {
            "type": "tag", "url": "https://api.github.com/tag-obj"
        }})
        tag_obj = _resp(200, json_data={"message": "Release notes for v1\n"})
        with patch.object(fc.requests, "get",
                          side_effect=[resolve, ref, tag_obj]):
            result = fc.fetch_from_github_tag_annotation(
                "https://github.com/o/r", "1.0.0"
            )
        assert result is not None
        label, url, content = result
        assert label == "GitHub tag annotation"
        assert "Release notes for v1" in content

    def test_returns_none_for_lightweight_tag(self):
        # `object.type` is "commit" not "tag" → lightweight tag, no annotation
        resolve = _resp(200)
        ref = _resp(200, json_data={"object": {"type": "commit"}})
        with patch.object(fc.requests, "get", side_effect=[resolve, ref]):
            assert fc.fetch_from_github_tag_annotation(
                "https://github.com/o/r", "1.0"
            ) is None

    def test_returns_none_when_tag_cant_resolve(self):
        with patch.object(fc.requests, "get", return_value=_resp(404)):
            assert fc.fetch_from_github_tag_annotation(
                "https://github.com/o/r", "1.0"
            ) is None
