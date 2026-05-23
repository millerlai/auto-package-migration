"""Tests for grant_permissions.py at the repo root."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import grant_permissions as gp


# --------------------------------------------------------------------------- #
# resolve_gh_entries
# --------------------------------------------------------------------------- #

class TestResolveGhEntries:
    def test_none_returns_empty(self):
        assert gp.resolve_gh_entries("none") == []

    def test_default_treated_as_none(self):
        assert gp.resolve_gh_entries("") == []

    def test_all_returns_every_value(self):
        result = gp.resolve_gh_entries("all")
        assert set(result) == set(gp.GH_ALLOW.values())

    def test_single_known_key(self):
        result = gp.resolve_gh_entries("pr_create")
        assert result == [gp.GH_ALLOW["pr_create"]]

    def test_multiple_keys_preserve_order(self):
        result = gp.resolve_gh_entries("auth_status,pr_view")
        assert result == [gp.GH_ALLOW["auth_status"], gp.GH_ALLOW["pr_view"]]

    def test_strips_whitespace(self):
        result = gp.resolve_gh_entries(" pr_create , api ")
        assert result == [gp.GH_ALLOW["pr_create"], gp.GH_ALLOW["api"]]

    def test_unknown_key_exits(self, capsys):
        with pytest.raises(SystemExit) as exc:
            gp.resolve_gh_entries("not_a_key")
        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert "unknown" in err
        assert "not_a_key" in err

    def test_mixed_known_and_unknown_exits(self):
        with pytest.raises(SystemExit):
            gp.resolve_gh_entries("pr_create,bogus_key")


# --------------------------------------------------------------------------- #
# desired_entries
# --------------------------------------------------------------------------- #

class TestDesiredEntries:
    def test_global_mode_includes_global_script_paths(self):
        allow, ask = gp.desired_entries("global", "none")
        # one of the script paths should mention `~/.claude`
        assert any("~/.claude" in entry for entry in allow)
        assert all(".claude/skills/package-upgrade" not in e
                   or "~/.claude" in e for e in allow if "package-upgrade" in e)

    def test_project_mode_includes_local_script_paths(self):
        allow, ask = gp.desired_entries("project", "none")
        # project mode uses relative `.claude/...` (without leading ~)
        local_paths = [e for e in allow if "package-upgrade/scripts" in e]
        assert local_paths
        # None of the project-mode entries should have the leading ~
        assert all("~/.claude" not in e for e in local_paths)

    def test_common_allow_included(self):
        allow, _ = gp.desired_entries("global", "none")
        # COMMON_ALLOW contents must show up
        assert "Bash(git status:*)" in allow
        assert "WebSearch" in allow

    def test_common_ask_included(self):
        _, ask = gp.desired_entries("global", "none")
        assert "Bash(git push:*)" in ask

    def test_gh_entries_none_by_default(self):
        allow, _ = gp.desired_entries("global", "none")
        for gh_entry in gp.GH_ALLOW.values():
            assert gh_entry not in allow

    def test_gh_entries_all_includes_them(self):
        allow, _ = gp.desired_entries("global", "all")
        for gh_entry in gp.GH_ALLOW.values():
            assert gh_entry in allow


# --------------------------------------------------------------------------- #
# merge — idempotency + ordering
# --------------------------------------------------------------------------- #

class TestMerge:
    def test_adds_new_items(self):
        existing = ["a", "b"]
        new, added = gp.merge(existing, ["c", "d"])
        assert new == ["a", "b", "c", "d"]
        assert added == ["c", "d"]

    def test_skips_duplicates(self):
        existing = ["a", "b"]
        _, added = gp.merge(existing, ["a", "c"])
        assert added == ["c"]
        assert existing == ["a", "b", "c"]

    def test_empty_additions_no_change(self):
        existing = ["a"]
        _, added = gp.merge(existing, [])
        assert added == []
        assert existing == ["a"]

    def test_all_duplicates_returns_empty_added(self):
        existing = ["a", "b"]
        _, added = gp.merge(existing, ["a", "b"])
        assert added == []

    def test_preserves_order_of_additions(self):
        existing: list = []
        _, added = gp.merge(existing, ["c", "a", "b"])
        assert added == ["c", "a", "b"]
        assert existing == ["c", "a", "b"]

    def test_dedupes_within_additions(self):
        existing: list = []
        _, added = gp.merge(existing, ["a", "a", "b"])
        # `seen` tracks both existing and previously-added items in the loop
        assert added == ["a", "b"]


# --------------------------------------------------------------------------- #
# load_settings
# --------------------------------------------------------------------------- #

class TestLoadSettings:
    def test_returns_empty_dict_when_missing(self, tmp_path: Path):
        assert gp.load_settings(tmp_path / "nope.json") == {}

    def test_loads_existing_json(self, tmp_path: Path):
        f = tmp_path / "settings.json"
        f.write_text('{"permissions": {"allow": ["x"]}}')
        result = gp.load_settings(f)
        assert result == {"permissions": {"allow": ["x"]}}

    def test_exits_on_invalid_json(self, tmp_path: Path, capsys):
        f = tmp_path / "settings.json"
        f.write_text("{not valid")
        with pytest.raises(SystemExit) as exc:
            gp.load_settings(f)
        assert exc.value.code == 2
        assert "not valid JSON" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# main — full integration on a tmpfile
# --------------------------------------------------------------------------- #

class TestMain:
    def test_creates_settings_file_when_missing(self, tmp_path: Path, monkeypatch):
        target = tmp_path / "settings.json"
        monkeypatch.setattr(
            "sys.argv",
            ["grant_permissions", "--settings", str(target), "--mode", "global"],
        )
        rc = gp.main()
        assert rc == 0
        assert target.exists()
        data = json.loads(target.read_text())
        assert "permissions" in data
        assert "allow" in data["permissions"]
        assert "Bash(git status:*)" in data["permissions"]["allow"]

    def test_dry_run_does_not_write(self, tmp_path: Path, monkeypatch):
        target = tmp_path / "settings.json"
        monkeypatch.setattr(
            "sys.argv",
            ["grant_permissions", "--settings", str(target),
             "--mode", "global", "--dry-run"],
        )
        rc = gp.main()
        assert rc == 0
        assert not target.exists()

    def test_idempotent_second_run_adds_nothing(self, tmp_path: Path, monkeypatch, capsys):
        target = tmp_path / "settings.json"
        argv = ["grant_permissions", "--settings", str(target), "--mode", "global"]
        monkeypatch.setattr("sys.argv", argv)
        gp.main()
        capsys.readouterr()  # clear
        gp.main()
        out = capsys.readouterr().out
        assert "Nothing to add" in out

    def test_gh_all_included_in_output(self, tmp_path: Path, monkeypatch):
        target = tmp_path / "settings.json"
        monkeypatch.setattr(
            "sys.argv",
            ["grant_permissions", "--settings", str(target),
             "--mode", "global", "--gh-entries", "all"],
        )
        gp.main()
        data = json.loads(target.read_text())
        allow = data["permissions"]["allow"]
        for gh_value in gp.GH_ALLOW.values():
            assert gh_value in allow

    def test_unknown_gh_key_exits(self, tmp_path: Path, monkeypatch):
        target = tmp_path / "settings.json"
        monkeypatch.setattr(
            "sys.argv",
            ["grant_permissions", "--settings", str(target),
             "--mode", "global", "--gh-entries", "not_a_real_key"],
        )
        with pytest.raises(SystemExit) as exc:
            gp.main()
        assert exc.value.code == 2

    def test_preserves_existing_unrelated_keys(self, tmp_path: Path, monkeypatch):
        target = tmp_path / "settings.json"
        target.write_text(json.dumps({
            "theme": "dark",
            "permissions": {"allow": ["preexisting"]},
        }))
        monkeypatch.setattr(
            "sys.argv",
            ["grant_permissions", "--settings", str(target), "--mode", "project"],
        )
        gp.main()
        data = json.loads(target.read_text())
        assert data["theme"] == "dark"
        assert "preexisting" in data["permissions"]["allow"]
