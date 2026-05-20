#!/usr/bin/env bash
# detect_env_js.sh - Detect JavaScript package manager and project environment.
#
# Usage: bash detect_env_js.sh <project_path>
# Output: JSON with environment information.
#
# Output schema (mirrors detect_env.sh where possible, plus JS-specific fields):
# {
#   "language": "javascript",
#   "pkg_manager": "npm" | "yarn" | "pnpm" | "bun" | "unknown",
#   "package_manager_field": "<value of package.json#packageManager>" | "",
#   "node_version": "20.x.x" | "unknown",
#   "lockfile_path": "<path>" | "",
#   "manifest_files": ["package.json", ...],
#   "is_workspace": true | false,
#   "workspace_globs": ["packages/*", ...],
#   "has_typescript": true | false,
#   "tsconfig_path": "<path>" | "",
#   "types_entry": "<value of package.json#types or typings>" | "",
#   "test_script": "<value of package.json#scripts.test>" | "",
#   "test_framework_hint": "jest" | "vitest" | "mocha" | "node-test" | "ava" | "unknown"
# }

set -euo pipefail

PROJECT_PATH="${1:-.}"
cd "$PROJECT_PATH" || exit 1

if [ ! -f "package.json" ]; then
    cat <<EOF
{
  "language": "javascript",
  "pkg_manager": "unknown",
  "error": "package.json not found in $PROJECT_PATH"
}
EOF
    exit 1
fi

# Detect package manager (priority: bun > pnpm > yarn > npm)
PKG_MANAGER="unknown"
LOCKFILE=""
if [ -f "bun.lock" ] || [ -f "bun.lockb" ]; then
    PKG_MANAGER="bun"
    [ -f "bun.lock" ] && LOCKFILE="bun.lock" || LOCKFILE="bun.lockb"
elif [ -f "pnpm-lock.yaml" ]; then
    PKG_MANAGER="pnpm"
    LOCKFILE="pnpm-lock.yaml"
elif [ -f "yarn.lock" ]; then
    PKG_MANAGER="yarn"
    LOCKFILE="yarn.lock"
elif [ -f "package-lock.json" ]; then
    PKG_MANAGER="npm"
    LOCKFILE="package-lock.json"
elif [ -f "npm-shrinkwrap.json" ]; then
    PKG_MANAGER="npm"
    LOCKFILE="npm-shrinkwrap.json"
fi

NODE_VERSION=$(node --version 2>/dev/null | sed 's/^v//' || echo "unknown")

# package.json fields via jq (fallback to empty string if jq missing or key absent)
PACKAGE_MANAGER_FIELD=""
WORKSPACE_GLOBS="[]"
IS_WORKSPACE="false"
TYPES_ENTRY=""
TEST_SCRIPT=""
HAS_DEP_TYPESCRIPT="false"

if command -v jq >/dev/null 2>&1; then
    PACKAGE_MANAGER_FIELD=$(jq -r '.packageManager // ""' package.json 2>/dev/null || echo "")

    # If packageManager field is set (Corepack), let it override detection
    if [ -n "$PACKAGE_MANAGER_FIELD" ]; then
        case "$PACKAGE_MANAGER_FIELD" in
            npm@*) PKG_MANAGER="npm" ;;
            yarn@*) PKG_MANAGER="yarn" ;;
            pnpm@*) PKG_MANAGER="pnpm" ;;
            bun@*) PKG_MANAGER="bun" ;;
        esac
    fi

    # workspaces can be an array or {packages: [...]} object
    WS_RAW=$(jq -c '.workspaces // null' package.json 2>/dev/null || echo "null")
    if [ "$WS_RAW" != "null" ]; then
        IS_WORKSPACE="true"
        if echo "$WS_RAW" | jq -e 'type=="array"' >/dev/null 2>&1; then
            WORKSPACE_GLOBS="$WS_RAW"
        elif echo "$WS_RAW" | jq -e '.packages | type=="array"' >/dev/null 2>&1; then
            WORKSPACE_GLOBS=$(echo "$WS_RAW" | jq -c '.packages')
        fi
    fi

    TYPES_ENTRY=$(jq -r '.types // .typings // ""' package.json 2>/dev/null || echo "")
    TEST_SCRIPT=$(jq -r '.scripts.test // ""' package.json 2>/dev/null || echo "")

    # Is typescript declared anywhere?
    if jq -e '(.dependencies.typescript // .devDependencies.typescript // empty)' package.json >/dev/null 2>&1; then
        HAS_DEP_TYPESCRIPT="true"
    fi
else
    # jq missing: best-effort grep
    PACKAGE_MANAGER_FIELD=$(grep -oE '"packageManager"[[:space:]]*:[[:space:]]*"[^"]+"' package.json 2>/dev/null | sed -E 's/.*"([^"]+)"$/\1/' || echo "")
    TEST_SCRIPT=$(grep -oE '"test"[[:space:]]*:[[:space:]]*"[^"]+"' package.json 2>/dev/null | head -1 | sed -E 's/.*"([^"]+)"$/\1/' || echo "")
    grep -q '"typescript"' package.json 2>/dev/null && HAS_DEP_TYPESCRIPT="true" || true
fi

# TypeScript detection: tsconfig.json OR typescript dep OR types entry OR any *.ts source
HAS_TYPESCRIPT="false"
TSCONFIG_PATH=""
if [ -f "tsconfig.json" ]; then
    HAS_TYPESCRIPT="true"
    TSCONFIG_PATH="tsconfig.json"
elif [ "$HAS_DEP_TYPESCRIPT" = "true" ] || [ -n "$TYPES_ENTRY" ]; then
    HAS_TYPESCRIPT="true"
fi

# Test framework hint from test script string + deps
TEST_HINT="unknown"
if [ -n "$TEST_SCRIPT" ]; then
    case "$TEST_SCRIPT" in
        *vitest*) TEST_HINT="vitest" ;;
        *jest*) TEST_HINT="jest" ;;
        *mocha*) TEST_HINT="mocha" ;;
        *"node --test"*|*"node:test"*) TEST_HINT="node-test" ;;
        *ava*) TEST_HINT="ava" ;;
        *playwright*) TEST_HINT="playwright" ;;
    esac
fi
# Fall back to dep sniffing if scripts.test was empty/ambiguous
if [ "$TEST_HINT" = "unknown" ] && command -v jq >/dev/null 2>&1; then
    for fw in vitest jest mocha ava playwright; do
        if jq -e "(.dependencies.\"$fw\" // .devDependencies.\"$fw\" // empty)" package.json >/dev/null 2>&1; then
            TEST_HINT="$fw"
            break
        fi
    done
fi

# Manifest files: root package.json + workspace package.jsons (capped)
MANIFEST_FILES=$(find . -maxdepth 4 -name "package.json" \
    -not -path "./node_modules/*" \
    -not -path "*/node_modules/*" \
    -not -path "./.git/*" 2>/dev/null | head -50 | \
    jq -R -s 'split("\n") | map(select(. != ""))' 2>/dev/null || echo "[\"./package.json\"]")

# Emit JSON
cat <<EOF
{
  "language": "javascript",
  "pkg_manager": "$PKG_MANAGER",
  "package_manager_field": "$PACKAGE_MANAGER_FIELD",
  "node_version": "$NODE_VERSION",
  "lockfile_path": "$LOCKFILE",
  "manifest_files": $MANIFEST_FILES,
  "is_workspace": $IS_WORKSPACE,
  "workspace_globs": $WORKSPACE_GLOBS,
  "has_typescript": $HAS_TYPESCRIPT,
  "tsconfig_path": "$TSCONFIG_PATH",
  "types_entry": "$TYPES_ENTRY",
  "test_script": $(printf '%s' "$TEST_SCRIPT" | jq -Rs . 2>/dev/null || echo "\"\""),
  "test_framework_hint": "$TEST_HINT"
}
EOF
