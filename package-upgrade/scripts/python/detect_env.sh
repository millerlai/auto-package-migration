#!/usr/bin/env bash
# detect_env.sh - Detect package manager and Python environment.
#
# Usage: bash detect_env.sh <project_path>
# Output: JSON with environment information consumed by preflight.sh and SKILL.md.
#
# Output schema (aligned with detect_env_js.sh / detect_env_go.sh where the
# concept maps cleanly; Python-only fields kept):
# {
#   "language": "python",
#   "pkg_manager": "pip" | "poetry" | "uv" | "unknown",
#   "pkg_manager_bin": "poetry" | "/usr/local/bin/poetry" | "" ,
#   "pkg_manager_version": "1.7.1" | "",
#   "python_version": "3.11.4",
#   "lockfile_path": "<path>" | "",
#   "pip_lock_file": "<path>" | "",          # Python-only (pip lock variants)
#   "has_pip_tools": true | false,           # Python-only
#   "dependency_files": ["pyproject.toml", ...],
#   "env_var_placeholders": ["JFROG_TOKEN", ...],
#   "custom_registries": [
#     {"name": "...", "registry": "https://...", "auth_env_var": "VAR",
#      "source_file": "pyproject.toml"},
#     ...
#   ],
#   "py_config_files": ["pyproject.toml", "pip.conf", ...],
#   "git_remote_host": "github.com" | "",
#   "git_remote_url": "git@github.com:...",
#   "memory_hints": ["private_registry", "poetry_source", "pip_extra_index",
#                    "non_default_remote", ...]
# }

set -euo pipefail

PROJECT_PATH="${1:-.}"
cd "$PROJECT_PATH" || exit 1

# ---------- Python interpreter version ----------

PYTHON_VERSION=$(python3 --version 2>/dev/null | grep -oP '\d+\.\d+\.\d+' || echo "unknown")

# ---------- Package manager + lockfile (existing logic) ----------

PKG_MANAGER="unknown"
LOCKFILE=""
PIP_LOCK_FILE=""
HAS_PIP_TOOLS="false"
DEP_FILES="[]"

# Detect package manager (priority: uv > poetry > pip)
if [ -f "uv.lock" ] || grep -q '\[tool\.uv\]' pyproject.toml 2>/dev/null; then
    PKG_MANAGER="uv"
    LOCKFILE="uv.lock"
elif [ -f "poetry.lock" ] || grep -q '\[tool\.poetry\]' pyproject.toml 2>/dev/null; then
    PKG_MANAGER="poetry"
    LOCKFILE="poetry.lock"
elif [ -f "requirements.txt" ] || [ -f "setup.py" ] || [ -f "setup.cfg" ] || [ -f "pyproject.toml" ]; then
    PKG_MANAGER="pip"

    # Detect pip lock file patterns
    # Priority: requirements.in (pip-tools) > requirements.lock > requirements.txt.lock
    if [ -f "requirements.in" ]; then
        HAS_PIP_TOOLS="true"
        LOCKFILE="requirements.txt"  # pip-tools uses .txt as lock
        PIP_LOCK_FILE="requirements.txt"
    elif [ -f "requirements.lock" ]; then
        LOCKFILE="requirements.txt"
        PIP_LOCK_FILE="requirements.lock"
    elif [ -f "requirements.txt.lock" ]; then
        LOCKFILE="requirements.txt"
        PIP_LOCK_FILE="requirements.txt.lock"
    elif [ -f "requirements-lock.txt" ]; then
        LOCKFILE="requirements.txt"
        PIP_LOCK_FILE="requirements-lock.txt"
    elif [ -f "requirements/production.lock" ]; then
        LOCKFILE="requirements.txt"
        PIP_LOCK_FILE="requirements/production.lock"
    elif [ -f "requirements.txt" ]; then
        LOCKFILE="requirements.txt"
        PIP_LOCK_FILE=""  # No separate lock file
    fi
fi

# Find dependency declaration files (exclude .venv, venv, node_modules)
DEP_FILES=$(find . -maxdepth 2 \( \
    -name "requirements*.txt" -o \
    -name "pyproject.toml" -o \
    -name "setup.py" -o \
    -name "setup.cfg" \
\) -not -path "./.venv/*" \
   -not -path "./venv/*" \
   -not -path "./node_modules/*" \
   -not -path "./.git/*" 2>/dev/null | \
   jq -R -s 'split("\n") | map(select(. != ""))')

# ---------- pkg_manager_bin (resolve absolute path) ----------

PKG_MANAGER_BIN=""
PKG_MANAGER_VERSION=""

case "$PKG_MANAGER" in
    poetry)
        if command -v poetry >/dev/null 2>&1; then
            PKG_MANAGER_BIN=$(command -v poetry)
            PKG_MANAGER_VERSION=$(poetry --version 2>/dev/null | grep -oP '\d+\.\d+\.\d+' | head -1 || echo "")
        fi
        ;;
    uv)
        if command -v uv >/dev/null 2>&1; then
            PKG_MANAGER_BIN=$(command -v uv)
            PKG_MANAGER_VERSION=$(uv --version 2>/dev/null | grep -oP '\d+\.\d+\.\d+' | head -1 || echo "")
        fi
        ;;
    pip)
        if command -v pip3 >/dev/null 2>&1; then
            PKG_MANAGER_BIN=$(command -v pip3)
            PKG_MANAGER_VERSION=$(pip3 --version 2>/dev/null | grep -oP 'pip \K\d+\.\d+(\.\d+)?' | head -1 || echo "")
        elif command -v pip >/dev/null 2>&1; then
            PKG_MANAGER_BIN=$(command -v pip)
            PKG_MANAGER_VERSION=$(pip --version 2>/dev/null | grep -oP 'pip \K\d+\.\d+(\.\d+)?' | head -1 || echo "")
        fi
        ;;
esac

# ---------- Collect Python config files ----------

PY_CONFIG_FILES_ARR=()
[ -f "pyproject.toml" ] && PY_CONFIG_FILES_ARR+=("pyproject.toml")
[ -f "pip.conf" ] && PY_CONFIG_FILES_ARR+=("pip.conf")
[ -f ".pip/pip.conf" ] && PY_CONFIG_FILES_ARR+=(".pip/pip.conf")
[ -f "setup.cfg" ] && PY_CONFIG_FILES_ARR+=("setup.cfg")

PY_CONFIG_FILES_JSON=$(printf '%s\n' "${PY_CONFIG_FILES_ARR[@]+"${PY_CONFIG_FILES_ARR[@]}"}" | \
    jq -R -s 'split("\n") | map(select(. != ""))' 2>/dev/null || echo "[]")

# ---------- env_var_placeholders: scan config files for ${VAR} / $VAR ----------

ENV_PLACEHOLDERS_RAW=""
if [ "${#PY_CONFIG_FILES_ARR[@]}" -gt 0 ]; then
    # Match ${VAR_NAME} and $VAR_NAME forms used by pip / poetry env interpolation.
    ENV_PLACEHOLDERS_RAW=$(grep -ohE '\$\{?[A-Z_][A-Z0-9_]*\}?' \
        "${PY_CONFIG_FILES_ARR[@]}" 2>/dev/null | \
        tr -d '${}' | sort -u || echo "")
fi

ENV_PLACEHOLDERS_JSON="[]"
if [ -n "$ENV_PLACEHOLDERS_RAW" ]; then
    ENV_PLACEHOLDERS_JSON=$(printf '%s\n' "$ENV_PLACEHOLDERS_RAW" | \
        jq -R . 2>/dev/null | jq -s . 2>/dev/null || echo "[]")
fi

# ---------- custom_registries: parse pyproject.toml + pip.conf ----------
#
# Scope this PR (per TODO 1.1 risk note): pyproject.toml [[tool.poetry.source]]
# and pip.conf [global] / [install] index-url + extra-index-url.
# ~/.pypirc and uv [[tool.uv.index]] will be added in a follow-up.

CUSTOM_REGISTRIES_JSON="[]"
if [ -f "pyproject.toml" ] || [ -f "pip.conf" ] || [ -f ".pip/pip.conf" ]; then
    CUSTOM_REGISTRIES_JSON=$(python3 - <<'PY' 2>/dev/null || echo "[]"
import json
import os
import re
import sys

try:
    # tomllib in 3.11+, fall back to tomli/toml if available.
    try:
        import tomllib  # type: ignore[import-not-found]
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[import-not-found]
        except ImportError:
            tomllib = None
except Exception:
    tomllib = None

out = []


def env_var_in(value):
    if not isinstance(value, str):
        return ""
    m = re.search(r"\$\{?([A-Z_][A-Z0-9_]*)\}?", value)
    return m.group(1) if m else ""


# --- pyproject.toml: [[tool.poetry.source]] ---
if os.path.isfile("pyproject.toml") and tomllib is not None:
    try:
        with open("pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        sources = data.get("tool", {}).get("poetry", {}).get("source", [])
        if isinstance(sources, list):
            for src in sources:
                if not isinstance(src, dict):
                    continue
                url = src.get("url", "")
                if not url:
                    continue
                out.append({
                    "name": src.get("name", ""),
                    "registry": url,
                    "auth_env_var": env_var_in(url),
                    "source_file": "pyproject.toml",
                })
    except Exception:
        pass

# --- pip.conf: [global] / [install] index-url + extra-index-url ---
for conf_path in ("pip.conf", ".pip/pip.conf"):
    if not os.path.isfile(conf_path):
        continue
    try:
        import configparser
        cp = configparser.ConfigParser()
        cp.read(conf_path)
        for section in cp.sections():
            for key in ("index-url", "extra-index-url"):
                if not cp.has_option(section, key):
                    continue
                raw = cp.get(section, key)
                # extra-index-url may be newline-separated multi-value
                for line in raw.splitlines():
                    url = line.strip()
                    if not url:
                        continue
                    out.append({
                        "name": f"{section}.{key}",
                        "registry": url,
                        "auth_env_var": env_var_in(url),
                        "source_file": conf_path,
                    })
    except Exception:
        pass

print(json.dumps(out))
PY
)
    [ -z "$CUSTOM_REGISTRIES_JSON" ] && CUSTOM_REGISTRIES_JSON="[]"
fi

# ---------- git remote ----------

GIT_REMOTE_URL=""
GIT_REMOTE_HOST=""
if [ -d ".git" ] || git rev-parse --git-dir >/dev/null 2>&1; then
    GIT_REMOTE_URL=$(git remote get-url origin 2>/dev/null || echo "")
    if [ -n "$GIT_REMOTE_URL" ]; then
        # Parse host from URL forms: git@host:..., ssh://git@host/..., https://host/...
        GIT_REMOTE_HOST=$(echo "$GIT_REMOTE_URL" | \
            sed -E 's,^(git@|ssh://git@|https?://)?([^/:]+).*,\2,')
    fi
fi

# ---------- memory_hints ----------

MEMORY_HINTS=()
HAS_POETRY_SOURCE="false"
HAS_PIP_EXTRA_INDEX="false"

if [ "$CUSTOM_REGISTRIES_JSON" != "[]" ]; then
    MEMORY_HINTS+=("\"private_registry\"")
    # Distinguish source type for downstream auth flow.
    if echo "$CUSTOM_REGISTRIES_JSON" | grep -q '"source_file": *"pyproject.toml"'; then
        HAS_POETRY_SOURCE="true"
        MEMORY_HINTS+=("\"poetry_source\"")
    fi
    if echo "$CUSTOM_REGISTRIES_JSON" | grep -q '"source_file": *"pip\.conf"\|"source_file": *"\.pip/pip\.conf"'; then
        HAS_PIP_EXTRA_INDEX="true"
        MEMORY_HINTS+=("\"pip_extra_index\"")
    fi
fi

[ "$HAS_PIP_TOOLS" = "true" ] && MEMORY_HINTS+=("\"pip_tools\"")

if [ -n "$GIT_REMOTE_HOST" ] && [ "$GIT_REMOTE_HOST" != "github.com" ] && \
   [ "$GIT_REMOTE_HOST" != "gitlab.com" ] && [ "$GIT_REMOTE_HOST" != "bitbucket.org" ]; then
    MEMORY_HINTS+=("\"non_default_remote\"")
fi

MEMORY_HINTS_JSON="[$(IFS=,; echo "${MEMORY_HINTS[*]+"${MEMORY_HINTS[*]}"}")]"

# ---------- Emit JSON ----------

cat <<EOF
{
  "language": "python",
  "pkg_manager": "$PKG_MANAGER",
  "pkg_manager_bin": $(printf '%s' "$PKG_MANAGER_BIN" | jq -Rs . 2>/dev/null || echo "\"\""),
  "pkg_manager_version": "$PKG_MANAGER_VERSION",
  "python_version": "$PYTHON_VERSION",
  "lockfile_path": "$LOCKFILE",
  "pip_lock_file": "$PIP_LOCK_FILE",
  "has_pip_tools": $HAS_PIP_TOOLS,
  "dependency_files": $DEP_FILES,
  "env_var_placeholders": $ENV_PLACEHOLDERS_JSON,
  "custom_registries": $CUSTOM_REGISTRIES_JSON,
  "py_config_files": $PY_CONFIG_FILES_JSON,
  "git_remote_host": "$GIT_REMOTE_HOST",
  "git_remote_url": $(printf '%s' "$GIT_REMOTE_URL" | jq -Rs . 2>/dev/null || echo "\"\""),
  "memory_hints": $MEMORY_HINTS_JSON
}
EOF
