#!/usr/bin/env bash
# validate_lockfile.sh - Validate a lockfile WITHOUT network access.
#
# Usage: bash validate_lockfile.sh <project_path>
#
# Used after Phase 5 — especially if we had to hand-edit yarn.lock /
# package-lock.json because of missing auth tokens. We want to catch
# checksum mismatches locally BEFORE pushing and waiting for CI.
#
# Picks the appropriate command per package manager:
#   yarn  : yarn install --immutable --check-cache --mode update-lockfile
#   npm   : npm ci --offline --dry-run     (npm 9+)
#   pnpm  : pnpm install --frozen-lockfile --offline
#   bun   : bun install --frozen-lockfile  (no offline equivalent)
#
# Output: JSON
#   { "status": "success" | "failure",
#     "pkg_manager": "yarn",
#     "command": "<full command run>",
#     "exit_code": 0,
#     "stdout_tail": "...", "stderr_tail": "..." }

set -euo pipefail

PROJECT_PATH="${1:-.}"
PROJECT_PATH=$(cd "$PROJECT_PATH" && pwd -P)
cd "$PROJECT_PATH" || exit 1

if [ ! -f "package.json" ]; then
    printf '{"status":"failure","message":"package.json not found"}\n'
    exit 1
fi

# Detect package manager (priority: bun > pnpm > yarn > npm)
PM="npm"
if   [ -f "bun.lock" ] || [ -f "bun.lockb" ]; then PM="bun"
elif [ -f "pnpm-lock.yaml" ]; then PM="pnpm"
elif [ -f "yarn.lock" ]; then PM="yarn"
fi

# Build the appropriate command + binary
CMD=""
if [ "$PM" = "yarn" ]; then
    # Prefer corepack-managed yarn release (yarn 3 Berry)
    if [ -d ".yarn/releases" ]; then
        YARN_BIN=$(ls .yarn/releases/yarn-*.cjs 2>/dev/null | sort -V | tail -1 || echo "")
        if [ -n "$YARN_BIN" ]; then
            CMD="node $YARN_BIN install --immutable --check-cache --mode update-lockfile"
        fi
    fi
    if [ -z "$CMD" ] && command -v yarn >/dev/null 2>&1; then
        # Decide between yarn 1 and yarn berry by lockfile signature
        if head -10 yarn.lock 2>/dev/null | grep -q '__metadata:'; then
            CMD="yarn install --immutable --check-cache --mode update-lockfile"
        else
            # yarn 1: closest equivalent is `yarn install --frozen-lockfile --check-files`
            CMD="yarn install --frozen-lockfile --check-files"
        fi
    fi
elif [ "$PM" = "npm" ]; then
    if command -v npm >/dev/null 2>&1; then
        CMD="npm ci --offline --dry-run"
    fi
elif [ "$PM" = "pnpm" ]; then
    if command -v pnpm >/dev/null 2>&1; then
        CMD="pnpm install --frozen-lockfile --offline"
    fi
elif [ "$PM" = "bun" ]; then
    if command -v bun >/dev/null 2>&1; then
        CMD="bun install --frozen-lockfile"
    fi
fi

if [ -z "$CMD" ]; then
    printf '{"status":"failure","pkg_manager":"%s","message":"package manager binary not found"}\n' "$PM"
    exit 1
fi

echo "Running offline validation: $CMD" >&2

STDOUT_FILE=$(mktemp)
STDERR_FILE=$(mktemp)
trap 'rm -f "$STDOUT_FILE" "$STDERR_FILE"' EXIT

EXIT_CODE=0
$CMD > "$STDOUT_FILE" 2> "$STDERR_FILE" || EXIT_CODE=$?

STATUS="success"
[ "$EXIT_CODE" -ne 0 ] && STATUS="failure"

# Tail the last 80 lines of each for the report (lockfile errors are usually at the bottom)
STDOUT_TAIL=$(tail -80 "$STDOUT_FILE" 2>/dev/null || true)
STDERR_TAIL=$(tail -80 "$STDERR_FILE" 2>/dev/null || true)

# Emit JSON
if command -v jq >/dev/null 2>&1; then
    jq -nc \
        --arg status "$STATUS" \
        --arg pkg_manager "$PM" \
        --arg cmd "$CMD" \
        --argjson exit_code "$EXIT_CODE" \
        --arg stdout "$STDOUT_TAIL" \
        --arg stderr "$STDERR_TAIL" \
        '{status:$status, pkg_manager:$pkg_manager, command:$cmd,
          exit_code:$exit_code, stdout_tail:$stdout, stderr_tail:$stderr}'
else
    printf '{"status":"%s","pkg_manager":"%s","command":%s,"exit_code":%d}\n' \
        "$STATUS" "$PM" "\"$CMD\"" "$EXIT_CODE"
fi

exit "$EXIT_CODE"
