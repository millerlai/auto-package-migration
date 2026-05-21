#!/usr/bin/env bash
# dep_tree_go.sh - Thin shim that invokes dep_tree_go.py for the heavy lifting.
#
# Usage:
#   bash dep_tree_go.sh <project_path> <module_path> [--target-version <v>]
#
# Output: JSON aligned with dep_tree_js.js / dep_tree.py. See dep_tree_go.py
# for the full schema documentation.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$SCRIPT_DIR/dep_tree_go.py" "$@"
