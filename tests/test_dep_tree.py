"""Tests for package-upgrade/scripts/dep_tree.py."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

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
                {
                    "package_name": "requests",
                    "installed_version": "2.28.0",
                    "required_version": ">=2.0",
                }
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
            "dependencies": [{"package_name": "requests", "installed_version": "2.28.0"}],
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
                    "dependencies": [{"package_name": "requests", "required_version": ">=1.0"}],
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
            "dependencies": [{"package_name": "Requests", "required_version": ">=2.0"}],
        }
        parents: list = []
        constraints: dict = {}
        dep_tree._search_json_tree("requests", node, parents, constraints)
        assert parents == ["foo"]

    def test_no_match_keeps_lists_empty(self):
        node = {"package_name": "foo", "dependencies": [{"package_name": "other"}]}
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
                    "dependencies": [{"package_name": "requests", "required_version": ">=2.0"}],
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
                    "dependencies": [{"package_name": "requests", "required_version": ">=2.0"}],
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
                    "dependencies": [{"package_name": "requests", "required_version": ">=2.0"}],
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
        result = dep_tree.classify_dependency("requests", tree, ["/nonexistent/file.txt"], "json")
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
            subprocess,
            "run",
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


# --------------------------------------------------------------------------- #
# parse_version_spec / version_tuple / spec_allows
# --------------------------------------------------------------------------- #


class TestParseVersionSpec:
    def test_single_op(self):
        assert dep_tree.parse_version_spec(">=2.0") == [(">=", "2.0")]

    def test_compound_spec(self):
        assert dep_tree.parse_version_spec(">=2.0,<3.0") == [(">=", "2.0"), ("<", "3.0")]

    def test_empty_returns_empty(self):
        assert dep_tree.parse_version_spec("") == []
        assert dep_tree.parse_version_spec("   ") == []

    def test_unparseable_returns_empty(self):
        # No recognised operator
        assert dep_tree.parse_version_spec("foo bar") == []

    def test_handles_whitespace(self):
        assert dep_tree.parse_version_spec(" >= 2.0 , < 3.0 ") == [(">=", "2.0"), ("<", "3.0")]


class TestVersionTuple:
    def test_basic(self):
        assert dep_tree.version_tuple("1.2.3") == (1, 2, 3)

    def test_strips_epoch(self):
        assert dep_tree.version_tuple("2!1.0.0") == (1, 0, 0)

    def test_strips_local(self):
        assert dep_tree.version_tuple("1.0.0+abc") == (1, 0, 0)

    def test_strips_prerelease_suffix(self):
        # PEP 440 pre-releases ('1.0a1') return just the numeric prefix
        assert dep_tree.version_tuple("1.0a1") == (1, 0)

    def test_empty_or_invalid(self):
        assert dep_tree.version_tuple("") == ()
        assert dep_tree.version_tuple("not-a-version") == ()


class TestSpecAllows:
    def test_ge_satisfied(self):
        assert dep_tree.spec_allows(">=2.0", "2.5") is True

    def test_ge_not_satisfied(self):
        assert dep_tree.spec_allows(">=2.0", "1.9") is False

    def test_compound_satisfied(self):
        assert dep_tree.spec_allows(">=2.0,<3.0", "2.5") is True

    def test_compound_one_clause_fails(self):
        assert dep_tree.spec_allows(">=2.0,<3.0", "3.0") is False

    def test_eq_exact(self):
        assert dep_tree.spec_allows("==1.2.3", "1.2.3") is True
        assert dep_tree.spec_allows("==1.2.3", "1.2.4") is False

    def test_ne_filter(self):
        assert dep_tree.spec_allows("!=1.0", "2.0") is True
        assert dep_tree.spec_allows("!=1.0", "1.0") is False

    def test_unsupported_op_returns_none(self):
        # ~= and === are deliberately not handled — caller should treat as unknown
        assert dep_tree.spec_allows("~=1.0", "1.5") is None
        assert dep_tree.spec_allows("===1.0", "1.0") is None

    def test_wildcard_returns_none(self):
        assert dep_tree.spec_allows("==1.*", "1.5") is None

    def test_unparseable_returns_none(self):
        assert dep_tree.spec_allows("", "1.0") is None
        assert dep_tree.spec_allows(">=2.0", "garbage") is None

    def test_padding_for_short_versions(self):
        # "2.0" should be treated as "2.0.0" when comparing to "2.0.1"
        assert dep_tree.spec_allows(">=2.0", "2.0.1") is True
        assert dep_tree.spec_allows("<=2.0", "2.0.0") is True


# --------------------------------------------------------------------------- #
# PyPI requires_dist parsing
# --------------------------------------------------------------------------- #


class TestExtractTargetSpec:
    def test_parens_form(self):
        reqs = ["requests (>=2.0,<3.0)", "click (>=8.0)"]
        found, spec = dep_tree.extract_target_spec_from_requires(reqs, "requests")
        assert found is True
        assert spec == ">=2.0,<3.0"

    def test_pep508_form(self):
        reqs = ["requests>=2.0", "click>=8.0"]
        found, spec = dep_tree.extract_target_spec_from_requires(reqs, "requests")
        assert found is True
        assert spec == ">=2.0"

    def test_bare_dep(self):
        reqs = ["requests", "click>=8.0"]
        found, spec = dep_tree.extract_target_spec_from_requires(reqs, "requests")
        assert found is True
        assert spec == ""

    def test_with_marker(self):
        reqs = ['requests (>=2.0); python_version >= "3.8"']
        found, spec = dep_tree.extract_target_spec_from_requires(reqs, "requests")
        assert found is True
        assert spec == ">=2.0"

    def test_with_extras(self):
        reqs = ["requests[security]>=2.0"]
        found, spec = dep_tree.extract_target_spec_from_requires(reqs, "requests")
        assert found is True
        assert spec == ">=2.0"

    def test_name_normalisation(self):
        # PyPI names normalise [-_.] runs to single '-' and lowercase
        reqs = ["Foo_Bar.Baz (>=1.0)"]
        found, spec = dep_tree.extract_target_spec_from_requires(reqs, "foo-bar-baz")
        assert found is True
        assert spec == ">=1.0"

    def test_not_found(self):
        reqs = ["click>=8.0"]
        found, spec = dep_tree.extract_target_spec_from_requires(reqs, "requests")
        assert found is False
        assert spec == ""

    def test_empty_reqs(self):
        found, spec = dep_tree.extract_target_spec_from_requires([], "requests")
        assert found is False


# --------------------------------------------------------------------------- #
# analyze_parent — uses fetch_pypi_metadata (mockable)
# --------------------------------------------------------------------------- #


class TestAnalyzeParent:
    def test_no_probe_returns_unknown(self):
        info = dep_tree.analyze_parent("flask", "requests", "2.32.0", probe_enabled=False)
        assert info["status"] == "unknown"
        assert "disabled" in info["reason"]

    def test_no_target_version_returns_unknown(self):
        info = dep_tree.analyze_parent("flask", "requests", None, probe_enabled=True)
        assert info["status"] == "unknown"
        assert "no --target-version" in info["reason"]

    def test_pypi_fetch_failure_returns_unknown(self):
        with patch.object(dep_tree, "fetch_pypi_metadata", return_value=None):
            info = dep_tree.analyze_parent("flask", "requests", "2.32.0", probe_enabled=True)
        assert info["status"] == "unknown"
        assert "PyPI fetch failed" in info["reason"]

    def test_satisfies_when_parent_latest_allows(self):
        meta = {
            "info": {
                "version": "3.0.0",
                "requires_dist": ["requests (>=2.30,<3.0)", "click>=8.0"],
            }
        }
        with patch.object(dep_tree, "fetch_pypi_metadata", return_value=meta):
            info = dep_tree.analyze_parent("flask", "requests", "2.32.0", probe_enabled=True)
        assert info["status"] == "satisfies"
        assert info["latest"] == "3.0.0"
        assert info["requires_target_spec"] == ">=2.30,<3.0"

    def test_would_not_help_pin_when_parent_still_excludes(self):
        meta = {
            "info": {
                "version": "3.0.0",
                "requires_dist": ["requests (<2.30)"],
            }
        }
        with patch.object(dep_tree, "fetch_pypi_metadata", return_value=meta):
            info = dep_tree.analyze_parent("flask", "requests", "2.32.0", probe_enabled=True)
        assert info["status"] == "would_not_help_pin"
        assert "excludes desired" in info["reason"]

    def test_no_dep_when_parent_no_longer_lists_target(self):
        meta = {
            "info": {
                "version": "3.0.0",
                "requires_dist": ["click>=8.0"],  # requests dropped
            }
        }
        with patch.object(dep_tree, "fetch_pypi_metadata", return_value=meta):
            info = dep_tree.analyze_parent("flask", "requests", "2.32.0", probe_enabled=True)
        assert info["status"] == "no_dep"

    def test_bare_dep_satisfies_any(self):
        meta = {
            "info": {
                "version": "3.0.0",
                "requires_dist": ["requests"],  # no spec
            }
        }
        with patch.object(dep_tree, "fetch_pypi_metadata", return_value=meta):
            info = dep_tree.analyze_parent("flask", "requests", "2.32.0", probe_enabled=True)
        assert info["status"] == "satisfies"


# --------------------------------------------------------------------------- #
# compose_strategies
# --------------------------------------------------------------------------- #


class TestComposeStrategies:
    def _direct(self, version_constraints=None):
        return {
            "dependency_type": "direct",
            "is_direct": True,
            "is_transitive": False,
            "parent_packages": [],
            "version_constraints": version_constraints or {},
        }

    def _transitive(self, parents, constraints):
        return {
            "dependency_type": "transitive",
            "is_direct": False,
            "is_transitive": True,
            "parent_packages": parents,
            "version_constraints": constraints,
        }

    def test_direct_emits_direct_bump_first(self):
        strats = dep_tree.compose_strategies(
            self._direct(), parent_analyses=[], has_lockfile=True, target_version="2.0"
        )
        assert strats[0]["type"] == "direct_bump"
        assert strats[0]["confidence"] == 0.95

    def test_transitive_with_all_parents_already_allowing_emits_lock_only(self):
        cls = self._transitive(["flask"], {"flask": ">=2.0,<3.0"})
        strats = dep_tree.compose_strategies(
            cls, parent_analyses=[], has_lockfile=True, target_version="2.32.0"
        )
        types = [s["type"] for s in strats]
        assert "lock_only" in types
        # lock_only should be top when no parent_analyses competing
        assert strats[0]["type"] == "lock_only"

    def test_transitive_no_lockfile_skips_lock_only(self):
        cls = self._transitive(["flask"], {"flask": ">=2.0"})
        strats = dep_tree.compose_strategies(
            cls, parent_analyses=[], has_lockfile=False, target_version="2.32.0"
        )
        assert all(s["type"] != "lock_only" for s in strats)

    def test_transitive_parent_constraint_excludes_target_skips_lock_only(self):
        cls = self._transitive(["flask"], {"flask": "<2.0"})  # excludes target 2.32.0
        strats = dep_tree.compose_strategies(
            cls, parent_analyses=[], has_lockfile=True, target_version="2.32.0"
        )
        assert all(s["type"] != "lock_only" for s in strats)

    def test_bump_parent_emitted_per_parent_with_weighted_confidence(self):
        cls = self._transitive(["flask", "django"], {})
        analyses = [
            {"name": "flask", "latest": "3.0", "status": "satisfies", "reason": "ok"},
            {
                "name": "django",
                "latest": "5.0",
                "status": "would_not_help_pin",
                "reason": "still pins",
            },
        ]
        strats = dep_tree.compose_strategies(
            cls, parent_analyses=analyses, has_lockfile=False, target_version="2.32.0"
        )
        bumps = [s for s in strats if s["type"] == "bump_parent"]
        assert len(bumps) == 2
        # satisfies (0.75) ranked above would_not_help_pin (0.05)
        satisfies = next(s for s in bumps if s["parent"] == "flask")
        blocked = next(s for s in bumps if s["parent"] == "django")
        assert satisfies["confidence"] > blocked["confidence"]

    def test_fallback_bump_parent_then_target_when_nothing_else(self):
        # transitive, no lockfile, no parent_analyses → final fallback fires
        cls = self._transitive(["flask"], {})
        strats = dep_tree.compose_strategies(
            cls, parent_analyses=[], has_lockfile=False, target_version=None
        )
        assert strats[0]["type"] == "bump_parent_then_target"

    def test_unknown_when_classification_empty(self):
        cls = {
            "dependency_type": "unknown",
            "is_direct": False,
            "is_transitive": False,
            "parent_packages": [],
            "version_constraints": {},
        }
        strats = dep_tree.compose_strategies(
            cls, parent_analyses=[], has_lockfile=False, target_version=None
        )
        assert strats[0]["type"] == "unknown"
        assert strats[0]["confidence"] == 0.0

    def test_strategies_sorted_by_confidence_desc(self):
        cls = self._transitive(["flask"], {"flask": ">=2.0"})  # allows 2.32
        analyses = [{"name": "flask", "latest": "3.0", "status": "satisfies", "reason": "ok"}]
        strats = dep_tree.compose_strategies(
            cls, parent_analyses=analyses, has_lockfile=True, target_version="2.32.0"
        )
        confs = [s["confidence"] for s in strats]
        assert confs == sorted(confs, reverse=True)
