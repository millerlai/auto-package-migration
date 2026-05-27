#!/usr/bin/env bash
# preflight_go.sh - Run all environment checks BEFORE entering Phase 1 (Go path).
#
# Usage: bash preflight_go.sh <project_path> [--json]
#
# Mirrors preflight.sh but tailored for Go modules. Auto-sources persisted
# token files (.env.go, .env.jfrog — corporate Go proxies often reuse JFrog).
#
# Output (JSON shape — aligned with preflight.sh):
# {
#   "blockers": [{"id": "...", "title": "...", "remediation": "..."}],
#   "warnings": [...],
#   "ok":       [...],
#   "summary":  {"ok_count": N, "warn_count": N, "blocker_count": N},
#   "env":      <full detect_env_go.sh output>
# }

set -euo pipefail

PROJECT_PATH="${1:-.}"
JSON_MODE="false"
if [ "${2:-}" = "--json" ]; then JSON_MODE="true"; fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DETECT="$SCRIPT_DIR/detect_env.sh"

if [ ! -x "$DETECT" ]; then
    echo "ERROR: detect_env_go.sh not found at $DETECT" >&2
    exit 1
fi

# Auto-load persisted token files. Same convention as preflight.sh.
PROJECT_ABS=$(cd "$PROJECT_PATH" && pwd -P)
for tok_file in "$PROJECT_ABS"/.env.go "$PROJECT_ABS"/.env.jfrog "$PROJECT_ABS"/.env.github; do
    if [ -f "$tok_file" ]; then
        set -a
        . "$tok_file" 2>/dev/null || true
        set +a
        echo "(preflight) sourced $(basename "$tok_file")" >&2
    fi
done

ENV_JSON=$(bash "$DETECT" "$PROJECT_PATH" 2>/dev/null || echo '{}')

have_jq() { command -v jq >/dev/null 2>&1; }
j() { if have_jq; then echo "$ENV_JSON" | jq -r "$1"; else echo ""; fi; }

PKG_MANAGER=$(j '.pkg_manager // ""')
GO_VERSION=$(j '.go_version // ""')
GO_DIRECTIVE=$(j '.go_directive // ""')
MODULE_PATH=$(j '.module_path // ""')
IS_VENDORED=$(j '.is_vendored // false')
HAS_WORKSPACE=$(j '.has_workspace // false')
HAS_REPLACE=$(j '.has_replace_directives // false')
GOPROXY=$(j '.go_env.GOPROXY // ""')
GOPRIVATE=$(j '.go_env.GOPRIVATE // ""')
GOVULNCHECK=$(j '.govulncheck_available // false')
APIDIFF=$(j '.apidiff_available // false')
GOMAJOR=$(j '.gomajor_available // false')
NETRC=$(j '.netrc_present // false')
GIT_REMOTE_HOST=$(j '.git_remote_host // ""')

declare -a BLOCKERS=()
declare -a WARNINGS=()
declare -a OK=()

add_ok()       { OK+=("$(jq -nc --arg id "$1" --arg title "$2" '{id:$id, title:$title}')"); }
add_warn()     { WARNINGS+=("$(jq -nc --arg id "$1" --arg title "$2" --arg remediation "$3" '{id:$id, title:$title, remediation:$remediation}')"); }
add_blocker()  { BLOCKERS+=("$(jq -nc --arg id "$1" --arg title "$2" --arg remediation "$3" '{id:$id, title:$title, remediation:$remediation}')"); }

# Check 1: go binary available
if [ -z "$GO_VERSION" ] || [ "$GO_VERSION" = "unknown" ]; then
    add_blocker "go_missing" \
        "go not found in PATH" \
        "Install Go: brew install go (macOS), or download from https://go.dev/dl/"
else
    add_ok "go_runtime" "go available (v$GO_VERSION)"
fi

# Check 2: package manager is gomod (we only support gomod; legacy = blocker)
case "$PKG_MANAGER" in
    gomod)
        add_ok "pkg_manager" "Go modules detected (module: ${MODULE_PATH:-unknown})"
        ;;
    dep|glide|govendor)
        add_blocker "legacy_tool" \
            "Legacy dependency tool detected: $PKG_MANAGER" \
            "This skill only supports Go modules. Migrate first: rm -rf vendor/ Gopkg.* glide.* && go mod init $MODULE_PATH && go mod tidy"
        ;;
    gopath)
        add_blocker "gopath_mode" \
            "Project has .go files but no go.mod (GOPATH-style)" \
            "Initialize modules: go mod init <module-path> && go mod tidy"
        ;;
    unknown)
        add_blocker "no_go_project" \
            "No Go project markers found (go.mod / *.go)" \
            "Check that you're in the correct directory"
        ;;
esac

# Check 3: Go directive vs runtime version — runtime must >= directive
if [ -n "$GO_DIRECTIVE" ] && [ -n "$GO_VERSION" ] && [ "$GO_VERSION" != "unknown" ]; then
    # Strip patch from runtime for comparison (e.g. 1.21.5 → 1.21)
    runtime_minor=$(echo "$GO_VERSION" | awk -F. '{print $1"."$2}')
    directive_minor=$(echo "$GO_DIRECTIVE" | awk -F. '{print $1"."$2}')
    if command -v python3 >/dev/null 2>&1; then
        cmp=$(python3 -c "
from packaging.version import Version
try:
    print(1 if Version('$runtime_minor') >= Version('$directive_minor') else 0)
except Exception:
    print('?')
" 2>/dev/null || echo "?")
    else
        # Fallback string compare for simple X.Y vs X.Y
        cmp="?"
        if [ "$runtime_minor" = "$directive_minor" ]; then cmp=1; fi
    fi
    if [ "$cmp" = "1" ]; then
        add_ok "go_directive" "Runtime Go $GO_VERSION satisfies go.mod directive ($GO_DIRECTIVE)"
    elif [ "$cmp" = "0" ]; then
        add_blocker "go_version_low" \
            "Runtime Go $GO_VERSION is older than go.mod directive ($GO_DIRECTIVE)" \
            "Install matching Go version: brew install go@$directive_minor or use a version manager (gvm/asdf)"
    fi
fi

# Check 4: govulncheck (optional but strongly recommended for Go CVE scanning)
if [ "$GOVULNCHECK" = "true" ]; then
    add_ok "govulncheck" "govulncheck available (recommended for reachability analysis)"
else
    add_warn "govulncheck_missing" \
        "govulncheck not installed (recommended for Go CVE workflow)" \
        "Install: go install golang.org/x/vuln/cmd/govulncheck@latest — falls back to dep-tree-only CVE matching otherwise"
fi

# Check 5: apidiff (optional but used for Phase 3 API surface diff)
if [ "$APIDIFF" = "true" ]; then
    add_ok "apidiff" "apidiff available (Phase 3 API surface diff enabled)"
else
    add_warn "apidiff_missing" \
        "apidiff not installed" \
        "Install: go install golang.org/x/exp/cmd/apidiff@latest — Phase 3 will fall back to Git diff + changelog only"
fi

# Check 6: gomajor (optional, only needed for major version upgrades)
if [ "$GOMAJOR" = "true" ]; then
    add_ok "gomajor" "gomajor available (automates v2+ path rewrites)"
else
    add_warn "gomajor_missing" \
        "gomajor not installed (only needed for major version upgrades)" \
        "Install when needed: go install github.com/icholy/gomajor@latest"
fi

# Check 7: GOPROXY sanity
if [ -n "$GOPROXY" ] && [ "$GOPROXY" != "off" ]; then
    add_ok "goproxy" "GOPROXY set: $GOPROXY"
else
    add_warn "goproxy_off" \
        "GOPROXY is empty or 'off'" \
        "module downloads may fail. Default: export GOPROXY=https://proxy.golang.org,direct (or your corporate proxy)"
fi

# Check 8: Private modules — `.netrc` is only required when fetching over HTTPS.
# SSH remote (git@host:...) authenticates via ssh-agent / ~/.ssh and does not
# touch netrc, so a missing netrc is fine. IMPROVEMENT.md §2.3.
if [ -n "$GOPRIVATE" ]; then
    REMOTE_URL=$(git -C "$PROJECT_PATH" remote get-url origin 2>/dev/null || true)
    REMOTE_SCHEME="unknown"
    case "$REMOTE_URL" in
        "") REMOTE_SCHEME="none" ;;
        git@*|ssh://*|git+ssh://*) REMOTE_SCHEME="ssh" ;;
        https://*|http://*) REMOTE_SCHEME="https" ;;
        git://*) REMOTE_SCHEME="git" ;;
        # scp-like syntax: host:path (no scheme). Heuristic: contains ':' and
        # the part before ':' has no '/' (otherwise it's a relative path).
        *:*)
            host_part="${REMOTE_URL%%:*}"
            case "$host_part" in
                */*) REMOTE_SCHEME="unknown" ;;
                *) REMOTE_SCHEME="ssh" ;;  # treat as scp-like SSH
            esac
            ;;
    esac

    if [ "$NETRC" = "true" ]; then
        add_ok "private_auth" "GOPRIVATE set ($GOPRIVATE) and ~/.netrc present"
    elif [ "$REMOTE_SCHEME" = "ssh" ]; then
        add_ok "private_auth_ssh" \
            "GOPRIVATE set ($GOPRIVATE); origin uses SSH ($REMOTE_URL) — netrc not required"
    elif [ "$REMOTE_SCHEME" = "https" ]; then
        add_warn "private_no_netrc" \
            "GOPRIVATE set ($GOPRIVATE), origin uses HTTPS, no ~/.netrc — clones may fail for private modules" \
            "Create ~/.netrc with: machine <host> login <user> password <token>; chmod 600 ~/.netrc — OR switch origin to SSH: git remote set-url origin git@<host>:<path>"
    else
        # No remote / unknown scheme — informational only
        add_warn "private_no_netrc_unknown_remote" \
            "GOPRIVATE set ($GOPRIVATE) but no ~/.netrc and origin scheme is '$REMOTE_SCHEME'" \
            "If you plan to fetch private modules over HTTPS, configure ~/.netrc; SSH remotes don't need it"
    fi
fi

# Check 9: vendor mode reminder
if [ "$IS_VENDORED" = "true" ]; then
    add_warn "vendored_project" \
        "Project uses vendor/ mode — Phase 5 must run 'go mod vendor' after upgrade" \
        "(Informational) The upgrade workflow will automatically re-vendor after dependency changes"
fi

# Check 10: workspace mode reminder
if [ "$HAS_WORKSPACE" = "true" ]; then
    add_warn "workspace_project" \
        "Project uses go.work multi-module workspace — Phase 2 will ask which module to target" \
        "(Informational) The upgrade workflow will prompt for module selection"
fi

# Check 11: replace directives reminder
if [ "$HAS_REPLACE" = "true" ]; then
    add_warn "replace_directives_present" \
        "go.mod contains replace directives — these must be preserved across the upgrade" \
        "(Informational) The skill will not touch existing replace directives without confirmation"
fi

# Check 12: gh CLI authentication
if [ -n "$GIT_REMOTE_HOST" ]; then
    if command -v gh >/dev/null 2>&1; then
        if gh auth status --hostname "$GIT_REMOTE_HOST" >/dev/null 2>&1; then
            add_ok "gh_auth" "gh CLI authenticated to $GIT_REMOTE_HOST"
        else
            if [ "$GIT_REMOTE_HOST" = "github.com" ]; then
                add_warn "gh_auth_missing" \
                    "gh CLI not authenticated to github.com" \
                    "Run: gh auth login --hostname github.com --git-protocol ssh"
            else
                add_warn "gh_auth_ghe_missing" \
                    "gh CLI not authenticated to $GIT_REMOTE_HOST (GitHub Enterprise)" \
                    "Run: gh auth login --hostname $GIT_REMOTE_HOST --git-protocol ssh — or PR creation will fall back to printing the URL"
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

# Check 13: git working tree clean
if git -C "$PROJECT_PATH" rev-parse --git-dir >/dev/null 2>&1; then
    if [ -z "$(git -C "$PROJECT_PATH" status --porcelain 2>/dev/null)" ]; then
        add_ok "git_clean" "git working tree clean"
    else
        add_warn "git_dirty" \
            "git working tree has uncommitted changes" \
            "Commit or stash before continuing — the upgrade will create a new branch and might intermix with your WIP"
    fi
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
    echo "Pre-flight Checks (Go)"
    echo "======================"
    have_jq && echo "$OK_JSON"      | jq -r '.[] | "[OK ] \(.title)"'
    have_jq && echo "$WARN_JSON"    | jq -r '.[] | "[WARN] \(.title)\n     -> \(.remediation)"'
    have_jq && echo "$BLOCKER_JSON" | jq -r '.[] | "[FAIL] \(.title)\n     -> \(.remediation)"'
    echo ""
    BC=$(echo "$BLOCKER_JSON" | jq 'length')
    WC=$(echo "$WARN_JSON"    | jq 'length')
    OC=$(echo "$OK_JSON"      | jq 'length')
    echo "Summary: $OC OK, $WC warnings, $BC blockers"
fi

[ "$(echo "$BLOCKER_JSON" | jq 'length')" -eq 0 ] || exit 1
