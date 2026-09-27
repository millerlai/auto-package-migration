#!/usr/bin/env bash
# with_tokens.sh - Run a command with this project's saved registry tokens
# loaded into its environment.
#
# Usage: bash with_tokens.sh <project_path> <python|js|go> -- <command...>
#
# WHY: each Bash tool call is a fresh shell, so an `export` from an earlier
# call (e.g. inside preflight.sh) is gone by the time a later command runs
# (platform docs: "An export in one command won't be available in the
# next."). Route every command that talks to a private registry through this
# wrapper instead of relying on that export to still be in effect.
#
# A token the user declined to persist has no file to load; pass it as a
# `VAR=value` prefix on the same command line instead — an already-set
# variable wins over a loaded file (D2), so the prefix still takes effect.

set -euo pipefail

usage() {
    echo "Usage: $0 <project_path> <python|js|go> -- <command...>" >&2
    exit 2
}

[ $# -ge 4 ] || usage
PROJECT_PATH="$1"
LANG_ARG="$2"
[ "$3" = "--" ] || usage
shift 3

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=./load_token_files.sh
. "$SCRIPT_DIR/load_token_files.sh"

FILES=$(token_files_for "$LANG_ARG") || usage

PROJECT_ABS=$(cd "$PROJECT_PATH" && pwd -P)
# shellcheck disable=SC2086 # FILES is a fixed, space-separated list of basenames
load_token_files "$PROJECT_ABS" $FILES

exec "$@"
