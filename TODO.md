# TODO — 三語言 track 對等性改進

> 本檔案聚焦於「PROJECT_STATUS.md 尚未列出、但實際影響 Python / JS / Go 三語言對等性」的結構性缺口。
> 排序依據：低風險、純機械修補的項目優先；需要新概念設計的放後面。
> 每項任務含：**背景 → 證據 → 要做的事 → 驗收條件 → 預估規模 → 風險與權衡**。

---

## 進度追蹤

| 子任務 | 狀態 | 分支 / 備註 |
|--------|------|-------------|
| 1.1 `detect_env.sh` Python 補欄位 | ✅ 完成 | `feat/schema-alignment` (cb07300)：加 `language` / `pkg_manager_bin` / `custom_registries`（pyproject.toml + pip.conf）/ `env_var_placeholders` / `git_remote_host` / `memory_hints` |
| 1.2 `ast_scanner` 加 `verdict` | ✅ 完成 | `feat/schema-alignment` (cb07300)：Python + JS scanner 加 `verdict` / `verdict_reason` / `files_scanned` / `import_count` / `usage_count` / `warnings`，與 `ast_scanner_go.go` 對齊 |
| 1.3 `api_surface_diff` confidence 統一 | ⬜ 未開始 | 依執行順序，等任務 3 補測試後再做 |
| 2.1 `runtime_verification_{py,go}.md` | ✅ 完成 | `docs/multi-lang-references`：兩份新文件覆蓋 T1-import / T1-cli / T2-web / T2-data (py)、T1-build / T1-cli / T2-server (go)。SKILL.md Phase 0.2 對應段落已連到新文件 |
| 2.2 `python_override_semantics.md` + `js_override_semantics.md` | ✅ 完成 | `docs/multi-lang-references`：Python 涵蓋 pip-tools / poetry / uv 三套；JS 涵蓋 npm / yarn 1 / yarn 3+ / pnpm / bun 五套。SKILL.md Phase 0.2 各 path 段落已連結 |
| 2.3 `breaking_change_patterns_py.md` | ✅ 完成 | `docs/multi-lang-references`：Python 慣例（`@deprecated` / `__getattr__` / async/sync / C ext ABI / pickle / pkg_resources 等）；含 Phase 4 修法 cookbook |
| 3.1 JS helper 加 pytest | 🟡 部分完成 | `test/js-go-helper-pytest`：加 `test_ast_scanner_js.py` (8 tests, all pass) + `test_detect_env_js.py` (5 pass, 1 skip on Windows)。`test_dep_tree_js.py` + `test_api_surface_diff_js.py` 留下個 PR。 |
| 3.2 Go helper 加 pytest | 🟡 部分完成 | `test/js-go-helper-pytest`：加 `test_ast_scanner_go.py` (7 tests) + `test_detect_env_go.py` (5 tests)。本地無 Go 全 skip；CI 會跑。`test_api_surface_diff_go.py` 留下個 PR。 |
| 3.3 共用 bash helper 煙霧測試 | ⬜ 未開始 | — |
| 4.1 `pnpm_workflow.md` | ⬜ 未開始 | — |
| 4.2 `dep_tree_js.js` 支援 pnpm | ⬜ 未開始 | — |
| 4.3 `run_tests_js.sh` / `snapshot_env_js.sh` / `validate_lockfile.sh` 加 pnpm | ⬜ 未開始 | — |
| 4.4 SKILL.md pnpm 段落 | ⬜ 未開始 | — |

**已知瑕疵（非本 PR 引入，記在這裡待後續處理）**：
- `detect_env.sh:12` 的 `grep -P` 在 Windows MSYS 環境會印 locale warning 到 stderr，造成 `python_version` 抓不到。原版即存在，未動。
- `detect_env_js.sh` 的 missing-`package.json` 錯誤訊息把 `$PROJECT_PATH` 直接 inline 進 JSON，Windows backslash 路徑（如 `C:\Users\...`）會產生無效的 JSON escape（`\U` / `\T` 等）。POSIX 不受影響。`test_detect_env_js.py::test_missing_package_json_errors` 在 Windows 上 skip。修法：改用 `jq -Rs` 編碼路徑。
- `detect_env_js.sh:287-292` 原本有 bash syntax error（pipe 跳行）導致整支 script parse 失敗。在 `test/js-go-helper-pytest` 補測試時發現並修復。

---

## Branch merge order

待 PR review 後依下表順序 merge 回 master。後序分支基於前序分支 branch，merge 順序顛倒會造成 conflict。

| # | Branch | 依賴 | 內容 |
|---|--------|------|------|
| 1 | `feat/schema-alignment` | master | 任務 1.1 + 1.2（schema 對齊基礎） |
| 2 | `test/js-go-helper-pytest` | #1 | 任務 3.1 + 3.2 部分完成（守 #1 新增的 schema 欄位）+ `detect_env_js.sh` syntax fix + CI 加 Node/Go toolchain |
| 3 | `docs/multi-lang-references` | #1 | 任務 2.1 / 2.2 / 2.3（純文件，零回歸風險，可平行 #2） |
| 4 | `test/dep-tree-api-surface-pytest` *(規劃中)* | #2 | 任務 3.1 / 3.2 補完（`test_dep_tree_js`、`test_api_surface_diff_*`） |
| 5 | `feat/api-surface-confidence` *(規劃中)* | #4 | 任務 1.3（confidence 統一，需要 #4 的測試守門） |
| 6 | `test/bash-helper-smoke` *(規劃中)* | #5 | 任務 3.3（剩餘 bash helper 煙霧測試） |
| 7 | `feat/pnpm-support` *(規劃中)* | #6 | 任務 4（pnpm 完整支援，最大塊獨立工作） |

#3 與 #2 平行；#2 / #3 同時動到 `TODO.md` 進度欄位，merge 時可能要手動合併 ✅ marker（merge order 表本身相同，不衝突）。其餘必須依序 merge。

---

## 任務 1 — 三語言 Output Schema 對齊

### 背景

Phase 0 偵測、Phase 4 AST scan、Phase 3 API surface diff 三個 helper 是 SKILL.md 後續所有判斷的基礎。
三語言 track 的 JSON 輸出欄位目前**不對等**，導致 Python track 在私有 registry / 認證偵測、
Phase 4 短路決策、API surface 信心分數三方面能力遠弱於 JS / Go。

### 證據

| 項目 | Python | JS | Go |
|------|--------|----|----|
| `detect_env.sh` 輸出欄位數 | 6（`pkg_manager` / `python_version` / `lockfile_path` / `pip_lock_file` / `has_pip_tools` / `dependency_files`）| 34（含 `pkg_manager_bin` / `uses_corepack` / `custom_registries` / `env_var_placeholders` / `memory_hints` / `git_remote_host` 等）| 25（含 `replace_directives` / `go_env` / `govulncheck_available` / `netrc_present` 等）|
| `ast_scanner` 是否輸出 `verdict` / `verdict_reason` | ✗ | ✗ | ✓（`ast_scanner_go.go:43-48`, `:105-106`, `:462`）|
| `api_surface_diff` 信心分數 baseline | 0.65（`api_surface_diff_py.sh:398`） | 0.85（dts/dts） / 0.4（js/js）（`api_surface_diff_js.js:389-400`） | ~0.9（SKILL.md 描述） |

### 1.1 補齊 `detect_env.sh`（Python）的私有 registry / 認證偵測欄位

- 新增 `custom_registries`：解析 `~/.pypirc`、`pip.conf`、`pyproject.toml [[tool.poetry.source]]`、`uv` 的 `index-url` / `extra-index-url`。
- 新增 `env_var_placeholders`：掃 config 中引用的 `${ENV_VAR}` 或 `$ENV_VAR`（pip 與 poetry 都支援）。
- 新增 `memory_hints`：例如 `["private_registry", "poetry_source", "pip_extra_index"]`。
- 新增 `git_remote_host`：與 JS 一致，方便後續 PR 流程判斷。
- 新增 `dependency_manager_bin`：對應 `pkg_manager_bin`，紀錄 `which poetry` / `which uv` 解析後的絕對路徑。

### 1.2 為 `ast_scanner.py` / `ast_scanner_js.js` 加上 `verdict` 欄位

- 統一輸出 schema：頂層加 `verdict ∈ {zero_impact, has_impact, scan_errored}` + `verdict_reason: string`。
- 判斷規則參考 `ast_scanner_go.go:462`：當套件在 dep tree 但無任何 source file 引用 → `zero_impact`。
- 更新 SKILL.md Phase 4.0 短路邏輯，使 Python / JS 與 Go 共用同一條件。

### 1.3 統一 `api_surface_diff_*` 的 `confidence_score` 與 `confidence_basis`

- 三個 script 都輸出 `confidence_score: float` + `confidence_basis: string`（描述為何給這個分數）。
- 在 SKILL.md 加一張對照表，明確列三語言各偵測情境的 baseline（目前只 JS / Go 寫了，Python 散落在 script 註解）。

### 驗收條件

- `tests/test_detect_env.py`（新）驗證 Python 輸出含新欄位且 schema 與 JS / Go 對齊（用 jsonschema 比較）。
- 在一個 sample fixture 專案上跑三個 `ast_scanner_*`，三邊 `verdict` 欄位皆有值。
- SKILL.md Phase 0 / Phase 3 / Phase 4 文字更新，反映新欄位用法。

### 預估規模

- 1.1: 約 100–150 行 bash（含 jq 解析）
- 1.2: Python ~50 行、JS ~80 行
- 1.3: 三邊各約 20–30 行調整 + SKILL.md 表格
- **總計**：1–2 天

### 風險與權衡

- 加欄位是 **additive** 變更，理論上不破壞既有讀取邏輯。但 SKILL.md 已經參考舊欄位的段落要逐一檢查，避免 Claude 在新欄位上做錯誤推論。
- `custom_registries` 解析涉及多種設定檔格式，可能要分階段做（先 `pyproject.toml`，再 `pip.conf`，再 `~/.pypirc`）。

---

## 任務 2 — Reference Docs 補齊（拉平三語言報告品質）

### 背景

`references/` 內三語言文件數量看似差不多，但概念覆蓋不對稱：
JS 有 runtime verification、Python / Go 沒有；Go 有 replace semantics 統整文件、
Python 對應的 transitive override 知識散落在各 workflow.md；
Python 沒有專屬的 breaking-change pattern 文件（JS / Go 都有）。

### 證據

| 概念 | Python | JS | Go |
|------|--------|----|----|
| 升級後 runtime smoke test | ✗ | ✓（`references/runtime_verification_js.md`）| ✗ |
| Transitive override / replace semantics | △（散落於 `pip_workflow.md` / `poetry_workflow.md`）| △（散落於 `npm_workflow.md` / `yarn_workflow.md`）| ✓（`references/go_replace_semantics.md`）|
| 語言特性的 breaking-change pattern | ✗（只有通用 `breaking_change_patterns.md`）| ✓（`breaking_change_patterns_js.md`）| ✓（`breaking_change_patterns_go.md`）|

### 2.1 新增 `references/runtime_verification_py.md` 與 `references/runtime_verification_go.md`

- **Python**：CLI smoke test（套件若提供 console entry point，跑 `--version` / `--help`）；
  web framework 升級（Django / Flask / FastAPI）的 dev server 啟動檢測；
  scientific stack（numpy / pandas）的 import + 基本 op 檢測。
- **Go**：`go build ./...` 是否通過、`go vet ./...`、若有 main package 跑 `--help`。
- SKILL.md Phase 0.5 / Phase 6.6 加 Python / Go 對應段落，與 JS 對齊。

### 2.2 新增 `references/python_override_semantics.md`

- 整合 pip-tools constraints、poetry `[tool.poetry.dependencies]` override、
  uv 的 `[tool.uv.sources]` / `tool.uv.override-dependencies`、
  pip 的 `--constraint` 用法。
- 對應 Phase 2 的 `bump_override` 策略，明確何時用 override、何時改 parent。
- 補一份 `references/js_override_semantics.md`（npm `overrides` / yarn `resolutions`），現有
  `npm_workflow.md` / `yarn_workflow.md` 也有提到但沒統整。

### 2.3 新增 `references/breaking_change_patterns_py.md`

- Python 特有 pattern：`@deprecated` decorator、`__getattr__` module-level 攔截、
  `warnings.warn(DeprecationWarning)`、`from __future__ import annotations` 影響、
  type hint 變更（`Optional[X]` → `X | None`）、async/sync API 切換。
- 與通用 `breaking_change_patterns.md` 區分：通用文件留語言無關規則（rename / move / removal），
  專項文件放語言慣例。

### 驗收條件

- 三個新 .md 檔產出，每份含 3+ 個具體範例 + 對應的 SKILL.md 段落引用。
- SKILL.md Phase 0 各語言 path 段落明確指向新文件（與 JS 既有對應段落同步）。

### 預估規模

- 每份文件約 150–250 行 markdown
- **總計**：1 天（純文件，無 code 變動）

### 風險與權衡

- 純文件變動，零回歸風險。
- 但 Python / Go 的 runtime verification 概念需要先有最小 PoC，否則寫成的文件 Claude 跑不出來。
  建議文件寫完後跑一次 sample 升級驗證可執行。

---

## 任務 3 — JS / Go Helper 的測試覆蓋

### 背景

`tests/` 目前只測 Python track 的 helper 與跨語言 helper，JS / Go 的 helper **完全沒有單元測試**。
schema 變更只靠 code review 守，沒有自動化防線。任務 1 改完 schema 後立刻需要這層守門。

### 證據

現有測試（`tests/`）：
- `test_ast_scanner.py`、`test_dep_tree.py`、`test_dep_tree_go.py`（注意這個是測 `dep_tree_go.py` 不是 `.sh` / `.go`）
- `test_fetch_changelog.py`、`test_parse_pm_errors.py`、`test_grant_permissions.py`、`test_jira_*.py`

**缺**：`ast_scanner_js.js`、`ast_scanner_go.go`、`dep_tree_js.js`、
`api_surface_diff_{py,js,go}.{sh,js}`、`detect_env_{,js,go}.sh`、
`run_tests_{,js,go}.sh`、`snapshot_env_*.sh`、`validate_lockfile*.sh`、`preflight*.sh`。

### 3.1 為 JS helper 加 pytest（用 subprocess + JSON 比對）

- 在 `tests/` 加 `test_ast_scanner_js.py`、`test_dep_tree_js.py`、`test_api_surface_diff_js.py`、`test_detect_env_js.py`。
- 每測試用 `tmp_path` 建一個最小 fixture 專案（`package.json` + 一兩個 `.js` / `.ts` 檔），
  `subprocess.run(["node", "scripts/ast_scanner_js.js", ...])`，解析 stdout JSON 後 assert 欄位。
- CI 已有 Node.js，不需新增 toolchain。

### 3.2 為 Go helper 加 pytest

- `test_ast_scanner_go.py`、`test_api_surface_diff_go.py`、`test_detect_env_go.py`。
- Go AST scanner 本身是 `.go` 檔需要 `go run`，fixture 專案需要最小 `go.mod`。
- CI 需要 Go toolchain（GitHub Actions 用 `actions/setup-go@v5` 即可）。

### 3.3 為共用 bash helper 加最小煙霧測試

- `test_detect_env_py.py`、`test_snapshot_env.py`、`test_validate_lockfile.py` 等。
- 不必測完整邏輯，至少驗證：能跑、退出碼 0、輸出是有效 JSON / 預期 schema。
- 用既存 `tests/conftest.py` 的 fixture pattern。

### 驗收條件

- 每個 helper script 至少 1 個 happy-path 測試 + 1 個 error-path 測試。
- CI 跑通（GitHub Actions 加 Go toolchain step）。
- `pytest --co` 不再「漏」未測 script（建議寫一個 meta test：掃 `package-upgrade/scripts/` 與 `tests/`，
  缺對應測試就 fail，列為 known-skip 也可以）。

### 預估規模

- 約 15–20 個新測試檔，每個 30–80 行
- CI 設定 ~10 行 yaml
- **總計**：2–3 天

### 風險與權衡

- Fixture 專案的維護成本：建議用 `pytest.fixture` factory 動態生成最小檔案，不要在 repo 裡塞 sample 專案。
- Go 測試會拉長 CI 時間（go 下載 module），考慮 cache。
- 任務 1 的 schema 變更後立刻補測試會比較順手；反過來先寫測試再改 schema 會雙倍工。
  **建議**：1 與 3 交錯做（每改一個 schema 就補對應測試）。

---

## 任務 4 — pnpm 支援

### 背景

PROJECT_STATUS.md 高優先 roadmap 第一項。SKILL.md `:118` 明確說「pnpm / bun → 後續 stage，
遇到時告知使用者尚未支援」。pnpm 在實務上越來越普遍（Vue、Nuxt、Vite 生態大量使用），
是目前最常被使用者問到的功能缺口。

### 證據

- `SKILL.md:118`：pnpm / bun 標為後續 stage
- `detect_env_js.sh` 偵測得到 `pnpm`（會輸出 `pkg_manager: "pnpm"`），但後續所有 phase 沒處理
- `dep_tree_js.js`、`run_tests_js.sh`、`snapshot_env_js.sh` 無 pnpm 分支

### 4.1 新增 `references/pnpm_workflow.md`

- 對應 `npm_workflow.md` / `yarn_workflow.md` 的結構。
- 重點覆蓋：
  - `pnpm-lock.yaml` 結構（與 `package-lock.json` / `yarn.lock` 顯著不同）
  - workspace（`pnpm-workspace.yaml`）
  - `pnpm add` / `pnpm update` / `pnpm dedupe` 對應到哪個 Phase 5 策略
  - `pnpm.overrides` 與 npm `overrides` / yarn `resolutions` 的對應
  - corepack 整合（與 yarn 3 類似的 `pkg_manager_bin` 解析）

### 4.2 擴充 `dep_tree_js.js` 支援 pnpm

- 偵測 `pnpm-lock.yaml`，解析其 YAML 結構（建議用 `js-yaml`，已在 inner package.json）。
- 輸出與 npm / yarn 對齊的 `dependency_type` / `current_version` / `parent_packages` / `version_constraints` schema。
- 處理 pnpm 的 hoisting / symlink 結構（與 npm flat node_modules 不同）。

### 4.3 擴充 `run_tests_js.sh` / `snapshot_env_js.sh` / `validate_lockfile.sh`

- `run_tests_js.sh`：加 `pnpm test` 分支（其實只是 `$pkg_manager_bin test`，但要確認）。
- `snapshot_env_js.sh`：備份 `pnpm-lock.yaml` 而不是 `package-lock.json`。
- `validate_lockfile.sh`：`pnpm install --frozen-lockfile` 對應 npm 的 `npm ci`。

### 4.4 更新 SKILL.md

- Phase 0 / Phase 5 移除「pnpm 不支援」的告警。
- 加 pnpm 對應的 Phase 5 命令對照（與 npm / yarn 並列）。

### 驗收條件

- 在一個真實 pnpm 專案（建議拿 Vite / Vue 官方 starter）上跑完整 Phase 0 → 7。
- `tests/test_dep_tree_js.py`（任務 3 產出）加 pnpm fixture 案例。
- README 與 PROJECT_STATUS.md 把 pnpm 從「待完成」移到「已完成」。

### 預估規模

- 4.1: 1 份新文件 ~300 行
- 4.2: dep_tree_js.js 加 pnpm parser ~150 行
- 4.3: 三個 bash script 各加 ~30 行分支
- 4.4: SKILL.md 多處小修
- **總計**：3–4 天

### 風險與權衡

- pnpm 的 hoisting model 與 npm / yarn 顯著不同（content-addressable store + symlink），
  AST scanner 可能要驗證能正確 follow symlink。可能不只 dep_tree，連 `ast_scanner_js.js`
  的 `node_modules` 走訪都要調整。
- 建議：先把 4.1 + 4.2 做完，跑一輪 dry run（不修檔），確認 dep tree 解析正確再做 4.3 / 4.4。
- bun 可以等 pnpm 完成後再決定要不要做（bun.lock 二進位、解析難度高，
  `dep_tree_js.js:830` 已標記 `no robust parser without bun runtime`）。

---

## 執行順序建議

1. **任務 1.1 + 1.2**（schema 對齊的基礎欄位）→ **任務 3.1 + 3.2**（立刻補對應測試）
2. **任務 2**（文件補齊，平行可做，零回歸風險）
3. **任務 1.3**（confidence 對齊，需要先有測試保護）
4. **任務 3.3**（補齊剩餘 bash helper 測試）
5. **任務 4**（pnpm 支援，獨立大塊）

每完成一個任務開一個 feature branch + PR，符合既有 CI / pre-commit 規範。
