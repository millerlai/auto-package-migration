# 安裝與驗證

> 把這個 Claude Code Skill 安裝到本機。三分鐘版 → 手動細節 → 故障排除 → 進階測試。

---

## 三分鐘安裝

### 1. 跑安裝腳本

```bash
# macOS / Linux                    # 全域安裝（推薦）
bash install.sh
bash install.sh --project          # 改為專案級安裝（./.claude/skills/）
bash install.sh --skip-permissions # 不寫 Claude Code settings.json

# Windows (PowerShell / cmd)
install.bat

# Cygwin64（會額外幫你裝 gh CLI）
bash install-cygwin64.sh
```

`install.sh` 自動完成：
1. 複製 `package-upgrade/` 與 `package-upgrade-feedback/` 到 `~/.claude/skills/`（或 `./.claude/skills/`）
2. 設定 scripts 執行權限（遞迴 chmod 各語言子資料夾）
3. 檢查並安裝 Python 依賴：`pipdeptree`、`requests`
4. 在 `scripts/javascript/` 內跑 `npm install`（JS / TS 用）
5. 偵測 `gh` CLI 是否安裝與認證（缺則協助安裝、`gh auth login`）
6. 把允許清單寫入 Claude Code `settings.json`（除非 `--skip-permissions`）

### 2. 驗證

```bash
# macOS / Linux / Cygwin64
bash verify_installation.sh

# Windows (PowerShell / cmd)
verify_installation.bat
```

預期看到 `✓ 安裝驗證通過!`。

### 3. 開始使用

```bash
claude
```

然後在對話中下達任一種觸發語句：

```text
# Python
升級 requests 到 2.32.0
修復 CVE-2024-35195

# JavaScript / TypeScript
bump axios to 1.7.0
update typescript to 5.5.0

# Go
go get -u github.com/spf13/cobra@v1.8.0
把 github.com/spf13/viper 從 v1 升到 v2

# Jira 觸發（需 Atlassian MCP 或 API token）
https://trendmicro.atlassian.net/browse/V1E-148968
V1E-148968
```

---

## 手動安裝（不跑 `install.sh`）

```bash
# 1. 複製 skill
cp -r package-upgrade ~/.claude/skills/

# 2. 設定執行權限（per-language reorg 後要遞迴）
find ~/.claude/skills/package-upgrade/scripts \( -name '*.sh' -o -name '*.py' -o -name '*.js' \) -exec chmod +x {} +

# 3. Python 依賴
pip install pipdeptree requests

# 4. JS helper 依賴（JS / TS 專案才需要）
cd ~/.claude/skills/package-upgrade/scripts/javascript && npm install && cd -

# 5. Go 工具（可選，Go 專案才需要）
go install golang.org/x/vuln/cmd/govulncheck@latest
go install golang.org/x/exp/cmd/apidiff@latest

# 6. 系統工具
brew install jq gh             # macOS
sudo apt-get install jq        # Debian / Ubuntu；gh 依官方說明 https://cli.github.com/
```

---

## 重要提醒

### 語言偵測順序：Go > JS > Python

多語言混合專案（同時存在 `go.mod` + `package.json` + `pyproject.toml`）會主動詢問升的是哪邊。

### Pip lock 檔案

如果你的 Python 專案有 lock 檔案（`requirements.lock` / `requirements.txt` from `pip-compile` / 自定義腳本），skill 會詢問如何重新產生：

```text
📋 偵測到專案使用 lock 檔案: requirements.lock

請選擇 lock 檔案產生方式:
[1] 使用 pip freeze (標準方式)
[2] 使用專案自定義腳本 (請告訴我命令)
[3] 我會手動處理，請繼續下一步
```

詳見 `package-upgrade/references/python/pip_lock_patterns.md`。

### Poetry / UV 必須用對命令

```bash
# ❌ 錯誤 — 只動 lock，不會更新 pyproject.toml
poetry update requests
uv lock --upgrade-package requests

# ✅ 正確 — 同時更新 manifest + lock
poetry add requests@2.32.0
uv add "requests>=2.32.0"
```

詳見 `package-upgrade/references/common/important_dependency_update.md`。

### Yarn 3 / pnpm 走 corepack

corepack-managed yarn / pnpm 通常**不在 PATH**。Skill 會用 `detect_env.sh` 解析出的 `pkg_manager_bin`（例 `node .yarn/releases/yarn-3.8.2.cjs`），不要在自定義腳本裡 hard-code `yarn` / `pnpm`。

### Go major version jump

從 `v1` 升到 `v2+` 時，skill 會列出所有要 rewrite 的 import path（`github.com/spf13/viper` → `github.com/spf13/viper/v2`），等你確認後一次改完。詳見 `package-upgrade/references/go/major_version_paths.md`。

---

## 使用者確認點

Skill 會在以下時間點暫停等你確認、不會自動執行：

1. Jira ticket 解析結果（package / 版本 / 驗收條件）— 僅 Jira 觸發
2. Pre-flight 偵測到 blocker（缺 token、git tree 不乾淨等）
3. Phase 2 升級策略選擇（direct_bump / bump_override / bump_parent / lock_only / add_replace 等）
4. Pip lock 檔案產生方式
5. Go major version jump 的 import path rewrite 預覽
6. Phase 4 程式碼修改 unified diff
7. 建立 Git 分支
8. 測試程式修改的理由
9. 建立 PR（PR 內容預覽）
10. Post Jira comment（預覽 + ticket URL）— 僅 Jira 觸發
11. Jira status transition — 僅 Jira 觸發

任何時點都可以同意 / 修改 / 暫停 / 中止。

---

## 故障排除

### Skill 找不到

```bash
ls ~/.claude/skills/package-upgrade/SKILL.md       # 確認檔案存在
head -25 ~/.claude/skills/package-upgrade/SKILL.md  # 確認 frontmatter
```

`name: package-upgrade` 不能有多餘空格，frontmatter 用 `---` 包圍。改完重啟 Claude Code。

### Permission denied

```bash
find ~/.claude/skills/package-upgrade/scripts \( -name '*.sh' -o -name '*.py' -o -name '*.js' \) -exec chmod +x {} +
```

### Python 依賴缺

```bash
pip install pipdeptree requests
```

### `jq` 命令找不到

```bash
brew install jq                  # macOS
sudo apt-get install jq          # Ubuntu / Debian
```

### JS helper 缺 `node_modules`

```bash
cd ~/.claude/skills/package-upgrade/scripts/javascript && npm install
```

### `yarn` 找不到 / corepack 沒啟用

```bash
corepack enable
```

### Go `govulncheck` 找不到

```bash
go install golang.org/x/vuln/cmd/govulncheck@latest
# 確認 $GOPATH/bin 在 PATH
```

### Jira 抓不到 ticket

- 檢查 MCP 連線：`claude mcp list | grep -i atlassian`
- 或改用 REST + API token，見 `package-upgrade/references/common/jira_workflow.md`

---

## 進階：測試專案範本

要在不弄髒實際專案的情況下試 skill，建議用以下三個一次性測試專案。**不要直接讓 skill 真的執行升級**（用 dry-run 性質的「分析」、「檢查」措辭，而非「升級」）。

### Python

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
claude
# 在對話中輸入: 檢查 requests 套件能不能從 2.28.0 升級到 2.32.0
```

### JavaScript / TypeScript

```bash
mkdir -p /tmp/test-pkg-upgrade-js && cd /tmp/test-pkg-upgrade-js
npm init -y
npm install axios@1.6.0
git init && git add . && git commit -m "Initial commit"
claude
# 在對話中輸入: 分析 axios 升到 1.7.0 的影響
```

### Go

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
# 在對話中輸入: 分析升 cobra 到 v1.8.0 的影響
```

---

## 文件導覽

- **入口介紹** → 根 `README.md` / `README.zh-TW.md`
- **這份** → `docs/installation.md`
- **貢獻 / 開發** → 根 `CONTRIBUTING.md`
- **專案狀態** → `docs/project-status.md`
- **變更歷史** → `CHANGELOG.md`
- **Skill 使用** → `package-upgrade/README.md`
- **Skill 工作流程細節** → `package-upgrade/SKILL.md`（Phase 0-7）
- **套件管理工具命令對照** → `package-upgrade/QUICK_REFERENCE.md`
- **語言專屬參考** → `package-upgrade/references/{common,python,javascript,go}/*.md`
