# 安裝驗證檢查清單

## 🚀 快速驗證 (3 步驟)

### 1️⃣ 自動驗證
```bash
bash verify_installation.sh
```

### 2️⃣ 檢查目錄
```bash
ls ~/.claude/skills/package-upgrade/
```
應該看到: `LICENSE`、`README.md`、`SKILL.md`、`QUICK_REFERENCE.md`、`scripts/`、`references/`、`templates/`

### 3️⃣ Claude Code 測試
```bash
claude
```
然後輸入: `list available skills`

---

## 📋 完整檢查清單

### ✅ 檔案結構檢查

- [ ] **核心檔案**
  ```bash
  ls ~/.claude/skills/package-upgrade/{LICENSE,README.md,SKILL.md,QUICK_REFERENCE.md}
  ```

- [ ] **Scripts — Python 軌**
  ```bash
  ls ~/.claude/skills/package-upgrade/scripts/{detect_env.sh,dep_tree.py,ast_scanner.py,fetch_changelog.py,git_diff.sh,run_tests.sh,snapshot_env.sh,preflight.sh,validate_lockfile.sh}
  ```

- [ ] **Scripts — JS / TS 軌**
  ```bash
  ls ~/.claude/skills/package-upgrade/scripts/{detect_env_js.sh,dep_tree_js.js,ast_scanner_js.js,git_diff_js.sh,run_tests_js.sh,snapshot_env_js.sh,api_surface_diff_js.js,package.json}
  ```

- [ ] **Scripts — Go 軌**
  ```bash
  ls ~/.claude/skills/package-upgrade/scripts/{detect_env_go.sh,dep_tree_go.sh,ast_scanner_go.go,git_diff_go.sh,run_tests_go.sh,snapshot_env_go.sh,preflight_go.sh,api_surface_diff_go.sh,govulncheck_go.sh,validate_modfile_go.sh}
  ```

- [ ] **Scripts — 跨語言 / 共用**
  ```bash
  ls ~/.claude/skills/package-upgrade/scripts/{parse_pm_errors.py,save_token.sh,jira_fetch.py,jira_comment.py,jira_transition.py}
  ```

- [ ] **References — Python**
  ```bash
  ls ~/.claude/skills/package-upgrade/references/{pip_workflow.md,poetry_workflow.md,uv_workflow.md,PIP_LOCK_PATTERNS.md,IMPORTANT_DEPENDENCY_UPDATE.md,breaking_change_patterns.md}
  ```

- [ ] **References — JS / TS**
  ```bash
  ls ~/.claude/skills/package-upgrade/references/{js_workflow.md,npm_workflow.md,yarn_workflow.md,js_ast_strategy.md,breaking_change_patterns_js.md}
  ```

- [ ] **References — Go**
  ```bash
  ls ~/.claude/skills/package-upgrade/references/{go_workflow.md,go_major_version_paths.md,go_replace_semantics.md,govulncheck.md,breaking_change_patterns_go.md}
  ```

- [ ] **References — 跨語言**
  ```bash
  ls ~/.claude/skills/package-upgrade/references/{jira_workflow.md,bdsa_mapping.md,auth_tokens.md}
  ```

- [ ] **Templates**
  ```bash
  ls ~/.claude/skills/package-upgrade/templates/report_structure.md
  ```

### ✅ 執行權限檢查

- [ ] **Bash Scripts 可執行**
  ```bash
  ls -la ~/.claude/skills/package-upgrade/scripts/*.sh
  ```
  每個都應該是: `-rwxr-xr-x`

- [ ] **Python Scripts 可執行**
  ```bash
  ls -la ~/.claude/skills/package-upgrade/scripts/*.py
  ```
  每個都應該是: `-rwxr-xr-x`

### ✅ 內容格式檢查

- [ ] **SKILL.md Frontmatter** (應涵蓋 Python / JS / TS / Go)
  ```bash
  head -25 ~/.claude/skills/package-upgrade/SKILL.md
  ```
  應該看到 (節錄):
  ```yaml
  ---
  name: package-upgrade
  description: >
    升級 Python / JavaScript / TypeScript / Go 套件或修復 CVE 漏洞的完整工作流。
    ...
  ---
  ```

- [ ] **Python Scripts Shebang**
  ```bash
  head -1 ~/.claude/skills/package-upgrade/scripts/*.py
  ```
  每個都應該是: `#!/usr/bin/env python3`

- [ ] **Bash Scripts Shebang**
  ```bash
  head -1 ~/.claude/skills/package-upgrade/scripts/*.sh
  ```
  每個都應該是: `#!/usr/bin/env bash`

### ✅ 依賴檢查

- [ ] **Python 3.8+**
  ```bash
  python3 --version
  ```

- [ ] **pipdeptree / requests**
  ```bash
  python3 -c "import pipdeptree, requests"
  ```

- [ ] **git / jq**
  ```bash
  git --version
  jq --version
  ```

- [ ] **gh (可選，用於自動建 PR)**
  ```bash
  gh --version
  ```

- [ ] **JS helper 依賴 (僅 JS / TS 專案需要)**
  ```bash
  ls ~/.claude/skills/package-upgrade/scripts/node_modules >/dev/null && echo "OK"
  ```

- [ ] **Go 工具 (可選，僅 Go 專案需要)**
  ```bash
  go version
  govulncheck -version
  apidiff -version
  ```

### ✅ 功能測試

- [ ] **detect_env.sh / detect_env_js.sh / detect_env_go.sh**
  ```bash
  bash ~/.claude/skills/package-upgrade/scripts/detect_env.sh .
  bash ~/.claude/skills/package-upgrade/scripts/detect_env_js.sh .
  bash ~/.claude/skills/package-upgrade/scripts/detect_env_go.sh .
  ```
  應該輸出 JSON

- [ ] **dep_tree.py** (Python 專案，且有 requests)
  ```bash
  python3 ~/.claude/skills/package-upgrade/scripts/dep_tree.py . requests
  ```

- [ ] **ast_scanner.py** (Python 專案，且有 requests)
  ```bash
  python3 ~/.claude/skills/package-upgrade/scripts/ast_scanner.py . requests
  ```

### ✅ Claude Code 整合

- [ ] **Skill 被識別**
  在 Claude Code 中輸入: `list available skills`
  應該看到 `package-upgrade` 出現

- [ ] **Skill 資訊正確**
  在 Claude Code 中輸入: `show me the package-upgrade skill`
  應該顯示 skill 的描述 (應涵蓋 Python / JS / TS / Go)

- [ ] **可以觸發** (Dry Run)
  在 Claude Code 中輸入: `檢查這個專案能不能升級 requests` (或對應的 JS / Go 套件)
  應該開始執行 Phase 0 環境偵測

---

## 🎯 快速驗證命令

一次執行所有檢查：

```bash
bash verify_installation.sh && echo "" && \
echo "✅ 驗證通過! 請繼續在 Claude Code 中測試:" && \
echo "" && \
echo "  claude" && \
echo "  # 然後輸入: list available skills"
```

---

## ❌ 常見失敗與修復

### 失敗: 目錄不存在
```bash
bash install.sh
```

### 失敗: 權限錯誤
```bash
chmod +x ~/.claude/skills/package-upgrade/scripts/*.sh
chmod +x ~/.claude/skills/package-upgrade/scripts/*.py
```

### 失敗: 缺少 Python 依賴
```bash
pip install pipdeptree requests
brew install jq  # macOS
sudo apt install jq  # Ubuntu
```

### 失敗: JS helper 缺 node_modules
```bash
cd ~/.claude/skills/package-upgrade/scripts && npm install
```

### 失敗: Claude Code 看不到 Skill
```bash
head -25 ~/.claude/skills/package-upgrade/SKILL.md   # 確認 frontmatter
# 重啟 Claude Code
```

---

## 📊 驗證結果解讀

### ✅ 完全通過
```
✓ 安裝驗證通過!
```
→ 可以開始使用

### ⚠️ 部分警告
```
通過: 25
失敗: 0
⚠ jq 不可用
⚠ gh CLI 不可用
```
→ 基本功能可用，建議補裝 jq / gh

### ❌ 有失敗
```
通過: 20
失敗: 3
✗ pipdeptree 未安裝
```
→ 必須修復失敗項目

---

## 🧪 測試專案建立

完整功能測試 (請參考 `INSTALLATION_GUIDE.md` 進階驗證一節中 Python / JS / Go 三套測試專案範本)。

---

## ✨ 驗證通過後的下一步

1. **閱讀文件**
   - `package-upgrade/README.md` - 使用說明
   - `package-upgrade/QUICK_REFERENCE.md` - 快速參考 (Python / JS / Go)

2. **了解工作流程**
   - `package-upgrade/SKILL.md` - Phase 0-7 完整流程

3. **開始使用**
   ```
   claude "升級 requests 到 2.32.0"
   claude "bump axios to 1.7.0"
   claude "go get -u github.com/spf13/cobra@v1.8.0"
   ```

4. **查看範例**
   - CVE 修復範例
   - 依賴衝突處理範例
   - Jira 觸發範例
   - Go major version jump 範例

---

全部檢查完成後，你就可以放心使用這個 Skill 了! 🎊
