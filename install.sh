#!/usr/bin/env bash
# install.sh - 快速安裝 Package Upgrade Skill
# Usage: bash install.sh [--global|--project]

set -euo pipefail

# 顏色輸出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 預設安裝模式
MODE="global"
SKIP_PERMISSIONS="false"

# 解析參數
for arg in "$@"; do
    case "$arg" in
        --project) MODE="project" ;;
        --global)  MODE="global"  ;;
        --skip-permissions) SKIP_PERMISSIONS="true" ;;
        -h|--help)
            cat <<EOF
Usage: bash install.sh [--global|--project] [--skip-permissions]

  --global              Install to ~/.claude/skills/package-upgrade (default)
  --project             Install to ./.claude/skills/package-upgrade
  --skip-permissions    Don't offer to write the recommended Claude Code
                        permissions into settings.json
EOF
            exit 0
            ;;
    esac
done

echo -e "${BLUE}=========================================="
echo "Package Upgrade Skill 安裝程式"
echo -e "==========================================${NC}"
echo ""

# 檢查是否在專案根目錄
if [ ! -d "package-upgrade" ]; then
    echo -e "${RED}錯誤: 請在專案根目錄執行此腳本${NC}"
    echo "目前路徑: $(pwd)"
    echo "預期看到: package-upgrade/ 目錄"
    exit 1
fi

# 安裝目標
if [ "$MODE" = "global" ]; then
    TARGET_DIR="$HOME/.claude/skills/package-upgrade"
    echo -e "${GREEN}安裝模式: 全域安裝${NC}"
    echo "安裝位置: $TARGET_DIR"
else
    TARGET_DIR="./.claude/skills/package-upgrade"
    echo -e "${GREEN}安裝模式: 專案級安裝${NC}"
    echo "安裝位置: $TARGET_DIR"
fi

echo ""
read -p "繼續安裝? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "安裝已取消"
    exit 0
fi

# 建立目標目錄
echo ""
echo -e "${BLUE}步驟 1/6: 建立目錄${NC}"
mkdir -p "$(dirname "$TARGET_DIR")"

if [ -d "$TARGET_DIR" ]; then
    echo -e "${YELLOW}警告: 目標目錄已存在,將會覆蓋${NC}"
    read -p "確定要覆蓋嗎? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "安裝已取消"
        exit 0
    fi
    rm -rf "$TARGET_DIR"
fi

# 複製檔案
echo ""
echo -e "${BLUE}步驟 2/6: 複製檔案${NC}"
cp -r package-upgrade "$TARGET_DIR"
echo -e "${GREEN}✓ 檔案已複製${NC}"

# 設定執行權限
echo ""
echo -e "${BLUE}步驟 3/6: 設定執行權限${NC}"
chmod +x "$TARGET_DIR"/scripts/*.sh
chmod +x "$TARGET_DIR"/scripts/*.py
echo -e "${GREEN}✓ 執行權限已設定${NC}"

# 檢查並安裝 Python 依賴
echo ""
echo -e "${BLUE}步驟 4/6: 檢查 Python 依賴${NC}"

MISSING_DEPS=()

if ! python3 -c "import pipdeptree" 2>/dev/null; then
    MISSING_DEPS+=("pipdeptree")
fi

if ! python3 -c "import requests" 2>/dev/null; then
    MISSING_DEPS+=("requests")
fi

if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
    echo -e "${YELLOW}缺少依賴: ${MISSING_DEPS[*]}${NC}"
    read -p "是否安裝? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        pip install "${MISSING_DEPS[@]}"
        echo -e "${GREEN}✓ 依賴已安裝${NC}"
    else
        echo -e "${YELLOW}⚠ 跳過依賴安裝,稍後請手動執行:${NC}"
        echo "  pip install ${MISSING_DEPS[*]}"
    fi
else
    echo -e "${GREEN}✓ 所有依賴已安裝${NC}"
fi

# 檢查系統工具
echo ""
echo -e "${BLUE}步驟 5/6: 檢查系統工具${NC}"

MISSING_TOOLS=()

if ! command -v jq &> /dev/null; then
    MISSING_TOOLS+=("jq")
fi

if ! command -v git &> /dev/null; then
    MISSING_TOOLS+=("git")
fi

if [ ${#MISSING_TOOLS[@]} -gt 0 ]; then
    echo -e "${YELLOW}⚠ 缺少系統工具: ${MISSING_TOOLS[*]}${NC}"
    echo ""
    echo "安裝建議:"
    for tool in "${MISSING_TOOLS[@]}"; do
        case $tool in
            jq)
                echo "  jq:"
                echo "    macOS: brew install jq"
                echo "    Ubuntu/Debian: sudo apt-get install jq"
                ;;
            git)
                echo "  git:"
                echo "    macOS: xcode-select --install"
                echo "    Ubuntu/Debian: sudo apt-get install git"
                ;;
        esac
    done
else
    echo -e "${GREEN}✓ 所有系統工具已安裝${NC}"
fi

# 設定 Claude Code 權限
echo ""
echo -e "${BLUE}步驟 6/6: 設定 Claude Code 權限${NC}"

if [ "$MODE" = "global" ]; then
    SETTINGS_FILE="$HOME/.claude/settings.json"
else
    SETTINGS_FILE="./.claude/settings.json"
fi

GRANT_SCRIPT="$(dirname "$0")/grant_permissions.py"
if [ ! -f "$GRANT_SCRIPT" ]; then
    echo -e "${YELLOW}⚠ 找不到 grant_permissions.py,跳過權限設定${NC}"
elif [ "$SKIP_PERMISSIONS" = "true" ]; then
    echo -e "${YELLOW}已指定 --skip-permissions,跳過權限設定${NC}"
    echo "若要稍後手動套用,執行:"
    echo "  python3 $GRANT_SCRIPT --settings $SETTINGS_FILE --mode $MODE"
else
    echo ""
    echo "Skill 執行時會用到以下類型的權限:"
    echo "  - Bash: skill 內建 scripts、git status/diff/log、poetry/pip/uv 套件操作、grep、docker ps"
    echo "  - WebFetch: pypi.org、github.com、raw.githubusercontent.com、api.github.com"
    echo "  - WebSearch (用於查詢 CVE / changelog)"
    echo "  - MCP (Jira): getJiraIssue、getTransitionsForJiraIssue、getAccessibleAtlassianResources"
    echo ""
    echo "下列動作會放入 'ask' 清單,執行前仍會提示確認:"
    echo "  - git push、git commit (非 -m 形式)"
    echo "  - 對 Jira 寫入留言 / 轉狀態"
    echo ""
    echo "預覽 (dry-run) 將要寫入 $SETTINGS_FILE 的變更..."
    echo ""
    if python3 "$GRANT_SCRIPT" --settings "$SETTINGS_FILE" --mode "$MODE" --dry-run; then
        echo ""
        read -p "套用這些權限? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            python3 "$GRANT_SCRIPT" --settings "$SETTINGS_FILE" --mode "$MODE"
            echo -e "${GREEN}✓ 權限已寫入 $SETTINGS_FILE${NC}"
        else
            echo -e "${YELLOW}已跳過,可日後執行:${NC}"
            echo "  python3 $GRANT_SCRIPT --settings $SETTINGS_FILE --mode $MODE"
        fi
    else
        echo -e "${RED}✗ 權限預覽失敗,請檢查 $SETTINGS_FILE 是否為合法 JSON${NC}"
    fi
fi

# 安裝完成
echo ""
echo -e "${GREEN}=========================================="
echo "✓ 安裝完成!"
echo -e "==========================================${NC}"
echo ""
echo "安裝位置: $TARGET_DIR"
echo ""
echo -e "${BLUE}下一步:${NC}"
echo ""
echo "1. 驗證安裝:"
echo "   bash verify_installation.sh"
echo ""
echo "2. 測試使用:"
echo "   claude"
echo "   # 然後輸入:"
echo "   list available skills"
echo ""
echo "3. 開始使用:"
echo "   升級 requests 到 2.32.0"
echo "   修復 CVE-2024-35195"
echo ""

if [ ${#MISSING_DEPS[@]} -gt 0 ] || [ ${#MISSING_TOOLS[@]} -gt 0 ]; then
    echo -e "${YELLOW}⚠ 注意: 請先安裝缺少的依賴和工具${NC}"
fi

echo ""
echo "更多資訊請參考:"
echo "  - INSTALLATION_GUIDE.md"
echo "  - package-upgrade/README.md"
