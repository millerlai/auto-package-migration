#!/usr/bin/env bash
# verify_installation.sh - 驗證 Package Upgrade Skill 安裝
# Usage: bash verify_installation.sh
#
# 安裝根目錄偵測順序:
#   1. $PACKAGE_UPGRADE_SKILLS_ROOT (覆蓋,供測試或非標準安裝用)
#   2. ~/.claude/skills        (install.sh 預設 --global)
#   3. ./.claude/skills        (install.sh --project)

set -euo pipefail

# --- 偵測安裝根目錄 (對齊 install.sh 的 --global / --project) ---
SKILLS_ROOT="${PACKAGE_UPGRADE_SKILLS_ROOT:-$HOME/.claude/skills}"
if [ ! -d "$SKILLS_ROOT/package-upgrade" ] && [ -d "./.claude/skills/package-upgrade" ]; then
    SKILLS_ROOT="./.claude/skills"
fi
SKILL_DIR="$SKILLS_ROOT/package-upgrade"
FEEDBACK_DIR="$SKILLS_ROOT/package-upgrade-feedback"

PASSED=0
FAILED=0

# 顏色輸出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "Package Upgrade Skill 安裝驗證"
echo "=========================================="
echo "安裝根目錄: $SKILLS_ROOT"
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
# .go 檔以 `go run` 執行,install.sh 不會 chmod +x,因此只檢查存在性。
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
                        check_fail "scripts/$subdir/$f 存在但不可執行"
                        echo "     修復: chmod +x $path"
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
    echo "請執行安裝:"
    echo "  bash install.sh            # 全域安裝 (~/.claude/skills)"
    echo "  bash install.sh --project  # 專案級安裝 (./.claude/skills)"
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
    jira_comment.py jira_fetch.py jira_transition.py dependabot_fetch.py
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
    important_dependency_update.md jira_workflow.md dependabot_workflow.md
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

if command -v python3 &> /dev/null; then
    check_pass "python3 可用"

    if python3 -c "import pipdeptree" 2>/dev/null; then
        check_pass "pipdeptree 已安裝"
    else
        check_fail "pipdeptree 未安裝"
        echo "     安裝: pip install pipdeptree"
    fi

    if python3 -c "import requests" 2>/dev/null; then
        check_pass "requests 已安裝"
    else
        check_fail "requests 未安裝"
        echo "     安裝: pip install requests"
    fi
else
    check_fail "python3 不可用"
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
    check_warn "jq 不可用 (建議安裝: brew install jq)"
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

# 9d. package-upgrade-feedback skill (install.sh 會一併安裝)
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
            check_fail "feedback scripts/$s 存在但不可執行"
            echo "     修復: chmod +x $p"
        else
            check_fail "feedback scripts/$s 不存在"
        fi
    done
else
    check_warn "feedback skill 未安裝 ($FEEDBACK_DIR) — install.sh 會一併安裝;若只手動複製主 skill 可忽略"
fi

# 10. 功能測試
echo ""
echo "10. 功能測試..."

# --- Python (python3 一定存在才有意義) ---
if command -v python3 &> /dev/null && command -v jq &> /dev/null; then
    if bash "$SKILL_DIR/scripts/python/detect_env.sh" . 2>/dev/null | jq -e '.pkg_manager' >/dev/null 2>&1; then
        check_pass "scripts/python/detect_env.sh 可正常執行"
    else
        check_fail "scripts/python/detect_env.sh 執行失敗"
    fi

    if python3 -c "import requests" 2>/dev/null; then
        if python3 "$SKILL_DIR/scripts/python/dep_tree.py" . requests 2>/dev/null | jq -e '.package_name' >/dev/null 2>&1; then
            check_pass "scripts/python/dep_tree.py 可正常執行"
        else
            check_warn "scripts/python/dep_tree.py 執行異常 (可能是專案沒有 requests)"
        fi
    fi
fi

# --- 共用 helpers (只需 python3 / bash,與 node 無關) ---
if command -v python3 &> /dev/null && command -v jq &> /dev/null; then
    # parse_pm_errors.py 無外部依賴
    if echo "YN0041: Invalid authentication" | python3 "$SKILL_DIR/scripts/common/parse_pm_errors.py" 2>/dev/null | jq -e '.primary_blocker == "auth"' >/dev/null 2>&1; then
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
    echo "1. 設定執行權限:"
    echo "   find $SKILL_DIR/scripts \\( -name '*.sh' -o -name '*.py' -o -name '*.js' \\) -exec chmod +x {} +"
    echo ""
    echo "2. 安裝 Python 依賴:"
    echo "   pip install pipdeptree requests"
    echo ""
    echo "3. 安裝 jq:"
    echo "   brew install jq  # macOS"
    echo "   sudo apt-get install jq  # Ubuntu/Debian"
    echo ""
    echo "4. 若 scripts/references 路徑全部 FAIL,代表安裝版落後於目前結構,請重新安裝:"
    echo "   bash install.sh"
    exit 1
fi
