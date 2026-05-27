#!/usr/bin/env bash
# validate_modfile_go.sh - Post-edit validation of go.mod / go.sum.
#
# Usage: bash validate_modfile_go.sh <project_path>
#
# Equivalent of validate_lockfile.sh for the JS path. Runs the lightest set
# of checks that catch hand-edit / merge-conflict / version-skew problems
# locally before committing:
#
#   1. `go mod verify`      — re-hash go.sum entries against module cache
#   2. `go vet ./...`       — quick syntax / declared-but-unused checks
#   3. `go mod tidy -diff`  — would `go mod tidy` need to change anything?
#                              (Go 1.21+; older versions get a less-strict fallback)
#
# Output JSON:
# {
#   "status": "success" | "failure",
#   "checks": {
#     "go_mod_verify":   {"exit_code": N, "stdout_tail": "...", "stderr_tail": "..."},
#     "go_vet":          {"exit_code": N, ...},
#     "go_mod_tidy_diff": {"exit_code": N, ...}
#   },
#   "errors": [...]
# }

set -uo pipefail

PROJECT_PATH="${1:-.}"
PROJECT_PATH=$(cd "$PROJECT_PATH" && pwd -P)
cd "$PROJECT_PATH" || exit 1

if [ ! -f "go.mod" ]; then
    printf '{"status":"failure","errors":["go.mod not found"]}\n'
    exit 1
fi

if ! command -v go >/dev/null 2>&1; then
    printf '{"status":"failure","errors":["go binary not in PATH"]}\n'
    exit 1
fi

run_check() {
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

VERIFY=$(run_check "go_mod_verify" go mod verify)
VET=$(run_check    "go_vet"        go vet ./...)

# `go mod tidy -diff` was added in 1.21 (and made non-mutating in 1.23?).
# Older versions: fall back to running `tidy` in a stashed go.mod and diffing.
GO_VER=$(go version 2>/dev/null | awk '{print $3}' | sed 's/^go//')
GO_MINOR=$(echo "$GO_VER" | awk -F. '{print $2}')
TIDY_DIFF="{}"
if [ "${GO_MINOR:-0}" -ge 21 ] 2>/dev/null; then
    TIDY_DIFF=$(run_check "go_mod_tidy_diff" go mod tidy -diff)
else
    # Fallback: copy go.mod to temp, run tidy, diff. Best-effort.
    TMP=$(mktemp -d)
    cp go.mod "$TMP/go.mod"
    [ -f go.sum ] && cp go.sum "$TMP/go.sum"
    pushd "$TMP" >/dev/null || true
    if (cd "$TMP" && go mod tidy >/dev/null 2>&1); then
        rc=0
        if ! diff -q go.mod "$PROJECT_PATH/go.mod" >/dev/null 2>&1; then
            rc=2  # tidy would change go.mod
        fi
        TIDY_DIFF=$(jq -nc --argjson rc "$rc" \
            '{name:"go_mod_tidy_diff_fallback", exit_code:$rc, stdout_tail:"", stderr_tail:""}')
    else
        TIDY_DIFF=$(jq -nc '{name:"go_mod_tidy_diff_fallback", exit_code:1, stdout_tail:"", stderr_tail:"tidy failed in sandbox"}')
    fi
    popd >/dev/null || true
    rm -rf "$TMP"
fi

# Compose final
VERIFY_RC=$(echo "$VERIFY" | jq -r '.exit_code')
VET_RC=$(echo "$VET" | jq -r '.exit_code')
TIDY_RC=$(echo "$TIDY_DIFF" | jq -r '.exit_code')

STATUS="success"
ERRORS_JSON="[]"
declare -a ERRS=()
[ "$VERIFY_RC" != "0" ] && STATUS="failure" && ERRS+=("go mod verify failed (rc=$VERIFY_RC) — go.sum hashes do not match downloaded modules")
[ "$VET_RC" != "0" ]    && STATUS="failure" && ERRS+=("go vet failed (rc=$VET_RC) — see vet stderr_tail")
[ "$TIDY_RC" != "0" ]   && STATUS="failure" && ERRS+=("go mod tidy would change go.mod/go.sum (rc=$TIDY_RC) — run 'go mod tidy' to fix")

if [ "${#ERRS[@]}" -gt 0 ]; then
    ERRORS_JSON=$(printf '%s\n' "${ERRS[@]}" | jq -R -s 'split("\n") | map(select(. != ""))')
fi

jq -nc \
    --arg status "$STATUS" \
    --argjson verify "$VERIFY" \
    --argjson vet "$VET" \
    --argjson tidy "$TIDY_DIFF" \
    --argjson errors "$ERRORS_JSON" \
    '{status:$status, checks:{go_mod_verify:$verify, go_vet:$vet, go_mod_tidy_diff:$tidy}, errors:$errors}'

[ "$STATUS" = "success" ] || exit 1
