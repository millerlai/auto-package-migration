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
ASSUME_YES="false"   # --yes / -y, or CI / PACKAGE_UPGRADE_ASSUME_YES=1

# 解析參數
for arg in "$@"; do
    case "$arg" in
        --project) MODE="project" ;;
        --global)  MODE="global"  ;;
        --skip-permissions) SKIP_PERMISSIONS="true" ;;
        --yes|-y) ASSUME_YES="true" ;;
        -h|--help)
            cat <<EOF
Usage: bash install.sh [--global|--project] [--skip-permissions] [--yes]

Installs two skills:
  - package-upgrade           (main upgrade workflow)
  - package-upgrade-feedback  (collect feedback → open GitHub Issue)

  --global              Install to ~/.claude/skills/ (default)
  --project             Install to ./.claude/skills/
  --skip-permissions    Don't offer to write the recommended Claude Code
                        permissions into settings.json
  --yes, -y             Non-interactive: assume yes to install/overwrite/deps
                        prompts (also implied by CI or PACKAGE_UPGRADE_ASSUME_YES=1).
                        Implies --skip-permissions to avoid unattended writes to
                        settings.json.
EOF
            exit 0
            ;;
    esac
done

# 非互動模式: 也由 CI / PACKAGE_UPGRADE_ASSUME_YES=1 觸發
if [ -n "${CI:-}" ] || [ "${PACKAGE_UPGRADE_ASSUME_YES:-}" = "1" ]; then
    ASSUME_YES="true"
fi
# 非互動時不自動改寫 settings.json (避免無人值守變更共用設定)
if [ "$ASSUME_YES" = "true" ]; then
    SKIP_PERMISSIONS="true"
fi

# confirm <prompt> <default-when-non-interactive: y|n> -> 0=yes, 1=no
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

echo -e "${BLUE}=========================================="
echo "Package Upgrade Skill 安裝程式"
echo -e "==========================================${NC}"
echo ""

# Skills to install (source dir → installed name).
# Both share the same target root: ~/.claude/skills/ or ./.claude/skills/
SKILLS=("package-upgrade" "package-upgrade-feedback")

# 檢查是否在專案根目錄
for skill in "${SKILLS[@]}"; do
    if [ ! -d "$skill" ]; then
        echo -e "${RED}錯誤: 請在專案根目錄執行此腳本${NC}"
        echo "目前路徑: $(pwd)"
        echo "預期看到: $skill/ 目錄"
        exit 1
    fi
done

# 安裝目標 (根目錄,個別 skill 路徑在迴圈中組出)
if [ "$MODE" = "global" ]; then
    SKILLS_ROOT="$HOME/.claude/skills"
    echo -e "${GREEN}安裝模式: 全域安裝${NC}"
else
    SKILLS_ROOT="./.claude/skills"
    echo -e "${GREEN}安裝模式: 專案級安裝${NC}"
fi
echo "安裝位置: $SKILLS_ROOT/{${SKILLS[0]},${SKILLS[1]}}"
# package-upgrade is the heavy one with helper scripts/deps; downstream steps
# (Python/Node deps, verify, etc.) only run against it. The feedback skill
# is pure bash/python stdlib so it just needs file copy + chmod.
TARGET_DIR="$SKILLS_ROOT/package-upgrade"

echo ""
if ! confirm "繼續安裝? (y/N) " y; then
    echo "安裝已取消"
    exit 0
fi

# 建立目標目錄
echo ""
echo -e "${BLUE}步驟 1/8: 建立目錄${NC}"
mkdir -p "$SKILLS_ROOT"

OVERWRITE_NEEDED="false"
for skill in "${SKILLS[@]}"; do
    if [ -d "$SKILLS_ROOT/$skill" ]; then
        OVERWRITE_NEEDED="true"
        break
    fi
done

if [ "$OVERWRITE_NEEDED" = "true" ]; then
    echo -e "${YELLOW}警告: 下列 skill 目錄已存在,將會覆蓋${NC}"
    for skill in "${SKILLS[@]}"; do
        [ -d "$SKILLS_ROOT/$skill" ] && echo "  - $SKILLS_ROOT/$skill"
    done
    if ! confirm "確定要覆蓋嗎? (y/N) " y; then
        echo "安裝已取消"
        exit 0
    fi
    for skill in "${SKILLS[@]}"; do
        rm -rf "$SKILLS_ROOT/$skill"
    done
fi

# 複製檔案
echo ""
echo -e "${BLUE}步驟 2/8: 複製檔案${NC}"
for skill in "${SKILLS[@]}"; do
    cp -r "$skill" "$SKILLS_ROOT/$skill"
    echo -e "${GREEN}✓ $skill 已複製到 $SKILLS_ROOT/$skill${NC}"
done

# 設定執行權限
# scripts/ now contains per-language subdirs (common/python/javascript/go),
# so chmod must recurse rather than glob at the top level.
echo ""
echo -e "${BLUE}步驟 3/8: 設定執行權限${NC}"
for skill in "${SKILLS[@]}"; do
    SKILL_PATH="$SKILLS_ROOT/$skill"
    [ -d "$SKILL_PATH/scripts" ] || continue
    find "$SKILL_PATH/scripts" \( -name '*.sh' -o -name '*.py' -o -name '*.js' \) \
        -exec chmod +x {} + 2>/dev/null || true
done
echo -e "${GREEN}✓ 執行權限已設定${NC}"

# 檢查並安裝 Python 依賴
echo ""
echo -e "${BLUE}步驟 4/8: 檢查 Python 依賴${NC}"

MISSING_DEPS=()

if ! python3 -c "import pipdeptree" 2>/dev/null; then
    MISSING_DEPS+=("pipdeptree")
fi

if ! python3 -c "import requests" 2>/dev/null; then
    MISSING_DEPS+=("requests")
fi

if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
    echo -e "${YELLOW}缺少依賴: ${MISSING_DEPS[*]}${NC}"
    if confirm "是否安裝? (y/N) " y; then
        pip install "${MISSING_DEPS[@]}"
        echo -e "${GREEN}✓ 依賴已安裝${NC}"
    else
        echo -e "${YELLOW}⚠ 跳過依賴安裝,稍後請手動執行:${NC}"
        echo "  pip install ${MISSING_DEPS[*]}"
    fi
else
    echo -e "${GREEN}✓ 所有依賴已安裝${NC}"
fi

# 檢查並安裝 Node 依賴 (JavaScript 支援)
echo ""
echo -e "${BLUE}步驟 5/8: 安裝 JavaScript 支援的 Node 依賴${NC}"

if ! command -v node >/dev/null 2>&1; then
    echo -e "${YELLOW}⚠ 未偵測到 node — JavaScript 套件升級功能將無法使用${NC}"
    echo "  安裝建議:"
    echo "    macOS:        brew install node  (or use nvm)"
    echo "    Ubuntu/Debian: sudo apt-get install nodejs npm"
    echo "    或透過 nvm:   https://github.com/nvm-sh/nvm"
    echo "  Python 套件升級不受影響。"
elif ! command -v npm >/dev/null 2>&1; then
    echo -e "${YELLOW}⚠ 偵測到 node 但找不到 npm${NC}"
    echo "  JavaScript 支援會缺少 javascript/dep_tree.js 與 javascript/api_surface_diff.js 所需的 npm 命令"
else
    NODE_VER=$(node --version 2>/dev/null || echo "unknown")
    echo "  node 版本: $NODE_VER"
    if [ -f "$TARGET_DIR/scripts/javascript/package.json" ]; then
        echo "  安裝 @babel/parser, @babel/traverse, ts-morph, semver..."
        (cd "$TARGET_DIR/scripts/javascript" && npm install --no-audit --no-fund --loglevel=error >/dev/null 2>&1) && \
            echo -e "${GREEN}✓ Node 依賴已安裝到 $TARGET_DIR/scripts/javascript/node_modules${NC}" || \
            echo -e "${YELLOW}⚠ npm install 失敗 — 可稍後手動執行: cd $TARGET_DIR/scripts/javascript && npm install${NC}"
    else
        echo -e "${YELLOW}⚠ 找不到 $TARGET_DIR/scripts/javascript/package.json,跳過 Node 依賴安裝${NC}"
    fi
fi

# 檢查系統工具
echo ""
echo -e "${BLUE}步驟 6/8: 檢查系統工具${NC}"

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

# 檢查 / 安裝 gh CLI (PR 自動化)
echo ""
echo -e "${BLUE}步驟 7/8: 檢查 gh CLI (GitHub PR 自動化)${NC}"

GH_AVAILABLE="false"

install_gh() {
    case "$(uname -s)" in
        Darwin*)
            if command -v brew >/dev/null 2>&1; then
                echo "  使用 brew 安裝..."
                brew install gh && return 0 || return 1
            else
                cat <<'GH_EOF'
  macOS 偵測到無 brew。請在另一個 terminal 執行以下任一方式:
    1) 先裝 brew: /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
       再裝 gh:   brew install gh
    2) 從 https://github.com/cli/cli/releases 下載 .pkg 直接安裝
GH_EOF
                read -p "  安裝完成後按 Enter 繼續 (或 Ctrl-C 中止)..." -r
            fi
            ;;
        Linux*)
            if [ -f /etc/debian_version ]; then
                cat <<'GH_EOF'
  請在另一個 terminal 執行以下指令安裝 gh (官方 apt source):

    (type -p wget >/dev/null || (sudo apt update && sudo apt-get install wget -y)) \
    && sudo mkdir -p -m 755 /etc/apt/keyrings \
    && wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
    && sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && sudo apt update \
    && sudo apt install gh -y
GH_EOF
            elif [ -f /etc/redhat-release ] || [ -f /etc/fedora-release ]; then
                echo "  請在另一個 terminal 執行: sudo dnf install gh"
            elif [ -f /etc/arch-release ]; then
                echo "  請在另一個 terminal 執行: sudo pacman -S github-cli"
            else
                echo "  未識別的 Linux 發行版。請參考 https://github.com/cli/cli#installation"
            fi
            read -p "  安裝完成後按 Enter 繼續 (或 Ctrl-C 中止)..." -r
            ;;
        CYGWIN*|MINGW*|MSYS*)
            if command -v winget >/dev/null 2>&1; then
                echo "  使用 winget 安裝..."
                winget install --id GitHub.cli -e --source winget && return 0 || return 1
            else
                cat <<'GH_EOF'
  Windows 偵測到無 winget。請在另一個 terminal 執行以下任一方式:
    1) scoop install gh
    2) choco install gh
    3) 從 https://github.com/cli/cli/releases 下載 .msi 安裝
GH_EOF
                read -p "  安裝完成後按 Enter 繼續 (或 Ctrl-C 中止)..." -r
            fi
            ;;
        *)
            echo "  未識別的 OS: $(uname -s)。請參考 https://github.com/cli/cli#installation"
            read -p "  安裝完成後按 Enter 繼續 (或 Ctrl-C 中止)..." -r
            ;;
    esac
    return 0
}

if command -v gh >/dev/null 2>&1; then
    echo -e "${GREEN}✓ 已安裝 gh: $(gh --version 2>/dev/null | head -1)${NC}"
    GH_AVAILABLE="true"
else
    echo -e "${YELLOW}未偵測到 gh CLI${NC}"
    echo "  gh 用於 Phase 7 自動建立 GitHub PR; 沒裝的話 skill 會 fallback 為印 URL 讓你手動建。"
    if confirm "  是否現在安裝 gh? (y/N) " n; then
        install_gh
        # 重新檢查 — 自動裝可能成功也可能失敗;手動裝完按 Enter 後也要再驗一次
        if command -v gh >/dev/null 2>&1; then
            echo -e "${GREEN}✓ gh 已就緒: $(gh --version 2>/dev/null | head -1)${NC}"
            GH_AVAILABLE="true"
        else
            echo -e "${YELLOW}⚠ 安裝後仍找不到 gh,跳過認證與權限步驟${NC}"
        fi
    else
        echo "  已跳過 gh 安裝。"
    fi
fi

# gh 認證
if [ "$GH_AVAILABLE" = "true" ]; then
    if gh auth status >/dev/null 2>&1; then
        echo -e "${GREEN}✓ gh 已認證${NC}"
    else
        echo -e "${YELLOW}gh 尚未認證 — Skill 建立 PR 時會失敗${NC}"
        if confirm "  現在執行 gh auth login? (y/N) " n; then
            gh auth login || echo -e "${YELLOW}⚠ gh auth login 未完成,可日後手動執行: gh auth login${NC}"
        else
            echo "  已跳過。日後請執行: gh auth login"
        fi
    fi
fi

# 設定 Claude Code 權限
echo ""
echo -e "${BLUE}步驟 8/8: 設定 Claude Code 權限${NC}"

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
    echo "  python3 $GRANT_SCRIPT --settings $SETTINGS_FILE --mode $MODE [--gh-entries all|none|<keys>]"
else
    echo ""
    echo "Skill 執行時會用到以下類型的權限:"
    echo "  - Bash: skill 內建 scripts、git status/diff/log、poetry/pip/uv 套件操作、"
    echo "          npm install/ls/show/pack/audit、node、grep、docker ps、tar -xzf"
    echo "  - WebFetch: pypi.org、registry.npmjs.org、www.npmjs.com、github.com、"
    echo "              raw.githubusercontent.com、api.github.com"
    echo "  - WebSearch (用於查詢 CVE / changelog)"
    echo "  - MCP (Jira): getJiraIssue、getTransitionsForJiraIssue、getAccessibleAtlassianResources"
    echo ""
    echo "下列動作會放入 'ask' 清單,執行前仍會提示確認:"
    echo "  - git push、git commit (非 -m 形式)"
    echo "  - 對 Jira 寫入留言 / 轉狀態"
    echo ""

    # --- gh 權限 (opt-in) ---
    # 4 個 gh entries 不再預設打開;依使用者選擇填入 --gh-entries
    GH_ENTRIES="none"
    GH_KEYS=("auth_status" "pr_create" "pr_view" "api")
    GH_VALUES=("Bash(gh auth status:*)" "Bash(gh pr create:*)" "Bash(gh pr view:*)" "Bash(gh api:*)")
    GH_DESCS=(
        "檢查 gh 認證狀態 (建議,Phase 0/preflight 會用到)"
        "自動建立 GitHub PR (建議,Phase 7 核心動作)"
        "查 PR 狀態與內容"
        "呼叫 GitHub REST API (例: GHE 認證檢查、PR 細節)"
    )

    echo "gh CLI 權限 (4 個 entries) 為 opt-in:"
    for i in 0 1 2 3; do
        echo "  - ${GH_VALUES[$i]}  — ${GH_DESCS[$i]}"
    done
    if [ "$GH_AVAILABLE" = "true" ]; then
        GH_HINT="Y"
        GH_PROMPT="開啟 gh 權限? [Y]全開 / [N]全不開 / [S]逐項選 (預設 Y,因偵測到 gh): "
    else
        GH_HINT="N"
        GH_PROMPT="開啟 gh 權限? [y]全開 / [N]全不開 / [s]逐項選 (預設 N,因未偵測到 gh): "
    fi
    read -p "$GH_PROMPT" -n 1 -r
    echo
    GH_REPLY="${REPLY:-$GH_HINT}"
    case "$GH_REPLY" in
        [Yy])
            GH_ENTRIES="all"
            ;;
        [Ss])
            SELECTED=()
            for i in 0 1 2 3; do
                read -p "  - ${GH_VALUES[$i]}? (y/N) " -n 1 -r
                echo
                if [[ $REPLY =~ ^[Yy]$ ]]; then
                    SELECTED+=("${GH_KEYS[$i]}")
                fi
            done
            if [ ${#SELECTED[@]} -gt 0 ]; then
                # bash 3.2 相容: 用迴圈組 comma-separated
                GH_ENTRIES=""
                for key in "${SELECTED[@]}"; do
                    if [ -z "$GH_ENTRIES" ]; then
                        GH_ENTRIES="$key"
                    else
                        GH_ENTRIES="$GH_ENTRIES,$key"
                    fi
                done
            fi
            ;;
        *)
            GH_ENTRIES="none"
            ;;
    esac
    echo "  → gh-entries: $GH_ENTRIES"
    echo ""

    echo "預覽 (dry-run) 將要寫入 $SETTINGS_FILE 的變更..."
    echo ""
    if python3 "$GRANT_SCRIPT" --settings "$SETTINGS_FILE" --mode "$MODE" --gh-entries "$GH_ENTRIES" --dry-run; then
        echo ""
        read -p "套用這些權限? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            python3 "$GRANT_SCRIPT" --settings "$SETTINGS_FILE" --mode "$MODE" --gh-entries "$GH_ENTRIES"
            echo -e "${GREEN}✓ 權限已寫入 $SETTINGS_FILE${NC}"
        else
            echo -e "${YELLOW}已跳過,可日後執行:${NC}"
            echo "  python3 $GRANT_SCRIPT --settings $SETTINGS_FILE --mode $MODE --gh-entries $GH_ENTRIES"
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
echo "已安裝 skill:"
for skill in "${SKILLS[@]}"; do
    echo "  - $SKILLS_ROOT/$skill"
done
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
echo "   升級 requests 到 2.32.0      (Python)"
echo "   升級 axios 到 1.6.0           (JavaScript)"
echo "   修復 CVE-2024-35195"
echo ""
echo "4. 跑完想回饋?"
echo "   /package-upgrade-feedback     (互動式收集 → 自動 sanitize → 開 GitHub Issue)"
echo ""

if [ ${#MISSING_DEPS[@]} -gt 0 ] || [ ${#MISSING_TOOLS[@]} -gt 0 ]; then
    echo -e "${YELLOW}⚠ 注意: 請先安裝缺少的依賴和工具${NC}"
fi

echo ""
echo "更多資訊請參考:"
echo "  - docs/installation.md"
echo "  - package-upgrade/README.md"
