#!/usr/bin/env bash
# verify_installation.sh - 驗證 Package Upgrade Skill 安裝
# Usage: bash verify_installation.sh

set -euo pipefail

SKILL_DIR="$HOME/.claude/skills/package-upgrade"
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

# 1. 檢查 Skill 目錄
echo "1. 檢查 Skill 目錄..."
if [ -d "$SKILL_DIR" ]; then
    check_pass "Skill 目錄存在: $SKILL_DIR"
else
    check_fail "Skill 目錄不存在: $SKILL_DIR"
    echo ""
    echo "請執行以下命令安裝:"
    echo "  cp -r package-upgrade ~/.claude/skills/"
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

# 4. 檢查 scripts 目錄
echo ""
echo "4. 檢查 Scripts..."
SCRIPTS=(
    "detect_env.sh"
    "dep_tree.py"
    "ast_scanner.py"
    "fetch_changelog.py"
    "git_diff.sh"
    "run_tests.sh"
    "snapshot_env.sh"
    "detect_env_js.sh"
    "dep_tree_js.js"
    "ast_scanner_js.js"
    "api_surface_diff_js.js"
    "git_diff_js.sh"
    "run_tests_js.sh"
    "snapshot_env_js.sh"
    "preflight.sh"
    "parse_pm_errors.py"
    "validate_lockfile.sh"
)

for script in "${SCRIPTS[@]}"; do
    script_path="$SKILL_DIR/scripts/$script"
    if [ -e "$script_path" ] || [ -L "$script_path" ]; then
        if [ -x "$script_path" ]; then
            check_pass "$script 存在且可執行"
        else
            check_fail "$script 存在但不可執行"
            echo "     修復: chmod +x $script_path"
        fi
    else
        check_fail "$script 不存在"
    fi
done

# 5. 檢查 Python scripts 內容
echo ""
echo "5. 檢查 Python Scripts 內容..."
PYTHON_SCRIPTS=("dep_tree.py" "ast_scanner.py" "fetch_changelog.py")
for script in "${PYTHON_SCRIPTS[@]}"; do
    script_path="$SKILL_DIR/scripts/$script"
    if [ -f "$script_path" ]; then
        # 檢查檔案是否有 shebang
        if head -1 "$script_path" | grep -q "^#!/usr/bin/env python3"; then
            check_pass "$script 格式正確 (有 shebang)"
        else
            check_warn "$script 缺少 shebang"
        fi
    else
        check_fail "$script 不存在"
    fi
done

# 6. 檢查 references 目錄
echo ""
echo "6. 檢查 Reference 文件..."
REFS=(
    "pip_workflow.md"
    "poetry_workflow.md"
    "uv_workflow.md"
    "breaking_change_patterns.md"
    "js_workflow.md"
    "npm_workflow.md"
    "yarn_workflow.md"
    "js_ast_strategy.md"
    "breaking_change_patterns_js.md"
    "auth_tokens.md"
    "bdsa_mapping.md"
)

for ref in "${REFS[@]}"; do
    if [ -f "$SKILL_DIR/references/$ref" ]; then
        check_pass "$ref 存在"
    else
        check_fail "$ref 不存在"
    fi
done

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
    if [ -d "$SKILL_DIR/scripts/node_modules/@babel/parser" ]; then
        check_pass "JS helper deps 已安裝 (@babel/parser found)"
    else
        check_warn "JS helper deps 未安裝 — 執行: cd $SKILL_DIR/scripts && npm install"
    fi
else
    check_warn "node 不可用 — JavaScript 套件升級功能無法使用 (Python 功能不受影響)"
fi

# 10. 功能測試
echo ""
echo "10. 功能測試..."

# 測試 detect_env.sh
if bash "$SKILL_DIR/scripts/detect_env.sh" . 2>/dev/null | jq -e '.pkg_manager' >/dev/null 2>&1; then
    check_pass "detect_env.sh 可正常執行"
else
    check_fail "detect_env.sh 執行失敗"
fi

# 測試 Python scripts (如果有 requests)
if python3 -c "import requests" 2>/dev/null; then
    if python3 "$SKILL_DIR/scripts/dep_tree.py" . requests 2>/dev/null | jq -e '.package_name' >/dev/null 2>&1; then
        check_pass "dep_tree.py 可正常執行"
    else
        check_warn "dep_tree.py 執行異常 (可能是專案沒有 requests)"
    fi
fi

# 測試 detect_env_js.sh on a synthetic package.json
if command -v node &> /dev/null && [ -d "$SKILL_DIR/scripts/node_modules" ]; then
    JS_TMP=$(mktemp -d)
    echo '{"name":"verify","version":"1.0.0","dependencies":{}}' > "$JS_TMP/package.json"
    if bash "$SKILL_DIR/scripts/detect_env_js.sh" "$JS_TMP" 2>/dev/null | jq -e '.language=="javascript"' >/dev/null 2>&1; then
        check_pass "detect_env_js.sh 可正常執行"
    else
        check_warn "detect_env_js.sh 執行異常"
    fi
    # preflight.sh returns non-zero when blockers exist (which is expected
    # for our minimal fixture). Just verify it emits valid JSON regardless.
    PF_OUT=$(bash "$SKILL_DIR/scripts/preflight.sh" "$JS_TMP" --json 2>/dev/null || true)
    if echo "$PF_OUT" | jq -e '.summary' >/dev/null 2>&1; then
        check_pass "preflight.sh 可正常執行"
    else
        check_warn "preflight.sh 執行異常"
    fi
    if node "$SKILL_DIR/scripts/ast_scanner_js.js" "$JS_TMP" axios 2>/dev/null | jq -e '.language=="javascript"' >/dev/null 2>&1; then
        check_pass "ast_scanner_js.js 可載入 @babel/parser 並執行"
    else
        check_warn "ast_scanner_js.js 執行異常 — 確認 cd $SKILL_DIR/scripts && npm install 已成功"
    fi
    # parse_pm_errors.py runs without external deps
    if echo "YN0041: Invalid authentication" | python3 "$SKILL_DIR/scripts/parse_pm_errors.py" 2>/dev/null | jq -e '.primary_blocker == "auth"' >/dev/null 2>&1; then
        check_pass "parse_pm_errors.py 可正常執行"
    else
        check_warn "parse_pm_errors.py 執行異常"
    fi
    rm -rf "$JS_TMP"
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
    echo "   chmod +x ~/.claude/skills/package-upgrade/scripts/*.sh"
    echo "   chmod +x ~/.claude/skills/package-upgrade/scripts/*.py"
    echo ""
    echo "2. 安裝 Python 依賴:"
    echo "   pip install pipdeptree requests"
    echo ""
    echo "3. 安裝 jq:"
    echo "   brew install jq  # macOS"
    echo "   sudo apt-get install jq  # Ubuntu/Debian"
    exit 1
fi
