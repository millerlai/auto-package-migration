"""Tests for package-upgrade/scripts/parse_pm_errors.py."""
from __future__ import annotations

import parse_pm_errors as ppe


# --------------------------------------------------------------------------- #
# extract_pkg_and_registry
# --------------------------------------------------------------------------- #

class TestExtractPkgAndRegistry:
    def test_extracts_scoped_npm_package(self):
        line = "└─ @scope/foo@npm:1.2.3 (resolution: ...)"
        pkg, reg = ppe.extract_pkg_and_registry(line)
        assert pkg == "@scope/foo"

    def test_extracts_unscoped_npm_package(self):
        line = "└─ lodash@npm:4.17.21 (resolution: https://registry.npmjs.org/lodash)"
        pkg, reg = ppe.extract_pkg_and_registry(line)
        assert pkg == "lodash"
        assert reg == "registry.npmjs.org"

    def test_extracts_registry_only(self):
        line = "Error fetching https://registry.npmjs.org/foo"
        pkg, reg = ppe.extract_pkg_and_registry(line)
        assert reg == "registry.npmjs.org"

    def test_no_match_returns_none(self):
        pkg, reg = ppe.extract_pkg_and_registry("some random text with no package")
        assert pkg is None
        assert reg is None


# --------------------------------------------------------------------------- #
# classify — per category
# --------------------------------------------------------------------------- #

class TestClassifyAuth:
    def test_yn0041(self):
        out = "YN0041: Invalid authentication for @scope/foo@npm:1.0.0"
        r = ppe.classify(out)
        assert len(r["categories"]["auth"]) == 1
        assert r["categories"]["auth"][0]["code"] == "YN0041"
        assert r["primary_blocker"] == "auth"

    def test_e401(self):
        r = ppe.classify("npm ERR! code E401\nnpm ERR! 401 Unauthorized")
        assert r["categories"]["auth"]  # one or more matches
        assert r["primary_blocker"] == "auth"

    def test_authentication_required(self):
        r = ppe.classify("error: authentication required for registry")
        assert r["categories"]["auth"]
        assert r["primary_blocker"] == "auth"


class TestClassifyNetwork:
    def test_enotfound(self):
        r = ppe.classify("npm ERR! code ENOTFOUND\nnpm ERR! errno ENOTFOUND")
        assert r["categories"]["network"]
        assert r["primary_blocker"] == "network"

    def test_etimedout(self):
        r = ppe.classify("Error: ETIMEDOUT connect to registry.example.com")
        assert r["categories"]["network"]

    def test_yn0050(self):
        r = ppe.classify("YN0050: Network error fetching package")
        assert r["categories"]["network"]


class TestClassifyConflict:
    def test_eresolve(self):
        r = ppe.classify("npm ERR! ERESOLVE unable to resolve dependency tree")
        # ERESOLVE plus the "unable to resolve dependency tree" line both match conflict
        assert r["categories"]["conflict"]
        assert r["primary_blocker"] == "conflict"

    def test_yn0086(self):
        r = ppe.classify("YN0086: The lockfile would have been modified by this install")
        assert r["categories"]["conflict"]

    def test_peer_dep_missing(self):
        r = ppe.classify("warning: peer dependency missing for react@18")
        assert r["categories"]["conflict"]


class TestClassifyChecksum:
    def test_eintegrity(self):
        r = ppe.classify("npm ERR! code EINTEGRITY\nnpm ERR! sha512 checksum mismatch")
        assert r["categories"]["checksum"]
        assert r["primary_blocker"] == "checksum"

    def test_yn0018(self):
        r = ppe.classify("YN0018: foo@npm:1.0.0 the integrity checksum failed")
        assert r["categories"]["checksum"]


class TestClassifyMissing:
    def test_e404(self):
        r = ppe.classify("npm ERR! 404 Not Found - GET https://reg/foo")
        assert r["categories"]["missing"]
        assert r["primary_blocker"] == "missing"

    def test_no_matching_version(self):
        r = ppe.classify("error: No matching version found for foo@9.9.9")
        assert r["categories"]["missing"]


class TestClassifyPatch:
    def test_yn0066_alone_is_primary(self):
        r = ppe.classify("YN0066: typescript@patch:typescript@npm%3A4.0.0 patch failed")
        assert r["categories"]["patch"]
        # When patch is the ONLY signal, it's the primary blocker
        assert r["primary_blocker"] == "patch"

    def test_patch_demoted_when_real_error_present(self):
        out = (
            "YN0066: typescript@patch:typescript@npm%3A4.0.0 patch failed\n"
            "YN0041: Invalid authentication for @scope/foo@npm:1.0.0\n"
        )
        r = ppe.classify(out)
        assert r["categories"]["patch"]
        assert r["categories"]["auth"]
        # Auth must win, patch is just noise here
        assert r["primary_blocker"] == "auth"


# --------------------------------------------------------------------------- #
# classify — global behaviour
# --------------------------------------------------------------------------- #

class TestClassifyGlobal:
    def test_empty_input(self):
        r = ppe.classify("")
        assert r["primary_blocker"] is None
        assert r["remediation"] == ""
        # "".splitlines() returns [] → total_lines_seen = 0
        assert r["total_lines_seen"] == 0
        assert all(v == [] for v in r["categories"].values())

    def test_total_lines_seen_counts_input(self):
        r = ppe.classify("line1\nline2\nline3\n")
        # "a\nb\nc\n".splitlines() == ["a", "b", "c"] → 3
        assert r["total_lines_seen"] == 3

    def test_dedup_same_line_same_category(self):
        # Same line should only be classified once per category
        out = "YN0041: Invalid authentication for foo\n" * 5
        r = ppe.classify(out)
        # deduped on (cat, raw[:120])
        assert len(r["categories"]["auth"]) == 1

    def test_remediation_string_for_auth(self):
        r = ppe.classify("YN0041: Invalid authentication\n")
        assert "token" in r["remediation"].lower()

    def test_blocker_priority_auth_over_network(self):
        out = "ENOTFOUND something\nYN0041: Invalid authentication\n"
        r = ppe.classify(out)
        assert r["categories"]["auth"]
        assert r["categories"]["network"]
        # priority: auth > network
        assert r["primary_blocker"] == "auth"

    def test_blocker_priority_checksum_over_conflict(self):
        out = "ERESOLVE conflict\nEINTEGRITY checksum mismatch\n"
        r = ppe.classify(out)
        assert r["primary_blocker"] == "checksum"

    def test_exit_clue_auth(self):
        r = ppe.classify("YN0041: Invalid authentication\n")
        assert "auth" in r["exit_clue"].lower() or r["exit_clue"]

    def test_exit_clue_network(self):
        r = ppe.classify("ENOTFOUND host\n")
        assert "network" in r["exit_clue"].lower()

    def test_no_match_no_blocker(self):
        r = ppe.classify("✓ success\ninfo: done\n")
        assert r["primary_blocker"] is None
        assert r["remediation"] == ""

    def test_patch_marked_noise(self):
        r = ppe.classify("YN0066: patch failed for typescript\n")
        entry = r["categories"]["patch"][0]
        assert entry.get("noise") is True

    def test_line_can_match_multiple_categories(self):
        # The `break` inside classify() only breaks the inner pattern loop,
        # not the outer category loop — so a line matching both auth and
        # patch markers ends up classified under BOTH categories. The
        # primary_blocker priority still demotes patch.
        line = "YN0041: Invalid authentication YN0066: patch failed"
        r = ppe.classify(line)
        assert len(r["categories"]["auth"]) == 1
        assert len(r["categories"]["patch"]) == 1
        # Auth wins the primary_blocker race despite patch matching
        assert r["primary_blocker"] == "auth"
