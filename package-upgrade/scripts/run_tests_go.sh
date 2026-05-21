#!/usr/bin/env bash
# run_tests_go.sh - Run Go tests and emit structured results.
#
# Usage: bash run_tests_go.sh <project_path> [--files <source_files...>] [--all] [--race]
#
# Mode mapping:
#   --files: map each .go file to its containing package and run `go test`
#            against just those package paths (Go is package-level, not file-level)
#   --all:   `go test ./...`
#   --race:  add `-race` flag (recommended for CVE upgrades)
#
# Output JSON aligned with run_tests_js.sh / run_tests.sh.

set -euo pipefail

PROJECT_PATH="${1:-.}"
shift || true
cd "$PROJECT_PATH" || exit 1

MODE="all"
RACE=""
SOURCE_FILES=()
while [[ $# -gt 0 ]]; do
    case $1 in
        --files)
            MODE="files"; shift
            while [[ $# -gt 0 ]] && [[ ! $1 =~ ^-- ]]; do
                SOURCE_FILES+=("$1")
                shift
            done
            ;;
        --all)  MODE="all"; shift ;;
        --race) RACE="-race"; shift ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

if [ ! -f "go.mod" ]; then
    echo '{"error": "go.mod not found"}'
    exit 1
fi

if ! command -v go >/dev/null 2>&1; then
    echo '{"error": "go binary not in PATH"}'
    exit 1
fi

# Determine package paths to test
TARGETS=()
if [ "$MODE" = "all" ]; then
    TARGETS+=("./...")
else
    # Map files → containing dirs (which Go treats as package paths)
    declare -A SEEN_DIRS=()
    for f in "${SOURCE_FILES[@]}"; do
        if [ -f "$f" ]; then
            d=$(dirname "$f")
            # Normalize to ./relative-path
            case "$d" in
                /*) ;;
                ./*) ;;
                *) d="./$d" ;;
            esac
            SEEN_DIRS["$d"]=1
        fi
    done
    for d in "${!SEEN_DIRS[@]}"; do
        TARGETS+=("$d")
    done
    if [ "${#TARGETS[@]}" -eq 0 ]; then
        TARGETS+=("./...")
    fi
fi

echo "Running: go test $RACE -count=1 -json ${TARGETS[*]}" >&2

OUTPUT_FILE=$(mktemp)
trap 'rm -f "$OUTPUT_FILE"' EXIT
EXIT_CODE=0

# -json: machine-readable per-event output
# -count=1: bypass test result cache (we just upgraded a dep — cache may be stale)
go test $RACE -count=1 -json "${TARGETS[@]}" > "$OUTPUT_FILE" 2>&1 || EXIT_CODE=$?

PARSED=$(python3 - <<'PY' < "$OUTPUT_FILE" || echo '{"passed":0,"failed":0,"failed_tests":[],"traceback":""}'
import json, sys

passed = 0
failed = 0
skipped = 0
failed_tests = []   # [{package, test, output_excerpt}]
package_results = {}
test_output_buffer = {}   # (pkg, test) -> [output lines]

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        continue
    action = ev.get("Action", "")
    pkg = ev.get("Package", "")
    test = ev.get("Test", "")
    if action == "output":
        key = (pkg, test)
        test_output_buffer.setdefault(key, []).append(ev.get("Output", ""))
    elif action == "pass" and test:
        passed += 1
    elif action == "fail" and test:
        failed += 1
        excerpt = "".join(test_output_buffer.get((pkg, test), []))[-2000:]
        failed_tests.append({
            "package": pkg,
            "test": test,
            "output": excerpt,
        })
    elif action == "skip" and test:
        skipped += 1
    elif action in ("pass", "fail") and not test:
        package_results[pkg] = action

# Build a concise traceback excerpt (top N failure outputs concatenated)
traceback_parts = []
for ft in failed_tests[:10]:
    traceback_parts.append(f"--- FAIL: {ft['package']}.{ft['test']}\n{ft['output']}")
traceback = "\n".join(traceback_parts)

print(json.dumps({
    "passed": passed,
    "failed": failed,
    "skipped": skipped,
    "failed_tests": failed_tests,
    "traceback": traceback,
}))
PY
)

# If python parse failed (e.g. -json output absent), keep the raw output as traceback
if [ -z "$PARSED" ]; then
    PARSED='{"passed":0,"failed":0,"failed_tests":[],"traceback":"(parse failed)"}'
fi

PASSED=$(echo "$PARSED" | python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("passed",0))' 2>/dev/null || echo 0)
FAILED=$(echo "$PARSED" | python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("failed",0))' 2>/dev/null || echo 0)
SKIPPED=$(echo "$PARSED" | python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("skipped",0))' 2>/dev/null || echo 0)
TRACEBACK=$(echo "$PARSED" | python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("traceback",""))' 2>/dev/null || echo "")
FAILED_TESTS=$(echo "$PARSED" | python3 -c 'import json,sys; print(json.dumps(json.loads(sys.stdin.read()).get("failed_tests",[])))' 2>/dev/null || echo "[]")

# JSON-escape strings via jq when available
escape() { printf '%s' "$1" | jq -Rs . 2>/dev/null || printf '""'; }

cat <<EOF
{
  "framework": "go-test",
  "pkg_manager": "gomod",
  "race": $([ -n "$RACE" ] && echo true || echo false),
  "targets": $(printf '%s\n' "${TARGETS[@]}" | jq -R -s 'split("\n") | map(select(. != ""))' 2>/dev/null || echo "[]"),
  "passed": $PASSED,
  "failed": $FAILED,
  "skipped": $SKIPPED,
  "exit_code": $EXIT_CODE,
  "failed_tests": $FAILED_TESTS,
  "traceback": $(escape "$TRACEBACK")
}
EOF
exit $EXIT_CODE
