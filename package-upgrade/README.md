# Package Upgrade Skill

自動化 Python / JavaScript / TypeScript / Go 套件升級與 CVE 漏洞修復的 Claude Code Skill。

> 這份 README 講解**已安裝的 skill 內部**：每個檔案的角色、Phase 0–7 的觸發、
> 使用者確認點。
>
> - **安裝與設定**：看 repo 根目錄的 [`docs/installation.md`](../docs/installation.md)
> - **專案介紹 / Features / Examples**：看 repo 根目錄的 [`README.md`](../README.md)
> - **貢獻 / 開發**：看 [`CONTRIBUTING.md`](../CONTRIBUTING.md)

---

## 觸發 Skill

裝完之後直接在 Claude Code 對話中下指令：

```bash
claude
```

```text
# 標準升級
升級 requests 到 2.32.0
bump axios to 1.7.0
go get -u github.com/spf13/cobra@v1.8.0

# CVE / BDSA / GHSA 修復
修復 CVE-2024-35195

# Jira ticket 觸發
https://trendmicro.atlassian.net/browse/V1E-148968
V1E-148968

# 探查（不真的升級）
看看 django 能不能從 4.2 升到 5.1
```

完整觸發語句範例見 [`../README.md` § Examples](../README.md#-examples)。

---

## Skill 內部結構

```
package-upgrade/
├── SKILL.md             # ⭐ Claude Code 讀這個；Phase 0–7 完整工作流程
├── README.md            # 你現在看的這份
├── QUICK_REFERENCE.md   # 套件管理工具命令對照卡（Python / JS / Go）
├── LICENSE
│
├── scripts/             # 確定性 helper — 產出 JSON 給 Claude 推理
│   ├── common/          # 跨語言：fetch_changelog / parse_pm_errors / save_token / git_diff / jira_*
│   ├── python/          # detect_env / dep_tree / ast_scanner / api_surface_diff / preflight / run_tests / snapshot_env / validate_lockfile / pip_audit
│   ├── javascript/      # 同上 + runtime_verify + package.json + node_modules
│   └── go/              # 同上 + govulncheck + validate_modfile
│
├── references/          # SKILL.md 在 phase 中 lazily 讀
│   ├── common/          # auth_tokens / bdsa_mapping / jira_workflow / breaking_change_patterns / important_dependency_update
│   ├── python/          # pip_workflow / poetry_workflow / uv_workflow / override_semantics / pip_lock_patterns / runtime_verification / breaking_change_patterns
│   ├── javascript/      # workflow / ast_strategy / npm_workflow / yarn_workflow / pnpm_workflow / override_semantics / runtime_verification / breaking_change_patterns
│   └── go/              # workflow / major_version_paths / replace_semantics / govulncheck / runtime_verification / breaking_change_patterns
│
└── templates/
    └── report_structure.md  # 報告結構範本（不是填空模板）
```

設計原則：

- **scripts/ 是確定性的**：解析 lockfile、走 AST、查 changelog 都是有正確答案的工具操作。輸出 JSON 給 SKILL.md 後續 phase 使用。
- **SKILL.md 是 LLM 推理**：判斷哪個是 breaking change、要選哪條升級策略、要怎麼改 code，這些都交給 Claude（host 本身就是 Claude）。
- **references/ 是 lazy-loaded**：SKILL.md 只在用得到的 phase 才讀對應 reference，避免一次塞滿 context。

---

## Phase 0–7 概觀

| Phase | 內容 | 主要 helper |
|-------|------|-------------|
| **0. 環境偵測** | 語言（Go > JS > Python）→ 套件管理工具 → lockfile 模式 | `<lang>/detect_env.sh` |
| **1. 輸入解析** | A. 套件名 / B. CVE-BDSA-GHSA + 風險評估 / C. Jira URL or key | `common/jira_*.py`（Mode C）|
| **2. 依賴分析** | direct / transitive / both；parent constraint 檢查 | `<lang>/dep_tree.*` |
| **3. Breaking change 分析** | Changelog（PyPI / npm / GitHub）+ Git diff 雙軌；JS 加 `.d.ts` surface diff、Go 加 `apidiff` | `common/fetch_changelog.py` + `<lang>/git_diff.sh` + `<lang>/api_surface_diff.*` |
| **4. 程式碼影響** | AST 掃描定位每個 import / symbol use | `<lang>/ast_scanner.*` |
| **5. 套用升級** | feature branch → 環境 snapshot → manifest + lock 更新 → AST patch | `<lang>/snapshot_env.sh` + Edit/Write |
| **6. 測試** | 分層執行；失敗時三向診斷（SOURCE_CODE / TEST_CODE / BOTH / CONFIG）；至多 3 次迴圈 | `<lang>/run_tests.sh` |
| **7. 報告 / commit / PR / Jira write-back** | Migration report → conventional commit → `gh pr create` → Jira comment + transition prompt | `gh` + `common/jira_*.py` |

完整 phase 規格與分支條件見 [`SKILL.md`](SKILL.md)。

---

## 使用者確認點

Skill 在以下時間點會暫停等你確認，不會自動執行：

| 時間點 | 內容 |
|--------|------|
| Phase 0.3 Pre-flight blockers | 缺 token、git tree 不乾淨等；提供 [1] 修完再來 / [2] 走 fallback / [3] 中止 |
| Phase 1.C Jira 解析 | 從 ticket 抽到的 package / 版本 / CVE / 驗收條件，等你校正 |
| Phase 2 升級策略 | direct_bump / bump_override / bump_parent / lock_only / add_replace 等 |
| Phase 2 (Python) Pip lock 處理 | 非標準 lockfile 的產生方式 |
| Phase 2.0 Workspace 範圍 | JS workspace / Go submodule 要動哪幾個 |
| Phase 2.2 (Go) major version jump | 列出所有要 rewrite 的 import path |
| Phase 4 程式碼修改 | 完整 unified diff 預覽 + 每處修改的理由 |
| Phase 5.1 建立 Git 分支 | 分支名稱與即將開始的修改 |
| Phase 6.4 測試程式修改 | 為什麼要改測試 + 改後仍驗證什麼 |
| Phase 7.3 建立 PR | PR title / body 預覽 |
| Phase 7.5 Jira comment | 預覽 + ticket URL（僅 Jira 觸發） |
| Phase 7.6 Jira status transition | 列出目前狀態 → 目標狀態（僅 Jira 觸發） |

任何確認點你都可以：同意 / 要求修改 / 暫停手動介入 / 中止並回退。

---

## 延伸 / 自訂

### 加新語言 / 新套件管理工具

`scripts/` 與 `references/` 已經 per-language 分子資料夾，加新語言（如 Rust）只要：
1. `scripts/rust/` 加 8 個必備 helper（`detect_env.sh` / `preflight.sh` / `dep_tree.*` / `ast_scanner.*` / `api_surface_diff.*` / `git_diff.sh` / `run_tests.sh` / `snapshot_env.sh`）
2. `references/rust/workflow.md` + `cargo_workflow.md`
3. `SKILL.md` Phase 0 detection order 加 Rust 分支

詳見 [`../CONTRIBUTING.md`](../CONTRIBUTING.md)。

### 改現有 helper

```bash
# 例：修改 Python detect_env.sh 支援 conda
vim ~/.claude/skills/package-upgrade/scripts/python/detect_env.sh

# 例：擴充 JS dep tree 解析（pnpm v9 已內建）
vim ~/.claude/skills/package-upgrade/scripts/javascript/dep_tree.js
```

修改 helper **必同步更新 SKILL.md 對應 phase 描述** — helper 的 CLI 和 JSON output schema 是 SKILL.md 的對外介面。

---

## 故障排除

精簡版（完整版見 [`../docs/installation.md`](../docs/installation.md) § 故障排除）：

| 症狀 | 處理 |
|---|---|
| Permission denied | `find ~/.claude/skills/package-upgrade/scripts \( -name '*.sh' -o -name '*.py' -o -name '*.js' \) -exec chmod +x {} +` |
| `jq` 找不到 | `brew install jq` / `sudo apt-get install jq` |
| JS helper 缺 `node_modules` | `cd ~/.claude/skills/package-upgrade/scripts/javascript && npm install` |
| corepack-managed `yarn` / `pnpm` 找不到 | `corepack enable`；不要 hard-code `yarn` / `pnpm`，讓 `detect_env.sh` 解析 `pkg_manager_bin` |
| Changelog 抓不到 | 自動降級成 web search |
| `govulncheck` 說 "not vulnerable" 但 advisory 說 CVE 在 | reachability 真的沒走到 — 看報告的 reachability 段 |

---

## 安全考量

- ⚠️ Skill 會跑 bash 命令並修改 source code — 請在受信任環境內使用
- ✅ 修改前一律建立 `snapshot_env.sh` 環境備份
- ✅ 所有程式碼 / 測試修改都會展示 diff 並等待確認
- ✅ 在獨立 feature branch 工作，不污染 main
- ✅ Auth token 走 `save_token.sh`（chmod 600 + 自動加 `.gitignore`）

---

## License

MIT — see [`LICENSE`](LICENSE).
