# 專案狀態總覽

> 本檔案為高層次的成熟度快照。詳細的版本變更請見 `CHANGELOG.md`、
> 工作原則與架構請見 `CLAUDE.md` / `package-upgrade-agent-architecture.md`。

---

## ✅ 已完成

### 多語言支援 — Phase 0 偵測順序: **Go > JS > Python**

| 語言 | 套件管理工具 | 進階能力 |
|------|--------------|----------|
| Python | pip (+ pip-tools / 自定義 lock)、poetry、uv | dep_tree 區分 direct / transitive、parent-bump 詢問 |
| JavaScript / TypeScript | npm、yarn 3 (corepack) | TypeScript `.d.ts` API surface diff、transitive 優先 bump parent |
| Go | go modules | major version path rewrite (v1 → v2+)、`apidiff` API surface diff、`govulncheck` reachability、vendor mode、`go.work`、`replace` directives |

### 核心 helper scripts

- ✅ **環境偵測**: `detect_env.sh` / `detect_env_js.sh` / `detect_env_go.sh`
- ✅ **依賴樹**: `dep_tree.py` / `dep_tree_js.js` / `dep_tree_go.{sh,py}`
- ✅ **AST 掃描**: `ast_scanner.py` / `ast_scanner_js.js` / `ast_scanner_go.go`
- ✅ **API surface diff**: `api_surface_diff_js.js` (TypeScript `.d.ts`) / `api_surface_diff_go.sh` (apidiff)
- ✅ **Vulnerability reachability**: `govulncheck_go.sh`
- ✅ **Changelog 抓取**: `fetch_changelog.py`
- ✅ **版本 diff**: `git_diff.sh` / `git_diff_js.sh` / `git_diff_go.sh`
- ✅ **測試執行**: `run_tests.sh` / `run_tests_js.sh` / `run_tests_go.sh`
- ✅ **環境 snapshot / 回退**: `snapshot_env.sh` / `snapshot_env_js.sh` / `snapshot_env_go.sh`
- ✅ **Pre-flight checks**: `preflight.sh` / `preflight_go.sh`
- ✅ **Lock / mod 驗證**: `validate_lockfile.sh` / `validate_modfile_go.sh`
- ✅ **錯誤解析**: `parse_pm_errors.py`
- ✅ **Auth token 寫入**: `save_token.sh` (chmod 600 + 自動加 `.gitignore`)

### Jira 整合

- ✅ MCP (Atlassian Rovo) 優先；fallback 到 REST + API token (`jira_fetch.py` / `jira_comment.py` / `jira_transition.py`)
- ✅ SKILL.md Phase 1.C / 7.5 / 7.6 完整定義
- ✅ Commit message + PR title 帶 `[ISSUE_KEY]`；PR body 第一行為 Jira URL
- ✅ Comment 自動回 ticket，依目前狀態分階段詢問 transition

### CVE / BDSA / GHSA

- ✅ CVE 編號觸發
- ✅ BDSA 編號 (Black Duck) 對應到 CVE (`references/bdsa_mapping.md`)
- ✅ GHSA (GitHub Security Advisory) 支援
- ✅ Go 額外做 `govulncheck` reachability 分析

### 安裝體驗

- ✅ `install.sh` (POSIX) — 一鍵安裝；可選 `--project` / `--skip-permissions`
- ✅ `install.bat` (Windows) — PowerShell / cmd 一鍵安裝
- ✅ `install-cygwin64.sh` (Cygwin) — 附自動安裝 `gh` CLI
- ✅ `grant_permissions.py` — 寫入 Claude Code `settings.json` 允許清單
- ✅ gh CLI 偵測 + auth flow
- ✅ JS helper 自動 `npm install`
- ✅ `verify_installation.sh` — 自動驗證

### 測試 / CI

- ✅ **pytest UT suite** (`tests/`) — helper script 覆蓋
- ✅ **GitHub Actions CI** — pytest + `ruff check .` 在 push / PR 都跑
- ✅ **pre-commit hook** — 本地 commit 也跑 ruff

### 文件

- ✅ `README.md` / `README.zh-TW.md` — 英中雙版本，覆蓋三語言
- ✅ `GETTING_STARTED.md` / `INSTALLATION_GUIDE.md` / `VERIFICATION_CHECKLIST.md` — 安裝與驗證
- ✅ `DEVELOPMENT.md` / `CONTRIBUTING.md` — 開發者文件
- ✅ `CLAUDE.md` — repo 層級的 Claude Code 指示
- ✅ `package-upgrade/SKILL.md` — 主技能 Phase 0–7
- ✅ `package-upgrade/QUICK_REFERENCE.md` — Python / JS / Go 三語言對照卡
- ✅ Language references (各 5–6 份)：Python / JS / Go workflow、breaking_change_patterns、
  Go major version paths、govulncheck、JS AST strategy、Jira workflow、BDSA mapping、auth tokens

---

## 🎯 關鍵特性

### 1. 智能依賴更新

- **Python 對應工具**: poetry → `poetry add`，uv → `uv add`，pip → 編輯後安裝；
  避免「只更新 lock，沒更新宣告檔」的陷阱
- **Pip Lock 變體**: pip-tools / 自定義 `requirements.lock` / 無 lock 三種模式
- **JS**: npm / yarn 3 corepack；`pkg_manager_bin` 解析確保不誤用全域 yarn
- **Go**: minor / patch 用 `go get -u`；major 用 `/vN` path rewrite 自動產生

### 2. Breaking Change 雙軌分析

- Changelog (PyPI / npm / GitHub Releases / repo CHANGELOG)
- Git Diff (tag 對 tag 的原始碼 diff)
- JS / TS 額外做 `.d.ts` API surface diff
- Go 額外做 `apidiff`
- 報告引用 source URL + commit SHA，reviewer 可直接驗證

### 3. 程式碼修改

- AST 靜態分析定位受影響程式碼 (Python `ast` / JS Babel / Go `go/ast`)
- 上下文感知，保持原有風格
- 修改前 unified diff 預覽 + 使用者確認

### 4. 測試診斷

- 分層執行 (受影響 → 全部)
- 三向交叉分析：SOURCE_CODE / TEST_CODE / BOTH / CONFIG
- 最多 3 次迴圈

### 5. Git / PR / Jira 整合

- 強制 feature branch
- Conventional Commits + Jira-aware (`[ISSUE_KEY]` prefix)
- 自動 PR (gh CLI)
- Jira ticket 自動 comment + 詢問 transition

---

## 📊 專案統計 (快照)

### 檔案規模

- **總 .md 文件**: 30+
- **三語言 helper scripts**: ~30 個檔案 (Python / JS / Go 各約 8–10)
- **跨語言 / 共用 helper**: ~7 個 (fetch_changelog、parse_pm_errors、save_token、jira_*)
- **References**: ~17 份 (Python 6、JS 5、Go 5、跨語言 3)
- **Tests**: pytest UT suite，CI 自動跑

### 支援範圍

- **Python**: pip、poetry、uv (3 工具) + pip-tools / 自定義 lock / 無 lock 變體 — Python 3.8+
- **JavaScript / TypeScript**: npm、yarn 3 (2 工具) — Node.js 18+
- **Go**: go modules — Go 1.21+；含 vendor、`go.work`、`replace`、major version rewrite
- **測試框架**: pytest / unittest / jest / vitest / go test
- **Git 平台**: GitHub (其他 issue tracker 待擴展)
- **作業系統**: macOS / Linux / Windows (PowerShell 與 Cygwin)

---

## 🚧 待完成 / 規劃中

### 高優先

- [ ] **pnpm** / **bun** 支援 (繼 npm / yarn 3 之後)
- [ ] **conda** / **pipenv** 支援
- [ ] **Monorepo 結構支援**：Lerna / Nx / Turborepo / pnpm workspaces / go.work
- [ ] 更多測試框架：Python (nose2 / tox)、JS (mocha / playwright)、Go (ginkgo)

### 中優先

- [ ] 跨語言移植：Ruby (bundler) / Rust (cargo) / Java (maven / gradle)
- [ ] JS / Python 的 reachability 分析 (參考 Go govulncheck 模式)
- [ ] 整合更多 issue tracker：GitHub Issues / GitLab Issues / Linear
- [ ] 改進三向診斷邏輯，自動偵測常見 mock / fixture 失敗 pattern

### 低優先

- [ ] Web UI 介面
- [ ] VS Code 擴充套件整合
- [ ] PyPI / npm / Go proxy 結果快取 (降低 web search 次數)

---

## 🎉 近期重點更新

詳見 `CHANGELOG.md` `[Unreleased]` 段。重點：

1. ✅ **JavaScript / TypeScript 三軌** (#8) — npm + yarn 3 + `.d.ts` API surface diff
2. ✅ **Go 三軌** (#7) — go modules、major version rewrite、apidiff、govulncheck
3. ✅ **Jira ticket 觸發** — Phase 1.C / 7.5 / 7.6；MCP 優先 + REST fallback
4. ✅ **Windows install.bat** (#11) 與 **Cygwin64 installer**
5. ✅ **gh CLI 自動安裝 + auth flow** (#9)
6. ✅ **pytest UT suite + CI** (#10)
7. ✅ **pre-commit hook + ruff CI** (#12)
8. ✅ **README.md / README.zh-TW.md 重寫** — 英中雙版本，覆蓋三語言

---

## 🚀 下一步

### 對於使用者

1. **安裝**: `bash install.sh` (POSIX) / `install.bat` (Windows) / `bash install-cygwin64.sh`
2. **驗證**: `bash verify_installation.sh`
3. **使用**:
   ```
   claude "升級 requests 到 2.32.0"        # Python
   claude "bump axios to 1.7.0"            # JS
   claude "go get -u github.com/spf13/cobra@v1.8.0"  # Go
   claude "V1E-148968"                      # Jira ticket
   ```

### 對於開發者

1. **設定環境**: `uv sync` + `cd package-upgrade/scripts && npm install`
2. **閱讀**: `CLAUDE.md`、`DEVELOPMENT.md`、`CONTRIBUTING.md`
3. **選擇任務**: 從上方「待完成」中選擇
4. **開始貢獻**: 建立 PR

---

## 📈 專案成熟度

| 面向 | 狀態 | 備註 |
|------|------|------|
| 核心功能 (Python) | ✅ | pip / poetry / uv 全支援，含 pip lock 變體 |
| 核心功能 (JavaScript / TS) | ✅ | npm + yarn 3，含 .d.ts diff |
| 核心功能 (Go) | ✅ | modules + major rewrite + govulncheck + apidiff |
| Jira 整合 | ✅ | MCP + REST fallback，三階段 transition |
| 安裝體驗 | ✅ | POSIX / Windows / Cygwin 三平台 |
| 文件 | ✅ | 英中雙語 README + 三語言 references |
| 單元測試 | ✅ | pytest UT + GitHub Actions CI |
| Lint / Format | ✅ | ruff + black + pre-commit + CI |
| 多套件管理工具 (pnpm / bun / conda) | ⚠️ | 規劃中 |
| 跨語言 (Ruby / Rust / Java) | ⚠️ | 規劃中 |

**總體成熟度**: 多語言 Beta，可用於生產。建議在新環境先跑 dry-run 熟悉流程。

---

## 🎯 版本規劃

### v2.x (目前)
- ✅ Python / JavaScript / TypeScript / Go 三軌
- ✅ Jira ticket 觸發 + transition flow
- ✅ Windows / Cygwin installer
- ✅ pytest UT + ruff CI + pre-commit

### v2.1 (Planned)
- [ ] pnpm / bun
- [ ] conda / pipenv
- [ ] Monorepo 結構支援
- [ ] 更多測試框架

### v3.0 (Future)
- [ ] Ruby / Rust / Java
- [ ] JS / Python 的 reachability 分析
- [ ] Web UI 介面

---

## 📝 總結

**狀態**: ✅ 可使用（生產 Beta）
**品質**: 三軌穩定、CI 守門
**文件**: 英中雙語、language-specific references 完整
**測試**: pytest UT + CI 已就位，仍歡迎補 fixture 與 e2e

**推薦操作**：
1. 使用者 → 直接安裝使用
2. 開發者 → 貢獻 pnpm / monorepo / 跨語言移植

歡迎貢獻! 🎊
