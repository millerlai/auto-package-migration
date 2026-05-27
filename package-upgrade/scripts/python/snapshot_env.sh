#!/usr/bin/env bash
# snapshot_env.sh - Save and restore environment state
# Usage: bash snapshot_env.sh <project_path> save|restore
# Output: Status messages

set -euo pipefail

PROJECT_PATH="${1:-.}"
ACTION="${2:-save}"
SNAPSHOT_DIR="$PROJECT_PATH/.upgrade_snapshot"

cd "$PROJECT_PATH" || exit 1

case "$ACTION" in
    save)
        echo "Creating environment snapshot..." >&2
        mkdir -p "$SNAPSHOT_DIR"

        # Backup dependency files
        for pattern in requirements*.txt pyproject.toml poetry.lock uv.lock setup.py setup.cfg Pipfile Pipfile.lock; do
            if [ -f "$pattern" ]; then
                cp "$pattern" "$SNAPSHOT_DIR/" 2>/dev/null || true
                echo "  Backed up: $pattern" >&2
            fi
        done

        # Backup installed packages list
        if command -v pip &> /dev/null; then
            pip freeze > "$SNAPSHOT_DIR/pip_freeze.txt" 2>/dev/null || true
            echo "  Backed up: pip freeze output" >&2
        fi

        # Create manifest
        cat > "$SNAPSHOT_DIR/manifest.txt" <<EOF
Snapshot created: $(date)
Project path: $PROJECT_PATH
Files backed up:
$(ls -1 "$SNAPSHOT_DIR" 2>/dev/null | grep -v manifest.txt || echo "  (none)")
EOF

        echo "✓ Snapshot saved to $SNAPSHOT_DIR" >&2
        echo '{"status": "success", "snapshot_dir": "'"$SNAPSHOT_DIR"'"}'
        ;;

    restore)
        if [ ! -d "$SNAPSHOT_DIR" ]; then
            echo "ERROR: No snapshot found at $SNAPSHOT_DIR" >&2
            echo '{"status": "error", "message": "No snapshot found"}'
            exit 1
        fi

        echo "Restoring environment from snapshot..." >&2

        # Restore dependency files
        for file in "$SNAPSHOT_DIR"/*; do
            fname=$(basename "$file")
            if [ "$fname" = "pip_freeze.txt" ] || [ "$fname" = "manifest.txt" ]; then
                continue
            fi
            if [ -f "$file" ]; then
                cp "$file" "$PROJECT_PATH/" 2>/dev/null || true
                echo "  Restored: $fname" >&2
            fi
        done

        # Restore packages (if pip freeze was saved)
        if [ -f "$SNAPSHOT_DIR/pip_freeze.txt" ]; then
            echo "  Restoring packages from pip freeze..." >&2
            pip install -r "$SNAPSHOT_DIR/pip_freeze.txt" 2>&1 | head -10 >&2 || true
        fi

        echo "✓ Environment restored from $SNAPSHOT_DIR" >&2
        echo '{"status": "success", "restored_from": "'"$SNAPSHOT_DIR"'"}'
        ;;

    clean)
        if [ -d "$SNAPSHOT_DIR" ]; then
            rm -rf "$SNAPSHOT_DIR"
            echo "✓ Snapshot cleaned" >&2
            echo '{"status": "success", "action": "cleaned"}'
        else
            echo "No snapshot to clean" >&2
            echo '{"status": "success", "action": "none"}'
        fi
        ;;

    *)
        echo "Usage: bash snapshot_env.sh <project_path> save|restore|clean" >&2
        echo '{"status": "error", "message": "Invalid action"}'
        exit 1
        ;;
esac
