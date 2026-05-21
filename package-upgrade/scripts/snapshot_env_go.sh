#!/usr/bin/env bash
# snapshot_env_go.sh - Save and restore Go project state.
#
# Usage: bash snapshot_env_go.sh <project_path> save|restore|clean|locate
#
# Snapshots live OUTSIDE the repo at:
#   ~/.cache/package-upgrade/<repo-hash>/<timestamp>/
#
# Backs up: go.mod, go.sum, go.work, go.work.sum, vendor/modules.txt
# Intentionally DOES NOT back up vendor/ source files — restore tells the
# user to run `go mod vendor` to rebuild from go.mod.

set -euo pipefail

PROJECT_PATH="${1:-.}"
ACTION="${2:-save}"

PROJECT_PATH=$(cd "$PROJECT_PATH" && pwd -P)

REPO_HASH=$(printf '%s' "$PROJECT_PATH" | shasum 2>/dev/null | awk '{print $1}' | cut -c1-12)
[ -z "$REPO_HASH" ] && REPO_HASH=$(printf '%s' "$PROJECT_PATH" | md5 2>/dev/null | cut -c1-12)
[ -z "$REPO_HASH" ] && REPO_HASH="unknown"

CACHE_ROOT="${HOME}/.cache/package-upgrade/${REPO_HASH}"
LATEST_LINK="${CACHE_ROOT}/latest"

cd "$PROJECT_PATH" || exit 1

FILES_TO_BACKUP=(
    "go.mod"
    "go.sum"
    "go.work"
    "go.work.sum"
)

case "$ACTION" in
    save)
        TIMESTAMP=$(date +%Y%m%dT%H%M%S)
        SNAPSHOT_DIR="${CACHE_ROOT}/${TIMESTAMP}"
        mkdir -p "$SNAPSHOT_DIR"

        echo "Creating Go environment snapshot..." >&2
        echo "  Location: $SNAPSHOT_DIR" >&2

        for pattern in "${FILES_TO_BACKUP[@]}"; do
            if [ -f "$pattern" ]; then
                cp "$pattern" "$SNAPSHOT_DIR/" 2>/dev/null || true
                echo "  Backed up: $pattern" >&2
            fi
        done

        # vendor/modules.txt only (we re-vendor on restore via `go mod vendor`)
        if [ -f "vendor/modules.txt" ]; then
            mkdir -p "$SNAPSHOT_DIR/vendor"
            cp "vendor/modules.txt" "$SNAPSHOT_DIR/vendor/modules.txt" 2>/dev/null || true
            echo "  Backed up: vendor/modules.txt (vendor/ source files NOT backed up — rerun 'go mod vendor' on restore)" >&2
        fi

        VENDORED="false"
        [ -f "vendor/modules.txt" ] && VENDORED="true"

        cat > "$SNAPSHOT_DIR/manifest.txt" <<EOF
Snapshot created: $(date)
Project path:     $PROJECT_PATH
Repo hash:        $REPO_HASH
Vendored:         $VENDORED
Files backed up:
$(ls -1 "$SNAPSHOT_DIR" 2>/dev/null | grep -v manifest.txt || echo "  (none)")

Restore command:
  bash snapshot_env_go.sh $PROJECT_PATH restore

After restore, if vendored, run:
  go mod vendor
EOF

        ln -snf "$SNAPSHOT_DIR" "$LATEST_LINK" 2>/dev/null || true

        echo "✓ Snapshot saved to $SNAPSHOT_DIR" >&2
        printf '{"status": "success", "snapshot_dir": "%s", "vendored": %s}\n' \
            "$SNAPSHOT_DIR" "$VENDORED"
        ;;

    restore)
        SNAPSHOT_DIR=""
        if [ -L "$LATEST_LINK" ] && [ -d "$LATEST_LINK" ]; then
            SNAPSHOT_DIR=$(readlink "$LATEST_LINK")
            [ "${SNAPSHOT_DIR#/}" = "$SNAPSHOT_DIR" ] && SNAPSHOT_DIR="${CACHE_ROOT}/${SNAPSHOT_DIR}"
        elif [ -d "$CACHE_ROOT" ]; then
            SNAPSHOT_DIR=$(ls -1d "$CACHE_ROOT"/*/ 2>/dev/null | grep -v '/latest/$' | sort | tail -1 | sed 's:/$::')
        fi

        if [ -z "$SNAPSHOT_DIR" ] || [ ! -d "$SNAPSHOT_DIR" ]; then
            echo "ERROR: No snapshot found under $CACHE_ROOT" >&2
            printf '{"status": "error", "message": "No snapshot found", "cache_root": "%s"}\n' "$CACHE_ROOT"
            exit 1
        fi

        echo "Restoring Go environment from $SNAPSHOT_DIR..." >&2
        for file in "$SNAPSHOT_DIR"/*; do
            fname=$(basename "$file")
            case "$fname" in
                manifest.txt) continue ;;
                vendor) continue ;;  # handled below
            esac
            cp "$file" "$PROJECT_PATH/" 2>/dev/null || true
            echo "  Restored: $fname" >&2
        done

        REVENDOR_HINT=""
        if [ -f "$SNAPSHOT_DIR/vendor/modules.txt" ]; then
            mkdir -p "$PROJECT_PATH/vendor"
            cp "$SNAPSHOT_DIR/vendor/modules.txt" "$PROJECT_PATH/vendor/modules.txt"
            echo "  Restored: vendor/modules.txt" >&2
            echo "  ⚠️  vendor/ source files were NOT backed up. Run 'go mod vendor' to repopulate." >&2
            REVENDOR_HINT="go mod vendor"
        fi

        printf '{"status": "success", "restored_from": "%s", "revendor_hint": "%s"}\n' \
            "$SNAPSHOT_DIR" "$REVENDOR_HINT"
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
        printf '{"cache_root": "%s", "latest": "%s"}\n' \
            "$CACHE_ROOT" \
            "$(readlink "$LATEST_LINK" 2>/dev/null || echo "")"
        ;;

    *)
        echo "Usage: bash snapshot_env_go.sh <project_path> save|restore|clean|locate" >&2
        printf '{"status": "error", "message": "Invalid action"}\n'
        exit 1
        ;;
esac
