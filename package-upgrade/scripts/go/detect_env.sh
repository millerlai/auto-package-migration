#!/usr/bin/env bash
# detect_env_go.sh - Detect Go project environment.
#
# Usage: bash detect_env_go.sh <project_path>
# Output: JSON consumed by preflight.sh and SKILL.md.
#
# Output schema (aligned with detect_env_js.sh where it makes sense):
# {
#   "language": "go",
#   "pkg_manager": "gomod" | "dep" | "glide" | "govendor" | "gopath" | "unknown",
#   "go_version": "1.21.5",
#   "module_path": "example.com/myapp",
#   "go_directive": "1.21",
#   "toolchain_directive": "go1.21.5",
#   "lockfile_path": "go.sum",
#   "manifest_files": ["go.mod"],
#   "has_workspace": true | false,
#   "workspace_modules": ["./module-a", "./module-b"],
#   "is_vendored": true | false,
#   "vendor_modules_count": 0,
#   "has_replace_directives": true | false,
#   "replace_directives": [{"old": "...", "new": "...", "new_version": "..."}],
#   "has_exclude_directives": true | false,
#   "go_env": {"GOPROXY": "...", "GOPRIVATE": "...", "GOFLAGS": "...", "GOOS": "...", "GOARCH": "..."},
#   "govulncheck_available": true | false,
#   "govulncheck_version": "v1.1.3",
#   "apidiff_available": true | false,
#   "gomajor_available": true | false,
#   "netrc_present": true | false,
#   "git_remote_host": "github.com",
#   "git_remote_url": "git@github.com:...",
#   "memory_hints": ["vendored", "workspace", "replace_directives", "non_default_remote", "private_modules"]
# }

set -euo pipefail

PROJECT_PATH="${1:-.}"
cd "$PROJECT_PATH" || exit 1

# ---------- legacy / non-modules detection ----------

PKG_MANAGER="unknown"
MODULE_PATH=""
GO_DIRECTIVE=""
TOOLCHAIN_DIRECTIVE=""
LOCKFILE=""

if [ -f "go.mod" ]; then
    PKG_MANAGER="gomod"
    LOCKFILE="go.sum"
    # Extract module path (first line should be `module <path>`)
    MODULE_PATH=$( (grep -E '^module[[:space:]]+' go.mod 2>/dev/null || true) | head -1 | awk '{print $2}' | tr -d '"')
    # Extract go directive (the language version required by this module)
    GO_DIRECTIVE=$( (grep -E '^go[[:space:]]+' go.mod 2>/dev/null || true) | head -1 | awk '{print $2}')
    # Extract toolchain directive if any (Go 1.21+)
    TOOLCHAIN_DIRECTIVE=$( (grep -E '^toolchain[[:space:]]+' go.mod 2>/dev/null || true) | head -1 | awk '{print $2}')
elif [ -f "Gopkg.toml" ]; then
    PKG_MANAGER="dep"
elif [ -f "glide.yaml" ]; then
    PKG_MANAGER="glide"
elif [ -f "vendor.json" ] || [ -f "vendor/vendor.json" ]; then
    PKG_MANAGER="govendor"
elif find . -maxdepth 2 -name "*.go" -not -path "./vendor/*" 2>/dev/null | head -1 | grep -q .; then
    # Has .go files but no module manifest → GOPATH-style legacy
    PKG_MANAGER="gopath"
fi

# ---------- Go runtime version ----------

GO_VERSION="unknown"
if command -v go >/dev/null 2>&1; then
    GO_VERSION=$(go version 2>/dev/null | awk '{print $3}' | sed 's/^go//')
fi

# ---------- workspace (go.work) ----------

HAS_WORKSPACE="false"
WORKSPACE_MODULES_JSON="[]"
if [ -f "go.work" ]; then
    HAS_WORKSPACE="true"
    # Parse `use ( ... )` block (multi-line) and `use ./path` (single-line)
    if command -v jq >/dev/null 2>&1; then
        WORKSPACE_MODULES_JSON=$(
            awk '
                /^use[[:space:]]*\(/ { in_block=1; next }
                in_block && /^\)/ { in_block=0; next }
                in_block { gsub(/^[[:space:]]+|[[:space:]]+$/, ""); if ($0 != "" && $0 !~ /^\/\//) print $0; next }
                /^use[[:space:]]+/ { print $2 }
            ' go.work 2>/dev/null \
            | jq -R -s 'split("\n") | map(select(. != ""))'
        )
    fi
fi

# ---------- vendor/ detection ----------

IS_VENDORED="false"
VENDOR_MODULES_COUNT=0
if [ -f "vendor/modules.txt" ]; then
    IS_VENDORED="true"
    # Each `# <module>` line in modules.txt = one vendored module
    VENDOR_MODULES_COUNT=$(grep -c '^# ' vendor/modules.txt 2>/dev/null || echo 0)
fi

# ---------- replace / exclude directives ----------

HAS_REPLACE="false"
HAS_EXCLUDE="false"
REPLACE_JSON="[]"

if [ -f "go.mod" ]; then
    if grep -qE '^replace[[:space:]]|=>' go.mod 2>/dev/null; then
        HAS_REPLACE="true"
    fi
    if grep -qE '^exclude[[:space:]]' go.mod 2>/dev/null; then
        HAS_EXCLUDE="true"
    fi

    # Parse replace directives — supports single-line `replace ... => ...` and block form.
    # NOTE: This is a quick scan for the env summary; dep_tree_go.py does a more
    # rigorous parse for upgrade-decision purposes.
    if [ "$HAS_REPLACE" = "true" ] && command -v jq >/dev/null 2>&1; then
        REPLACE_JSON=$(python3 - <<'PY' 2>/dev/null || echo "[]"
import json, re, sys
out = []
try:
    text = open("go.mod", encoding="utf-8").read()
except Exception:
    print("[]"); sys.exit(0)

# Single-line: `replace <old> [<old-ver>] => <new> [<new-ver>]`
single_re = re.compile(
    r'^\s*replace\s+(\S+)\s+(v\S+)?\s*=>\s*(\S+)\s*(v\S+)?\s*$',
    re.M,
)
for m in single_re.finditer(text):
    out.append({
        "old": m.group(1),
        "old_version": m.group(2) or "",
        "new": m.group(3),
        "new_version": m.group(4) or "",
    })

# Block form: `replace ( ... )` (multi-line inside parens)
block_re = re.compile(r'^replace\s*\(\s*$(.*?)^\)\s*$', re.M | re.S)
inner_re = re.compile(r'(\S+)\s+(v\S+)?\s*=>\s*(\S+)\s*(v\S+)?\s*$')
for blk in block_re.finditer(text):
    body = blk.group(1)
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        mm = inner_re.match(line)
        if mm:
            out.append({
                "old": mm.group(1),
                "old_version": mm.group(2) or "",
                "new": mm.group(3),
                "new_version": mm.group(4) or "",
            })

print(json.dumps(out))
PY
)
    fi
fi

# ---------- go env ----------

GOPROXY=""
GOPRIVATE=""
GOFLAGS=""
GOOS=""
GOARCH=""
if command -v go >/dev/null 2>&1; then
    GOPROXY=$(go env GOPROXY 2>/dev/null || echo "")
    GOPRIVATE=$(go env GOPRIVATE 2>/dev/null || echo "")
    GOFLAGS=$(go env GOFLAGS 2>/dev/null || echo "")
    GOOS=$(go env GOOS 2>/dev/null || echo "")
    GOARCH=$(go env GOARCH 2>/dev/null || echo "")
fi

# ---------- tool availability ----------

GOVULNCHECK_AVAILABLE="false"
GOVULNCHECK_VERSION=""
if command -v govulncheck >/dev/null 2>&1; then
    GOVULNCHECK_AVAILABLE="true"
    GOVULNCHECK_VERSION=$(govulncheck -version 2>/dev/null | grep -oE 'Scanner: govulncheck@[^[:space:]]+|govulncheck@[^[:space:]]+|v[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "")
fi

APIDIFF_AVAILABLE="false"
if command -v apidiff >/dev/null 2>&1; then
    APIDIFF_AVAILABLE="true"
fi

GOMAJOR_AVAILABLE="false"
if command -v gomajor >/dev/null 2>&1; then
    GOMAJOR_AVAILABLE="true"
fi

# ---------- .netrc (used by Go for HTTPS-authenticated module downloads) ----------

NETRC_PRESENT="false"
if [ -f "$HOME/.netrc" ]; then
    NETRC_PRESENT="true"
fi

# ---------- git remote ----------

GIT_REMOTE_URL=""
GIT_REMOTE_HOST=""
if [ -d ".git" ] || git rev-parse --git-dir >/dev/null 2>&1; then
    GIT_REMOTE_URL=$(git remote get-url origin 2>/dev/null || echo "")
    if [ -n "$GIT_REMOTE_URL" ]; then
        GIT_REMOTE_HOST=$(echo "$GIT_REMOTE_URL" | sed -E 's,^(git@|ssh://git@|https?://)?([^/:]+).*,\2,' || echo "")
    fi
fi || true

# ---------- manifest files ----------

MANIFEST_FILES_JSON="[]"
if command -v jq >/dev/null 2>&1; then
    MANIFEST_FILES_JSON=$(
        { for f in go.mod go.work Gopkg.toml glide.yaml vendor.json; do
            [ -f "$f" ] && echo "$f" || true
        done; } | jq -R -s 'split("\n") | map(select(. != ""))' 2>/dev/null || echo "[]"
    )
fi

# ---------- memory hints ----------

MEMORY_HINTS=()
[ "$IS_VENDORED" = "true" ] && MEMORY_HINTS+=("\"vendored\"")
[ "$HAS_WORKSPACE" = "true" ] && MEMORY_HINTS+=("\"workspace\"")
[ "$HAS_REPLACE" = "true" ] && MEMORY_HINTS+=("\"replace_directives\"")
[ -n "$GOPRIVATE" ] && MEMORY_HINTS+=("\"private_modules\"")
if [ -n "$GIT_REMOTE_HOST" ] && [ "$GIT_REMOTE_HOST" != "github.com" ] && [ "$GIT_REMOTE_HOST" != "gitlab.com" ] && [ "$GIT_REMOTE_HOST" != "bitbucket.org" ]; then
    MEMORY_HINTS+=("\"non_default_remote\"")
fi
[ "$PKG_MANAGER" != "gomod" ] && [ "$PKG_MANAGER" != "unknown" ] && MEMORY_HINTS+=("\"legacy_$PKG_MANAGER\"")
MEMORY_HINTS_JSON="[$(IFS=,; echo "${MEMORY_HINTS[*]+"${MEMORY_HINTS[*]}"}")]"

# ---------- emit JSON ----------

# JSON-safe escaping for strings via jq if available
js_string() {
    if command -v jq >/dev/null 2>&1; then
        printf '%s' "$1" | jq -Rs .
    else
        # crude fallback — only safe for ASCII without quotes/newlines
        printf '"%s"' "$1"
    fi
}

cat <<EOF
{
  "language": "go",
  "pkg_manager": "$PKG_MANAGER",
  "go_version": "$GO_VERSION",
  "module_path": "$MODULE_PATH",
  "go_directive": "$GO_DIRECTIVE",
  "toolchain_directive": "$TOOLCHAIN_DIRECTIVE",
  "lockfile_path": "$LOCKFILE",
  "manifest_files": $MANIFEST_FILES_JSON,
  "has_workspace": $HAS_WORKSPACE,
  "workspace_modules": $WORKSPACE_MODULES_JSON,
  "is_vendored": $IS_VENDORED,
  "vendor_modules_count": $VENDOR_MODULES_COUNT,
  "has_replace_directives": $HAS_REPLACE,
  "replace_directives": $REPLACE_JSON,
  "has_exclude_directives": $HAS_EXCLUDE,
  "go_env": {
    "GOPROXY": $(js_string "$GOPROXY"),
    "GOPRIVATE": $(js_string "$GOPRIVATE"),
    "GOFLAGS": $(js_string "$GOFLAGS"),
    "GOOS": $(js_string "$GOOS"),
    "GOARCH": $(js_string "$GOARCH")
  },
  "govulncheck_available": $GOVULNCHECK_AVAILABLE,
  "govulncheck_version": $(js_string "$GOVULNCHECK_VERSION"),
  "apidiff_available": $APIDIFF_AVAILABLE,
  "gomajor_available": $GOMAJOR_AVAILABLE,
  "netrc_present": $NETRC_PRESENT,
  "git_remote_host": "$GIT_REMOTE_HOST",
  "git_remote_url": $(js_string "$GIT_REMOTE_URL"),
  "memory_hints": $MEMORY_HINTS_JSON
}
EOF
