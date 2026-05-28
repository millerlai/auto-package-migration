"""Tests for package-upgrade/scripts/common/jira_comment.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests as _requests

import jira_comment


def _resp(status: int = 200, json_data=None) -> MagicMock:
    m = MagicMock()
    m.status_code = status
    m.json.return_value = json_data or {}
    if status >= 400:
        m.raise_for_status.side_effect = _requests.HTTPError(f"HTTP {status}")
    return m


# --------------------------------------------------------------------------- #
# markdown_to_adf
# --------------------------------------------------------------------------- #


class TestMarkdownToAdf:
    def test_single_paragraph(self):
        doc = jira_comment.markdown_to_adf("hello world")
        assert doc["type"] == "doc"
        assert doc["version"] == 1
        assert len(doc["content"]) == 1
        assert doc["content"][0]["type"] == "paragraph"
        assert doc["content"][0]["content"][0]["text"] == "hello world"

    def test_two_blank_line_separated_blocks(self):
        doc = jira_comment.markdown_to_adf("para1\n\npara2")
        assert len(doc["content"]) == 2
        texts = [b["content"][0]["text"] for b in doc["content"]]
        assert texts == ["para1", "para2"]

    def test_empty_blocks_are_skipped(self):
        # "\n\n\n\n" → blocks: "", "", "" → all skipped
        doc = jira_comment.markdown_to_adf("\n\n\n\n")
        # Since the original markdown is non-empty, the fallback paragraph preserves it
        assert len(doc["content"]) == 1
        assert doc["content"][0]["content"][0]["text"] == "\n\n\n\n"

    def test_empty_string_yields_fallback(self):
        doc = jira_comment.markdown_to_adf("")
        # `md or " "` → " " when md is empty
        assert len(doc["content"]) == 1
        assert doc["content"][0]["content"][0]["text"] == " "

    def test_crlf_normalized_to_lf(self):
        doc = jira_comment.markdown_to_adf("line1\r\nline2")
        assert doc["content"][0]["content"][0]["text"] == "line1\nline2"

    def test_trailing_whitespace_stripped(self):
        doc = jira_comment.markdown_to_adf("hello   \n\nworld   ")
        texts = [b["content"][0]["text"] for b in doc["content"]]
        assert texts == ["hello", "world"]


# --------------------------------------------------------------------------- #
# post_comment — mock requests
# --------------------------------------------------------------------------- #


class TestPostComment:
    def test_returns_normalized_dict_on_success(self):
        payload = {
            "id": "12345",
            "created": "2024-01-01",
            "author": {"displayName": "Alice"},
        }
        with patch.object(jira_comment.requests, "post", return_value=_resp(201, payload)):
            result = jira_comment.post_comment("s.atlassian.net", "K-1", "hello", "e@x", "tok")
        assert result["id"] == "12345"
        assert result["created"] == "2024-01-01"
        assert result["author"] == "Alice"
        assert "focusedCommentId=12345" in result["url"]

    def test_401_raises_runtime_error(self):
        with patch.object(jira_comment.requests, "post", return_value=_resp(401)):
            with pytest.raises(RuntimeError, match="401"):
                jira_comment.post_comment("s", "K-1", "x", "e", "t")

    def test_403_raises_runtime_error(self):
        with patch.object(jira_comment.requests, "post", return_value=_resp(403)):
            with pytest.raises(RuntimeError, match="403"):
                jira_comment.post_comment("s", "K-1", "x", "e", "t")

    def test_404_raises_runtime_error(self):
        with patch.object(jira_comment.requests, "post", return_value=_resp(404)):
            with pytest.raises(RuntimeError, match="404"):
                jira_comment.post_comment("s", "K-1", "x", "e", "t")

    def test_sends_adf_body(self):
        with patch.object(
            jira_comment.requests, "post", return_value=_resp(201, {"id": "1"})
        ) as mock_post:
            jira_comment.post_comment("s", "K", "hello world", "e", "t")
            _, kwargs = mock_post.call_args
            payload = kwargs["json"]
            assert payload["body"]["type"] == "doc"
            assert payload["body"]["version"] == 1
            assert payload["body"]["content"][0]["content"][0]["text"] == "hello world"

    def test_uses_basic_auth(self):
        with patch.object(
            jira_comment.requests, "post", return_value=_resp(201, {"id": "1"})
        ) as mock_post:
            jira_comment.post_comment("s", "K", "x", "alice@x", "tok")
            _, kwargs = mock_post.call_args
            assert kwargs["auth"] == ("alice@x", "tok")

    def test_anonymous_author_handled(self):
        # author missing → result["author"] is None (gracefully)
        with patch.object(
            jira_comment.requests, "post", return_value=_resp(201, {"id": "1", "author": None})
        ):
            result = jira_comment.post_comment("s", "K", "x", "e", "t")
        assert result["author"] is None
