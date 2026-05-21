#!/usr/bin/env bash
# detect_env_js.sh - Detect JavaScript package manager and project environment.
#
# Usage: bash detect_env_js.sh <project_path>
# Output: JSON with environment information consumed by preflight.sh and SKILL.md.
#
# Output schema (mirrors detect_env.sh where possible, plus JS-specific fields):
# {
#   "language": "javascript",
#   "pkg_manager": "npm" | "yarn" | "pnpm" | "bun" | "unknown",
#   "pkg_manager_version": "3.8.2",
#   "pkg_manager_bin": "yarn" | "node .yarn/releases/yarn-3.8.2.cjs" | ...,
#   "uses_corepack": true | false,
#   "yarn_release_path": ".yarn/releases/yarn-3.8.2.cjs" | "",
#   "yarn_node_linker": "pnp" | "node-modules" | "",
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
#   "test_framework_hint": "jest" | "vitest" | "mocha" | "node-test" | "ava" | "unknown",
#   "npm_config_files": [".yarnrc.yml", ".yarnrc.default.yml", ".npmrc"],
#   "env_var_placeholders": ["JFROG_TOKEN", "NPM_TOKEN", ...],
#   "custom_registries": [{"scope": "@tonic-one", "registry": "https://...", "auth_env_var": "JFROG_TOKEN"}, ...],
#   "git_remote_host": "github.com" | "adc.github.trendmicro.com" | "",
#   "git_remote_url": "git@github.com:...",
#   "has_node_modules": true | false,
#   "memory_hints": ["yarn3_corepack", "workspace", "custom_registry", "ghe_remote"]
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

# ---------- package manager + lockfile ----------

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

# ---------- package.json fields via jq ----------

PACKAGE_MANAGER_FIELD=""
WORKSPACE_GLOBS="[]"
IS_WORKSPACE="false"
TYPES_ENTRY=""
TEST_SCRIPT=""
HAS_DEP_TYPESCRIPT="false"

if command -v jq >/dev/null 2>&1; then
    PACKAGE_MANAGER_FIELD=$(jq -r '.packageManager // ""' package.json 2>/dev/null || echo "")
    if [ -n "$PACKAGE_MANAGER_FIELD" ]; then
        case "$PACKAGE_MANAGER_FIELD" in
            npm@*) PKG_MANAGER="npm" ;;
            yarn@*) PKG_MANAGER="yarn" ;;
            pnpm@*) PKG_MANAGER="pnpm" ;;
            bun@*) PKG_MANAGER="bun" ;;
        esac
    fi

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

    if jq -e '(.dependencies.typescript // .devDependencies.typescript // empty)' package.json >/dev/null 2>&1; then
        HAS_DEP_TYPESCRIPT="true"
    fi
else
    PACKAGE_MANAGER_FIELD=$(grep -oE '"packageManager"[[:space:]]*:[[:space:]]*"[^"]+"' package.json 2>/dev/null | sed -E 's/.*"([^"]+)"$/\1/' || echo "")
    TEST_SCRIPT=$(grep -oE '"test"[[:space:]]*:[[:space:]]*"[^"]+"' package.json 2>/dev/null | head -1 | sed -E 's/.*"([^"]+)"$/\1/' || echo "")
    grep -q '"typescript"' package.json 2>/dev/null && HAS_DEP_TYPESCRIPT="true" || true
fi

# ---------- yarn binary / corepack detection (#3) ----------

USES_COREPACK="false"
YARN_RELEASE_PATH=""
PKG_MANAGER_BIN=""
PKG_MANAGER_VERSION=""

if [ "$PKG_MANAGER" = "yarn" ]; then
    if [ -d ".yarn/releases" ]; then
        # Pick the highest-version yarn-*.cjs (corepack-managed)
        YARN_RELEASE_PATH=$(ls .yarn/releases/yarn-*.cjs 2>/dev/null | sort -V | tail -1 || echo "")
        if [ -n "$YARN_RELEASE_PATH" ]; then
            USES_COREPACK="true"
            PKG_MANAGER_BIN="node $YARN_RELEASE_PATH"
            # extract version from filename
            PKG_MANAGER_VERSION=$(echo "$YARN_RELEASE_PATH" | sed -E 's/.*yarn-([0-9.]+)\.cjs/\1/')
        fi
    fi
    if [ -z "$PKG_MANAGER_BIN" ] && command -v yarn >/dev/null 2>&1; then
        PKG_MANAGER_BIN="yarn"
        PKG_MANAGER_VERSION=$(yarn --version 2>/dev/null || echo "")
    fi
elif [ "$PKG_MANAGER" = "pnpm" ]; then
    if command -v pnpm >/dev/null 2>&1; then
        PKG_MANAGER_BIN="pnpm"
        PKG_MANAGER_VERSION=$(pnpm --version 2>/dev/null || echo "")
    fi
    # Corepack-managed pnpm goes through corepack shim, no .yarn/releases equivalent
elif [ "$PKG_MANAGER" = "npm" ]; then
    if command -v npm >/dev/null 2>&1; then
        PKG_MANAGER_BIN="npm"
        PKG_MANAGER_VERSION=$(npm --version 2>/dev/null || echo "")
    fi
elif [ "$PKG_MANAGER" = "bun" ]; then
    if command -v bun >/dev/null 2>&1; then
        PKG_MANAGER_BIN="bun"
        PKG_MANAGER_VERSION=$(bun --version 2>/dev/null || echo "")
    fi
fi

# packageManager field overrides version (Corepack standard)
if [ -n "$PACKAGE_MANAGER_FIELD" ] && [ -z "$PKG_MANAGER_VERSION" ]; then
    PKG_MANAGER_VERSION=$(echo "$PACKAGE_MANAGER_FIELD" | sed -E 's/^[^@]+@([^+]+).*/\1/')
fi

# ---------- yarn nodeLinker ----------

YARN_NODE_LINKER=""
for f in .yarnrc.yml .yarnrc.default.yml; do
    if [ -f "$f" ]; then
        v=$(grep -E '^nodeLinker:' "$f" 2>/dev/null | awk '{print $2}' | tr -d '"' || echo "")
        if [ -n "$v" ]; then
            YARN_NODE_LINKER="$v"
            break
        fi
    fi
done
# Default for yarn 3+ is pnp; for yarn 1 there is no concept
if [ "$PKG_MANAGER" = "yarn" ] && [ -z "$YARN_NODE_LINKER" ]; then
    case "$PKG_MANAGER_VERSION" in
        1.*) YARN_NODE_LINKER="node-modules" ;;
        *)   YARN_NODE_LINKER="pnp" ;;
    esac
fi

# ---------- npm/yarn config files: env var placeholders + custom registries (#1, #14) ----------

NPM_CONFIG_FILES_ARR=()
for f in .yarnrc.yml .yarnrc.default.yml .yarnrc .npmrc; do
    [ -f "$f" ] && NPM_CONFIG_FILES_ARR+=("$f")
done

# Extract ${ENV_VAR} placeholders across all config files
ENV_PLACEHOLDERS_RAW=""
if [ "${#NPM_CONFIG_FILES_ARR[@]}" -gt 0 ]; then
    ENV_PLACEHOLDERS_RAW=$(grep -ohE '\$\{[A-Z_][A-Z0-9_]*\}' "${NPM_CONFIG_FILES_ARR[@]}" 2>/dev/null | tr -d '${}' | sort -u || echo "")
fi

# Build env_var_placeholders JSON array
ENV_PLACEHOLDERS_JSON="[]"
if [ -n "$ENV_PLACEHOLDERS_RAW" ]; then
    ENV_PLACEHOLDERS_JSON=$(printf '%s\n' "$ENV_PLACEHOLDERS_RAW" | jq -R . 2>/dev/null | jq -s . 2>/dev/null || echo "[]")
fi

# Parse custom registries (scope-prefixed entries)
# .yarnrc.yml format:
#   npmScopes:
#     scope-name:
#       npmRegistryServer: "https://..."
#       npmAuthToken: "${JFROG_TOKEN}"
# .npmrc format:
#   @scope:registry=https://...
#   //registry.host/:_authToken=${TOKEN}
CUSTOM_REGISTRIES_JSON="[]"
if [ -f ".yarnrc.yml" ] || [ -f ".yarnrc.default.yml" ]; then
    CUSTOM_REGISTRIES_JSON=$(
        for f in .yarnrc.yml .yarnrc.default.yml; do
            [ -f "$f" ] || continue
            python3 - "$f" <<'PY' 2>/dev/null || true
import re, sys, json
path = sys.argv[1]
out = []
try:
    text = open(path, encoding="utf-8").read()
except Exception:
    sys.exit(0)
# crude YAML-ish parser for npmScopes block (indentation based)
m = re.search(r'^npmScopes:\s*\n((?:[ \t]+.*\n?)+)', text, re.M)
if m:
    block = m.group(1)
    # Split into per-scope sub-blocks (top-level 2-space indent)
    scope_pat = re.compile(r'^[ \t]+([\w\-./]+):\s*\n((?:[ \t]{4,}.*\n?)+)', re.M)
    for sm in scope_pat.finditer(block):
        scope = sm.group(1)
        body = sm.group(2)
        registry = ""
        auth = ""
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("npmRegistryServer:"):
                registry = line.split(":", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("npmAuthToken:") or line.startswith("npmAlwaysAuth:"):
                # extract ${VAR} if present
                vm = re.search(r'\$\{([A-Z_][A-Z0-9_]*)\}', line)
                if vm:
                    auth = vm.group(1)
        if registry:
            entry = {"scope": "@" + scope if not scope.startswith("@") else scope,
                     "registry": registry,
                     "auth_env_var": auth,
                     "source_file": path}
            out.append(entry)
for entry in out:
    print(json.dumps(entry))
PY
        done | jq -s . 2>/dev/null || echo "[]"
    )
fi

# Also parse .npmrc style
if [ -f ".npmrc" ]; then
    NPMRC_REGISTRIES=$(python3 - <<'PY' 2>/dev/null || true
import re, json
out = []
try:
    text = open(".npmrc", encoding="utf-8").read()
except Exception:
    raise SystemExit
# @scope:registry=URL
for m in re.finditer(r'^(@[\w\-./]+):registry\s*=\s*(\S+)', text, re.M):
    out.append({"scope": m.group(1), "registry": m.group(2),
                "auth_env_var": "", "source_file": ".npmrc"})
# //host/:_authToken=${VAR}
host_auth = {}
for m in re.finditer(r'^//([\w\-./:]+)/?:_authToken\s*=\s*(\S+)', text, re.M):
    host = m.group(1)
    val = m.group(2)
    vm = re.search(r'\$\{([A-Z_][A-Z0-9_]*)\}', val)
    if vm:
        host_auth[host] = vm.group(1)
# Cross-reference: tag auth_env_var on entries whose registry matches a host in host_auth
for entry in out:
    for host, env in host_auth.items():
        if host in entry["registry"]:
            entry["auth_env_var"] = env
            break
for entry in out:
    print(json.dumps(entry))
PY
)
    if [ -n "$NPMRC_REGISTRIES" ]; then
        CUSTOM_REGISTRIES_JSON=$(
            echo "$CUSTOM_REGISTRIES_JSON" | jq -c '.' 2>/dev/null
            echo "$NPMRC_REGISTRIES" | jq -s '.' 2>/dev/null
        | jq -s 'add' 2>/dev/null || echo "$CUSTOM_REGISTRIES_JSON")
    fi
fi

# ---------- git remote (#2) ----------

GIT_REMOTE_URL=""
GIT_REMOTE_HOST=""
if [ -d ".git" ] || git rev-parse --git-dir >/dev/null 2>&1; then
    GIT_REMOTE_URL=$(git remote get-url origin 2>/dev/null || echo "")
    if [ -n "$GIT_REMOTE_URL" ]; then
        # Parse host from URL forms: git@host:..., ssh://git@host/..., https://host/...
        GIT_REMOTE_HOST=$(echo "$GIT_REMOTE_URL" | sed -E 's,^(git@|ssh://git@|https?://)?([^/:]+).*,\2,')
    fi
fi

# ---------- node_modules presence (informs lockfile-first dep_tree behavior) ----------

HAS_NODE_MODULES="false"
[ -d "node_modules" ] && HAS_NODE_MODULES="true"

# ---------- TypeScript detection ----------

HAS_TYPESCRIPT="false"
TSCONFIG_PATH=""
if [ -f "tsconfig.json" ]; then
    HAS_TYPESCRIPT="true"
    TSCONFIG_PATH="tsconfig.json"
elif [ "$HAS_DEP_TYPESCRIPT" = "true" ] || [ -n "$TYPES_ENTRY" ]; then
    HAS_TYPESCRIPT="true"
fi

# ---------- Test framework hint ----------

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
if [ "$TEST_HINT" = "unknown" ] && command -v jq >/dev/null 2>&1; then
    for fw in vitest jest mocha ava playwright; do
        if jq -e "(.dependencies.\"$fw\" // .devDependencies.\"$fw\" // empty)" package.json >/dev/null 2>&1; then
            TEST_HINT="$fw"
            break
        fi
    done
fi

# ---------- Manifest files ----------

MANIFEST_FILES=$(find . -maxdepth 4 -name "package.json" \
    -not -path "./node_modules/*" \
    -not -path "*/node_modules/*" \
    -not -path "./.git/*" 2>/dev/null | head -50 | \
    jq -R -s 'split("\n") | map(select(. != ""))' 2>/dev/null || echo "[\"./package.json\"]")

# Files config files as JSON array
NPM_CONFIG_FILES_JSON=$(printf '%s\n' "${NPM_CONFIG_FILES_ARR[@]+"${NPM_CONFIG_FILES_ARR[@]}"}" | jq -R -s 'split("\n") | map(select(. != ""))' 2>/dev/null || echo "[]")

# ---------- Memory hints (#14) ----------

MEMORY_HINTS=()
[ "$USES_COREPACK" = "true" ] && MEMORY_HINTS+=("\"yarn3_corepack\"")
[ "$IS_WORKSPACE" = "true" ] && MEMORY_HINTS+=("\"workspace\"")
if [ "$CUSTOM_REGISTRIES_JSON" != "[]" ] && [ -n "$CUSTOM_REGISTRIES_JSON" ]; then
    MEMORY_HINTS+=("\"custom_registry\"")
fi
if [ -n "$GIT_REMOTE_HOST" ] && [ "$GIT_REMOTE_HOST" != "github.com" ] && [ "$GIT_REMOTE_HOST" != "gitlab.com" ] && [ "$GIT_REMOTE_HOST" != "bitbucket.org" ]; then
    MEMORY_HINTS+=("\"non_default_remote\"")
fi
MEMORY_HINTS_JSON="[$(IFS=,; echo "${MEMORY_HINTS[*]+"${MEMORY_HINTS[*]}"}")]"

# ---------- Emit JSON ----------

cat <<EOF
{
  "language": "javascript",
  "pkg_manager": "$PKG_MANAGER",
  "pkg_manager_version": "$PKG_MANAGER_VERSION",
  "pkg_manager_bin": $(printf '%s' "$PKG_MANAGER_BIN" | jq -Rs . 2>/dev/null || echo "\"\""),
  "uses_corepack": $USES_COREPACK,
  "yarn_release_path": "$YARN_RELEASE_PATH",
  "yarn_node_linker": "$YARN_NODE_LINKER",
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
  "test_framework_hint": "$TEST_HINT",
  "npm_config_files": $NPM_CONFIG_FILES_JSON,
  "env_var_placeholders": $ENV_PLACEHOLDERS_JSON,
  "custom_registries": $CUSTOM_REGISTRIES_JSON,
  "git_remote_host": "$GIT_REMOTE_HOST",
  "git_remote_url": $(printf '%s' "$GIT_REMOTE_URL" | jq -Rs . 2>/dev/null || echo "\"\""),
  "has_node_modules": $HAS_NODE_MODULES,
  "memory_hints": $MEMORY_HINTS_JSON
}
EOF
