#!/usr/bin/env bash
# snapshot_env_js.sh - Save and restore JS project state.
#
# Usage: bash snapshot_env_js.sh <project_path> save|restore|clean|locate
#
# Snapshots live OUTSIDE the repo at:
#   ~/.cache/package-upgrade/<repo-hash>/<timestamp>/
# This way snapshots are zero-pollution: never accidentally committed, never
# interfere with `git clean -fdx`, and multiple snapshots coexist per repo.
#
# Only backs up package.json + lockfile(s) + relevant config (`.npmrc`,
# `.yarnrc.yml`, etc). node_modules is intentionally excluded; restore
# reinstalls via the package manager's frozen-lockfile mode.

set -euo pipefail

PROJECT_PATH="${1:-.}"
ACTION="${2:-save}"

PROJECT_PATH=$(cd "$PROJECT_PATH" && pwd -P)

# Stable repo hash so the same repo always maps to the same parent dir
REPO_HASH=$(printf '%s' "$PROJECT_PATH" | shasum 2>/dev/null | awk '{print $1}' | cut -c1-12)
[ -z "$REPO_HASH" ] && REPO_HASH=$(printf '%s' "$PROJECT_PATH" | md5 2>/dev/null | cut -c1-12)
[ -z "$REPO_HASH" ] && REPO_HASH="unknown"

CACHE_ROOT="${HOME}/.cache/package-upgrade/${REPO_HASH}"
LATEST_LINK="${CACHE_ROOT}/latest"

cd "$PROJECT_PATH" || exit 1

LOCK_PATTERNS=(
    "package.json"
    "package-lock.json"
    "npm-shrinkwrap.json"
    "yarn.lock"
    "pnpm-lock.yaml"
    "pnpm-workspace.yaml"
    "bun.lock"
    "bun.lockb"
    ".npmrc"
    ".yarnrc"
    ".yarnrc.yml"
    ".yarnrc.default.yml"
)

restore_command_hint() {
    case "$1" in
        npm)  echo "npm ci" ;;
        yarn) echo "yarn install --immutable" ;;
        pnpm) echo "pnpm install --frozen-lockfile" ;;
        bun)  echo "bun install --frozen-lockfile" ;;
        *)    echo "<run your package manager install command>" ;;
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
        TIMESTAMP=$(date +%Y%m%dT%H%M%S)
        SNAPSHOT_DIR="${CACHE_ROOT}/${TIMESTAMP}"
        mkdir -p "$SNAPSHOT_DIR"

        echo "Creating JS environment snapshot..." >&2
        echo "  Location: $SNAPSHOT_DIR" >&2

        for pattern in "${LOCK_PATTERNS[@]}"; do
            if [ -f "$pattern" ]; then
                # Preserve subdirectory structure (only matters for workspaces but cheap)
                cp "$pattern" "$SNAPSHOT_DIR/" 2>/dev/null || true
                echo "  Backed up: $pattern" >&2
            fi
        done

        PM=$(detect_pm ".")
        cat > "$SNAPSHOT_DIR/manifest.txt" <<EOF
Snapshot created: $(date)
Project path:     $PROJECT_PATH
Repo hash:        $REPO_HASH
Package manager:  $PM
Restore command:  $(restore_command_hint "$PM")
Files backed up:
$(ls -1 "$SNAPSHOT_DIR" 2>/dev/null | grep -v manifest.txt || echo "  (none)")
EOF

        # Update "latest" symlink for easy restore
        ln -snf "$SNAPSHOT_DIR" "$LATEST_LINK" 2>/dev/null || true

        echo "✓ Snapshot saved to $SNAPSHOT_DIR" >&2
        echo "  node_modules is NOT backed up — restore reinstalls from lockfile." >&2
        printf '{"status": "success", "snapshot_dir": "%s", "pkg_manager": "%s"}\n' \
            "$SNAPSHOT_DIR" "$PM"
        ;;

    restore)
        SNAPSHOT_DIR=""
        if [ -L "$LATEST_LINK" ] && [ -d "$LATEST_LINK" ]; then
            SNAPSHOT_DIR=$(readlink "$LATEST_LINK")
            # readlink may return relative; resolve
            [ "${SNAPSHOT_DIR#/}" = "$SNAPSHOT_DIR" ] && SNAPSHOT_DIR="${CACHE_ROOT}/${SNAPSHOT_DIR}"
        elif [ -d "$CACHE_ROOT" ]; then
            # Fallback: pick the lexicographically latest timestamp dir
            SNAPSHOT_DIR=$(ls -1d "$CACHE_ROOT"/*/ 2>/dev/null | grep -v '/latest/$' | sort | tail -1 | sed 's:/$::')
        fi

        if [ -z "$SNAPSHOT_DIR" ] || [ ! -d "$SNAPSHOT_DIR" ]; then
            echo "ERROR: No snapshot found under $CACHE_ROOT" >&2
            printf '{"status": "error", "message": "No snapshot found", "cache_root": "%s"}\n' "$CACHE_ROOT"
            exit 1
        fi

        echo "Restoring JS environment from $SNAPSHOT_DIR..." >&2
        for file in "$SNAPSHOT_DIR"/*; do
            fname=$(basename "$file")
            [ "$fname" = "manifest.txt" ] && continue
            cp "$file" "$PROJECT_PATH/" 2>/dev/null || true
            echo "  Restored: $fname" >&2
        done

        PM=$(detect_pm ".")
        echo "  Reinstall manually (we don't run install automatically to avoid lifecycle scripts):" >&2
        echo "    $(restore_command_hint "$PM")" >&2
        printf '{"status": "success", "restored_from": "%s", "pkg_manager": "%s", "reinstall_hint": "%s"}\n' \
            "$SNAPSHOT_DIR" "$PM" "$(restore_command_hint "$PM")"
        ;;

    clean)
        if [ -d "$CACHE_ROOT" ]; then
            rm -rf "$CACHE_ROOT"
            echo "✓ Cache cleaned: $CACHE_ROOT" >&2
            printf '{"status": "success", "action": "cleaned", "cache_root": "%s"}\n' "$CACHE_ROOT"
        else
            echo "No cache to clean at $CACHE_ROOT" >&2
            printf '{"status": "success", "action": "none"}\n'
        fi
        ;;

    locate)
        # Inform caller where snapshots live (useful for the LLM to mention in Phase 5)
        printf '{"cache_root": "%s", "latest": "%s"}\n' \
            "$CACHE_ROOT" \
            "$(readlink "$LATEST_LINK" 2>/dev/null || echo "")"
        ;;

    *)
        echo "Usage: bash snapshot_env_js.sh <project_path> save|restore|clean|locate" >&2
        printf '{"status": "error", "message": "Invalid action"}\n'
        exit 1
        ;;
esac
