"""Tests for package-upgrade/scripts/dep_tree.py."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import dep_tree


# --------------------------------------------------------------------------- #
# _search_json_tree
# --------------------------------------------------------------------------- #

class TestSearchJsonTree:
    def test_finds_direct_parent(self):
        # foo depends on requests
        node = {
            "package_name": "foo",
            "dependencies": [
                {"package_name": "requests", "installed_version": "2.28.0",
                 "required_version": ">=2.0"}
            ],
        }
        parents: list = []
        constraints: dict = {}
        dep_tree._search_json_tree("requests", node, parents, constraints)
        assert parents == ["foo"]
        assert constraints["foo"] == ">=2.0"

    def test_falls_back_to_installed_version(self):
        node = {
            "package_name": "foo",
            "dependencies": [
                {"package_name": "requests", "installed_version": "2.28.0"}
            ],
        }
        parents: list = []
        constraints: dict = {}
        dep_tree._search_json_tree("requests", node, parents, constraints)
        assert constraints["foo"] == "==2.28.0"

    def test_recurses_into_nested_deps(self):
        # bar → foo → requests
        node = {
            "package_name": "bar",
            "dependencies": [
                {
                    "package_name": "foo",
                    "dependencies": [
                        {"package_name": "requests", "required_version": ">=1.0"}
                    ],
                }
            ],
        }
        parents: list = []
        constraints: dict = {}
        dep_tree._search_json_tree("requests", node, parents, constraints)
        # `foo` is the direct parent of requests; "bar" is only the parent of foo
        assert "foo" in parents

    def test_case_insensitive_match(self):
        node = {
            "package_name": "Foo",
            "dependencies": [
                {"package_name": "Requests", "required_version": ">=2.0"}
            ],
        }
        parents: list = []
        constraints: dict = {}
        dep_tree._search_json_tree("requests", node, parents, constraints)
        assert parents == ["foo"]

    def test_no_match_keeps_lists_empty(self):
        node = {"package_name": "foo", "dependencies": [
            {"package_name": "other"}
        ]}
        parents: list = []
        constraints: dict = {}
        dep_tree._search_json_tree("requests", node, parents, constraints)
        assert parents == []
        assert constraints == {}

    def test_dedupes_parents(self):
        # foo appears twice as parent of requests (shouldn't double-add)
        node = {
            "package_name": "foo",
            "dependencies": [
                {"package_name": "requests", "required_version": ">=1.0"},
                {"package_name": "requests", "required_version": ">=2.0"},
            ],
        }
        parents: list = []
        constraints: dict = {}
        dep_tree._search_json_tree("requests", node, parents, constraints)
        assert parents.count("foo") == 1


# --------------------------------------------------------------------------- #
# find_parents_in_tree
# --------------------------------------------------------------------------- #

class TestFindParentsInTree:
    def test_finds_parents_from_json_format(self):
        tree = {
            "data": [
                {
                    "package_name": "foo",
                    "dependencies": [
                        {"package_name": "requests", "required_version": ">=2.0"}
                    ],
                }
            ]
        }
        parents, constraints = dep_tree.find_parents_in_tree("requests", tree, "json")
        assert parents == ["foo"]
        assert constraints == {"foo": ">=2.0"}

    def test_text_format_returns_empty(self):
        # text format isn't parsed (poetry/uv); returns ([], {})
        tree = {"raw": "some text", "format": "text"}
        parents, constraints = dep_tree.find_parents_in_tree("x", tree, "text")
        assert parents == []
        assert constraints == {}

    def test_empty_tree(self):
        parents, constraints = dep_tree.find_parents_in_tree("x", {"data": []}, "json")
        assert parents == []
        assert constraints == {}


# --------------------------------------------------------------------------- #
# classify_dependency
# --------------------------------------------------------------------------- #

class TestClassifyDependency:
    def test_direct_only(self, tmp_path: Path):
        req = tmp_path / "requirements.txt"
        req.write_text("requests>=2.0\n", encoding="utf-8")
        tree = {"data": []}
        result = dep_tree.classify_dependency("requests", tree, [str(req)], "json")
        assert result["dependency_type"] == "direct"
        assert result["is_direct"] is True
        assert result["is_transitive"] is False
        assert result["parent_packages"] == []

    def test_transitive_only(self, tmp_path: Path):
        req = tmp_path / "requirements.txt"
        req.write_text("flask>=2.0\n", encoding="utf-8")
        tree = {
            "data": [
                {
                    "package_name": "flask",
                    "dependencies": [
                        {"package_name": "requests", "required_version": ">=2.0"}
                    ],
                }
            ]
        }
        result = dep_tree.classify_dependency("requests", tree, [str(req)], "json")
        assert result["dependency_type"] == "transitive"
        assert result["is_direct"] is False
        assert result["is_transitive"] is True
        assert result["parent_packages"] == ["flask"]

    def test_both_direct_and_transitive(self, tmp_path: Path):
        req = tmp_path / "requirements.txt"
        req.write_text("requests>=2.0\nflask>=2.0\n", encoding="utf-8")
        tree = {
            "data": [
                {
                    "package_name": "flask",
                    "dependencies": [
                        {"package_name": "requests", "required_version": ">=2.0"}
                    ],
                }
            ]
        }
        result = dep_tree.classify_dependency("requests", tree, [str(req)], "json")
        assert result["dependency_type"] == "both"

    def test_unknown_when_not_found(self, tmp_path: Path):
        req = tmp_path / "requirements.txt"
        req.write_text("flask>=2.0\n", encoding="utf-8")
        tree = {"data": []}
        result = dep_tree.classify_dependency("requests", tree, [str(req)], "json")
        assert result["dependency_type"] == "unknown"

    def test_missing_dep_file_doesnt_crash(self):
        tree = {"data": []}
        result = dep_tree.classify_dependency(
            "requests", tree, ["/nonexistent/file.txt"], "json"
        )
        assert result["is_direct"] is False
        assert result["dependency_type"] == "unknown"

    def test_pkg_name_with_special_chars_escaped(self, tmp_path: Path):
        # `re.escape` handles dots in package names like `zope.interface`
        req = tmp_path / "requirements.txt"
        req.write_text("zope.interface>=5.0\n", encoding="utf-8")
        tree = {"data": []}
        result = dep_tree.classify_dependency("zope.interface", tree, [str(req)], "json")
        assert result["is_direct"] is True

    def test_word_boundary_no_false_match(self, tmp_path: Path):
        # `requestsmock` shouldn't match `requests`
        req = tmp_path / "requirements.txt"
        req.write_text("requestsmock>=1.0\n", encoding="utf-8")
        tree = {"data": []}
        result = dep_tree.classify_dependency("requests", tree, [str(req)], "json")
        assert result["is_direct"] is False


# --------------------------------------------------------------------------- #
# get_installed_version — mock subprocess
# --------------------------------------------------------------------------- #

class TestGetInstalledVersion:
    def test_parses_pip_show_version_line(self):
        fake_output = "Name: requests\nVersion: 2.28.1\nSummary: HTTP for humans\n"
        completed = MagicMock(returncode=0, stdout=fake_output, stderr="")
        with patch.object(subprocess, "run", return_value=completed):
            v = dep_tree.get_installed_version("requests", "pip", ".")
        assert v == "2.28.1"

    def test_returns_unknown_when_not_found(self):
        completed = MagicMock(returncode=0, stdout="", stderr="not found")
        with patch.object(subprocess, "run", return_value=completed):
            v = dep_tree.get_installed_version("nope", "pip", ".")
        assert v == "unknown"

    def test_handles_filenotfound(self):
        with patch.object(subprocess, "run", side_effect=FileNotFoundError):
            v = dep_tree.get_installed_version("x", "pip", ".")
        assert v == "unknown"

    def test_handles_calledprocesserror(self):
        with patch.object(
            subprocess, "run",
            side_effect=subprocess.CalledProcessError(1, ["pip"], stderr="err"),
        ):
            v = dep_tree.get_installed_version("x", "pip", ".")
        assert v == "unknown"

    def test_unknown_pkg_manager_falls_back_to_pip(self):
        fake = MagicMock(returncode=0, stdout="Version: 9.9.9\n", stderr="")
        with patch.object(subprocess, "run", return_value=fake) as mock_run:
            dep_tree.get_installed_version("x", "unknown_pm", ".")
            args, _ = mock_run.call_args
            # Falls back to the pip command
            assert args[0] == ["pip", "show", "x"]


# --------------------------------------------------------------------------- #
# get_dep_tree_* wrappers — mock subprocess
# --------------------------------------------------------------------------- #

class TestGetDepTreePip:
    def test_returns_parsed_json(self):
        tree_json = [{"package_name": "requests"}]
        fake = MagicMock(returncode=0, stdout=json.dumps(tree_json), stderr="")
        with patch.object(subprocess, "run", return_value=fake):
            result = dep_tree.get_dep_tree_pip(".")
        assert result["format"] == "json"
        assert result["data"] == tree_json

    def test_handles_pipdeptree_missing(self):
        with patch.object(subprocess, "run", side_effect=FileNotFoundError):
            result = dep_tree.get_dep_tree_pip(".")
        assert "error" in result
        assert "pipdeptree" in result["error"]

    def test_handles_called_process_error(self):
        err = subprocess.CalledProcessError(1, ["pipdeptree"], stderr="boom")
        with patch.object(subprocess, "run", side_effect=err):
            result = dep_tree.get_dep_tree_pip(".")
        assert "error" in result
        assert result["data"] == []


class TestGetDepTreePoetry:
    def test_returns_raw_text(self):
        fake = MagicMock(returncode=0, stdout="raw poetry output", stderr="")
        with patch.object(subprocess, "run", return_value=fake):
            result = dep_tree.get_dep_tree_poetry(".")
        assert result["format"] == "text"
        assert result["raw"] == "raw poetry output"

    def test_handles_missing_poetry(self):
        with patch.object(subprocess, "run", side_effect=FileNotFoundError):
            result = dep_tree.get_dep_tree_poetry(".")
        assert "error" in result
        assert "poetry" in result["error"]


class TestGetDepTreeUv:
    def test_returns_raw_text(self):
        fake = MagicMock(returncode=0, stdout="raw uv output", stderr="")
        with patch.object(subprocess, "run", return_value=fake):
            result = dep_tree.get_dep_tree_uv(".")
        assert result["format"] == "text"
        assert result["raw"] == "raw uv output"

    def test_handles_missing_uv(self):
        with patch.object(subprocess, "run", side_effect=FileNotFoundError):
            result = dep_tree.get_dep_tree_uv(".")
        assert "error" in result
