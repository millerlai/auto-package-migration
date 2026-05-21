#!/usr/bin/env bash
# save_token.sh - Persist an auth token to a project-local .env.<name> file
# with conflict detection and safe permissions.
#
# Usage:
#   bash save_token.sh <project_path> <env_file_basename> <KEY> <VALUE> [--force]
#
#   <env_file_basename> example: .env.jfrog
#   <KEY> example:              JFROG_TOKEN
#
# Behaviour:
#   * If <env_file_basename> does not exist → create it (chmod 600) with KEY=VALUE.
#   * If file exists but KEY=... line is absent → append KEY=VALUE.
#   * If file exists AND KEY=... line is present:
#       - Without --force: exit 2 and emit JSON {"status": "conflict", ...}.
#         The caller (LLM) must ask the user, then re-invoke with --force.
#       - With --force: replace the existing line in-place.
#   * Always ensures <env_file_basename> is listed in .gitignore (appends if
#     missing; creates .gitignore if absent). The skill must never commit
#     a token file.
#   * File mode always normalised to 600 (rw for owner only).
#
# Output: JSON status to stdout.
#   {"status": "created" | "appended" | "replaced" | "conflict" | "error",
#    "file": "<abs path>", "key": "<KEY>", "message": "..."}
# Exit codes:
#   0  success (created / appended / replaced)
#   2  conflict (file has KEY=... and --force not given)
#   1  hard error (bad args, IO failure)

set -euo pipefail

if [ "$#" -lt 4 ]; then
    cat >&2 <<EOF
Usage: bash save_token.sh <project_path> <env_file_basename> <KEY> <VALUE> [--force]
Example: bash save_token.sh . .env.jfrog JFROG_TOKEN cmVkYWN0ZWQ=
EOF
    printf '{"status":"error","message":"missing arguments"}\n'
    exit 1
fi

PROJECT_PATH="$1"
ENV_FILE_NAME="$2"
KEY="$3"
VALUE="$4"
FORCE="false"
[ "${5:-}" = "--force" ] && FORCE="true"

PROJECT_ABS=$(cd "$PROJECT_PATH" && pwd -P)
TARGET="$PROJECT_ABS/$ENV_FILE_NAME"
GITIGNORE="$PROJECT_ABS/.gitignore"

ensure_gitignore() {
    # Make sure the env file is gitignored so a token never ends up in git.
    if [ -f "$GITIGNORE" ]; then
        if ! grep -Fxq "$ENV_FILE_NAME" "$GITIGNORE" 2>/dev/null && \
           ! grep -Fxq ".env.*" "$GITIGNORE" 2>/dev/null && \
           ! grep -Fxq "$ENV_FILE_NAME/" "$GITIGNORE" 2>/dev/null; then
            printf '\n# Auth token files persisted by package-upgrade skill\n%s\n' \
                "$ENV_FILE_NAME" >> "$GITIGNORE"
        fi
    else
        # Create a minimal .gitignore if the project doesn't have one
        cat > "$GITIGNORE" <<EOF
# Auth token files persisted by package-upgrade skill
$ENV_FILE_NAME
EOF
    fi
}

emit() {
    # emit <status> <message>
    local status="$1"
    local msg="$2"
    if command -v jq >/dev/null 2>&1; then
        jq -nc --arg status "$status" \
               --arg file "$TARGET" \
               --arg key "$KEY" \
               --arg message "$msg" \
               '{status:$status, file:$file, key:$key, message:$message}'
    else
        printf '{"status":"%s","file":"%s","key":"%s","message":"%s"}\n' \
            "$status" "$TARGET" "$KEY" "$msg"
    fi
}

write_atomic() {
    # Write content to TARGET via a temp file then mv. Always chmod 600.
    local content="$1"
    local tmp="${TARGET}.tmp.$$"
    printf '%s' "$content" > "$tmp"
    chmod 600 "$tmp"
    mv "$tmp" "$TARGET"
}

# Case 1: file doesn't exist → create with single line
if [ ! -f "$TARGET" ]; then
    write_atomic "$KEY=$VALUE
"
    ensure_gitignore
    emit "created" "Created $TARGET with $KEY (chmod 600). Future preflight will source this automatically."
    exit 0
fi

# Case 2: file exists. Look for existing KEY= line.
if grep -qE "^$KEY=" "$TARGET" 2>/dev/null; then
    if [ "$FORCE" != "true" ]; then
        emit "conflict" "File already contains $KEY=... — re-run with --force to overwrite, or skip to keep existing value."
        exit 2
    fi
    # Replace line in-place via temp file (portable: avoids sed -i differences across macOS/GNU)
    NEW_CONTENT=$(awk -v k="$KEY" -v v="$VALUE" '
        BEGIN { replaced=0 }
        $0 ~ "^" k "=" { print k "=" v; replaced=1; next }
        { print }
        END { if (!replaced) print k "=" v }
    ' "$TARGET")
    write_atomic "$NEW_CONTENT
"
    ensure_gitignore
    emit "replaced" "Replaced existing $KEY in $TARGET (chmod 600)."
    exit 0
fi

# Case 3: file exists but no matching key → append
# Make sure existing file ends with a newline before appending
if [ -s "$TARGET" ]; then
    LAST_BYTE=$(tail -c 1 "$TARGET" 2>/dev/null || echo "")
    if [ "$LAST_BYTE" != $'\n' ]; then
        printf '\n' >> "$TARGET"
    fi
fi
printf '%s=%s\n' "$KEY" "$VALUE" >> "$TARGET"
chmod 600 "$TARGET"
ensure_gitignore
emit "appended" "Appended $KEY to existing $TARGET (chmod 600)."
exit 0
