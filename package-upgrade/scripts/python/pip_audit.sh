#!/usr/bin/env bash
# pip_audit_py.sh - Python CVE reachability via pip-audit + ast_scanner.py.
#
# Usage:
#   bash pip_audit_py.sh <project_path> [--cve CVE-XXXX-XXXXX] [--post-upgrade]
#
# Python equivalent of govulncheck_go.sh. Since Python has no native call
# graph tool, we approximate reachability by:
#   1. pip-audit  → list of vulnerable installed packages + advisory text
#   2. ast_scanner.py per affected package → import sites + symbol usages
#   3. Best-effort symbol extraction from the advisory description
#   4. Classify each finding as called / imported / not_present
#
# This is weaker than govulncheck's SSA-based call graph (Python is dynamic),
# but materially better than "all CVEs are critical" — the LLM can stop
# treating not_present findings as urgent.
#
# Output JSON shape — aligned with govulncheck_go.sh so Phase 1.B logic is
# shared across languages:
#   {
#     "project_path": "...",
#     "tool": "pip-audit",
#     "tool_version": "x.y.z",
#     "findings": [
#       {
#         "osv_id":     "PYSEC-2023-..." | "GHSA-..." | "",
#         "aliases":    ["CVE-XXXX-XXXXX", ...],
#         "summary":    "<advisory description, first 400 chars>",
#         "package":    "pillow",
#         "current_version": "9.5.0",
#         "fixed_in":   "10.0.1",
#         "match":      "called" | "imported" | "not_present",
#         "call_sites": [{"file": "...", "line": N, "symbol": "..."}],
#         "advisory_url": "https://...",
#         "extracted_symbols": ["truetype", "ImageFont.truetype"],
#         "import_names":     ["PIL"]
#       }, ...
#     ],
#     "summary": {"called": N, "imported": N, "not_present": N},
#     "filter_cve": "..." | null,
#     "post_upgrade": bool,
#     "errors": [...]
#   }

set -euo pipefail

PROJECT_PATH="${1:-}"
shift || true

CVE_FILTER=""
POST_UPGRADE="false"
while [[ $# -gt 0 ]]; do
    case $1 in
        --cve)          CVE_FILTER="$2"; shift 2 ;;
        --post-upgrade) POST_UPGRADE="true"; shift ;;
        *) shift ;;
    esac
done

if [ -z "$PROJECT_PATH" ]; then
    echo "Usage: bash pip_audit_py.sh <project_path> [--cve CVE-XXXX-XXXXX] [--post-upgrade]" >&2
    exit 1
fi

PROJECT_ABS=$(cd "$PROJECT_PATH" && pwd -P)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AST_SCANNER="$SCRIPT_DIR/ast_scanner.py"

if ! command -v pip-audit >/dev/null 2>&1; then
    cat <<EOF
{
  "project_path": "$PROJECT_ABS",
  "tool": "pip-audit",
  "findings": [],
  "summary": {"called": 0, "imported": 0, "not_present": 0},
  "filter_cve": $([ -n "$CVE_FILTER" ] && printf '"%s"' "$CVE_FILTER" || echo "null"),
  "post_upgrade": $POST_UPGRADE,
  "errors": ["pip-audit not installed; install: pip install pip-audit"]
}
EOF
    exit 0
fi

PA_VERSION=$(pip-audit --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "")

# Run pip-audit. It exits non-zero when vulns are found but stdout is valid JSON.
RAW_FILE=$(mktemp)
ERR_FILE=$(mktemp)
trap 'rm -f "$RAW_FILE" "$ERR_FILE"' EXIT

# --strict: include findings without known fix versions
# --format json: machine-readable output
# --disable-pip: don't shell out to pip for resolution (faster, uses installed env)
(cd "$PROJECT_ABS" && pip-audit --format json --strict 2>"$ERR_FILE" >"$RAW_FILE") || true

# Hand off to Python for parsing + reachability cross-reference.
PA_RAW_PATH="$RAW_FILE" \
PA_AST_SCANNER="$AST_SCANNER" \
PA_PROJECT_PATH="$PROJECT_ABS" \
PA_CVE_FILTER="$CVE_FILTER" \
PA_TOOL_VERSION="$PA_VERSION" \
PA_POST_UPGRADE="$POST_UPGRADE" \
python3 <<'PY'
import json
import os
import re
import subprocess
import sys

raw_path     = os.environ["PA_RAW_PATH"]
ast_scanner  = os.environ["PA_AST_SCANNER"]
project_path = os.environ["PA_PROJECT_PATH"]
cve_filter   = os.environ.get("PA_CVE_FILTER", "")
tool_version = os.environ.get("PA_TOOL_VERSION", "")
post_upgrade = os.environ.get("PA_POST_UPGRADE", "false") == "true"

errors = []

try:
    with open(raw_path, "r", encoding="utf-8") as fh:
        text = fh.read().strip()
except Exception as e:
    text = ""
    errors.append(f"could not read pip-audit output: {e}")

audit = {}
if text:
    try:
        audit = json.loads(text)
    except json.JSONDecodeError as e:
        errors.append(f"pip-audit JSON parse failure: {e}")
        audit = {}

# pip-audit JSON shape (current): {"dependencies": [{"name", "version",
# "vulns": [{"id", "fix_versions", "aliases", "description"}]}]}
deps = audit.get("dependencies", []) if isinstance(audit, dict) else []


# ---------------------------------------------------------------------------
# Map pip distribution name → list of import names (e.g. pillow → ["PIL"])
# importlib.metadata.files() is available on Python 3.8+ via stdlib; the data
# may be empty if the package isn't installed in the current interpreter.
# ---------------------------------------------------------------------------

def import_names_for(dist: str):
    try:
        import importlib.metadata as md
    except ImportError:
        return [dist]
    try:
        files = md.files(dist) or []
    except Exception:
        return [dist]
    names = set()
    for f in files:
        parts = str(f).replace("\\", "/").split("/")
        if len(parts) == 2 and parts[1] == "__init__.py":
            names.add(parts[0])
        elif len(parts) == 1 and parts[0].endswith(".py") and "/" not in parts[0]:
            # Top-level single-file module
            names.add(parts[0][:-3])
    return sorted(names) if names else [dist]


# ---------------------------------------------------------------------------
# Heuristic symbol extraction from advisory text.
# Returns a deduped list of candidate symbols, preferring dotted paths first.
# Common English filler is filtered out so we don't end up with "the", "is".
# ---------------------------------------------------------------------------

_FILLER = {
    "the", "is", "of", "to", "in", "on", "by", "with", "as", "an", "a",
    "this", "that", "these", "those", "if", "then", "else", "and", "or",
    "but", "not", "from", "for", "into", "via", "be", "are", "was", "were",
    "has", "have", "had", "do", "does", "did", "can", "could", "should",
    "would", "may", "might", "will", "shall", "must", "all", "any", "some",
    "no", "none", "user", "users", "issue", "vulnerability", "function",
    "method", "class", "module", "library", "version", "versions", "fix",
    "fixed", "patch", "patched", "above", "below", "before", "after",
    "data", "input", "output", "string", "value", "param", "parameter",
    "request", "response", "true", "false", "null",
}


def extract_symbols(text: str):
    if not text:
        return []
    candidates = []

    # 1) Backtick-quoted identifiers: `Foo.bar`, `requests`, `Session.send`
    for m in re.finditer(r"`([A-Za-z_][\w.]*)`", text):
        candidates.append(m.group(1))

    # 2) Dotted identifiers anywhere (e.g. "ImageFont.truetype")
    for m in re.finditer(r"\b([A-Za-z_]\w*(?:\.\w+)+)\b", text):
        candidates.append(m.group(1))

    # 3) "<name>() function/method"
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\(\s*\)\s*(?:function|method)", text):
        candidates.append(m.group(1))

    # 4) "function/method <name>"
    for m in re.finditer(r"\b(?:function|method|class)\s+`?([A-Za-z_]\w*)`?", text):
        candidates.append(m.group(1))

    # Dedupe while preserving order; drop filler / pure lowercase common words
    seen = set()
    out = []
    for c in candidates:
        if c.lower() in _FILLER:
            continue
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


# ---------------------------------------------------------------------------
# Cross-reference: run ast_scanner.py for each import_name, then look for
# any extracted symbol in the scanner's reported usages.
# ---------------------------------------------------------------------------

def scan_usage(import_name: str):
    """Return list of {file, imports, usages} for one import name."""
    try:
        result = subprocess.run(
            [sys.executable, ast_scanner, project_path, import_name],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return []
        data = json.loads(result.stdout or "{}")
        return data.get("scan_results", []) or []
    except Exception:
        return []


def classify(scan_results, extracted_symbols):
    """Return (match, call_sites). call_sites limited to first 10."""
    if not scan_results:
        return "not_present", []

    # If any scan result had an import or usage, the package is at least imported
    any_import = any(r.get("imports") for r in scan_results)
    any_usage  = any(r.get("usages") for r in scan_results)
    if not (any_import or any_usage):
        return "not_present", []

    # Look for symbol matches in usages
    call_sites = []
    if extracted_symbols:
        sym_norm = [s.lower() for s in extracted_symbols]
        for r in scan_results:
            for use in r.get("usages", []):
                used_sym = (use.get("symbol") or "").lower()
                # Match if the used symbol ENDS WITH any extracted symbol,
                # or contains it as a dotted suffix (handles aliasing).
                hit = any(
                    used_sym == s or used_sym.endswith("." + s) or ("." + s + ".") in ("." + used_sym + ".")
                    for s in sym_norm
                )
                if hit:
                    call_sites.append({
                        "file":   r.get("file", ""),
                        "line":   use.get("line", 0),
                        "symbol": use.get("symbol", ""),
                    })
                    if len(call_sites) >= 10:
                        break
            if len(call_sites) >= 10:
                break

    if call_sites:
        return "called", call_sites
    # Imported but no symbol from advisory found in usages — or no symbol extracted
    return "imported", []


# ---------------------------------------------------------------------------
# Build findings
# ---------------------------------------------------------------------------

findings = []
for dep in deps:
    pkg = dep.get("name", "") or ""
    cur_ver = dep.get("version", "") or ""
    vulns = dep.get("vulns", []) or []
    if not vulns:
        continue

    imports = import_names_for(pkg)

    # Scan once per import name; reuse across all vulns for the same package
    scan_by_import = {name: scan_usage(name) for name in imports}
    merged_scan = []
    for r_list in scan_by_import.values():
        merged_scan.extend(r_list)

    for v in vulns:
        osv_id   = v.get("id", "") or ""
        aliases  = v.get("aliases", []) or []
        fix_vers = v.get("fix_versions", []) or []
        descr    = v.get("description", "") or ""

        # Filter by --cve
        if cve_filter:
            id_pool = [osv_id.upper()] + [str(a).upper() for a in aliases]
            if cve_filter.upper() not in id_pool:
                continue

        symbols = extract_symbols(descr)
        match, call_sites = classify(merged_scan, symbols)

        advisory_url = ""
        if osv_id.startswith("GHSA-"):
            advisory_url = f"https://github.com/advisories/{osv_id}"
        elif osv_id.startswith("PYSEC-"):
            advisory_url = f"https://osv.dev/vulnerability/{osv_id}"
        elif osv_id:
            advisory_url = f"https://osv.dev/vulnerability/{osv_id}"

        findings.append({
            "osv_id":            osv_id,
            "aliases":           aliases,
            "summary":           descr[:400],
            "package":           pkg,
            "current_version":   cur_ver,
            "fixed_in":          (fix_vers[0] if fix_vers else ""),
            "match":             match,
            "call_sites":        call_sites,
            "advisory_url":      advisory_url,
            "extracted_symbols": symbols,
            "import_names":      imports,
        })

# If --cve filter was set but produced no rows, emit a synthetic not_present
# finding so the LLM can report "CVE-XXX is not present in this project".
if cve_filter and not findings:
    findings.append({
        "osv_id": "",
        "aliases": [cve_filter],
        "summary": "",
        "package": "",
        "current_version": "",
        "fixed_in": "",
        "match": "not_present",
        "call_sites": [],
        "advisory_url": "",
        "extracted_symbols": [],
        "import_names": [],
    })

summary = {"called": 0, "imported": 0, "not_present": 0}
for f in findings:
    summary[f["match"]] = summary.get(f["match"], 0) + 1

print(json.dumps({
    "project_path":  project_path,
    "tool":          "pip-audit",
    "tool_version":  tool_version,
    "findings":      findings,
    "summary":       summary,
    "filter_cve":    cve_filter or None,
    "post_upgrade":  post_upgrade,
    "errors":        errors,
}, indent=2))
PY
