# Package Upgrade / CVE Fix Skill for Claude Code

> 自動化 Python / JavaScript / TypeScript / Go 套件升級與 CVE / BDSA / GHSA 漏洞修復的 Claude Code Skill

一個基於 Claude Code 的智能套件升級助手，能夠：
- 🔍 自動分析 breaking changes (從 changelog + git diff，附 source URL / commit SHA)
- 🛠️ 自動修改受影響的程式碼 (AST 掃描 → unified diff 預覽 → 使用者確認)
- ✅ 自動執行測試並做三向診斷 (SOURCE_CODE / TEST_CODE / BOTH / CONFIG)
- 📝 產出完整的遷移報告、commit、PR
- 🔒 支援 CVE / BDSA / GHSA 漏洞修復與風險評估
- 🎫 支援 Jira ticket 觸發 (URL 或 issue key)，完成後回寫 comment + transition

支援語言與套件管理工具：

| 語言 | 套件管理工具 |
|------|--------------|
| Python | `pip` (含 pip-tools 與自定義 lock)、`poetry`、`uv` |
| JavaScript / TypeScript | `npm`、`yarn 3` (corepack)；TypeScript `.d.ts` API surface diff |
| Go | `go modules`；major version path rewrite (v1 → v2+)、`apidiff`、`govulncheck` reachability、vendor mode、`go.work` workspace、`replace` directives |

語言偵測順序 (Phase 0)：**Go > JS > Python**。

---

## 安裝

### 前置需求

1. **Claude Code CLI** (版本 ≥ 1.0)
   - 安裝說明：<https://docs.anthropic.com/claude/docs/claude-code>

2. **Python 環境** (helper scripts 使用)
   - Python 3.8+
   - `pip install pipdeptree requests`

3. **Git**
   - git CLI (建立分支與 PR)
   - `gh` CLI (可選，自動建立 GitHub PR；`install.sh` 偵測缺失時會詢問是否安裝)

4. **Node.js** (若會升級 JS / TS 專案)
   - Node.js ≥ 18 (corepack 內建)
   - 安裝完成後 `install.sh` 會在 skill 的 `scripts/` 內自動跑 `npm install`

5. **Go toolchain** (若會升級 Go 專案)
   - Go ≥ 1.21
   - (可選) `go install golang.org/x/vuln/cmd/govulncheck@latest`
   - (可選) `go install golang.org/x/exp/cmd/apidiff@latest`

6. **Atlassian MCP** (可選，啟用 Jira 觸發)
   - 只在你想用 Jira URL / Jira ID 觸發時需要
   - 細節見下方「可選: Atlassian MCP 安裝」

### 安裝步驟

#### 方法 1: 用 repo 根目錄的 `install.sh` (最簡單)

```bash
git clone https://github.com/millerlai/auto-package-migration.git
cd auto-package-migration

# 全域安裝 (推薦)
bash install.sh

# 或專案級安裝
bash install.sh --project
```

Windows 使用者：直接執行 `install.bat`，或在 Cygwin 環境用 `install-cygwin64.sh`。

#### 方法 2: 手動全域安裝

```bash
# 1. Clone repo
git clone https://github.com/millerlai/auto-package-migration.git

# 2. 複製到 Claude Code 全域 skills 目錄
mkdir -p ~/.claude/skills/
cp -r auto-package-migration/package-upgrade ~/.claude/skills/

# 3. 賦予 scripts 執行權限
chmod +x ~/.claude/skills/package-upgrade/scripts/*.sh
chmod +x ~/.claude/skills/package-upgrade/scripts/*.py

# 4. 若會升級 JS / TS 專案 — 安裝 JS helper deps
cd ~/.claude/skills/package-upgrade/scripts && npm install && cd -
```

#### 方法 3: 專案級安裝

```bash
cd /path/to/your/project
mkdir -p .claude/skills/
cp -r /path/to/auto-package-migration/package-upgrade .claude/skills/
chmod +x .claude/skills/package-upgrade/scripts/*.{sh,py}

# (可選) 加入 .gitignore
echo ".claude/skills/package-upgrade/" >> .gitignore
```

### 可選: Atlassian MCP 安裝 (Jira 整合)

啟用後可用 Jira URL (例 `https://trendmicro.atlassian.net/browse/V1E-148968`)
或 Jira ID (例 `V1E-148968`) 觸發升級流程，完成後自動 comment 報告回 ticket，
並依目前 ticket 狀態詢問轉換 (To Do → Ready for Work → Development → Done)。

#### 路徑 A: claude.ai connectors (推薦)

最簡單的方式，多半已預裝。確認：

```bash
claude mcp list | grep -i atlassian
```

預期輸出：
```
claude.ai Atlassian Rovo: https://mcp.atlassian.com/v1/mcp - ✓ Connected
```

若顯示 `! Needs authentication` → 啟動 Claude Code 後執行 `/mcp` 登入即可，
無需手動配置 token。

#### 路徑 B: 自架 MCP + API token (適合 CI 或無 OAuth 的情境)

```bash
# 1. 取得 Atlassian API token：https://id.atlassian.com/manage-profile/security/api-tokens
# 2. 註冊 MCP server (token 會寫入 ~/.claude.json)
claude mcp add atlassian \
  --env ATLASSIAN_SITE=trendmicro.atlassian.net \
  --env ATLASSIAN_EMAIL=you@example.com \
  --env ATLASSIAN_API_TOKEN=<your_token> \
  -- npx -y @modelcontextprotocol/server-atlassian

# 3. 驗證
claude mcp list | grep atlassian
```

⚠️ Token 會寫入 `~/.claude.json`，建議：
- 使用最小權限的 token (僅讀寫所需 project)
- 用完後到 Atlassian 後台 revoke

#### 路徑 C: 不安裝 MCP，用 REST API fallback

Skill 內建 fallback — 若 MCP 不可用，會主動詢問你是否提供 API token，
然後透過 `scripts/jira_fetch.py` / `jira_comment.py` / `jira_transition.py`
直接呼叫 REST API。Token 只在當前 session 暫存，**不寫入任何檔案**。

⚠️ 這個模式下 token 會出現在對話 transcript 中，慎用。

### 驗證安裝

```bash
# 從 repo 根目錄
bash verify_installation.sh

# 或直接讓 Claude Code 列出 skills
claude
# 然後在 Claude Code 中輸入: "list available skills"
# 你應該會看到 package-upgrade 出現在列表中
```

---

## 快速開始

直接在 Claude Code 中輸入升級指令：

```bash
claude
```

然後輸入以下任一指令：

```
升級 requests 到 2.32.0
bump axios to 1.7.0
go get -u github.com/spf13/cobra@v1.8.0
修復 CVE-2024-35195
處理這張 Jira ticket: https://trendmicro.atlassian.net/browse/V1E-148968
V1E-148968
看看 django 能不能從 4.2 升到 5.1
```

### 使用範例

#### 範例 1: 直接升級到指定版本 (Python)

```
使用者: 升級 requests 到 2.32.0

Claude Code:
1. 偵測語言 → python；偵測環境 → 使用 pip
2. 分析依賴 → requests 是直接引用
3. 雙軌分析 breaking changes (changelog + git diff)
4. AST 掃描專案程式碼 → 找到 5 處受影響
5. 產生修改建議 → 展示 unified diff 並等待確認
6. 建立分支 feature/Update-requests-to-2.32.0
7. 套用修改 → 更新 pyproject.toml/requirements.txt + lock
8. 分層執行測試 (受影響 → 全部)
9. 產出報告 → 建立 PR (附 changelog URL + commit SHA 證據)
```

#### 範例 2: JS / TS 升級

```
使用者: bump axios to 1.7.0

Claude Code:
1. 偵測語言 → javascript；偵測環境 → npm
2. 分析依賴 → axios 為直接引用
3. 雙軌 breaking change 分析 + TypeScript .d.ts API surface diff
4. AST 掃描 .ts/.js → 標示需要調整的 axios 呼叫
5. 套用修改 + 更新 package.json + package-lock.json
6. jest / vitest 執行測試
```

#### 範例 3: Go 大版本跳躍

```
使用者: 把 github.com/spf13/viper 從 v1 升到 v2

Claude Code:
1. 偵測語言 → go；major version jump 偵測到
2. 列出所有需要改成 /v2 的 import path (read references/go_major_version_paths.md)
3. 等待使用者確認
4. 同時改 go.mod、所有 *.go 的 import、必要的程式碼調整
5. go vet / go build / go test 驗證
```

#### 範例 4: CVE / BDSA / GHSA 修復

```
使用者: 修復 CVE-2024-35195

Claude Code:
1. 搜尋 CVE 資訊 → 找到受影響的套件: requests
2. (Go 專案會跑 govulncheck 做 reachability 分析)
3. 評估風險 → critical (專案直接使用受影響功能)
4. 找到修復版本 → 2.32.0
5. (後續流程同範例 1)
6. 建立分支 fix/CVE-2024-35195-requests
7. PR 標記為 security label
```

BDSA 編號 (Black Duck) 與 GHSA (GitHub Security Advisory) 同樣支援，
參考 `references/bdsa_mapping.md` 對應到上游 CVE。

#### 範例 5: Transitive 套件升級

```
使用者: 升級 urllib3 到 2.2.0

Claude Code:
1. dep_tree 發現 urllib3 不是直接引用，被 requests 拉進來
2. 檢查 requests 的版本約束是否允許 urllib3 2.2.0
3.   若允許 → 只更新 lock 檔案 (不動 pyproject.toml / package.json / go.mod)
4.   若擋住 → 列出 parent 約束，提出三種選擇：
        [A] 升 parent (列出每個 parent 的最新版能否解開)
        [B] 放棄
        [C] 你自己選一個中間版本
```

#### 範例 6: 依賴衝突處理

```
使用者: 升級 pydantic 到 2.0

Claude Code:
1. 偵測依賴 → pydantic 被 fastapi 和 sqlmodel 依賴
2. 發現衝突 → fastapi 要求 pydantic<2.0
3. 提出 3 種解決方案 (附風險評估與工作量預估):
   - 方案 A: 同時升級 fastapi 到 0.100+ (推薦)
   - 方案 B: 使用 pydantic 1.10 (中間版本)
   - 方案 C: 使用 pip --force-reinstall (風險高)
4. 等待使用者選擇 → 使用者選 A
5. (繼續升級流程)
```

#### 範例 7: 從 Jira ticket 觸發

```
使用者: https://trendmicro.atlassian.net/browse/V1E-148968

Claude Code:
1. 用 Atlassian MCP 抓取 ticket 內容
   ├── 若 401/403 → 詢問是否提供 API token (REST fallback)
   └── 若 200 → 解析
2. 從 summary/description 抽出: 套件 = requests, 目標版本 = 2.32.0
3. 列出解析結果並等待確認 ✋
4. (執行標準升級流程 Phase 2-7)
5. 升級完成後:
   ├── 確認後將遷移報告 comment 回 ticket ✋ (帶 PR URL、changelog URL)
   └── 詢問是否依目前狀態 transition ✋
        ├── [Y] → To Do → Ready for Work → Development → Done 分階段推進
        ├── [O] → 列出所有 transitions 讓你挑
        └── [N] → 保持目前狀態
```

最終留下的 git artifacts：
```
Branch:  feature/V1E-148968-Update-requests-to-2.32.0
Commit:  [V1E-148968] chore(deps): upgrade requests to 2.32.0
         <body>
         Jira: https://trendmicro.atlassian.net/browse/V1E-148968
PR:      Title: [V1E-148968] chore: upgrade requests to 2.32.0
         Body 第一行: Jira: https://trendmicro.atlassian.net/browse/V1E-148968
```

---

## 功能說明

### 自動化分析

- ✅ **語言 + 環境偵測**: 順序 Go > JS > Python；Python 自動辨識 pip / poetry / uv，JS 辨識 npm / yarn 3
- ✅ **依賴樹分析**: 判斷直接 / 間接引用，識別版本衝突
- ✅ **Breaking Change 分析**:
  - 解析 Changelog (PyPI / npm / GitHub Releases / repo CHANGELOG)
  - 分析 Git Diff (tag 之間的程式碼變更)
  - 交叉驗證並合併結果，保留 source URL + commit SHA 供報告引用
  - JS / TS 額外做 `.d.ts` API surface diff；Go 額外跑 `apidiff`
- ✅ **程式碼影響掃描**: AST 靜態分析找出所有受影響的使用位置
- ✅ **CVE 風險評估**: 判斷漏洞是否實際影響專案用法
  - Go 額外用 `govulncheck` 做 reachability 分析

### 智能修改

- ✅ 理解程式碼上下文，生成符合專案風格的修改
- ✅ 保持原有縮排、引號、命名慣例
- ✅ 只修改受影響的部分，不做無關的「改進」
- ✅ 提供完整 diff 預覽，等待確認後才套用

### 測試診斷

- ✅ 分層執行測試 (先跑受影響的，再跑全部)
- ✅ 三向交叉分析失敗原因 (SOURCE_CODE / TEST_CODE / BOTH / CONFIG)
- ✅ 自動修復或提供修改建議
- ✅ 最多 3 次迴圈，避免無限嘗試

### Git / PR / Jira 整合

- ✅ 強制建立 feature branch: `feature/{ISSUE_KEY}-Update-{Package}-to-{Version}` (Jira 觸發) 或 `feature/Update-{Package}-to-{Version}` (一般)
- ✅ 環境備份與回退機制 (Python `snapshot_env.sh`、JS `snapshot_env_js.sh`、Go `snapshot_env_go.sh`)
- ✅ Conventional Commits + Jira-aware：subject `[ISSUE_KEY] type(scope): description`，body 帶 `Jira: <full URL>`
- ✅ 自動建立 Pull Request (`gh` CLI)；title 含 `[ISSUE_KEY]`、body 第一行為 Jira URL
- ✅ Jira 自動 comment 報告回 ticket，並依目前狀態詢問 transition

### 報告產出

- ✅ Executive Summary
- ✅ 依賴分析詳情
- ✅ Breaking Changes 清單 (附 changelog URL + commit SHA)
- ✅ 程式碼修改說明
- ✅ 測試結果
- ✅ 後續建議
- ✅ 回退指南

---

## 使用者確認點

此 Skill 在以下時間點會暫停並等待你的確認：

| 時間點 | 說明 |
|--------|------|
| **Jira ticket 解析** | 從 ticket 抽到的 package/版本/驗收條件，等你校正 (僅 Jira 觸發) |
| **Pip lock 檔案處理** | 偵測到 `requirements.lock` 等非標準 lock 時，詢問產生方式 |
| **依賴衝突** | 如有多種解決方案，會列出風險評估並等待選擇 |
| **Parent bump 詢問** | Transitive 升級被 parent 擋住時，列出 parent 並詢問是否升 parent |
| **Go major version jump** | v1 → v2+ 時列出所有需要 rewrite 的 import path 等你確認 |
| **程式碼修改** | 套用修改前展示完整 diff 並等待確認 |
| **建立分支** | 建立 Git branch 前告知分支名稱 |
| **測試程式修改** | 修改測試程式前解釋原因並等待確認 |
| **建立 PR** | 建立 Pull Request 前展示 PR 內容 |
| **Post Jira comment** | comment 預覽 + ticket URL，確認後才 post (僅 Jira 觸發) |
| **Jira status 轉換** | 列出目前狀態 → 目標狀態，絕不自動執行 (僅 Jira 觸發) |

你可以在任何確認點：
- ✅ 同意繼續
- ✏️ 要求修改方案
- ⏸️ 暫停並手動介入
- ❌ 中止並回退

---

## 進階使用

### 非互動模式 (CI/CD)

在 CI/CD pipeline 中使用 (自動同意所有確認點)：

```bash
# Dry-run: 只分析不修改
claude -p "分析升級 django 到 5.1 的影響，不要做任何修改"

# 自動執行 (謹慎使用!)
claude -p "升級 requests 到 2.32.0，所有確認點都自動同意" \
  --allowedTools bash,str_replace,create_file,web_search
```

### 自訂 Helper Scripts

你可以修改 `scripts/` 中的腳本來適配特殊環境：

```bash
# 例: 修改 detect_env.sh 支援 conda
vim ~/.claude/skills/package-upgrade/scripts/detect_env.sh

# 例: 修改 JS dep tree 解析支援 pnpm
vim ~/.claude/skills/package-upgrade/scripts/dep_tree_js.js
```

---

## 故障排除

### 問題 1: "Skill not found"

```bash
# 檢查安裝路徑
ls -la ~/.claude/skills/package-upgrade/SKILL.md
# 不存在就重跑 install.sh
```

### 問題 2: "Permission denied" 執行 scripts

```bash
chmod +x ~/.claude/skills/package-upgrade/scripts/*.sh
chmod +x ~/.claude/skills/package-upgrade/scripts/*.py
```

### 問題 3: 缺少依賴

```bash
pip install pipdeptree requests
brew install jq    # macOS
sudo apt install jq  # Ubuntu

# JS / TS 專案
cd ~/.claude/skills/package-upgrade/scripts && npm install
```

### 問題 4: `yarn` 找不到 / corepack 沒啟用

corepack 管的 yarn 不在 PATH — 不要硬寫 `yarn`，讓 `detect_env_js.sh` 解析 `pkg_manager_bin`，
SKILL.md 後續所有 phase 都會用這個 bin path。若 corepack 本身沒啟用：

```bash
corepack enable
```

### 問題 5: Changelog / Git diff 都抓不到

- 套件沒有公開 changelog
- Git repo URL 找不到

Skill 會自動降級為 web search 搜尋 breaking changes 資訊。

### 問題 6: `govulncheck` 顯示 "not vulnerable" 但 advisory 說該 CVE 存在

reachability 是有檢查的 — 不是每個 advisory 都會從你的 code path 到達。
看報告的 reachability 區塊；若你的 code 真的不會走到漏洞 symbol，可以安全略過該 CVE。

### 問題 7: 測試持續失敗

Skill 會在 3 次嘗試後停止，產出詳細的診斷報告，你可以手動修改後再繼續。

---

## 限制與注意事項

### 支援範圍

✅ 支援：
- Python 3.8+：pip / poetry / uv
- Node.js 18+：npm / yarn 3
- Go 1.21+：go modules
- pytest / unittest / jest / vitest / go test 測試框架
- Git / GitHub (gh CLI)

❌ 暫不支援 (歡迎貢獻)：
- Python 2.x
- pipenv / conda
- pnpm / bun (規劃中)
- Ruby / Rust / Java

### 安全考量

- ⚠️ Skill 會執行 bash 命令和修改程式碼，請在可信任的環境中使用
- ✅ 所有修改前都會建立環境備份
- ✅ 所有程式碼修改都會展示 diff 並等待確認
- ✅ 在獨立的 Git branch 上工作，不影響 main branch
- ✅ Auth token 透過 `save_token.sh` 寫入 (chmod 600 + 自動加 `.gitignore`)

### 最佳實踐

1. **先測試**: 在小專案上先試用，熟悉流程
2. **看 Diff**: 仔細檢查程式碼修改 diff 再確認
3. **跑測試**: 即使 Skill 說測試通過，自己也要再跑一次
4. **Code Review**: 用 PR 讓團隊 review 修改內容

---

## 貢獻

歡迎貢獻！請：

1. Fork 此專案 (`millerlai/auto-package-migration`)
2. 建立 feature branch: `git checkout -b feature/your-feature`
3. Commit 變更: `git commit -m 'feat: add some feature'`
4. Push 到 branch: `git push origin feature/your-feature`
5. 建立 Pull Request

### 貢獻方向

- 新增套件管理工具支援 (conda / pipenv、pnpm / bun)
- 跨語言移植 (Ruby / Rust / Java)
- 改進 breaking change 偵測 patterns
- 增加測試框架支援
- 改進三向診斷邏輯
- 整合更多 issue tracker (GitHub Issues / GitLab Issues / Linear)

---

## 授權

MIT License

---

## 聯絡

- Issues: <https://github.com/millerlai/auto-package-migration/issues>
- Discussions: <https://github.com/millerlai/auto-package-migration/discussions>

---

## 致謝

- [Claude Code](https://claude.ai/code) by Anthropic
- [Atlassian Rovo MCP](https://www.atlassian.com/) — Jira / Confluence 整合
- [pipdeptree](https://github.com/tox-dev/pipdeptree)
- [poetry](https://python-poetry.org/) / [uv](https://github.com/astral-sh/uv)
- [corepack](https://nodejs.org/api/corepack.html) — yarn 3 / pnpm shim
- [govulncheck](https://pkg.go.dev/golang.org/x/vuln/cmd/govulncheck) / [apidiff](https://pkg.go.dev/golang.org/x/exp/cmd/apidiff)
