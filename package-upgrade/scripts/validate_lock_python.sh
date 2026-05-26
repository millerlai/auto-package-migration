#!/usr/bin/env bash
# validate_lock_python.sh - Post-edit validation of Python dependency files.
#
# Usage: bash validate_lock_python.sh <project_path> [--upgrade-strategy <name>]
#
# Equivalent of validate_lockfile.sh (JS) / validate_modfile_go.sh (Go) but for
# Python. Runs the lightest set of checks that catch missed steps from Phase 5
# locally before committing. Detects pkg_manager by lockfile presence
# (uv > poetry > pip-tools > raw pip) — same priority as detect_env.sh.
#
# Per pkg_manager check matrix:
#   uv         : uv lock --check        (verifies uv.lock matches pyproject.toml)
#   poetry     : poetry check --lock    (poetry 1.7+) or poetry lock --check
#                                       (1.4–1.6 fallback)
#   pip-tools  : pip-compile -q --dry-run -o - requirements.in
#                |  diff against current requirements.txt
#   pip (raw)  : pip install --dry-run -r requirements.txt (pip 23+)
#                or `pip check` (always available, catches conflicts)
#
# When `--upgrade-strategy lock_only` is passed, also asserts that the
# dependency *manifest* (pyproject.toml / requirements.in / requirements.txt
# in non-pip-tools mode) is UNCHANGED in the working tree — lock-only paths
# must not touch the manifest (IMPORTANT_DEPENDENCY_UPDATE.md).
#
# Output JSON:
# {
#   "status": "success" | "failure",
#   "pkg_manager": "uv" | "poetry" | "pip-tools" | "pip" | "unknown",
#   "checks": {
#     "lock_consistent":    {"name": "...", "exit_code": N, "stdout_tail": "...", "stderr_tail": "..."},
#     "manifest_unchanged": {...}   # only present when --upgrade-strategy lock_only
#   },
#   "errors": [...]
# }

set -uo pipefail

PROJECT_PATH="${1:-.}"
UPGRADE_STRATEGY=""

# Parse remaining args (only --upgrade-strategy supported today; keep the loop
# so adding flags later doesn't require touching positional parsing).
shift || true
while [ $# -gt 0 ]; do
    case "$1" in
        --upgrade-strategy)
            UPGRADE_STRATEGY="${2:-}"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

PROJECT_PATH=$(cd "$PROJECT_PATH" && pwd -P)
cd "$PROJECT_PATH" || exit 1

# Detect package manager (priority: uv > poetry > pip-tools > pip)
PM="unknown"
if [ -f "uv.lock" ]; then
    PM="uv"
elif [ -f "poetry.lock" ]; then
    PM="poetry"
elif [ -f "requirements.in" ]; then
    PM="pip-tools"
elif [ -f "requirements.txt" ] || [ -f "pyproject.toml" ] || [ -f "setup.py" ]; then
    PM="pip"
fi

if [ "$PM" = "unknown" ]; then
    printf '{"status":"failure","pkg_manager":"unknown","errors":["No Python project markers found"]}\n'
    exit 1
fi

run_check() {
    # Usage: run_check <name> <command...>
    # Echoes a single-line JSON object describing the check result.
    local name="$1"; shift
    local stdout_file stderr_file rc=0
    stdout_file=$(mktemp); stderr_file=$(mktemp)
    "$@" > "$stdout_file" 2> "$stderr_file" || rc=$?
    local stdout_tail stderr_tail
    stdout_tail=$(tail -50 "$stdout_file" 2>/dev/null || true)
    stderr_tail=$(tail -50 "$stderr_file" 2>/dev/null || true)
    rm -f "$stdout_file" "$stderr_file"

    jq -nc \
        --arg name "$name" \
        --argjson exit_code "$rc" \
        --arg stdout_tail "$stdout_tail" \
        --arg stderr_tail "$stderr_tail" \
        '{name:$name, exit_code:$exit_code, stdout_tail:$stdout_tail, stderr_tail:$stderr_tail}'
}

# --------------------------------------------------------------------------- #
# Lock consistency check per pkg_manager
# --------------------------------------------------------------------------- #

LOCK_CHECK="{}"
case "$PM" in
    uv)
        if command -v uv >/dev/null 2>&1; then
            # `uv lock --check` (formerly --locked) fails non-zero when the lock
            # file would need to change. Both forms are accepted by current uv.
            LOCK_CHECK=$(run_check "uv_lock_check" uv lock --check)
        else
            LOCK_CHECK=$(jq -nc '{name:"uv_lock_check", exit_code:127,
                stdout_tail:"", stderr_tail:"uv not in PATH"}')
        fi
        ;;
    poetry)
        if command -v poetry >/dev/null 2>&1; then
            # poetry 1.7+ : `poetry check --lock`
            # poetry 1.4-1.6: `poetry lock --check` (deprecated alias)
            # Probe by version; pick whichever works.
            POETRY_VER=$(poetry --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1 || echo "0.0")
            POETRY_MAJOR=$(echo "$POETRY_VER" | cut -d. -f1)
            POETRY_MINOR=$(echo "$POETRY_VER" | cut -d. -f2)
            if [ "${POETRY_MAJOR:-0}" -gt 1 ] || \
               { [ "${POETRY_MAJOR:-0}" -eq 1 ] && [ "${POETRY_MINOR:-0}" -ge 7 ]; }; then
                LOCK_CHECK=$(run_check "poetry_check_lock" poetry check --lock)
            else
                LOCK_CHECK=$(run_check "poetry_lock_check" poetry lock --check)
            fi
        else
            LOCK_CHECK=$(jq -nc '{name:"poetry_check_lock", exit_code:127,
                stdout_tail:"", stderr_tail:"poetry not in PATH"}')
        fi
        ;;
    pip-tools)
        # pip-compile -q --dry-run prints the resolved output to stdout without
        # touching disk. We diff against the current requirements.txt to detect
        # drift. If the diff is empty, the lock is consistent with the .in.
        if command -v pip-compile >/dev/null 2>&1; then
            stdout_file=$(mktemp); stderr_file=$(mktemp); rc=0
            # Use a temp output file so the run is fully non-mutating (pip-compile
            # historically still wrote the header to disk even with --dry-run).
            tmp_out=$(mktemp)
            pip-compile --quiet --dry-run --output-file "$tmp_out" requirements.in \
                > "$stdout_file" 2> "$stderr_file" || rc=$?
            diff_out=""
            if [ "$rc" -eq 0 ] && [ -f "requirements.txt" ]; then
                # Strip comment lines (pip-compile timestamps differ between runs)
                if ! diff <(grep -v '^#' requirements.txt) <(grep -v '^#' "$tmp_out") \
                        > /dev/null 2>&1; then
                    rc=2
                    diff_out=$(diff <(grep -v '^#' requirements.txt) <(grep -v '^#' "$tmp_out") \
                              2>/dev/null | head -50)
                fi
            fi
            tail_stdout=$(tail -50 "$stdout_file" 2>/dev/null || true)
            tail_stderr=$(tail -50 "$stderr_file" 2>/dev/null || true)
            if [ -n "$diff_out" ]; then
                tail_stdout="$diff_out"
            fi
            rm -f "$stdout_file" "$stderr_file" "$tmp_out"
            LOCK_CHECK=$(jq -nc \
                --argjson exit_code "$rc" \
                --arg stdout_tail "$tail_stdout" \
                --arg stderr_tail "$tail_stderr" \
                '{name:"pip_compile_dry_run", exit_code:$exit_code,
                  stdout_tail:$stdout_tail, stderr_tail:$stderr_tail}')
        else
            LOCK_CHECK=$(jq -nc '{name:"pip_compile_dry_run", exit_code:127,
                stdout_tail:"", stderr_tail:"pip-compile not in PATH (install pip-tools)"}')
        fi
        ;;
    pip)
        # Raw pip has no real "lock consistency" concept. The closest sanity
        # check is `pip check` (which flags installed-package conflicts) plus
        # `pip install --dry-run` against requirements.txt if pip is recent
        # enough to support --dry-run (pip 23+).
        if command -v pip >/dev/null 2>&1; then
            if [ -f "requirements.txt" ]; then
                # Probe pip's --dry-run support cheaply
                if pip install --dry-run --quiet pip >/dev/null 2>&1; then
                    LOCK_CHECK=$(run_check "pip_install_dry_run" \
                        pip install --dry-run --quiet -r requirements.txt)
                else
                    LOCK_CHECK=$(run_check "pip_check" pip check)
                fi
            else
                LOCK_CHECK=$(run_check "pip_check" pip check)
            fi
        else
            LOCK_CHECK=$(jq -nc '{name:"pip_check", exit_code:127,
                stdout_tail:"", stderr_tail:"pip not in PATH"}')
        fi
        ;;
esac

# --------------------------------------------------------------------------- #
# Manifest-unchanged guard (only when lock-only strategy)
# --------------------------------------------------------------------------- #

MANIFEST_CHECK="null"
if [ "$UPGRADE_STRATEGY" = "lock_only" ]; then
    declare -a MANIFEST_FILES=()
    case "$PM" in
        uv|poetry)
            [ -f pyproject.toml ] && MANIFEST_FILES+=("pyproject.toml") ;;
        pip-tools)
            [ -f requirements.in ] && MANIFEST_FILES+=("requirements.in") ;;
        pip)
            # In raw-pip mode there's no separate "manifest" file — the
            # requirements.txt IS the manifest. Lock-only doesn't strictly
            # apply, but we still check pyproject.toml in case the project
            # uses PEP 621 dependencies.
            [ -f pyproject.toml ] && MANIFEST_FILES+=("pyproject.toml") ;;
    esac

    if [ "${#MANIFEST_FILES[@]}" -eq 0 ]; then
        MANIFEST_CHECK=$(jq -nc \
            '{name:"manifest_unchanged", exit_code:0,
              stdout_tail:"no manifest files to check for this pkg_manager",
              stderr_tail:""}')
    elif ! git -C "$PROJECT_PATH" rev-parse --git-dir >/dev/null 2>&1; then
        MANIFEST_CHECK=$(jq -nc \
            '{name:"manifest_unchanged", exit_code:0,
              stdout_tail:"not a git repo — skipping manifest-unchanged check",
              stderr_tail:""}')
    else
        diff_out=$(git -C "$PROJECT_PATH" diff -- "${MANIFEST_FILES[@]}" 2>/dev/null | head -50)
        rc=0
        if [ -n "$diff_out" ]; then
            rc=2
        fi
        MANIFEST_CHECK=$(jq -nc \
            --argjson exit_code "$rc" \
            --arg stdout_tail "$diff_out" \
            --arg stderr_tail "" \
            '{name:"manifest_unchanged", exit_code:$exit_code,
              stdout_tail:$stdout_tail, stderr_tail:$stderr_tail}')
    fi
fi

# --------------------------------------------------------------------------- #
# Compose final output
# --------------------------------------------------------------------------- #

LOCK_RC=$(echo "$LOCK_CHECK" | jq -r '.exit_code')
MAN_RC=0
if [ "$MANIFEST_CHECK" != "null" ]; then
    MAN_RC=$(echo "$MANIFEST_CHECK" | jq -r '.exit_code')
fi

STATUS="success"
declare -a ERRS=()
case "$PM" in
    uv)
        [ "$LOCK_RC" != "0" ] && STATUS="failure" && \
            ERRS+=("uv lock is out of sync with pyproject.toml (rc=$LOCK_RC) — run 'uv lock'") ;;
    poetry)
        [ "$LOCK_RC" != "0" ] && STATUS="failure" && \
            ERRS+=("poetry.lock is out of sync with pyproject.toml (rc=$LOCK_RC) — run 'poetry lock --no-update'") ;;
    pip-tools)
        [ "$LOCK_RC" = "2" ] && STATUS="failure" && \
            ERRS+=("requirements.txt drifts from requirements.in (rc=2) — run 'pip-compile requirements.in'")
        [ "$LOCK_RC" != "0" ] && [ "$LOCK_RC" != "2" ] && STATUS="failure" && \
            ERRS+=("pip-compile dry-run failed (rc=$LOCK_RC) — see stderr_tail") ;;
    pip)
        [ "$LOCK_RC" != "0" ] && STATUS="failure" && \
            ERRS+=("pip check / dry-run reported conflicts (rc=$LOCK_RC) — see stderr_tail") ;;
esac

if [ "$MAN_RC" = "2" ]; then
    STATUS="failure"
    ERRS+=("upgrade_strategy=lock_only but manifest file was modified -- revert manifest with 'git checkout -- <file>'")
fi

ERRORS_JSON="[]"
if [ "${#ERRS[@]}" -gt 0 ]; then
    ERRORS_JSON=$(printf '%s\n' "${ERRS[@]}" | jq -R -s 'split("\n") | map(select(. != ""))')
fi

# Build the final checks object — manifest_unchanged is only added when present
if [ "$MANIFEST_CHECK" = "null" ]; then
    CHECKS_JSON=$(jq -nc --argjson lock "$LOCK_CHECK" '{lock_consistent:$lock}')
else
    CHECKS_JSON=$(jq -nc --argjson lock "$LOCK_CHECK" --argjson man "$MANIFEST_CHECK" \
        '{lock_consistent:$lock, manifest_unchanged:$man}')
fi

jq -nc \
    --arg status "$STATUS" \
    --arg pm "$PM" \
    --argjson checks "$CHECKS_JSON" \
    --argjson errors "$ERRORS_JSON" \
    '{status:$status, pkg_manager:$pm, checks:$checks, errors:$errors}'

[ "$STATUS" = "success" ] || exit 1
