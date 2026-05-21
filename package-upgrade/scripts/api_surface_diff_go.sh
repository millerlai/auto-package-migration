#!/usr/bin/env bash
# api_surface_diff_go.sh - Diff a Go module's exported API between two versions
# using golang.org/x/exp/cmd/apidiff.
#
# Usage:
#   bash api_surface_diff_go.sh <module_path> <old_version> <new_version>
#
# Strategy:
#   1. `go mod download` both versions into the module cache.
#   2. Locate each version's source dir under $GOMODCACHE/<path>@<ver>.
#   3. Run `apidiff -m <old_dir> <new_dir>` and parse the output.
#
# Output: JSON aligned with api_surface_diff_js.js so Phase 3 LLM logic
#         stays shared:
#   {
#     "package_name": "github.com/foo/bar",
#     "old_version": "v1.2.0",
#     "new_version": "v1.3.0",
#     "strategy": "apidiff" | "none",
#     "old_source_label": "module cache: .../foo@v1.2.0",
#     "new_source_label": "module cache: .../foo@v1.3.0",
#     "removed": [{"name": "...", "kind": "incompatible"}, ...],
#     "added":   [...],
#     "changed": [{"name": "...", "old_signature": "...", "new_signature": "...",
#                  "category": "signature_change" | "kind_change" | "type_change"}],
#     "deprecated_new": [],   # Go-only: harvested via grep for `// Deprecated:`
#     "warnings": [...],
#     "errors": [...]
#   }

set -euo pipefail

MODULE_PATH="${1:-}"
OLD_VER="${2:-}"
NEW_VER="${3:-}"

if [ -z "$MODULE_PATH" ] || [ -z "$OLD_VER" ] || [ -z "$NEW_VER" ]; then
    echo "Usage: bash api_surface_diff_go.sh <module_path> <old_version> <new_version>" >&2
    exit 1
fi

# ---------- tool availability ----------

WARNINGS_JSON="[]"
ERRORS_JSON="[]"

declare -a WARNS=()
declare -a ERRS=()

add_warn() { WARNS+=("$1"); }
add_err()  { ERRS+=("$1"); }

flush_warns() {
    if [ "${#WARNS[@]}" -gt 0 ]; then
        WARNINGS_JSON=$(printf '%s\n' "${WARNS[@]}" | jq -R -s 'split("\n") | map(select(. != ""))')
    fi
}
flush_errs() {
    if [ "${#ERRS[@]}" -gt 0 ]; then
        ERRORS_JSON=$(printf '%s\n' "${ERRS[@]}" | jq -R -s 'split("\n") | map(select(. != ""))')
    fi
}

emit_empty() {
    local strategy="$1"
    flush_warns
    flush_errs
    cat <<EOF
{
  "package_name": "$MODULE_PATH",
  "old_version": "$OLD_VER",
  "new_version": "$NEW_VER",
  "strategy": "$strategy",
  "old_source_label": "",
  "new_source_label": "",
  "removed": [],
  "added": [],
  "changed": [],
  "deprecated_new": [],
  "warnings": $WARNINGS_JSON,
  "errors": $ERRORS_JSON
}
EOF
}

if ! command -v go >/dev/null 2>&1; then
    add_err "go binary not in PATH — cannot resolve module sources"
    emit_empty "none"
    exit 1
fi

if ! command -v apidiff >/dev/null 2>&1; then
    add_warn "apidiff not installed — install: go install golang.org/x/exp/cmd/apidiff@latest. Falling back to no-API-diff strategy."
    emit_empty "none"
    exit 0
fi

# ---------- download both versions ----------

GOMODCACHE=$(go env GOMODCACHE 2>/dev/null || echo "")
if [ -z "$GOMODCACHE" ]; then
    add_err "GOMODCACHE is empty"
    emit_empty "none"
    exit 1
fi

# Run download in a temp module so we don't dirty the user's project
TMP_MOD=$(mktemp -d)
trap 'rm -rf "$TMP_MOD"' EXIT
cd "$TMP_MOD"
cat > go.mod <<EOF
module tmp.local/apidiff-helper

go 1.21
EOF

if ! go mod download "$MODULE_PATH@$OLD_VER" 2>/dev/null; then
    add_err "go mod download failed for $MODULE_PATH@$OLD_VER"
    emit_empty "none"
    exit 1
fi
if ! go mod download "$MODULE_PATH@$NEW_VER" 2>/dev/null; then
    add_err "go mod download failed for $MODULE_PATH@$NEW_VER"
    emit_empty "none"
    exit 1
fi

# Resolve cache dirs. Go encodes module paths with `!` for uppercase letters.
# `go mod download -json` returns the actual path; use that.
OLD_INFO=$(go mod download -json "$MODULE_PATH@$OLD_VER" 2>/dev/null || echo "{}")
NEW_INFO=$(go mod download -json "$MODULE_PATH@$NEW_VER" 2>/dev/null || echo "{}")

OLD_DIR=$(echo "$OLD_INFO" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); print(d.get("Dir",""))' 2>/dev/null || echo "")
NEW_DIR=$(echo "$NEW_INFO" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); print(d.get("Dir",""))' 2>/dev/null || echo "")

if [ -z "$OLD_DIR" ] || [ ! -d "$OLD_DIR" ]; then
    add_err "cannot locate module cache dir for $MODULE_PATH@$OLD_VER"
    emit_empty "none"
    exit 1
fi
if [ -z "$NEW_DIR" ] || [ ! -d "$NEW_DIR" ]; then
    add_err "cannot locate module cache dir for $MODULE_PATH@$NEW_VER"
    emit_empty "none"
    exit 1
fi

# ---------- run apidiff ----------

# apidiff exit codes:
#   0 = compatible
#   1 = incompatible changes found (still produces useful output)
#   2 = error
RAW=$(apidiff "$OLD_DIR" "$NEW_DIR" 2>&1 || true)

# Parse apidiff output. Format is roughly:
#
#   Incompatible changes:
#   - pkg/path: <Symbol>: removed
#   - pkg/path: <Symbol>: changed from <X> to <Y>
#   - pkg/path: <Symbol>: method set changed
#
#   Compatible changes:
#   - pkg/path: <Symbol>: added
#
# (apidiff's text format varies slightly between versions.)
DIFF_JSON=$(echo "$RAW" | python3 - "$MODULE_PATH" <<'PY' 2>/dev/null || echo '{"removed":[],"added":[],"changed":[]}'
import json, sys, re

raw = sys.stdin.read()
target = sys.argv[1]

removed, added, changed = [], [], []

# Each section starts with `Incompatible changes:` or `Compatible changes:`
sections = re.split(r'^\s*(Incompatible changes:|Compatible changes:)\s*$',
                    raw, flags=re.M)

# sections is like ["preamble", "Incompatible changes:", "<body>", "Compatible changes:", "<body>"]
i = 0
while i < len(sections):
    head = sections[i].strip() if i < len(sections) else ""
    body = sections[i + 1] if (i + 1) < len(sections) else ""
    if head == "Incompatible changes:":
        for line in body.splitlines():
            line = line.rstrip()
            m = re.match(r'^- (.+?):\s*(removed|changed from (.+) to (.+)|method set changed|.*)$', line)
            if not m:
                continue
            name = m.group(1).strip()
            rest = m.group(2).strip()
            if rest == "removed":
                removed.append({"name": f"{target}.{name}", "kind": "incompatible_removed"})
            elif rest.startswith("changed from"):
                old_sig = (m.group(3) or "").strip()
                new_sig = (m.group(4) or "").strip()
                # Heuristic categorization
                if "func" in old_sig and "func" in new_sig:
                    cat = "signature_change"
                elif old_sig.split()[0:1] != new_sig.split()[0:1]:
                    cat = "kind_change"
                else:
                    cat = "type_change"
                changed.append({
                    "name": f"{target}.{name}",
                    "old_signature": old_sig,
                    "new_signature": new_sig,
                    "category": cat,
                })
            else:
                # method set changed / other → record as changed without sig info
                changed.append({
                    "name": f"{target}.{name}",
                    "old_signature": "",
                    "new_signature": "",
                    "category": "incompatible_other",
                    "raw": rest,
                })
        i += 2
        continue
    if head == "Compatible changes:":
        for line in body.splitlines():
            line = line.rstrip()
            m = re.match(r'^- (.+?):\s*(added|.*)$', line)
            if not m:
                continue
            name = m.group(1).strip()
            rest = m.group(2).strip()
            if rest == "added":
                added.append({"name": f"{target}.{name}", "kind": "added"})
            else:
                added.append({"name": f"{target}.{name}", "kind": "compatible_other", "raw": rest})
        i += 2
        continue
    i += 1

print(json.dumps({"removed": removed, "added": added, "changed": changed}))
PY
)

# ---------- harvest // Deprecated: comments added in new version ----------

DEPRECATED_JSON="[]"
if command -v grep >/dev/null 2>&1; then
    # Compare files in both dirs: list `// Deprecated:` lines unique to new
    DEPRECATED_JSON=$(python3 - "$OLD_DIR" "$NEW_DIR" <<'PY' 2>/dev/null || echo "[]"
import json, os, re, sys

old_dir, new_dir = sys.argv[1], sys.argv[2]

def collect(root):
    """Map symbol-name → set of file:line where `// Deprecated:` appears
    immediately before it. Best-effort: associates the comment with the
    next non-blank exported declaration line."""
    seen = {}
    for dirpath, dirs, files in os.walk(root):
        # Skip vendor/internal/testdata
        skip = set(["vendor", "testdata", "internal"])
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            if not f.endswith(".go") or f.endswith("_test.go"):
                continue
            full = os.path.join(dirpath, f)
            try:
                with open(full, encoding="utf-8") as fh:
                    lines = fh.read().splitlines()
            except Exception:
                continue
            # Find every `// Deprecated:` line followed by an exported decl
            for i, line in enumerate(lines):
                if "// Deprecated:" not in line:
                    continue
                # Look ahead for an exported declaration on the next few lines
                for j in range(i + 1, min(i + 6, len(lines))):
                    nxt = lines[j].lstrip()
                    if not nxt or nxt.startswith("//"):
                        continue
                    m = re.match(r'(?:func\s+(?:\([^)]+\)\s+)?|type\s+|var\s+|const\s+)?([A-Z]\w*)', nxt)
                    if m:
                        name = m.group(1)
                        seen.setdefault(name, []).append(f"{full.replace(root,'').lstrip(os.sep)}:{i+1}")
                    break
    return seen

old_dep = collect(old_dir)
new_dep = collect(new_dir)

# Only report symbols newly marked as Deprecated in new version
out = []
for sym, locs in new_dep.items():
    if sym not in old_dep:
        out.append({"name": sym, "locations": locs[:3]})
print(json.dumps(out))
PY
)
fi

# ---------- emit final JSON ----------

flush_warns
flush_errs

REMOVED=$(echo "$DIFF_JSON" | jq -c '.removed')
ADDED=$(echo "$DIFF_JSON" | jq -c '.added')
CHANGED=$(echo "$DIFF_JSON" | jq -c '.changed')

# Sentinel labels
OLD_LABEL="module cache: ${OLD_DIR}"
NEW_LABEL="module cache: ${NEW_DIR}"

cat <<EOF
{
  "package_name": "$MODULE_PATH",
  "old_version": "$OLD_VER",
  "new_version": "$NEW_VER",
  "strategy": "apidiff",
  "old_source_label": $(printf '%s' "$OLD_LABEL" | jq -Rs .),
  "new_source_label": $(printf '%s' "$NEW_LABEL" | jq -Rs .),
  "removed": $REMOVED,
  "added": $ADDED,
  "changed": $CHANGED,
  "deprecated_new": $DEPRECATED_JSON,
  "warnings": $WARNINGS_JSON,
  "errors": $ERRORS_JSON
}
EOF
