#!/usr/bin/env bash
set -euo pipefail

# verify_provenance.sh — deterministic Phase 3 provenance gate.
#
# Validates that a package-upgrade migration report actually contains the
# evidence that only running the Phase 3 tracks (Step 3.1 changelog,
# Step 3.2 git diff, Step 3.0 API surface diff) can produce. An agent that
# skipped Phase 3 and reasoned from memory has nothing to cite, so the
# markers below are absent and this script fails.
#
# LANGUAGE-AGNOSTIC BY DESIGN: it checks the standardized provenance markers
# that every language path (Python / JS / Go and any future language) emits
# in the Phase 7.1 report. There is no per-language branch here on purpose —
# new languages are covered automatically as long as they follow the report
# structure in templates/report_structure.md.
#
# Usage:   verify_provenance.sh <report.md>
# Output:  JSON summary to stdout.
# Exit:    0 = pass, 1 = provenance missing, 2 = usage / file error.

if [ $# -ne 1 ]; then
    echo "usage: verify_provenance.sh <report.md>" >&2
    exit 2
fi

REPORT="$1"
if [ ! -f "$REPORT" ]; then
    echo "error: report file not found: $REPORT" >&2
    exit 2
fi

# Legitimate skip: Step 4.0 zero_impact records a "Skipped Phases" section.
if grep -qiE 'skipped phases' "$REPORT" \
    && grep -qiE 'phase 3.*(skip|zero[_-]?impact|transitive)|zero[_-]?impact|purely transitive' "$REPORT"; then
    printf '{"pass":true,"report":%s,"skipped_phase3":true,"missing":[]}\n' "\"$REPORT\""
    exit 0
fi

missing=()

# --- Track 3.1: Changelog -------------------------------------------------
# Either a real changelog URL, or an explicit not-found marker.
if grep -qiE 'changelog' "$REPORT" \
    && grep -qiE 'changelog.*(https?://|not[_ ]?found|未找到|no changelog)' "$REPORT"; then
    has_changelog=true
else
    has_changelog=false
    missing+=("changelog (Step 3.1): no changelog URL nor explicit NOT_FOUND marker")
fi

# --- Track 3.2: Git diff --------------------------------------------------
# A compare URL, or >=2 commit SHAs, or an explicit degraded/fallback note.
sha_count=$( { grep -ioE '\b[0-9a-f]{12,40}\b' "$REPORT" || true; } | wc -l | tr -d ' ')
if grep -qiE '/compare/' "$REPORT" \
    || [ "${sha_count:-0}" -ge 2 ] \
    || grep -qiE 'git diff only|git[_ ]?tag.*fallback|diff.*degraded' "$REPORT"; then
    has_gitdiff=true
else
    has_gitdiff=false
    missing+=("git diff (Step 3.2): no compare URL, no commit SHAs, no degraded note")
fi

# --- Track 3.0: API surface diff ------------------------------------------
# The mandated "API Surface Diff 來源" section carries a confidence score,
# or an explicit none/degraded note when the tool was unavailable.
if grep -qiE 'confidence' "$REPORT" \
    || grep -qiE 'api surface.*(none|degraded|skipped|未|n/?a)' "$REPORT"; then
    has_apisurface=true
else
    has_apisurface=false
    missing+=("API surface (Step 3.0): no confidence_score nor explicit none/degraded note")
fi

# --- Breaking-change entries must cite their source -----------------------
# If the report lists breaking changes, each must carry a 來源/Source line.
bc_count=$(grep -cE '^#{2,4}.*(🔴|🟡|BC-[0-9]+)' "$REPORT" || true)
src_count=$(grep -ciE '來源|^- *source|sources?:' "$REPORT" || true)
if [ "${bc_count:-0}" -gt 0 ] && [ "${src_count:-0}" -eq 0 ]; then
    bc_sourced=false
    missing+=("breaking changes: $bc_count BC entries found but none carry a 來源/Source line")
else
    bc_sourced=true
fi

if [ ${#missing[@]} -eq 0 ]; then
    pass=true
else
    pass=false
fi

# Emit JSON (hand-built to avoid a jq dependency in the hook path).
missing_json="[]"
if [ ${#missing[@]} -gt 0 ]; then
    missing_json="["
    for i in "${!missing[@]}"; do
        esc=${missing[$i]//\\/\\\\}
        esc=${esc//\"/\\\"}
        [ "$i" -gt 0 ] && missing_json+=","
        missing_json+="\"$esc\""
    done
    missing_json+="]"
fi

printf '{"pass":%s,"report":"%s","skipped_phase3":false,"checks":{"changelog":%s,"git_diff":%s,"api_surface":%s,"bc_sourced":%s},"missing":%s}\n' \
    "$pass" "$REPORT" "$has_changelog" "$has_gitdiff" "$has_apisurface" "$bc_sourced" "$missing_json"

[ "$pass" = "true" ] && exit 0 || exit 1
