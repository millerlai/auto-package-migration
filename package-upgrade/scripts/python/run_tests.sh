#!/usr/bin/env bash
# run_tests.sh - Run tests and output structured results
# Usage: bash run_tests.sh <project_path> [--files <test_files>] [--all]
# Output: JSON with test results

set -euo pipefail

PROJECT_PATH="${1:-.}"
shift || true

cd "$PROJECT_PATH" || exit 1

MODE="all"
TEST_FILES=()

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --files)
            MODE="files"
            shift
            while [[ $# -gt 0 ]] && [[ ! $1 =~ ^-- ]]; do
                TEST_FILES+=("$1")
                shift
            done
            ;;
        --all)
            MODE="all"
            shift
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

# Detect test framework
TEST_RUNNER=""
if command -v pytest &> /dev/null; then
    TEST_RUNNER="pytest"
elif python3 -m pytest --version &> /dev/null 2>&1; then
    TEST_RUNNER="python3 -m pytest"
elif python3 -c "import unittest" &> /dev/null 2>&1; then
    TEST_RUNNER="python3 -m unittest"
else
    echo '{"error": "No test framework found (pytest or unittest)"}'
    exit 1
fi

echo "Using test runner: $TEST_RUNNER" >&2

# Run tests
OUTPUT_FILE=$(mktemp)
EXIT_CODE=0

if [[ "$TEST_RUNNER" =~ pytest ]]; then
    # Run pytest
    if [ "$MODE" = "files" ]; then
        $TEST_RUNNER -v "${TEST_FILES[@]}" > "$OUTPUT_FILE" 2>&1 || EXIT_CODE=$?
    else
        $TEST_RUNNER -v > "$OUTPUT_FILE" 2>&1 || EXIT_CODE=$?
    fi

    # Parse pytest's final summary line (e.g. "2 passed in 0.01s" or
    # "1 failed, 1 passed in 0.02s" or "1 error in 0.00s"), not log lines:
    # grepping PASSED/FAILED/ERROR counts log lines, not tests, and ERROR
    # also matches inside tracebacks.
    SUMMARY_LINE=$(grep -E "^=+ .* =+$" "$OUTPUT_FILE" | tail -1 || true)
    PASSED=$(grep -oE "[0-9]+ passed" <<<"$SUMMARY_LINE" | grep -oE "[0-9]+" || true)
    FAILED=$(grep -oE "[0-9]+ failed" <<<"$SUMMARY_LINE" | grep -oE "[0-9]+" || true)
    ERRORS=$(grep -oE "[0-9]+ error(s)?" <<<"$SUMMARY_LINE" | grep -oE "[0-9]+" || true)
    PASSED="${PASSED:-0}"
    FAILED="${FAILED:-0}"
    ERRORS="${ERRORS:-0}"
else
    # Run unittest
    if [ "$MODE" = "files" ]; then
        $TEST_RUNNER discover -s "${TEST_FILES[0]%/*}" -v > "$OUTPUT_FILE" 2>&1 || EXIT_CODE=$?
    else
        $TEST_RUNNER discover -v > "$OUTPUT_FILE" 2>&1 || EXIT_CODE=$?
    fi

    # Parse the "Ran N tests" line and the "OK" / "FAILED (failures=X,
    # errors=Y)" line, not log lines: grep -c "ok" matches any line
    # containing "ok" (e.g. "token"), and unittest has no per-test PASSED
    # marker to count directly. "failures=" is anchored to "(failures="
    # so it doesn't match inside "(expected failures=N)", which unittest
    # prints on a fully green run (exit code 0); "errors=" needs no such
    # anchor since unittest never prints an "expected errors=" variant.
    # skipped= is parsed and subtracted so a skipped test isn't counted
    # as passed.
    TOTAL=$(grep -oE "^Ran [0-9]+ test" "$OUTPUT_FILE" | tail -1 | grep -oE "[0-9]+" || true)
    FAILED=$(grep -oE "\(failures=[0-9]+" "$OUTPUT_FILE" | tail -1 | grep -oE "[0-9]+" || true)
    ERRORS=$(grep -oE "errors=[0-9]+" "$OUTPUT_FILE" | tail -1 | grep -oE "[0-9]+" || true)
    SKIPPED=$(grep -oE "skipped=[0-9]+" "$OUTPUT_FILE" | tail -1 | grep -oE "[0-9]+" || true)
    TOTAL="${TOTAL:-0}"
    FAILED="${FAILED:-0}"
    ERRORS="${ERRORS:-0}"
    SKIPPED="${SKIPPED:-0}"
    PASSED=$((TOTAL - FAILED - ERRORS - SKIPPED))
fi

# Extract traceback if there are failures. Passed via --rawfile (not
# --arg) so a large traceback never hits the command-line length limit.
TRACEBACK_FILE=$(mktemp)
if [ $EXIT_CODE -ne 0 ]; then
    cp "$OUTPUT_FILE" "$TRACEBACK_FILE"
fi

# Output JSON. Built with jq -n --argjson (not a heredoc) so a malformed
# value fails loudly instead of producing broken JSON.
jq -n \
    --argjson passed "$PASSED" \
    --argjson failed "$FAILED" \
    --argjson errors "$ERRORS" \
    --argjson exit_code "$EXIT_CODE" \
    --arg test_runner "$TEST_RUNNER" \
    --rawfile traceback "$TRACEBACK_FILE" \
    '{passed: $passed, failed: $failed, errors: $errors, exit_code: $exit_code, test_runner: $test_runner, traceback: $traceback}'

rm -f "$OUTPUT_FILE" "$TRACEBACK_FILE"
exit $EXIT_CODE
