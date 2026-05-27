#!/usr/bin/env bash
# git_diff_go.sh - Clone repo and diff Go source files between version tags.
#
# Usage: bash git_diff_go.sh <repo_url> <old_version> <new_version> [--subdir <path>]
#
# `--subdir` is for monorepo modules where the target lives under a sub-path
# (e.g. `cmd/foo` with tags `cmd/foo/v1.2.3`).
#
# Output: HTML-comment metadata header + git diff restricted to .go source
# files. Same shape as git_diff_js.sh so Phase 3 LLM logic is reusable.
#
# Filters: *.go (excludes *_test.go, vendor/, examples/, testdata/, .pb.go).

set -euo pipefail

REPO_URL="${1:-}"
OLD_VER="${2:-}"
NEW_VER="${3:-}"
SUBDIR=""

shift 3 2>/dev/null || true
while [[ $# -gt 0 ]]; do
    case $1 in
        --subdir) SUBDIR="$2"; shift 2 ;;
        *) shift ;;
    esac
done

if [ -z "$REPO_URL" ] || [ -z "$OLD_VER" ] || [ -z "$NEW_VER" ]; then
    echo "Usage: bash git_diff_go.sh <repo_url> <old_version> <new_version> [--subdir <path>]" >&2
    exit 1
fi

WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"' EXIT
cd "$WORK_DIR" || exit 1

echo "Cloning repository (shallow)..." >&2
if ! git clone --bare --filter=tree:0 "$REPO_URL" repo.git 2>/dev/null; then
    echo "ERROR: Failed to clone repository: $REPO_URL" >&2
    exit 1
fi
cd repo.git || exit 1

find_tag() {
    local ver="$1"
    local prefix="$2"  # optional subdir prefix for monorepo tags
    # Try common Go tag patterns. Order matters: more-specific first.
    local patterns=()
    if [ -n "$prefix" ]; then
        patterns+=("${prefix}/$ver" "${prefix}/v$ver")
    fi
    patterns+=("v$ver" "$ver" "release-$ver" "release/$ver")
    for pattern in "${patterns[@]}"; do
        if git rev-parse "$pattern" >/dev/null 2>&1; then
            echo "$pattern"
            return 0
        fi
    done
    # Fallback: any tag ending in @<ver> or /v<ver>
    local match
    match=$(git tag --list "*@$ver" 2>/dev/null | head -1)
    [ -n "$match" ] && echo "$match" && return 0
    match=$(git tag --list "*/v$ver" 2>/dev/null | head -1)
    [ -n "$match" ] && echo "$match" && return 0
    return 1
}

OLD_TAG=$(find_tag "$OLD_VER" "$SUBDIR") || true
NEW_TAG=$(find_tag "$NEW_VER" "$SUBDIR") || true

if [ -z "$OLD_TAG" ]; then
    echo "ERROR: Cannot find tag for version $OLD_VER" >&2
    echo "Available tags (most recent 20):" >&2
    git tag --list | tail -20 >&2
    exit 1
fi
if [ -z "$NEW_TAG" ]; then
    echo "ERROR: Cannot find tag for version $NEW_VER" >&2
    echo "Available tags (most recent 20):" >&2
    git tag --list | tail -20 >&2
    exit 1
fi

echo "Comparing $OLD_TAG -> $NEW_TAG" >&2

OLD_SHA=$(git rev-parse "$OLD_TAG^{commit}")
NEW_SHA=$(git rev-parse "$NEW_TAG^{commit}")

COMPARE_URL=""
if [[ "$REPO_URL" =~ github\.com[:/]+([^/]+)/([^/\.]+) ]]; then
    GH_OWNER="${BASH_REMATCH[1]}"
    GH_REPO="${BASH_REMATCH[2]%.git}"
    COMPARE_URL="https://github.com/${GH_OWNER}/${GH_REPO}/compare/${OLD_TAG}...${NEW_TAG}"
fi

echo "<!-- git_diff_repo_url: ${REPO_URL} -->"
echo "<!-- git_diff_old_version: ${OLD_VER} -->"
echo "<!-- git_diff_new_version: ${NEW_VER} -->"
echo "<!-- git_diff_old_tag: ${OLD_TAG} -->"
echo "<!-- git_diff_new_tag: ${NEW_TAG} -->"
echo "<!-- git_diff_old_sha: ${OLD_SHA} -->"
echo "<!-- git_diff_new_sha: ${NEW_SHA} -->"
echo "<!-- git_diff_language: go -->"
[ -n "$SUBDIR" ] && echo "<!-- git_diff_subdir: ${SUBDIR} -->"
if [ -n "$COMPARE_URL" ]; then
    echo "<!-- git_diff_compare_url: ${COMPARE_URL} -->"
fi
echo

# Diff .go files, excluding tests/vendor/examples/testdata/generated.
# If subdir specified, restrict to that subtree.
GIT_DIFF_ARGS=(
    "$OLD_TAG..$NEW_TAG"
    "--"
)
if [ -n "$SUBDIR" ]; then
    GIT_DIFF_ARGS+=("$SUBDIR/*.go")
else
    GIT_DIFF_ARGS+=("*.go")
fi
GIT_DIFF_ARGS+=(
    ':(exclude)**/*_test.go'
    ':(exclude)**/vendor/**'
    ':(exclude)**/testdata/**'
    ':(exclude)**/examples/**'
    ':(exclude)**/_examples/**'
    ':(exclude)**/*.pb.go'
    ':(exclude)**/zz_generated*.go'
    ':(exclude)**/generated*.go'
)

git diff "${GIT_DIFF_ARGS[@]}"
