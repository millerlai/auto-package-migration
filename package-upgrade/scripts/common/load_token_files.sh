#!/usr/bin/env bash
# load_token_files.sh - Safely load KEY=VALUE pairs from project-local
# .env.<service> token files into the environment.
#
# WHY NOT `source` / `.`:
#   Sourcing executes the file as shell. A token value such as
#       JFROG_TOKEN=abc$(rm -rf ~)def
#   would run the embedded command at load time. Token files can be
#   attacker-influenced — a value the user pasted, or an .env.<service> planted
#   in a shared / freshly-cloned repo (the loader trusts files purely by name).
#   So we parse KEY=VALUE textually and export the LITERAL value; we never
#   evaluate it. Bash variable expansion is not recursive, so any $(...) /
#   backticks inside the value are preserved verbatim, not executed.
#
# Usage (source this file, then call):
#   . "<scripts>/common/load_token_files.sh"
#   load_token_files <project_abs> <basename> [<basename> ...]
#
# Pairs with save_token.sh, which writes values single-quoted; this loader
# strips one surrounding pair of single/double quotes before exporting.
#
# D2: a key already non-empty in the environment wins over the file — a
# `VAR=value` prefix on the calling command (an unsaved session token) is
# never overwritten by a stale saved file sharing the same key.

# token_files_for <python|js|go> - the per-language .env.<service> basenames,
# in the same order preflight.sh / preflight_go.sh already load them. The one
# place this list lives, so preflight and with_tokens.sh cannot drift apart.
token_files_for() {
    case "$1" in
        python) echo ".env.pip .env.poetry .env.uv .env.pypi .env.jfrog" ;;
        js)     echo ".env.jfrog .env.npm .env.github" ;;
        go)     echo ".env.go .env.jfrog .env.github" ;;
        *)      return 2 ;;
    esac
}

load_token_files() {
    local project_abs="$1"; shift
    local name tok_file line key val
    for name in "$@"; do
        tok_file="$project_abs/$name"
        [ -f "$tok_file" ] || continue
        while IFS= read -r line || [ -n "$line" ]; do
            # tolerate CRLF token files (strip a trailing carriage return)
            line="${line%$'\r'}"
            # ltrim leading whitespace
            line="${line#"${line%%[![:space:]]*}"}"
            # skip blanks and comments
            case "$line" in '' | '#'*) continue ;; esac
            # allow an optional `export ` prefix
            line="${line#export }"
            # must be KEY=VALUE
            case "$line" in *=*) ;; *) continue ;; esac
            key="${line%%=*}"
            val="${line#*=}"
            # key must be a valid shell identifier — reject anything else so a
            # malformed line can never turn into an `export "FOO BAR=..."` error
            case "$key" in
                '' | *[!A-Za-z0-9_]* | [0-9]*) continue ;;
            esac
            # strip one surrounding pair of matching quotes (save_token.sh writes
            # single-quoted). No unescaping: values with embedded quotes are
            # rejected by save_token, so this round-trips cleanly.
            case "$val" in
                \'*\') val="${val#\'}"; val="${val%\'}" ;;
                \"*\") val="${val#\"}"; val="${val%\"}" ;;
            esac
            # D2: an already-set variable wins over the file.
            [ -n "${!key:-}" ] && continue
            export "$key=$val"
        done < "$tok_file"
        echo "(preflight) loaded $name" >&2
    done
}
