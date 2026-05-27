#!/usr/bin/env bash
# api_surface_diff_py.sh - Diff a Python package's exported API between two
# versions using griffe.
#
# Usage:
#   bash api_surface_diff_py.sh <package_name> <old_version> <new_version>
#
# Strategy:
#   1. `pip install --target` each version into a temp dir (no deps).
#   2. Load both with griffe to get the API tree.
#   3. Walk both trees → flat {path: signature} dicts.
#   4. Diff to produce removed / added / changed / deprecated_new.
#
# Why confidence_score is 0.65 (vs Go's 0.9):
#   Python is dynamic — `.pyi` stubs are optional, type hints incomplete on
#   older packages, metaclasses / __getattr__ can produce attributes that
#   griffe can't see statically. We surface what's structurally provable,
#   the LLM still needs to cross-check against changelog + git diff.
#
# Output: JSON aligned with api_surface_diff_go.sh / api_surface_diff_js.js
#   {
#     "package_name": "requests",
#     "old_version": "2.28.0",
#     "new_version": "2.32.0",
#     "strategy": "griffe" | "none",
#     "old_source_label": "pip install --target: requests-2.28.0",
#     "new_source_label": "...",
#     "confidence_score": 0.65,
#     "removed": [{"name": "...", "kind": "function|class|attribute"}],
#     "added":   [...],
#     "changed": [{"name": "...", "old_signature": "...", "new_signature": "...",
#                  "category": "signature_change" | "kind_change" |
#                              "type_change" | "incompatible_other"}],
#     "deprecated_new": [{"name": "...", "via": "docstring|decorator"}],
#     "warnings": [...],
#     "errors": [...]
#   }

set -euo pipefail

PKG_NAME="${1:-}"
OLD_VER="${2:-}"
NEW_VER="${3:-}"

if [ -z "$PKG_NAME" ] || [ -z "$OLD_VER" ] || [ -z "$NEW_VER" ]; then
    echo "Usage: bash api_surface_diff_py.sh <package_name> <old_version> <new_version>" >&2
    exit 1
fi

declare -a WARNS=()
declare -a ERRS=()

emit_empty() {
    local strategy="$1"
    local warns_json errs_json
    if [ "${#WARNS[@]}" -gt 0 ]; then
        warns_json=$(printf '%s\n' "${WARNS[@]}" | jq -R -s 'split("\n") | map(select(. != ""))')
    else
        warns_json="[]"
    fi
    if [ "${#ERRS[@]}" -gt 0 ]; then
        errs_json=$(printf '%s\n' "${ERRS[@]}" | jq -R -s 'split("\n") | map(select(. != ""))')
    else
        errs_json="[]"
    fi
    cat <<EOF
{
  "package_name": "$PKG_NAME",
  "old_version": "$OLD_VER",
  "new_version": "$NEW_VER",
  "strategy": "$strategy",
  "old_source_label": "",
  "new_source_label": "",
  "confidence_score": 0.0,
  "removed": [],
  "added": [],
  "changed": [],
  "deprecated_new": [],
  "warnings": $warns_json,
  "errors": $errs_json
}
EOF
}

# ---------- tool availability ----------

if ! command -v python3 >/dev/null 2>&1; then
    ERRS+=("python3 not in PATH")
    emit_empty "none"
    exit 1
fi

if ! python3 -c "import griffe" >/dev/null 2>&1; then
    WARNS+=("griffe not installed -- install: pip install griffe. Falling back to no-API-diff strategy.")
    emit_empty "none"
    exit 0
fi

# We need SOME way to install a package into a target dir. Prefer `uv pip`
# (works on uv-managed venvs that don't bundle pip) and fall back to plain
# `python3 -m pip`.
INSTALLER=""
if command -v uv >/dev/null 2>&1; then
    INSTALLER="uv"
elif python3 -m pip --version >/dev/null 2>&1; then
    INSTALLER="pip"
else
    ERRS+=("neither uv nor python3 -m pip is available -- cannot install package versions into temp dirs")
    emit_empty "none"
    exit 1
fi

# ---------- install both versions into temp dirs ----------

TMP_ROOT=$(mktemp -d)
OLD_DIR="$TMP_ROOT/old"
NEW_DIR="$TMP_ROOT/new"
mkdir -p "$OLD_DIR" "$NEW_DIR"
trap 'rm -rf "$TMP_ROOT"' EXIT

install_pkg() {
    local target_dir="$1" version="$2"
    # --no-deps: just the target package; we don't need transitive deps to
    # read the API surface. --target: dedicated dir, no site-packages
    # pollution. --quiet: suppress download chatter (real errors still go
    # to stderr).
    if [ "$INSTALLER" = "uv" ]; then
        uv pip install --target "$target_dir" --no-deps --quiet \
            "${PKG_NAME}==${version}" 2>/dev/null
    else
        python3 -m pip install --no-deps --quiet --target "$target_dir" \
            "${PKG_NAME}==${version}" 2>/dev/null
    fi
}

if ! install_pkg "$OLD_DIR" "$OLD_VER"; then
    ERRS+=("pip install ${PKG_NAME}==${OLD_VER} failed (network / yanked / wrong name)")
    emit_empty "none"
    exit 1
fi
if ! install_pkg "$NEW_DIR" "$NEW_VER"; then
    ERRS+=("pip install ${PKG_NAME}==${NEW_VER} failed (network / yanked / wrong name)")
    emit_empty "none"
    exit 1
fi

# ---------- griffe load + diff ----------

WARNS_JSON="[]"
ERRS_JSON="[]"
if [ "${#WARNS[@]}" -gt 0 ]; then
    WARNS_JSON=$(printf '%s\n' "${WARNS[@]}" | jq -R -s 'split("\n") | map(select(. != ""))')
fi
if [ "${#ERRS[@]}" -gt 0 ]; then
    ERRS_JSON=$(printf '%s\n' "${ERRS[@]}" | jq -R -s 'split("\n") | map(select(. != ""))')
fi

SD_PKG_NAME="$PKG_NAME" \
SD_OLD_VER="$OLD_VER" \
SD_NEW_VER="$NEW_VER" \
SD_OLD_DIR="$OLD_DIR" \
SD_NEW_DIR="$NEW_DIR" \
SD_WARNS_JSON="$WARNS_JSON" \
SD_ERRS_JSON="$ERRS_JSON" \
python3 <<'PY'
import json
import os
import sys

pkg_name = os.environ["SD_PKG_NAME"]
old_ver  = os.environ["SD_OLD_VER"]
new_ver  = os.environ["SD_NEW_VER"]
old_dir  = os.environ["SD_OLD_DIR"]
new_dir  = os.environ["SD_NEW_DIR"]
warns    = json.loads(os.environ.get("SD_WARNS_JSON", "[]"))
errs     = json.loads(os.environ.get("SD_ERRS_JSON", "[]"))

import griffe


def load_tree(search_dir, label):
    """Load `pkg_name` with griffe, rooted at `search_dir`."""
    try:
        return griffe.load(pkg_name, search_paths=[search_dir])
    except Exception as e:
        errs.append(f"griffe.load failed for {label} ({pkg_name}): "
                    f"{type(e).__name__}: {e}")
        return None


def _kind_str(obj):
    k = getattr(obj, "kind", None)
    if k is None:
        return "unknown"
    s = str(k)
    return s.split(".")[-1].lower() if "." in s else s.lower()


def _is_private(name):
    # PEP 8: leading underscore = private. Dunder names (__init__ etc.) are
    # public-ish; we keep them because subclasses care about overriding them.
    if name.startswith("__") and name.endswith("__"):
        return False
    return name.startswith("_")


def _safe_get_parameters(obj):
    """Return parameters list or None. griffe raises AliasResolutionError on
    aliases pointing into modules we didn't load (e.g. stdlib re-exports);
    swallow those — they're not API surface of THIS package."""
    try:
        return obj.parameters if hasattr(obj, "parameters") else None
    except Exception:
        return None


def _safe_get_returns(obj):
    try:
        return obj.returns if hasattr(obj, "returns") else None
    except Exception:
        return None


def _safe_get_annotation(obj):
    try:
        return obj.annotation if hasattr(obj, "annotation") else None
    except Exception:
        return None


def signature_of(obj):
    """Produce a stable string for diffing. Format depends on kind."""
    kind = _kind_str(obj)
    if kind == "function":
        params = _safe_get_parameters(obj) or []
        parts = []
        for p in params:
            s = p.name
            ann = getattr(p, "annotation", None)
            if ann is not None:
                s += f": {ann}"
            default = getattr(p, "default", None)
            if default is not None:
                s += f" = {default}"
            parts.append(s)
        ret = _safe_get_returns(obj)
        sig = "(" + ", ".join(parts) + ")"
        if ret is not None:
            sig += f" -> {ret}"
        return sig
    if kind == "class":
        bases = getattr(obj, "bases", None) or []
        return "class(" + ", ".join(str(b) for b in bases) + ")"
    if kind == "attribute":
        ann = _safe_get_annotation(obj)
        return f": {ann}" if ann is not None else ""
    if kind == "module":
        return "module"
    return kind


def is_deprecated(obj):
    """Detect `@deprecated` decorator or '.. deprecated::' docstring marker.
    Returns ('decorator' | 'docstring' | '')."""
    decos = getattr(obj, "decorators", None) or []
    for d in decos:
        ds = str(getattr(d, "callable_path", d) or "")
        if "deprecat" in ds.lower():
            return "decorator"
    doc = getattr(obj, "docstring", None)
    if doc and getattr(doc, "value", None):
        text = doc.value.lower()
        if ".. deprecated::" in text or "deprecated since" in text:
            return "docstring"
    return ""


def walk(obj, prefix=""):
    """Yield (path, kind, signature, deprecation_marker) for each public symbol."""
    name = getattr(obj, "name", "") or ""
    if prefix:
        path = f"{prefix}.{name}" if name else prefix
    else:
        path = name
    kind = _kind_str(obj)

    if kind == "alias":
        # Re-exports — don't dive into them (they may point at other packages),
        # but DO record the alias path itself as part of the surface.
        if name and not _is_private(name):
            yield (path, "alias", "alias", "")
        return

    if name and _is_private(name):
        return

    if kind in ("function", "class", "attribute"):
        yield (path, kind, signature_of(obj), is_deprecated(obj))

    members = getattr(obj, "members", None) or {}
    if kind == "module" and not name:
        # Root module case — already handled above with empty name
        pass
    elif kind == "module":
        yield (path, "module", "module", is_deprecated(obj))

    for child_name, child in members.items():
        try:
            yield from walk(child, path)
        except Exception as e:
            errs.append(f"walk failed at {path}.{child_name}: "
                        f"{type(e).__name__}: {e}")


old_tree = load_tree(old_dir, f"{pkg_name}@{old_ver}")
new_tree = load_tree(new_dir, f"{pkg_name}@{new_ver}")

if old_tree is None or new_tree is None:
    # Already recorded errors; emit empty diff with strategy=none.
    print(json.dumps({
        "package_name": pkg_name,
        "old_version": old_ver,
        "new_version": new_ver,
        "strategy": "none",
        "old_source_label": f"pip install --target: {pkg_name}-{old_ver}",
        "new_source_label": f"pip install --target: {pkg_name}-{new_ver}",
        "confidence_score": 0.0,
        "removed": [],
        "added": [],
        "changed": [],
        "deprecated_new": [],
        "warnings": warns,
        "errors": errs,
    }, indent=2))
    sys.exit(0)

old_map = {}
new_map = {}
old_deprecated = {}
new_deprecated = {}

for path, kind, sig, dep in walk(old_tree):
    old_map[path] = (kind, sig)
    if dep:
        old_deprecated[path] = dep
for path, kind, sig, dep in walk(new_tree):
    new_map[path] = (kind, sig)
    if dep:
        new_deprecated[path] = dep

removed = []
added = []
changed = []

for path, (kind, sig) in old_map.items():
    if path not in new_map:
        removed.append({"name": path, "kind": kind})
    else:
        new_kind, new_sig = new_map[path]
        if kind != new_kind:
            changed.append({
                "name": path,
                "old_signature": f"[{kind}] {sig}",
                "new_signature": f"[{new_kind}] {new_sig}",
                "category": "kind_change",
            })
        elif sig != new_sig:
            if kind == "function":
                category = "signature_change"
            elif kind == "attribute":
                category = "type_change"
            else:
                category = "incompatible_other"
            changed.append({
                "name": path,
                "old_signature": sig,
                "new_signature": new_sig,
                "category": category,
            })

for path, (kind, _) in new_map.items():
    if path not in old_map:
        added.append({"name": path, "kind": kind})

deprecated_new = []
for path, via in new_deprecated.items():
    if path not in old_deprecated:
        deprecated_new.append({"name": path, "via": via})

# Cap each list at 200 entries to keep output digestible. The LLM's job is
# to surface the high-signal changes, not paginate a 5000-entry dump.
def cap(lst, n=200):
    return lst[:n] + ([{"_truncated": True, "_omitted_count": len(lst) - n}]
                      if len(lst) > n else [])

# Confidence: both trees loaded successfully and the diff produced data;
# floor at 0.65 (vs Go apidiff's 0.9) to remind callers Python is dynamic.
# Schema aligned with api_surface_diff_js.js + api_surface_diff_go.sh:
# always emit confidence_score + confidence_basis.
if errs:
    confidence = 0.5
    confidence_basis = (
        "errors during griffe enumeration; surface may be incomplete"
    )
else:
    confidence = 0.65
    confidence_basis = (
        "griffe static enumeration; Python's dynamic introspection means "
        "runtime-only exports (e.g. via __getattr__) may be missed"
    )

print(json.dumps({
    "package_name": pkg_name,
    "old_version": old_ver,
    "new_version": new_ver,
    "strategy": "griffe",
    "old_source_label": f"pip install --target: {pkg_name}-{old_ver}",
    "new_source_label": f"pip install --target: {pkg_name}-{new_ver}",
    "confidence_score": confidence,
    "confidence_basis": confidence_basis,
    "removed": cap(removed),
    "added": cap(added),
    "changed": cap(changed),
    "deprecated_new": cap(deprecated_new),
    "warnings": warns,
    "errors": errs,
}, indent=2))
PY
