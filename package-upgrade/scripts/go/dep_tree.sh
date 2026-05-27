#!/usr/bin/env bash
# dep_tree.sh - Thin shim that invokes dep_tree.py for the heavy lifting.
#
# Usage:
#   bash dep_tree.sh <project_path> <module_path> [--target-version <v>]
#
# Output: JSON aligned with ../javascript/dep_tree.js / ../python/dep_tree.py.
# See dep_tree.py for the full schema documentation.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$SCRIPT_DIR/dep_tree.py" "$@"
