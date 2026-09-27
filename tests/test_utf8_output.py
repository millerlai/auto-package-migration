"""Regression tests for T12: helpers must survive cp950 (non-UTF-8) consoles.

Each script's ``main()`` is called in-process with ``sys.stdout`` swapped for a
``cp950``-encoded ``io.TextIOWrapper`` (simulating a Windows console pipe) and
``requests`` mocked, feeding content that contains the sparkles emoji (U+2728,
outside cp950). Before the fix each of these raised ``UnicodeEncodeError``.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import dependabot_fetch as df
import fetch_changelog as fc
import grant_permissions as gp
import jira_comment as jc
import jira_fetch as jf
import jira_transition as jt

SPARKLE = "✨"


def _cp950_stdout() -> io.TextIOWrapper:
    """A stdout-like TextIOWrapper encoded as cp950, the way a Windows zh-TW
    console pipe presents itself when PYTHONUTF8 is off."""
    return io.TextIOWrapper(io.BytesIO(), encoding="cp950", write_through=True)


def _resp(status: int = 200, json_data=None, text: str = "") -> MagicMock:
    m = MagicMock()
    m.status_code = status
    m.text = text
    m.ok = status < 400
    if json_data is not None:
        m.json.return_value = json_data
    if status >= 400:
        import requests

        m.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status}")
    else:
        m.raise_for_status.return_value = None
    m.links = {}
    return m


class TestFetchChangelogUtf8:
    def test_main_survives_cp950_stdout(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["fetch_changelog.py", "somepkg", "https://github.com/o/r"])
        pypi_resp = _resp(
            200,
            json_data={
                "info": {
                    "project_urls": {
                        "Changelog": "https://example.com/CHANGES",
                        "Homepage": "https://github.com/o/r",
                    }
                }
            },
        )
        changelog_resp = _resp(200, text=f"# Changelog\n{SPARKLE} Features\n")
        stdout = _cp950_stdout()
        with patch.object(fc.requests, "get", side_effect=[pypi_resp, changelog_resp]):
            with patch("sys.stdout", stdout):
                fc.main()
        stdout.flush()
        written = stdout.buffer.getvalue().decode("utf-8")
        assert "Features" in written


class TestJiraFetchUtf8:
    def test_main_survives_cp950_stdout(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jira_fetch.py", "example.atlassian.net", "KEY-1"])
        monkeypatch.setenv("ATLASSIAN_EMAIL", "a@example.com")
        monkeypatch.setenv("ATLASSIAN_API_TOKEN", "tok")
        issue = {
            "key": "KEY-1",
            "self": "https://example.atlassian.net/rest/api/3/issue/10000",
            "fields": {
                "summary": f"{SPARKLE} Fixed",
                "status": {"name": "Done"},
                "issuetype": {"name": "Bug"},
                "priority": {"name": "High"},
                "labels": [],
                "description": None,
            },
        }
        stdout = _cp950_stdout()
        with patch.object(jf.requests, "get", return_value=_resp(200, json_data=issue)):
            with patch("sys.stdout", stdout):
                jf.main()
        stdout.flush()
        written = stdout.buffer.getvalue().decode("utf-8")
        assert "Fixed" in written


class TestJiraCommentUtf8:
    def test_main_survives_cp950_stdout(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jira_comment.py", "example.atlassian.net", "KEY-1", "-"])
        monkeypatch.setenv("ATLASSIAN_EMAIL", "a@example.com")
        monkeypatch.setenv("ATLASSIAN_API_TOKEN", "tok")
        monkeypatch.setattr("sys.stdin", io.StringIO("body text"))
        created = {
            "id": "1",
            "created": "2026-01-01",
            "author": {"displayName": f"{SPARKLE} Bot"},
        }
        stdout = _cp950_stdout()
        with patch.object(jc.requests, "post", return_value=_resp(200, json_data=created)):
            with patch("sys.stdout", stdout):
                jc.main()
        stdout.flush()
        written = stdout.buffer.getvalue().decode("utf-8")
        assert "Bot" in written


class TestJiraTransitionUtf8:
    def test_main_survives_cp950_stdout(self, monkeypatch):
        monkeypatch.setattr(
            "sys.argv", ["jira_transition.py", "list", "example.atlassian.net", "KEY-1"]
        )
        monkeypatch.setenv("ATLASSIAN_EMAIL", "a@example.com")
        monkeypatch.setenv("ATLASSIAN_API_TOKEN", "tok")
        data = {
            "transitions": [
                {
                    "id": "31",
                    "name": f"{SPARKLE} Done",
                    "to": {"name": "Done", "statusCategory": {"key": "done"}},
                    "hasScreen": False,
                }
            ]
        }
        stdout = _cp950_stdout()
        with patch.object(jt.requests, "get", return_value=_resp(200, json_data=data)):
            with patch("sys.stdout", stdout):
                jt.main()
        stdout.flush()
        written = stdout.buffer.getvalue().decode("utf-8")
        assert "Done" in written


class TestDependabotFetchUtf8:
    def test_main_survives_cp950_stdout(self, monkeypatch):
        monkeypatch.setattr(df.shutil, "which", lambda _: None)
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        alerts = [
            {
                "number": 1,
                "dependency": {
                    "package": {"ecosystem": "pip", "name": "requests"},
                    "manifest_path": "requirements.txt",
                },
                "security_advisory": {
                    "ghsa_id": "GHSA-x",
                    "cve_id": "CVE-2024-1",
                    "severity": "high",
                    "summary": f"{SPARKLE} advisory",
                },
                "security_vulnerability": {
                    "severity": "high",
                    "vulnerable_version_range": "<2",
                    "first_patched_version": {"identifier": "2.0.0"},
                },
                "html_url": "https://github.com/o/r/security/dependabot/1",
            }
        ]
        resp = _resp(200, json_data=alerts)
        resp.links = {}
        stdout = _cp950_stdout()
        with patch("requests.get", return_value=resp):
            with patch("sys.stdout", stdout):
                df.main(["github.com", "o", "r"])
        stdout.flush()
        written = stdout.buffer.getvalue().decode("utf-8")
        assert "advisory" in written


class TestGrantPermissionsUtf8:
    def test_load_settings_reads_chinese_utf8(self, tmp_path: Path):
        f = tmp_path / "settings.json"
        f.write_text(json.dumps({"note": "中文注釋"}), encoding="utf-8")
        data = gp.load_settings(f)
        assert data["note"] == "中文注釋"

    def test_load_settings_reads_with_explicit_utf8(self, tmp_path: Path, monkeypatch):
        # Locale-independent: assert the encoding kwarg itself, rather than
        # relying on the host's default encoding to differ from UTF-8.
        f = tmp_path / "settings.json"
        f.write_text("{}", encoding="utf-8")
        calls = []
        orig = Path.read_text

        def spy(self, *a, **kw):
            calls.append(kw)
            return orig(self, *a, **kw)

        monkeypatch.setattr(Path, "read_text", spy)
        gp.load_settings(f)
        assert calls and calls[-1].get("encoding") == "utf-8"

    def test_load_settings_catches_unicode_decode_error(self, tmp_path: Path, monkeypatch, capsys):
        f = tmp_path / "settings.json"
        f.write_text("{}", encoding="utf-8")

        def bad_read_text(self, *a, **kw):
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

        monkeypatch.setattr(Path, "read_text", bad_read_text)
        with pytest.raises(SystemExit) as exc:
            gp.load_settings(f)
        assert exc.value.code == 2
        assert "not valid JSON" in capsys.readouterr().err

    def test_main_writes_with_explicit_utf8(self, tmp_path: Path, monkeypatch):
        target = tmp_path / "settings.json"
        calls = []
        orig = Path.write_text

        def spy(self, *a, **kw):
            calls.append(kw)
            return orig(self, *a, **kw)

        monkeypatch.setattr(Path, "write_text", spy)
        monkeypatch.setattr(
            "sys.argv",
            ["grant_permissions", "--settings", str(target), "--mode", "project"],
        )
        rc = gp.main()
        assert rc == 0
        assert calls and calls[-1].get("encoding") == "utf-8"

    def test_main_round_trips_chinese_settings(self, tmp_path: Path, monkeypatch):
        target = tmp_path / "settings.json"
        target.write_text(
            json.dumps({"note": "中文", "permissions": {"allow": []}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "sys.argv",
            ["grant_permissions", "--settings", str(target), "--mode", "project"],
        )
        rc = gp.main()
        assert rc == 0
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["note"] == "中文"
