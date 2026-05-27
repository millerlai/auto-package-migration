# 專案狀態總覽

> 高層次成熟度快照。詳細的版本變更請見 [`CHANGELOG.md`](../CHANGELOG.md)、
> 工作原則請見 [`CLAUDE.md`](../CLAUDE.md)。

---

## ✅ 已完成

### 多語言支援

Phase 0 偵測順序：**Go > JavaScript > Python**

| 語言 | 套件管理工具 | 進階能力 |
|------|--------------|----------|
| Python | pip（+ pip-tools / 自定義 lock）、poetry、uv | dep_tree 區分 direct / transitive、parent-bump 詢問 |
| JavaScript / TypeScript | npm、yarn 3 (corepack)、**pnpm**（含 v9 snapshots block） | TypeScript `.d.ts` API surface diff、transitive 優先 bump parent、workspace 偵測 |
| Go | go modules | major version path rewrite (v1 → v2+)、`apidiff` API surface diff、`govulncheck` reachability、vendor mode、`go.work`、`replace` directives |

`bun` 仍標記為後續 stage（`bun.lock` 為二進位格式）。

### Helper scripts（per-language reorg 後的佈局）

```
scripts/
├── common/      fetch_changelog / parse_pm_errors / save_token / git_diff / jira_*
├── python/      detect_env / dep_tree / ast_scanner / api_surface_diff / preflight / run_tests / snapshot_env / validate_lockfile / pip_audit
├── javascript/  + runtime_verify + package.json
└── go/          + govulncheck + validate_modfile
```

### Jira 整合

- ✅ MCP（Atlassian Rovo）優先；fallback 到 REST + API token（`scripts/common/jira_*.py`）
- ✅ SKILL.md Phase 1.C / 7.5 / 7.6 完整定義
- ✅ Commit message + PR title 帶 `[ISSUE_KEY]`；PR body 第一行為 Jira URL
- ✅ Comment 自動回 ticket，依目前狀態分階段詢問 transition

### CVE / BDSA / GHSA

- ✅ CVE / BDSA（Black Duck）/ GHSA 編號觸發
- ✅ Go 額外做 `govulncheck` reachability

### 安裝體驗

- ✅ `install.sh` (POSIX) / `install.bat` (Windows) / `install-cygwin64.sh`
- ✅ `grant_permissions.py` 寫入 Claude Code `settings.json`
- ✅ gh CLI 偵測 + auth flow
- ✅ JS helper 自動 `npm install`（在 `scripts/javascript/`）
- ✅ `verify_installation.sh` 自動驗證

### 測試 / CI

- ✅ **pytest UT suite**（`tests/`，322 passed / 15 skipped）
- ✅ **GitHub Actions CI**：pytest + `ruff check .` 在 push / PR 都跑
- ✅ **pre-commit hook**：本地 commit 跑 ruff

### 文件（重整後）

- `README.md` / `README.zh-TW.md`（短指標）
- `CONTRIBUTING.md`（合併自舊 DEVELOPMENT + CONTRIBUTING）
- `docs/installation.md`（合併自舊 GETTING_STARTED + INSTALLATION_GUIDE + VERIFICATION_CHECKLIST）
- `docs/project-status.md`（本檔）
- `CHANGELOG.md`
- `CLAUDE.md`
- `package-upgrade/SKILL.md`、`QUICK_REFERENCE.md`
- `references/{common,python,javascript,go}/*.md`

---

## 🚧 待完成 / 規劃中

### 高優先

- [ ] **bun** 支援（`bun.lock` 二進位格式需 bun runtime 才能 robust 解析）
- [ ] **conda** / **pipenv** 支援
- [ ] **Monorepo 結構支援**：Lerna / Nx / Turborepo / `go.work`（pnpm workspaces 已支援）
- [ ] 更多測試框架：Python (nose2 / tox)、JS (mocha / playwright)、Go (ginkgo)

### 中優先

- [ ] 跨語言移植：Ruby (bundler) / Rust (cargo) / Java (maven / gradle)
  - per-language scripts/ 重組後加新語言只要新增子資料夾 + SKILL.md 對應 phase 分支
- [ ] JS / Python 的 reachability 分析（參考 Go `govulncheck` 模式）
- [ ] 整合更多 issue tracker：GitHub Issues / GitLab Issues / Linear
- [ ] 改進三向診斷邏輯，自動偵測常見 mock / fixture 失敗 pattern

### 低優先

- [ ] Web UI 介面
- [ ] VS Code 擴充套件整合
- [ ] PyPI / npm / Go proxy 結果快取（降低 web search 次數）

---

## 📈 專案成熟度

| 面向 | 狀態 | 備註 |
|------|------|------|
| 核心功能 (Python) | ✅ | pip / poetry / uv，含 pip lock 變體 |
| 核心功能 (JS / TS) | ✅ | npm + yarn 3 + pnpm（含 v9 lockfile） |
| 核心功能 (Go) | ✅ | modules + major rewrite + govulncheck + apidiff |
| Jira 整合 | ✅ | MCP + REST fallback，三階段 transition |
| 安裝體驗 | ✅ | POSIX / Windows / Cygwin 三平台 |
| 文件 | ✅ | per-language references 完整、reorg 後結構清晰 |
| 單元測試 | ✅ | pytest UT + GitHub Actions CI |
| Lint / Format | ✅ | ruff + black + pre-commit + CI |
| bun / conda / pipenv | ⚠️ | 規劃中 |
| 跨語言 (Ruby / Rust / Java) | ⚠️ | 規劃中 |

**總體成熟度**：多語言 Beta，可用於生產。建議在新環境先跑 dry-run 熟悉流程。

