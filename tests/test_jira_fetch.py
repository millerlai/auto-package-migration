"""Tests for package-upgrade/scripts/jira_fetch.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests as _requests

import jira_fetch


def _resp(status: int = 200, json_data=None) -> MagicMock:
    m = MagicMock()
    m.status_code = status
    m.json.return_value = json_data or {}
    if status >= 400:
        m.raise_for_status.side_effect = _requests.HTTPError(f"HTTP {status}")
    return m


# --------------------------------------------------------------------------- #
# adf_to_text
# --------------------------------------------------------------------------- #

class TestAdfToText:
    def test_text_node(self):
        assert jira_fetch.adf_to_text({"type": "text", "text": "hello"}) == "hello"

    def test_paragraph_appends_newline(self):
        doc = {"type": "paragraph", "content": [{"type": "text", "text": "hi"}]}
        assert jira_fetch.adf_to_text(doc) == "hi\n"

    def test_hard_break_becomes_newline(self):
        assert jira_fetch.adf_to_text({"type": "hardBreak"}) == "\n"

    def test_heading_appends_newline(self):
        doc = {"type": "heading", "content": [{"type": "text", "text": "Title"}]}
        assert jira_fetch.adf_to_text(doc) == "Title\n"

    def test_bullet_list_passes_through(self):
        doc = {
            "type": "bulletList",
            "content": [
                {"type": "listItem", "content": [
                    {"type": "text", "text": "a"}]},
                {"type": "listItem", "content": [
                    {"type": "text", "text": "b"}]},
            ],
        }
        out = jira_fetch.adf_to_text(doc)
        assert "a" in out and "b" in out

    def test_nested_document(self):
        doc = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [
                    {"type": "text", "text": "p1"}]},
                {"type": "paragraph", "content": [
                    {"type": "text", "text": "p2"}]},
            ],
        }
        out = jira_fetch.adf_to_text(doc)
        assert out == "p1\np2\n"

    def test_none_returns_empty_string(self):
        assert jira_fetch.adf_to_text(None) == ""

    def test_string_passes_through(self):
        assert jira_fetch.adf_to_text("plain") == "plain"

    def test_list_of_nodes(self):
        nodes = [
            {"type": "text", "text": "a"},
            {"type": "text", "text": "b"},
        ]
        assert jira_fetch.adf_to_text(nodes) == "ab"

    def test_unknown_int_returns_empty(self):
        # neither str nor list nor dict → ""
        assert jira_fetch.adf_to_text(42) == ""


# --------------------------------------------------------------------------- #
# normalize
# --------------------------------------------------------------------------- #

class TestNormalize:
    def test_extracts_basic_fields(self):
        raw = {
            "key": "V1E-1",
            "self": "https://example.atlassian.net/rest/api/3/issue/V1E-1",
            "fields": {
                "summary": "Upgrade lodash",
                "status": {"name": "In Progress"},
                "issuetype": {"name": "Task"},
                "priority": {"name": "Medium"},
                "labels": ["security", "cve"],
                "description": "Please bump",
            },
        }
        result = jira_fetch.normalize(raw)
        assert result["key"] == "V1E-1"
        assert result["summary"] == "Upgrade lodash"
        assert result["status"] == "In Progress"
        assert result["issue_type"] == "Task"
        assert result["priority"] == "Medium"
        assert result["labels"] == ["security", "cve"]
        assert result["description"] == "Please bump"
        assert "example.atlassian.net/browse/V1E-1" in result["url"]

    def test_handles_adf_description(self):
        raw = {
            "key": "X-1",
            "self": "https://s.atlassian.net/rest/api/3/issue/X-1",
            "fields": {
                "summary": "s",
                "description": {
                    "type": "doc",
                    "content": [{"type": "paragraph", "content": [
                        {"type": "text", "text": "ADF body"}
                    ]}],
                },
            },
        }
        result = jira_fetch.normalize(raw)
        assert "ADF body" in result["description"]

    def test_falls_back_to_rendered_description(self):
        raw = {
            "key": "X-1",
            "self": "https://s.atlassian.net/rest/api/3/issue/X-1",
            "fields": {"summary": "s", "description": None},
            "renderedFields": {"description": "<p>rendered</p>"},
        }
        result = jira_fetch.normalize(raw)
        assert result["description"] == "<p>rendered</p>"

    def test_normalizes_comments(self):
        raw = {
            "key": "X-1",
            "self": "https://s.atlassian.net/rest/api/3/issue/X-1",
            "fields": {
                "summary": "s",
                "comment": {
                    "comments": [
                        {
                            "author": {"displayName": "Alice"},
                            "created": "2024-01-01",
                            "body": {"type": "doc", "content": [
                                {"type": "paragraph", "content": [
                                    {"type": "text", "text": "Looks good"}
                                ]}
                            ]},
                        },
                        {
                            "author": {"displayName": "Bob"},
                            "created": "2024-01-02",
                            "body": "Plain text comment",
                        },
                    ]
                },
            },
        }
        result = jira_fetch.normalize(raw)
        assert len(result["comments"]) == 2
        assert result["comments"][0]["author"] == "Alice"
        assert "Looks good" in result["comments"][0]["body"]
        assert result["comments"][1]["author"] == "Bob"
        assert result["comments"][1]["body"] == "Plain text comment"

    def test_missing_fields_default_to_empty(self):
        raw = {"key": "X", "self": "https://s.atlassian.net/rest/api/3/issue/X",
               "fields": {}}
        result = jira_fetch.normalize(raw)
        assert result["summary"] == ""
        assert result["status"] == ""
        assert result["issue_type"] == ""
        assert result["priority"] == ""
        assert result["labels"] == []
        assert result["comments"] == []

    def test_anonymous_comment_author(self):
        raw = {
            "key": "X", "self": "https://s.atlassian.net/rest/api/3/issue/X",
            "fields": {"summary": "s", "comment": {"comments": [
                {"author": None, "body": "x"}
            ]}},
        }
        result = jira_fetch.normalize(raw)
        assert result["comments"][0]["author"] == "unknown"

    def test_no_self_no_url(self):
        raw = {"key": "X", "fields": {"summary": "s"}}
        result = jira_fetch.normalize(raw)
        assert result["url"] is None


# --------------------------------------------------------------------------- #
# fetch_issue — mock requests
# --------------------------------------------------------------------------- #

class TestFetchIssue:
    def test_returns_json_on_200(self):
        payload = {"key": "X-1", "fields": {"summary": "s"}}
        with patch.object(jira_fetch.requests, "get", return_value=_resp(200, payload)):
            result = jira_fetch.fetch_issue("s.atlassian.net", "X-1", "e", "t")
        assert result == payload

    def test_401_raises_runtime_error(self):
        with patch.object(jira_fetch.requests, "get", return_value=_resp(401)):
            with pytest.raises(RuntimeError, match="401"):
                jira_fetch.fetch_issue("s.atlassian.net", "X-1", "e", "t")

    def test_403_raises_runtime_error(self):
        with patch.object(jira_fetch.requests, "get", return_value=_resp(403)):
            with pytest.raises(RuntimeError, match="403"):
                jira_fetch.fetch_issue("s", "K-1", "e", "t")

    def test_404_raises_runtime_error(self):
        with patch.object(jira_fetch.requests, "get", return_value=_resp(404)):
            with pytest.raises(RuntimeError, match="404"):
                jira_fetch.fetch_issue("s", "K-1", "e", "t")

    def test_other_5xx_raises_http_error(self):
        with patch.object(jira_fetch.requests, "get", return_value=_resp(500)):
            with pytest.raises(_requests.HTTPError):
                jira_fetch.fetch_issue("s", "K-1", "e", "t")

    def test_uses_basic_auth(self):
        with patch.object(jira_fetch.requests, "get",
                          return_value=_resp(200, {})) as mock_get:
            jira_fetch.fetch_issue("s.atlassian.net", "K-1", "me@x", "tok")
            _, kwargs = mock_get.call_args
            assert kwargs["auth"] == ("me@x", "tok")
