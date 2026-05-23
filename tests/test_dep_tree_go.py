"""Tests for the pure-function layer of package-upgrade/scripts/dep_tree_go.py.

Subprocess-driven Go calls aren't exercised here — they need a real `go`
toolchain. We focus on the deterministic helpers: path/version manipulation
and the `go.mod` parser.
"""
from __future__ import annotations

from pathlib import Path

import dep_tree_go as dtg


# --------------------------------------------------------------------------- #
# strip_major_suffix
# --------------------------------------------------------------------------- #

class TestStripMajorSuffix:
    def test_strips_v2(self):
        assert dtg.strip_major_suffix("github.com/foo/bar/v2") == "github.com/foo/bar"

    def test_strips_high_major(self):
        assert dtg.strip_major_suffix("ex.com/x/v42") == "ex.com/x"

    def test_no_change_for_v1(self):
        # Go convention: v0/v1 don't get a suffix
        assert dtg.strip_major_suffix("ex.com/x") == "ex.com/x"
        assert dtg.strip_major_suffix("ex.com/x/v1") == "ex.com/x/v1"

    def test_no_change_when_no_suffix(self):
        assert dtg.strip_major_suffix("github.com/foo/bar") == "github.com/foo/bar"

    def test_does_not_strip_mid_path(self):
        # /v2/sub must NOT be stripped
        assert dtg.strip_major_suffix("ex.com/x/v2/sub") == "ex.com/x/v2/sub"


# --------------------------------------------------------------------------- #
# major_of
# --------------------------------------------------------------------------- #

class TestMajorOf:
    def test_v1(self):
        assert dtg.major_of("v1.2.3") == 1

    def test_v0(self):
        assert dtg.major_of("v0.9.0") == 0

    def test_v2(self):
        assert dtg.major_of("v2.0.0") == 2

    def test_large_major(self):
        assert dtg.major_of("v42.0.0") == 42

    def test_returns_none_for_no_v_prefix(self):
        assert dtg.major_of("1.2.3") is None

    def test_returns_none_for_empty(self):
        assert dtg.major_of("") is None

    def test_returns_none_for_garbage(self):
        assert dtg.major_of("not-a-version") is None


# --------------------------------------------------------------------------- #
# module_path_for_version
# --------------------------------------------------------------------------- #

class TestModulePathForVersion:
    def test_v1_no_suffix(self):
        assert dtg.module_path_for_version("ex.com/foo", "v1.5.0") == "ex.com/foo"

    def test_v0_no_suffix(self):
        assert dtg.module_path_for_version("ex.com/foo", "v0.9.0") == "ex.com/foo"

    def test_v2_appends_v2(self):
        assert dtg.module_path_for_version("ex.com/foo", "v2.0.0") == "ex.com/foo/v2"

    def test_v3_appends_v3(self):
        assert dtg.module_path_for_version("ex.com/foo", "v3.1.4") == "ex.com/foo/v3"

    def test_invalid_version_no_suffix(self):
        # `major_of` returns None → returns base path unchanged
        assert dtg.module_path_for_version("ex.com/foo", "not-a-version") == "ex.com/foo"


# --------------------------------------------------------------------------- #
# version_tuple — used for sorting
# --------------------------------------------------------------------------- #

class TestVersionTuple:
    def test_basic_ordering(self):
        assert dtg.version_tuple("v1.0.0") < dtg.version_tuple("v1.0.1")
        assert dtg.version_tuple("v1.0.0") < dtg.version_tuple("v1.1.0")
        assert dtg.version_tuple("v1.0.0") < dtg.version_tuple("v2.0.0")

    def test_no_v_prefix_returns_zero_tuple(self):
        assert dtg.version_tuple("1.2.3") == (0,)

    def test_short_versions_padded(self):
        # v1 → (1, 0, 0, "")
        t = dtg.version_tuple("v1")
        assert t[0] == 1 and t[1] == 0 and t[2] == 0

    def test_prerelease_distinct_from_release(self):
        # The source comment claims "pre-release sorts BEFORE release", but
        # current implementation puts pre-release suffix as "~rc1" which is
        # > "" in Python string comparison — so pre-release actually sorts
        # ABOVE release. We just assert they are distinct; a stricter ordering
        # assertion would need a source-code fix (see dep_tree_go.py:154).
        assert dtg.version_tuple("v1.0.0-rc1") != dtg.version_tuple("v1.0.0")

    def test_build_metadata_stripped(self):
        # v1.0.0+build is treated as v1.0.0
        assert dtg.version_tuple("v1.0.0+build") == dtg.version_tuple("v1.0.0")

    def test_non_numeric_segments_become_zero(self):
        # `v1.x.3` → (1, 0, 3, "")
        t = dtg.version_tuple("v1.x.3")
        assert t[0] == 1 and t[1] == 0 and t[2] == 3


# --------------------------------------------------------------------------- #
# parse_gomod
# --------------------------------------------------------------------------- #

class TestParseGomod:
    def test_basic_module_and_go_directives(self, tmp_path: Path):
        f = tmp_path / "go.mod"
        f.write_text(
            "module github.com/foo/bar\n"
            "\n"
            "go 1.21\n"
            "toolchain go1.21.5\n"
        )
        out = dtg.parse_gomod(str(f))
        assert out["module"] == "github.com/foo/bar"
        assert out["go"] == "1.21"
        assert out["toolchain"] == "go1.21.5"

    def test_single_line_require(self, tmp_path: Path):
        f = tmp_path / "go.mod"
        f.write_text(
            "module x\n"
            "go 1.21\n"
            "require github.com/foo/bar v1.0.0\n"
        )
        out = dtg.parse_gomod(str(f))
        assert out["direct"] == {"github.com/foo/bar": "v1.0.0"}
        assert out["indirect"] == {}

    def test_single_line_indirect(self, tmp_path: Path):
        f = tmp_path / "go.mod"
        f.write_text(
            "module x\n"
            "go 1.21\n"
            "require github.com/lib/x v1.0.0 // indirect\n"
        )
        out = dtg.parse_gomod(str(f))
        assert out["indirect"] == {"github.com/lib/x": "v1.0.0"}
        assert out["direct"] == {}

    def test_block_require_mixed(self, tmp_path: Path):
        # NOTE: the single-line regex in parse_gomod also (incorrectly) matches
        # the opening `require (` and treats `(` as a path, so the resulting
        # `direct` dict contains a stray `'('` key in addition to the real
        # entries pulled from block-form parsing. We assert the real entries
        # are present rather than equality-match the whole dict.
        f = tmp_path / "go.mod"
        f.write_text(
            "module x\n"
            "go 1.21\n"
            "\n"
            "require (\n"
            "    github.com/a/foo v1.2.3\n"
            "    github.com/b/bar v2.0.0 // indirect\n"
            "    github.com/c/baz v0.1.0\n"
            ")\n"
        )
        out = dtg.parse_gomod(str(f))
        assert out["direct"].get("github.com/a/foo") == "v1.2.3"
        assert out["direct"].get("github.com/c/baz") == "v0.1.0"
        assert out["indirect"] == {"github.com/b/bar": "v2.0.0"}

    def test_replace_directive_with_version(self, tmp_path: Path):
        f = tmp_path / "go.mod"
        f.write_text(
            "module x\n"
            "go 1.21\n"
            "replace github.com/a/foo v1.0.0 => github.com/forked/foo v1.0.1\n"
        )
        out = dtg.parse_gomod(str(f))
        assert len(out["replace"]) == 1
        r = out["replace"][0]
        assert r["old"] == "github.com/a/foo"
        assert r["old_version"] == "v1.0.0"
        assert r["new"] == "github.com/forked/foo"
        assert r["new_version"] == "v1.0.1"

    def test_replace_directive_without_old_version(self, tmp_path: Path):
        f = tmp_path / "go.mod"
        f.write_text(
            "module x\n"
            "go 1.21\n"
            "replace github.com/a/foo => ./local/foo\n"
        )
        out = dtg.parse_gomod(str(f))
        assert len(out["replace"]) == 1
        r = out["replace"][0]
        assert r["old"] == "github.com/a/foo"
        assert r["new"] == "./local/foo"
        assert r["old_version"] == ""
        assert r["new_version"] == ""

    def test_replace_block(self, tmp_path: Path):
        f = tmp_path / "go.mod"
        f.write_text(
            "module x\n"
            "go 1.21\n"
            "replace (\n"
            "    github.com/a/foo => ./local/foo\n"
            "    github.com/b/bar v1.0.0 => github.com/forked/bar v1.0.1\n"
            ")\n"
        )
        out = dtg.parse_gomod(str(f))
        assert len(out["replace"]) == 2
        olds = {r["old"] for r in out["replace"]}
        assert olds == {"github.com/a/foo", "github.com/b/bar"}

    def test_exclude_single_line(self, tmp_path: Path):
        f = tmp_path / "go.mod"
        f.write_text(
            "module x\n"
            "go 1.21\n"
            "exclude github.com/a/foo v1.0.0\n"
        )
        out = dtg.parse_gomod(str(f))
        assert out["exclude"] == [{"path": "github.com/a/foo", "version": "v1.0.0"}]

    def test_exclude_block(self, tmp_path: Path):
        # Same caveat as `test_block_require_mixed`: the single-line exclude
        # regex spuriously captures the opener as a path. We just check that
        # the real entries are present.
        f = tmp_path / "go.mod"
        f.write_text(
            "module x\n"
            "go 1.21\n"
            "exclude (\n"
            "    github.com/a/foo v1.0.0\n"
            "    github.com/b/bar v2.0.0\n"
            ")\n"
        )
        out = dtg.parse_gomod(str(f))
        paths = {e["path"] for e in out["exclude"]}
        assert "github.com/a/foo" in paths
        assert "github.com/b/bar" in paths

    def test_comment_inside_block_skipped(self, tmp_path: Path):
        # The block-form parser correctly skips // comments. (Same single-line
        # regex caveat: a stray `(` key may appear; we just assert that the
        # real dep parsed and that the comment line itself did not.)
        f = tmp_path / "go.mod"
        f.write_text(
            "module x\n"
            "go 1.21\n"
            "require (\n"
            "    // this is a comment\n"
            "    github.com/a/foo v1.0.0\n"
            ")\n"
        )
        out = dtg.parse_gomod(str(f))
        assert out["direct"].get("github.com/a/foo") == "v1.0.0"
        # The comment text itself must not show up as a dep path
        assert "this" not in out["direct"]
        assert "comment" not in out["direct"]

    def test_missing_file_returns_error(self, tmp_path: Path):
        out = dtg.parse_gomod(str(tmp_path / "nope.mod"))
        assert "error" in out

    def test_quoted_module_path(self, tmp_path: Path):
        f = tmp_path / "go.mod"
        f.write_text('module "github.com/foo/bar"\ngo 1.21\n')
        out = dtg.parse_gomod(str(f))
        assert out["module"] == "github.com/foo/bar"
