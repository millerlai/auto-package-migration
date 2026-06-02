#!/usr/bin/env bash
# uninstall-cygwin64.sh - Remove the skill installed by install-cygwin64.sh.
#
# Mirrors install-cygwin64.sh: --global targets $USERPROFILE/.claude (the dir
# the Windows build of Claude Code reads), --project targets ./.claude.
#
# Usage: bash uninstall-cygwin64.sh [--global|--project] [--skip-permissions] [--yes]
#
# SAFETY: fingerprints the target before deleting so a same-named third-party
# skill is never removed (see is_our_skill).

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

MODE="global"
SKIP_PERMISSIONS="false"
ASSUME_YES="false"

for arg in "$@"; do
    case "$arg" in
        --project) MODE="project" ;;
        --global)  MODE="global"  ;;
        --skip-permissions) SKIP_PERMISSIONS="true" ;;
        --yes|-y) ASSUME_YES="true" ;;
        -h|--help)
            cat <<EOF
Usage: bash uninstall-cygwin64.sh [--global|--project] [--skip-permissions] [--yes]

Removes the two skills installed by install-cygwin64.sh:
  - package-upgrade
  - package-upgrade-feedback

  --global              Remove from \$USERPROFILE/.claude/skills/ (default)
  --project             Remove from ./.claude/skills/
  --skip-permissions    Don't touch settings.json
  --yes, -y             Non-interactive (also implied by CI). Implies
                        --skip-permissions.

Only directories that fingerprint as THIS skill are removed.
EOF
            exit 0
            ;;
    esac
done

if [ -n "${CI:-}" ] || [ "${PACKAGE_UPGRADE_ASSUME_YES:-}" = "1" ]; then
    ASSUME_YES="true"
fi
if [ "$ASSUME_YES" = "true" ]; then
    SKIP_PERMISSIONS="true"
fi

confirm() {
    if [ "$ASSUME_YES" = "true" ]; then
        echo "${1}[auto:${2}]"
        [ "$2" = "y" ]
        return
    fi
    local reply
    read -p "$1" -n 1 -r reply
    echo
    [[ $reply =~ ^[Yy]$ ]]
}

is_our_skill() {
    local skill="$1" dir="$2" got f
    [ -f "$dir/SKILL.md" ] || return 1
    got=$(awk -F': *' '/^name:/{print $2; exit}' "$dir/SKILL.md" | tr -d '[:space:]\r')
    [ "$got" = "$skill" ] || return 1
    local sigs=()
    case "$skill" in
        package-upgrade)
            sigs=(
                "scripts/common/save_token.sh"
                "scripts/common/provenance_stop_hook.py"
                "scripts/go/dep_tree.py"
            ) ;;
        package-upgrade-feedback)
            sigs=("scripts/sanitize_feedback.sh" "scripts/submit_feedback.sh") ;;
        *) return 1 ;;
    esac
    for f in "${sigs[@]}"; do
        [ -f "$dir/$f" ] || return 1
    done
    return 0
}

if [ -z "${USERPROFILE:-}" ]; then
    echo -e "${RED}錯誤: USERPROFILE 未設定,無法定位 Windows 版 Claude Code 的 .claude 目錄。${NC}"
    exit 1
fi
WIN_HOME_UNIX="$(cygpath -u "$USERPROFILE")"

# Best-effort python detection (only needed for the settings.json cleanup).
PY=""
for cmd in python3 python; do
    if command -v "$cmd" >/dev/null 2>&1 && \
       "$cmd" -c "import sys; sys.exit(0 if sys.version_info[0]==3 else 1)" 2>/dev/null; then
        PY="$cmd"; break
    fi
done
if [ -z "$PY" ] && command -v py >/dev/null 2>&1; then
    py -3 -c "import sys" 2>/dev/null && PY="py -3"
fi

echo -e "${BLUE}=========================================="
echo "Package Upgrade Skill 解除安裝 (Cygwin64)"
echo -e "==========================================${NC}"
echo ""

if [ "$MODE" = "global" ]; then
    SKILLS_ROOT="$WIN_HOME_UNIX/.claude/skills"
    SETTINGS_FILE="$WIN_HOME_UNIX/.claude/settings.json"
    echo -e "${GREEN}解除安裝模式: 全域 (Windows Claude Code 視角)${NC}"
else
    SKILLS_ROOT="./.claude/skills"
    SETTINGS_FILE="./.claude/settings.json"
    echo -e "${GREEN}解除安裝模式: 專案級${NC}"
fi
echo "位置: $SKILLS_ROOT"
echo ""

SKILLS=("package-upgrade" "package-upgrade-feedback")
REMOVED_ANY="false"

for skill in "${SKILLS[@]}"; do
    SKILL_DIR="$SKILLS_ROOT/$skill"
    if [ ! -d "$SKILL_DIR" ]; then
        echo -e "${YELLOW}• $skill: 未安裝,略過${NC}"
        continue
    fi
    if ! is_our_skill "$skill" "$SKILL_DIR"; then
        echo -e "${RED}⚠ $skill: $SKILL_DIR 看起來不是本專案安裝的 skill,略過不刪。${NC}"
        continue
    fi
    if confirm "移除 $skill ($SKILL_DIR)? (y/N) " y; then
        rm -rf "$SKILL_DIR"
        echo -e "${GREEN}✓ 已移除 $skill${NC}"
        REMOVED_ANY="true"
    else
        echo -e "${YELLOW}• $skill: 已略過${NC}"
    fi
done

echo ""
if [ "$SKIP_PERMISSIONS" = "true" ]; then
    echo -e "${YELLOW}已指定 --skip-permissions / 非互動模式,不修改 settings.json${NC}"
    if [ -n "$PY" ]; then
        echo "若要移除 provenance Stop hook,稍後執行:"
        echo "  $PY $(dirname "$0")/grant_permissions.py --settings $SETTINGS_FILE --mode $MODE --uninstall"
    fi
elif [ "$REMOVED_ANY" = "true" ]; then
    GRANT_SCRIPT="$(dirname "$0")/grant_permissions.py"
    if [ -n "$PY" ] && [ -f "$GRANT_SCRIPT" ] && [ -f "$SETTINGS_FILE" ]; then
        echo -e "${BLUE}清理 settings.json 中的 provenance Stop hook...${NC}"
        $PY "$GRANT_SCRIPT" --settings "$SETTINGS_FILE" --mode "$MODE" --uninstall || \
            echo -e "${YELLOW}⚠ Stop hook 清理失敗,請手動檢查 $SETTINGS_FILE${NC}"
    fi
fi

echo ""
echo -e "${GREEN}完成。${NC}"
