"""Tests for package-upgrade/scripts/common/fetch_changelog.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests as _requests

import fetch_changelog as fc

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _resp(
    status: int = 200, body: str = "", json_data=None, links: dict | None = None
) -> MagicMock:
    m = MagicMock()
    m.status_code = status
    m.text = body
    if json_data is not None:
        m.json.return_value = json_data
    else:
        m.json.side_effect = ValueError("no json")
    if status >= 400:
        m.raise_for_status.side_effect = _requests.HTTPError(f"HTTP {status}")
    m.links = links or {}
    return m


# --------------------------------------------------------------------------- #
# fetch_from_pypi
# --------------------------------------------------------------------------- #


class TestFetchFromPypi:
    REPO = "https://github.com/owner/repo"

    def test_returns_content_when_pypi_has_changelog_url(self):
        pypi_resp = _resp(
            200,
            json_data={
                "info": {
                    "project_urls": {
                        "Changelog": "https://example.com/CHANGES",
                        "Homepage": self.REPO,
                    }
                }
            },
        )
        changelog_resp = _resp(200, body="# Changelog\n- v1: bug fix")
        with patch.object(fc.requests, "get", side_effect=[pypi_resp, changelog_resp]):
            result = fc.fetch_from_pypi("requests", self.REPO)
        assert result is not None
        label, url, content = result
        assert "PyPI" in label
        assert url == "https://example.com/CHANGES"
        assert "Changelog" in content

    def test_returns_none_when_no_changelog_url(self):
        pypi_resp = _resp(200, json_data={"info": {"project_urls": {"Homepage": self.REPO}}})
        with patch.object(fc.requests, "get", return_value=pypi_resp):
            assert fc.fetch_from_pypi("requests", self.REPO) is None

    def test_returns_none_when_pypi_404(self):
        bad = _resp(404)
        with patch.object(fc.requests, "get", return_value=bad):
            assert fc.fetch_from_pypi("nonexistent", self.REPO) is None

    def test_returns_none_on_network_error(self):
        with patch.object(fc.requests, "get", side_effect=_requests.ConnectionError("dns")):
            assert fc.fetch_from_pypi("requests", self.REPO) is None

    def test_uses_first_matching_key(self):
        # `Changelog` should win over `Release Notes` because of catalogue order
        pypi_resp = _resp(
            200,
            json_data={
                "info": {
                    "project_urls": {
                        "Changelog": "https://a.com/CHANGES",
                        "Release Notes": "https://b.com/NOTES",
                        "Homepage": self.REPO,
                    }
                }
            },
        )
        changelog_resp = _resp(200, body="A")
        with patch.object(fc.requests, "get", side_effect=[pypi_resp, changelog_resp]):
            result = fc.fetch_from_pypi("x", self.REPO)
        assert result is not None
        assert result[1] == "https://a.com/CHANGES"

    def test_skips_unreachable_changelog_url(self):
        pypi_resp = _resp(
            200,
            json_data={
                "info": {
                    "project_urls": {
                        "Changelog": "https://broken.example.com/CHANGES",
                        "Homepage": self.REPO,
                    }
                }
            },
        )
        bad_changelog = _resp(500)
        with patch.object(fc.requests, "get", side_effect=[pypi_resp, bad_changelog]):
            assert fc.fetch_from_pypi("x", self.REPO) is None

    def test_returns_none_when_repo_does_not_match(self):
        # Repro from issue #68 T3: `semver` on PyPI is a different project than
        # npm's node-semver — the repo-identity guard must reject it.
        pypi_resp = _resp(
            200,
            json_data={
                "info": {
                    "project_urls": {"Changelog": "https://example.com/CHANGES"},
                    "home_page": "https://github.com/other/unrelated",
                }
            },
        )
        with patch.object(fc.requests, "get", return_value=pypi_resp):
            assert fc.fetch_from_pypi("semver", self.REPO) is None

    def test_project_urls_null_does_not_crash(self):
        pypi_resp = _resp(200, json_data={"info": {"project_urls": None, "home_page": None}})
        with patch.object(fc.requests, "get", return_value=pypi_resp):
            assert fc.fetch_from_pypi("x", self.REPO) is None

    def test_matches_via_home_page_when_project_urls_lacks_key(self):
        pypi_resp = _resp(200, json_data={"info": {"project_urls": {}, "home_page": self.REPO}})
        with patch.object(fc.requests, "get", return_value=pypi_resp):
            # Guard passes (home_page matches) but no changelog key present.
            assert fc.fetch_from_pypi("x", self.REPO) is None


# --------------------------------------------------------------------------- #
# _same_github_repo
# --------------------------------------------------------------------------- #


class TestSameGithubRepo:
    def test_case_insensitive(self):
        assert fc._same_github_repo(
            "https://github.com/Owner/Repo", "https://github.com/owner/repo"
        )

    def test_ignores_git_suffix_and_trailing_slash(self):
        assert fc._same_github_repo(
            "https://github.com/owner/repo.git", "https://github.com/owner/repo/"
        )

    def test_different_repo_returns_false(self):
        assert not fc._same_github_repo(
            "https://github.com/owner/repo", "https://github.com/owner/other"
        )

    def test_non_github_url_returns_false(self):
        assert not fc._same_github_repo(
            "https://gitlab.com/owner/repo", "https://github.com/owner/repo"
        )

    def test_internal_dot_in_repo_name_is_not_truncated(self):
        assert not fc._same_github_repo(
            "https://github.com/webpack/webpack.js.org", "https://github.com/webpack/webpack"
        )
        assert not fc._same_github_repo(
            "https://github.com/owner/foo.bar", "https://github.com/owner/foo.baz"
        )


# --------------------------------------------------------------------------- #
# main() --ecosystem gating
# --------------------------------------------------------------------------- #


class TestMainEcosystem:
    def test_ecosystem_npm_never_requests_pypi(self, monkeypatch):
        monkeypatch.setattr(
            "sys.argv",
            [
                "fetch_changelog.py",
                "semver",
                "https://github.com/npm/node-semver",
                "--ecosystem",
                "npm",
            ],
        )
        with (
            patch.object(fc, "fetch_from_pypi") as mock_pypi,
            patch.object(
                fc,
                "fetch_from_github_releases",
                return_value=("GitHub Releases API", "url", "node-semver notes"),
            ) as mock_releases,
        ):
            fc.main()
        mock_pypi.assert_not_called()
        mock_releases.assert_called_once()

    def test_old_version_alone_is_forwarded(self, monkeypatch):
        monkeypatch.setattr(
            "sys.argv",
            [
                "fetch_changelog.py",
                "somepkg",
                "https://github.com/o/r",
                "2.0.0",
                "--ecosystem",
                "pypi",
            ],
        )
        with (
            patch.object(fc, "fetch_from_pypi", return_value=None),
            patch.object(
                fc,
                "fetch_from_github_releases",
                return_value=("GitHub Releases API", "url", "notes"),
            ) as mock_releases,
        ):
            fc.main()
        mock_releases.assert_called_once_with("https://github.com/o/r", "2.0.0", None)


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
        with patch.object(
            fc.requests,
            "get",
            return_value=_resp(200, json_data=[{"tag_name": "v1", "name": "v1", "body": "x"}]),
        ):
            result = fc.fetch_from_github_releases("git@github.com:owner/repo.git")
        assert result is not None
        assert "owner/repo" in result[1]

    def test_returns_none_on_http_error(self):
        with patch.object(fc.requests, "get", return_value=_resp(500)):
            assert fc.fetch_from_github_releases("https://github.com/o/r") is None

    def test_caps_at_page_limit(self):
        # Every page claims a `next` link exists — the loop must stop at the
        # 10-page hard cap (1000 releases) rather than following it forever.
        page = [{"tag_name": f"v{i}", "name": f"r{i}", "body": "b"} for i in range(100)]
        resp = _resp(200, json_data=page, links={"next": {"url": "https://api.github.com/next"}})
        with patch.object(fc.requests, "get", return_value=resp) as mock_get:
            result = fc.fetch_from_github_releases("https://github.com/o/r")
        assert result is not None
        assert mock_get.call_count == 10
        assert "## r0 " in result[2]
        assert "## r99 " in result[2]

    def test_paginates_and_includes_old_version_found_on_page_2(self):
        page1 = [{"tag_name": "v3.0.0", "name": "r3", "body": "b3"}]
        page2 = [
            {"tag_name": "v2.0.0", "name": "r2", "body": "b2"},
            {"tag_name": "v1.0.0", "name": "r1", "body": "b1"},
        ]
        resp1 = _resp(200, json_data=page1, links={"next": {"url": "https://api.github.com/p2"}})
        resp2 = _resp(200, json_data=page2)  # no `next` — last page anyway
        with patch.object(fc.requests, "get", side_effect=[resp1, resp2]) as mock_get:
            result = fc.fetch_from_github_releases(
                "https://github.com/o/r", old_version="1.0.0", new_version="3.0.0"
            )
        assert result is not None
        assert mock_get.call_count == 2
        _, _, content = result
        assert "## r3 " in content
        assert "## r2 " in content
        assert "## r1 " not in content  # tag == old_version, excluded by (old, new]
        assert "<!-- changelog_coverage: partial -->" not in content

    def test_range_filter_excludes_outside_old_new(self):
        releases = [
            {"tag_name": "v3.0.0", "name": "r3", "body": "b3"},
            {"tag_name": "v2.0.0", "name": "r2", "body": "b2"},
            {"tag_name": "v1.0.0", "name": "r1", "body": "b1"},
        ]
        with patch.object(fc.requests, "get", return_value=_resp(200, json_data=releases)):
            result = fc.fetch_from_github_releases(
                "https://github.com/o/r", old_version="1.0.0", new_version="2.0.0"
            )
        assert result is not None
        _, _, content = result
        assert "## r2 " in content
        assert "## r3 " not in content  # newer than new_version
        assert "## r1 " not in content  # == old_version, excluded by (old, new]
        assert "Covered range: (1.0.0, 2.0.0]" in content

    def test_partial_marker_when_old_version_never_reached(self):
        releases = [{"tag_name": "v3.0.0", "name": "r3", "body": "b3"}]
        with patch.object(fc.requests, "get", return_value=_resp(200, json_data=releases)):
            result = fc.fetch_from_github_releases(
                "https://github.com/o/r", old_version="0.1.0", new_version="3.0.0"
            )
        assert result is not None
        assert "<!-- changelog_coverage: partial -->" in result[2]

    def test_http_error_on_page_2_stops_and_marks_partial(self):
        resp1 = _resp(
            200,
            json_data=[{"tag_name": "v3.0.0", "name": "r3", "body": "b3"}],
            links={"next": {"url": "https://api.github.com/p2"}},
        )
        with patch.object(fc.requests, "get", side_effect=[resp1, _requests.ConnectionError("x")]):
            result = fc.fetch_from_github_releases("https://github.com/o/r")
        assert result is not None
        assert "<!-- changelog_coverage: partial -->" not in result[2]  # no old_version given


# --------------------------------------------------------------------------- #
# _version_key
# --------------------------------------------------------------------------- #


class TestVersionKey:
    def test_parses_v_prefix(self):
        assert fc._version_key("v1.2.3") == (1, 2, 3)

    def test_parses_release_prefix(self):
        assert fc._version_key("release-1.2.3") == (1, 2, 3)
        assert fc._version_key("release/1.2.3") == (1, 2, 3)

    def test_unparseable_tag_returns_empty_tuple(self):
        assert fc._version_key("not-a-version") == ()

    def test_empty_string_returns_empty_tuple(self):
        assert fc._version_key("") == ()


# --------------------------------------------------------------------------- #
# fetch_from_common_files
# --------------------------------------------------------------------------- #


class TestFetchFromCommonFiles:
    def test_returns_first_matching_file(self):
        # First file/branch tried: CHANGELOG.md @ main → return 200
        with patch.object(fc.requests, "get", return_value=_resp(200, body="# Changelog\n")):
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
        with patch.object(fc.requests, "get", side_effect=[_resp(404), _resp(200)]):
            tag = fc._resolve_tag("o", "r", "1.2.3")
        assert tag == "1.2.3"

    def test_returns_none_when_no_tag_resolves(self):
        with patch.object(fc.requests, "get", return_value=_resp(404)):
            assert fc._resolve_tag("o", "r", "1.2.3") is None

    def test_swallows_request_exception(self):
        with patch.object(fc.requests, "get", side_effect=_requests.ConnectionError("dns")):
            assert fc._resolve_tag("o", "r", "1.2.3") is None


# --------------------------------------------------------------------------- #
# fetch_from_github_compare
# --------------------------------------------------------------------------- #


class TestFetchFromGithubCompare:
    def test_returns_commit_list(self):
        # _resolve_tag: 2 calls (one per version), each succeeds on first try
        tag_resp = _resp(200)
        compare = _resp(
            200,
            json_data={
                "commits": [
                    {
                        "sha": "abc123def456",
                        "commit": {
                            "message": "fix: thing\n\nmore detail",
                            "author": {"name": "Alice"},
                        },
                    }
                ]
            },
        )
        with patch.object(fc.requests, "get", side_effect=[tag_resp, tag_resp, compare]):
            result = fc.fetch_from_github_compare("https://github.com/o/r", "1.0.0", "1.1.0")
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
            result = fc.fetch_from_github_compare("https://github.com/o/r", "1.0", "1.1")
        assert result is None

    def test_returns_none_for_non_github(self):
        assert fc.fetch_from_github_compare("https://gitlab.com/o/r", "1", "2") is None

    def test_returns_none_when_no_commits(self):
        tag = _resp(200)
        compare = _resp(200, json_data={"commits": []})
        with patch.object(fc.requests, "get", side_effect=[tag, tag, compare]):
            result = fc.fetch_from_github_compare("https://github.com/o/r", "1.0", "1.1")
        assert result is None


# --------------------------------------------------------------------------- #
# fetch_from_github_tag_annotation
# --------------------------------------------------------------------------- #


class TestFetchFromGithubTagAnnotation:
    def test_returns_annotation_message(self):
        # 1) resolve tag (200), 2) ref lookup → object{type=tag,url=...}, 3) tag obj fetch
        resolve = _resp(200)
        ref = _resp(
            200, json_data={"object": {"type": "tag", "url": "https://api.github.com/tag-obj"}}
        )
        tag_obj = _resp(200, json_data={"message": "Release notes for v1\n"})
        with patch.object(fc.requests, "get", side_effect=[resolve, ref, tag_obj]):
            result = fc.fetch_from_github_tag_annotation("https://github.com/o/r", "1.0.0")
        assert result is not None
        label, url, content = result
        assert label == "GitHub tag annotation"
        assert "Release notes for v1" in content

    def test_returns_none_for_lightweight_tag(self):
        # `object.type` is "commit" not "tag" → lightweight tag, no annotation
        resolve = _resp(200)
        ref = _resp(200, json_data={"object": {"type": "commit"}})
        with patch.object(fc.requests, "get", side_effect=[resolve, ref]):
            assert fc.fetch_from_github_tag_annotation("https://github.com/o/r", "1.0") is None

    def test_returns_none_when_tag_cant_resolve(self):
        with patch.object(fc.requests, "get", return_value=_resp(404)):
            assert fc.fetch_from_github_tag_annotation("https://github.com/o/r", "1.0") is None
