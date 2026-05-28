#!/usr/bin/env bash
# install-cygwin64.sh - 在 Cygwin64 / Git Bash / MSYS2 上安裝 Package Upgrade Skill
#
# 與 install.sh 的差異:
#   1. global 安裝改寫入 $USERPROFILE/.claude/...,因為 Windows 版 Claude Code
#      讀的是 C:\Users\<user>\.claude,而不是 Cygwin 的 $HOME (/home/<user> 或
#      /c/cygwin64/home/<user>)。
#   2. Python 解譯器自動偵測 python3 / python / py -3,並補上常見 Windows 安裝路徑。
#   3. chmod 在 Windows 檔系統上是 no-op,失敗時不中斷流程。
#
# Usage: bash install-cygwin64.sh [--global|--project] [--skip-permissions]

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
Usage: bash install-cygwin64.sh [--global|--project] [--skip-permissions]

  --global              Install to \$USERPROFILE/.claude/skills/package-upgrade
                        (i.e. C:\\Users\\<you>\\.claude\\skills\\package-upgrade,
                        the path Windows-native Claude Code actually reads).
                        Default.
  --project             Install to ./.claude/skills/package-upgrade
  --skip-permissions    Don't offer to write the recommended Claude Code
                        permissions into settings.json
EOF
            exit 0
            ;;
    esac
done

echo -e "${BLUE}=========================================="
echo "Package Upgrade Skill 安裝程式 (Cygwin64 / Git Bash)"
echo -e "==========================================${NC}"
echo ""

# 環境檢查: 需要 cygpath
if ! command -v cygpath >/dev/null 2>&1; then
    echo -e "${RED}錯誤: 找不到 cygpath。此腳本只能在 Cygwin / Git Bash / MSYS2 執行。${NC}"
    echo "macOS / Linux 請改用: bash install.sh"
    exit 1
fi

# 環境檢查: USERPROFILE 必須存在
if [ -z "${USERPROFILE:-}" ]; then
    echo -e "${RED}錯誤: 環境變數 USERPROFILE 未設定,無法定位 Windows 版 Claude Code 的 .claude 目錄。${NC}"
    exit 1
fi

# 把 Windows 風格的 USERPROFILE 轉成 unix 風格 (e.g. C:\Users\me -> /c/Users/me)
WIN_HOME_UNIX="$(cygpath -u "$USERPROFILE")"

# 檢查是否在專案根目錄
if [ ! -d "package-upgrade" ]; then
    echo -e "${RED}錯誤: 請在專案根目錄執行此腳本${NC}"
    echo "目前路徑: $(pwd)"
    echo "預期看到: package-upgrade/ 目錄"
    exit 1
fi

# Python 偵測: 依序 python3 / python / py -3,再 fallback 到常見 Windows 安裝路徑
detect_python() {
    local candidates=(
        "python3"
        "python"
    )
    for cmd in "${candidates[@]}"; do
        if command -v "$cmd" >/dev/null 2>&1; then
            # 驗證真的是 Python 3
            if "$cmd" -c "import sys; sys.exit(0 if sys.version_info[0]==3 else 1)" 2>/dev/null; then
                echo "$cmd"
                return 0
            fi
        fi
    done
    # py launcher (Windows 專屬)
    if command -v py >/dev/null 2>&1; then
        if py -3 -c "import sys; sys.exit(0 if sys.version_info[0]==3 else 1)" 2>/dev/null; then
            echo "py -3"
            return 0
        fi
    fi
    # Fallback: 掃描常見 Windows Python 安裝路徑
    local fallback_paths=(
        "$WIN_HOME_UNIX/AppData/Local/Programs/Python/Python313/python.exe"
        "$WIN_HOME_UNIX/AppData/Local/Programs/Python/Python312/python.exe"
        "$WIN_HOME_UNIX/AppData/Local/Programs/Python/Python311/python.exe"
        "$WIN_HOME_UNIX/AppData/Local/Programs/Python/Python310/python.exe"
        "/c/Python313/python.exe"
        "/c/Python312/python.exe"
        "/c/Python311/python.exe"
        "/c/Python310/python.exe"
    )
    for p in "${fallback_paths[@]}"; do
        if [ -x "$p" ]; then
            echo "$p"
            return 0
        fi
    done
    return 1
}

PY="$(detect_python || true)"

# 安裝目標
if [ "$MODE" = "global" ]; then
    TARGET_DIR="$WIN_HOME_UNIX/.claude/skills/package-upgrade"
    TARGET_DIR_WIN="$(cygpath -w "$TARGET_DIR" 2>/dev/null || echo "$TARGET_DIR")"
    echo -e "${GREEN}安裝模式: 全域安裝 (Windows Claude Code 視角)${NC}"
    echo "安裝位置 (unix): $TARGET_DIR"
    echo "安裝位置 (win):  $TARGET_DIR_WIN"
else
    TARGET_DIR="./.claude/skills/package-upgrade"
    echo -e "${GREEN}安裝模式: 專案級安裝${NC}"
    echo "安裝位置: $TARGET_DIR"
fi

if [ -n "$PY" ]; then
    echo "Python 解譯器: $PY"
else
    echo -e "${YELLOW}Python 解譯器: 未偵測到 (後續 Python 依賴與權限設定步驟會跳過)${NC}"
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
echo -e "${BLUE}步驟 1/8: 建立目錄${NC}"
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
echo -e "${BLUE}步驟 2/8: 複製檔案${NC}"
cp -r package-upgrade "$TARGET_DIR"
echo -e "${GREEN}✓ 檔案已複製${NC}"

# 設定執行權限 (Windows 檔案系統會無視,但 Cygwin 掛載點上仍有效)
echo ""
echo -e "${BLUE}步驟 3/8: 設定執行權限${NC}"
# scripts/ 含 per-language 子目錄 (common/python/javascript/go),chmod 必須遞迴。
find "$TARGET_DIR/scripts" \( -name '*.sh' -o -name '*.py' -o -name '*.js' \) \
    -exec chmod +x {} + 2>/dev/null || true
echo -e "${GREEN}✓ 執行權限已設定 (Windows 檔系統會忽略此屬性,屬正常現象)${NC}"

# 檢查並安裝 Python 依賴
echo ""
echo -e "${BLUE}步驟 4/8: 檢查 Python 依賴${NC}"

MISSING_DEPS=()

if [ -z "$PY" ]; then
    echo -e "${YELLOW}⚠ 未偵測到 Python 3,跳過依賴檢查${NC}"
    echo "  建議安裝 Python 3 (https://www.python.org/) 後重新執行此腳本,"
    echo "  或手動執行: pip install pipdeptree requests"
else
    if ! $PY -c "import pipdeptree" 2>/dev/null; then
        MISSING_DEPS+=("pipdeptree")
    fi
    if ! $PY -c "import requests" 2>/dev/null; then
        MISSING_DEPS+=("requests")
    fi

    if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
        echo -e "${YELLOW}缺少依賴: ${MISSING_DEPS[*]}${NC}"
        read -p "是否安裝? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            $PY -m pip install "${MISSING_DEPS[@]}"
            echo -e "${GREEN}✓ 依賴已安裝${NC}"
        else
            echo -e "${YELLOW}⚠ 跳過依賴安裝,稍後請手動執行:${NC}"
            echo "  $PY -m pip install ${MISSING_DEPS[*]}"
        fi
    else
        echo -e "${GREEN}✓ 所有依賴已安裝${NC}"
    fi
fi

# 檢查並安裝 Node 依賴 (JavaScript 支援)
echo ""
echo -e "${BLUE}步驟 5/8: 安裝 JavaScript 支援的 Node 依賴${NC}"

if ! command -v node >/dev/null 2>&1; then
    echo -e "${YELLOW}⚠ 未偵測到 node — JavaScript 套件升級功能將無法使用${NC}"
    echo "  安裝建議:"
    echo "    Windows: 從 https://nodejs.org/ 下載安裝,或透過 winget install OpenJS.NodeJS"
    echo "    或透過 nvm-windows: https://github.com/coreybutler/nvm-windows"
    echo "  Python 套件升級不受影響。"
elif ! command -v npm >/dev/null 2>&1; then
    echo -e "${YELLOW}⚠ 偵測到 node 但找不到 npm${NC}"
    echo "  JavaScript 支援會缺少 javascript/dep_tree.js 與 javascript/api_surface_diff.js 所需的 npm 命令"
else
    NODE_VER=$(node --version 2>/dev/null || echo "unknown")
    echo "  node 版本: $NODE_VER"
    if [ -f "$TARGET_DIR/scripts/javascript/package.json" ]; then
        echo "  安裝 @babel/parser, @babel/traverse, ts-morph, semver..."
        if (cd "$TARGET_DIR/scripts/javascript" && npm install --no-audit --no-fund --loglevel=error >/dev/null 2>&1); then
            echo -e "${GREEN}✓ Node 依賴已安裝到 $TARGET_DIR/scripts/javascript/node_modules${NC}"
        else
            echo -e "${YELLOW}⚠ npm install 失敗 — 可稍後手動執行: cd $TARGET_DIR/scripts/javascript && npm install${NC}"
        fi
    else
        echo -e "${YELLOW}⚠ 找不到 $TARGET_DIR/scripts/javascript/package.json,跳過 Node 依賴安裝${NC}"
    fi
fi

# 檢查系統工具
echo ""
echo -e "${BLUE}步驟 6/8: 檢查系統工具${NC}"

MISSING_TOOLS=()

if ! command -v jq >/dev/null 2>&1; then
    MISSING_TOOLS+=("jq")
fi

if ! command -v git >/dev/null 2>&1; then
    MISSING_TOOLS+=("git")
fi

if [ ${#MISSING_TOOLS[@]} -gt 0 ]; then
    echo -e "${YELLOW}⚠ 缺少系統工具: ${MISSING_TOOLS[*]}${NC}"
    echo ""
    echo "安裝建議 (Windows):"
    for tool in "${MISSING_TOOLS[@]}"; do
        case $tool in
            jq)
                echo "  jq:"
                echo "    winget install jqlang.jq"
                echo "    或透過 Cygwin setup: apt-cyg install jq / setup-x86_64.exe 勾選 jq"
                ;;
            git)
                echo "  git:"
                echo "    winget install Git.Git"
                echo "    或下載 https://git-scm.com/download/win"
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
    return 0
}

if command -v gh >/dev/null 2>&1; then
    echo -e "${GREEN}✓ 已安裝 gh: $(gh --version 2>/dev/null | head -1)${NC}"
    GH_AVAILABLE="true"
else
    echo -e "${YELLOW}未偵測到 gh CLI${NC}"
    echo "  gh 用於 Phase 7 自動建立 GitHub PR; 沒裝的話 skill 會 fallback 為印 URL 讓你手動建。"
    read -p "  是否現在安裝 gh? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
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
        read -p "  現在執行 gh auth login? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
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
    SETTINGS_FILE="$WIN_HOME_UNIX/.claude/settings.json"
else
    SETTINGS_FILE="./.claude/settings.json"
fi

GRANT_SCRIPT="$(dirname "$0")/grant_permissions.py"
if [ ! -f "$GRANT_SCRIPT" ]; then
    echo -e "${YELLOW}⚠ 找不到 grant_permissions.py,跳過權限設定${NC}"
elif [ -z "$PY" ]; then
    echo -e "${YELLOW}⚠ 沒有 Python 解譯器,跳過權限設定${NC}"
    echo "  安裝 Python 後可手動執行:"
    echo "  python $GRANT_SCRIPT --settings $SETTINGS_FILE --mode $MODE [--gh-entries all|none|<keys>]"
elif [ "$SKIP_PERMISSIONS" = "true" ]; then
    echo -e "${YELLOW}已指定 --skip-permissions,跳過權限設定${NC}"
    echo "若要稍後手動套用,執行:"
    echo "  $PY $GRANT_SCRIPT --settings $SETTINGS_FILE --mode $MODE [--gh-entries all|none|<keys>]"
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
    if $PY "$GRANT_SCRIPT" --settings "$SETTINGS_FILE" --mode "$MODE" --gh-entries "$GH_ENTRIES" --dry-run; then
        echo ""
        read -p "套用這些權限? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            $PY "$GRANT_SCRIPT" --settings "$SETTINGS_FILE" --mode "$MODE" --gh-entries "$GH_ENTRIES"
            echo -e "${GREEN}✓ 權限已寫入 $SETTINGS_FILE${NC}"
        else
            echo -e "${YELLOW}已跳過,可日後執行:${NC}"
            echo "  $PY $GRANT_SCRIPT --settings $SETTINGS_FILE --mode $MODE --gh-entries $GH_ENTRIES"
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
echo "安裝位置 (unix): $TARGET_DIR"
if [ "$MODE" = "global" ]; then
    echo "安裝位置 (win):  $TARGET_DIR_WIN"
fi
echo ""
echo -e "${BLUE}下一步:${NC}"
echo ""
echo "1. 驗證安裝 (verify_installation.sh 預設讀 \$HOME/.claude,Cygwin 上不適用)"
echo "   改用以下指令快速驗證關鍵檔案是否就位:"
echo "   ls \"$TARGET_DIR/SKILL.md\" && ls \"$TARGET_DIR/scripts\""
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

if [ ${#MISSING_DEPS[@]} -gt 0 ] || [ ${#MISSING_TOOLS[@]} -gt 0 ] || [ -z "$PY" ]; then
    echo -e "${YELLOW}⚠ 注意: 請先安裝缺少的依賴和工具${NC}"
fi

echo ""
echo "更多資訊請參考:"
echo "  - docs/installation.md"
echo "  - package-upgrade/README.md"
