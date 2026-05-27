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
# own later) is sourced if present. Files are owned by the user only
# (chmod 600 enforced by save_token.sh) and gitignored.
PROJECT_ABS=$(cd "$PROJECT_PATH" && pwd -P)
for tok_file in "$PROJECT_ABS"/.env.jfrog "$PROJECT_ABS"/.env.npm "$PROJECT_ABS"/.env.github; do
    if [ -f "$tok_file" ]; then
        # set -a auto-exports every KEY=VALUE in the file; subshell-scoped
        # so we don't leak unrelated variables into the parent shell.
        # shellcheck disable=SC1090
        set -a
        . "$tok_file" 2>/dev/null || true
        set +a
        echo "(preflight) sourced $(basename "$tok_file")" >&2
    fi
done

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

# Find the registry/host that references a given env var
host_for_env_var() {
    local var="$1"
    if have_jq; then
        echo "$ENV_JSON" | jq -r --arg v "$var" \
            '(.custom_registries // []) | map(select(.auth_env_var == $v)) | .[0].registry // ""' \
            | sed -E 's,^https?://([^/]+).*,\1,'
    fi
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
            host=$(host_for_env_var "$var")
            portal=$(token_portal_url "${host:-unknown}")
            scope_summary=""
            if have_jq; then
                scope_summary=$(echo "$ENV_JSON" | jq -r --arg v "$var" \
                    '(.custom_registries // []) | map(select(.auth_env_var == $v) | .scope) | join(", ")')
            fi
            remediation="Required by config files referencing \${$var}"
            [ -n "$scope_summary" ] && remediation="$remediation (scopes: $scope_summary)"
            remediation="$remediation. Get token: $portal. Then: export $var=<value>"
            add_blocker "env_${var}_missing" \
                "Missing env var: \$$var" \
                "$remediation"
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
