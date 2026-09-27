#!/usr/bin/env bash
# preflight.sh - Run all environment checks BEFORE entering Phase 1.
#
# Usage: bash preflight.sh <project_path> [--json]
#
# Without --json: prints a human-readable checklist (used by the LLM to relay
# status to the user). With --json: emits a structured object for programmatic
# decision-making.
#
# This is the orchestrator that wraps detect_env_js.sh + adds checks that
# require running other tools (gh auth status, env var presence, git tree).
#
# Output (JSON shape):
# {
#   "blockers": [{"id": "...", "title": "...", "remediation": "..."}],
#   "warnings": [{"id": "...", "title": "...", "remediation": "..."}],
#   "ok":       [{"id": "...", "title": "..."}],
#   "summary": {"ok_count": N, "warn_count": N, "blocker_count": N},
#   "env": <full detect_env_js.sh output>
# }

set -euo pipefail

PROJECT_PATH="${1:-.}"
JSON_MODE="false"
if [ "${2:-}" = "--json" ]; then JSON_MODE="true"; fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DETECT="$SCRIPT_DIR/detect_env.sh"

if [ ! -x "$DETECT" ]; then
    echo "ERROR: detect_env.sh not found at $DETECT" >&2
    exit 1
fi

# Auto-load persisted token files BEFORE checking env vars. Each .env.<name>
# in the project root (currently .env.jfrog; other registries may add their
# own later) is loaded if present. Files are owned by the user only
# (chmod 600 enforced by save_token.sh) and gitignored.
# SECURITY: parse KEY=VALUE textually (load_token_files.sh) rather than sourcing,
# so a token value can never execute embedded $(...) / backticks on load.
PROJECT_ABS=$(cd "$PROJECT_PATH" && pwd -P)
# shellcheck source=../common/load_token_files.sh
. "$SCRIPT_DIR/../common/load_token_files.sh"
# shellcheck disable=SC2046,SC2086 # fixed, space-separated list of basenames
load_token_files "$PROJECT_ABS" $(token_files_for js)

# Run language detector
ENV_JSON=$(bash "$DETECT" "$PROJECT_PATH" 2>/dev/null || echo '{}')

# Extract everything we need with jq (fall back to grep if jq absent)
have_jq() { command -v jq >/dev/null 2>&1; }

j() {
    if have_jq; then echo "$ENV_JSON" | jq -r "$1"
    else echo ""
    fi
}

PKG_MANAGER=$(j '.pkg_manager // ""')
PKG_MANAGER_BIN=$(j '.pkg_manager_bin // ""')
PKG_MANAGER_VER=$(j '.pkg_manager_version // ""')
USES_COREPACK=$(j '.uses_corepack // false')
ENV_PLACEHOLDERS=$(j '.env_var_placeholders // [] | .[]?')
GIT_REMOTE_HOST=$(j '.git_remote_host // ""')
GIT_REMOTE_URL=$(j '.git_remote_url // ""')
HAS_NODE_MODULES=$(j '.has_node_modules // false')

# JSON accumulators (built as bash arrays of single-line JSON objects)
declare -a BLOCKERS=()
declare -a WARNINGS=()
declare -a OK=()

add_ok()       { OK+=("$(jq -nc --arg id "$1" --arg title "$2" '{id:$id, title:$title}')"); }
add_warn()     { WARNINGS+=("$(jq -nc --arg id "$1" --arg title "$2" --arg remediation "$3" '{id:$id, title:$title, remediation:$remediation}')"); }
add_blocker()  { BLOCKERS+=("$(jq -nc --arg id "$1" --arg title "$2" --arg remediation "$3" '{id:$id, title:$title, remediation:$remediation}')"); }

# Mapping host → token portal URL (from auth_tokens.md)
token_portal_url() {
    local host="$1"
    case "$host" in
        *.jfrog.trendmicro.com|jfrog.trendmicro.com)
            echo "https://jfrog.trendmicro.com/ui/admin/artifactory/user_profile" ;;
        *.pkgs.visualstudio.com)
            echo "https://dev.azure.com/<org>/_usersSettings/tokens" ;;
        npm.pkg.github.com)
            echo "https://github.com/settings/tokens" ;;
        *.github.trendmicro.com)
            echo "https://${host}/settings/tokens" ;;
        *.github.com)
            echo "https://github.com/settings/tokens" ;;
        *)
            echo "(see auth_tokens.md or ask the registry maintainer)" ;;
    esac
}

# Find the full registry URL that references a given env var (host AND path —
# npm scopes auth to a specific path on a host, not just the host; C8).
registry_url_for_env_var() {
    local var="$1"
    if have_jq; then
        echo "$ENV_JSON" | jq -r --arg v "$var" \
            '(.custom_registries // []) | map(select(.auth_env_var == $v)) | .[0].registry // ""'
    fi
}

# npm's own resolution order (C8): given a registry URL, walk its path one
# segment at a time from most specific down to the bare host, checking
# project .npmrc before ~/.npmrc at each level. The FIRST level where either
# file has an auth key decides the answer — a literal value is native, a
# ${VAR} placeholder is not, and either way nothing less specific is
# consulted. Echoes the source file and returns 0 on a literal; returns 2
# (decided, not native) on a placeholder; returns 1 when no level matched
# anywhere, so the caller can still try yarn's own config.
_npm_native_auth() {
    local host="$1" path="$2" level f line value esc_level levels=() segs=() n i j lvl

    path="${path%/}"
    if [ -n "$path" ]; then
        IFS='/' read -ra segs <<< "$path"
    fi
    n=${#segs[@]}
    for ((i = n; i >= 1; i--)); do
        lvl=""
        for ((j = 0; j < i; j++)); do
            lvl="${lvl}${segs[j]}/"
        done
        levels+=("//${host}/${lvl}")
    done
    levels+=("//${host}/")

    for level in "${levels[@]}"; do
        esc_level="${level//./\\.}"
        for f in "$PROJECT_ABS/.npmrc" "$HOME/.npmrc"; do
            [ -f "$f" ] || continue
            line=$(grep -E "^${esc_level}:_(authToken|auth|password)=" "$f" 2>/dev/null | head -1)
            [ -z "$line" ] && continue
            value="${line#*=}"
            if [[ "$value" == \$* ]]; then
                return 2
            fi
            echo "$f"; return 0
        done
    done
    return 1
}

# yarn berry's merged config: `config get npmRegistries --json` stays in its
# redacted default (I2 — never --no-redacted) so a hit only proves a secret is
# set, never reveals it. `yarn npm login` writes to the HOME copy, so the
# fallback below must check $HOME/.yarnrc.yml too, and require a host match —
# `config get` throwing on an unset ${VAR} (C7) or the binary being
# unavailable both fall through to it the same way.
#
# SECURITY: never run a corepack-managed `.yarn/releases/*.cjs` shim here —
# that file is project-supplied content (the thing this skill is upgrading),
# not locally-trusted tooling. detect_env.sh already avoids executing it (it
# parses the version from the filename instead); running it during preflight,
# before the user has approved anything, would let a trojanized shim execute
# merely by asking "is a token already configured". Only a real system
# `yarn`/`pnpm` binary (USES_COREPACK=false) is invoked; the corepack case
# falls straight to the textual fallback below.
_yarn_native_auth() {
    local registry_url="$1" host="$2" json f default_server default_host token
    if [ -n "${PKG_MANAGER_BIN:-}" ] && [ "${USES_COREPACK:-false}" != "true" ]; then
        json=$(cd "$PROJECT_ABS" && $PKG_MANAGER_BIN config get npmRegistries --json 2>/dev/null) || json=""
        if [ -n "$json" ] && have_jq; then
            if echo "$json" | jq -e --arg u "$registry_url" --arg h "$host" \
                'to_entries[] | select((.key == $u) or ((.key | capture("^https?://(?<h>[^/]+)")? .h // "") == $h)) | select(.value.npmAuthToken // "" | length > 0)' \
                >/dev/null 2>&1; then
                echo "(yarn config get npmRegistries)"; return 0
            fi
        fi
        # Top-level npmAuthToken applies to yarn's default registry only —
        # an exact host match, not a substring (a different registry's host
        # must never satisfy this one just because one contains the other).
        default_server=$(cd "$PROJECT_ABS" && $PKG_MANAGER_BIN config get npmRegistryServer 2>/dev/null) || default_server=""
        default_host=$(printf '%s' "$default_server" | sed -E 's,^https?://([^/]+).*,\1,')
        if [ -n "$default_server" ] && [ "$default_host" = "$host" ]; then
            token=$(cd "$PROJECT_ABS" && $PKG_MANAGER_BIN config get npmAuthToken --json 2>/dev/null) || token=""
            case "$token" in
                ""|null|'""') ;;
                *) echo "(yarn config get npmAuthToken)"; return 0 ;;
            esac
        fi
    fi
    if command -v python3 >/dev/null 2>&1; then
        for f in "$PROJECT_ABS/.yarnrc.yml" "$HOME/.yarnrc.yml"; do
            [ -f "$f" ] || continue
            if python3 - "$f" "$host" <<'PY' 2>/dev/null
import re, sys
path, host = sys.argv[1], sys.argv[2]
try:
    text = open(path, encoding="utf-8").read()
except Exception:
    sys.exit(1)

def key_host(k):
    # Exact host match: a URL's host component, or the bare string itself
    # when it carries no scheme — never a substring ("nottest.com" must not
    # satisfy host "test.com").
    m = re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://([^/]+)', k)
    return (m.group(1) if m else k.rstrip("/").split("/")[0]).strip('"\'')

m = re.search(r'^npmRegistries:\s*\n((?:[ \t]+.*\n?)+)', text, re.M)
if m:
    entry_pat = re.compile(r'^[ \t]+(?:"([^"]+)"|\'([^\']+)\'|([^"\':\n]+)):\s*\n((?:[ \t]{4,}.*\n?)+)', re.M)
    for em in entry_pat.finditer(m.group(1)):
        key = em.group(1) or em.group(2) or em.group(3)
        if key_host(key) != host:
            continue
        for line in em.group(4).splitlines():
            line = line.strip()
            if line.startswith("npmAuthToken:"):
                val = line.split(":", 1)[1].strip().strip('"').strip("'")
                if val and not val.startswith("$"):
                    sys.exit(0)
# Top-level npmAuthToken applies to the default registry (npmRegistryServer).
server_m = re.search(r'^npmRegistryServer:\s*(.+)$', text, re.M)
token_m = re.search(r'^npmAuthToken:\s*(.+)$', text, re.M)
server_val = server_m.group(1).strip().strip('"').strip("'") if server_m else ""
if server_m and token_m and key_host(server_val) == host:
    val = token_m.group(1).strip().strip('"').strip("'")
    if val and not val.startswith("$"):
        sys.exit(0)
sys.exit(1)
PY
            then
                echo "$f"; return 0
            fi
        done
    fi
    return 1
}

# Tier-1 capability detection: does this registry ALREADY have a real
# (non-${VAR}-placeholder) credential configured natively? If so, the package
# manager can authenticate without us collecting a token at all. Offline only —
# we read config files (or ask the package manager for its own merged view of
# them), never hit the network. Echoes the source on a hit.
registry_native_auth_source() {
    local registry_url="$1" host path hostpath rc src
    [ -z "$registry_url" ] && return 1
    hostpath="${registry_url#http://}"
    hostpath="${hostpath#https://}"
    hostpath="${hostpath%%\?*}"
    hostpath="${hostpath%%#*}"
    [ "${hostpath: -1}" = "/" ] || hostpath="${hostpath}/"
    host="${hostpath%%/*}"
    path="${hostpath#*/}"
    { [ -z "$host" ] || [ "$host" = "unknown" ]; } && return 1

    src=$(_npm_native_auth "$host" "$path"); rc=$?
    if [ "$rc" -eq 0 ]; then echo "$src"; return 0; fi
    # rc == 2 means npm's own resolution decided "not native" (a ${VAR}
    # placeholder). That is not the final answer for this registry — yarn
    # berry (the package manager actually in use) may still have a working
    # credential of its own, so it always gets a chance before giving up.

    src=$(_yarn_native_auth "$registry_url" "$host"); rc=$?
    if [ "$rc" -eq 0 ]; then echo "$src"; return 0; fi
    return 1
}

# Check 1: pkg_manager binary available
if [ -z "$PKG_MANAGER" ] || [ "$PKG_MANAGER" = "unknown" ]; then
    add_blocker "pkg_manager_unknown" \
        "Cannot determine JavaScript package manager" \
        "Ensure project has a recognised lockfile (package-lock.json / yarn.lock / pnpm-lock.yaml / bun.lock) or packageManager field in package.json"
elif [ -z "$PKG_MANAGER_BIN" ]; then
    if [ "$USES_COREPACK" = "true" ]; then
        add_blocker "pkg_manager_bin_missing" \
            "Detected $PKG_MANAGER but binary not in PATH and no .yarn/releases shim found" \
            "Enable corepack (corepack enable) or install $PKG_MANAGER directly. For yarn 3 check that .yarn/releases/yarn-*.cjs exists."
    else
        add_blocker "pkg_manager_bin_missing" \
            "Detected $PKG_MANAGER but command not in PATH" \
            "Install $PKG_MANAGER: e.g. 'corepack enable' (if yarn/pnpm) or 'npm install -g $PKG_MANAGER'"
    fi
else
    add_ok "pkg_manager_bin" "$PKG_MANAGER binary: $PKG_MANAGER_BIN${PKG_MANAGER_VER:+ (v$PKG_MANAGER_VER)}"
fi

# Check 2: each env var placeholder is set in the environment
if [ -n "$ENV_PLACEHOLDERS" ]; then
    while IFS= read -r var; do
        [ -z "$var" ] && continue
        if [ -n "${!var:-}" ]; then
            add_ok "env_${var}" "Env var \$$var is set"
        else
            registry_url=$(registry_url_for_env_var "$var")
            host=$(printf '%s' "$registry_url" | sed -E 's,^https?://([^/]+).*,\1,')
            native_src=$(registry_native_auth_source "${registry_url:-}" || true)
            if [ -n "$native_src" ]; then
                # Tier-1: PM can already authenticate natively — no token needed.
                add_ok "registry_auth_native" \
                    "Registry $host already authenticated via $native_src — env var \$$var not needed"
            else
                portal=$(token_portal_url "${host:-unknown}")
                scope_summary=""
                if have_jq; then
                    scope_summary=$(echo "$ENV_JSON" | jq -r --arg v "$var" \
                        '(.custom_registries // []) | map(select(.auth_env_var == $v) | .scope) | join(", ")')
                fi
                remediation="Required by config files referencing \${$var}"
                [ -n "$scope_summary" ] && remediation="$remediation (scopes: $scope_summary)"
                # Tier-2 self-auth comes before Tier-3 (pasting a raw token). Log
                # in to the EXACT registry URL — a less specific one (e.g. the
                # bare host) would land the credential at a key npm's own
                # resolution order shadows with a more specific, still-missing one.
                login_url="${registry_url:-<registry-url>}"
                remediation="$remediation. Authenticate yourself (preferred): 'npm login --registry $login_url' (npm/pnpm) or 'yarn npm login' (yarn berry), then re-run preflight. Last resort — paste a token: get it at $portal, then export $var=<value>"
                add_blocker "env_${var}_missing" \
                    "Missing env var: \$$var" \
                    "$remediation"
            fi
        fi
    done <<< "$ENV_PLACEHOLDERS"
fi

# Check 3: gh CLI authenticated to the git remote host
if [ -n "$GIT_REMOTE_HOST" ]; then
    if command -v gh >/dev/null 2>&1; then
        if gh auth status --hostname "$GIT_REMOTE_HOST" >/dev/null 2>&1; then
            add_ok "gh_auth" "gh CLI authenticated to $GIT_REMOTE_HOST"
        else
            # Distinguish GHE (custom host) from public github.com
            if [ "$GIT_REMOTE_HOST" = "github.com" ]; then
                add_warn "gh_auth_missing" \
                    "gh CLI not authenticated to github.com" \
                    "Run: gh auth login --hostname github.com --git-protocol ssh"
            else
                add_warn "gh_auth_ghe_missing" \
                    "gh CLI not authenticated to $GIT_REMOTE_HOST (GitHub Enterprise)" \
                    "Run: gh auth login --hostname $GIT_REMOTE_HOST --git-protocol ssh — or PR creation will fall back to printing the URL for manual open"
            fi
        fi
    else
        add_warn "gh_cli_missing" \
            "gh CLI not installed" \
            "PR creation will fall back to printing URL/body for manual creation. Install: brew install gh"
    fi
else
    add_warn "no_git_remote" \
        "No git remote 'origin' configured" \
        "PR creation will be skipped. Run: git remote add origin <url>"
fi

# Check 4: git working tree clean (so we don't mix user's WIP with the upgrade)
if git -C "$PROJECT_PATH" rev-parse --git-dir >/dev/null 2>&1; then
    if [ -z "$(git -C "$PROJECT_PATH" status --porcelain 2>/dev/null)" ]; then
        add_ok "git_clean" "git working tree clean"
    else
        add_warn "git_dirty" \
            "git working tree has uncommitted changes" \
            "Commit or stash before continuing — the upgrade will create a new branch and might intermix with your WIP"
    fi
fi

# Check 5: node_modules presence (informational — affects whether we can run local tests)
if [ "$HAS_NODE_MODULES" = "true" ]; then
    add_ok "node_modules" "node_modules/ present (local tests can run)"
else
    add_warn "no_node_modules" \
        "node_modules/ does not exist" \
        "Local tests/install cannot run; CI will validate on push. Run '$PKG_MANAGER_BIN install' if you want local validation"
fi

# Check 6: node available (basic sanity)
if command -v node >/dev/null 2>&1; then
    NODE_VER=$(node --version 2>/dev/null)
    add_ok "node_runtime" "node available ($NODE_VER)"
else
    add_blocker "node_missing" \
        "node not found in PATH" \
        "Install Node.js: brew install node (macOS) or use nvm"
fi

OK_JSON=$(printf '%s\n' "${OK[@]+"${OK[@]}"}" | jq -s '.' 2>/dev/null || echo '[]')
WARN_JSON=$(printf '%s\n' "${WARNINGS[@]+"${WARNINGS[@]}"}" | jq -s '.' 2>/dev/null || echo '[]')
BLOCKER_JSON=$(printf '%s\n' "${BLOCKERS[@]+"${BLOCKERS[@]}"}" | jq -s '.' 2>/dev/null || echo '[]')

if [ "$JSON_MODE" = "true" ]; then
    jq -n \
        --argjson ok       "$OK_JSON" \
        --argjson warnings "$WARN_JSON" \
        --argjson blockers "$BLOCKER_JSON" \
        --argjson env      "$ENV_JSON" \
        '{ok:$ok, warnings:$warnings, blockers:$blockers,
          summary:{ok_count:($ok|length), warn_count:($warnings|length), blocker_count:($blockers|length)},
          env:$env}'
else
    echo "Pre-flight Checks"
    echo "================="
    have_jq && echo "$OK_JSON"      | jq -r '.[] | "[OK ] \(.title)"'
    have_jq && echo "$WARN_JSON"    | jq -r '.[] | "[WARN] \(.title)\n     -> \(.remediation)"'
    have_jq && echo "$BLOCKER_JSON" | jq -r '.[] | "[FAIL] \(.title)\n     -> \(.remediation)"'
    echo ""
    BC=$(echo "$BLOCKER_JSON" | jq 'length')
    WC=$(echo "$WARN_JSON"    | jq 'length')
    OC=$(echo "$OK_JSON"      | jq 'length')
    echo "Summary: $OC OK, $WC warnings, $BC blockers"
fi

# Exit code: 0 if no blockers (warnings are non-fatal); 1 if any blocker
[ "$(echo "$BLOCKER_JSON" | jq 'length')" -eq 0 ] || exit 1
