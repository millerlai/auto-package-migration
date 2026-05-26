#!/usr/bin/env bash
# submit_feedback.sh - Open a GitHub Issue on millerlai/auto-package-migration
# with the feedback label, using a sanitized markdown body.
#
# Usage:
#   bash submit_feedback.sh --title <title> --body-file <path> [--dry-run]
#
# Exit codes:
#   0  success — issue URL printed to stdout
#   1  bad arguments / body file missing
#   2  gh CLI not installed
#   3  gh not authenticated
#   4  gh rejected the request (permissions, repo not found, etc.)
#   5  unknown error

set -euo pipefail

REPO="millerlai/auto-package-migration"
LABEL="feedback"
TITLE=""
BODY_FILE=""
DRY_RUN="false"

while [ $# -gt 0 ]; do
    case "$1" in
        --title)     TITLE="$2"; shift 2 ;;
        --body-file) BODY_FILE="$2"; shift 2 ;;
        --dry-run)   DRY_RUN="true"; shift ;;
        -h|--help)
            sed -n '2,15p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown arg: $1" >&2
            exit 1
            ;;
    esac
done

if [ -z "$TITLE" ] || [ -z "$BODY_FILE" ]; then
    echo "Missing required arguments: --title and --body-file" >&2
    exit 1
fi
if [ ! -f "$BODY_FILE" ]; then
    echo "Body file not found: $BODY_FILE" >&2
    exit 1
fi

if [ "$DRY_RUN" = "true" ]; then
    echo "DRY RUN — would run:"
    echo "  gh issue create \\"
    echo "      --repo '$REPO' \\"
    echo "      --label '$LABEL' \\"
    echo "      --title '$TITLE' \\"
    echo "      --body-file '$BODY_FILE'"
    exit 0
fi

if ! command -v gh >/dev/null 2>&1; then
    echo "gh CLI not installed." >&2
    echo "Install: https://github.com/cli/cli#installation" >&2
    exit 2
fi

if ! gh auth status >/dev/null 2>&1; then
    echo "gh CLI is not authenticated. Run: gh auth login" >&2
    exit 3
fi

# Capture stderr separately so we can disambiguate auth/permission errors.
ERR_TMP=$(mktemp)
trap 'rm -f "$ERR_TMP"' EXIT

if URL=$(gh issue create \
            --repo "$REPO" \
            --label "$LABEL" \
            --title "$TITLE" \
            --body-file "$BODY_FILE" 2>"$ERR_TMP"); then
    echo "$URL"
    exit 0
fi

# gh failed — classify based on stderr
ERR_TEXT=$(cat "$ERR_TMP")
echo "$ERR_TEXT" >&2

if echo "$ERR_TEXT" | grep -qiE "not.+(authenticated|logged in)|authentication required"; then
    exit 3
fi
if echo "$ERR_TEXT" | grep -qiE "not found|permission|forbidden|HTTP 40[34]"; then
    exit 4
fi
exit 5
