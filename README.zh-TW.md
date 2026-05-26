# Package Upgrade Skill for Claude Code

繁體中文 · [English](README.md)

一個 [Claude Code Skill](https://docs.claude.com/en/docs/claude-code/skills)，自動化 **Python**、**JavaScript / TypeScript**、**Go** 三大語言的套件升級、CVE 漏洞修復，以及 Jira ticket 驅動的維護工作。從觸發、依賴分析、breaking change 判讀、程式碼修改、測試驗證，到 commit / PR / Jira ticket 回寫，一條 pipeline 跑完。

---

## 🚀 快速開始

### 安裝

```bash
# 全域安裝 (建議，所有專案可用)
bash install.sh

# 或專案級安裝
bash install.sh --project
```

Windows 使用者可改用 `install.bat` (PowerShell) 或 `install-cygwin64.sh` (Cygwin)。

### 驗證

```bash
bash verify_installation.sh
```

### 觸發

以下任一種方式都會觸發這個 skill：

```bash
claude "升級 requests 到 2.32.0"
claude "bump axios to 1.7.0"
claude "go get -u github.com/spf13/cobra@v1.8.0"
claude "修復 CVE-2024-35195"
claude "https://trendmicro.atlassian.net/browse/V1E-148968"
claude "V1E-148968"
claude "看看 django 能不能從 4.2 升到 5.1"
```

---

## ✨ 功能特色

### 觸發方式
- 📦 **套件名稱 + 目標版本** — 一般升級
- 🔒 **CVE / BDSA / GHSA 編號** — 自動查 NVD / OSV / GitHub Advisory，對照專案實際使用方式評估風險
- 🎫 **Jira URL 或 Issue Key** — 自動讀 ticket、分析該升級什麼，完成後 comment 報告回 ticket，並依使用者同意 transition 狀態

### 語言支援
| 語言 | 套件管理工具 | 額外能力 |
|------|--------------|----------|
| Python | `pip`、`poetry`、`uv` | pip-tools (`requirements.in` / `requirements.txt`)、自定義 `requirements.lock`、無 lock 流程 |
| JavaScript / TypeScript | `npm`、`yarn 3` (corepack) | TypeScript `.d.ts` API surface diff；`pnpm` / `bun` 規劃中 |
| Go | `go modules` | major version path rewrite (v1 → v2+)、`apidiff` API surface diff、`govulncheck` reachability、vendor mode、`go.work` workspace、`replace` directives |

語言偵測順序 (Phase 0)：**Go > JS > Python**。

### 升級分析
- 🌳 **依賴分析** — 區分 direct / transitive / both，識別 parent 約束衝突
- 🪶 **Transitive lock-only 路徑** — transitive package 升級且 parent 約束允許時，**只刷 lock 檔案，不動宣告檔**
- 🔁 **Parent 阻擋處理** — parent 鎖定版本擋住升級時，列出每個阻擋的 parent 與版本範圍，詢問使用者「升 parent / 放棄 / 自選」
- 🔬 **雙軌 Breaking Change 分析** — 同時讀 Changelog (PyPI / npm / GitHub Releases / repo `CHANGELOG`) 與 Git Diff (tag 對 tag 的原始碼 diff)，交叉驗證
- 📚 **可追溯來源** — 報告會具體寫出 Changelog URL、git diff 的舊新 tag、舊新 commit SHA、compare URL，reviewer 可直接驗證

### 程式碼修改
- 🌲 **AST 掃描** — 解析專案中所有 import 與 symbol 使用點，精準定位 Phase 3 breaking change 的影響範圍
- 🧠 **上下文感知修改** — 結合 breaking change 與專案程式碼風格生成修改，逐一附 unified diff 預覽
- ✅ **每一次程式碼修改都必須使用者確認**

### 測試與診斷
- 🎯 **分層測試** — 先跑受影響的測試，全綠後再跑完整測試
- 🔍 **三向診斷** — 失敗時同時讀 traceback / 測試碼 / 業務碼 / breaking change 清單，分類為 `SOURCE_CODE` / `TEST_CODE` / `BOTH` / `CONFIG`
- 🤝 **測試碼修改同樣必須使用者確認**
- 🔁 **修補迴圈上限 3 輪**，避免無窮迴圈

### Git / PR / Jira 整合
- 🌿 **強制建立 feature branch** — `feature/{ISSUE_KEY}-Update-{pkg}-to-{ver}` (Jira 觸發) 或 `feature/Update-{pkg}-to-{ver}` (一般)
- 📝 **Conventional Commits + Jira-aware** — commit subject `[V1E-148968] type(scope): description`，body 帶 `Jira: <full URL>`
- 🔗 **PR 第一行就是 Jira link** — title `[ISSUE_KEY]`、body 第一行 `Jira: <url>`，reviewer 在 PR 列表卡片就看得到
- 💬 **Jira 自動回寫** — 升級完成後 comment 遷移報告回 ticket，並詢問是否 transition 狀態 (Done / Resolved / Fixed 等同義詞自動 match)

### Go 專屬保護
- ⚠️ **Major version path rewrite** — 從 `v1` 升到 `v2+` 時，skill 會把 codebase 裡的 import path (`example.com/foo` → `example.com/foo/v2`) 全部改掉，不是只動 `go.mod`
- 🛡️ **govulncheck reachability** — 修 Go CVE 時會檢查漏洞 symbol 是否真的被你的程式呼叫
- 📦 **Vendor / workspace 感知** — 尊重 `vendor/`、`go.work`、`replace` directives，不會誤覆蓋

### 💌 Feedback companion — `/package-upgrade-feedback`

`install.sh` 會同時安裝第二個 skill，用於把改進建議回送到本 repo。觸發詞：`/package-upgrade-feedback`、「改進 package-upgrade」、「report package-upgrade issue」。

- 🧠 **LLM 主動草擬 `Improvement.md`** — 讀 `package-upgrade/SKILL.md`，從外部視角寫 5–10 項 improvement 草稿。草稿**完全不引用**使用者環境、目標套件、CVE / Jira / token、檔案路徑等私人資料。
- ☑️ **多選 + 自由輸入** — 用 `AskUserQuestion`：勾選優先分類，並透過自動附加的 Other 欄位提供自由文字補充。
- 🛡️ **Sanitizer 把關** — 自由輸入會過 `sanitize_feedback.sh`，自動 redact 路徑、token、Jira key、email、私有 IP、內部 hostname。偵測到高信心 secret pattern（`ghp_*`、`AKIA*`、JWT、private-key block…）會強制中斷流程。
- 👀 **送出前 Review** — `y` / `edit` / `n`。選 `y` 後立即跑 `gh issue create`，送到 `millerlai/auto-package-migration` 並標 `feedback` label，**不再二次確認**。
- 🔁 **`gh` 不可用 fallback** — 印出 pre-filled GitHub Issue URL，使用者可貼到瀏覽器手動送出。

---

## 🔄 7-Phase 工作流程

| Phase | 內容 |
|-------|------|
| **0. 環境偵測** | 語言偵測 (Go > JS > Python) → `detect_env*.{sh}` 偵測 pkg manager、版本、lock 模式 |
| **1. 輸入解析** | A. 套件名稱 / B. CVE / BDSA / GHSA (web search + 風險評估) / C. Jira URL or key (MCP 或 REST + API token 抓 ticket) |
| **2. 依賴分析** | `dep_tree*` 取得 `direct` / `transitive` / `both`；transitive 走 lock-only 或 parent-bump 詢問 |
| **3. Breaking Change 分析** | Changelog + Git Diff 雙軌；保留 source URL 與 commit SHA 供報告引用 |
| **4. 程式碼影響分析** | `ast_scanner*` 掃 import / symbol → 結合 Phase 3 breaking change 生成修改建議 |
| **5. 執行升級** | 建分支 → snapshot → 更新依賴宣告檔 + lock (或 lock-only) → 套用程式碼修改 |
| **6. 測試驗證** | 分層執行 → 三向診斷失敗 → 最多 3 輪迴圈 |
| **7. 產出與回寫** | 報告 + commit + push + PR；若 Jira 觸發 → comment + 詢問 transition |

完整工作流程定義：[`package-upgrade/SKILL.md`](package-upgrade/SKILL.md)

---

## 📋 目錄結構

```
auto-package-migration/
├── README.md                          # 英文版
├── README.zh-TW.md                    # 本檔案
├── GETTING_STARTED.md                 # 3 分鐘快速上手
├── INSTALLATION_GUIDE.md              # 詳細安裝指南
├── VERIFICATION_CHECKLIST.md          # 驗證檢查清單
├── DEVELOPMENT.md                     # 開發指南 (UV-based)
├── CONTRIBUTING.md                    # 貢獻指南
├── CHANGELOG.md
├── CLAUDE.md                          # 給 Claude Code 的 repo 層級指示
├── install.sh                         # POSIX 安裝腳本
├── install.bat                        # Windows 安裝腳本
├── install-cygwin64.sh                # Cygwin 安裝腳本 (附 gh CLI)
├── verify_installation.sh
├── grant_permissions.py               # 把 allow-list 寫進 Claude Code settings
├── pyproject.toml / uv.lock           # 本 repo 自己的開發環境 (UV 管理)
│
├── package-upgrade/                   # ⭐ 主升級 Skill (複製到 ~/.claude/skills/)
│   ├── SKILL.md                       # 主技能定義 (Phase 0–7)
│   ├── README.md                      # 終端使用者說明
│   ├── QUICK_REFERENCE.md
│   ├── LICENSE                        # MIT
│   ├── scripts/                       # Helper scripts — 三條平行軌道
│   │   ├── detect_env.sh              # 每一支腳本都有 py / js / go 三個變體
│   │   ├── detect_env_js.sh
│   │   ├── detect_env_go.sh
│   │   ├── dep_tree.py
│   │   ├── dep_tree_js.js
│   │   ├── dep_tree_go.{sh,py}
│   │   ├── ast_scanner.py
│   │   ├── ast_scanner_js.js
│   │   ├── ast_scanner_go.go
│   │   ├── api_surface_diff_js.js     # TypeScript .d.ts surface diff
│   │   ├── api_surface_diff_go.sh     # Go apidiff
│   │   ├── govulncheck_go.sh
│   │   ├── git_diff.sh / git_diff_js.sh / git_diff_go.sh
│   │   ├── fetch_changelog.py
│   │   ├── preflight.sh / preflight_go.sh
│   │   ├── snapshot_env*.sh
│   │   ├── run_tests*.sh
│   │   ├── validate_lockfile.sh / validate_modfile_go.sh
│   │   ├── parse_pm_errors.py
│   │   ├── save_token.sh              # 寫入 auth token (chmod 600 + .gitignore)
│   │   ├── jira_fetch.py / jira_comment.py / jira_transition.py
│   │   └── package.json               # JS helpers 專用的 package.json
│   ├── references/                    # SKILL.md 按需 lazy load
│   │   ├── pip_workflow.md / poetry_workflow.md / uv_workflow.md
│   │   ├── npm_workflow.md / yarn_workflow.md / js_workflow.md
│   │   ├── js_ast_strategy.md
│   │   ├── go_workflow.md
│   │   ├── go_major_version_paths.md
│   │   ├── go_replace_semantics.md
│   │   ├── govulncheck.md
│   │   ├── breaking_change_patterns{,_js,_go}.md
│   │   ├── IMPORTANT_DEPENDENCY_UPDATE.md
│   │   ├── PIP_LOCK_PATTERNS.md
│   │   ├── auth_tokens.md
│   │   ├── bdsa_mapping.md
│   │   └── jira_workflow.md
│   └── templates/
│       └── report_structure.md        # 報告撰寫範本
│
├── package-upgrade-feedback/          # 💌 Companion skill — 把改進建議回送成 GitHub Issue
│   ├── SKILL.md                       # 5-phase 流程：LLM 草擬 → 問 → sanitize → review → 送
│   └── scripts/
│       ├── sanitize_feedback.sh       # redact 路徑 / token / Jira key / email / 私有 IP
│       └── submit_feedback.sh         # `gh issue create` wrapper，附非 gh 環境 URL fallback
│
└── package-upgrade-agent-architecture.md  # 完整架構設計文件
```

---

## 📖 使用範例

### 一般升級

```bash
claude "升級 requests 到 2.32.0"
claude "bump axios to 1.7.0"
claude "go get -u github.com/spf13/cobra@v1.8.0"
```

### CVE 修復

```bash
claude "修復 CVE-2024-35195"
```

Skill 會自動 web search advisory，搜尋專案中對受影響功能的使用方式，產出風險評估 (critical / high / medium / low)。

### Transitive 套件升級

```bash
claude "升級 urllib3 到 2.2.0"
```

若 `urllib3` 不是專案直接引用，而是被 `requests` 拉進來：
- Parent (`requests`) 的版本約束允許 → 只更新 lock 檔案 (`poetry.lock` / `uv.lock` / `requirements.lock` / `package-lock.json` / `yarn.lock` / `go.sum`)，不動宣告檔
- Parent 約束擋住 → 列表顯示哪個 parent 鎖了哪個版本範圍、parent 升到最新版能否解開，由你選擇是否升 parent

### Go 大版本跳躍

```bash
claude "把 github.com/spf13/viper 從 v1 升到 v2"
```

Skill 會偵測到 major version jump，列出所有需要加 `/v2` 的 import path，等你確認後再連同 `go.mod` 一起改。

### Jira ticket 觸發

```bash
claude "https://trendmicro.atlassian.net/browse/V1E-148968"
# 或只給 issue key
claude "V1E-148968"
```

Skill 會：
1. 抓 ticket 內容 (Atlassian MCP 優先；沒接 MCP 則 REST + API token fallback)
2. 從 summary / description / comments 抽出該升級的套件 + 版本 + CVE
3. 暫停確認解析結果，跑完整 Phase 2–7
4. 完成後把遷移報告 comment 回 ticket，並詢問是否 transition 狀態

最終留下的 git artifacts：
```
Branch:  feature/V1E-148968-Update-requests-to-2.32.0
Commit:  [V1E-148968] chore(deps): upgrade requests to 2.32.0
         <body>
         Jira: https://trendmicro.atlassian.net/browse/V1E-148968
PR:      Title: [V1E-148968] chore: upgrade requests to 2.32.0
         Body 第一行: Jira: https://trendmicro.atlassian.net/browse/V1E-148968
```

### 探索式查詢

```bash
claude "看看 django 能不能從 4.2 升到 5.1"
```

依然會跑完整分析，但你可以在 Phase 4 確認點選 `[N]` 不執行修改 — 等於拿到一份「升級可行性報告」。

### 回送對這個 skill 的改進建議

```bash
claude "/package-upgrade-feedback"
```

Companion skill 會草擬一份 10 項的 improvement 草稿（純針對 skill 設計，不會引用你當前 repo 的任何資料），讓你勾選優先分類並補充自由文字，sanitize 過敏感資料後印 final issue 內容給你 review；選 `y` 直接跑 `gh issue create` 送到 `millerlai/auto-package-migration` 並標 `feedback` label。

---

## 🔧 手動安裝

不想用 `install.sh` 的話：

```bash
# 1. 複製 skill
cp -r package-upgrade ~/.claude/skills/

# 2. 設定執行權限
chmod +x ~/.claude/skills/package-upgrade/scripts/*.sh
chmod +x ~/.claude/skills/package-upgrade/scripts/*.py

# 3. Python 依賴
pip install pipdeptree requests

# 4. JS helper 依賴 (僅 JS/TS 專案需要)
cd ~/.claude/skills/package-upgrade/scripts && npm install && cd -

# 5. 系統工具
brew install jq          # macOS
sudo apt-get install jq  # Debian / Ubuntu

# 6. (可選) gh CLI — 用於自動建 PR
brew install gh

# 7. (可選，Go 專案) govulncheck + apidiff
go install golang.org/x/vuln/cmd/govulncheck@latest
go install golang.org/x/exp/cmd/apidiff@latest

# 8. 驗證
bash verify_installation.sh
```

### Atlassian 整合 (可選，啟用 Jira 觸發)

兩種接法擇一：

**方式 A：Atlassian MCP** — 透過 [Claude connector 頁面](https://claude.ai/settings/connectors) 連 Atlassian，瀏覽器登入即可，無需在本機放 token。

**方式 B：REST + API Token** — 沒有 MCP 也能用，session 中 ad-hoc 提供：
```bash
export ATLASSIAN_EMAIL="you@example.com"
export ATLASSIAN_API_TOKEN="<token>"
# Token 申請：https://id.atlassian.com/manage-profile/security/api-tokens
```
Skill 會自動偵測 MCP 是否可用，否則 fallback 到 `scripts/jira_*.py`。Token 只在 shell session 期間使用，skill 不會寫入任何檔案。

---

## 🔍 故障排除

| 症狀 | 排查 |
|------|------|
| Skill 找不到 | `ls ~/.claude/skills/package-upgrade/SKILL.md`，不存在就重跑 `bash install.sh` |
| Permission denied | `chmod +x ~/.claude/skills/package-upgrade/scripts/*.{sh,py}` |
| 缺少依賴 | `pip install pipdeptree requests`、`brew install jq`，JS 專案還要在 `scripts/` 跑 `npm install` |
| `yarn` 找不到 | corepack 管的 yarn 不在 PATH — 讓 `detect_env_js.sh` 自己解析 `pkg_manager_bin`，不要 hard-code `yarn` |
| Jira 抓不到 | 檢查 MCP 連線狀態，或改用 REST + API Token |
| `git_diff*.sh` 找不到 tag | Skill 會列出可用 tag 讓你判斷；版本標記不一致時 (如 `release-X.Y.Z`) 可能需手動確認 |
| `govulncheck` 顯示 "not vulnerable" 但 advisory 說該 CVE 存在 | reachability 是有檢查的 — 不是每個 advisory 都會從你的 code path 到達。看報告的 reachability 區塊 |

詳細排查請參考 `INSTALLATION_GUIDE.md`。

---

## 🛠️ 開發

本專案使用 **UV** 管理自己的開發環境，`package-upgrade/scripts/` 下的 helper 在開發時透過 `uv run` 執行。

```bash
git clone https://github.com/millerlai/auto-package-migration.git
cd auto-package-migration

# 安裝 UV
curl -LsSf https://astral.sh/uv/install.sh | sh

# 同步依賴 (建立 .venv/、安裝 editable project)
uv sync

# 執行 helper script
uv run python package-upgrade/scripts/dep_tree.py . requests
uv run python package-upgrade/scripts/ast_scanner.py . requests

# 格式化 / lint / type-check
uv run black package-upgrade/scripts/
uv run ruff check --fix package-upgrade/scripts/
uv run mypy package-upgrade/scripts/*.py

# 測試
uv run pytest
uv run pytest --cov=package-upgrade --cov-report=html
```

JS helpers 有自己的 `package.json` (位於 `package-upgrade/scripts/package.json`) — `install.sh` 會在該目錄內跑 `npm install`。`scripts/node_modules/` 已加入 gitignore。

更多細節請看 `DEVELOPMENT.md` 與 `package-upgrade-agent-architecture.md`。

---

## 🤝 貢獻

歡迎 PR。可能的方向：
- 新增套件管理工具支援 (conda / pipenv、pnpm / bun)
- 跨語言移植 (Ruby / Rust / Java)
- 改進 breaking change 偵測 patterns
- 增加測試框架支援
- 改進三向診斷邏輯
- 整合更多 issue tracker (GitHub Issues / GitLab Issues / Linear)

詳見 `CONTRIBUTING.md`。

---

## 📄 授權

MIT — 詳見 `package-upgrade/LICENSE`。

---

## 🙏 致謝

- [Claude Code](https://claude.ai/code) by Anthropic
- [Atlassian Rovo MCP](https://www.atlassian.com/) — Jira / Confluence 整合
- [pipdeptree](https://github.com/tox-dev/pipdeptree) — Python 依賴樹
- [poetry](https://python-poetry.org/) / [uv](https://github.com/astral-sh/uv) — Python 套件管理
- [corepack](https://nodejs.org/api/corepack.html) — yarn 3 / pnpm shim
- [govulncheck](https://pkg.go.dev/golang.org/x/vuln/cmd/govulncheck) / [apidiff](https://pkg.go.dev/golang.org/x/exp/cmd/apidiff) — Go 漏洞與 API surface 工具
