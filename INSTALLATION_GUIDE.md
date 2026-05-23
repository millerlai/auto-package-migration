# 安裝與驗證指南

## 快速安裝

最簡單的方式：從 repo 根目錄執行對應平台的 installer。

```bash
# macOS / Linux
bash install.sh                # 全域安裝 (推薦)
bash install.sh --project      # 專案級安裝
bash install.sh --skip-permissions   # 跳過寫入 Claude Code settings.json

# Windows (PowerShell / cmd)
install.bat

# Cygwin64 (附帶安裝 gh CLI)
bash install-cygwin64.sh
```

`install.sh` 會自動：
1. 複製 `package-upgrade/` 到 `~/.claude/skills/`
2. 設定 scripts 執行權限
3. 安裝 Python 依賴 (`pipdeptree`, `requests`)
4. (若會用 JS / TS) 在 `scripts/` 內跑 `npm install`
5. (若同意) 偵測缺失的 `gh` CLI 並協助安裝 / `gh auth login`
6. (若同意，且未 `--skip-permissions`) 把允許清單寫入 Claude Code `settings.json`

---

## 手動安裝

### 步驟 1: 複製 Skill 到 Claude Code 目錄

```bash
# 從專案根目錄執行
cp -r package-upgrade ~/.claude/skills/
```

### 步驟 2: 設定執行權限

```bash
chmod +x ~/.claude/skills/package-upgrade/scripts/*.sh
chmod +x ~/.claude/skills/package-upgrade/scripts/*.py
```

### 步驟 3: 安裝 Python 依賴

```bash
pip install pipdeptree requests
```

### 步驟 4: 安裝 JS helper 依賴 (僅 JS / TS 專案需要)

```bash
cd ~/.claude/skills/package-upgrade/scripts && npm install && cd -
```

### 步驟 5: 安裝 Go 工具 (可選，Go 專案需要)

```bash
go install golang.org/x/vuln/cmd/govulncheck@latest
go install golang.org/x/exp/cmd/apidiff@latest
```

### 步驟 6: 系統工具

```bash
# macOS
brew install jq gh

# Debian / Ubuntu
sudo apt-get install jq
# gh：依官方說明 https://cli.github.com/
```

---

## 驗證安裝

### 方法 1: 使用驗證腳本 (推薦)

```bash
bash verify_installation.sh
```

這個腳本會自動檢查：
- ✅ Skill 目錄是否存在
- ✅ 所有必要檔案是否存在
- ✅ Scripts 是否有執行權限
- ✅ Python scripts 格式是否正確
- ✅ Python 依賴是否安裝
- ✅ SKILL.md frontmatter 是否正確

### 方法 2: 手動驗證步驟

#### 2.1 檢查檔案結構

```bash
ls -la ~/.claude/skills/package-upgrade/
# 應該看到: LICENSE, README.md, SKILL.md, QUICK_REFERENCE.md, scripts/, references/, templates/

ls ~/.claude/skills/package-upgrade/scripts/
# 應該看到三軌 helper：Python / JS / Go 各自的 detect_env*, dep_tree*,
# ast_scanner*, git_diff*, run_tests*, snapshot_env*；
# 加上 fetch_changelog.py、preflight*.sh、validate_lockfile.sh、
# validate_modfile_go.sh、govulncheck_go.sh、api_surface_diff_*、
# parse_pm_errors.py、save_token.sh、jira_*.py、package.json (JS helpers)

ls ~/.claude/skills/package-upgrade/references/
# 應該看到語言別 references：
#   Python: pip_workflow / poetry_workflow / uv_workflow /
#           PIP_LOCK_PATTERNS / IMPORTANT_DEPENDENCY_UPDATE / breaking_change_patterns
#   JS:     js_workflow / npm_workflow / yarn_workflow /
#           js_ast_strategy / breaking_change_patterns_js
#   Go:     go_workflow / go_major_version_paths / go_replace_semantics /
#           govulncheck / breaking_change_patterns_go
#   跨語言: jira_workflow / bdsa_mapping / auth_tokens
```

#### 2.2 檢查 SKILL.md frontmatter

```bash
head -25 ~/.claude/skills/package-upgrade/SKILL.md
```

應該看到 (節錄)：

```yaml
---
name: package-upgrade
description: >
  升級 Python / JavaScript / TypeScript / Go 套件或修復 CVE 漏洞的完整工作流。
  ...
  Python: 支援 pip、poetry、uv 三種套件管理工具。
  JavaScript/TypeScript: 支援 npm + yarn 3 + TypeScript .d.ts API surface diff
  (pnpm / bun 後續 stage)。
  Go: 支援 go modules、major version path rewrite (v1→v2+)、apidiff API surface
  diff、govulncheck reachability 分析、vendor mode、go.work workspace、
  replace directives。
---
```

#### 2.3 檢查 Scripts 執行權限

```bash
ls -la ~/.claude/skills/package-upgrade/scripts/

# 所有 .sh 和 .py 檔案應該有 'x' 權限
# 例: -rwxr-xr-x  detect_env.sh
```

#### 2.4 測試 Helper Scripts

```bash
# Python 環境偵測
bash ~/.claude/skills/package-upgrade/scripts/detect_env.sh .

# 應該輸出 JSON，例:
# {
#   "pkg_manager": "pip",
#   "python_version": "3.11.4",
#   ...
# }
```

```bash
# JS 環境偵測 (在 JS 專案根目錄)
bash ~/.claude/skills/package-upgrade/scripts/detect_env_js.sh .

# Go 環境偵測 (在 Go 專案根目錄)
bash ~/.claude/skills/package-upgrade/scripts/detect_env_go.sh .
```

```bash
# 測試 dep_tree.py / ast_scanner.py
python3 ~/.claude/skills/package-upgrade/scripts/dep_tree.py . requests
python3 ~/.claude/skills/package-upgrade/scripts/ast_scanner.py . requests
```

#### 2.5 檢查 Python 依賴

```bash
pipdeptree --version
python3 -c "import requests; print(requests.__version__)"
```

#### 2.6 檢查 JS helper 依賴 (僅 JS 專案需要)

```bash
ls ~/.claude/skills/package-upgrade/scripts/node_modules >/dev/null && echo "JS helpers OK"
```

### 方法 3: 在 Claude Code 中驗證

#### 3.1 啟動 Claude Code

```bash
claude
```

#### 3.2 列出 Skills

在 Claude Code 中輸入：
```
list available skills
```

你應該會看到 `package-upgrade` 出現在列表中。

#### 3.3 查看 Skill 資訊

```
show me the package-upgrade skill
```

Claude Code 應該會顯示 skill 的描述和觸發條件 (應該涵蓋 Python / JavaScript / TypeScript / Go)。

#### 3.4 測試觸發 Skill (Dry Run)

```
檢查這個專案能不能升級 requests 套件
```

或：

```
分析一下升級 axios 會有什麼影響
```

**注意**：不要直接說「升級 requests」，因為會真的執行升級！

---

## 常見問題排除

### Q1: 找不到 Skill

```bash
# 確認目錄存在
ls ~/.claude/skills/package-upgrade/SKILL.md

# 確認 frontmatter 格式正確
head -25 ~/.claude/skills/package-upgrade/SKILL.md
```

**解決**：
- 確保 SKILL.md 的 frontmatter 使用 `---` 包圍
- 確保 `name: package-upgrade` 沒有多餘空格
- 重啟 Claude Code

### Q2: "Permission denied" 執行 scripts

```bash
chmod +x ~/.claude/skills/package-upgrade/scripts/*.sh
chmod +x ~/.claude/skills/package-upgrade/scripts/*.py
```

### Q3: Python scripts 找不到

```bash
ls -la ~/.claude/skills/package-upgrade/scripts/*.py
# 缺檔則從 repo 重新複製
cp /path/to/package-upgrade/scripts/*.py ~/.claude/skills/package-upgrade/scripts/
chmod +x ~/.claude/skills/package-upgrade/scripts/*.py
```

### Q4: 缺少 Python 依賴

```bash
pip install pipdeptree requests
```

### Q5: jq 命令找不到

```bash
brew install jq        # macOS
sudo apt-get install jq  # Ubuntu / Debian
```

### Q6: JS helper 缺 `node_modules`

```bash
cd ~/.claude/skills/package-upgrade/scripts && npm install
```

### Q7: `yarn` 找不到 / corepack 沒啟用

```bash
corepack enable
```

不要硬寫 `yarn` 命令；Skill 會用 `detect_env_js.sh` 解析的 `pkg_manager_bin`
(例 `node .yarn/releases/yarn-3.8.2.cjs`)。

### Q8: Go `govulncheck` 找不到

```bash
go install golang.org/x/vuln/cmd/govulncheck@latest
# 確認 $GOPATH/bin 在 PATH
```

### Q9: Jira 抓不到 ticket

- 檢查 MCP 連線：`claude mcp list | grep -i atlassian`
- 改用 REST + API Token (參考 `package-upgrade/README.md` Atlassian 一節)

---

## 進階驗證: 完整測試

### Python 測試專案

```bash
mkdir -p /tmp/test-pkg-upgrade-py && cd /tmp/test-pkg-upgrade-py
python3 -m venv .venv && source .venv/bin/activate
pip install requests==2.28.0
echo "requests==2.28.0" > requirements.txt
cat > test_app.py <<'EOF'
import requests

def fetch_data(url):
    return requests.get(url).json()
EOF
git init && git add . && git commit -m "Initial commit"

# 啟動 Claude Code 並下 Dry Run
claude
# 輸入: 檢查 requests 套件能不能從 2.28.0 升級到 2.32.0
```

### JS / TS 測試專案

```bash
mkdir -p /tmp/test-pkg-upgrade-js && cd /tmp/test-pkg-upgrade-js
npm init -y
npm install axios@1.6.0
git init && git add . && git commit -m "Initial commit"
claude
# 輸入: 分析 axios 升到 1.7.0 的影響
```

### Go 測試專案

```bash
mkdir -p /tmp/test-pkg-upgrade-go && cd /tmp/test-pkg-upgrade-go
go mod init example.com/test
go get github.com/spf13/cobra@v1.7.0
cat > main.go <<'EOF'
package main

import "github.com/spf13/cobra"

func main() {
    cmd := &cobra.Command{Use: "demo"}
    _ = cmd.Execute()
}
EOF
git init && git add . && git commit -m "Initial commit"
claude
# 輸入: 分析升 cobra 到 v1.8.0 的影響
```

**不要讓它真的執行升級！** 這只是測試 Skill 是否能正常運作。

---

## 驗證檢查清單

- [ ] `~/.claude/skills/package-upgrade/` 目錄存在
- [ ] `SKILL.md` 存在且 frontmatter 涵蓋 Python / JS / TS / Go
- [ ] `README.md` 和 `LICENSE` 存在
- [ ] `scripts/` 包含三軌 helper (Python / JS / Go)
- [ ] `references/` 包含 Python / JS / Go / 跨語言 references
- [ ] `templates/report_structure.md` 存在
- [ ] 所有 `.sh` / `.py` 檔案有執行權限
- [ ] Python scripts 有正確的 shebang (`#!/usr/bin/env python3`)
- [ ] `pipdeptree` / `requests` 已安裝
- [ ] (JS / TS 專案) `scripts/node_modules/` 存在
- [ ] (Go 專案) `govulncheck` / `apidiff` 已安裝
- [ ] `jq` 命令可用
- [ ] Claude Code 可以列出 package-upgrade skill
- [ ] 測試專案中可以觸發 skill

全部打勾即安裝成功! ✅
