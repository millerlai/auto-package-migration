#!/usr/bin/env bash
# run_tests_js.sh - Run JS/TS tests and emit structured results.
#
# Usage: bash run_tests_js.sh <project_path> [--files <test_files...>] [--all]
#
# Detection priority:
#   1. package.json#scripts.test (run with the project's chosen package manager)
#   2. Direct invocation of jest / vitest / mocha if installed locally
#
# When --files is supplied we try to use the framework's "only related" mode:
#   jest:    --findRelatedTests
#   vitest:  related
#   mocha:   pass file paths directly

set -euo pipefail

PROJECT_PATH="${1:-.}"
shift || true
cd "$PROJECT_PATH" || exit 1

MODE="all"
TEST_FILES=()
while [[ $# -gt 0 ]]; do
    case $1 in
        --files)
            MODE="files"; shift
            while [[ $# -gt 0 ]] && [[ ! $1 =~ ^-- ]]; do
                TEST_FILES+=("$1")
                shift
            done
            ;;
        --all) MODE="all"; shift ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

if [ ! -f "package.json" ]; then
    echo '{"error": "package.json not found"}'
    exit 1
fi

# Detect package manager (priority: bun > pnpm > yarn > npm)
PM="npm"
if   [ -f "bun.lock" ] || [ -f "bun.lockb" ]; then PM="bun"
elif [ -f "pnpm-lock.yaml" ]; then PM="pnpm"
elif [ -f "yarn.lock" ]; then PM="yarn"
fi

# Detect framework
FRAMEWORK="unknown"
if [ -f "node_modules/.bin/vitest" ]; then FRAMEWORK="vitest"
elif [ -f "node_modules/.bin/jest" ]; then FRAMEWORK="jest"
elif [ -f "node_modules/.bin/mocha" ]; then FRAMEWORK="mocha"
fi
# Fall back to scripts.test pattern
if [ "$FRAMEWORK" = "unknown" ] && command -v jq >/dev/null 2>&1; then
    TEST_SCRIPT=$(jq -r '.scripts.test // ""' package.json 2>/dev/null || echo "")
    case "$TEST_SCRIPT" in
        *vitest*) FRAMEWORK="vitest" ;;
        *jest*) FRAMEWORK="jest" ;;
        *mocha*) FRAMEWORK="mocha" ;;
        *"node --test"*) FRAMEWORK="node-test" ;;
    esac
fi

echo "Detected: pkg_manager=$PM, framework=$FRAMEWORK, mode=$MODE" >&2

OUTPUT_FILE=$(mktemp)
trap 'rm -f "$OUTPUT_FILE"' EXIT
EXIT_CODE=0

run_with_npx_or_local() {
    # Use local binary if present, else npx (no install)
    local bin="$1"; shift
    if [ -x "node_modules/.bin/$bin" ]; then
        "node_modules/.bin/$bin" "$@"
    else
        npx --no-install "$bin" "$@" 2>&1 || npx --yes "$bin" "$@"
    fi
}

case "$FRAMEWORK" in
    jest)
        if [ "$MODE" = "files" ] && [ "${#TEST_FILES[@]}" -gt 0 ]; then
            run_with_npx_or_local jest --findRelatedTests "${TEST_FILES[@]}" --passWithNoTests > "$OUTPUT_FILE" 2>&1 || EXIT_CODE=$?
        else
            run_with_npx_or_local jest > "$OUTPUT_FILE" 2>&1 || EXIT_CODE=$?
        fi
        PASSED=$(grep -oE '[0-9]+ passed' "$OUTPUT_FILE" | head -1 | awk '{print $1}' || echo 0)
        FAILED=$(grep -oE '[0-9]+ failed' "$OUTPUT_FILE" | head -1 | awk '{print $1}' || echo 0)
        ;;
    vitest)
        if [ "$MODE" = "files" ] && [ "${#TEST_FILES[@]}" -gt 0 ]; then
            run_with_npx_or_local vitest related --run "${TEST_FILES[@]}" > "$OUTPUT_FILE" 2>&1 || EXIT_CODE=$?
        else
            run_with_npx_or_local vitest run > "$OUTPUT_FILE" 2>&1 || EXIT_CODE=$?
        fi
        PASSED=$(grep -oE '[0-9]+ passed' "$OUTPUT_FILE" | head -1 | awk '{print $1}' || echo 0)
        FAILED=$(grep -oE '[0-9]+ failed' "$OUTPUT_FILE" | head -1 | awk '{print $1}' || echo 0)
        ;;
    mocha)
        if [ "$MODE" = "files" ] && [ "${#TEST_FILES[@]}" -gt 0 ]; then
            run_with_npx_or_local mocha "${TEST_FILES[@]}" > "$OUTPUT_FILE" 2>&1 || EXIT_CODE=$?
        else
            run_with_npx_or_local mocha > "$OUTPUT_FILE" 2>&1 || EXIT_CODE=$?
        fi
        PASSED=$(grep -oE '[0-9]+ passing' "$OUTPUT_FILE" | head -1 | awk '{print $1}' || echo 0)
        FAILED=$(grep -oE '[0-9]+ failing' "$OUTPUT_FILE" | head -1 | awk '{print $1}' || echo 0)
        ;;
    node-test)
        node --test > "$OUTPUT_FILE" 2>&1 || EXIT_CODE=$?
        PASSED=$(grep -oE 'pass [0-9]+' "$OUTPUT_FILE" | head -1 | awk '{print $2}' || echo 0)
        FAILED=$(grep -oE 'fail [0-9]+' "$OUTPUT_FILE" | head -1 | awk '{print $2}' || echo 0)
        ;;
    unknown)
        # Fall back to whatever scripts.test says, executed via the project's pkg manager
        echo "No framework detected; falling back to '$PM test'" >&2
        case "$PM" in
            npm)  npm test > "$OUTPUT_FILE" 2>&1 || EXIT_CODE=$? ;;
            yarn) yarn test > "$OUTPUT_FILE" 2>&1 || EXIT_CODE=$? ;;
            pnpm) pnpm test > "$OUTPUT_FILE" 2>&1 || EXIT_CODE=$? ;;
            bun)  bun test > "$OUTPUT_FILE" 2>&1 || EXIT_CODE=$? ;;
        esac
        PASSED=0
        FAILED=0
        ;;
esac

PASSED=${PASSED:-0}
FAILED=${FAILED:-0}

TRACEBACK=""
if [ "$EXIT_CODE" -ne 0 ]; then
    TRACEBACK=$(cat "$OUTPUT_FILE")
fi

cat <<EOF
{
  "framework": "$FRAMEWORK",
  "pkg_manager": "$PM",
  "passed": $PASSED,
  "failed": $FAILED,
  "exit_code": $EXIT_CODE,
  "traceback": $(printf '%s' "$TRACEBACK" | jq -Rs . 2>/dev/null || echo '""')
}
EOF
exit $EXIT_CODE
