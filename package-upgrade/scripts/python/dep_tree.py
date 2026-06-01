#!/usr/bin/env python3
"""Dependency tree analyzer for package upgrades.

Usage:
    python dep_tree.py <project_path> <package_name> \
        [--pkg-manager pip|poetry|uv] [--target-version <v>] [--no-probe]

Output: JSON with dependency classification and tree information.

Phase 2 contract — fields are aligned with dep_tree_js.js / dep_tree_go.py
where it makes sense for Python:

    {
      "package_name": str,
      "current_version": str,
      "dependency_type": "direct" | "transitive" | "both" | "unknown",
      "is_direct": bool,
      "is_transitive": bool,
      "parent_packages": [str],            # direct parents (closest to root)
      "version_constraints": {parent: spec_string},
      "target_version": str | "",          # echoed back from --target-version
      "parent_analyses": [{name, latest, requires_target_spec, status, reason}],
      "upgrade_strategies": [{type, mechanism, confidence, ...}],  # sorted desc
      "recommended_strategy": str,         # = upgrade_strategies[0].type
      "full_tree": <pipdeptree/poetry/uv raw output>,
    }

Canonical strategy `type` values are aligned across the three languages:
`direct_bump`, `lock_only`, `bump_parent`, `pin_add`, `pin_update`,
`pin_source` (Python/Go only). Each strategy also carries a `mechanism`
string (e.g. `uv-override`, `poetry-dep`, `pip-constraints`) describing the
language-specific tool that applies it.

`--target-version` and `--no-probe` are optional. Without target_version we
cannot evaluate whether a parent constraint "satisfies" or "would_not_help",
so parent_analyses entries return status="unknown" and the strategy ranking
falls back to dependency_type only.
"""

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import requests as _requests  # type: ignore
except ImportError:
    _requests = None  # type: ignore

# TOML parsing is best-effort. tomllib is stdlib only on Python 3.11+; the skill
# targets 3.10, so we attempt the import and fall back to a minimal line scanner
# below (see _detect_existing_override). We never add a heavyweight TOML dep.
try:
    import tomllib as _tomllib  # type: ignore
except ImportError:  # Python 3.10
    try:
        import tomli as _tomllib  # type: ignore
    except ImportError:
        _tomllib = None  # type: ignore


def get_dep_tree_pip(project_path: str) -> Dict[str, Any]:
    """Get dependency tree using pipdeptree."""
    try:
        result = subprocess.run(
            ["pipdeptree", "--json-tree"],
            capture_output=True,
            text=True,
            cwd=project_path,
            check=True,
        )
        return {"data": json.loads(result.stdout), "format": "json"}
    except subprocess.CalledProcessError as e:
        return {"error": f"pipdeptree failed: {e.stderr}", "data": []}
    except FileNotFoundError:
        return {"error": "pipdeptree not installed. Run: pip install pipdeptree", "data": []}


def get_dep_tree_poetry(project_path: str) -> Dict[str, Any]:
    """Get dependency tree using poetry show."""
    try:
        result = subprocess.run(
            ["poetry", "show", "--tree", "--no-ansi"],
            capture_output=True,
            text=True,
            cwd=project_path,
            check=True,
        )
        return {"raw": result.stdout, "format": "text"}
    except subprocess.CalledProcessError as e:
        return {"error": f"poetry failed: {e.stderr}", "raw": ""}
    except FileNotFoundError:
        return {"error": "poetry not installed", "raw": ""}


def get_dep_tree_uv(project_path: str) -> Dict[str, Any]:
    """Get dependency tree using uv pip tree."""
    try:
        result = subprocess.run(
            ["uv", "pip", "tree"], capture_output=True, text=True, cwd=project_path, check=True
        )
        return {"raw": result.stdout, "format": "text"}
    except subprocess.CalledProcessError as e:
        return {"error": f"uv failed: {e.stderr}", "raw": ""}
    except FileNotFoundError:
        return {"error": "uv not installed", "raw": ""}


def get_installed_version(package_name: str, pkg_manager: str, project_path: str) -> str:
    """Get the currently installed version of a package."""
    cmds = {
        "pip": ["pip", "show", package_name],
        "poetry": ["poetry", "show", package_name],
        "uv": ["uv", "pip", "show", package_name],
    }

    try:
        result = subprocess.run(
            cmds.get(pkg_manager, cmds["pip"]), capture_output=True, text=True, cwd=project_path
        )
        for line in result.stdout.splitlines():
            if line.lower().startswith("version:"):
                return line.split(":", 1)[1].strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    return "unknown"


def find_parents_in_tree(
    package_name: str, tree_data: Any, format_type: str = "json"
) -> Tuple[List[str], Dict[str, str]]:
    """Recursively search dependency tree to find parent packages.

    Returns:
        Tuple of (parent_packages, version_constraints)
    """
    parents = []
    constraints = {}

    if format_type == "json" and isinstance(tree_data, dict):
        data = tree_data.get("data", [])
        if isinstance(data, list):
            for pkg in data:
                _search_json_tree(package_name.lower(), pkg, parents, constraints)

    return parents, constraints


def _search_json_tree(
    target: str,
    node: Dict,
    parents: List[str],
    constraints: Dict[str, str],
    parent_name: Optional[str] = None,
):
    """Helper to recursively search JSON tree structure."""
    pkg_name = node.get("package_name", node.get("key", "")).lower()

    # Check dependencies of current node
    dependencies = node.get("dependencies", [])
    for dep in dependencies:
        dep_name = dep.get("package_name", dep.get("key", "")).lower()
        if dep_name == target:
            # Found target as dependency
            if pkg_name and pkg_name not in parents:
                parents.append(pkg_name)
                # Try to extract version constraint
                installed_ver = dep.get("installed_version", "")
                required_ver = dep.get("required_version", "")
                if required_ver:
                    constraints[pkg_name] = required_ver
                elif installed_ver:
                    constraints[pkg_name] = f"=={installed_ver}"

        # Recurse into dependency's dependencies
        if dep.get("dependencies"):
            _search_json_tree(target, dep, parents, constraints, pkg_name)


def classify_dependency(
    package_name: str, dep_tree: Dict[str, Any], dep_files: List[str], format_type: str = "json"
) -> Dict[str, Any]:
    """Classify package as direct, transitive, or both dependency."""
    is_direct = False
    parent_packages = []
    version_constraints = {}

    # Check if package is directly declared in dependency files
    package_pattern = re.compile(rf"^{re.escape(package_name)}\b", re.MULTILINE | re.IGNORECASE)

    for dep_file in dep_files:
        try:
            content = Path(dep_file).read_text()
            if package_pattern.search(content):
                is_direct = True
                break
        except (FileNotFoundError, IOError):
            continue

    # Find parent packages from dependency tree
    parent_packages, version_constraints = find_parents_in_tree(package_name, dep_tree, format_type)

    is_transitive = len(parent_packages) > 0

    # Determine dependency type
    if is_direct and is_transitive:
        dep_type = "both"
    elif is_direct:
        dep_type = "direct"
    elif is_transitive:
        dep_type = "transitive"
    else:
        dep_type = "unknown"

    return {
        "dependency_type": dep_type,
        "is_direct": is_direct,
        "is_transitive": is_transitive,
        "parent_packages": parent_packages,
        "version_constraints": version_constraints,
    }


# --------------------------------------------------------------------------- #
# Version specifier parsing — PEP 440 best-effort.
#
# Used by both `lock_only` viability check (current parents' constraints) and
# `bump_parent` analysis (parent@latest's requires_dist). Returns None on any
# parse ambiguity so callers can mark status="unknown" instead of guessing.
# --------------------------------------------------------------------------- #

_SPEC_OP = re.compile(r"\s*(===|==|>=|<=|!=|~=|>|<)\s*([\w.+*\-]+)\s*")


def parse_version_spec(spec: str) -> List[Tuple[str, str]]:
    """Parse a PEP 440 spec like '>=1.0,<2.0' into [(op, ver), ...].

    Returns [] when the input has no recognisable specifier clauses.
    """
    if not spec:
        return []
    out: List[Tuple[str, str]] = []
    for piece in spec.split(","):
        m = _SPEC_OP.match(piece.strip())
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def version_tuple(v: str) -> Tuple[int, ...]:
    """Convert a version string to a comparable int tuple. Best-effort PEP 440.

    Returns () on parse failure so callers know to treat the comparison as
    unknown. Strips epoch ('1!2.0') and any pre/post/dev release suffix
    ('1.0a1', '1.0.post1', '1.0+local').
    """
    if not v:
        return ()
    # Strip epoch (the part before '!')
    if "!" in v:
        v = v.split("!", 1)[1]
    # Strip local-version segment ('+local')
    v = v.split("+", 1)[0]
    # Strip anything from first non-(digit|dot)
    m = re.match(r"^(\d+(?:\.\d+)*)", v)
    if not m:
        return ()
    parts = []
    for p in m.group(1).split("."):
        if not p.isdigit():
            return ()
        parts.append(int(p))
    return tuple(parts)


def _cmp(a: Tuple[int, ...], b: Tuple[int, ...]) -> int:
    """Compare two version tuples, padding the shorter one with zeros."""
    n = max(len(a), len(b))
    pa = a + (0,) * (n - len(a))
    pb = b + (0,) * (n - len(b))
    if pa < pb:
        return -1
    if pa > pb:
        return 1
    return 0


def spec_allows(spec: str, version: str) -> Optional[bool]:
    """Returns True if `version` satisfies `spec`, False if not, None if undetermined.

    ~=, ===, and wildcard versions ('1.*') return None — we don't try to be
    clever, we'd rather say "unknown" and let the LLM decide than misclassify.
    """
    ops = parse_version_spec(spec)
    if not ops:
        return None
    v = version_tuple(version)
    if not v:
        return None
    for op, ver in ops:
        if "*" in ver or op in ("~=", "==="):
            return None
        t = version_tuple(ver)
        if not t:
            return None
        cmp = _cmp(v, t)
        if op == "==":
            if cmp != 0:
                return False
        elif op == "!=":
            if cmp == 0:
                return False
        elif op == ">=":
            if cmp < 0:
                return False
        elif op == "<=":
            if cmp > 0:
                return False
        elif op == ">":
            if cmp <= 0:
                return False
        elif op == "<":
            if cmp >= 0:
                return False
        else:
            return None
    return True


# --------------------------------------------------------------------------- #
# PyPI probing for parent_analyses
# --------------------------------------------------------------------------- #


def _normalize_pypi_name(name: str) -> str:
    """PyPI normalises names: lowercase, runs of [-_.] collapse to single '-'."""
    return re.sub(r"[-_.]+", "-", name.lower())


def fetch_pypi_metadata(package_name: str, timeout: int = 10) -> Optional[Dict[str, Any]]:
    """Fetch package metadata from PyPI JSON API.

    Returns None on any failure (network, parse, 404). Caller distinguishes
    "no_dep" (parsed successfully, target absent from requires_dist) from
    "unknown" (this returned None) themselves.
    """
    if _requests is None:
        return None
    try:
        resp = _requests.get(f"https://pypi.org/pypi/{package_name}/json", timeout=timeout)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:  # noqa: BLE001 — network/JSON failures all collapse to None
        return None


def extract_target_spec_from_requires(
    requires_dist: List[str], target_name: str
) -> Tuple[bool, str]:
    """From a requires_dist list, find the entry for `target_name` and return
    (found, spec_string). Spec string is empty when the dep is listed bare.

    PEP 508 entries look like:
        'requests (>=2.0,<3.0)'           # legacy parenthesised form
        'requests>=2.0'                   # PEP 508 modern form
        'requests'                        # bare, no constraint
        'requests; python_version >= "3.8"'  # with marker
    """
    target_norm = _normalize_pypi_name(target_name)
    for req in requires_dist or []:
        bare = req.split(";", 1)[0].strip()
        # Match: name + optional (spec) + optional spec_without_parens
        m = re.match(
            r"^([A-Za-z0-9_.\-]+)\s*(?:\[(.*?)\])?\s*(?:\(([^)]*)\))?\s*([<>=!~].*)?$",
            bare,
        )
        if not m:
            continue
        if _normalize_pypi_name(m.group(1)) != target_norm:
            continue
        paren_spec = (m.group(3) or "").strip()
        trailing_spec = (m.group(4) or "").strip()
        return True, paren_spec or trailing_spec
    return False, ""


def analyze_parent(
    parent_name: str,
    target_name: str,
    target_version: Optional[str],
    probe_enabled: bool = True,
) -> Dict[str, Any]:
    """For one direct parent, classify whether bumping it to latest helps reach
    `target_version` for `target_name`.

    Status values:
        "satisfies"          — parent@latest's spec on target allows target_version
        "would_not_help_pin" — parent@latest still excludes target_version
        "no_dep"             — parent@latest no longer requires target
        "unknown"            — could not probe (network / parse / disabled / no target_version)
    """
    info: Dict[str, Any] = {
        "name": parent_name,
        "latest": "",
        "requires_target_spec": "",
        "status": "unknown",
        "reason": "",
    }
    if not probe_enabled:
        info["reason"] = "PyPI probe disabled (--no-probe)"
        return info
    if not target_version:
        info["reason"] = "no --target-version provided; cannot evaluate parent constraint"
        return info
    if _requests is None:
        info["reason"] = "`requests` library not installed; cannot probe PyPI"
        return info

    meta = fetch_pypi_metadata(parent_name)
    if meta is None:
        info["reason"] = f"PyPI fetch failed for {parent_name} (network / 404)"
        return info

    info["latest"] = meta.get("info", {}).get("version", "")
    requires_dist = meta.get("info", {}).get("requires_dist") or []

    found, spec = extract_target_spec_from_requires(requires_dist, target_name)
    if not found:
        info["status"] = "no_dep"
        info["reason"] = (
            f"{parent_name}@{info['latest']} no longer requires {target_name} "
            f"(not in requires_dist)"
        )
        return info

    info["requires_target_spec"] = spec
    if not spec:
        # Bare requirement: any version is allowed
        info["status"] = "satisfies"
        info["reason"] = (
            f"{parent_name}@{info['latest']} requires {target_name} with no version "
            f"pin — any version including {target_version} is acceptable"
        )
        return info

    allowed = spec_allows(spec, target_version)
    if allowed is True:
        info["status"] = "satisfies"
        info["reason"] = (
            f"{parent_name}@{info['latest']} requires {target_name} {spec} "
            f"(allows desired {target_version})"
        )
    elif allowed is False:
        info["status"] = "would_not_help_pin"
        info["reason"] = (
            f"{parent_name}@{info['latest']} still constrains {target_name} {spec} — "
            f"excludes desired {target_version}; waiting on upstream release"
        )
    else:
        info["reason"] = (
            f"could not evaluate {parent_name}@{info['latest']}'s spec "
            f"({spec}) against {target_version} — unsupported operator or wildcard"
        )
    return info


# --------------------------------------------------------------------------- #
# Existing target-specific override / pin detection
#
# Phase 2 needs to know whether the target ALREADY has a forced pin in the
# manifest so it can choose `pin_update` (edit the existing entry) over
# `pin_add` (introduce a new one) — and `pin_source` when the existing pin is
# a source redirect (fork / git) rather than a version. Mirrors the JS
# findOverridesPin() and Go replace_directive detection.
#
# TOML is parsed with tomllib/tomli when available (3.11+ / installed), else a
# minimal line scanner — the same dependency-free spirit as the rest of this
# script (which regex-scans manifests). Returns:
#   {"exists": bool, "mechanism": str, "kind": "version"|"source",
#    "current_value": str|None}
# --------------------------------------------------------------------------- #


def _load_toml(path: Path) -> Optional[Dict[str, Any]]:
    """Parse a TOML file, or None when no parser is available / on error."""
    if _tomllib is None:
        return None
    try:
        with path.open("rb") as fh:
            data: Dict[str, Any] = _tomllib.load(fh)
            return data
    except Exception:  # noqa: BLE001 — malformed TOML degrades to scanner/None
        return None


def _name_in_req_string(req: str, target_norm: str) -> bool:
    """True when a PEP 508 requirement string names `target_norm`."""
    bare = req.split(";", 1)[0].strip()
    m = re.match(r"^([A-Za-z0-9_.\-]+)", bare)
    if not m:
        return False
    return _normalize_pypi_name(m.group(1)) == target_norm


def _scan_override_lines(text: str, target_norm: str) -> Optional[Dict[str, Any]]:
    """Minimal fallback scanner for uv override/constraint/source entries when
    no TOML parser is available. Best-effort; returns None when nothing matched.
    """
    # [tool.uv.sources] table: `target = { git = "...", ... }`
    in_sources = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line.startswith("["):
            in_sources = line.replace(" ", "") == "[tool.uv.sources]"
            continue
        if in_sources and "=" in line:
            key = line.split("=", 1)[0].strip().strip('"')
            if _normalize_pypi_name(key) == target_norm:
                return {
                    "exists": True,
                    "mechanism": "uv-source",
                    "kind": "source",
                    "current_value": line.split("=", 1)[1].strip(),
                }
    # override-dependencies / constraint-dependencies arrays (may span lines)
    for field, mechanism in (
        ("override-dependencies", "uv-override"),
        ("constraint-dependencies", "uv-constraint"),
    ):
        m = re.search(rf"{field}\s*=\s*\[(.*?)\]", text, re.S)
        if not m:
            continue
        for item in re.findall(r'"([^"]+)"|\'([^\']+)\'', m.group(1)):
            req = item[0] or item[1]
            if _name_in_req_string(req, target_norm):
                return {
                    "exists": True,
                    "mechanism": mechanism,
                    "kind": "version",
                    "current_value": req,
                }
    return None


def _detect_in_pyproject(data: Dict[str, Any], target_norm: str) -> Optional[Dict[str, Any]]:
    """Inspect a parsed pyproject.toml for an existing target pin/override."""
    tool = data.get("tool", {}) if isinstance(data, dict) else {}
    uv = tool.get("uv", {}) if isinstance(tool, dict) else {}

    # [tool.uv.sources] — a source redirect (fork / git / url)
    sources = uv.get("sources", {}) if isinstance(uv, dict) else {}
    if isinstance(sources, dict):
        for name, spec in sources.items():
            if _normalize_pypi_name(name) == target_norm:
                return {
                    "exists": True,
                    "mechanism": "uv-source",
                    "kind": "source",
                    "current_value": json.dumps(spec) if not isinstance(spec, str) else spec,
                }

    # [tool.uv] override-dependencies / constraint-dependencies — version pins
    for field, mechanism in (
        ("override-dependencies", "uv-override"),
        ("constraint-dependencies", "uv-constraint"),
    ):
        entries = uv.get(field, []) if isinstance(uv, dict) else []
        if isinstance(entries, list):
            for req in entries:
                if isinstance(req, str) and _name_in_req_string(req, target_norm):
                    return {
                        "exists": True,
                        "mechanism": mechanism,
                        "kind": "version",
                        "current_value": req,
                    }

    # [tool.poetry.dependencies] + [tool.poetry.group.*.dependencies]
    poetry = tool.get("poetry", {}) if isinstance(tool, dict) else {}
    if isinstance(poetry, dict):
        dep_tables: List[Tuple[str, Any]] = [("poetry-dep", poetry.get("dependencies", {}))]
        groups = poetry.get("group", {})
        if isinstance(groups, dict):
            for grp in groups.values():
                if isinstance(grp, dict):
                    dep_tables.append(("poetry-group", grp.get("dependencies", {})))
        for mechanism, table in dep_tables:
            if not isinstance(table, dict):
                continue
            for name, spec in table.items():
                if _normalize_pypi_name(name) != target_norm:
                    continue
                # A dict spec with git/url/path is a source redirect; a string
                # (or {version=...}) is a version pin.
                if isinstance(spec, dict) and any(k in spec for k in ("git", "url", "path")):
                    return {
                        "exists": True,
                        "mechanism": mechanism,
                        "kind": "source",
                        "current_value": json.dumps(spec),
                    }
                return {
                    "exists": True,
                    "mechanism": mechanism,
                    "kind": "version",
                    "current_value": spec if isinstance(spec, str) else json.dumps(spec),
                }
    return None


def detect_existing_override(project_path: str, package_name: str) -> Dict[str, Any]:
    """Detect whether `package_name` already has a forced pin / source override
    in the project's manifests.

    Looks at, in priority order:
      - pyproject.toml: [tool.uv] override/constraint-dependencies,
        [tool.uv.sources], [tool.poetry.dependencies], [tool.poetry.group.*]
      - root constraints.txt / requirements.in `-c` references (version pins)

    Returns {"exists", "mechanism", "kind", "current_value"}.
    """
    target_norm = _normalize_pypi_name(package_name)
    root = Path(project_path)

    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        data = _load_toml(pyproject)
        if data is not None:
            hit = _detect_in_pyproject(data, target_norm)
            if hit:
                return hit
        else:
            # No TOML parser available — minimal line scan for uv tables.
            try:
                hit = _scan_override_lines(pyproject.read_text(encoding="utf-8"), target_norm)
            except OSError:
                hit = None
            if hit:
                return hit

    # constraints.txt referenced via `-c` from requirements.in, or a root
    # constraints.txt — a target line there is a version pin (pip-tools).
    referenced: List[Path] = []
    req_in = root / "requirements.in"
    if req_in.exists():
        try:
            for raw in req_in.read_text(encoding="utf-8").splitlines():
                m = re.match(r"^\s*-c\s+(\S+)", raw)
                if m:
                    referenced.append((root / m.group(1)).resolve())
        except OSError:
            pass
    default_constraints = root / "constraints.txt"
    if default_constraints.exists():
        referenced.append(default_constraints)
    for cfile in referenced:
        try:
            for raw in cfile.read_text(encoding="utf-8").splitlines():
                line = raw.split("#", 1)[0].strip()
                if line and _name_in_req_string(line, target_norm):
                    return {
                        "exists": True,
                        "mechanism": "pip-constraints",
                        "kind": "version",
                        "current_value": line,
                    }
        except OSError:
            continue

    return {"exists": False, "mechanism": "", "kind": "", "current_value": None}


# --------------------------------------------------------------------------- #
# Strategy composition
# --------------------------------------------------------------------------- #

# Confidence weights for bump_parent strategies — mirrors dep_tree_go.py's
# weighting so the LLM can reason uniformly across languages.
_PARENT_STATUS_CONFIDENCE = {
    "satisfies": 0.75,
    "would_not_help_pin": 0.05,
    "no_dep": 0.10,
    "unknown": 0.25,
}


def compose_strategies(
    classification: Dict[str, Any],
    parent_analyses: List[Dict[str, Any]],
    has_lockfile: bool,
    target_version: Optional[str],
    existing_override: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Build ranked candidate upgrade strategies for Python.

    Canonical strategies emitted (each with `type` + `mechanism` + `confidence`):
        direct_bump   — target IS a direct dep
        lock_only     — transitive AND current parents already allow target
                        (requires_consent: touches the lock pin directly)
        bump_parent   — transitive; bump a parent to widen the constraint
        pin_update    — transitive; an EXISTING version override/pin is edited
        pin_source    — transitive; an EXISTING source redirect (fork/git) edited,
                        or offered as a fork fallback when no other path works
        pin_add       — transitive; no existing pin → add a new forced version pin
                        (fallback that replaces the former parent-then-target placeholder)
        unknown       — placeholder when nothing above applied

    `existing_override` is detect_existing_override()'s result. It decides
    whether the manifest-pin path emits `pin_update`/`pin_source` (edit the
    existing entry) vs `pin_add` (introduce a new one).
    """
    strategies: List[Dict[str, Any]] = []
    is_direct = classification["is_direct"]
    is_transitive = classification["is_transitive"]
    constraints = classification.get("version_constraints", {}) or {}
    override = existing_override or {
        "exists": False,
        "mechanism": "",
        "kind": "",
        "current_value": None,
    }

    if is_direct:
        strategies.append(
            {
                "type": "direct_bump",
                "mechanism": "poetry-dep",
                "confidence": 0.95,
                "rationale": (
                    "Target is a direct dependency. Bump the declaration "
                    "(pyproject.toml / requirements.txt) and refresh the lock file."
                ),
                "apply_hint": (
                    "poetry add <pkg>@<ver>  |  uv add '<pkg>>=<ver>'  |  "
                    "edit requirements.txt + pip install --upgrade"
                ),
            }
        )

    if is_transitive and has_lockfile and target_version and constraints:
        # All current parent constraints must allow the target version. If any
        # constraint is unparseable we degrade to "unknown" and skip lock_only —
        # safer to recommend bump_parent explicitly than to risk a silent
        # lock-only that the resolver later rejects.
        allow_results = [spec_allows(c, target_version) for c in constraints.values()]
        if all(r is True for r in allow_results):
            strategies.append(
                {
                    "type": "lock_only",
                    "mechanism": "uv-constraint",
                    "confidence": 0.85,
                    "status": "satisfies",
                    "requires_consent": True,
                    "warning": (
                        "Touches the lock file directly without recording the bump in "
                        "the manifest. The parents' constraints allow it TODAY, but a "
                        "later parent upgrade can silently hold the pin back (re-resolve "
                        "to an older target) since nothing in the manifest expresses the "
                        "intent. Confirm with the user before proceeding."
                    ),
                    "rationale": (
                        f"All {len(constraints)} parent constraint(s) already allow "
                        f"{target_version}. Refreshing the lock only leaves the manifest "
                        "untouched — fast, but the bump is invisible to the manifest, so "
                        "a future parent upgrade may re-resolve the target back down."
                    ),
                    "apply_hint": (
                        "poetry update <pkg>  |  uv lock --upgrade-package <pkg>  |  "
                        "pip-compile --upgrade-package <pkg> requirements.in"
                    ),
                }
            )

    if is_transitive and parent_analyses:
        for pa in parent_analyses:
            status = pa.get("status", "unknown")
            strategies.append(
                {
                    "type": "bump_parent",
                    "mechanism": "poetry-dep",
                    "parent": pa["name"],
                    "confidence": _PARENT_STATUS_CONFIDENCE.get(status, 0.25),
                    "status": status,
                    "reason": pa.get("reason", ""),
                    "rationale": (
                        f"Bump direct parent `{pa['name']}` to "
                        f"{pa.get('latest') or 'latest'} — analysis: {status}."
                    ),
                    "apply_hint": (
                        f"poetry add {pa['name']}@latest  |  "
                        f"uv add '{pa['name']}>={pa.get('latest', '')}'"
                    ),
                }
            )

    # Manifest-pin path. When an existing override/pin is present we EDIT it
    # (pin_update / pin_source); otherwise we ADD a new one (pin_add). pin_add
    # is also the fallback that fires when transitive and nothing else applied
    # (the role formerly held by the parent-then-target placeholder).
    if is_transitive and not is_direct:
        if override.get("exists"):
            if override.get("kind") == "source":
                strategies.append(
                    {
                        "type": "pin_source",
                        "mechanism": override.get("mechanism") or "uv-source",
                        "confidence": 0.65,
                        "requires_consent": True,
                        "current_value": override.get("current_value"),
                        "rationale": (
                            "An existing SOURCE redirect (fork / git / url) for the target "
                            f"is declared via {override.get('mechanism') or 'a source entry'}. "
                            "Update that source to the version/ref that carries the fix."
                        ),
                        "apply_hint": (
                            "Edit [tool.uv.sources] / the poetry git-or-url dependency for "
                            "the target, then refresh the lock."
                        ),
                    }
                )
            else:
                strategies.append(
                    {
                        "type": "pin_update",
                        "mechanism": override.get("mechanism") or "uv-override",
                        "confidence": 0.80,
                        "current_value": override.get("current_value"),
                        "rationale": (
                            "An existing forced version pin for the target is declared via "
                            f"{override.get('mechanism') or 'an override entry'} "
                            f"(current: {override.get('current_value')}). Update that entry "
                            "to the new version — preferable to adding a second pin."
                        ),
                        "apply_hint": (
                            "Edit the existing override/constraint entry for the target, then "
                            "refresh the lock."
                        ),
                    }
                )
        else:
            strategies.append(
                {
                    "type": "pin_add",
                    "mechanism": "uv-override",
                    "confidence": 0.30,
                    "requires_consent": True,
                    "rationale": (
                        "No existing manifest pin and no parent release widens the "
                        "constraint yet. Add a NEW forced version pin (uv "
                        "override-dependencies / constraint, poetry direct add, or a "
                        "pip constraints.txt entry) so the bump is expressed in the "
                        "manifest. Changes resolution for all consumers of the "
                        "transitive — requires user consent."
                    ),
                    "apply_hint": (
                        "uv add '<pkg>>=<ver>' (or [tool.uv] override-dependencies)  |  "
                        "poetry add '<pkg>>=<ver>'  |  add to constraints.txt"
                    ),
                }
            )
            # pin_source as a low-confidence fork fallback (no version release helps).
            strategies.append(
                {
                    "type": "pin_source",
                    "mechanism": "uv-source",
                    "confidence": 0.10,
                    "requires_consent": True,
                    "rationale": (
                        "Last resort: if no published version carries the fix, point the "
                        "target at a fork / git ref via [tool.uv.sources] or a poetry "
                        "git/url dependency. Source redirects are local to this project."
                    ),
                    "apply_hint": (
                        "Add [tool.uv.sources] target = { git = '...', rev = '...' }  |  "
                        "poetry add 'git+https://.../target.git@<ref>'"
                    ),
                }
            )

    if not strategies:
        strategies.append(
            {
                "type": "unknown",
                "mechanism": "",
                "confidence": 0.0,
                "rationale": ("Could not classify an upgrade path. Manual review required."),
            }
        )

    strategies.sort(key=lambda s: s["confidence"], reverse=True)
    return strategies


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main():
    parser = argparse.ArgumentParser(description="Analyze dependency tree for a package")
    parser.add_argument("project_path", help="Path to the project directory")
    parser.add_argument("package_name", help="Name of the package to analyze")
    parser.add_argument(
        "--pkg-manager",
        choices=["pip", "poetry", "uv"],
        default="pip",
        help="Package manager to use",
    )
    parser.add_argument(
        "--target-version", default="", help="Desired version for parent analysis (PyPI probing)"
    )
    parser.add_argument(
        "--no-probe",
        action="store_true",
        help="Skip PyPI probing for parent_analyses (offline mode)",
    )
    args = parser.parse_args()

    # Get dependency tree based on package manager
    tree_funcs = {"pip": get_dep_tree_pip, "poetry": get_dep_tree_poetry, "uv": get_dep_tree_uv}

    dep_tree = tree_funcs[args.pkg_manager](args.project_path)
    format_type = dep_tree.get("format", "json")

    # Get installed version
    version = get_installed_version(args.package_name, args.pkg_manager, args.project_path)

    # Find dependency files
    dep_files_raw = subprocess.run(
        [
            "find",
            args.project_path,
            "-maxdepth",
            "2",
            "(",
            "-name",
            "requirements*.txt",
            "-o",
            "-name",
            "pyproject.toml",
            "-o",
            "-name",
            "setup.py",
            "-o",
            "-name",
            "setup.cfg",
            ")",
            "-not",
            "-path",
            "*/.venv/*",
            "-not",
            "-path",
            "*/venv/*",
        ],
        capture_output=True,
        text=True,
    )
    dep_files = [f for f in dep_files_raw.stdout.strip().splitlines() if f]

    # Classify dependency
    classification = classify_dependency(args.package_name, dep_tree, dep_files, format_type)

    # Lockfile hint: any of these counts. Cheap detection — caller already has
    # the authoritative answer from detect_env.sh, but we want this script to
    # be standalone-runnable too.
    project_root = Path(args.project_path)
    has_lockfile = any(
        (project_root / name).exists()
        for name in (
            "poetry.lock",
            "uv.lock",
            "requirements.lock",
            "requirements.txt.lock",
            "requirements-lock.txt",
        )
    )

    # Probe each direct parent for whether bumping it would help reach target_version
    target_version = args.target_version or ""
    probe_enabled = (not args.no_probe) and bool(target_version)
    parent_analyses: List[Dict[str, Any]] = []
    for parent in classification["parent_packages"]:
        parent_analyses.append(
            analyze_parent(
                parent_name=parent,
                target_name=args.package_name,
                target_version=target_version or None,
                probe_enabled=probe_enabled,
            )
        )

    # Detect whether the target already has a forced pin / source override in
    # the manifest — decides pin_update / pin_source vs pin_add downstream.
    existing_override = detect_existing_override(args.project_path, args.package_name)

    strategies = compose_strategies(
        classification,
        parent_analyses,
        has_lockfile=has_lockfile,
        target_version=target_version or None,
        existing_override=existing_override,
    )

    # Build result — existing fields preserved verbatim, new fields appended.
    result = {
        "package_name": args.package_name,
        "current_version": version,
        **classification,
        "target_version": target_version,
        "parent_analyses": parent_analyses,
        "existing_override": existing_override,
        "upgrade_strategies": strategies,
        "recommended_strategy": strategies[0]["type"] if strategies else "unknown",
        "full_tree": dep_tree,
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
