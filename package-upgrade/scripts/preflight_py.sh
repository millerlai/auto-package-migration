#!/usr/bin/env bash
# preflight_py.sh - Run all environment checks BEFORE entering Phase 1 (Python path).
#
# Usage: bash preflight_py.sh <project_path> [--json]
#
# Mirrors preflight.sh (JS) / preflight_go.sh (Go) shape so the LLM can treat
# the three the same way (same blockers/warnings/ok schema). Auto-sources
# persisted token files for private indexes:
#   .env.pip / .env.poetry / .env.uv / .env.pypi / .env.jfrog
#
# Output (JSON shape — aligned with preflight.sh / preflight_go.sh):
# {
#   "blockers": [{"id": "...", "title": "...", "remediation": "..."}],
#   "warnings": [...],
#   "ok":       [...],
#   "summary":  {"ok_count": N, "warn_count": N, "blocker_count": N},
#   "env":      <full detect_env.sh output>
# }

set -euo pipefail

PROJECT_PATH="${1:-.}"
JSON_MODE="false"
if [ "${2:-}" = "--json" ]; then JSON_MODE="true"; fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DETECT="$SCRIPT_DIR/detect_env.sh"

if [ ! -f "$DETECT" ]; then
    echo "ERROR: detect_env.sh not found at $DETECT" >&2
    exit 1
fi

# Auto-load persisted token files BEFORE checking env vars. Convention matches
# preflight.sh / preflight_go.sh — each .env.<service> is sourced if present.
# Files should be chmod 600 + gitignored (save_token.sh enforces this).
PROJECT_ABS=$(cd "$PROJECT_PATH" && pwd -P)
for tok_file in "$PROJECT_ABS"/.env.pip \
                "$PROJECT_ABS"/.env.poetry \
                "$PROJECT_ABS"/.env.uv \
                "$PROJECT_ABS"/.env.pypi \
                "$PROJECT_ABS"/.env.jfrog; do
    if [ -f "$tok_file" ]; then
        set -a
        # shellcheck disable=SC1090
        . "$tok_file" 2>/dev/null || true
        set +a
        echo "(preflight) sourced $(basename "$tok_file")" >&2
    fi
done

ENV_JSON=$(bash "$DETECT" "$PROJECT_PATH" 2>/dev/null || echo '{}')

have_jq() { command -v jq >/dev/null 2>&1; }
j() { if have_jq; then echo "$ENV_JSON" | jq -r "$1"; else echo ""; fi; }

PKG_MANAGER=$(j '.pkg_manager // ""')
PYTHON_VERSION=$(j '.python_version // ""')
HAS_PIP_TOOLS=$(j '.has_pip_tools // false')
PIP_LOCK_FILE=$(j '.pip_lock_file // ""')

# Git remote host — detect_env.sh doesn't output it; derive inline (mirrors
# the JS/Go preflight contract without changing detect_env.sh's schema).
GIT_REMOTE_URL=""
GIT_REMOTE_HOST=""
if git -C "$PROJECT_PATH" rev-parse --git-dir >/dev/null 2>&1; then
    GIT_REMOTE_URL=$(git -C "$PROJECT_PATH" remote get-url origin 2>/dev/null || true)
    case "$GIT_REMOTE_URL" in
        https://*|http://*)
            GIT_REMOTE_HOST=$(echo "$GIT_REMOTE_URL" | sed -E 's,^https?://([^/]+).*,\1,')
            ;;
        git@*)
            GIT_REMOTE_HOST=$(echo "$GIT_REMOTE_URL" | sed -E 's,^git@([^:]+):.*,\1,')
            ;;
        ssh://*)
            GIT_REMOTE_HOST=$(echo "$GIT_REMOTE_URL" | sed -E 's,^ssh://([^@]+@)?([^/:]+).*,\2,')
            ;;
    esac
fi

declare -a BLOCKERS=()
declare -a WARNINGS=()
declare -a OK=()

add_ok()       { OK+=("$(jq -nc --arg id "$1" --arg title "$2" '{id:$id, title:$title}')"); }
add_warn()     { WARNINGS+=("$(jq -nc --arg id "$1" --arg title "$2" --arg remediation "$3" '{id:$id, title:$title, remediation:$remediation}')"); }
add_blocker()  { BLOCKERS+=("$(jq -nc --arg id "$1" --arg title "$2" --arg remediation "$3" '{id:$id, title:$title, remediation:$remediation}')"); }

# Mapping host → token portal URL (same table as preflight.sh; keep in sync
# with references/auth_tokens.md).
token_portal_url() {
    local host="$1"
    case "$host" in
        pypi.org|*.pypi.org)
            echo "https://pypi.org/manage/account/token/" ;;
        *.jfrog.trendmicro.com|jfrog.trendmicro.com)
            echo "https://jfrog.trendmicro.com/ui/admin/artifactory/user_profile" ;;
        *.pkgs.visualstudio.com)
            echo "https://dev.azure.com/<org>/_usersSettings/tokens" ;;
        *.github.trendmicro.com)
            echo "https://${host}/settings/tokens" ;;
        *.github.com|github.com)
            echo "https://github.com/settings/tokens" ;;
        *)
            echo "(see auth_tokens.md or ask the index maintainer)" ;;
    esac
}

# Check 1: python3 binary available
if ! command -v python3 >/dev/null 2>&1; then
    add_blocker "python_missing" \
        "python3 not found in PATH" \
        "Install Python 3: brew install python (macOS), apt-get install python3 (Debian), or use pyenv"
elif [ -z "$PYTHON_VERSION" ] || [ "$PYTHON_VERSION" = "unknown" ]; then
    add_warn "python_version_unknown" \
        "python3 found but version could not be parsed" \
        "Run: python3 --version — make sure it returns 'Python X.Y.Z' format"
else
    add_ok "python_runtime" "python3 available (v$PYTHON_VERSION)"
fi

# Check 2: package manager binary available
case "$PKG_MANAGER" in
    pip)
        if command -v pip >/dev/null 2>&1 || command -v pip3 >/dev/null 2>&1; then
            add_ok "pkg_manager_bin" "pip available"
        else
            add_blocker "pkg_manager_bin_missing" \
                "Detected pip project but neither 'pip' nor 'pip3' in PATH" \
                "Reinstall Python with pip bundled, or run: python3 -m ensurepip --upgrade"
        fi
        ;;
    poetry)
        if command -v poetry >/dev/null 2>&1; then
            POETRY_VER=$(poetry --version 2>/dev/null | head -1)
            add_ok "pkg_manager_bin" "poetry available ($POETRY_VER)"
        else
            add_blocker "pkg_manager_bin_missing" \
                "Detected poetry project but 'poetry' not in PATH" \
                "Install poetry: curl -sSL https://install.python-poetry.org | python3 - — or use pipx install poetry"
        fi
        ;;
    uv)
        if command -v uv >/dev/null 2>&1; then
            UV_VER=$(uv --version 2>/dev/null | head -1)
            add_ok "pkg_manager_bin" "uv available ($UV_VER)"
        else
            add_blocker "pkg_manager_bin_missing" \
                "Detected uv project but 'uv' not in PATH" \
                "Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh — or brew install uv"
        fi
        ;;
    unknown)
        add_blocker "pkg_manager_unknown" \
            "Cannot determine Python package manager" \
            "Ensure project has pyproject.toml / requirements.txt / setup.py / setup.cfg in root"
        ;;
esac

# Check 3: pip-tools availability when requirements.in detected
if [ "$HAS_PIP_TOOLS" = "true" ]; then
    if command -v pip-compile >/dev/null 2>&1; then
        add_ok "pip_tools" "pip-tools (pip-compile) available — requirements.in workflow supported"
    else
        add_warn "pip_tools_missing" \
            "requirements.in detected but pip-tools not installed" \
            "Install: pip install pip-tools — Phase 5 lock-only / direct upgrades need pip-compile"
    fi
fi

# Check 4: virtualenv hint — warn (not block) if running outside any venv.
# pip/poetry/uv can technically run against system Python but the upgrade
# will then pollute the user's system site-packages.
if [ -n "${VIRTUAL_ENV:-}" ]; then
    add_ok "virtualenv" "Virtualenv active: $(basename "$VIRTUAL_ENV")"
elif [ -n "${CONDA_PREFIX:-}" ]; then
    add_ok "virtualenv" "Conda env active: $(basename "$CONDA_PREFIX")"
elif [ -d "$PROJECT_ABS/.venv" ] || [ -d "$PROJECT_ABS/venv" ]; then
    venv_dir=".venv"; [ -d "$PROJECT_ABS/venv" ] && venv_dir="venv"
    add_warn "venv_not_activated" \
        "Project has $venv_dir/ but no VIRTUAL_ENV set in current shell" \
        "Activate it: source $venv_dir/bin/activate (or use 'uv run' / 'poetry run' to wrap commands)"
else
    add_warn "no_virtualenv" \
        "No virtualenv detected and no .venv/ in project" \
        "Upgrades will touch system site-packages. Recommended: python3 -m venv .venv && source .venv/bin/activate"
fi

# Check 5: scan dependency declaration files for ${ENV_VAR} placeholders
# (typically used for private index auth: tool.uv.index, tool.poetry.source,
# pip.conf index-url). Symmetric to preflight.sh env_var_placeholders check.
declare -a SCAN_FILES=()
[ -f "$PROJECT_ABS/pyproject.toml" ] && SCAN_FILES+=("$PROJECT_ABS/pyproject.toml")
[ -f "$PROJECT_ABS/pip.conf" ]       && SCAN_FILES+=("$PROJECT_ABS/pip.conf")
[ -f "$PROJECT_ABS/.pip/pip.conf" ]  && SCAN_FILES+=("$PROJECT_ABS/.pip/pip.conf")
[ -f "$PROJECT_ABS/poetry.toml" ]    && SCAN_FILES+=("$PROJECT_ABS/poetry.toml")

declare -a PLACEHOLDERS=()
if [ ${#SCAN_FILES[@]} -gt 0 ]; then
    # Match ${VAR} or ${VAR:-default} forms; dedupe.
    raw=$(grep -hoE '\$\{[A-Z_][A-Z0-9_]*' "${SCAN_FILES[@]}" 2>/dev/null | \
          sed -E 's/^\$\{//' | sort -u || true)
    if [ -n "$raw" ]; then
        while IFS= read -r var; do
            [ -z "$var" ] && continue
            PLACEHOLDERS+=("$var")
        done <<< "$raw"
    fi
fi

if [ ${#PLACEHOLDERS[@]} -gt 0 ]; then
    for var in "${PLACEHOLDERS[@]}"; do
        if [ -n "${!var:-}" ]; then
            add_ok "env_${var}" "Env var \$$var is set"
        else
            portal=$(token_portal_url "unknown")
            add_blocker "env_${var}_missing" \
                "Missing env var: \$$var (referenced in dependency config)" \
                "Referenced by one of: ${SCAN_FILES[*]}. Get token: $portal. Then: export $var=<value>"
        fi
    done
fi

# Check 6: gh CLI authenticated to the git remote host
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

# Check 7: git working tree clean
if git -C "$PROJECT_PATH" rev-parse --git-dir >/dev/null 2>&1; then
    if [ -z "$(git -C "$PROJECT_PATH" status --porcelain 2>/dev/null)" ]; then
        add_ok "git_clean" "git working tree clean"
    else
        add_warn "git_dirty" \
            "git working tree has uncommitted changes" \
            "Commit or stash before continuing — the upgrade will create a new branch and might intermix with your WIP"
    fi
fi

# Check 8: lock file reminder (informational)
if [ -n "$PIP_LOCK_FILE" ]; then
    add_ok "lock_file" "Pip lock file detected: $PIP_LOCK_FILE"
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
    echo "Pre-flight Checks (Python)"
    echo "=========================="
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
