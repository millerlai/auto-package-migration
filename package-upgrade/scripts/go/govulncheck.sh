#!/usr/bin/env bash
# govulncheck_go.sh - Run govulncheck and produce structured output for
# CVE reachability analysis (Phase 1.B for the Go path).
#
# Usage:
#   bash govulncheck_go.sh <project_path> [--cve CVE-XXXX-XXXXX] [--post-upgrade]
#
# Without --cve: report ALL vulnerabilities found.
# With    --cve: report only matches for the given CVE (case-insensitive),
#                including the called/imported/not_present classification.
#
# Output JSON shape:
#   {
#     "project_path": "...",
#     "govulncheck_version": "...",
#     "findings": [
#       {
#         "osv_id": "GO-2024-2611",
#         "aliases": ["CVE-2024-24786", "GHSA-..."],
#         "summary": "...",
#         "module": "google.golang.org/protobuf",
#         "package": ".../protojson",
#         "function": "Unmarshal",
#         "current_version": "v1.31.0",
#         "fixed_in": "v1.33.0",
#         "match": "called" | "imported" | "not_present",
#         "call_sites": [{"file": "handler.go", "line": 42, "function": "..."}, ...],
#         "advisory_url": "https://pkg.go.dev/vuln/GO-2024-2611"
#       }, ...
#     ],
#     "summary": {"called": N, "imported": M, "not_present": K},
#     "filter_cve": "CVE-XXXX-XXXXX" | null,
#     "errors": [...]
#   }

set -euo pipefail

PROJECT_PATH="${1:-}"
shift || true

CVE_FILTER=""
POST_UPGRADE="false"
while [[ $# -gt 0 ]]; do
    case $1 in
        --cve) CVE_FILTER="$2"; shift 2 ;;
        --post-upgrade) POST_UPGRADE="true"; shift ;;
        *) shift ;;
    esac
done

if [ -z "$PROJECT_PATH" ]; then
    echo "Usage: bash govulncheck_go.sh <project_path> [--cve CVE-XXXX-XXXXX] [--post-upgrade]" >&2
    exit 1
fi

cd "$PROJECT_PATH" || exit 1

if ! command -v govulncheck >/dev/null 2>&1; then
    cat <<EOF
{
  "project_path": "$PROJECT_PATH",
  "findings": [],
  "summary": {"called": 0, "imported": 0, "not_present": 0},
  "filter_cve": $([ -n "$CVE_FILTER" ] && printf '"%s"' "$CVE_FILTER" || echo "null"),
  "errors": ["govulncheck not installed; install: go install golang.org/x/vuln/cmd/govulncheck@latest"]
}
EOF
    exit 0
fi

# Get version (best effort — format varies)
GVC_VERSION=$(govulncheck -version 2>/dev/null | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "")

# Run govulncheck in JSON mode. It always exits non-zero when vulns found,
# but stdout is still valid.
RAW_FILE=$(mktemp)
ERR_FILE=$(mktemp)
trap 'rm -f "$RAW_FILE" "$ERR_FILE"' EXIT

govulncheck -json ./... >"$RAW_FILE" 2>"$ERR_FILE" || true

# Parse stream of JSON objects into findings
RESULT_JSON=$(GVC_RAW_PATH="$RAW_FILE" python3 - "$CVE_FILTER" "$GVC_VERSION" "$PROJECT_PATH" <<'PY' 2>/dev/null || echo '{"findings":[],"summary":{"called":0,"imported":0,"not_present":0},"errors":["parse failure"]}'
import json, sys, os, re

cve_filter = sys.argv[1] or ""
gvc_version = sys.argv[2] or ""
project_path = sys.argv[3]

raw_path = os.environ.get("GVC_RAW_PATH", "")
try:
    text = open(raw_path, "r", encoding="utf-8").read() if raw_path else ""
except Exception:
    text = ""

decoder = json.JSONDecoder()
items = []
i, n = 0, len(text)
while i < n:
    while i < n and text[i] in " \t\n\r":
        i += 1
    if i >= n:
        break
    try:
        obj, end = decoder.raw_decode(text[i:])
        items.append(obj)
        i += end
    except json.JSONDecodeError:
        break

osvs = {}
findings_raw = []
for it in items:
    if isinstance(it, dict):
        if "osv" in it:
            o = it["osv"]
            osvs[o.get("id", "")] = o
        elif "finding" in it:
            findings_raw.append(it["finding"])

agg = {}
main_module_prefix = ""
try:
    with open(os.path.join(project_path, "go.mod"), encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r'^module\s+(\S+)', line)
            if m:
                main_module_prefix = m.group(1)
                break
except Exception:
    pass

for f in findings_raw:
    osv_id = f.get("osv", "")
    fixed = f.get("fixed_version", "")
    trace = f.get("trace", []) or []

    a = agg.setdefault(osv_id, {
        "kinds": set(),
        "call_sites": [],
        "modules": set(),
        "packages": set(),
        "functions": set(),
        "current_versions": set(),
        "fixed_in": fixed,
    })

    is_called = False
    for frame in trace:
        pkg = frame.get("package", "") or ""
        mod = frame.get("module", "") or ""
        ver = frame.get("version", "") or ""
        fn  = frame.get("function", "") or ""
        pos = frame.get("position", {}) or {}
        if mod and ver:
            a["current_versions"].add(f"{mod}@{ver}")
        if mod:
            a["modules"].add(mod)
        if pkg:
            a["packages"].add(pkg)
        if fn:
            a["functions"].add(fn)
        if main_module_prefix and pkg.startswith(main_module_prefix):
            is_called = True
            a["call_sites"].append({
                "file": pos.get("filename", ""),
                "line": pos.get("line", 0),
                "function": fn,
            })

    if trace:
        a["kinds"].add("called" if is_called else "imported")
    else:
        a["kinds"].add("imported")

findings = []
for osv_id, a in agg.items():
    o = osvs.get(osv_id, {})
    aliases = o.get("aliases", []) or []
    summary = (o.get("summary", "") or o.get("details", "")[:200] or "").strip()
    advisory_url = (o.get("database_specific") or {}).get("url", "") \
        or (f"https://pkg.go.dev/vuln/{osv_id}" if osv_id else "")

    if "called" in a["kinds"]:
        match = "called"
    elif "imported" in a["kinds"]:
        match = "imported"
    else:
        match = "not_present"

    finding = {
        "osv_id": osv_id,
        "aliases": aliases,
        "summary": summary,
        "modules": sorted(a["modules"]),
        "packages": sorted(a["packages"]),
        "functions": sorted(a["functions"]),
        "current_versions": sorted(a["current_versions"]),
        "fixed_in": a["fixed_in"],
        "match": match,
        "call_sites": a["call_sites"][:10],
        "advisory_url": advisory_url,
    }

    if cve_filter:
        ids = [osv_id.upper()] + [str(x).upper() for x in aliases]
        if cve_filter.upper() not in ids:
            continue

    findings.append(finding)

if cve_filter and not findings:
    findings.append({
        "osv_id": "",
        "aliases": [cve_filter],
        "summary": "",
        "match": "not_present",
        "modules": [], "packages": [], "functions": [],
        "current_versions": [], "fixed_in": "",
        "call_sites": [], "advisory_url": "",
    })

summary = {"called": 0, "imported": 0, "not_present": 0}
for f in findings:
    summary[f["match"]] = summary.get(f["match"], 0) + 1

print(json.dumps({
    "project_path": project_path,
    "govulncheck_version": gvc_version,
    "findings": findings,
    "summary": summary,
    "filter_cve": cve_filter or None,
    "errors": [],
}))
PY
)

echo "$RESULT_JSON"
