#!/usr/bin/env bash
# uninstall.sh - Remove the Package Upgrade Skill installed by install.sh.
# Usage: bash uninstall.sh [--global|--project] [--skip-permissions] [--yes]
#
# SAFETY: a directory named `package-upgrade` under ~/.claude/skills could be a
# DIFFERENT skill that merely shares the name. Before deleting anything we
# fingerprint the target (SKILL.md `name:` + signature helper files that only
# OUR skill ships). If it doesn't match, we refuse to delete it and say so.

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
Usage: bash uninstall.sh [--global|--project] [--skip-permissions] [--yes]

Removes the two skills installed by install.sh:
  - package-upgrade
  - package-upgrade-feedback

  --global              Remove from ~/.claude/skills/ (default)
  --project             Remove from ./.claude/skills/
  --skip-permissions    Don't touch settings.json (leave the Stop hook in place)
  --yes, -y             Non-interactive: assume yes to removal prompts
                        (also implied by CI or PACKAGE_UPGRADE_ASSUME_YES=1).
                        Implies --skip-permissions to avoid unattended writes to
                        settings.json.

Only directories that fingerprint as THIS skill are removed; a same-named
skill from somewhere else is left untouched.
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

# is_our_skill <skill-name> <dir> -> 0 if the dir is the skill WE installed.
# Checks the SKILL.md frontmatter name and a set of signature files that a
# coincidentally same-named third-party skill is very unlikely to all ship.
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

echo -e "${BLUE}=========================================="
echo "Package Upgrade Skill 解除安裝程式"
echo -e "==========================================${NC}"
echo ""

if [ "$MODE" = "global" ]; then
    SKILLS_ROOT="$HOME/.claude/skills"
    SETTINGS_FILE="$HOME/.claude/settings.json"
    echo -e "${GREEN}解除安裝模式: 全域${NC}"
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
        echo -e "${RED}⚠ $skill: $SKILL_DIR 看起來不是本專案安裝的 skill${NC}"
        echo "  (SKILL.md name 不符,或缺少我們的 signature 檔案)"
        echo -e "  ${YELLOW}為避免誤刪同名的其他 skill,略過不刪。${NC}"
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

# Remove the provenance Stop hook we wrote — it points at a now-deleted script,
# so leaving it would make every Stop fail. Permissions allow/ask entries are
# intentionally left (they may be shared with other tools); remove by hand if
# desired. --skip-permissions leaves settings.json completely untouched.
echo ""
if [ "$SKIP_PERMISSIONS" = "true" ]; then
    echo -e "${YELLOW}已指定 --skip-permissions / 非互動模式,不修改 settings.json${NC}"
    echo "若要移除 provenance Stop hook,稍後執行:"
    echo "  python3 $(dirname "$0")/grant_permissions.py --settings $SETTINGS_FILE --mode $MODE --uninstall"
elif [ "$REMOVED_ANY" = "true" ]; then
    GRANT_SCRIPT="$(dirname "$0")/grant_permissions.py"
    if [ -f "$GRANT_SCRIPT" ] && [ -f "$SETTINGS_FILE" ]; then
        echo -e "${BLUE}清理 settings.json 中的 provenance Stop hook...${NC}"
        python3 "$GRANT_SCRIPT" --settings "$SETTINGS_FILE" --mode "$MODE" --uninstall || \
            echo -e "${YELLOW}⚠ Stop hook 清理失敗,請手動檢查 $SETTINGS_FILE${NC}"
    fi
fi

echo ""
echo -e "${GREEN}完成。${NC}"
