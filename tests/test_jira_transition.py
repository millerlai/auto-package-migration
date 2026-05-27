"""Tests for package-upgrade/scripts/common/jira_transition.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests as _requests

import jira_transition


def _resp(status: int = 200, json_data=None, text: str = "") -> MagicMock:
    m = MagicMock()
    m.status_code = status
    m.text = text
    if json_data is not None:
        m.json.return_value = json_data
    else:
        m.json.side_effect = ValueError("no json")
    if status >= 400 and status not in (400, 401, 403, 404):
        m.raise_for_status.side_effect = _requests.HTTPError(f"HTTP {status}")
    return m


@pytest.fixture
def env_auth(monkeypatch):
    monkeypatch.setenv("ATLASSIAN_EMAIL", "me@x")
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "tok")


# --------------------------------------------------------------------------- #
# _auth
# --------------------------------------------------------------------------- #

class TestAuth:
    def test_returns_pair_when_env_set(self, env_auth):
        assert jira_transition._auth() == ("me@x", "tok")

    def test_exits_when_env_missing(self, monkeypatch):
        monkeypatch.delenv("ATLASSIAN_EMAIL", raising=False)
        monkeypatch.delenv("ATLASSIAN_API_TOKEN", raising=False)
        with pytest.raises(SystemExit) as exc:
            jira_transition._auth()
        assert exc.value.code == 2

    def test_exits_when_only_email_set(self, monkeypatch):
        monkeypatch.setenv("ATLASSIAN_EMAIL", "x")
        monkeypatch.delenv("ATLASSIAN_API_TOKEN", raising=False)
        with pytest.raises(SystemExit):
            jira_transition._auth()


# --------------------------------------------------------------------------- #
# _check — status code → exception mapping
# --------------------------------------------------------------------------- #

class TestCheck:
    def test_401(self):
        with pytest.raises(RuntimeError, match="401"):
            jira_transition._check(_resp(401), "K-1")

    def test_403(self):
        with pytest.raises(RuntimeError, match="403"):
            jira_transition._check(_resp(403), "K-1")

    def test_404(self):
        with pytest.raises(RuntimeError, match="404"):
            jira_transition._check(_resp(404), "K-1")

    def test_500_raises_via_raise_for_status(self):
        with pytest.raises(_requests.HTTPError):
            jira_transition._check(_resp(500), "K-1")

    def test_200_returns_silently(self):
        jira_transition._check(_resp(200), "K-1")  # no exception


# --------------------------------------------------------------------------- #
# list_transitions
# --------------------------------------------------------------------------- #

class TestListTransitions:
    def test_returns_normalized_list(self, env_auth):
        payload = {"transitions": [
            {
                "id": "11",
                "name": "In Progress",
                "to": {"name": "In Progress",
                       "statusCategory": {"key": "indeterminate"}},
                "hasScreen": False,
            },
            {
                "id": "21",
                "name": "Done",
                "to": {"name": "Done", "statusCategory": {"key": "done"}},
                "hasScreen": True,
            },
        ]}
        with patch.object(jira_transition.requests, "get",
                          return_value=_resp(200, payload)):
            result = jira_transition.list_transitions("s.atlassian.net", "K-1")
        assert result["issue"] == "K-1"
        assert len(result["transitions"]) == 2
        assert result["transitions"][0]["id"] == "11"
        assert result["transitions"][0]["to_status"] == "In Progress"
        assert result["transitions"][0]["to_category"] == "indeterminate"
        assert result["transitions"][1]["has_screen"] is True

    def test_empty_transitions(self, env_auth):
        with patch.object(jira_transition.requests, "get",
                          return_value=_resp(200, {"transitions": []})):
            result = jira_transition.list_transitions("s", "K-1")
        assert result["transitions"] == []

    def test_propagates_404(self, env_auth):
        with patch.object(jira_transition.requests, "get",
                          return_value=_resp(404)):
            with pytest.raises(RuntimeError, match="404"):
                jira_transition.list_transitions("s", "K-1")


# --------------------------------------------------------------------------- #
# apply_transition
# --------------------------------------------------------------------------- #

class TestApplyTransition:
    def test_simple_apply_returns_status_applied(self, env_auth):
        with patch.object(jira_transition.requests, "post",
                          return_value=_resp(204)):
            result = jira_transition.apply_transition(
                "s.atlassian.net", "K-1", "11", None
            )
        assert result["status"] == "applied"
        assert result["transition_id"] == "11"
        assert result["resolution"] is None
        assert result["issue"] == "K-1"

    def test_apply_with_resolution(self, env_auth):
        with patch.object(jira_transition.requests, "post",
                          return_value=_resp(204)) as mock_post:
            result = jira_transition.apply_transition("s", "K-1", "21", "Done")
            _, kwargs = mock_post.call_args
            payload = kwargs["json"]
            assert payload["fields"]["resolution"]["name"] == "Done"
        assert result["resolution"] == "Done"

    def test_400_surfaces_workflow_error(self, env_auth):
        body = {"errors": {"resolution": "Field is required"}}
        with patch.object(jira_transition.requests, "post",
                          return_value=_resp(400, body)):
            with pytest.raises(RuntimeError) as exc:
                jira_transition.apply_transition("s", "K-1", "11", None)
        assert "400" in str(exc.value)
        assert "resolution" in str(exc.value)

    def test_400_non_json_body_still_handled(self, env_auth):
        # response.json() raises ValueError → falls back to raw text
        resp = _resp(400, text="<html>oops</html>")
        with patch.object(jira_transition.requests, "post", return_value=resp):
            with pytest.raises(RuntimeError) as exc:
                jira_transition.apply_transition("s", "K-1", "11", None)
        assert "400" in str(exc.value)

    def test_401_raises_runtime_error(self, env_auth):
        with patch.object(jira_transition.requests, "post",
                          return_value=_resp(401)):
            with pytest.raises(RuntimeError, match="401"):
                jira_transition.apply_transition("s", "K-1", "11", None)

    def test_uses_basic_auth(self, env_auth):
        with patch.object(jira_transition.requests, "post",
                          return_value=_resp(204)) as mock_post:
            jira_transition.apply_transition("s", "K-1", "11", None)
            _, kwargs = mock_post.call_args
            assert kwargs["auth"] == ("me@x", "tok")

    def test_payload_shape_without_resolution(self, env_auth):
        with patch.object(jira_transition.requests, "post",
                          return_value=_resp(204)) as mock_post:
            jira_transition.apply_transition("s", "K-1", "11", None)
            _, kwargs = mock_post.call_args
            assert kwargs["json"] == {"transition": {"id": "11"}}
