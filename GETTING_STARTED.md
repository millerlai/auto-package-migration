# 快速上手指南

## 🎯 3 分鐘安裝並開始使用

### 步驟 1: 安裝 (1 分鐘)

#### macOS / Linux

```bash
bash install.sh
```

#### Windows

```cmd
install.bat
```

(Cygwin 環境改用 `bash install-cygwin64.sh`，會額外幫你裝好 `gh` CLI。)

輸入 `y` 確認安裝。腳本會自動：
- ✅ 複製 skill 到 `~/.claude/skills/package-upgrade/`
- ✅ 設定執行權限
- ✅ 檢查並安裝 Python 依賴 (`pipdeptree`, `requests`)
- ✅ (若會用 JS / TS) 在 `scripts/` 內跑 `npm install` 安裝 JS helpers 的依賴
- ✅ (若同意) 偵測缺失的 `gh` CLI 並協助安裝 / `gh auth login`
- ✅ (若同意) 把允許清單寫入 Claude Code `settings.json`

---

### 步驟 2: 驗證 (1 分鐘)

```bash
bash verify_installation.sh
```

**預期輸出**：

```
==========================================
Package Upgrade Skill 安裝驗證
==========================================

1. 檢查 Skill 目錄...
✓ Skill 目錄存在

2. 檢查核心檔案...
✓ LICENSE 存在
✓ README.md 存在
✓ SKILL.md 存在

...

==========================================
驗證結果總結
==========================================
通過: 28
失敗: 0

✓ 安裝驗證通過!
```

---

### 步驟 3: 開始使用 (1 分鐘)

```bash
claude
```

然後輸入以下任一指令：

#### Python
```
升級 requests 到 2.32.0
修復 CVE-2024-35195
看看 django 能不能從 4.2 升到 5.1
```

#### JavaScript / TypeScript
```
bump axios to 1.7.0
update typescript to 5.5.0
```

#### Go
```
go get -u github.com/spf13/cobra@v1.8.0
把 github.com/spf13/viper 從 v1 升到 v2
```

#### Jira 觸發 (需 Atlassian MCP 或 API token)
```
https://trendmicro.atlassian.net/browse/V1E-148968
V1E-148968
```

---

## 📖 重要提醒

### ⚠️ 語言偵測順序

Skill 偵測順序為 **Go > JS > Python**。多語言混合專案 (`go.mod` + `package.json` + `pyproject.toml` 都存在) 會主動詢問你要升的是哪一邊的套件。

### ⚠️ Pip Lock 檔案

如果你的專案使用 pip 並且有 lock 檔案 (如 `requirements.lock`)，Skill 會**詢問你**如何產生 lock 檔案：

```
📋 偵測到專案使用 lock 檔案: requirements.lock

請選擇 lock 檔案產生方式:

[1] 使用 pip freeze (標準方式)
[2] 使用專案自定義腳本 (請告訴我命令)
[3] 我會手動處理，請繼續下一步
```

**常見情況**：
- **pip-tools**: 會自動執行 `pip-compile`
- **自定義 lock**: 會詢問你的產生方式
- **無 lock**: 直接更新 `requirements.txt`

詳見：`package-upgrade/references/PIP_LOCK_PATTERNS.md`

### ⚠️ Poetry / UV

**重要**：必須使用正確的命令：

```bash
# ❌ 錯誤 - 只更新 lock
poetry update requests
uv lock --upgrade-package requests

# ✅ 正確 - 同時更新 pyproject.toml 和 lock
poetry add requests@2.32.0
uv add "requests>=2.32.0"
```

### ⚠️ Yarn 3 (corepack)

JS 專案若用 yarn 3，corepack-managed yarn 不在 PATH。Skill 會用
`detect_env_js.sh` 解析出的 `pkg_manager_bin` (例 `node .yarn/releases/yarn-3.8.2.cjs`)，
不要在自定義腳本裡 hard-code `yarn`。

### ⚠️ Go major version jump

從 `v1` 升到 `v2+` 時，Skill 會列出所有需要 rewrite 的 import path
(`github.com/spf13/viper` → `github.com/spf13/viper/v2`)，等你確認後一次改完。

詳見：`package-upgrade/references/go_major_version_paths.md`

詳見：`package-upgrade/QUICK_REFERENCE.md`

---

## 🎨 使用者確認點

Skill 會在以下時間點暫停並等待你確認：

1. **Jira ticket 解析** - 從 ticket 抽到的 package/版本/驗收條件 (僅 Jira 觸發)
2. **依賴衝突** - 提供多種解決方案供選擇
3. **Pip Lock 檔案** - 詢問如何產生 lock
4. **Parent bump 詢問** - Transitive 升級被 parent 擋住時
5. **Go major version jump** - 列出需 rewrite 的 import path
6. **程式碼修改** - 展示完整 diff 等待確認
7. **建立分支** - 告知分支名稱
8. **測試程式修改** - 解釋為什麼要改測試
9. **建立 PR** - 展示 PR 內容
10. **Post Jira comment** - 預覽 comment + ticket URL (僅 Jira 觸發)
11. **Jira status 轉換** - 列出目前狀態 → 目標狀態 (僅 Jira 觸發)

你可以在任何時候：
- ✅ 同意繼續
- ✏️ 要求修改
- ⏸️ 暫停手動介入
- ❌ 中止並回退

---

## 📚 完整文件導航

### 安裝相關
- `README.md` / `README.zh-TW.md` - 專案總覽 (英 / 繁中)
- `INSTALLATION_GUIDE.md` - 詳細安裝指南
- `VERIFICATION_CHECKLIST.md` - 完整驗證檢查清單
- `install.sh` / `install.bat` / `install-cygwin64.sh` - 各平台安裝腳本
- `verify_installation.sh` - 自動驗證腳本

### 使用相關
- `package-upgrade/README.md` - Skill 使用說明
- `package-upgrade/SKILL.md` - 完整工作流程 (Phase 0-7)
- `package-upgrade/QUICK_REFERENCE.md` - 快速參考卡片 (Python / JS / Go)

### 參考文件 (Python)
- `package-upgrade/references/pip_workflow.md` - Pip 操作指南
- `package-upgrade/references/poetry_workflow.md` - Poetry 操作指南
- `package-upgrade/references/uv_workflow.md` - UV 操作指南
- `package-upgrade/references/PIP_LOCK_PATTERNS.md` - Pip lock 模式指南
- `package-upgrade/references/IMPORTANT_DEPENDENCY_UPDATE.md` - 依賴更新規則

### 參考文件 (JavaScript / TypeScript)
- `package-upgrade/references/js_workflow.md`
- `package-upgrade/references/npm_workflow.md`
- `package-upgrade/references/yarn_workflow.md`
- `package-upgrade/references/js_ast_strategy.md`
- `package-upgrade/references/breaking_change_patterns_js.md`

### 參考文件 (Go)
- `package-upgrade/references/go_workflow.md`
- `package-upgrade/references/go_major_version_paths.md`
- `package-upgrade/references/go_replace_semantics.md`
- `package-upgrade/references/govulncheck.md`
- `package-upgrade/references/breaking_change_patterns_go.md`

### 跨語言
- `package-upgrade/references/breaking_change_patterns.md`
- `package-upgrade/references/jira_workflow.md` - Jira 整合流程
- `package-upgrade/references/bdsa_mapping.md`
- `package-upgrade/references/auth_tokens.md`

### 架構設計
- `package-upgrade-agent-architecture.md` - 完整架構設計文件
- `CHANGELOG.md` - 版本更新記錄

---

## 🆘 需要幫助?

### 問題排查順序

1. **檢查安裝**: `bash verify_installation.sh`
2. **查看文件**: `INSTALLATION_GUIDE.md` → 故障排除章節
3. **檢查權限**: `chmod +x ~/.claude/skills/package-upgrade/scripts/*`
4. **重新安裝**: `bash install.sh`

### 快速診斷

```bash
# 檢查 Skill 目錄
ls ~/.claude/skills/package-upgrade/SKILL.md

# 檢查 Python 依賴
python3 -c "import pipdeptree, requests"

# 檢查 JS helper 依賴 (僅 JS / TS 專案需要)
ls ~/.claude/skills/package-upgrade/scripts/node_modules >/dev/null && echo "OK"

# 檢查工具
jq --version
git --version
gh --version       # 可選
go version         # 僅 Go 專案需要
```

---

## 🎊 安裝成功後

你現在可以：

1. ✅ 自動升級 Python / JS / TS / Go 套件
2. ✅ 自動分析 breaking changes (changelog + git diff，附 source URL + commit SHA)
3. ✅ 自動修改受影響的程式碼 (AST 掃描)
4. ✅ 自動執行測試並做三向診斷
5. ✅ 自動產生遷移報告和 PR
6. ✅ 修復 CVE / BDSA / GHSA 漏洞 (Go 額外做 govulncheck reachability)
7. ✅ 從 Jira ticket 觸發，完成後 comment 回 ticket + 詢問 transition

**開始你的第一次升級**：
```bash
claude "升級 requests 到 2.32.0"
```

享受自動化的套件升級體驗! 🚀
