#!/usr/bin/env bash
# verify_installation_cygwin64.sh - 在 Cygwin64 / Git Bash / MSYS2 上驗證
# Package Upgrade Skill 安裝 (對應 install-cygwin64.sh 的安裝結果)。
#
# 與 verify_installation.sh 的差異:
#   1. 預設 SKILL_DIR 解析到 $USERPROFILE/.claude/skills/package-upgrade,
#      也就是 Windows-native Claude Code 真正讀的 C:\Users\<user>\.claude,
#      而不是 Cygwin 的 $HOME (verify_installation.sh 用的路徑)。
#      接受一個可選的位置參數覆蓋 (直接指向某個 package-upgrade skill 目錄,
#      例如驗證 --project 安裝: bash verify_installation_cygwin64.sh ./.claude/skills/package-upgrade,
#      或直接驗證 repo 內原始碼: bash verify_installation_cygwin64.sh ./package-upgrade)。
#   2. Python 解譯器自動偵測 python3 / python / py -3,並補上常見 Windows 安裝路徑,
#      取代 verify_installation.sh 寫死的 python3。
#   3. 缺少 exec bit 視為「正常」而非失敗 —— NTFS 不保留執行權限,且 Windows 版
#      Claude Code 是以 bash/python/node 呼叫腳本,不依賴該屬性。
#   4. 純 Python / bash 的功能測試與 node 守衛解耦,因此在沒有 node 的 Cygwin
#      上仍會跑;JS 專屬檢查在無 node 時降級為警告 (反映真實環境)。
#
# Usage:
#   bash verify_installation_cygwin64.sh [SKILL_DIR]
#   PACKAGE_UPGRADE_SKILL_DIR=<path> bash verify_installation_cygwin64.sh

set -euo pipefail

# 顏色輸出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PASSED=0
FAILED=0
NONEXEC_FOUND=0   # 是否有腳本缺 exec bit (NTFS 上屬正常,只在結尾提醒一次)

# 此腳本是 Cygwin 專屬變體,需要 cygpath 才能在預設情況下定位 Windows 的 .claude。
if ! command -v cygpath >/dev/null 2>&1; then
    echo -e "${RED}錯誤: 找不到 cygpath。此腳本只能在 Cygwin / Git Bash / MSYS2 執行。${NC}" >&2
    echo "macOS / Linux 請改用: bash verify_installation.sh" >&2
    exit 1
fi

# --- 偵測 SKILL_DIR ---
#   1. 位置參數 $1            (直接指向 package-upgrade skill 目錄)
#   2. $PACKAGE_UPGRADE_SKILL_DIR (env 覆蓋)
#   3. $USERPROFILE/.claude/skills/package-upgrade (Windows-native Claude Code 讀的路徑)
WIN_HOME_UNIX=""
if [ -n "${USERPROFILE:-}" ]; then
    WIN_HOME_UNIX="$(cygpath -u "$USERPROFILE")"
fi

if [ -n "${1:-}" ]; then
    SKILL_DIR="$1"
elif [ -n "${PACKAGE_UPGRADE_SKILL_DIR:-}" ]; then
    SKILL_DIR="$PACKAGE_UPGRADE_SKILL_DIR"
else
    if [ -z "$WIN_HOME_UNIX" ]; then
        echo -e "${RED}錯誤: 環境變數 USERPROFILE 未設定,無法定位 Windows 版 Claude Code 的 .claude 目錄。${NC}" >&2
        echo "請改用位置參數指定 skill 目錄,例如:" >&2
        echo "  bash verify_installation_cygwin64.sh ./.claude/skills/package-upgrade" >&2
        exit 1
    fi
    SKILL_DIR="$WIN_HOME_UNIX/.claude/skills/package-upgrade"
fi
# feedback skill 與主 skill 同層
FEEDBACK_DIR="$(dirname "$SKILL_DIR")/package-upgrade-feedback"

# --- Python 偵測 (對齊 install-cygwin64.sh 的 detect_python) ---
detect_python() {
    local candidates=(
        "python3"
        "python"
    )
    for cmd in "${candidates[@]}"; do
        if command -v "$cmd" >/dev/null 2>&1; then
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
    local p
    for p in "${fallback_paths[@]}"; do
        if [ -x "$p" ]; then
            echo "$p"
            return 0
        fi
    done
    return 1
}

PY="$(detect_python || true)"

echo "=========================================="
echo "Package Upgrade Skill 安裝驗證 (Cygwin64 / Git Bash)"
echo "=========================================="
echo "Skill 目錄 (unix): $SKILL_DIR"
echo "Skill 目錄 (win):  $(cygpath -w "$SKILL_DIR" 2>/dev/null || echo "$SKILL_DIR")"
if [ -n "$PY" ]; then
    echo "Python 解譯器:     $PY"
else
    echo -e "${YELLOW}Python 解譯器:     未偵測到 (Python 依賴與功能測試會跳過)${NC}"
fi
echo ""

# 測試函式 (注意: bash 3.2 + set -e 會把 `((PASSED++))` 的零值結果視為錯誤,
# 用 `: $((PASSED += 1))` 避開,因為 `:` 永遠回 0)
check_pass() {
    echo -e "${GREEN}✓${NC} $1"
    : $((PASSED += 1))
}

check_fail() {
    echo -e "${RED}✗${NC} $1"
    : $((FAILED += 1))
}

check_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# 檢查一組 scripts 檔案 (per-language 子目錄)。
# 用法: check_scripts <subdir> <file> [file ...]
# .go 檔以 `go run` 執行,本來就不需要 exec bit,只檢查存在性。
# 其他檔案: 存在即視為通過; 缺 exec bit 在 NTFS 上屬正常 (見結尾提醒),不算失敗。
check_scripts() {
    local subdir="$1"; shift
    local f path
    for f in "$@"; do
        path="$SKILL_DIR/scripts/$subdir/$f"
        if [ -e "$path" ] || [ -L "$path" ]; then
            case "$f" in
                *.go)
                    check_pass "scripts/$subdir/$f 存在"
                    ;;
                *)
                    if [ -x "$path" ]; then
                        check_pass "scripts/$subdir/$f 存在且可執行"
                    else
                        check_pass "scripts/$subdir/$f 存在 (無 exec bit — NTFS 正常)"
                        NONEXEC_FOUND=1
                    fi
                    ;;
            esac
        else
            check_fail "scripts/$subdir/$f 不存在"
        fi
    done
}

# 檢查一組 reference 文件 (per-language 子目錄)。
# 用法: check_refs <subdir> <file> [file ...]
check_refs() {
    local subdir="$1"; shift
    local f path
    for f in "$@"; do
        path="$SKILL_DIR/references/$subdir/$f"
        if [ -f "$path" ]; then
            check_pass "references/$subdir/$f 存在"
        else
            check_fail "references/$subdir/$f 不存在"
        fi
    done
}

# 1. 檢查 Skill 目錄
echo "1. 檢查 Skill 目錄..."
if [ -d "$SKILL_DIR" ]; then
    check_pass "Skill 目錄存在: $SKILL_DIR"
else
    check_fail "Skill 目錄不存在: $SKILL_DIR"
    echo ""
    echo "請執行安裝 (Cygwin64 / Git Bash):"
    echo "  bash install-cygwin64.sh            # 全域安裝 (\$USERPROFILE/.claude/skills)"
    echo "  bash install-cygwin64.sh --project  # 專案級安裝 (./.claude/skills)"
    exit 1
fi

# 2. 檢查核心檔案
echo ""
echo "2. 檢查核心檔案..."
CORE_FILES=("LICENSE" "README.md" "SKILL.md")
for file in "${CORE_FILES[@]}"; do
    if [ -f "$SKILL_DIR/$file" ]; then
        check_pass "$file 存在"
    else
        check_fail "$file 不存在"
    fi
done

# 3. 檢查 SKILL.md frontmatter
echo ""
echo "3. 檢查 SKILL.md frontmatter..."
if [ -f "$SKILL_DIR/SKILL.md" ]; then
    if head -1 "$SKILL_DIR/SKILL.md" | grep -q "^---$"; then
        check_pass "Frontmatter 開始標記正確"
    else
        check_fail "Frontmatter 開始標記錯誤"
    fi

    if grep -q "^name: package-upgrade$" "$SKILL_DIR/SKILL.md"; then
        check_pass "Skill 名稱正確"
    else
        check_fail "Skill 名稱錯誤或缺失"
    fi

    if grep -q "^description:" "$SKILL_DIR/SKILL.md"; then
        check_pass "Description 存在"
    else
        check_fail "Description 缺失"
    fi
fi

# 4. 檢查 scripts 目錄 (per-language 子目錄: common / python / javascript / go)
echo ""
echo "4. 檢查 Scripts..."
check_scripts common \
    fetch_changelog.py git_diff.sh parse_pm_errors.py save_token.sh \
    jira_comment.py jira_fetch.py jira_transition.py
check_scripts python \
    detect_env.sh dep_tree.py ast_scanner.py run_tests.sh snapshot_env.sh \
    preflight.sh validate_lockfile.sh api_surface_diff.sh pip_audit.sh
check_scripts javascript \
    detect_env.sh dep_tree.js ast_scanner.js api_surface_diff.js git_diff.sh \
    run_tests.sh snapshot_env.sh preflight.sh validate_lockfile.sh runtime_verify.js
check_scripts go \
    detect_env.sh dep_tree.sh dep_tree.py ast_scanner.go api_surface_diff.sh \
    git_diff.sh run_tests.sh snapshot_env.sh preflight.sh govulncheck.sh validate_modfile.sh

# 5. 檢查 Python scripts 內容 (shebang)
echo ""
echo "5. 檢查 Python Scripts 內容..."
PYTHON_SCRIPTS=("python/dep_tree.py" "python/ast_scanner.py" "common/fetch_changelog.py")
for script in "${PYTHON_SCRIPTS[@]}"; do
    script_path="$SKILL_DIR/scripts/$script"
    if [ -f "$script_path" ]; then
        if head -1 "$script_path" | grep -q "^#!/usr/bin/env python3"; then
            check_pass "$script 格式正確 (有 shebang)"
        else
            check_warn "$script 缺少 shebang"
        fi
    else
        check_fail "$script 不存在"
    fi
done

# 6. 檢查 references 目錄 (per-language 子目錄)
echo ""
echo "6. 檢查 Reference 文件..."
check_refs common \
    auth_tokens.md bdsa_mapping.md breaking_change_patterns.md \
    important_dependency_update.md jira_workflow.md
check_refs python \
    breaking_change_patterns.md override_semantics.md pip_lock_patterns.md \
    pip_workflow.md poetry_workflow.md runtime_verification.md uv_workflow.md
check_refs javascript \
    ast_strategy.md breaking_change_patterns.md npm_workflow.md override_semantics.md \
    pnpm_workflow.md runtime_verification.md workflow.md yarn_workflow.md
check_refs go \
    breaking_change_patterns.md govulncheck.md major_version_paths.md \
    replace_semantics.md runtime_verification.md workflow.md

# 7. 檢查 templates 目錄
echo ""
echo "7. 檢查 Templates..."
if [ -f "$SKILL_DIR/templates/report_structure.md" ]; then
    check_pass "report_structure.md 存在"
else
    check_fail "report_structure.md 不存在"
fi

# 8. 檢查 Python 依賴
echo ""
echo "8. 檢查 Python 依賴..."

if [ -n "$PY" ]; then
    check_pass "Python 3 可用 ($PY)"

    if $PY -c "import pipdeptree" 2>/dev/null; then
        check_pass "pipdeptree 已安裝"
    else
        check_fail "pipdeptree 未安裝"
        echo "     安裝: $PY -m pip install pipdeptree"
    fi

    if $PY -c "import requests" 2>/dev/null; then
        check_pass "requests 已安裝"
    else
        check_fail "requests 未安裝"
        echo "     安裝: $PY -m pip install requests"
    fi
else
    check_warn "未偵測到 Python 3 — 跳過依賴檢查 (Python 套件升級功能無法使用)"
    echo "     安裝 Python 3 (https://www.python.org/) 後重新驗證"
fi

# 9. 檢查系統工具
echo ""
echo "9. 檢查系統工具..."

if command -v git &> /dev/null; then
    check_pass "git 可用"
else
    check_fail "git 不可用"
fi

if command -v jq &> /dev/null; then
    check_pass "jq 可用"
else
    check_warn "jq 不可用 (建議安裝: winget install jqlang.jq / Cygwin setup 勾選 jq)"
fi

if command -v gh &> /dev/null; then
    check_pass "gh CLI 可用 (可選)"
else
    check_warn "gh CLI 不可用 (可選,用於自動建立 PR)"
fi

# 9b. Node + JS helper deps
echo ""
echo "9b. 檢查 Node 環境與 JS helper 依賴..."
if command -v node &> /dev/null; then
    NODE_VER=$(node --version 2>/dev/null || echo "?")
    check_pass "node 可用 ($NODE_VER)"
    if command -v npm &> /dev/null; then
        check_pass "npm 可用"
    else
        check_warn "npm 不可用 (JS 升級流程會缺命令)"
    fi
    if [ -d "$SKILL_DIR/scripts/javascript/node_modules/@babel/parser" ]; then
        check_pass "JS helper deps 已安裝 (@babel/parser found)"
    else
        check_warn "JS helper deps 未安裝 — 執行: cd $SKILL_DIR/scripts/javascript && npm install"
    fi
else
    check_warn "node 不可用 — JavaScript 套件升級功能無法使用 (Python 功能不受影響)"
fi

# 9c. Go 工具鏈 (可選 — 僅 Go 套件升級需要)
echo ""
echo "9c. 檢查 Go 工具鏈 (可選)..."
if command -v go &> /dev/null; then
    GO_VER=$(go version 2>/dev/null | awk '{print $3}' || echo "?")
    check_pass "go 可用 ($GO_VER)"
    if command -v govulncheck &> /dev/null; then
        check_pass "govulncheck 可用 (Go reachability 分析)"
    else
        check_warn "govulncheck 不可用 (可選 — 安裝: go install golang.org/x/vuln/cmd/govulncheck@latest)"
    fi
else
    check_warn "go 不可用 — Go 套件升級功能無法使用 (Python/JS 功能不受影響)"
fi

# 9d. package-upgrade-feedback skill (install-cygwin64.sh 會一併安裝)
echo ""
echo "9d. 檢查 package-upgrade-feedback skill..."
if [ -d "$FEEDBACK_DIR" ]; then
    check_pass "feedback skill 目錄存在: $FEEDBACK_DIR"
    if [ -f "$FEEDBACK_DIR/SKILL.md" ]; then
        check_pass "feedback SKILL.md 存在"
        if grep -q "^name: package-upgrade-feedback$" "$FEEDBACK_DIR/SKILL.md"; then
            check_pass "feedback skill 名稱正確"
        else
            check_fail "feedback skill 名稱錯誤或缺失"
        fi
    else
        check_fail "feedback SKILL.md 不存在"
    fi
    for s in sanitize_feedback.sh submit_feedback.sh; do
        p="$FEEDBACK_DIR/scripts/$s"
        if [ -x "$p" ]; then
            check_pass "feedback scripts/$s 存在且可執行"
        elif [ -e "$p" ]; then
            check_pass "feedback scripts/$s 存在 (無 exec bit — NTFS 正常)"
            NONEXEC_FOUND=1
        else
            check_fail "feedback scripts/$s 不存在"
        fi
    done
else
    check_warn "feedback skill 未安裝 ($FEEDBACK_DIR) — install-cygwin64.sh 會一併安裝;若只手動複製主 skill 可忽略"
fi

# 10. 功能測試
echo ""
echo "10. 功能測試..."

# --- Python (用偵測到的 $PY,而非寫死的 python3) ---
if [ -n "$PY" ] && command -v jq &> /dev/null; then
    if bash "$SKILL_DIR/scripts/python/detect_env.sh" . 2>/dev/null | jq -e '.pkg_manager' >/dev/null 2>&1; then
        check_pass "scripts/python/detect_env.sh 可正常執行"
    else
        check_fail "scripts/python/detect_env.sh 執行失敗"
    fi

    if $PY -c "import requests" 2>/dev/null; then
        if $PY "$SKILL_DIR/scripts/python/dep_tree.py" . requests 2>/dev/null | jq -e '.package_name' >/dev/null 2>&1; then
            check_pass "scripts/python/dep_tree.py 可正常執行"
        else
            check_warn "scripts/python/dep_tree.py 執行異常 (可能是專案沒有 requests)"
        fi
    fi
elif [ -n "$PY" ] && ! command -v jq &> /dev/null; then
    check_warn "有 Python 但缺 jq — 跳過需要 jq 的功能測試 (安裝 jq 後可完整驗證)"
fi

# --- 共用 helpers (只需 $PY / bash,與 node 無關) ---
if [ -n "$PY" ] && command -v jq &> /dev/null; then
    # parse_pm_errors.py 無外部依賴
    if echo "YN0041: Invalid authentication" | $PY "$SKILL_DIR/scripts/common/parse_pm_errors.py" 2>/dev/null | jq -e '.primary_blocker == "auth"' >/dev/null 2>&1; then
        check_pass "scripts/common/parse_pm_errors.py 可正常執行"
    else
        check_warn "scripts/common/parse_pm_errors.py 執行異常"
    fi
    # save_token.sh — 創建後再次寫入應偵測衝突 (exit 2)
    TOK_TMP=$(mktemp -d)
    SAVE_OUT1=$(bash "$SKILL_DIR/scripts/common/save_token.sh" "$TOK_TMP" .env.test FAKE_TOKEN "v1" 2>/dev/null || true)
    SAVE_OUT2_EXIT=0
    bash "$SKILL_DIR/scripts/common/save_token.sh" "$TOK_TMP" .env.test FAKE_TOKEN "v2" >/dev/null 2>&1 || SAVE_OUT2_EXIT=$?
    if echo "$SAVE_OUT1" | jq -e '.status == "created"' >/dev/null 2>&1 && [ "$SAVE_OUT2_EXIT" = "2" ]; then
        check_pass "scripts/common/save_token.sh 創建與衝突偵測都正確"
    else
        check_warn "scripts/common/save_token.sh 行為異常 (created=$SAVE_OUT1, conflict_exit=$SAVE_OUT2_EXIT)"
    fi
    rm -rf "$TOK_TMP"
fi

# --- JavaScript helpers (需 node + 已安裝的 node_modules) ---
if command -v node &> /dev/null && command -v jq &> /dev/null && [ -d "$SKILL_DIR/scripts/javascript/node_modules" ]; then
    JS_TMP=$(mktemp -d)
    echo '{"name":"verify","version":"1.0.0","dependencies":{}}' > "$JS_TMP/package.json"
    if bash "$SKILL_DIR/scripts/javascript/detect_env.sh" "$JS_TMP" 2>/dev/null | jq -e '.language=="javascript"' >/dev/null 2>&1; then
        check_pass "scripts/javascript/detect_env.sh 可正常執行"
    else
        check_warn "scripts/javascript/detect_env.sh 執行異常"
    fi
    # preflight.sh 在有 blocker 時回非零 (對最小 fixture 是預期的),只驗證它吐出合法 JSON
    PF_OUT=$(bash "$SKILL_DIR/scripts/javascript/preflight.sh" "$JS_TMP" --json 2>/dev/null || true)
    if echo "$PF_OUT" | jq -e '.summary' >/dev/null 2>&1; then
        check_pass "scripts/javascript/preflight.sh 可正常執行"
    else
        check_warn "scripts/javascript/preflight.sh 執行異常"
    fi
    if node "$SKILL_DIR/scripts/javascript/ast_scanner.js" "$JS_TMP" axios 2>/dev/null | jq -e '.language=="javascript"' >/dev/null 2>&1; then
        check_pass "scripts/javascript/ast_scanner.js 可載入 @babel/parser 並執行"
    else
        check_warn "scripts/javascript/ast_scanner.js 執行異常 — 確認 cd $SKILL_DIR/scripts/javascript && npm install 已成功"
    fi
    rm -rf "$JS_TMP"
else
    check_warn "跳過 JavaScript helper 功能測試 (需 node + jq + 已安裝的 node_modules — Cygwin 上常無 node,屬正常)"
fi

# --- Go helpers (需 go 工具鏈) ---
if command -v go &> /dev/null && command -v jq &> /dev/null; then
    GO_TMP=$(mktemp -d)
    (cd "$GO_TMP" && go mod init verify/example >/dev/null 2>&1) || true
    if bash "$SKILL_DIR/scripts/go/detect_env.sh" "$GO_TMP" 2>/dev/null | jq -e '.language=="go"' >/dev/null 2>&1; then
        check_pass "scripts/go/detect_env.sh 可正常執行"
    else
        check_warn "scripts/go/detect_env.sh 執行異常"
    fi
    rm -rf "$GO_TMP"
fi

# 總結
echo ""
echo "=========================================="
echo "驗證結果總結"
echo "=========================================="
if [ "$NONEXEC_FOUND" = "1" ]; then
    check_warn "部分 scripts 缺 exec bit — NTFS 不保留執行權限,Windows 版 Claude Code 以 bash/python/node 呼叫,屬正常,不影響使用"
    echo ""
fi
echo -e "${GREEN}通過: $PASSED${NC}"
echo -e "${RED}失敗: $FAILED${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ 安裝驗證通過!${NC}"
    echo ""
    echo "下一步:"
    echo "1. 啟動 Claude Code: claude"
    echo "2. 輸入: list available skills"
    echo "3. 確認 package-upgrade 出現在列表中"
    echo ""
    echo "測試使用:"
    echo "  輸入: 檢查這個專案能不能升級 requests"
    exit 0
else
    echo -e "${RED}✗ 安裝驗證失敗,請修復上述問題${NC}"
    echo ""
    echo "常見修復方法:"
    echo "1. 若 scripts/references 路徑全部 FAIL,代表安裝版落後於目前結構,請重新安裝:"
    echo "   bash install-cygwin64.sh"
    echo ""
    echo "2. 安裝 Python 依賴 (用偵測到的解譯器):"
    echo "   ${PY:-python} -m pip install pipdeptree requests"
    echo ""
    echo "3. 安裝 jq:"
    echo "   winget install jqlang.jq          # Windows"
    echo "   或 Cygwin setup-x86_64.exe 勾選 jq"
    exit 1
fi
