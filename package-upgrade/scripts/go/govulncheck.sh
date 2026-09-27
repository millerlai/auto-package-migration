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
  "scan_status": "failed",
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

# Run govulncheck in JSON mode. -json exits 0 regardless of findings, so any
# non-zero exit here is a real failure (build error, network, etc.).
RAW_FILE=$(mktemp)
ERR_FILE=$(mktemp)
GVC_PY_ERR_FILE=$(mktemp)
trap 'rm -f "$RAW_FILE" "$ERR_FILE" "$GVC_PY_ERR_FILE"' EXIT

GVC_EXIT_CODE=0
govulncheck -json ./... >"$RAW_FILE" 2>"$ERR_FILE" || GVC_EXIT_CODE=$?

# Parse stream of JSON objects into findings
RESULT_JSON=$(GVC_RAW_PATH="$RAW_FILE" GVC_ERR_PATH="$ERR_FILE" GVC_EXIT_CODE="$GVC_EXIT_CODE" \
    python3 - "$CVE_FILTER" "$GVC_VERSION" "$PROJECT_PATH" <<'PY' 2>"$GVC_PY_ERR_FILE"
import json, sys, os, re

cve_filter = sys.argv[1] or ""
gvc_version = sys.argv[2] or ""
project_path = sys.argv[3]

raw_path = os.environ.get("GVC_RAW_PATH", "")
err_path = os.environ.get("GVC_ERR_PATH", "")
exit_code = int(os.environ.get("GVC_EXIT_CODE", "0") or "0")
try:
    text = open(raw_path, "r", encoding="utf-8").read() if raw_path else ""
except Exception:
    text = ""

# govulncheck itself failed: scan_status is "failed" regardless of what (if
# anything) is on stdout, and the not_present classification is never used.
scan_status = "ok" if exit_code == 0 else "failed"
errors = []


def _redact_creds(s):
    """Strip embedded basic-auth credentials (scheme://user:pass@host) from
    text before it is kept in this wrapper's own stdout. A failing `go`
    module fetch can echo the failing GOPROXY URL verbatim, and a corporate
    proxy may carry credentials inline.
    """
    return re.sub(r"://[^/@\s]+@", "://", s)


if scan_status == "failed":
    try:
        with open(err_path, "r", encoding="utf-8", errors="replace") as fh:
            err_lines = [ln.rstrip("\n") for ln in fh.readlines()]
        tail = _redact_creds("\n".join(err_lines[-20:]))
        errors.append(f"govulncheck exited {exit_code}:\n" + tail)
    except Exception as e:
        errors.append(f"govulncheck exited {exit_code}; could not read stderr: {e}")

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

if cve_filter and not findings and scan_status == "ok":
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
    "scan_status": scan_status,
    "findings": findings,
    "summary": summary,
    "filter_cve": cve_filter or None,
    "errors": errors,
}))
PY
) || {
    PY_ERR_TEXT=$(tail -20 "$GVC_PY_ERR_FILE" | python3 -c 'import json, sys; print(json.dumps(sys.stdin.read()))')
    RESULT_JSON=$(printf '{"project_path": %s, "findings": [], "summary": {"called": 0, "imported": 0, "not_present": 0}, "filter_cve": null, "scan_status": "failed", "errors": [%s]}' \
        "$(printf '%s' "$PROJECT_PATH" | python3 -c 'import json, sys; print(json.dumps(sys.stdin.read()))')" \
        "$PY_ERR_TEXT")
}

echo "$RESULT_JSON"
