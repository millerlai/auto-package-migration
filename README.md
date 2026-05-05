# Package Upgrade Skill for Claude Code

一個 Claude Code Skill，幫你自動化 Python 套件升級、CVE 漏洞修復，以及 Jira ticket 驅動的維護工作。
從觸發、依賴分析、breaking change 判讀、程式碼修改、測試驗證，到 commit / PR / Jira ticket 回寫，整條鏈路一個流程跑完。

---

## 🚀 快速開始

### 一鍵安裝

```bash
# 全域安裝 (所有專案可用，建議)
bash install.sh

# 或專案級安裝
bash install.sh --project
```

### 驗證

```bash
bash verify_installation.sh
```

### 觸發

任何一種方式都會觸發這個 skill：

```bash
claude "升級 requests 到 2.32.0"
claude "修復 CVE-2024-35195"
claude "https://trendmicro.atlassian.net/browse/V1E-148968"
claude "V1E-148968"
claude "看看 django 能不能從 4.2 升到 5.1"
```

---

## ✨ 功能特色

### 觸發方式
- 📦 **套件名稱 + 目標版本** — 一般升級
- 🔒 **CVE 編號** — 自動查 NVD/OSV，比對專案實際使用方式評估風險
- 🎫 **Jira URL 或 Issue Key** — 自動讀 ticket、分析該升級什麼，完成後把報告 comment 回 ticket，可選擇 transition 到 Done

### 升級分析
- 🌳 **依賴分析** — 區分 direct / transitive / both，識別 parent 約束衝突
- 🪶 **Transitive lock-only 路徑** — transitive package 升級且 parent 約束允許時，**只刷 lock 檔案，不動宣告檔**
- 🔁 **Parent 阻擋處理** — 當 parent 鎖定版本擋住升級時，列出每個阻擋的 parent 並詢問使用者「升級 parent / 放棄 / 自選」
- 🔬 **雙軌 Breaking Change 分析** — 同時讀 Changelog (PyPI / GitHub Releases / repo CHANGELOG) 和 Git Diff (tag 對 tag 的 `*.py` diff)，交叉驗證
- 📚 **可追溯來源** — 報告會具體寫出 Changelog URL、git diff 的舊新 tag、舊新 commit SHA、compare URL，reviewer 可直接驗證

### 程式碼修改
- 🌲 **AST 掃描** — 解析專案中所有 import 與 symbol 使用點，精準定位影響範圍
- 🧠 **上下文感知修改** — 結合 breaking change 與專案程式碼風格生成修改，逐一附 unified diff 預覽
- ✅ **修改前必須使用者確認**

### 測試與診斷
- 🎯 **分層測試** — 先跑受影響的測試，全綠後再跑完整測試
- 🔍 **三向診斷** — 失敗時同時讀 traceback / 測試碼 / 業務碼 / breaking change 清單，分類為 SOURCE_CODE / TEST_CODE / BOTH / CONFIG
- 🤝 **測試碼修改必須使用者確認**

### Git / PR / Jira 整合
- 🌿 **強制建立 feature branch**，分支名規則 `feature/{ISSUE_KEY}-Update-{pkg}-to-{ver}` (Jira 觸發) / `feature/Update-{pkg}-to-{ver}` (一般)
- 📝 **Conventional Commits** + Jira-aware：commit subject `[V1E-148968] type(scope): description`，body 帶 `Jira: <full URL>`
- 🔗 **PR 第一行就是 Jira link** — title `[ISSUE_KEY]`、body 第一行 `Jira: <url>`，reviewer 在 PR 列表卡片就看得到
- 💬 **Jira 自動回寫** — 升級完成後把遷移報告 comment 回 ticket，可選擇 transition status (Done / Resolved / Fixed 等同義詞自動 match)

### 套件管理工具
- 🎯 自動偵測 **pip / poetry / uv**
- 涵蓋 pip-tools (`requirements.in` + `requirements.txt`)、自定義 lock (`requirements.lock`)、無 lock 三種 pip 變體

---

## 🔄 核心工作流程

| Phase | 內容 |
|-------|------|
| **0. 環境偵測** | `detect_env.sh` 偵測 pkg manager、Python 版本、lock 檔案 |
| **1. 輸入解析** | A. 套件名稱 / B. CVE 編號 (web search + 風險評估) / C. Jira URL or key (MCP 或 REST 抓 ticket) |
| **2. 依賴分析** | 透過 `dep_tree.py` 取得 dependency type；transitive 走 lock-only 或 parent-bump 詢問 |
| **3. Breaking Change 分析** | Changelog + Git Diff 雙軌；保留 source URL / commit SHA 供報告引用 |
| **4. 程式碼影響分析** | `ast_scanner.py` 掃 import/symbol → 結合 breaking change 生成修改建議 |
| **5. 執行升級** | 建分支 → snapshot → 更新依賴宣告檔 + lock (或 lock-only) → 套用程式碼修改 |
| **6. 測試驗證** | 分層執行 → 三向診斷失敗 → 最多 3 輪迴圈 |
| **7. 產出與回寫** | 報告 + commit + push + PR；若 Jira 觸發 → comment + 詢問 transition |

完整工作流程定義：[`package-upgrade/SKILL.md`](package-upgrade/SKILL.md)

---

## 📋 目錄結構

```
python-auto-package-migration/
├── README.md                          # 本檔案
├── GETTING_STARTED.md                 # 3 分鐘快速上手
├── INSTALLATION_GUIDE.md              # 詳細安裝指南
├── VERIFICATION_CHECKLIST.md          # 驗證檢查清單
├── DEVELOPMENT.md                     # 開發指南
├── CHANGELOG.md                       # 版本更新記錄
├── install.sh                         # 一鍵安裝腳本
├── verify_installation.sh             # 安裝驗證腳本
├── pyproject.toml / uv.lock           # 本專案 (UV 管理依賴)
│
├── package-upgrade/                   # ⭐ Claude Code Skill 本體 (安裝時複製到 ~/.claude/skills/)
│   ├── SKILL.md                       # 主技能定義 (Phase 0–7)
│   ├── README.md                      # Skill 使用說明
│   ├── QUICK_REFERENCE.md             # 快速參考卡片
│   ├── LICENSE                        # MIT 授權
│   ├── scripts/                       # Helper scripts
│   │   ├── detect_env.sh              # 環境偵測 (pkg manager / lock 模式)
│   │   ├── dep_tree.py                # 依賴樹分析
│   │   ├── ast_scanner.py             # AST 程式碼掃描
│   │   ├── fetch_changelog.py         # Changelog 抓取 (帶 source URL header)
│   │   ├── git_diff.sh                # 版本 tag 之間的 diff (帶 commit SHA header)
│   │   ├── run_tests.sh               # 測試執行
│   │   ├── snapshot_env.sh            # 環境備份/回退
│   │   ├── jira_fetch.py              # Jira REST: 抓 ticket
│   │   ├── jira_comment.py            # Jira REST: post comment
│   │   └── jira_transition.py         # Jira REST: list/apply transitions
│   ├── references/                    # 參考文件
│   │   ├── pip_workflow.md
│   │   ├── poetry_workflow.md
│   │   ├── uv_workflow.md
│   │   ├── breaking_change_patterns.md
│   │   ├── IMPORTANT_DEPENDENCY_UPDATE.md
│   │   ├── PIP_LOCK_PATTERNS.md
│   │   └── jira_workflow.md           # Jira 觸發流程細節
│   └── templates/
│       └── report_structure.md        # 報告撰寫指南
│
└── package-upgrade-agent-architecture.md  # 完整架構設計文件
```

---

## 📖 使用範例

### 一般升級

```bash
claude "升級 requests 到 2.32.0"
```

### CVE 修復

```bash
claude "修復 CVE-2024-35195"
```

Skill 會自動 web search CVE 詳情，搜尋專案中對受影響功能的使用，產出風險評估 (critical / high / medium / low)。

### Transitive 套件升級

```bash
claude "升級 urllib3 到 2.2.0"
```

如果 `urllib3` 不是專案直接引用，而是被 `requests` 拉進來：
- Parent (`requests`) 的版本約束允許 → 只更新 lock 檔案 (`poetry.lock` / `uv.lock` / `requirements.lock`)，不動 `pyproject.toml`
- Parent 約束擋住 → 列表顯示哪個 parent 鎖了哪個版本範圍、parent 升到最新版能否解開，由你選擇是否升 parent

### Jira ticket 觸發

```bash
claude "https://trendmicro.atlassian.net/browse/V1E-148968"
# 或只給 issue key
claude "V1E-148968"
```

Skill 會：
1. 抓 ticket 內容 (Atlassian MCP，或 REST + API token fallback)
2. 從 summary / description / comments 抽出該升級的套件 + 版本 + CVE
3. 暫停確認解析結果，跑完整 Phase 2–7
4. 完成後把遷移報告 comment 回 ticket，並詢問是否 transition 到 Done

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

# 4. 系統工具
brew install jq        # macOS
sudo apt-get install jq  # Ubuntu/Debian

# 5. (可選) gh CLI - 用於自動建 PR
brew install gh

# 6. 驗證
bash verify_installation.sh
```

### Atlassian 整合 (可選，啟用 Jira 觸發)

兩種接法擇一：

**方式 A：Atlassian MCP** — 透過 [claude.ai connector](https://claude.ai/settings/connectors) 連 Atlassian，瀏覽器登入即可，無需在本機放 token。

**方式 B：REST + API Token** — 沒有 MCP 也能用，session 中 ad-hoc 提供：
```bash
export ATLASSIAN_EMAIL="you@example.com"
export ATLASSIAN_API_TOKEN="<token>"
# Token 申請：https://id.atlassian.com/manage-profile/security/api-tokens
```
Skill 會自動偵測並 fallback 到 `scripts/jira_*.py`，token 只在 session 期間使用、不寫入任何檔案。

---

## 🔍 故障排除

| 症狀 | 排查 |
|------|------|
| Skill 找不到 | `ls ~/.claude/skills/package-upgrade/SKILL.md`，不存在就重跑 `bash install.sh` |
| Permission denied | `chmod +x ~/.claude/skills/package-upgrade/scripts/*.{sh,py}` |
| 缺少依賴 | `pip install pipdeptree requests`、`brew install jq` |
| Jira 抓不到 | MCP 連線狀態檢查；或改用 REST + API Token |
| `git_diff.sh` 找不到 tag | Skill 會列出可用 tag 讓你判斷；版本標記不一致時 (例如 `release-X.Y.Z`) 可能需要手動確認 |

詳細排查請參考 `INSTALLATION_GUIDE.md`。

---

## 🛠️ 開發

本專案使用 UV 管理依賴：

```bash
git clone https://github.com/millerlai/python-auto-package-migration.git
cd python-auto-package-migration

# 安裝 UV
curl -LsSf https://astral.sh/uv/install.sh | sh

# 同步依賴
uv sync

# 執行 helper script
uv run python package-upgrade/scripts/dep_tree.py . requests

# 格式化 / lint
uv run black package-upgrade/scripts/
uv run ruff check package-upgrade/scripts/
```

更多細節請看 `DEVELOPMENT.md` 與 `package-upgrade-agent-architecture.md`。

---

## 🤝 貢獻

歡迎貢獻：
- 新增套件管理工具支援 (conda / pipenv)
- 跨語言移植 (Node.js / Ruby / Go)
- 改進 breaking change 偵測 patterns
- 增加測試框架支援
- 改進三向診斷邏輯
- 整合更多 issue tracker (GitHub Issues / GitLab Issues / Linear)

---

## 📄 授權

MIT License — 詳見 `package-upgrade/LICENSE`

---

## 🙏 致謝

- [Claude Code](https://claude.ai/code) by Anthropic
- [Atlassian Rovo MCP](https://www.atlassian.com/) — Jira / Confluence 整合
- [pipdeptree](https://github.com/tox-dev/pipdeptree) — 依賴樹分析
- [poetry](https://python-poetry.org/) / [uv](https://github.com/astral-sh/uv) — 套件管理
