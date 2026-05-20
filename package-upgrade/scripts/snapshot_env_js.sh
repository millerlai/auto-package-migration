#!/usr/bin/env bash
# snapshot_env_js.sh - Save and restore JS project state.
#
# Usage: bash snapshot_env_js.sh <project_path> save|restore|clean
#
# Only backs up package.json + lockfile(s). node_modules is intentionally
# excluded: it can be gigabytes large and is fully reproducible from the
# lockfile via `npm ci` / `pnpm install --frozen-lockfile` / etc.

set -euo pipefail

PROJECT_PATH="${1:-.}"
ACTION="${2:-save}"
SNAPSHOT_DIR="$PROJECT_PATH/.upgrade_snapshot_js"

cd "$PROJECT_PATH" || exit 1

LOCK_PATTERNS=(
    "package.json"
    "package-lock.json"
    "npm-shrinkwrap.json"
    "yarn.lock"
    "pnpm-lock.yaml"
    "bun.lock"
    "bun.lockb"
    ".npmrc"
    ".yarnrc"
    ".yarnrc.yml"
    "pnpm-workspace.yaml"
)

restore_command_hint() {
    case "$1" in
        npm) echo "npm ci" ;;
        yarn) echo "yarn install --frozen-lockfile" ;;
        pnpm) echo "pnpm install --frozen-lockfile" ;;
        bun) echo "bun install --frozen-lockfile" ;;
        *) echo "<run your package manager install command>" ;;
    esac
}

detect_pm() {
    if [ -f "$1/bun.lock" ] || [ -f "$1/bun.lockb" ]; then echo "bun"
    elif [ -f "$1/pnpm-lock.yaml" ]; then echo "pnpm"
    elif [ -f "$1/yarn.lock" ]; then echo "yarn"
    elif [ -f "$1/package-lock.json" ] || [ -f "$1/npm-shrinkwrap.json" ]; then echo "npm"
    else echo "unknown"
    fi
}

case "$ACTION" in
    save)
        echo "Creating JS environment snapshot..." >&2
        mkdir -p "$SNAPSHOT_DIR"

        for pattern in "${LOCK_PATTERNS[@]}"; do
            if [ -f "$pattern" ]; then
                cp "$pattern" "$SNAPSHOT_DIR/" 2>/dev/null || true
                echo "  Backed up: $pattern" >&2
            fi
        done

        PM=$(detect_pm ".")
        cat > "$SNAPSHOT_DIR/manifest.txt" <<EOF
Snapshot created: $(date)
Project path:     $PROJECT_PATH
Package manager:  $PM
Restore command:  $(restore_command_hint "$PM")
Files backed up:
$(ls -1 "$SNAPSHOT_DIR" 2>/dev/null | grep -v manifest.txt || echo "  (none)")
EOF
        echo "✓ Snapshot saved to $SNAPSHOT_DIR" >&2
        echo "  node_modules is NOT backed up — restore reinstalls from lockfile." >&2
        echo "{\"status\": \"success\", \"snapshot_dir\": \"$SNAPSHOT_DIR\", \"pkg_manager\": \"$PM\"}"
        ;;

    restore)
        if [ ! -d "$SNAPSHOT_DIR" ]; then
            echo "ERROR: No snapshot found at $SNAPSHOT_DIR" >&2
            echo '{"status": "error", "message": "No snapshot found"}'
            exit 1
        fi

        echo "Restoring JS environment from snapshot..." >&2
        for file in "$SNAPSHOT_DIR"/*; do
            fname=$(basename "$file")
            [ "$fname" = "manifest.txt" ] && continue
            cp "$file" "$PROJECT_PATH/" 2>/dev/null || true
            echo "  Restored: $fname" >&2
        done

        PM=$(detect_pm ".")
        echo "  Reinstall manually (we don't run install automatically to avoid lifecycle scripts):" >&2
        echo "    $(restore_command_hint "$PM")" >&2
        echo "{\"status\": \"success\", \"restored_from\": \"$SNAPSHOT_DIR\", \"pkg_manager\": \"$PM\", \"reinstall_hint\": \"$(restore_command_hint "$PM")\"}"
        ;;

    clean)
        if [ -d "$SNAPSHOT_DIR" ]; then
            rm -rf "$SNAPSHOT_DIR"
            echo "✓ JS snapshot cleaned" >&2
            echo '{"status": "success", "action": "cleaned"}'
        else
            echo "No JS snapshot to clean" >&2
            echo '{"status": "success", "action": "none"}'
        fi
        ;;

    *)
        echo "Usage: bash snapshot_env_js.sh <project_path> save|restore|clean" >&2
        echo '{"status": "error", "message": "Invalid action"}'
        exit 1
        ;;
esac
