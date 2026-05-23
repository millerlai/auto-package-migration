# Changelog

## [Unreleased]

### Added — 多語言支援 (v2.0 工作)
- **JavaScript / TypeScript 支援** (#8)
  - 新增 `detect_env_js.sh` / `dep_tree_js.js` / `ast_scanner_js.js` / `git_diff_js.sh` /
    `run_tests_js.sh` / `snapshot_env_js.sh`
  - 支援 `npm` 與 `yarn 3` (corepack)；`pkg_manager_bin` 解析 corepack-managed yarn 的路徑
  - 新增 `api_surface_diff_js.js` 做 TypeScript `.d.ts` API surface diff
  - 新增 references：`js_workflow.md`、`npm_workflow.md`、`yarn_workflow.md`、
    `js_ast_strategy.md`、`breaking_change_patterns_js.md`
  - JS transitive 依賴優先 bump parent，不再手改 lock 檔案
  - 加入 `preflight.sh` (lockfile-first dep tree、yarn 3 偵測)

- **Go 支援** (#7)
  - 新增 `detect_env_go.sh` / `dep_tree_go.{sh,py}` / `ast_scanner_go.go` /
    `git_diff_go.sh` / `run_tests_go.sh` / `snapshot_env_go.sh` / `preflight_go.sh`
  - 支援 go modules、major version path rewrite (v1 → v2+)、`apidiff` API surface diff
  - 新增 `govulncheck_go.sh` 做 Go CVE reachability 分析
  - 新增 `validate_modfile_go.sh` 驗證 `go.mod` / `go.sum`
  - 新增 references：`go_workflow.md`、`go_major_version_paths.md`、
    `go_replace_semantics.md`、`govulncheck.md`、`breaking_change_patterns_go.md`
  - 支援 vendor mode、`go.work` workspace、`replace` directives

- **語言偵測**：SKILL.md Phase 0 加入語言偵測 (順序 Go > JS > Python)，
  後續所有 phase 依語言走對應的 helper script 變體

### Added — Jira / 觸發體驗
- **Jira ticket 觸發** (Phase 1.C / 7.5 / 7.6)
  - 新增 `scripts/jira_fetch.py` / `jira_comment.py` / `jira_transition.py` (REST + API token fallback)
  - SKILL.md 新增 Phase 1 情況 C (Jira URL / issue key)、Phase 7.5 (comment 回 ticket)、
    Phase 7.6 (詢問 transition 狀態，依目前狀態分階段推進)
  - 新增 `references/jira_workflow.md`
  - PR title 加 `[ISSUE_KEY]` 前綴、body 第一行為 Jira URL，方便 reviewer 識別
  - 遷移報告同時 cite changelog URL 與 git diff commit SHA，並寫入 commit message + Jira comment
- **BDSA 編號**：CVE 觸發擴充為 CVE / BDSA / GHSA；新增 `references/bdsa_mapping.md`

### Added — 安裝體驗
- **Windows `install.bat`** (#11) — PowerShell 環境一鍵安裝
- **Cygwin64 installer** — `install-cygwin64.sh`，附自動安裝 `gh` CLI
- **gh CLI 自動安裝 + auth flow** (#9) — `install.sh` 偵測缺失即詢問安裝；新增 opt-in gh 權限
- **`grant_permissions.py`** — 安裝時把允許清單寫入 Claude Code `settings.json`
- **`save_token.sh`** — 統一寫入 auth token (chmod 600 + 自動加 `.gitignore`)，
  支援 JFROG_TOKEN `.env.jfrog` 寫入與衝突處理
- **`parse_pm_errors.py`** — 解析 pip / poetry / uv / npm / go 的錯誤輸出供 Claude 推理
- **`validate_lockfile.sh`** — lock-only 模式後驗證 lock 檔案

### Added — 測試 / CI
- **pytest UT suite** (#10) — `tests/` 目錄、`conftest.py`、helper script 覆蓋；GitHub Actions CI 跑 pytest
- **pre-commit hook + CI 跑 ruff** (#12) — 本地 commit 與 CI 都會 enforce `ruff check .`

### Added — 文件
- **CLAUDE.md** — repo 層級的 Claude Code 指示
- **README.md / README.zh-TW.md** — 重寫為英中雙版本，覆蓋三語言、Jira、Windows / Cygwin 安裝

### Fixed
- **重要修正**: 修正 poetry 和 uv 套件管理工具只更新鎖定檔案,沒有更新 `pyproject.toml` 的問題
  - 更新 `poetry_workflow.md` 說明必須使用 `poetry add` 而非 `poetry update`
  - 更新 `uv_workflow.md` 說明必須使用 `uv add` 而非 `uv lock --upgrade-package`
  - 更新 `pip_workflow.md` 強調 pip 不會自動寫入任何檔案
  - 在 `SKILL.md` Phase 5.3 中詳細說明正確的更新流程
  - 新增 `IMPORTANT_DEPENDENCY_UPDATE.md` 文件,詳細說明各工具的正確使用方式

- **重要修正**: 加入 pip lock 檔案檢測與處理
  - 更新 `detect_env.sh` 自動檢測 pip-tools (requirements.in) 和自定義 lock 檔案
  - 新增 `pip_lock_file` 和 `has_pip_tools` 欄位到環境偵測輸出
  - 在 `SKILL.md` Phase 0 中說明 pip lock 檔案的檢測
  - 在 `SKILL.md` Phase 5.3 中加入 pip lock 檔案的處理流程,會詢問使用者確認
  - 支援常見的 lock 檔案模式: `requirements.lock`, `requirements.txt.lock`, `requirements-lock.txt` 等

- **Ruff first-party import 偵測穩定化** — 修 CI 上 first-party 名稱解析不一致的問題

### Changed
- **架構調整**: 移除 symlink 設計,Python scripts 直接放在 `package-upgrade/scripts/` 目錄
  - 簡化安裝流程,不需要保留 src/ 目錄
  - 使用者已將 src/*.py 直接搬移到 scripts/ 目錄
  - 移除 verify_installation.sh 中的 symlink 檢查
  - 更新所有文件移除 symlink 相關說明
  - 更新 README.md 目錄結構說明,移除 src/ 目錄

- **專案套件管理**: 將專案本身改用 UV 管理
  - 新增 `pyproject.toml` 使用 UV 格式配置
  - 新增 `uv.lock` 鎖定檔案
  - 使用 `dependency-groups` 管理開發依賴
  - 配置 hatchling 作為 build backend
  - 虛擬環境在 `.venv/` (已在 .gitignore)

- **Jira status 流程**：改為依目前狀態 (current-state aware) 分階段推進，
  不再一律直接 transition 到 Done

### Added (v1 文件擴充)
- 新增 `IMPORTANT_DEPENDENCY_UPDATE.md` - 依賴檔案更新規則總覽
- 新增 `QUICK_REFERENCE.md` - 快速參考卡片
- 新增 `PIP_LOCK_PATTERNS.md` - Pip lock 檔案模式完整指南
- 新增 `VERIFICATION_CHECKLIST.md` - 完整的安裝驗證檢查清單
- 新增 `GETTING_STARTED.md` - 3 分鐘快速上手指南
- 新增 `DEVELOPMENT.md` - 開發者指南 (UV 使用說明)
- 新增 `pyproject.toml` - UV 專案配置檔案
- 新增 `uv.lock` - UV 鎖定檔案
- 擴展 `detect_env.sh` 支援檢測多種 pip lock 檔案模式:
  - 檢測 pip-tools (requirements.in)
  - 檢測常見 lock 檔案 (requirements.lock, requirements.txt.lock 等)
  - 新增 `pip_lock_file` 和 `has_pip_tools` 輸出欄位
- 在 Phase 5.3 中加入使用者確認機制,詢問如何處理 pip lock 檔案
  - 情況 A: pip-tools → 自動執行 pip-compile
  - 情況 B: 自定義 lock → 詢問使用者產生方式
  - 情況 C: 無 lock → 直接編輯安裝

## [1.0.0] - 2026-04-14

### Added
- 初始版本發布
- 完整的 Claude Code Skill 實作
- 支援 pip、poetry、uv 三種套件管理工具
- 自動化 breaking changes 分析 (Changelog + Git Diff)
- AST 程式碼掃描與修改建議
- 測試失敗診斷 (三向交叉分析)
- Git 整合 (自動建立分支和 PR)
- 完整的遷移報告產出
- 安裝驗證腳本 (`verify_installation.sh`)
- 一鍵安裝腳本 (`install.sh`)
- 詳細的安裝指南 (`INSTALLATION_GUIDE.md`)
