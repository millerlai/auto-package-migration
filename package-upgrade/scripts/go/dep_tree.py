#!/usr/bin/env python3
"""dep_tree_go.py — Dependency tree analyzer for Go modules.

Usage:
    python3 dep_tree_go.py <project_path> <module_path> [--target-version <v>]

Strategy:
    1. Parse `go.mod` to find direct vs indirect entries and replace directives.
    2. `go list -m -json all` (readonly) to enrich version + indirect info.
    3. `go mod graph` to walk up the dependency graph and find direct parents
       for an indirect target.
    4. `go mod why -m <target>` to determine if target is on the main module's
       build path (catches the indirect-but-unused trap — see
       references/go_replace_semantics.md).
    5. For each direct parent: download its latest `.mod` (in a scratch module
       so the project's GOMODCACHE/go.sum is not touched) and parse what the
       parent pins / replaces for the target.
    6. `go list -m -versions <path>` to get available versions.
    7. Probe `<path>/v2`, `<path>/v3`, ... for available major variants.
    8. Compose ranked upgrade_strategies (confidence-sorted).

Read-only contract:
    All `go` invocations use `-mod=readonly` (or `GOFLAGS=-mod=readonly`)
    so analysis never mutates the project's `go.mod` / `go.sum`. Parent-mod
    probes run inside a temporary scratch module to keep download cache
    activity off the project.

Output schema (aligned with dep_tree_js.js / dep_tree.py):
    {
      "package_name": str,
      "language": "go",
      "pkg_manager": "gomod",
      "current_version": str,           # e.g. "v1.2.3"
      "current_module_path": str,       # e.g. "github.com/foo/bar" or ".../v2"
      "target_version": str | None,
      "target_module_path": str | None,
      "is_major_version_jump": bool,
      "dependency_type": "direct" | "indirect" | "not_present",
      "is_direct": bool,
      "is_indirect": bool,
      "parent_packages": [str],         # direct + transitive parents (legacy field)
      "direct_parents": [str],          # parents that are themselves in go.mod
      "transitive_parents": [str],
      "parent_chains": [[str]],         # ordered from target → direct parent
      "version_constraints": {str: str},
      "available_versions": [str],
      "latest_in_current_major": str | None,
      "available_majors": [{"path": str, "latest": str, "version_count": int}],
      "replace_directive": {old, old_version, new, new_version} | None,
      "go_mod_why_status": "needed" | "not_needed_by_main_module"
                         | "not_in_module_graph" | "unknown",
      "parent_analyses": [{name, latest, pins_target_to, uses_replace_for_target,
                           status, reason}],
      "is_vendored": bool,
      "go_directive": str,
      "upgrade_strategies": [...],      # each has `confidence` 0..1; sorted desc
      "recommended_strategy": str,
      "source": "go-list+go-mod-graph",
      "errors": [str]
    }
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import deque
from pathlib import Path

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def run(
    cmd: list[str],
    cwd: str | None = None,
    timeout: int = 30,
    env: dict | None = None,
) -> tuple[int, str, str]:
    """Run a subprocess, return (returncode, stdout, stderr).

    For `go` commands we always inject `GOFLAGS=-mod=readonly` (unless caller
    overrides) so analysis never mutates the project's go.mod / go.sum.
    """
    full_env = os.environ.copy()
    is_go = bool(cmd) and (cmd[0] == "go" or cmd[0].endswith("/go"))
    if is_go and "GOFLAGS" not in (env or {}):
        existing = full_env.get("GOFLAGS", "")
        if "-mod=" not in existing:
            full_env["GOFLAGS"] = (existing + " -mod=readonly").strip()
    if env:
        full_env.update(env)

    try:
        r = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=full_env,
        )
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s: {' '.join(cmd)}"


def strip_major_suffix(path: str) -> str:
    """github.com/foo/bar/v2 → github.com/foo/bar"""
    return re.sub(r"/v[2-9][0-9]*$", "", path)


def major_of(version: str) -> int | None:
    """v1.2.3 → 1, v0.9.0 → 0. Returns None for malformed input."""
    m = re.match(r"^v(\d+)", version or "")
    return int(m.group(1)) if m else None


def module_path_for_version(base_path: str, version: str) -> str:
    """Return canonical module path for a target version.

    >>> module_path_for_version("example.com/foo", "v2.0.0")
    'example.com/foo/v2'
    >>> module_path_for_version("example.com/foo", "v1.5.0")
    'example.com/foo'
    """
    m = major_of(version)
    if m is not None and m >= 2:
        return f"{base_path}/v{m}"
    return base_path


def version_tuple(v: str) -> tuple:
    """Best-effort tuple for sorting. v1.2.3 → (1, 2, 3).
    Pre-release suffixes like -rc1 sort below the plain version."""
    if not v.startswith("v"):
        return (0,)
    core = v[1:].split("+", 1)[0]
    pre = ""
    if "-" in core:
        core, pre = core.split("-", 1)
    parts = []
    for p in core.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    # Pre-release sorts BEFORE release of same core; use ("", ) > ("rc1",)
    return (*parts, "" if not pre else f"~{pre}")


# --------------------------------------------------------------------------- #
# go.mod parsing
# --------------------------------------------------------------------------- #


def parse_gomod(path: str) -> dict:
    """Parse go.mod into structured form.

    Returns:
        {
          "module": str,
          "go": str,
          "toolchain": str,
          "direct": {path: version},
          "indirect": {path: version},
          "replace": [{old, old_version, new, new_version}],
          "exclude": [{path, version}],
        }
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except Exception as e:
        return {"error": f"cannot read go.mod: {e}"}

    out = {
        "module": "",
        "go": "",
        "toolchain": "",
        "direct": {},
        "indirect": {},
        "replace": [],
        "exclude": [],
    }

    m = re.search(r"^module\s+(\S+)", text, re.M)
    if m:
        out["module"] = m.group(1).strip('"')
    m = re.search(r"^go\s+(\S+)", text, re.M)
    if m:
        out["go"] = m.group(1)
    m = re.search(r"^toolchain\s+(\S+)", text, re.M)
    if m:
        out["toolchain"] = m.group(1)

    def parse_require_line(line: str) -> tuple[str, str, bool] | None:
        line = line.split("//")[0].rstrip()
        _is_indirect = "// indirect" in (line + " ")  # we stripped already
        # Better: check the original
        return line

    # Tokenize require statements (both single-line and block form)
    def iter_require_entries():
        # Single-line: `require <path> <ver> [// indirect]`
        for m in re.finditer(r"^\s*require\s+(\S+)\s+(\S+)(.*)$", text, re.M):
            path, ver, tail = m.group(1), m.group(2), m.group(3)
            yield path, ver, "// indirect" in tail

        # Block form: `require ( ... )`
        for blk in re.finditer(r"^require\s*\(\s*$(.*?)^\)\s*$", text, re.M | re.S):
            body = blk.group(1)
            for raw in body.splitlines():
                line = raw.strip()
                if not line or line.startswith("//"):
                    continue
                # `path version [// indirect]`
                mm = re.match(r"(\S+)\s+(\S+)(.*)$", line)
                if not mm:
                    continue
                path, ver, tail = mm.group(1), mm.group(2), mm.group(3)
                yield path, ver, "// indirect" in tail

    for path, ver, indirect in iter_require_entries():
        if indirect:
            out["indirect"][path] = ver
        else:
            out["direct"][path] = ver

    # replace directives
    def iter_replace_entries():
        for m in re.finditer(
            r"^\s*replace\s+(\S+)\s+(v\S+)?\s*=>\s*(\S+)\s*(v\S+)?\s*$",
            text,
            re.M,
        ):
            yield m.group(1), m.group(2) or "", m.group(3), m.group(4) or ""
        for blk in re.finditer(r"^replace\s*\(\s*$(.*?)^\)\s*$", text, re.M | re.S):
            body = blk.group(1)
            for raw in body.splitlines():
                line = raw.strip()
                if not line or line.startswith("//"):
                    continue
                mm = re.match(r"(\S+)\s+(v\S+)?\s*=>\s*(\S+)\s*(v\S+)?\s*$", line)
                if mm:
                    yield mm.group(1), mm.group(2) or "", mm.group(3), mm.group(4) or ""

    for old, old_ver, new, new_ver in iter_replace_entries():
        out["replace"].append(
            {
                "old": old,
                "old_version": old_ver,
                "new": new,
                "new_version": new_ver,
            }
        )

    # exclude directives
    for m in re.finditer(r"^\s*exclude\s+(\S+)\s+(\S+)", text, re.M):
        out["exclude"].append({"path": m.group(1), "version": m.group(2)})
    for blk in re.finditer(r"^exclude\s*\(\s*$(.*?)^\)\s*$", text, re.M | re.S):
        body = blk.group(1)
        for raw in body.splitlines():
            line = raw.strip()
            if not line or line.startswith("//"):
                continue
            mm = re.match(r"(\S+)\s+(\S+)", line)
            if mm:
                out["exclude"].append({"path": mm.group(1), "version": mm.group(2)})

    return out


# --------------------------------------------------------------------------- #
# Lookups via `go list` / `go mod graph`
# --------------------------------------------------------------------------- #


def go_list_all_modules(project_path: str) -> tuple[list[dict], list[str]]:
    """`go list -mod=mod -m -json all` → list of module info dicts."""
    errors = []
    rc, out, err = run(
        ["go", "list", "-mod=readonly", "-m", "-json", "all"],
        cwd=project_path,
        timeout=60,
    )
    if rc != 0:
        errors.append(f"go list -m all failed (rc={rc}): {err.strip()[:300]}")
        return [], errors

    # Stream of JSON objects (one per module). Use raw_decode loop.
    decoder = json.JSONDecoder()
    modules = []
    i, n = 0, len(out)
    while i < n:
        while i < n and out[i] in " \t\n\r":
            i += 1
        if i >= n:
            break
        try:
            obj, end = decoder.raw_decode(out[i:])
            modules.append(obj)
            i += end
        except json.JSONDecodeError as e:
            errors.append(f"go list JSON parse error at offset {i}: {e}")
            break
    return modules, errors


def go_list_replace(project_path: str, module_path: str) -> dict | None:
    """Get replace info for a single module via `go list -m -json <path>`."""
    rc, out, _ = run(
        ["go", "list", "-mod=readonly", "-m", "-json", module_path],
        cwd=project_path,
        timeout=15,
    )
    if rc != 0:
        return None
    try:
        obj = json.loads(out)
    except json.JSONDecodeError:
        return None
    if obj.get("Replace"):
        r = obj["Replace"]
        return {
            "old": obj.get("Path", ""),
            "old_version": obj.get("Version", ""),
            "new": r.get("Path", ""),
            "new_version": r.get("Version", ""),
        }
    return None


def go_mod_graph(project_path: str) -> str:
    rc, out, _ = run(["go", "mod", "graph"], cwd=project_path, timeout=60)
    if rc != 0:
        return ""
    return out


def go_list_versions(project_path: str, module_path: str) -> list[str]:
    rc, out, _ = run(
        ["go", "list", "-mod=readonly", "-m", "-versions", module_path],
        cwd=project_path,
        timeout=20,
    )
    if rc != 0:
        return []
    parts = out.strip().split()
    if len(parts) < 2:
        return []
    return parts[1:]


def go_mod_why(project_path: str, module_path: str) -> str:
    """Run `go mod why -m <module>` and classify the result.

    Returns one of:
        "needed"                       — target is on the main module's build path
        "not_needed_by_main_module"    — target in graph but not used
        "not_in_module_graph"          — target not in graph at all
        "unknown"                      — command failed; treat as unknown

    See references/go_replace_semantics.md for why this matters.
    """
    rc, out, _ = run(
        ["go", "mod", "why", "-m", module_path],
        cwd=project_path,
        timeout=20,
    )
    if rc != 0:
        return "unknown"
    text = out.lower()
    if "does not need" in text or "is not needed" in text:
        return "not_needed_by_main_module"
    if "not in module graph" in text or "not found in module graph" in text:
        return "not_in_module_graph"
    return "needed"


def fetch_parent_mod_via_scratch(parent_path: str, version: str) -> str | None:
    """Download `<parent>@<version>` into a temp scratch module and return the
    `.mod` text.

    Using a scratch module guarantees the project's go.sum and download-cache
    activity stays untouched. The system GOMODCACHE is still used (we want
    cache hits for speed), but no project files are written.
    """
    with tempfile.TemporaryDirectory(prefix="dep_tree_go_probe_") as td:
        Path(td, "go.mod").write_text("module scratch_probe\n\ngo 1.21\n", encoding="utf-8")
        # `download -json` is allowed even with -mod=readonly; explicitly
        # override GOFLAGS in case readonly blocks the fetch on some Go versions.
        rc, out, _ = run(
            ["go", "mod", "download", "-json", f"{parent_path}@{version}"],
            cwd=td,
            timeout=45,
            env={"GOFLAGS": "-mod=mod"},
        )
        if rc != 0:
            return None
        try:
            info = json.loads(out)
        except json.JSONDecodeError:
            return None
        gomod_path = info.get("GoMod") or ""
        if gomod_path and Path(gomod_path).exists():
            try:
                return Path(gomod_path).read_text(encoding="utf-8")
            except OSError:
                return None
    return None


def parse_target_in_parent_mod(mod_text: str, target_base: str) -> tuple[str, dict | None]:
    """Parse a parent's .mod text for what it pins / replaces for target.

    Returns:
        (require_version, replace_info)
        — require_version: e.g. "v4.1.3" or "" if not required
        — replace_info: {new_path, new_version} or None

    Both fields cover the major-suffix variant of target_base as well
    (e.g. `target_base/v4`).
    """
    if not mod_text:
        return "", None

    require_version = ""
    replace_info = None

    def base(p: str) -> str:
        return strip_major_suffix(p)

    # Single-line requires
    for m in re.finditer(r"^\s*require\s+(\S+)\s+(\S+)", mod_text, re.M):
        path, ver = m.group(1), m.group(2)
        if base(path) == target_base:
            require_version = ver
            break
    if not require_version:
        # Block-form requires
        for blk in re.finditer(r"^require\s*\(\s*$(.*?)^\)\s*$", mod_text, re.M | re.S):
            for raw in blk.group(1).splitlines():
                line = raw.strip().split("//")[0].strip()
                if not line:
                    continue
                mm = re.match(r"(\S+)\s+(\S+)", line)
                if mm and base(mm.group(1)) == target_base:
                    require_version = mm.group(2)
                    break
            if require_version:
                break

    # Single-line replaces
    for m in re.finditer(
        r"^\s*replace\s+(\S+)\s+(v\S+)?\s*=>\s*(\S+)\s*(v\S+)?\s*$",
        mod_text,
        re.M,
    ):
        if base(m.group(1)) == target_base:
            replace_info = {
                "new_path": m.group(3),
                "new_version": m.group(4) or "",
            }
            break
    if not replace_info:
        for blk in re.finditer(r"^replace\s*\(\s*$(.*?)^\)\s*$", mod_text, re.M | re.S):
            for raw in blk.group(1).splitlines():
                line = raw.strip().split("//")[0].strip()
                if not line:
                    continue
                mm = re.match(r"(\S+)\s+(v\S+)?\s*=>\s*(\S+)\s*(v\S+)?\s*$", line)
                if mm and base(mm.group(1)) == target_base:
                    replace_info = {
                        "new_path": mm.group(3),
                        "new_version": mm.group(4) or "",
                    }
                    break
            if replace_info:
                break

    return require_version, replace_info


def analyze_parent(
    project_path: str,
    parent_path: str,
    target_base: str,
    target_version: str | None,
) -> dict:
    """For one direct parent, return a dict describing whether bumping it
    will help reach `target_version` for `target_base`.

    Status values:
        "satisfies"             — parent@latest requires target at >= target_version
        "would_not_help_pin"    — parent@latest still pins target at an older version
        "would_not_help_replace"— parent@latest uses a `replace` for target (won't flow)
        "no_dep"                — parent@latest no longer requires target
        "unknown"               — could not probe (network / parsing failure)
    """
    info: dict = {
        "name": parent_path,
        "latest": "",
        "pins_target_to": "",
        "uses_replace_for_target": None,
        "status": "unknown",
        "reason": "",
    }

    versions = go_list_versions(project_path, parent_path)
    if not versions:
        info["reason"] = "could not list parent versions (network / private module)"
        return info
    latest = sorted(versions, key=version_tuple)[-1]
    info["latest"] = latest

    mod_text = fetch_parent_mod_via_scratch(parent_path, latest)
    if mod_text is None:
        info["reason"] = f"could not download {parent_path}@{latest} .mod for inspection"
        return info

    pinned, replaced = parse_target_in_parent_mod(mod_text, target_base)
    info["pins_target_to"] = pinned
    info["uses_replace_for_target"] = replaced

    if replaced is not None:
        info["status"] = "would_not_help_replace"
        info["reason"] = (
            f"{parent_path}@{latest} uses a `replace` directive for "
            f"{target_base} → {replaced.get('new_path', '')} "
            f"{replaced.get('new_version', '')}. Per Go spec, replace "
            "directives are LOCAL — they do NOT flow to downstream "
            "consumers. Bumping this parent will not change what our "
            "module resolves. See references/go_replace_semantics.md."
        )
        return info

    if not pinned:
        info["status"] = "no_dep"
        info["reason"] = f"{parent_path}@{latest} no longer requires {target_base}"
        return info

    if target_version and version_tuple(pinned) >= version_tuple(target_version):
        info["status"] = "satisfies"
        info["reason"] = (
            f"{parent_path}@{latest} requires {target_base}@{pinned} "
            f"(>= desired {target_version})"
        )
    else:
        info["status"] = "would_not_help_pin"
        info["reason"] = (
            f"{parent_path}@{latest} still pins {target_base}@{pinned} — "
            "no upstream release brings the desired version yet"
        )
    return info


def probe_major_variants(project_path: str, base_path: str, max_major: int = 9) -> list[dict]:
    """For v2..v9, try `go list -m -versions <base>/vN` and record what's available."""
    out = []
    for major in range(2, max_major + 1):
        path = f"{base_path}/v{major}"
        versions = go_list_versions(project_path, path)
        if not versions:
            continue
        sorted_v = sorted(versions, key=version_tuple)
        out.append(
            {
                "path": path,
                "latest": sorted_v[-1],
                "version_count": len(versions),
            }
        )
    return out


def walk_parents(
    mod_graph: str, target: str, direct_dep_names: set[str], main_module: str | None
) -> dict:
    """BFS up the graph from `target` to find parents that are in user's go.mod direct list.

    Returns:
        {direct_parents, transitive_parents, chains, version_constraints}
    """
    # Build forward + reverse adjacency from mod_graph lines
    edges_fwd: dict[str, set[str]] = {}
    edges_rev: dict[str, set[str]] = {}
    child_constraints: dict[str, str] = {}  # parent_path → version_of_target_required

    def split_module(s: str) -> tuple[str, str]:
        if "@" in s:
            p, v = s.rsplit("@", 1)
            return p, v
        return s, ""

    detected_main = None
    for line in mod_graph.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2:
            continue
        parent_s, child_s = parts
        pp, pv = split_module(parent_s)
        cp, cv = split_module(child_s)
        if "@" not in parent_s and detected_main is None:
            detected_main = parent_s
        edges_fwd.setdefault(pp, set()).add(cp)
        edges_rev.setdefault(cp, set()).add(pp)
        if cp == target:
            # Record the *first* constraint we see (closest to root)
            child_constraints.setdefault(pp, cv)

    if main_module is None:
        main_module = detected_main

    direct_parents: list[str] = []
    transitive_parents: list[str] = []
    chains: list[list[str]] = []
    visited = {target}
    queue: deque[list[str]] = deque([[target]])
    MAX_DEPTH = 12

    while queue:
        chain = queue.popleft()
        head = chain[-1]
        if len(chain) > MAX_DEPTH:
            continue
        for p in edges_rev.get(head, set()):
            if p in visited:
                continue
            if p == main_module:
                continue
            new_chain = chain + [p]
            if p in direct_dep_names:
                if p not in direct_parents:
                    direct_parents.append(p)
                chains.append(new_chain)
            else:
                if p not in transitive_parents:
                    transitive_parents.append(p)
                visited.add(p)
                queue.append(new_chain)

    # Constraints map: keep only parents we actually surfaced
    surfaced = set(direct_parents) | set(transitive_parents)
    constraints = {p: v for p, v in child_constraints.items() if p in surfaced}

    return {
        "direct_parents": direct_parents,
        "transitive_parents": transitive_parents,
        "chains": chains,
        "version_constraints": constraints,
    }


# --------------------------------------------------------------------------- #
# Upgrade strategies
# --------------------------------------------------------------------------- #


def compose_strategies(ctx: dict) -> list[dict]:
    """Build candidate strategies, each with a `confidence` 0..1.
    The list is returned sorted by confidence descending.

    Signals consumed (all optional — missing signals leave confidence at default):
        - go_mod_why_status: "needed" | "not_needed_by_main_module"
                           | "not_in_module_graph" | "unknown"
        - parent_analyses: per-parent analyze_parent() output

    See references/go_replace_semantics.md for the Go semantics that drive
    the reweighting (tidy sweeping indirect, replace not flowing downstream).
    """
    s: list[dict] = []
    dep_type = ctx["dependency_type"]
    is_direct = ctx["is_direct"]
    is_indirect = ctx["is_indirect"]
    is_major_jump = ctx["is_major_version_jump"]
    target_base = ctx["target_base"]
    target_version = ctx["target_version"]
    current_path = ctx["current_module_path"]
    current_ver = ctx["current_version"]
    target_path = ctx["target_module_path"]
    direct_parents = ctx["direct_parents"]
    has_replace = ctx["replace_directive"] is not None
    why_status = ctx.get("go_mod_why_status", "unknown")
    parent_analyses = ctx.get("parent_analyses", []) or []

    tv = target_version or "<target>"
    not_on_build_path = why_status == "not_needed_by_main_module"

    # 1. major_version_rewrite — when applicable, it's the only valid path
    if is_major_jump and target_path:
        s.append(
            {
                "type": "major_version_rewrite",
                "confidence": 0.95,
                "rationale": (
                    f"Target version {target_version} is a major-version jump "
                    f"({current_ver or 'absent'} → {target_version}). Go modules require "
                    f"rewriting all import paths from `{current_path or target_base}` to "
                    f"`{target_path}`. This is invasive — every .go file importing this "
                    f"package needs editing."
                ),
                "old_path": current_path or target_base,
                "new_path": target_path,
                "apply_hint": (f"gomajor get {target_path}@{tv}  # automates import rewrites"),
                "fallback_hint": (
                    f"go get {target_path}@{tv} && "
                    "(rewrite imports via ast_scanner_go output) && go mod tidy"
                ),
            }
        )

    # 2. direct_bump — straightforward
    if is_direct and not is_major_jump:
        s.append(
            {
                "type": "direct_bump",
                "confidence": 0.95,
                "rationale": (
                    f"Target is a direct dependency in go.mod ({current_ver}). "
                    "Bump in-place with `go get`."
                ),
                "current_version": current_ver,
                "apply_hint": f"go get {current_path}@{tv} && go mod tidy",
            }
        )

    # 3. bump_parent — confidence depends on parent_analyses
    if is_indirect and direct_parents:
        # Index analyses by parent name for quick lookup
        analyses_by_name = {a["name"]: a for a in parent_analyses}

        for p in direct_parents:
            analysis = analyses_by_name.get(p)
            strat: dict = {
                "type": "bump_parent",
                "target": p,
                "apply_hint": (
                    f"go get {p}@latest && go mod tidy  " f"# then verify {target_base} got bumped"
                ),
            }
            if analysis:
                status = analysis["status"]
                strat["parent_latest_version"] = analysis["latest"]
                strat["parent_pins_target_to"] = analysis["pins_target_to"]
                strat["parent_uses_replace_for_target"] = analysis["uses_replace_for_target"]

                if status == "satisfies":
                    base_conf = 0.85
                    if not_on_build_path:
                        # Even if parent satisfies, tidy may still sweep target
                        # away because it's not on build path.
                        base_conf = 0.30
                        strat["caveat"] = (
                            "Parent's latest brings the desired version, BUT "
                            "`go mod why` says target is not on the build path "
                            "— `go mod tidy` may still drop the indirect entry. "
                            "See references/go_replace_semantics.md."
                        )
                    strat["confidence"] = base_conf
                    strat["status"] = "satisfies"
                    strat["reason"] = analysis["reason"]
                    strat["rationale"] = (
                        f"Bumping direct parent `{p}` to {analysis['latest']} "
                        f"brings {target_base}@{analysis['pins_target_to']} "
                        f"(satisfies target {target_version or '?'})."
                    )
                elif status == "would_not_help_replace":
                    strat["confidence"] = 0.05
                    strat["status"] = "would_not_help"
                    strat["reason"] = analysis["reason"]
                    strat["rationale"] = (
                        f"`{p}@{analysis['latest']}` uses a `replace` directive "
                        f"for {target_base} — per Go spec this replace is LOCAL "
                        f"to {p} and will NOT flow to our module. Bumping `{p}` "
                        "will not change what we resolve. See "
                        "references/go_replace_semantics.md."
                    )
                elif status == "would_not_help_pin":
                    strat["confidence"] = 0.05
                    strat["status"] = "would_not_help"
                    strat["reason"] = analysis["reason"]
                    strat["rationale"] = (
                        f"`{p}@{analysis['latest']}` still pins "
                        f"{target_base}@{analysis['pins_target_to']} — "
                        "no upstream fix yet. Bumping this parent would be a no-op."
                    )
                elif status == "no_dep":
                    strat["confidence"] = 0.10
                    strat["status"] = "would_not_help"
                    strat["reason"] = analysis["reason"]
                    strat["rationale"] = (
                        f"`{p}@{analysis['latest']}` no longer depends on "
                        f"{target_base}. Bumping {p} drops the indirect "
                        "entirely (could be desirable, but doesn't 'upgrade' it)."
                    )
                else:  # "unknown"
                    strat["confidence"] = 0.50
                    strat["status"] = "unknown"
                    strat["reason"] = analysis["reason"] or ("could not probe parent's latest .mod")
                    strat["rationale"] = (
                        f"Parent `{p}` could not be probed — fall back to manual "
                        f"check: `go mod download -json {p}@latest`."
                    )
            else:
                # No analysis available — fall back to original heuristic confidence
                strat["confidence"] = 0.55
                strat["rationale"] = (
                    f"Target is INDIRECT, pulled in by direct dep `{p}`. "
                    "Bumping `{p}` may transitively pull a newer "
                    f"{target_base}, but no parent .mod probe was performed."
                )
            s.append(strat)

    # 4. bump_indirect — bump indirect entry directly
    if is_indirect:
        bump_indirect_strat: dict = {
            "type": "bump_indirect",
            "apply_hint": f"go get {current_path}@{tv} && go mod tidy",
        }
        if not_on_build_path:
            bump_indirect_strat["confidence"] = 0.10
            bump_indirect_strat["status"] = "would_not_help"
            bump_indirect_strat["reason"] = (
                "go mod why says target is not on the build path; `go mod tidy` "
                "will silently remove the indirect entry. Only `replace` survives."
            )
            bump_indirect_strat["rationale"] = (
                f"Bumping the indirect entry of {current_path} would work briefly, "
                "but the next `go mod tidy` will drop it (target not on build path). "
                "See references/go_replace_semantics.md."
            )
        else:
            bump_indirect_strat["confidence"] = 0.60
            bump_indirect_strat["rationale"] = (
                f"Bump the indirect entry of {current_path} in go.mod directly. "
                "Go MVS adopts the higher version. Standard approach when no parent "
                "release pulls the desired version yet."
            )
        s.append(bump_indirect_strat)

    # 5. add_replace — boosted when not_on_build_path or no parent will help
    if dep_type != "not_present":
        replace_warning = (
            "Replace directives are LOCAL to your module — downstream consumers "
            "do NOT inherit them. Use only for emergency patches, missing upstream "
            "fixes, or pointing at a fork."
        )
        if has_replace:
            replace_warning = "Existing replace directive present; " + replace_warning

        # Compute boost conditions
        any_parent_satisfies = any(a.get("status") == "satisfies" for a in parent_analyses)
        add_replace_strat: dict = {
            "type": "add_replace",
            "patch_hint": (
                f"// In go.mod\nreplace {current_path or target_base} => "
                f"{current_path or target_base} {tv}"
            ),
            "warning": replace_warning,
        }
        if not_on_build_path:
            add_replace_strat["confidence"] = 0.85
            add_replace_strat["rationale"] = (
                "Target is indirect AND not on build path "
                "(`go mod why`: not needed). `go mod tidy` will drop "
                "`bump_indirect`/`bump_parent` results, but `replace` survives. "
                "See references/go_replace_semantics.md."
            )
        elif is_indirect and not any_parent_satisfies and parent_analyses:
            add_replace_strat["confidence"] = 0.70
            add_replace_strat["rationale"] = (
                "No direct parent's latest version brings the desired target "
                "version. Adding a `replace` directive is the most reliable "
                "way to force the upgrade. " + replace_warning
            )
        else:
            add_replace_strat["confidence"] = 0.20
            add_replace_strat["rationale"] = (
                "Last resort: add a `replace` directive to pin the target. " + replace_warning
            )
        s.append(add_replace_strat)

    # not_present + target_version → recommend adding it as direct dep
    if dep_type == "not_present" and target_version:
        s.append(
            {
                "type": "direct_bump",
                "confidence": 0.95,
                "rationale": (
                    f"Target {target_base} is not currently in go.mod. `go get` "
                    "will add it as a new direct dependency."
                ),
                "apply_hint": (f"go get {target_path or target_base}@{tv} && go mod tidy"),
            }
        )

    # Sort by confidence descending (stable for ties)
    s.sort(key=lambda x: x.get("confidence", 0.0), reverse=True)
    return s


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_path")
    ap.add_argument("package_name")
    ap.add_argument("--target-version", default="")
    args = ap.parse_args()

    project = os.path.abspath(args.project_path)
    pkg_name = args.package_name
    target_version = args.target_version or None

    errors: list[str] = []

    if not Path(project, "go.mod").exists():
        print(
            json.dumps(
                {
                    "package_name": pkg_name,
                    "language": "go",
                    "pkg_manager": "unknown",
                    "error": "go.mod not found in project",
                },
                indent=2,
            )
        )
        return 1

    gomod = parse_gomod(str(Path(project, "go.mod")))
    if "error" in gomod:
        errors.append(gomod["error"])
        gomod = {
            "module": "",
            "direct": {},
            "indirect": {},
            "replace": [],
            "go": "",
            "toolchain": "",
            "exclude": [],
        }

    target_base = strip_major_suffix(pkg_name)

    # ----- Locate target across direct / indirect / not_present + major variants -----
    current_module_path = ""
    current_version = ""
    is_direct = False
    is_indirect = False

    for direct_map_name, flag in (("direct", "is_direct"), ("indirect", "is_indirect")):
        for path, ver in gomod.get(direct_map_name, {}).items():
            base_of_path = strip_major_suffix(path)
            if base_of_path == target_base:
                current_module_path = path
                current_version = ver
                if flag == "is_direct":
                    is_direct = True
                else:
                    is_indirect = True
                break
        if current_module_path:
            break

    # Cross-check with `go list -m -json all` — handles cases where go.mod
    # doesn't list an indirect entry (Go 1.16- behavior) but the build graph does.
    modules, list_errors = go_list_all_modules(project)
    errors.extend(list_errors)
    if not current_module_path:
        for mod in modules:
            path = mod.get("Path", "")
            if strip_major_suffix(path) == target_base and not mod.get("Main"):
                current_module_path = path
                current_version = mod.get("Version", "")
                if mod.get("Indirect"):
                    is_indirect = True
                else:
                    is_direct = True
                break

    if current_module_path:
        dep_type = "direct" if is_direct else ("indirect" if is_indirect else "unknown")
    else:
        dep_type = "not_present"

    # ----- Replace directive lookup -----
    replace_directive = None
    if current_module_path:
        replace_directive = go_list_replace(project, current_module_path)
    # Cross-check with parsed go.mod replace block
    if not replace_directive:
        for r in gomod.get("replace", []):
            if strip_major_suffix(r["old"]) == target_base:
                replace_directive = r
                break

    # ----- Parent walking via `go mod graph` -----
    direct_parents: list[str] = []
    transitive_parents: list[str] = []
    parent_chains: list[list[str]] = []
    version_constraints: dict[str, str] = {}
    if current_module_path:
        graph = go_mod_graph(project)
        if graph:
            direct_dep_names = set(gomod.get("direct", {}).keys())
            walked = walk_parents(graph, current_module_path, direct_dep_names, gomod.get("module"))
            direct_parents = walked["direct_parents"]
            transitive_parents = walked["transitive_parents"]
            parent_chains = walked["chains"]
            version_constraints = walked["version_constraints"]

    # ----- Available versions -----
    available_versions: list[str] = []
    latest_in_current_major: str | None = None
    if current_module_path:
        available_versions = go_list_versions(project, current_module_path)
        if available_versions and current_version:
            cm = major_of(current_version)
            if cm is not None:
                same_major = [v for v in available_versions if major_of(v) == cm]
                if same_major:
                    latest_in_current_major = sorted(same_major, key=version_tuple)[-1]

    available_majors = probe_major_variants(project, target_base)

    # ----- go mod why (only meaningful when target is present) -----
    why_status = "unknown"
    if current_module_path:
        why_status = go_mod_why(project, current_module_path)

    # ----- Parent analyses (probe each direct parent's latest .mod) -----
    parent_analyses: list[dict] = []
    if is_indirect and direct_parents:
        for p in direct_parents:
            try:
                pa = analyze_parent(project, p, target_base, target_version)
            except Exception as e:  # never let probe failure kill the report
                pa = {
                    "name": p,
                    "latest": "",
                    "pins_target_to": "",
                    "uses_replace_for_target": None,
                    "status": "unknown",
                    "reason": f"probe raised: {e!r}",
                }
            parent_analyses.append(pa)

    # ----- target path / major jump -----
    target_module_path = None
    is_major_version_jump = False
    if target_version:
        target_module_path = module_path_for_version(target_base, target_version)
        tm = major_of(target_version)
        cm = major_of(current_version) if current_version else None
        if tm is not None and tm >= 2 and (cm is None or cm != tm):
            is_major_version_jump = True

    # ----- Strategies -----
    strategies = compose_strategies(
        {
            "dependency_type": dep_type,
            "is_direct": is_direct,
            "is_indirect": is_indirect,
            "is_major_version_jump": is_major_version_jump,
            "target_base": target_base,
            "target_version": target_version,
            "current_module_path": current_module_path,
            "current_version": current_version,
            "target_module_path": target_module_path,
            "direct_parents": direct_parents,
            "replace_directive": replace_directive,
            "go_mod_why_status": why_status,
            "parent_analyses": parent_analyses,
        }
    )

    is_vendored = Path(project, "vendor", "modules.txt").exists()

    result = {
        "package_name": pkg_name,
        "language": "go",
        "pkg_manager": "gomod",
        "current_version": current_version,
        "current_module_path": current_module_path,
        "target_version": target_version,
        "target_module_path": target_module_path,
        "is_major_version_jump": is_major_version_jump,
        "dependency_type": dep_type,
        "is_direct": is_direct,
        "is_indirect": is_indirect,
        "parent_packages": direct_parents + transitive_parents,
        "direct_parents": direct_parents,
        "transitive_parents": transitive_parents,
        "parent_chains": parent_chains,
        "version_constraints": version_constraints,
        "available_versions": available_versions,
        "latest_in_current_major": latest_in_current_major,
        "available_majors": available_majors,
        "replace_directive": replace_directive,
        "go_mod_why_status": why_status,
        "parent_analyses": parent_analyses,
        "is_vendored": is_vendored,
        "go_directive": gomod.get("go", ""),
        "upgrade_strategies": strategies,
        "recommended_strategy": strategies[0]["type"] if strategies else "unknown",
        "source": "go-list+go-mod-graph+go-mod-why+parent-mod-probe",
        "errors": errors,
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
