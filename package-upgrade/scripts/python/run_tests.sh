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

    # Parse pytest output
    PASSED=$(grep -c "PASSED" "$OUTPUT_FILE" || echo "0")
    FAILED=$(grep -c "FAILED" "$OUTPUT_FILE" || echo "0")
    ERRORS=$(grep -c "ERROR" "$OUTPUT_FILE" || echo "0")

else
    # Run unittest
    if [ "$MODE" = "files" ]; then
        $TEST_RUNNER discover -s "${TEST_FILES[0]%/*}" -v > "$OUTPUT_FILE" 2>&1 || EXIT_CODE=$?
    else
        $TEST_RUNNER discover -v > "$OUTPUT_FILE" 2>&1 || EXIT_CODE=$?
    fi

    # Parse unittest output
    PASSED=$(grep -c "ok" "$OUTPUT_FILE" || echo "0")
    FAILED=$(grep -c "FAIL" "$OUTPUT_FILE" || echo "0")
    ERRORS=$(grep -c "ERROR" "$OUTPUT_FILE" || echo "0")
fi

# Extract traceback if there are failures
TRACEBACK=""
if [ $EXIT_CODE -ne 0 ]; then
    TRACEBACK=$(cat "$OUTPUT_FILE")
fi

# Output JSON
cat <<EOF
{
  "passed": $PASSED,
  "failed": $FAILED,
  "errors": $ERRORS,
  "exit_code": $EXIT_CODE,
  "test_runner": "$TEST_RUNNER",
  "traceback": $(echo "$TRACEBACK" | jq -Rs .)
}
EOF

rm -f "$OUTPUT_FILE"
exit $EXIT_CODE
