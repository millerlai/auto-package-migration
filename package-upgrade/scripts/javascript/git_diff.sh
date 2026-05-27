#!/usr/bin/env bash
# git_diff_js.sh - Clone repo and diff JS/TS files between version tags.
#
# Usage: bash git_diff_js.sh <repo_url> <old_version> <new_version>
# Output: HTML-comment metadata header + git diff restricted to JS/TS
#         source files. Designed to be consumed by an LLM in the same way
#         as git_diff.sh — the report cites these headers.
#
# Filters: *.{js,jsx,mjs,cjs,ts,tsx,d.ts}.
# Excludes: tests/__tests__/test/spec/fixtures dirs, *.test.* / *.spec.*,
#           and minified bundles, so the diff focuses on shippable API code.

set -euo pipefail

REPO_URL="$1"
OLD_VER="$2"
NEW_VER="$3"
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
    # Try common JS tag patterns
    local patterns=("v$ver" "$ver" "release-$ver" "release/$ver" "releases/$ver" "@$ver" "package-name@$ver")
    for pattern in "${patterns[@]}"; do
        if git rev-parse "$pattern" >/dev/null 2>&1; then
            echo "$pattern"
            return 0
        fi
    done
    # Monorepo-style scoped tags often look like `<pkg>@<ver>` — fall back to
    # any tag ending in @<ver>
    local match
    match=$(git tag --list "*@$ver" | head -1)
    if [ -n "$match" ]; then
        echo "$match"
        return 0
    fi
    return 1
}

OLD_TAG=$(find_tag "$OLD_VER")
NEW_TAG=$(find_tag "$NEW_VER")

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
echo "<!-- git_diff_language: javascript -->"
if [ -n "$COMPARE_URL" ]; then
    echo "<!-- git_diff_compare_url: ${COMPARE_URL} -->"
fi
echo

# Include JS/TS sources, exclude tests + minified bundles.
git diff "$OLD_TAG".."$NEW_TAG" -- \
    '*.js' '*.jsx' '*.mjs' '*.cjs' '*.ts' '*.tsx' '*.d.ts' \
    ':(exclude)**/*.test.*' \
    ':(exclude)**/*.spec.*' \
    ':(exclude)**/__tests__/**' \
    ':(exclude)**/test/**' \
    ':(exclude)**/tests/**' \
    ':(exclude)**/__mocks__/**' \
    ':(exclude)**/fixtures/**' \
    ':(exclude)**/*.min.js' \
    ':(exclude)**/dist/**' \
    ':(exclude)**/build/**'
