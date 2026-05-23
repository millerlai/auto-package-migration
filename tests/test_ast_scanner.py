"""Tests for package-upgrade/scripts/ast_scanner.py."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import ast_scanner


# --------------------------------------------------------------------------- #
# PackageUsageVisitor — visit_Import / visit_ImportFrom
# --------------------------------------------------------------------------- #

def _visit(source: str, package: str) -> ast_scanner.PackageUsageVisitor:
    tree = ast.parse(source)
    visitor = ast_scanner.PackageUsageVisitor(package, source.splitlines())
    visitor.visit(tree)
    return visitor


class TestVisitImport:
    def test_plain_import_records_module(self):
        v = _visit("import requests\n", "requests")
        assert len(v.imports) == 1
        assert v.imports[0]["type"] == "import"
        assert v.imports[0]["module"] == "requests"
        assert v.imports[0]["alias"] is None
        assert v.imports[0]["line"] == 1
        assert "requests" in v.imported_names

    def test_import_with_alias(self):
        v = _visit("import requests as rq\n", "requests")
        assert v.imports[0]["alias"] == "rq"
        # alias maps the local name back to the original module
        assert v.imported_names["rq"] == "requests"
        assert "requests" not in v.imported_names

    def test_submodule_import_matches(self):
        v = _visit("import requests.adapters\n", "requests")
        assert len(v.imports) == 1
        assert v.imports[0]["module"] == "requests.adapters"

    def test_unrelated_import_ignored(self):
        v = _visit("import json\nimport os\n", "requests")
        assert v.imports == []
        assert v.imported_names == {}

    def test_package_name_prefix_only_matches_full_segment(self):
        # "requestsmock" must NOT match "requests"
        v = _visit("import requestsmock\n", "requests")
        assert v.imports == []


class TestVisitImportFrom:
    def test_from_import_records_each_name(self):
        v = _visit("from requests import get, post\n", "requests")
        assert len(v.imports) == 2
        names = {i["name"] for i in v.imports}
        assert names == {"get", "post"}
        assert all(i["type"] == "from_import" for i in v.imports)

    def test_from_import_alias(self):
        v = _visit("from requests import get as g\n", "requests")
        assert v.imports[0]["alias"] == "g"
        assert v.imported_names["g"] == "requests.get"

    def test_from_submodule_import(self):
        v = _visit("from requests.exceptions import HTTPError\n", "requests")
        assert len(v.imports) == 1
        assert v.imports[0]["module"] == "requests.exceptions"
        assert v.imports[0]["name"] == "HTTPError"

    def test_star_import(self):
        v = _visit("from requests import *\n", "requests")
        assert len(v.imports) == 1
        assert v.imports[0]["name"] == "*"
        # imported_names should hold the module itself for *
        assert v.imported_names["*"] == "requests"

    def test_from_unrelated_module_ignored(self):
        v = _visit("from json import loads\n", "requests")
        assert v.imports == []


# --------------------------------------------------------------------------- #
# PackageUsageVisitor — visit_Name / visit_Attribute
# --------------------------------------------------------------------------- #

class TestUsageTracking:
    def test_name_usage_recorded(self):
        v = _visit("from requests import get\nget('http://x')\n", "requests")
        # `get` should appear in usages
        symbols = [u["symbol"] for u in v.usages]
        assert "requests.get" in symbols

    def test_attribute_chain_resolved(self):
        v = _visit("import requests\nrequests.adapters.HTTPAdapter()\n", "requests")
        symbols = [u["symbol"] for u in v.usages]
        # The full chain should resolve to requests.adapters.HTTPAdapter
        assert any(s.startswith("requests.adapters.HTTPAdapter") for s in symbols)

    def test_alias_resolution_in_usage(self):
        v = _visit("import requests as r\nr.get('u')\n", "requests")
        symbols = [u["symbol"] for u in v.usages]
        # `r.get` should resolve back to requests.get
        assert any("requests" in s and "get" in s for s in symbols)

    def test_unrelated_name_not_recorded(self):
        v = _visit("import os\nos.path.join('a', 'b')\n", "requests")
        assert v.usages == []


# --------------------------------------------------------------------------- #
# _get_context
# --------------------------------------------------------------------------- #

class TestGetContext:
    def test_context_includes_line(self):
        source = "\n".join(f"line{i}" for i in range(1, 21))  # 20 lines
        v = ast_scanner.PackageUsageVisitor("x", source.splitlines())
        ctx = v._get_context(10, radius=2)
        # radius=2 → lines 8,9,10,11,12
        assert "line8" in ctx
        assert "line10" in ctx
        assert "line12" in ctx
        assert "line7" not in ctx
        assert "line13" not in ctx

    def test_context_clamps_at_start(self):
        v = ast_scanner.PackageUsageVisitor("x", ["a", "b", "c"])
        ctx = v._get_context(1, radius=5)
        # All three lines should appear
        assert "a" in ctx and "b" in ctx and "c" in ctx

    def test_context_line_numbers_prefixed(self):
        v = ast_scanner.PackageUsageVisitor("x", ["a", "b", "c"])
        ctx = v._get_context(2, radius=0)
        assert "2 | b" in ctx


# --------------------------------------------------------------------------- #
# _resolve_attr_chain
# --------------------------------------------------------------------------- #

class TestResolveAttrChain:
    def test_resolve_two_level(self):
        v = ast_scanner.PackageUsageVisitor("requests", [])
        # parse `requests.get` → Attribute node
        node = ast.parse("requests.get").body[0].value
        assert v._resolve_attr_chain(node) == "requests.get"

    def test_resolve_three_level(self):
        v = ast_scanner.PackageUsageVisitor("requests", [])
        node = ast.parse("requests.adapters.HTTPAdapter").body[0].value
        assert v._resolve_attr_chain(node) == "requests.adapters.HTTPAdapter"

    def test_resolve_returns_none_for_non_name_root(self):
        v = ast_scanner.PackageUsageVisitor("requests", [])
        # `(a + b).c` — root is a BinOp, not a Name
        node = ast.parse("(a + b).c").body[0].value
        assert v._resolve_attr_chain(node) is None


# --------------------------------------------------------------------------- #
# scan_file
# --------------------------------------------------------------------------- #

class TestScanFile:
    def test_scan_file_returns_none_when_unused(self, tmp_path: Path):
        f = tmp_path / "a.py"
        f.write_text("import os\nprint(1)\n", encoding="utf-8")
        assert ast_scanner.scan_file(f, "requests") is None

    def test_scan_file_returns_dict_when_used(self, tmp_path: Path):
        f = tmp_path / "a.py"
        f.write_text("import requests\nrequests.get('x')\n", encoding="utf-8")
        result = ast_scanner.scan_file(f, "requests")
        assert result is not None
        assert result["file"] == str(f)
        assert len(result["imports"]) == 1
        assert len(result["usages"]) >= 1

    def test_scan_file_skips_syntax_error(self, tmp_path: Path):
        f = tmp_path / "broken.py"
        f.write_text("def bad(:\n    pass\n", encoding="utf-8")
        assert ast_scanner.scan_file(f, "requests") is None

    def test_scan_file_skips_bad_encoding(self, tmp_path: Path):
        f = tmp_path / "binary.py"
        # bytes that are not valid utf-8
        f.write_bytes(b"\xff\xfe\x00\x00import requests\n")
        # Should silently return None — no exception
        assert ast_scanner.scan_file(f, "requests") is None


# --------------------------------------------------------------------------- #
# scan_project
# --------------------------------------------------------------------------- #

class TestScanProject:
    def test_scan_project_finds_matches(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("import requests\nrequests.get('u')\n")
        (tmp_path / "b.py").write_text("import os\n")  # no match
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "c.py").write_text("from requests import post\npost('u')\n")

        results = ast_scanner.scan_project(str(tmp_path), "requests")
        files = {Path(r["file"]).name for r in results}
        assert "a.py" in files
        assert "c.py" in files
        assert "b.py" not in files

    def test_scan_project_skips_venv(self, tmp_path: Path):
        venv = tmp_path / ".venv" / "lib"
        venv.mkdir(parents=True)
        (venv / "lib.py").write_text("import requests\nrequests.get('u')\n")
        (tmp_path / "real.py").write_text("import requests\nrequests.get('u')\n")

        results = ast_scanner.scan_project(str(tmp_path), "requests")
        files = [Path(r["file"]).name for r in results]
        assert "real.py" in files
        assert "lib.py" not in files

    def test_scan_project_skips_node_modules(self, tmp_path: Path):
        nm = tmp_path / "node_modules"
        nm.mkdir()
        (nm / "x.py").write_text("import requests\nrequests.get('u')\n")
        (tmp_path / "real.py").write_text("import requests\nrequests.get('u')\n")

        results = ast_scanner.scan_project(str(tmp_path), "requests")
        assert all("node_modules" not in r["file"] for r in results)

    def test_scan_project_empty_dir(self, tmp_path: Path):
        assert ast_scanner.scan_project(str(tmp_path), "requests") == []
