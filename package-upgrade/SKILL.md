---
name: package-upgrade
description: >
  升級 Python / JavaScript / TypeScript / Go 套件或修復 CVE 漏洞的完整工作流。
  當使用者提到「升級 package」、「更新套件」、「fix CVE」、「修復漏洞」、
  「package migration」、「dependency update」、「bump version」、
  「升級 npm package」、「update axios / react / lodash」、「bump <pkg>」、
  「升級 go module」、「update go.mod」、「go get upgrade」、
  「govulncheck」、「v1 升 v2」、「major version upgrade」
  時觸發此 skill。也適用於使用者提供 CVE 編號 (如 CVE-2024-xxxxx)
  並希望修復的場景，以及提供 Atlassian Jira ticket URL
  (如 https://trendmicro.atlassian.net/browse/V1E-148968) 或
  Jira issue key (如 V1E-148968) — 此時會自動讀取 ticket 內容、
  分析應升級的套件、完成後將報告 comment 回 ticket，並依目前 ticket
  狀態提議推進 (To Do → Ready for Work → Development → Done)。
  Python: 支援 pip、poetry、uv 三種套件管理工具。
  JavaScript/TypeScript: 支援 npm、yarn (1 & 3 Berry)、pnpm、bun，含
  TypeScript .d.ts API surface diff、workspace/monorepo 偵測、
  @types/<pkg> 同步升級偵測。
  Go: 支援 go modules、major version path rewrite (v1→v2+)、apidiff API surface
  diff、govulncheck reachability 分析、vendor mode、go.work workspace、
  replace directives。
  自動偵測專案使用的語言與工具。即使使用者只是隨口問「這個套件能不能升級」，
  也應觸發此 skill 來做完整分析。
---

# Package Upgrade / CVE Fix Skill

## 概觀

你是一位資深的套件遷移專家，同時熟悉 Python 與 JavaScript / TypeScript 生態。
當使用者要求升級套件或修復 CVE 時，按照以下工作流程逐步執行。你自己就是分析引擎
— 不需要呼叫外部 LLM API。

關鍵原則:
- **在修改任何專案內容之前，必須先建立新的 Git 分支** (Phase 5.1)
- 每個步驟先用 helper script 取得結構化數據，再用你的推理能力分析
- 在修改任何檔案之前，先備份環境
- 測試程式的修改必須經過使用者確認
- 完成後建立 Pull Request 供 review
- 全程保持可回退
- **若觸發來源是 Jira ticket** (Phase 1 情況 C)，在整個 session 中保留
  `jira_context = { site_host, cloud_id, issue_key, url }`，
  完成後 (Phase 7.5/7.6) 將報告 comment 回 ticket、並依目前狀態
  分階段提議轉換 (To Do → Ready for Work、Ready for Work → Development，
  最後在使用者同意下才轉 Done)

---

## Phase 0: 環境偵測

### Step 0.1: 偵測語言

先看專案根目錄有哪些訊號檔，**多語言並存時的偵測順序**：Go > JS > Python
（Go 與 JS 同時存在的可能性低，且 `go.mod` 是明確訊號；
Python 與 JS 同時存在時優先 JS — Python 全棧專案常常不會有 `package.json`，
但前端專案可能順手放個 `setup.py`）：

| 訊號 | 語言 |
|------|------|
| `go.mod` | Go |
| `package.json` | JavaScript / TypeScript |
| `pyproject.toml`、`requirements.txt`、`setup.py`、`Pipfile`、`uv.lock`、`poetry.lock` (且無 `package.json`) | Python |
| `Gopkg.toml`、`glide.yaml`、`vendor.json`（但無 `go.mod`） | Go (legacy) — 提示先 migrate 到 modules |
| 多種同時存在且難以判斷 | 詢問使用者要升的是哪一邊的套件 |

`language ∈ {python, javascript, go}` 要在 session 中保留，後續所有 phase 都會用到。

### Step 0.2: 偵測套件管理工具

**若 `language == "python"`**，執行：

```bash
bash scripts/python/detect_env.sh <project_path>
```

輸出為 JSON，**schema 與 `detect_env_js.sh` / `detect_env_go.sh` 對齊**，重點欄位:
- `language`: 固定 `"python"`
- `pkg_manager`: pip | poetry | uv
- `pkg_manager_bin`: `which poetry` / `which uv` / `which pip` 解析後的絕對路徑（後續 phase 可選用）
- `pkg_manager_version`: 例 1.7.1
- `python_version`: 例 3.11.4
- `lockfile_path`: 鎖定檔路徑 (如有)
- `pip_lock_file`: pip 專案的 lock 檔案 (如 requirements.lock)
- `has_pip_tools`: 是否使用 pip-tools (requirements.in)
- `dependency_files`: 依賴宣告檔清單
- `env_var_placeholders`: config 檔中引用的 `${ENV_VAR}` 清單（如 `JFROG_TOKEN`）
- `custom_registries`: 自訂 registry 對映表，每筆含 `name` / `registry` / `auth_env_var` / `source_file`（目前解析 `pyproject.toml [[tool.poetry.source]]` 與 `pip.conf` 的 `index-url` / `extra-index-url`）
- `py_config_files`: 已偵測的 `pyproject.toml` / `pip.conf` / `setup.cfg` 等
- `git_remote_host`: 例 `github.com` 或內部 GHE
- `memory_hints`: 例 `["private_registry", "poetry_source", "pip_extra_index", "non_default_remote"]`

根據偵測到的 pkg_manager，讀取對應的 references 文件:
- pip → 讀 `references/python/pip_workflow.md`
- poetry → 讀 `references/python/poetry_workflow.md`
- uv → 讀 `references/python/uv_workflow.md`

接著一律讀:
- `references/python/breaking_change_patterns.md` — Python 慣例（`@deprecated` / `__getattr__` / async/sync / C ext ABI 等）
- `references/python/override_semantics.md` — Phase 2 `bump_override` 策略選擇參考
- 偵測為 web app / CLI / scientific stack 時 → `references/python/runtime_verification.md`

**若 `language == "javascript"`**，執行：

```bash
bash scripts/javascript/detect_env.sh <project_path>
```

輸出 JSON 包含（重點欄位）：
- `pkg_manager`: npm | yarn | pnpm | bun | unknown
- `pkg_manager_bin`: **後續所有 phase 一律使用這個變數呼叫套件管理工具**（例 `node .yarn/releases/yarn-3.8.2.cjs`），不要 hardcode `yarn` / `npm`
- `pkg_manager_version`: 例 3.8.2
- `uses_corepack`: yarn/pnpm 是否走 corepack-managed 路徑
- `yarn_release_path` / `yarn_node_linker`: yarn 特定
- `node_version`: 例 20.x.x
- `lockfile_path`: package-lock.json / yarn.lock / ...
- `manifest_files`: 所有 package.json 路徑（含 workspace）
- `is_workspace` / `workspace_globs`: 是否為 monorepo
- `has_typescript` / `tsconfig_path` / `types_entry`
- `test_framework_hint`: jest / vitest / mocha / node-test / unknown
- `npm_config_files`: 已偵測的 `.npmrc` / `.yarnrc.yml` / `.yarnrc.default.yml`
- `env_var_placeholders`: config 檔中引用的 `${ENV_VAR}` 清單（如 `JFROG_TOKEN`）
- `custom_registries`: 自訂 scope → registry + auth env var 對映表
- `git_remote_host`: 例 `github.com` 或內部 GHE
- `has_node_modules`: 影響 dep_tree 與 test 能否在本地跑
- `memory_hints`: 例 `["yarn3_corepack", "workspace", "custom_registry", "non_default_remote"]`

接著一律讀 `references/javascript/workflow.md` 為主文件，依 `pkg_manager` 補讀：
- `npm` → `references/javascript/npm_workflow.md`
- `yarn` (含 yarn 3 Berry) → `references/javascript/yarn_workflow.md`
- `pnpm` → `references/javascript/pnpm_workflow.md`
- `bun` → 後續 stage，遇到時告知使用者尚未支援（bun.lock 為二進位格式，dep_tree 解析受限）
- 一律讀 `references/javascript/ast_strategy.md`、`references/javascript/breaking_change_patterns.md`、`references/common/auth_tokens.md`
- Phase 2 涉及 transitive override 時 → `references/javascript/override_semantics.md`（涵蓋 npm `overrides` / yarn `resolutions` / `pnpm.overrides` / bun 的對應寫法）

**若 `language == "go"`**，執行：

```bash
bash scripts/go/detect_env.sh <project_path>
```

輸出 JSON 包含（重點欄位）：
- `pkg_manager`: gomod | dep | glide | govendor | gopath | unknown
- `go_version`: runtime version（例 `1.21.5`）
- `module_path`: 主模組路徑（go.mod 第一行 `module ...`）
- `go_directive` / `toolchain_directive`: go.mod 內宣告的最低 Go 版本
- `has_workspace`: 是否為 `go.work` 多模組 workspace
- `workspace_modules`: workspace 內的子模組路徑清單
- `is_vendored`: 是否使用 `vendor/` 目錄模式
- `has_replace_directives` / `replace_directives`: `go.mod` 內的 `replace` 條目
- `has_exclude_directives`: 是否有 `exclude` 條目
- `go_env`: 內含 `GOPROXY` / `GOPRIVATE` / `GOFLAGS` / `GOOS` / `GOARCH`
- `govulncheck_available` / `apidiff_available` / `gomajor_available`: 可選工具是否安裝
- `netrc_present`: `~/.netrc` 是否存在（私有 module 認證用）
- `memory_hints`: 例 `["vendored", "workspace", "replace_directives", "private_modules"]`

接著一律讀 `references/go/workflow.md` 為主文件，並依場景補讀：
- 觸發 major version (`v2+`) 升級 → `references/go/major_version_paths.md`
- CVE / 漏洞流程 → `references/go/govulncheck.md`
- 一律讀 `references/go/breaking_change_patterns.md`、`references/common/auth_tokens.md`
- 偵測為 CLI binary / server 時 → `references/go/runtime_verification.md`

⚠️ **legacy 工具偵測**：若 `pkg_manager == "dep"|"glide"|"govendor"|"gopath"`,
**停下來告訴使用者先 migrate 到 Go modules**（`go mod init <path> && go mod tidy`），
然後重跑 skill。此 skill **不處理** legacy 工具升級。

### Step 0.3: Pre-flight checks（三條路徑都必跑）

**Phase 1 之前必須跑 pre-flight**，把所有可能 block 的環境問題一次列出。
別像 IMPROVEMENTS #1/#2/#3 那樣跑到 Phase 5 才撞牆。三支腳本輸出 schema 對齊
（`blockers` / `warnings` / `ok` / `summary` / `env`），LLM 可以同一套邏輯處理。

**Python path**:

```bash
bash scripts/python/preflight.sh <project_path>
```

腳本會自動 source `<project>/.env.pip` / `.env.poetry` / `.env.uv` / `.env.pypi` /
`.env.jfrog`（若存在），所以前一次 session 持久化的 token 不需要重新提供。檢查：
1. `python3` 在 PATH 且版本可解析
2. 偵測到的 pkg_manager binary（pip / poetry / uv）在 PATH
3. `requirements.in` 存在時 `pip-compile` 可用
4. virtualenv 是否啟用（`VIRTUAL_ENV` / `CONDA_PREFIX` / `.venv/` / `venv/`）
5. `pyproject.toml` / `pip.conf` / `poetry.toml` 中 `${ENV_VAR}` 引用是否都已設定
6. `gh` CLI 對 `git_remote_host` 是否已認證
7. git working tree 是否乾淨
8. 偵測到的 pip lock file（informational）

**JS path**:

```bash
bash scripts/javascript/preflight.sh <project_path>
```

腳本會自動 **source `<project>/.env.jfrog` / `.env.npm` / `.env.github`**（若存在），
所以前一次 session 持久化的 token 不需要重新提供。接著檢查：
1. `pkg_manager_bin` 是否可呼叫（yarn 3 是 `.yarn/releases/yarn-*.cjs` ⇒ corepack）
2. `env_var_placeholders` 中每個變數是否已設定（含 source `.env.*` 後）
3. `gh` CLI 對 `git_remote_host` 是否已認證（內部 GHE 也要檢查）
4. git working tree 是否乾淨（防 WIP 被混進升級分支）
5. `node_modules/` 是否存在（決定 dep_tree 走 lockfile-first 或 `npm ls`）
6. `node` 是否在 PATH

**Go path**:

```bash
bash scripts/go/preflight.sh <project_path>
```

腳本自動 source `.env.go` / `.env.jfrog` / `.env.github`。接著檢查：
1. `go` binary 在 PATH 且版本 ≥ `go_directive`
2. `pkg_manager == "gomod"`（legacy 工具 = blocker）
3. `govulncheck` 是否安裝（warn — 缺失時 Phase 1 CVE 流程會降級為只看 dep tree）
4. `apidiff` 是否安裝（warn — 缺失時 Phase 3 只走 changelog + git diff 雙軌）
5. `gomajor` 是否安裝（warn — major version 升級會走手動 fallback）
6. `GOPROXY` 設定合理（非 `off`）
7. `GOPRIVATE` 有設時 `~/.netrc` 應存在（私有 module 認證）
8. vendor mode / workspace mode / replace directive 的 informational warn
9. `gh` CLI 對 `git_remote_host` 是否已認證
10. git working tree 是否乾淨

**遇到 ❌ blocker 時**：把整份 checklist 給使用者看，並提供選項：
```
有 N 個 blockers, M 個 warnings.

[1] 全部修復後我再回來繼續 (建議)
[2] 部分跳過,走可用的 fallback (e.g. 缺 token → lockfile-only 升級;
    缺 gh → 印 PR URL 讓使用者手動建立)
[3] 中止
```

### Step 0.3.1: Token-acquisition 互動（缺 JFROG_TOKEN 等 token blocker 時）

對 `env_*_missing` 類 blocker，**逐字**用 `references/common/auth_tokens.md` 指定的詢問
範本（IMPROVEMENTS feedback 要求的措辭），別自己換句話說。範例（JFROG_TOKEN）：

```
🔑 取得 token:
  go to https://jfrog.trendmicro.com/ui/admin/artifactory/user_profile.
  In the next step, click "Generate Identity Token" to generate a token
  that will be used as part of CURL.
```

**使用者提供 token 後的儲存規則**（必跑 `scripts/common/save_token.sh`）：

1. 先 `export <ENV_VAR>=<value>` 進當前 session（讓 Phase 5 命令可用）
2. 呼叫 `bash scripts/common/save_token.sh <project_path> .env.<service> <KEY> "<value>"`：
   - 檔案不存在 → 直接創建（`{"status":"created"}`）
   - 檔案存在但無同名 key → 直接追加（`{"status":"appended"}`）
   - 檔案存在且**有同名 key** → 腳本回 exit 2 + `{"status":"conflict"}`
3. 收到 `conflict` → 詢問使用者：
   ```
   ⚠️ <project>/.env.jfrog 已經有 JFROG_TOKEN 值。
   是否覆蓋成你剛才提供的新 token?
   [Y] 是, 覆蓋舊 token
   [N] 否, 保留現有 .env.jfrog 內容 (新 token 仍 export 進當前 session)
   ```
   - 選 [Y] → 重跑加 `--force` flag → `{"status":"replaced"}`
   - 選 [N] → 不寫檔，僅 session 內生效

`save_token.sh` 同時負責 `chmod 600` 與把 `.env.<service>` 加進 `<project>/.gitignore` —
不需要 LLM 手動處理。**永遠不要直接用 Write/Edit 工具寫 token 檔**，那會失去
chmod / gitignore 保護。

下次 session 跑 preflight 時，相同的 token 就由 `preflight.sh` 自動 source，
不會再被詢問。

**警告 (⚠️) 不阻擋**，但要在 Phase 7.1 報告中列出（讓 reviewer 知道哪些步驟跑在
降級模式下）。

### Step 0.4: Project memory write（針對非預設設定）

依 `memory_hints` 主動寫 project memory（不要等到 session 結束才寫；下次 session
就不必重新發現）：

- `yarn3_corepack` → memory: 「此 repo 使用 corepack-managed yarn 3，pkg_manager_bin 須走 `.yarn/releases/yarn-*.cjs`」
- `workspace` (JS) → memory: 「此 repo 是 JS workspace monorepo，升級需考慮哪個 workspace 是目標」
- `workspace` (Go) → memory: 「此 repo 是 Go `go.work` workspace，升級需指定子模組」
- `custom_registry` → memory: 「此 repo 使用自訂 registry `<host>`，需要 `${ENV_VAR}`」
- `non_default_remote` → memory: 「git remote host 是 `<host>` (非 github.com)，`gh` 要登入此 hostname」
- `vendored` (Go) → memory: 「此 repo 使用 vendor mode；Phase 5 必須跑 `go mod vendor`」
- `replace_directives` (Go) → memory: 「`go.mod` 含 replace directive（位於 `<行號>`），升級時不要覆蓋」
- `private_modules` (Go) → memory: 「`GOPRIVATE` 涵蓋 `<pattern>`，私有 module 透過 `.netrc` 認證」
- `legacy_dep` / `legacy_glide` / `legacy_govendor` / `legacy_gopath` (Go) → memory: 「使用 legacy 工具 `<name>`，建議先 migrate 到 Go modules」

**特別注意 pip 專案的 lock 檔案**:

如果偵測到 `pip_lock_file` 不為空,表示專案使用了 lock 機制:
- `requirements.in` + `requirements.txt` → 使用 pip-tools
- `requirements.txt` + `requirements.lock` → 使用自定義 lock
- `requirements.txt.lock` 或其他 `*.lock` → 自定義 lock 模式

**⚠️ 重要**: 在開始前,先閱讀 `references/common/important_dependency_update.md`,
了解如何正確更新依賴檔案。關鍵要點:
- **pip**: 必須手動編輯 `requirements.txt` 或 `pyproject.toml`
- **poetry**: 使用 `poetry add pkg@version` (不是 `poetry update`)
- **uv**: 使用 `uv add "pkg>=version"` (不是 `uv lock --upgrade-package`)

### Step 0.5: (JS only) Runtime Verification Baseline (optional)

**僅 `language == "javascript"` 時走這步**。Python / Go path 跳過。

JS 升級最容易發生的問題不是 type error 或 unit test fail，而是 `npm run dev`
一啟動就 white screen / module not found / runtime error — 這些**只有實際啟動
server 才能抓到**。本步驟在**任何變更之前**抓 baseline，Step 6.6 升完後再跑
一次做 diff，把「升級造成的」regression 跟「本來就有的雜訊」分開。

**何時跳過 (Step 0.5 自身先做的判斷)**：

讀 `references/javascript/runtime_verification.md` 的「Web app 偵測訊號」章節，根據
`package.json#dependencies` + `scripts` 判斷：
- 沒有 web framework dep (next/vite/react-scripts/vue/angular/nuxt/sveltekit/
  remix/astro/express/fastify/...) 且沒有 `scripts.dev|start|serve` →
  **library / CLI tool，直接跳過 Step 0.5 與 Step 6.6**，不需詢問使用者
- 有任一訊號 → 進入下面的詢問流程

**詢問使用者 (偵測到 web app 後)**：

```
偵測到此專案像是 web app (framework: {next}, dev script: "npm run dev" → http://localhost:3000)。

升級 JS package 最常見的 regression 是 dev server 啟動後 white screen / runtime error，
unit test 抓不到。建議在升級**前**先抓一份 baseline (約 30-60 秒)，升完後跑一次 diff。

[1] 跑 baseline (推薦)
[2] 跳過 runtime verification (只跑 unit test)
[3] 自訂啟動指令 / port / URL 後跑 baseline
```

選 [1] → 用偵測到的 cmd / url 跑；選 [3] → 收使用者提供的字串再跑。

**詢問是否啟用 T2 (headless browser)**：

```
T1 (預設) 用純 HTTP probe + stderr scan，抓套件 import 失敗、編譯失敗。
T2 額外用 Playwright headless 開頁，抓 React runtime error / white screen / console error。
T2 需先下載 chromium (~150MB，約 1-2 分鐘)。

[1] 只跑 T1 (預設、輕量)
[2] 加跑 T2 (高保真，首次需下載 chromium)
[3] 我自己用瀏覽器看 (T3 fallback — 升前升後我會請你各確認一次)
```

選 [2] 時：先檢查 `node -e "require('playwright')"` 是否成功。若失敗，
跑 `cd <project>/.package-upgrade-cache && npm init -y >/dev/null && npm install playwright --no-save && npx playwright install chromium`
(或在 skill scripts 旁安裝，依使用者偏好；安裝完整 path 用 `NODE_PATH` 注入)。

**跑 baseline**：

```bash
node scripts/javascript/runtime_verify.js <project_path> \
    --mode baseline \
    --start-cmd "<確認後的指令>" \
    --url "<確認後的 URL>" \
    --timeout 60 \
    [--playwright]    # 僅當使用者選 T2
```

輸出寫 `<project>/.package-upgrade-cache/runtime-baseline.json` (LLM 自己負責落檔；
腳本只 print 到 stdout，避免假設 cache 結構)。腳本會自動把 `.package-upgrade-cache/`
加進專案 `.gitignore`。

**baseline 結果處理**：

- `boot_status: "ready"` + `http_status: 2xx/3xx` → 正常 baseline，繼續 Phase 1
- `boot_status: "ready"` + `http_status: 5xx` → 警告使用者：「baseline 雖然 server
  起得來但首頁回 500，升完後若 500 還在不算 regression」並繼續
- `boot_status: "crashed"` / `"timeout"` → 詢問使用者：[1] 修好後重抓 baseline
  [2] 仍記錄此 baseline 作對照 (升完後 server 反而起來 = 升級修好了既有問題) [3] 跳過
- `boot_status: "port_conflict"` → 提醒使用者 kill 舊行程或改 port，重抓

**T3 (使用者選 [3] 純人眼)**：本步只記錄一句「使用者承諾自己用瀏覽器看 baseline」
到 session 狀態，**不啟動 server**。Step 6.6 升完後再請使用者在同一個瀏覽器頁面
重新整理確認。

---

## Phase 1: 輸入解析

### 情況 A: 使用者指定 package 名稱

直接進入 Phase 2。

### 情況 B: 使用者提供 CVE / BDSA / GHSA 編號

抽取規則（IMPROVEMENTS #9）：

```python
patterns = [
    re.compile(r'CVE-\d{4}-\d{4,7}'),         # public CVE
    re.compile(r'BDSA-\d{4}-\d+'),            # BlackDuck internal
    re.compile(r'GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}'),  # GitHub Advisory
]
```

**若只抽到 `BDSA-...`**（內部編號，外部不可查）→ 走 `references/common/bdsa_mapping.md` 的
fallback 鏈（OSV → GitHub Advisory → npm audit）把對應的 public CVE/GHSA 補齊，
報告中明確列出 BDSA → CVE → GHSA 三方對映表。

1. 用 web search / API 查詢 vulnerability 資訊:
   - 搜尋 `{CVE-ID} python package fix`
   - 搜尋 `site:osv.dev {CVE-ID}`
   - 搜尋 `site:nvd.nist.gov {CVE-ID}`
   - OSV API: `POST https://api.osv.dev/v1/query` (詳見 `bdsa_mapping.md`)

2. 從搜尋結果中提取:
   - 受影響的 package 名稱
   - 受影響的版本範圍
   - 修復版本
   - 嚴重性 (CVSS)
   - 漏洞描述

3. **你的分析任務** (這是你作為 LLM 的價值):
   - 閱讀 CVE 描述，理解漏洞的攻擊向量
   - 用 `grep -rn` 搜尋專案中對該 package 的使用方式
   - 判斷這個漏洞是否真的影響到專案的用法
   - 產出風險評估:
     - critical: 專案直接使用了受影響的功能
     - high: 專案間接使用了受影響的功能
     - medium: 專案使用了該 package 但不涉及漏洞路徑
     - low: 專案幾乎不使用受影響的功能
   - 將評估結果告知使用者

**Go path 額外步驟（govulncheck reachability）**:

若 `language == "go"` 且 `govulncheck_available == true`，**在 grep 風險評估之前**
先跑 reachability 分析（call graph 比 grep 精準很多）：

```bash
bash scripts/go/govulncheck.sh <project_path> --cve <CVE-ID>
```

輸出含 `match` 欄位：
- `called` — call graph 證實有呼叫到漏洞函式 → **critical**
- `imported` — dep tree 中存在但 call graph 不可達 → **medium**（仍建議升）
- `not_present` — dep tree 不含此套件 → **告知使用者不影響**，問是否仍要升

`call_sites` 提供精確的 `file:line:function`，比 grep 結果可靠 — 直接列在報告中。

**`govulncheck_available == false`**: 告知使用者降級為 grep-only 模式，繼續走原本
LLM 推理流程，但在 Phase 7.1 報告中標明缺少 reachability 分析。

詳見 `references/go/govulncheck.md`。

**Python path 額外步驟（pip-audit reachability）**:

若 `language == "python"` 且 `pip-audit` 可用（pre-flight 會偵測），**在 grep 風險
評估之前**先跑：

```bash
bash scripts/python/pip_audit.sh <project_path> --cve <CVE-ID>
```

輸出 schema 對齊 govulncheck_go.sh，含 `match` 欄位（`called` / `imported` /
`not_present`）。Python 沒有原生 call graph，腳本以「`pip-audit` 列出脆弱套件 +
從 advisory 文字抽取符號名 + `ast_scanner.py` 找實際使用點」近似 reachability：

- `called` — source code 真的用到 advisory 提到的 symbol → **critical**
- `imported` — 有 import 但 advisory 的 symbol 沒在 usages 出現 → **medium**
- `not_present` — dep 完全沒被 import → **告知使用者不影響**

精度低於 Go (Python 動態本質)，但仍能把純 transitive 噪音篩掉。`extracted_symbols`
與 `import_names` 都列出來，方便 LLM 在報告中說明 reachability 推論依據。

**`pip-audit` 未安裝時**: 告知使用者降級為 grep-only 模式，並建議
`pip install pip-audit` 後重跑。

### 情況 C: 使用者提供 Jira URL 或 Jira ID

範例輸入:
- `https://trendmicro.atlassian.net/browse/V1E-148968`
- `V1E-148968`
- 任何包含 `/browse/<KEY>` pattern 的 URL

詳細流程請讀 `references/common/jira_workflow.md`。摘要如下:

#### Step 1.C.1: 解析輸入

用 regex 抽出:
- `site_host`: 例 `trendmicro.atlassian.net`
- `issue_key`: 例 `V1E-148968` (格式 `[A-Z][A-Z0-9]+-\d+`)

如果只給 issue key (沒有 URL):
- 先檢查 auto-memory 是否有先前儲存的 default site (reference type)
- 若有 → 直接使用
- 若無 → 詢問使用者並在使用者回答後將 site host 存到 memory

**組出完整 URL 並保留** (後續 Phase 7 commit/PR 必須引用):

```
issue_url = f"https://{site_host}/browse/{issue_key}"
```

範例: `https://trendmicro.atlassian.net/browse/V1E-148968`

這個 URL 是必須的 — 即使使用者一開始只給 issue key,也要在這一步補出完整連結,
並在 Phase 7.2 commit message 第一行、Phase 7.3 PR title/body 中明顯呈現,
讓 git web portal (GitHub/Bitbucket/GitLab) 上的 reviewer 一眼就能跳到 Jira ticket。

#### Step 1.C.2: 抓取 ticket 內容

**優先用 Atlassian MCP** (使用者多半已透過 claude.ai 連接):

```
mcp__claude_ai_Atlassian_Rovo__getJiraIssue(
  cloudId=<site_host>,           # 直接傳 site hostname; MCP 會自動解析
  issueIdOrKey=<issue_key>,
  responseContentFormat="markdown",
  fields=["summary", "description", "status", "labels", "comment"]
)
```

**權限失敗 fallback**: 若 MCP 回傳 401 / 403 / `unauthorized` / `not accessible`:

> 暫停並詢問使用者:
>
> 無法存取 `{site}/browse/{key}` (HTTP {status})。請選擇:
> - **[1]** 提供 Atlassian email + API token (我會用環境變數呼叫 Atlassian REST API,
>        token 只在這個 session 暫存,不會寫到任何檔案;⚠️ token 會出現在這個對話的 transcript 中)
> - **[2]** 我已在瀏覽器登入 Atlassian MCP 連線,請重試
> - **[3]** 我會手動貼上 ticket 的內容到對話中

若使用者選 [1]:
1. 詢問 email 和 API token (token 連結: `https://id.atlassian.com/manage-profile/security/api-tokens`)
2. 設定環境變數 `ATLASSIAN_EMAIL` 和 `ATLASSIAN_API_TOKEN`
3. 呼叫 `python scripts/common/jira_fetch.py <site_host> <issue_key>` 取得 JSON

#### Step 1.C.3: 分析 ticket 內容 (LLM 任務)

從 ticket 的 summary / description / comments / labels 中抽取:

- **目標 package 名稱** — 找以下 pattern:
  - `pkg==X.Y` / `pkg X.Y` / `upgrade <pkg>` / `bump <pkg>`
  - `affects <package>` / `<package> needs update`
  - 程式碼區塊中的 import 或 requirements 內容
  - 標題中明確提到的套件名

- **目標版本** (如有明確指定): `X.Y.Z` 或範圍 `>=X.Y`
- **CVE 編號** (若提到): 抽出 `CVE-XXXX-XXXXX` → 串接情況 B 的 CVE 流程
- **驗收條件** (Acceptance Criteria): ticket 描述中是否有明確的 done 條件

#### Step 1.C.4: 確認點 — 等待使用者校正

向使用者報告解析結果並暫停:

```
從 Jira ticket {KEY} 解析到:
- Ticket 標題: {summary}
- 狀態: {status}
- 分析結果:
  - 套件: {package_name}
  - 目標版本: {target_version} ({"明確指定" | "推論"})
  - 相關 CVE: {cve_id_if_any}
  - 驗收條件: {acceptance_criteria_if_any}

要繼續以這個套件 + 版本進行升級嗎？
[Y] 是, 繼續 Phase 2
[N] 不對, 我會告訴你正確的套件/版本
```

#### Step 1.C.5: 保存 jira_context

在 session 中保留:
```
jira_context = {
  "site_host": "trendmicro.atlassian.net",
  "cloud_id": "<resolved cloud id, or site_host if MCP accepted it>",
  "issue_key": "V1E-148968",
  "url": "https://.../browse/V1E-148968",
  "auth_mode": "mcp" | "rest_token",   # Phase 7.5/7.6 要用同一個方式
  "summary": "<for the comment header>"
}
```

---

## Phase 2: 依賴分析

### Step 2.0: (JS only) Workspace 條件分流

若 Phase 0 的 `is_workspace: true`，並不是一律 hard-stop（IMPROVEMENTS #6）。
依 `dependency_type` 與 `upgrade_strategy` 條件處理：

| dependency_type | upgrade_strategy | 動作 |
|---|---|---|
| `transitive` | `lock_only` | ✅ 繼續 — workspace 不影響 lock-only 升級 |
| `transitive` | `parent_upgrade` | ⚠️ 詢問：parent package 要在哪些 workspace 升 |
| `direct` | — | ⚠️ 詢問：哪個（些）workspace 是目標 |
| `direct` (root only) | — | ✅ 繼續 |

`dep_tree_js.js` 的 `workspace_info.locations` 已經告訴你 target 到底出現在哪些
workspace（與哪個 dep 欄位）。詢問時直接帶入這份清單，**不要**讓使用者自己列。

詢問模板（含實裝資料）—— 多選為一等公民，預設推薦 `all`（CVE / security
升級通常需要把所有命中 workspace 一起升）：

```
偵測到此 repo 是 workspace monorepo (workspaces 共 {len(workspaces)} 個)。
{package} 目前出現在以下 workspaces：

  [1] packages/foo   dependencies     ^1.2.3
  [2] packages/bar   devDependencies  ^1.2.0
  [3] packages/baz   peerDependencies ^1.2.0

（其餘 N 個 workspace 沒有引用此套件，不會被改動）

要升級哪些 workspace？(可多選)
  - all      (推薦) 一次升完所有命中的 workspaces — CVE / security 升級通常選這個
  - 1 3      指定編號，空白分隔，可多選
  - root     只改 root package.json（僅 hoist 模式有效）
```

收到回應後：
- `all` → 對 `workspace_info.locations` 中每一筆都跑 Phase 5 升級
- 編號清單 → 只對選到的子集跑
- `root` → 僅改 root `package.json`，警告使用者「只在 hoist 模式下有效，否則子 workspace 仍會用舊版」
- 任何看不懂的輸入 → 重新顯示 prompt，不要自行猜測

若 `workspace_info.locations` 為空但 `is_workspace_root: true`，代表此 monorepo 完全
沒引用 target — 跳出並警告使用者輸入是否正確，不要往下做升級。

### Step 2.0.1: (Go only) `go.work` workspace 與 vendor mode 分流

若 `has_workspace: true`（`go.work` 存在）：

```
偵測到此 repo 是 go.work workspace,內含子模組:
  - ./module-a
  - ./module-b

`{package}` 升級要套用到哪個子模組?
[1] 列出有 import 此 package 的子模組,讓我選
[2] 我已知目標是 `./module-x`
[3] 套用到所有子模組
```

選 [1]時用 `ast_scanner_go.go` 對每個子模組掃 import，列出命中的子模組讓使用者挑。

若 `is_vendored: true`：**不阻擋繼續**，但提醒「Phase 5.4 完成後會跑 `go mod vendor` 重建
vendor 目錄，PR diff 行數會顯著增加」。

### Step 2.1: 取得依賴樹

**若 `language == "python"`**：

```bash
python scripts/python/dep_tree.py <project_path> <package_name> \
    [--target-version <v>] [--no-probe]
```

`--target-version` 與 `--no-probe` 為選用。提供 `--target-version` 時，腳本會對
每個 direct parent 呼叫 PyPI JSON API 取 `info.requires_dist`，分類為
`satisfies` / `would_not_help_pin` / `no_dep` / `unknown`，並把每條候選策略
（`direct_bump` / `lock_only` / `bump_parent` per parent / `bump_parent_then_target`）
依 confidence 排序輸出在 `upgrade_strategies[]`，第一名同步寫到
`recommended_strategy`。未提供 target_version 時 parent_analyses 為空，策略 fallback
為僅依 `dependency_type` 判斷。schema 對齊 `dep_tree_go.py` 的 `parent_analyses` /
`upgrade_strategies`，Phase 2.2 可直接用同一套渲染邏輯。

**若 `language == "javascript"`**（lockfile-first，**不需要 node_modules**）：

```bash
node scripts/javascript/dep_tree.js <project_path> <package_name>
```

JS 版的 dep_tree 已改為直接解析 lockfile（`yarn.lock` v1/v3、`pnpm-lock.yaml`、
`package-lock.json`），不需要 `npm ls`。輸出中的 `source` 欄位會標明使用了
哪個 lockfile（`yarn3-lock` / `yarn1-lock` / `pnpm-lock` / `npm-lock` / `npm-ls`）。

**若 `language == "go"`**：

```bash
bash scripts/go/dep_tree.sh <project_path> <module_path> [--target-version vX.Y.Z]
```

Go 版透過 `go list -m -json all` + `go mod graph` 取得完整資訊。提供 `--target-version`
能讓輸出含 `is_major_version_jump` 與 `target_module_path` 判斷。輸出多出 Go 特有欄位:
- `current_module_path`: 解析後的實際 module path（含 `/v2` 等 suffix）
- `target_module_path`: 若目標是 major version，會是 `<base>/v<N>`
- `is_major_version_jump`: bool
- `available_majors`: 列出 `/v2`、`/v3` 等可用 major variant
- `latest_in_current_major`: 不跨 major 的話最高可以升到哪
- `replace_directive`: 若 `go.mod` 已對此 module 有 `replace`

兩個 script 的輸出 schema 對齊，包含:
- `dependency_type`: direct | transitive | both | peer (JS only) | unknown
- `current_version`: 目前使用的版本
- `parent_packages`: 如果是 transitive，哪些 direct pkg 引用它
- `version_constraints`: 各 parent 對此 pkg 的版本約束（JS 另含 `__declared__` 自我約束）
- `is_peer` (JS only): 是否為 `peerDependencies`
- `declared_in` (JS only): `["dependencies", "devDependencies", ...]`
- `full_tree`: 完整依賴子樹

JS 額外輸出（供 Phase 2.0 與 Phase 5 使用）：
- `workspace_info.is_workspace_root`: bool — 是否為 monorepo root
- `workspace_info.workspaces`: 全部偵測到的 workspace list（`{workspace, name}`）
- `workspace_info.locations`: target 出現在哪些 workspace（`{workspace, name, declared_in, constraint}`）
  → Phase 2.0 用這個取代「全域 dep_tree」的範圍對話
- `types_sibling.applicable`: bool — target 是否為 `@types/...`（若是則 false）
- `types_sibling.sibling_name`: 對應 DefinitelyTyped 名稱（`@scope/x` → `@types/scope__x`）
- `types_sibling.present`: bool — root manifest 或 lockfile 是否已含此 sibling
- `types_sibling.recommendation`: 若 `present == true`，提示 Phase 5 一併升 sibling

### Step 2.2: 判斷升級路徑

根據 `dependency_type` 分支處理:

#### Type A — 直接引用

**Python path**:
1. 用 web search 查 PyPI 上目標版本的 `python_requires`
   - 搜尋 `{package_name} {target_version} pypi python_requires`
   - 或 `web_fetch https://pypi.org/pypi/{package_name}/{target_version}/json`
2. 比對專案的 python 版本
3. 若相容 → 可升級，進入 Phase 3
4. 若不相容 → 告知使用者 Python 版本不滿足

**JavaScript path**:
1. 用 `web_fetch https://registry.npmjs.org/{package_name}/{target_version}` 取
   `engines.node` 與 `peerDependencies`
2. 比對 `node --version` 與 Phase 0 偵測到的 `node_version`
3. 比對 `peerDependencies` 中每個 peer 在專案中的目前版本（用 `dep_tree_js.js`
   單獨查每個 peer）
4. 若 Node 不相容或 peer range 失敗 → 告知使用者，問是否要先升級 Node / peer
5. 若相容 → 進入 Phase 3

#### Type B — 間接引用 (transitive)

> **核心原則** (JS / Python / Go 各有不同):
> - **Python**: 沒有 manifest-level transitive 釘版機制（pip 沒有 overrides），
>   所以 transitive 升級走 lock-only。下方 Python-only path 沿用既有邏輯。
> - **JavaScript**: 優先「**把意圖寫進 package.json**」 — 即升級直接 parent
>   或使用 overrides/resolutions。**hand-edit lockfile 是 last resort**，
>   只在 package.json 完全沒有 target 的任何約束時才允許。
> - **Go**: `go.mod` 同時是 manifest，沒有 lock-only 概念。優先 `bump_parent`
>   （讓 parent 拉新版），其次 `bump_indirect`（直接 bump indirect entry，
>   Go MVS 會接受），`add_replace` 是 last resort。

##### B (JS) — JavaScript 決策樹

`dep_tree_js.js` 已經把所有可能的策略排好序輸出在 `upgrade_strategies[]`，
按 `recommended_strategy` 對應的分支執行：

**B/JS-1. `direct_bump`** — 不會走到 Type B（target 在 dependencies/devDeps/peerDeps，
直接走 Type A 流程）。出現在這裡只是 schema 完整性。

**B/JS-2. `bump_override`** — target 已被 `overrides` (npm) / `resolutions` (yarn) /
`pnpm.overrides` 釘版。把 override 值改成 target 新版本，跑 install 讓 lock 跟著走。
不去動 parent，因為使用者顯式表達過「鎖死 target 不管 parent 如何」。

報告並暫停確認：
```
{package} 在 package.json#{field} 已有釘版 (current: {value})。
建議直接更新該 override 為 {new_version} — 不需要動 parent。

繼續嗎?
[Y] 是, 升級 override 並進入 Phase 5
[N] 取消
```

**B/JS-3. `bump_parent`** — **預設推薦**。target 不在 package.json，但
`direct_parents` 含至少一個在 package.json 的直接依賴 P。升 P 而不是硬改 lock。

報告並暫停確認：
```
{package} 是 transitive，由以下 direct parent(s) 引入：

| Parent | 在 package.json 中的範圍 | parent 最新版本 | 升 parent 是否解決 |
|--------|-------------------------|----------------|-------------------|
| {direct_parent} | {constraint_in_root} | {latest} | ✅/❌ |
| ...    | ...                     | ...            | ... |

Parent chain: {target} ← ... ← {direct_parent}

建議策略: 升級 {direct_parent} 到 {latest}，由它自己拉新版的 {package}。
這比「直接動 lock」安全 — parent 對 target 的相容性已經由 parent 維護者驗證。

繼續嗎?
[Y] 是, 把 {direct_parent} 當成新目標跑 Phase 2~6
[O] 升其他 parent (顯示完整 candidate 列表)
[A] 改用 add_override (詳見 B/JS-4)
[N] 取消
```

**B/JS-4. `add_override`** — target 是 transitive 且 package.json 沒有任何約束，
但能走到一個 direct parent。提供「不動 parent，加 override」這條替代路徑。

```
無法保證升 {direct_parent} 一定會拉到 {package} 新版（parent 的範圍可能還是允許舊版）。
替代方案: 在 package.json 加入 overrides/resolutions 把 {package} 釘到新版。

對 npm:  "overrides":  {"{package}": "{new_version}"}
對 yarn: "resolutions":{"{package}": "{new_version}"}
對 pnpm: "pnpm": {"overrides": {"{package}": "{new_version}"}}

優點: 一定會生效；缺點: 繞過 parent 的相容性測試，需要在 Phase 6 跑足測試。

繼續嗎?
[Y] 是, 加 override
[N] 取消, 回到 B/JS-3 升 parent
```

**B/JS-5. `lock_only`** — **真正的 last resort**。只在以下都成立時才允許：
- target 不在 dependencies/devDeps/peerDeps
- target 不在 overrides/resolutions/pnpm.overrides
- 沒有任何 direct parent 能走到 target（孤兒 transitive）

這通常代表 lockfile 有手動撈進來的奇怪東西，或 workspace 結構特殊。
強烈警告使用者後再繼續：

```
⚠️ {package} 在 lockfile 中存在，但：
  - 沒在 package.json 任何 dependency 欄位
  - 沒在 overrides / resolutions 中
  - 走不到任何在 package.json 的 direct parent

唯一辦法是手動 patch lockfile。這代表升級後沒有 manifest-level 的審計軌跡，
未來 lockfile regenerate 時你的升級會被沖掉。

是否仍要繼續?
[Y] 是, 走 lock_only (我會跑 validate_lockfile.sh 確保 checksum 正確)
[N] 中止, 請手動加 override 後再跑一次 skill
```

session 中標記 `upgrade_strategy = <chosen strategy>`，Phase 5.3 走對應命令
（見 `references/javascript/yarn_workflow.md` / `references/javascript/npm_workflow.md`）。

##### B (Go) — Go modules 決策樹

`dep_tree_go.sh` 把所有可能策略以 **confidence 分數**排序輸出在 `upgrade_strategies[]`,
依 `recommended_strategy` (= 最高分者) 對應分支執行。

**關鍵新訊號** (IMPROVEMENT.md §4.1 / §4.2):
- `go_mod_why_status`: 從 `go mod why -m <target>` 解析,值為 `needed` /
  `not_needed_by_main_module` / `not_in_module_graph` / `unknown`。
  當值為 `not_needed_by_main_module` 時,target 不在 build path 上,
  `go mod tidy` 會把 `bump_indirect`/`bump_parent` 的結果**沖掉** —
  此時 `add_replace` 自動升權為推薦策略。
- `parent_analyses[]`: 對每個 direct parent 都下載過它 latest 版本的
  `.mod` 並解析。每個 entry 含 `status`:
  - `satisfies` — parent@latest 已 require target 到符合版本 → bump_parent 有效
  - `would_not_help_pin` — parent@latest 仍 pin 舊 target → bump_parent **無效**
  - `would_not_help_replace` — parent@latest 用 `replace` 改 target → bump_parent **無效**
    (replace directive 不繼承給 downstream consumer,見 `references/go/replace_semantics.md`)
  - `no_dep` — parent@latest 不再 require target
  - `unknown` — 無法 probe (網路 / 私有 module)
  策略卡片會把 `status` / `reason` 直接帶出來,**呈現給使用者時要原樣展示**
  (不要省略 reason — 它說明了為什麼某個 bump_parent 候選被降權)。

當 `add_replace` 因上述訊號升權成為推薦時,確認對話必須引用
`references/go/replace_semantics.md` 解釋原因,讓使用者知道這不是 last resort
而是當下唯一可行解。

**B/Go-1. `direct_bump`** — 不會走到 Type B（target 在 go.mod 且非 `// indirect`,
直接走 Type A 流程）。出現在這裡只是 schema 完整性。

**B/Go-2. `major_version_rewrite`** — target 新版本是 v2+ 且當前在不同 major.
這條 strategy 因為**侵入性高（要改 source 檔的 import path）**，永遠由 `dep_tree_go.sh`
排在最前面，即使其他 strategy 也適用。詳見 `references/go/major_version_paths.md`。

報告並暫停確認：
```
{package} 升到 {target_version} 是 major version 跳升 ({current} → {target}).
Go modules 要求 import path 從:
  {old_path}     → {new_path}

預估影響: {N} 個 .go 檔案會被改寫 (Phase 4 會列出精確位置).
推薦工具: gomajor get {new_path}@{target_version}  (自動改 imports + go.mod)
Fallback: 手動兩步 (go get + AST scanner 列出 import 位置 + 我來逐一改).

繼續嗎?
[Y] 是, 用 gomajor (若 preflight 偵測到已安裝)
[F] 是, 用手動 fallback
[N] 取消, 改升到當前 major 內最高版本 ({latest_in_current_major})
```

**B/Go-3. `bump_parent`** — 當 target 是 indirect 且至少一個 parent 的
`status == "satisfies"` 時的推薦路徑。升 parent 而不是強制動 indirect entry。

報告並暫停確認 (表格直接由 `parent_analyses[]` 渲染):
```
{package} 是 indirect dependency, 由以下 direct parent(s) 引入:

| Parent | go.mod 中的版本 | parent latest | parent 對 {package} 的處理 | 升 parent 是否解決 |
|--------|---------------|----------------|---------------------------|-------------------|
| {direct_parent} | {ver_in_gomod} | {latest} | requires @{pins_target_to} | ✅ satisfies |
| {direct_parent_2} | {ver_in_gomod} | {latest} | replace => {new}@{new_ver} | ❌ would_not_help_replace |
| {direct_parent_3} | {ver_in_gomod} | {latest} | requires @{pins_target_to} | ❌ would_not_help_pin |

(每一欄的 `reason` 直接從 dep_tree_go.sh 的 parent_analyses 帶出, 不要自己改寫)

Parent chain: {target} ← ... ← {direct_parent}

建議策略: 升級 {direct_parent} 到 {latest}, 讓它自己拉新版 {package}.

繼續嗎?
[Y] 是, 把 {direct_parent} 當新目標跑 Phase 2~6
[B] 改用 bump_indirect (直接動 indirect entry)
[R] 改用 add_replace (若所有 parent 都 would_not_help, 這通常是真正的解)
[N] 取消
```

若**所有 parent 都是 `would_not_help_*`** → 不要硬推 bump_parent;
直接告訴使用者並建議走 `add_replace`,引用 `references/go/replace_semantics.md`。

**B/Go-4. `bump_indirect`** — target 是 indirect，直接 bump indirect entry。
這是 Go 的「lock-only」等價物（雖然 `go.mod` 會改）。CVE patch 流程常用。

⚠️ **重要**: 當 `go_mod_why_status == "not_needed_by_main_module"` 時,
`go mod tidy` 會把這條 indirect entry **沖掉**,bump_indirect 等於白做。
此時 `dep_tree_go.sh` 已自動降權 bump_indirect 並升權 add_replace —
**不要硬推 bump_indirect**,改走 B/Go-5。詳見 `references/go/replace_semantics.md`。

```
若選擇 bump_indirect: go.mod 的 indirect entry 從:
  require {package} {old} // indirect
  → require {package} {new} // indirect

Go MVS 會接受這個更高版本。不影響 direct deps 的宣告.

⚠️ 警告 (若 dep_tree_go.sh 標 status: would_not_help):
  go mod why -m {package} 回傳 "not needed by main module" —
  下一次 `go mod tidy` 會刪掉這條 indirect entry,升級會被沖掉。
  此情境建議走 add_replace (B/Go-5)。

繼續嗎?
[Y] 是, bump indirect entry
[P] 改用 bump_parent (我會把 parent 當新目標)
[R] 改用 add_replace (推薦, 若上述警告出現)
[N] 取消
```

**B/Go-5. `add_replace`** — last resort，緊急 CVE patch / 上游不修 / 指向 fork 時用。

```
⚠️ 即將新增 replace directive 到 go.mod:
  replace {package} => {package} {new_version}

警告:
  1. replace 是 LOCAL 的 — 你的 module 被 downstream import 時, 他們不會繼承
     這個 replace, 需要自己加.
  2. {package} 之後上游發版本時, 要記得回來移除 replace.
  3. {若已有其他 replace} go.mod 中已有 {N} 個 replace directive, 升級不會動到它們.

繼續嗎?
[Y] 是, 加 replace
[N] 取消, 改用 bump_indirect / bump_parent
```

session 中標記 `upgrade_strategy = <chosen strategy>`，Phase 5.3 走對應命令
（見 `references/go/workflow.md` 的「升級命令 (Phase 5)」章節）。

##### B (Python) — Python lock-only 路徑（既有邏輯保留）

按以下順序判斷處理路徑,選定後在 Phase 5.3 對應執行:

**B-1. 檢查是否有 lock 檔案** (從 Phase 0 的 `lockfile_path` / `pip_lock_file`)

- ✅ 有 lock 檔案 → 進入 B-2
- ❌ 無 lock 檔案 → transitive 升級沒有意義 (重新解析時還是會回到舊版本),
  告知使用者並建議改為「升級直接依賴的 parent package」, 進入 B-4

**B-2. 檢查所有 parent 的版本約束是否允許目標版本**

對每個 parent package, 查 `version_constraints[parent]` 對此 transitive pkg 的約束:
- 用 web search / `pip index versions` / 解析 PyPI metadata 確認 parent 對此 pkg
  宣告的版本範圍 (如 `requests = ">=2.0,<3.0"`) 是否涵蓋 `target_version`

- ✅ 全部 parent 都允許 → 進入 B-3 (lock-only 升級)
- ❌ 至少一個 parent 鎖住版本不允許目標版本 → 進入 B-4 (詢問是否升級 parent)

**B-3. Lock-only 升級路徑** (Python only — parent 約束允許, 不動宣告檔)

報告給使用者並暫停確認:

```
{package} 是 transitive dependency, 由 {parent_list} 引用。
所有 parent 的版本約束都允許目標版本 {target_version}。

升級策略: 只更新 lock 檔案 ({lockfile_path}), 不動 pyproject.toml / requirements.txt。
這是最小擾動的方式, parent 不變、宣告不變, 只刷新被鎖定的解析結果。

繼續嗎?
[Y] 是, 進入 Phase 3 並在 Phase 5.3 走 lock-only 路徑
[N] 取消
```

使用者同意 → 在 session 中標記 `upgrade_strategy = "lock_only"`,
Phase 5.3 走對應的 lock-only 命令 (見 Phase 5.3 的「Transitive: lock-only 路徑」)。

**B-4. Parent 約束阻擋 → 詢問是否升級 parent** (Python only)

> 這是新增的關鍵分支: 不要自己決定升級 parent, 永遠先問。

對每個阻擋的 parent, 收集以下資訊:
- parent 目前版本
- parent 對 target pkg 的約束 (例: `<2.0`)
- parent 的最新版本 (web search / PyPI)
- parent 的最新版本對 target pkg 的約束是否放寬

報告並暫停:

```
無法直接升級 transitive package {package} 到 {target_version},
因為以下 parent package 鎖定了 {package} 的版本:

| Parent | 目前版本 | 對 {package} 的約束 | parent 最新版本 | 升級後是否允許 |
|--------|---------|-------------------|---------------|-------------|
| {parent_a} | {ver} | {constraint} | {latest} | ✅/❌ |
| ...     |       |                  |             |        |

請選擇:
[1] 升級 parent package(s) 以放寬約束 (我會把每個 parent 當成新的升級目標跑一次完整流程)
[2] 放棄升級 {package}, 結束此次任務
[3] 我來決定 (告訴我具體要升哪些 parent / 跳過哪些)

注意: 升級 parent 會修改宣告檔 (pyproject.toml / requirements.txt),
影響範圍比 lock-only 大, 請確認後再繼續。
```

根據使用者選擇:
- 選 [1] → 對每個阻擋的 parent 遞迴執行 Phase 2 (作為新的升級目標, dependency_type 通常是 direct)
- 選 [2] → 紀錄到報告中、結束流程
- 選 [3] → 等使用者列出 parent 清單, 對每個跑 Phase 2~6

#### Type C — 直接 + 間接引用

最複雜的情況。你需要:
1. 先做 Type A 的 python 相容性檢查
2. 再檢查所有 parent 的版本約束 (走 Type B 的 B-2 / B-4 邏輯)
3. 因為 pkg 本身是直接依賴, 必須更新宣告檔, lock-only 路徑不適用
4. 如果有 parent 約束衝突 → 走 Type B 的 B-4 詢問流程

### Step 2.3: 衝突解決 (如有衝突)

**這是你作為 LLM 的關鍵價值所在。** 不要只給出機械式的「升級 parent」建議。

你要綜合分析整個依賴圖，考慮以下策略並排序:

1. **同時升級** — 能否同時升級衝突的 parent packages？
2. **版本範圍** — 是否有中間版本同時滿足所有約束？
3. **約束寬鬆** — 衝突是否只是宣告性的？(實際 API 相容但 parent 的 requirements 寫太緊)
4. **替代套件** — 是否有 drop-in replacement 可以繞過衝突？
5. **分階段升級** — 先升到某個中間版本，再升到目標版本
6. **Override** — 使用 pip --force / poetry 的 dependency overrides

對每個方案給出:
- 具體操作步驟
- 風險評估
- 預估工作量

然後 **暫停，等使用者選擇方案** 再繼續。

---

## Phase 3: Breaking Change 分析

> **這是整個流程中你的 LLM 能力最重要的階段。**
> 你需要從多個維度分析後合併結果：
> - Python: Changelog + Git Diff（雙軌）
> - JavaScript: Changelog + Git Diff + `.d.ts` API Surface Diff（**三軌**）
> - Go: Changelog + Git Diff + `apidiff` API Surface Diff（**三軌**）

### Step 3.0: API Surface Diff（三條路徑都有，Python 較弱）

三條路徑都可跑 API surface diff 當作 Phase 3 的第三軌（除 changelog + git diff
外的額外結構性訊號）。三邊輸出 schema **完全對齊**：
都含 `confidence_score: float` + `confidence_basis: string` + `strategy` +
`removed` / `added` / `changed` / `deprecated_new` / `warnings` / `errors`。

#### 三語言 confidence baseline 對照（TODO task 1.3）

| 語言 | strategy | baseline | 為何此分數 |
|------|----------|----------|------------|
| Go | `apidiff` | **0.9** | apidiff 是 source-level 比較，含完整型別資訊（gold-standard） |
| JS / TS | `dts/dts` | 0.85 | 雙方都有 `.d.ts`，型別宣告級比對 |
| JS / TS | `mixed` (dts ↔ js) | 0.3 | 一邊有 type、一邊沒有，diff 雜訊高 |
| JS / TS | `js/js` | 0.4 | 純 runtime symbol 枚舉，缺 type 資訊 |
| Python | `griffe` | 0.65 | griffe 靜態枚舉；`__getattr__` / runtime-only export 可能漏 |
| 任一語言 | `none` | 0.0 | 工具未裝或無法枚舉 — 不採信本軌 |
| 任一語言 | errors 非空 | × 0.7 | 處理過程出錯，surface 可能不完整 |
| 任一語言 | warnings 非空 | × 0.9 | 部分 corner case 沒解析到 |

`confidence_basis` 是一段一句話文字描述，標明 baseline 是如何得來的；
報告中應原樣引用，方便 reviewer 判斷可信度。

Phase 3.3 合併三軌（changelog / git diff / API surface）時，
把各 `confidence_score` 當 baseline，再依交叉驗證調整最終結論。

**JS path**:

```bash
node scripts/javascript/api_surface_diff.js <package_name> <old_version> <new_version>
```

輸出 JSON 含 `removed` / `added` / `changed` / `deprecated_new`，以及
`strategy`（`dts` / `js` / `mixed` / `none`）與 `old_source_label` / `new_source_label`
標明資料來源。**`confidence_score` 欄位**（0.0~0.95）即此單一來源的 baseline 信心，
規則如下（與 Step 3.3 對齊）：

| 兩版策略 | baseline | 說明 |
|---|---|---|
| `dts/dts` | 0.85 | 雙方都有 .d.ts；API 宣告級別比對最可信 |
| `mixed`（dts ↔ js） | 0.3 | 一邊有 type、一邊沒有，diff 雜訊高 |
| `js/js` | 0.4 | 純 runtime symbol 枚舉，缺 type 資訊 |
| `none` either side | 0.0 | 無法枚舉 — 不應採信本軌 |

`errors[]` 非空再 × 0.7，`warnings[]` 非空再 × 0.9。Phase 3.3 合併其他軌時把
`confidence_score` 當 baseline，再依交叉驗證調整。詳細策略見
`references/javascript/ast_strategy.md`。

**Go path**:

```bash
bash scripts/go/api_surface_diff.sh <module_path> <old_version> <new_version>
```

輸出 JSON 含 `removed` / `added` / `changed` / `deprecated_new`，加上
`strategy`（`apidiff` 或 `none`）與 `old_source_label` / `new_source_label`。`changed`
條目含 `category`（`signature_change` / `kind_change` / `type_change` /
`incompatible_other`）。`deprecated_new` 來自 grep 兩個 cache 目錄的 `// Deprecated:` 註解差異。

`strategy == "none"` 表示 `apidiff` 沒裝或 module 下載失敗 — 走 Git Diff + Changelog
雙軌降級。詳細策略見 `references/go/workflow.md` 與 `references/go/breaking_change_patterns.md`。

**Python path**:

```bash
bash scripts/python/api_surface_diff.sh <package_name> <old_version> <new_version>
```

輸出 schema 與 JS / Go 對齊（`removed` / `added` / `changed` / `deprecated_new`
+ `strategy` + `confidence_score`）。`changed` 條目 `category` 為
`signature_change` / `kind_change` / `type_change` / `incompatible_other`。
`deprecated_new` 透過 `@deprecated` decorator 或 docstring `.. deprecated::`
標記偵測。

| 兩版策略 | baseline | 說明 |
|---|---|---|
| `griffe` | 0.65 | griffe 載入成功 — Python 動態本質導致精度上限低於 Go apidiff 的 0.9 |
| `none` | 0.0 | griffe 未安裝或 pip install 失敗 — 不採信本軌 |

`errors[]` 非空時降至 0.5。腳本以 `pip install --target` (或 `uv pip install`
fallback) 將兩版本裝到 temp dir，griffe 載入後 walk 全樹建立 `{path: signature}`
flat map 做集合差集。**前提條件**：`griffe` 套件已安裝（`pip install griffe`）。
未裝時降級走 Changelog + Git Diff 雙軌。

**在 session 中保留** `api_surface_diff = {package, old, new, strategy, confidence_score,
removed_count, changed_count, deprecated_new_count, source_old, source_new}`。Phase 7.1
報告必須新增一個小節「**🔧 API Surface Diff 來源**」引用這組數值（含 `confidence_score`）。

若 `strategy == "none"`，不要硬要報告「沒有 breaking change」，改告知使用者並依靠
Git Diff + Changelog 雙軌做判斷。

### Step 3.1: Changelog 分析

```bash
python scripts/common/fetch_changelog.py <package_name> <git_repo_url>
```

script 會嘗試以下來源並輸出原文:
- PyPI metadata 中的 changelog URL
- GitHub Releases API
- 常見路徑: CHANGELOG.md, CHANGES.rst, HISTORY.md

**先抓 metadata header**: stdout 開頭有兩行 HTML comment:

```
<!-- changelog_source_label: ... -->
<!-- changelog_source_url: ... -->
```

**在 session 中保留** `changelog_source = { label, url }` (若 `NOT_FOUND` → 記為 missing)。
這要在 Phase 7.1 報告中明確列出, 不可省略。

**你的分析任務:**

拿到 changelog 原文後，你要:

1. 定位從 `current_version` 到 `target_version` 之間的所有條目
2. 逐條分類:
   - 🔴 BREAKING — API 刪除、更名、行為變更、預設值變更
   - 🟡 DEPRECATED — 標記為棄用但仍可用
   - 🟢 FEATURE — 新增功能
   - ⚪ FIX — Bug 修復

3. **特別注意隱含 breaking change 的措辭** (讀 `references/common/breaking_change_patterns.md`):
   - "improved default behavior" → 預設行為變更
   - "now returns X instead of Y" → 回傳型別變更
   - "parameter X is now required" → 簽名變更
   - "moved from A to B" → 模組路徑變更

4. 對每個 BREAKING/DEPRECATED 條目，記錄:
   - 影響的模組路徑和符號
   - 舊用法 → 新用法
   - 你的信心分數 (0.0~1.0)

### Step 3.2: Git Diff 分析

**Python path**：
```bash
bash scripts/common/git_diff.sh <git_repo_url> <current_version> <target_version>
```

**JavaScript path**：
```bash
bash scripts/javascript/git_diff.sh <git_repo_url> <current_version> <target_version>
```

**Go path**：
```bash
bash scripts/go/git_diff.sh <git_repo_url> <current_version> <target_version> [--subdir <path>]
```

`--subdir` 用於 monorepo sub-module 標籤（例 `cmd/foo/v1.2.3`）。Go diff 過濾
`*.go`,排除 `*_test.go`、`vendor/`、`testdata/`、`examples/`、`*.pb.go`、generated files。

輸出: stdout 開頭的 metadata header + 兩個版本 tag 之間的 source diff（語言對應）

**先抓 metadata header**: stdout 前幾行是 HTML comment, 形如:

```
<!-- git_diff_repo_url: https://github.com/owner/repo -->
<!-- git_diff_old_version: 2.28.0 -->
<!-- git_diff_new_version: 2.32.0 -->
<!-- git_diff_old_tag: v2.28.0 -->
<!-- git_diff_new_tag: v2.32.0 -->
<!-- git_diff_old_sha: <40-char SHA> -->
<!-- git_diff_new_sha: <40-char SHA> -->
<!-- git_diff_compare_url: https://github.com/owner/repo/compare/v2.28.0...v2.32.0 -->
```

**在 session 中保留** `git_diff_source = { repo_url, old_version, new_version,
old_tag, new_tag, old_sha, new_sha, compare_url }`。Phase 7.1 報告必須引用這組數值
(尤其是 old_sha / new_sha 和 compare_url), 不可只寫版本號就帶過。

**你的分析任務:**

> 這是 AST 做不到、只有 LLM 能做的部分。

如果 diff 很大，分批閱讀 (每次一個檔案或一組相關檔案)。
聚焦在以下 public API 變更:

1. **被刪除的** public function / class / method
2. **函式簽名變更** — 參數增減、預設值改變、type hint 變更
3. **回傳值型別變更** — 例: list → generator (會影響 len/index 操作)
4. **行為邏輯變更** — 同一函式的輸出結果不同
5. **預設參數值變更** — 例: timeout 從 None 改為 30
6. **Exception 類型變更** — 例: ValueError 改為 TypeError
7. **`__all__` 清單變更** — 影響 `from pkg import *`
8. **新增 `warnings.warn` / `@deprecated`** — 標記即將棄用

判斷準則:
- `_` 開頭的是 private → 忽略
- 新增帶預設值的參數 → 通常不 breaking
- 刪除參數或改變順序 → breaking

### Step 3.3: 合併分析結果

將上述軌道的分析合併（Python 雙軌、JS / Go 三軌）：
- **去重**: 同一個變更可能多軌都提到
- **交叉驗證**: 多軌都提到 → 信心提高
  - JS：`.d.ts` ✅ + Git Diff ✅ + Changelog ✅ → 信心 ≥ 0.95
  - JS：只 `.d.ts` 標 `removed` → 信心 0.85（API 宣告刪除幾乎一定 breaking）
  - JS：只 Git Diff 有但 `.d.ts` 無 → 信心 0.5（可能是 internal 變更）
  - Go：`apidiff` Incompatible ✅ + Changelog ✅ → 信心 ≥ 0.95
  - Go：只 `apidiff` 標 `Incompatible: removed` → 信心 0.9（編譯期就會擋）
  - Go：只 Git Diff 看到但 `apidiff` 沒列 → 信心 0.5（可能是 unexported 變更）
- **補充**: 單軌發現但其他軌沒提 → 標記為「未記錄的 breaking change ⚠️」
- **按影響程度排序**: 刪除 > 簽名變更 > 行為變更 > 棄用

**JS 額外要對比**（從 npm registry metadata 取兩版的 manifest）：
- `package.json#type` 從 commonjs → module → 列為 🔴 ESM 切換 breaking
- `package.json#exports` 收緊（subpath 移除） → 🔴 deep import 失效
- `package.json#engines.node` 收緊 → 🔴 Node 最低版本變高
- `package.json#peerDependencies` range 收緊 → 🔴 升級前需先升 peer

**Go 額外要對比**（從兩版的 `go.mod` 與 source 抽取）：
- `go.mod#go` directive 提升 → 🟡 升級後本專案 `go` 最低版本要跟著升（不一定 block，要警告）
- `package` 從 exported 移到 `internal/` → 🔴 無 workaround
- interface 新增 method → 🔴 user implementer 編譯失敗
- function 新增 `context.Context` 第一參數 → 🔴 所有 call site 要改
- error 改用 `errors.Is`/`%w` wrap → 🟡 `==` 比對失效（隱藏 breaking，僅靠 changelog）
- 詳見 `references/go/breaking_change_patterns.md`

產出最終的 breaking changes 清單，格式:

```
## Breaking Changes 清單

### 🔴 BC-001: `module.func_name` 已被移除
- 來源: Changelog ✅ + Git Diff ✅
- 信心: 0.98
- 舊用法: `from pkg.module import func_name`
- 新用法: `from pkg.module import new_func_name`
- 遷移說明: ...

### 🟡 BC-002: `module.old_api` 標記為棄用
- 來源: Git Diff ✅ (Changelog 未記錄 ⚠️)
- 信心: 0.75
- 說明: 新增了 DeprecationWarning，建議改用 new_api
```

---

## Phase 4: 專案程式碼影響分析

### Step 4.0: Zero-impact 短路（IMPROVEMENTS #11）

**三語言統一規則**：先跑 Step 4.1 的 AST scanner，再依 `verdict` 欄位短路。

三語言 scanner 輸出的頂層 JSON 都帶這兩個欄位（schema 對齊 `ast_scanner_go.go`）：

| `verdict` | 意義 | 對應動作 |
|-----------|------|----------|
| `zero_impact` | 走訪所有來源檔案，0 個 import / 0 個 usage，且 0 個解析失敗 | **跳過 Phase 3 / Phase 4 其他步驟，直接到 Phase 5** |
| `has_impact` | 至少 1 個 import 或 usage | 正常進行 Phase 4.2 / 4.3 |
| `scan_errored` | 0 命中但有檔案解析失敗（語法錯誤、編碼問題） | **不可短路**；回報 `warnings`，請使用者人工確認 |

短路的前置條件（沒變）：
- Phase 2 判定 `dependency_type == "transitive"`
- 所有 manifest（`pyproject.toml` / `package.json` / `go.mod`，含 workspace）對該 package 都是零命中

兩個條件同時成立才短路。`verdict` 已涵蓋舊版「`grep -r` 零命中」的判斷，
但避免錯把 `scan_errored` 當成「沒命中」（語法錯誤的檔案 grep 也是零命中，
但 AST 沒看過內容）。

這代表：升級的是純 build-time / transitive 套件，專案完全沒有直接使用，沒有
任何 breaking change 影響面，跑完整 Phase 3 / 4.2+ 純粹浪費時間
（IMPROVEMENTS session 實際遇到的情況）。

報告中要寫一節「## Skipped Phases」記錄跳過原因：

```markdown
## Skipped Phases
- Phase 3 (Breaking Change Analysis): skipped — {pkg} is purely transitive,
  not declared in any package.json, and zero source-code references found.
- Phase 4 (Code Impact Analysis): skipped — same reason.
- Upgrade reduces to: refresh lockfile entry only.
```

### Step 4.1: AST 掃描

**Python path**:
```bash
python scripts/python/ast_scanner.py <project_path> <package_name>
```

**JavaScript path**:
```bash
node scripts/javascript/ast_scanner.js <project_path> <package_name>
```

**Go path**:
```bash
go run scripts/go/ast_scanner.go <project_path> <module_path>
```

三個 script 的輸出 schema 對齊，包含每個來源檔案中:
- import / require 該 package 的位置與形式
- 使用的 symbol (含完整 chain, 如 `axios.default.get` / `github.com/foo/bar.NewClient`)
- 行號 + 周圍 ±5 行的程式碼上下文

JS 版會額外標 `imports[].type` 為 `esm_default` / `esm_named` / `esm_namespace` /
`esm_type_only` / `esm_side_effect` / `cjs_default` / `cjs_destructure` / `dynamic` /
`cjs_resolve`，**`esm_type_only` 的影響只在編譯期**（不算 runtime breaking)，
Phase 4.3 生成修改建議時要區別處理。

Go 版 `imports[].type` 為 `named` / `alias` / `dot_import` / `blank_import` /
`submodule_import`。其中:
- `blank_import` (`import _ "pkg"`) 不會產生 usage symbol — 純 side-effect
- `dot_import` (`import . "pkg"`) 會在 `warnings[]` 標記，因為無法精準解析未限定識別子
- `submodule_import` (`import "pkg/sub"`) 與主 path 在 Phase 3 應該分開判斷影響面
- 升 major version 時，舊 `import "pkg"` 與新 `import "pkg/v2"` symbol 命名規則
  保留 `/v2` 後綴，方便 Phase 3 比對 `apidiff` 輸出

### Step 4.2: 交叉比對

將 AST 掃描結果與 Phase 3 的 breaking changes 清單交叉比對，
找出專案中實際受影響的程式碼位置。

### Step 4.3: 生成修改建議

**這是你作為 LLM 的核心價值 — 不只標記問題，還要提供解法。**

對每個受影響的程式碼位置:

1. 閱讀周圍上下文 (至少前後 10 行)
2. 理解這段程式碼的業務邏輯意圖
3. 結合 breaking change 的遷移說明
4. 生成具體的修改程式碼 (不是泛泛的建議)
5. 確保:
   - 保持原有的程式碼風格 (縮排、引號、命名)
   - 新的 import 路徑正確
   - 如有多種修改方式，選最簡潔且向後相容的
   - 不修改與 breaking change 無關的程式碼

6. 以 unified diff 格式展示每處修改

### Step 4.4: 預覽確認

將所有待修改的檔案和 diff 展示給使用者，**暫停等待確認** 再繼續。

列出:
- 總共影響 N 個檔案、M 處修改
- 每個檔案的修改摘要
- 完整的 diff 預覽

---

## Phase 5: 執行升級

### Step 5.1: 建立 Git 分支

**在修改任何專案內容之前，必須先建立新的 feature 分支。**

分支命名取決於觸發類型 — **若有 `jira_context`,issue key 一律放在最前面**,
讓 git 端 (branch list / PR list / `git log --all`) 可以直接掃到 Jira ticket。

#### 一般升級 (沒有 Jira / 沒有 CVE)

```bash
git checkout -b feature/Update-{PackageName}-to-{TargetVersion}
```

範例:
```bash
git checkout -b feature/Update-requests-to-2.32.0
git checkout -b feature/Update-django-to-5.1
```

#### CVE 修復 (沒有 Jira)

```bash
git checkout -b fix/CVE-{CVE-ID}-{PackageName}
# 範例: git checkout -b fix/CVE-2024-35195-cryptography
```

#### Jira 觸發 (Phase 1 情況 C)

```bash
# 一般升級
git checkout -b feature/{ISSUE_KEY}-Update-{PackageName}-to-{TargetVersion}

# CVE 修復 + Jira (兩者都有時, Jira 優先放最前面)
git checkout -b fix/{ISSUE_KEY}-CVE-{CVE-ID}-{PackageName}
```

範例:
```bash
git checkout -b feature/V1E-148968-Update-requests-to-2.32.0
git checkout -b fix/V1E-148968-CVE-2024-35195-cryptography
```

**為什麼 Jira ID 放最前面**:
- `git branch --list 'feature/V1E-*'` 可以一次列出某個 epic / project 的所有分支
- PR 列表頁排序後同一 ticket 的相關 branch 會聚在一起
- 配合 Phase 7.2 commit 的 `[<issue_key>]` 前綴、Phase 7.3 PR title 的 `[<issue_key>]` 前綴,
  branch / commit / PR 三層都能一眼追到 Jira ticket

**字元限制**: 分支名只用 `[A-Za-z0-9._-]`,不要放空白或中文。
若 `{PackageName}` 含特殊字元 (例 `python-dateutil`),保留原 `-` 即可。

### Step 5.2: 環境備份

**Python path**:
```bash
bash scripts/python/snapshot_env.sh <project_path> save
```

**JavaScript path** (僅備份 `package.json` + lockfile，**不備份 `node_modules`**)：
```bash
bash scripts/javascript/snapshot_env.sh <project_path> save
```

**Go path** (備份 `go.mod` / `go.sum` / `go.work*` / `vendor/modules.txt`，**不備份 vendor/ 內容**)：
```bash
bash scripts/go/snapshot_env.sh <project_path> save
```

### Step 5.3: 更新依賴宣告檔

**先決定走哪條路徑** (來自 Phase 2.2):

**Python path** (簡化 2 分支):
- `upgrade_strategy == "lock_only"` (Type B, parent 約束允許)
  → 走「Transitive: lock-only 路徑」, **不要動 pyproject.toml / requirements.txt**
- 其他 (Type A 直接、Type C 直接+間接、Type B 升 parent)
  → 走「Direct: 同時更新宣告檔 + lock」

**JavaScript path** (5 分支對應 `upgrade_strategy`):

| `upgrade_strategy` | 走哪條 | 指令樣板 (npm / yarn / pnpm) |
|---|---|---|
| `direct_bump` | 「Direct: 同時更新宣告檔 + lock」 | `npm install <pkg>@<ver>` / `$PKG_MANAGER_BIN up <pkg>@<ver>` / `$PKG_MANAGER_BIN add <pkg>@<ver>` |
| `bump_override` | 編輯 `package.json#overrides`/`resolutions`/`pnpm.overrides` 後重 install | `npm install --package-lock-only` / `$PKG_MANAGER_BIN install --mode update-lockfile` / `$PKG_MANAGER_BIN install --lockfile-only` |
| `bump_parent` | 把 direct parent 當新目標跑 direct_bump | `npm install <parent>@<latest>` / `$PKG_MANAGER_BIN up <parent>` / `$PKG_MANAGER_BIN add <parent>@<latest>` |
| `add_override` | 編輯 `package.json` 新增 `overrides`/`resolutions`/`pnpm.overrides` 後重 install | 同 `bump_override` |
| `lock_only` | 「Transitive: lock-only 路徑」(yarn 用 `set resolution`，npm/pnpm 用 `update`) | `$PKG_MANAGER_BIN set resolution ...` / `npm update <pkg>` / `$PKG_MANAGER_BIN update <pkg>` |

詳細命令見 `references/javascript/yarn_workflow.md` / `references/javascript/npm_workflow.md` / `references/javascript/pnpm_workflow.md` 的「Transitive 升級策略」章節。

**Go path** (5 分支對應 `upgrade_strategy`):

| `upgrade_strategy` | 動作 | 指令樣板 |
|---|---|---|
| `direct_bump` | `go get` + `go mod tidy` | `go get <module>@<ver> && go mod tidy` |
| `major_version_rewrite` | 改 import path + bump go.mod | `gomajor get <module>/v2@<ver>` (or manual two-step, see below) |
| `bump_parent` | 升 direct parent，讓它拉新版 target | `go get <parent>@<ver-or-latest> && go mod tidy` |
| `bump_indirect` | 直接 bump indirect entry | `go get <module>@<ver> && go mod tidy` |
| `add_replace` | 編輯 `go.mod` 加 `replace` directive | 編輯後 `go mod tidy` |

升完後 **若 `is_vendored == true`** 一定要追加 `go mod vendor` 重建 vendor/。

詳細命令與每條 strategy 的執行步驟見 `references/go/workflow.md` 的「升級命令 (Phase 5)」。
major version path rewrite 詳見 `references/go/major_version_paths.md`。

---

#### Transitive: lock-only 路徑

> 目標: 只刷新 lock 檔案中該 transitive pkg 的版本, 不動依賴宣告檔。
> 這條路徑只在 parent 的版本約束已經允許目標版本時才走。

**For poetry**:
```bash
# 只更新 lock, pyproject.toml 不變
poetry update <package>
# 或更精準: 只重新解析這一個 pkg
# poetry update --lock <package>   # 視 poetry 版本而定
```

**For uv (專案模式)**:
```bash
# 只升級 lock 中的特定 pkg, pyproject.toml 不動
uv lock --upgrade-package <package>
# 同步到環境 (不會修改 pyproject.toml)
uv sync
```

**For pip (有 lock 檔案)**:

依 lock 檔案類型:
- pip-tools: `pip-compile --upgrade-package <package> requirements.in`
  (注意: 不要編輯 requirements.in, 只升級指定 transitive pkg)
- 自定義 lock (如 requirements.lock): 需要詢問使用者如何重新產生 lock,
  常見方式 `pip install --upgrade <package>==<target_version> && pip freeze > <lock_file>`

**驗證 lock-only 結果**:
- ✅ 確認依賴宣告檔 (`pyproject.toml` / `requirements.txt` / `requirements.in`)
  在 `git diff` 中**沒有變化**
- ✅ 確認 lock 檔案中該 pkg 版本已更新到 target
- 若宣告檔也被改到 → 還原宣告檔的變更 (`git checkout -- <file>`),
  保留 lock 變更

---

#### Direct: 同時更新宣告檔 + lock

**重要**: 必須同時更新依賴宣告檔和鎖定檔案,不能只更新鎖定檔案!

根據 pkg_manager 執行對應的更新命令:

#### For pip:

**檢查是否有 lock 檔案** (從 Phase 0 的 `pip_lock_file` 欄位):

**情況 A: 使用 pip-tools (有 requirements.in)**

```bash
# 1. 手動編輯 requirements.in
# 例: requests==2.28.0 → requests==2.32.0

# 2. 重新編譯產生 requirements.txt (lock 檔案)
pip-compile requirements.in --output-file requirements.txt

# 或只升級特定套件
pip-compile --upgrade-package requests requirements.in

# 3. 安裝
pip-sync requirements.txt
```

**如果沒有 pip-compile 命令**:
```bash
pip install pip-tools
```

**情況 B: 有自定義 lock 檔案 (如 requirements.lock)**

**暫停並詢問使用者**:
```
偵測到專案使用 lock 檔案: {pip_lock_file}

請確認更新流程:
1. 更新 requirements.txt 中的版本約束
2. 重新產生 {pip_lock_file}

產生 lock 檔案的方式:
a) 使用 pip freeze: pip install -r requirements.txt && pip freeze > {pip_lock_file}
b) 使用專案自定義腳本 (如 make lock)
c) 手動管理

請選擇:
[1] 自動執行方式 a (pip freeze)
[2] 告訴我使用哪個腳本
[3] 我會手動處理,繼續下一步
```

根據使用者選擇執行對應操作。

**情況 C: 無 lock 檔案 (只有 requirements.txt)**

```bash
# 1. 手動編輯 requirements.txt
# 例: requests==2.28.0 → requests==2.32.0

# 2. 安裝新版本
pip install --upgrade <package>==<version>

# 或從檔案安裝
pip install -r requirements.txt
```

#### For poetry:

```bash
# 使用 poetry add 自動更新 pyproject.toml 和 poetry.lock
poetry add <package>@<version>

# 範例
poetry add requests@2.32.0
```

**`poetry add` 會自動**:
1. ✅ 更新 `pyproject.toml` 中的版本約束
2. ✅ 更新 `poetry.lock`
3. ✅ 安裝新版本

**不要只執行 `poetry lock` 或 `poetry update`**,這些命令不會修改 `pyproject.toml`!

#### For uv (專案模式):

```bash
# 使用 uv add 自動更新 pyproject.toml 和 uv.lock
uv add "<package>>=<version>"

# 範例
uv add "requests>=2.32.0"
# 或精確版本
uv add "requests==2.32.0"
```

**`uv add` 會自動**:
1. ✅ 更新 `pyproject.toml` 的 dependencies 列表
2. ✅ 更新 `uv.lock`
3. ✅ 安裝新版本

**不要只執行 `uv lock --upgrade-package`**,這只會更新鎖定檔案,不會更新 `pyproject.toml`!

#### For uv (傳統 pip 模式):

```bash
# 1. 手動編輯 requirements.txt
# 例: requests==2.28.0 → requests==2.32.0

# 2. 安裝新版本
uv pip install -r requirements.txt
```

#### For npm (JavaScript path):

```bash
# 直接依賴 (dependencies)
npm install <package>@<version> --save --ignore-scripts

# Dev 依賴 (devDependencies)
npm install <package>@<version> --save-dev --ignore-scripts

# Peer 依賴 (npm >= 7)
npm install <package>@<version> --save-peer --ignore-scripts

# Transitive lock-only (Phase 2 走 B-3 時)
npm update <package> --ignore-scripts
```

#### For yarn (JavaScript path, 含 yarn 3 Berry):

> **重要**: 用 Phase 0 偵測到的 `pkg_manager_bin` (例 `node .yarn/releases/yarn-3.8.2.cjs`)。
> 不要 hardcode `yarn` — corepack 管理的 yarn 不在 PATH（IMPROVEMENTS #3）。

```bash
# 直接依賴
$PKG_MANAGER_BIN up <package>@<range>

# 範例 (yarn 3)
node .yarn/releases/yarn-3.8.2.cjs up axios@^1.6.0
```

⚠️ **`yarn up -R <pkg>` 不能接 range** (踩過坑 — yarn 會拒：`Ranges aren't allowed when using --recursive`)。要 recursive 必須分兩步：

```bash
$PKG_MANAGER_BIN up <pkg>@<range>
$PKG_MANAGER_BIN dedupe
```

**Transitive override（更乾淨的 lock-only 做法）**:

```bash
$PKG_MANAGER_BIN set resolution "<pkg>@npm:<old-range>" "npm:<exact-version>"
$PKG_MANAGER_BIN install --mode update-lockfile
```

對應 manifest 寫法：在 `package.json` 加 `"resolutions": { "<pkg>": "<version>" }`。

**若 preflight 偵測到缺 auth token（IMPROVEMENTS #1）**：詢問使用者選擇：
- 提供 token → `export <ENV_VAR>=<value>`，續走完整 `yarn up`
- 跳過 → 走「手動編輯 yarn.lock + Phase 5.4 validate_lockfile.sh」fallback；Phase 7 報告中註明「Auth fallback: lockfile-only」

詳見 `references/javascript/yarn_workflow.md` 與 `references/common/auth_tokens.md`。

#### For pnpm (JavaScript path):

> **重要**: 用 Phase 0 偵測到的 `pkg_manager_bin`。pnpm 9+ 透過 corepack 管理時，
> 仍會被 detect_env_js.sh 解析出實際路徑 — 不要 hardcode `pnpm`。

```bash
# 直接依賴 (dependencies)
$PKG_MANAGER_BIN add <package>@<version>

# Dev 依賴 (devDependencies)
$PKG_MANAGER_BIN add -D <package>@<version>

# Peer 依賴
$PKG_MANAGER_BIN add --save-peer <package>@<version>

# Workspace 內升級 (filter 用 workspace name 或 glob)
$PKG_MANAGER_BIN --filter <workspace-name> add <package>@<version>

# Transitive override：先編輯 package.json 加 pnpm.overrides，再：
$PKG_MANAGER_BIN install --lockfile-only

# Transitive lock-only (Phase 2 走 B-3 時)
$PKG_MANAGER_BIN update <package>
```

`pnpm add` 與 `npm install --save` 行為對應 — 會同時寫回 `package.json` 與
`pnpm-lock.yaml`。pnpm 預設**會**跑 lifecycle scripts；若要跳過明確加
`--ignore-scripts`，事後再 `pnpm rebuild <pkg>` 補。

詳見 `references/javascript/pnpm_workflow.md`。

**`npm install` 會自動**:
1. ✅ 更新 `package.json` 中的版本範圍 (預設用 `^<version>` caret range)
2. ✅ 更新 `package-lock.json`
3. ✅ 下載並安裝到 `node_modules`

**為何預設加 `--ignore-scripts`**: npm 套件可以定義 `preinstall` / `install` /
`postinstall` 等 lifecycle script — 這些 script 會在 install 時執行任意程式碼。
升級流程不該觸發未審核的 lifecycle script。

⚠️ 若升級的套件**需要 postinstall 才能正常運作** (常見如 `esbuild`、`sharp`、
`puppeteer`、`node-gyp` 相關套件)，升級後手動跑：

```bash
npm rebuild <package>
```

並在 Phase 6 測試時特別注意是否因為缺少 native binary 而失敗。

**`@types/<pkg>` 同步升級** (TypeScript 專案)：

不要自己 grep — Phase 2 的 `dep_tree_js.js` 已輸出 `types_sibling`，直接讀：

- `types_sibling.applicable == false` → target 本身就是 `@types/...`，跳過此小節
- `types_sibling.present == true` → 升級主套件後**必須**同步升 `types_sibling.sibling_name`
- `types_sibling.present == false` → 不必處理（runtime 套件自帶 .d.ts 或專案是純 JS）

升級命令（依 Phase 2 偵測到的 `pkg_manager`）：

```bash
# npm
npm install <sibling_name>@<matching-version> --save-dev --ignore-scripts
# yarn 3
$PKG_MANAGER_BIN up <sibling_name>@<matching-version> --dev
# pnpm
pnpm add -D <sibling_name>@<matching-version>
```

並把 `types_sibling.sibling_name` 列入 Phase 7 報告的「相關套件」小節。
版本對應策略：先試與 runtime 同 major，若 DefinitelyTyped 未發 latest 則退一個 patch。

#### For Go (Go modules):

依 Phase 2 確定的 `upgrade_strategy` 走對應分支：

**direct_bump**:
```bash
go get <module>@<version>
go mod tidy
```

**major_version_rewrite** (gomajor available):
```bash
gomajor get <module>/v<N>@<version>
go mod tidy
```

**major_version_rewrite** (manual fallback):
```bash
# Step 1: pull new module
go get <module>/v<N>@<version>

# Step 2: rewrite all `import "<old-path>"` → `import "<new-path>"`
# 用 Phase 4 ast_scanner_go.go 的輸出列出每處 import,逐一用 Edit tool 改寫.
# (永遠不要用 sed 盲改 — string literal 可能誤傷)

# Step 3: 清理舊 entry
go mod tidy
```

**bump_parent**:
```bash
go get <parent-module>@<version-or-latest>
go mod tidy
# 然後驗證 target 真的被 bump 到了
go list -m <target-module>
```

**bump_indirect**:
```bash
go get <module>@<version>
go mod tidy
# go.mod 中該 module 的 `// indirect` 註解會保留
```

**add_replace** (last resort，需使用者確認):
用 Edit tool 加入 `replace` directive,然後：
```bash
go mod tidy
```

**通用後續步驟**:
```bash
# 若 vendored — 一定要重建 vendor/
[ -f vendor/modules.txt ] && go mod vendor

# 驗證 go.sum 一致性
go mod verify
```

**`go.mod` 不會自動執行任何 install script** — Go 與 npm 不同,沒有 lifecycle scripts
的隱憂。不需要 `--ignore-scripts` 對應動作。

**驗證更新**:

更新後,檢查以下檔案確認版本已正確更新:

- pip: `requirements.txt` 或 `pyproject.toml`
- poetry: `pyproject.toml` (檢查 `[tool.poetry.dependencies]`) 和 `poetry.lock`
- uv: `pyproject.toml` (檢查 `dependencies` 列表) 和 `uv.lock`
- npm: `package.json` (檢查 `dependencies` / `devDependencies` / `peerDependencies`) 和 `package-lock.json`

### Step 5.4: Post-edit 離線驗證（三條路徑都應跑）

**Python path** — Phase 5.3 結束後**一律跑**：

```bash
bash scripts/python/validate_lockfile.sh <project_path> [--upgrade-strategy <name>]
```

依偵測到的 pkg_manager 跑對應的 lock 一致性檢查：
- uv:        `uv lock --check`
- poetry:    `poetry check --lock` (1.7+) 或 `poetry lock --check` (1.4-1.6)
- pip-tools: `pip-compile --dry-run -o <tmp> requirements.in` 並 diff `requirements.txt`
- pip (raw): `pip install --dry-run -r requirements.txt`（pip 23+）或 `pip check`

當 Phase 2 的 `recommended_strategy == "lock_only"` 時，**必須**同時傳 `--upgrade-strategy
lock_only`，腳本會額外 `git diff` 檢查 `pyproject.toml` / `requirements.in` 是否
誤動 — lock-only 路徑不可動 manifest（見 `references/common/important_dependency_update.md`）。

**JS path** — 只要走過「手動編輯 lockfile」這條 fallback 路徑（preflight 缺 auth token、
或 Phase 2 走 yarn `set resolution` 後手動補 lockfile），完工後**必跑**：

```bash
bash scripts/javascript/validate_lockfile.sh <project_path>
```

腳本會選對應的 offline 驗證命令：
- yarn 3: `<bin> install --immutable --check-cache --mode update-lockfile`
- yarn 1: `yarn install --frozen-lockfile --check-files`
- npm:    `npm ci --offline --dry-run`
- pnpm:   `pnpm install --frozen-lockfile --offline`

**Go path** — Phase 5.3 結束後**一律跑**（不限於走 fallback 路徑）：

```bash
bash scripts/go/validate_modfile.sh <project_path>
```

腳本順序執行：
1. `go mod verify` — 確認 `go.sum` 與 module cache 一致
2. `go vet ./...` — 快速 syntax / declared-but-unused 檢查
3. `go mod tidy -diff` (Go 1.21+) 或 fallback diff — 若 `go mod tidy` 還會改 `go.mod`,
   代表 Phase 5.3 漏跑了 tidy 或 indirect entries 不一致

純本地操作，不需要 network。若任一步失敗 → **不要 commit**，回 Phase 5.3 排查。

驗證失敗常見原因：
- `go mod verify` 失敗 → 通常是手動編 `go.sum` 出錯 → 跑 `rm go.sum && go mod download` 重建
- `go vet` 失敗 → AST scanner 漏掉某些 call site → 回 Phase 4 補修
- `go mod tidy -diff` 失敗 → 跑 `go mod tidy` 補上差異後重試

### Step 5.5: 套用程式碼修改

使用 file editing 工具 (str_replace) 逐一套用 Phase 4 確認的修改。
(若 Phase 4.0 短路 zero-impact，此步省略。)

---

## Phase 6: 測試驗證

### Step 6.1: 識別相關測試

**Python**:
- 根據 affected_files 推斷對應的 test 檔案: `src/foo/bar.py` → `tests/test_bar.py` 或 `tests/foo/test_bar.py`
- 也檢查 `conftest.py` 中對該 package 的 fixture

**JavaScript**:
- `src/foo/bar.ts` → `src/foo/bar.test.ts` / `src/foo/bar.spec.ts` / `__tests__/bar.test.ts` / `tests/bar.test.ts`
- 看 jest / vitest config 中的 `testMatch` / `testRegex` 確認規則

**Go**:
- Go 是 **package-level** 測試，不是 file-level — 每個 `*_test.go` 必須跟 source 在同 package
- 受影響的 .go 檔案 → 推導所在 package → 該 package 內所有 `*_test.go` 都會被跑
- 例如 `service/auth/handler.go` 變動 → 跑 `go test ./service/auth/...` 自動涵蓋
  `service/auth/handler_test.go`、`service/auth/auth_test.go` 等
- External test packages (`package foo_test` in `foo_test.go`) 也會跑到 — 它們是黑盒測試

### Step 6.2: 分層執行測試

**Python path**:
```bash
# 第一輪: 只跑受影響的測試
bash scripts/python/run_tests.sh <project_path> --files <test_files>

# 第二輪 (若第一輪通過): 跑完整測試
bash scripts/python/run_tests.sh <project_path> --all
```

**JavaScript path**:
```bash
# 第一輪: 只跑受影響的測試 (jest --findRelatedTests / vitest related)
bash scripts/javascript/run_tests.sh <project_path> --files <source_files>

# 第二輪
bash scripts/javascript/run_tests.sh <project_path> --all
```

**Go path**:
```bash
# 第一輪: 只跑受影響 package（mapping 來自 ast_scanner_go 結果 → containing dir）
bash scripts/go/run_tests.sh <project_path> --files <source_files>

# 第二輪
bash scripts/go/run_tests.sh <project_path> --all

# CVE 升級建議加 -race
bash scripts/go/run_tests.sh <project_path> --all --race
```

**升完後若有 `govulncheck`**: 再跑一次 `bash scripts/go/govulncheck.sh <path> --cve <ID>
--post-upgrade`，期望 `match: "not_present"`。仍出現代表升級沒生效，回 Phase 5 排查。

### Step 6.3: 測試失敗診斷

> **這是你作為 LLM 第二重要的分析任務。**

如果有測試失敗，你需要做 **三向交叉分析**:

1. 閱讀完整的 traceback (pytest / jest / vitest / mocha 各自格式不同但邏輯相同)
2. 閱讀失敗測試的原始碼
3. 閱讀被測試的業務程式碼 (source code)
4. 參照本次升級的 breaking changes 清單

然後對每個失敗的測試判斷:

**根因分類:**
- `SOURCE_CODE` — 業務程式碼還需要修改 (Phase 4 漏掉的)
- `TEST_CODE` — 測試程式碼需要修改 (測試了已變更的行為)
- `BOTH` — 兩者都需要修改
- `CONFIG` — 配置問題 (fixture、conftest、mock 設定)

**判斷準則** (Python):
- ImportError / ModuleNotFoundError → 通常是 SOURCE_CODE
- AssertionError 且 assert 值反映行為變更 → TEST_CODE
- TypeError (參數不匹配) → 看是業務碼還是測試碼直接呼叫
- 測試 mock 了被變更的 API → TEST_CODE
- 測試直接呼叫了被刪除的 API → TEST_CODE

**判斷準則** (JavaScript / TypeScript):
- `Cannot find module 'X'` / `MODULE_NOT_FOUND` → SOURCE_CODE，可能是 deep import 路徑變了
- `ERR_REQUIRE_ESM` → CONFIG，套件改成 ESM-only，需要全專案升級 ESM 或用 dynamic import
- TS 編譯失敗 (`TS2304` / `TS2345` / ...) → SOURCE_CODE 但屬於型別層 (runtime 可能不爆)
- `TypeError: X is not a function` → 通常 SOURCE_CODE，export shape 變了
- Jest `expect(...).toMatchSnapshot()` 失敗 → TEST_CODE，先確認新 snapshot 是正確的行為
- `jest.mock('X')` 後 mock 結構不符 → TEST_CODE
- React `act()` warning 變多 → CONFIG，可能 react 升 18 後測試 setup 要改

**判斷準則** (Go):
- `cannot find package "X"` → SOURCE_CODE，major version path 沒改完 (Phase 5.3 漏掉)
- `undefined: pkg.Foo` → SOURCE_CODE，套件刪除了該 symbol (apidiff 應已偵測)
- `cannot use X (type T1) as type T2` → SOURCE_CODE，參數型別變更，看 apidiff signature_change
- `not enough arguments in call to ...` → SOURCE_CODE，常見於套件加了 `context.Context` 首參
- `does not implement <Interface>` → SOURCE_CODE，interface 加了 method (apidiff 應有報)
- `imported and not used` → SOURCE_CODE，AST scanner 改完 import 但留下未用的 → 刪掉
- 測試斷言 `==` 失敗但邏輯沒錯 → TEST_CODE，可能套件改用 `errors.Is`/wrapped errors
- `data race detected` (`-race` 開啟時) → 升級套件可能改變 goroutine 用法 → 看 changelog
- `inconsistent vendoring` → CONFIG，沒跑 `go mod vendor`

### Step 6.4: 處理測試失敗

#### 如果是 SOURCE_CODE 問題:
- 生成額外的程式碼修改
- 套用修改
- 重新跑測試

#### 如果是 TEST_CODE 問題:
- **必須暫停，等使用者確認**
- 向使用者解釋:
  - 為什麼這個測試需要改 (不是 bug，而是上游行為的預期變更)
  - 具體要怎麼改
  - 改後的測試仍然在驗證什麼
- 使用者確認後才修改測試
- 修改後重新跑測試

### Step 6.5: 迴圈

重複 6.2 ~ 6.4 直到所有測試通過 (或使用者決定停止)。

最大迴圈次數: 3 次。超過 3 次仍有失敗 → 停下來，把所有資訊報告給使用者。

### Step 6.6: (JS only) Runtime Verification Post-Upgrade

**僅當 Step 0.5 抓了 baseline (`.package-upgrade-cache/runtime-baseline.json` 存在) 時跑**。
否則直接進 Phase 7。

**重跑 verify**：用跟 baseline **完全相同的** start cmd / url / timeout / playwright flag：

```bash
node scripts/javascript/runtime_verify.js <project_path> \
    --mode verify \
    --start-cmd "<同 baseline>" \
    --url "<同 baseline>" \
    --timeout 60 \
    [--playwright]
```

寫到 `<project>/.package-upgrade-cache/runtime-post.json`。

**Diff 兩份 JSON** — 細節見 `references/javascript/runtime_verification.md` 的「Diff 策略」
章節 (Bucket 1-6)。重點：

- **不要** raw text diff；按欄位類別比對
- 「新出現的 error 類型」直接歸因為本次升級
- `boot_status` 退化矩陣 (ready→timeout/crashed = regression；crashed→ready = 修好了)
- `http_status` 2xx→5xx 必修
- T2 額外看 `console_errors` / `pageerror` / render broken (`dom_node_count` 暴跌)

**有 regression 怎麼辦**：

1. 把 regression 列出來給使用者看 (對照 Phase 3 breaking changes 嘗試歸因)
2. 三類根因：
   - `SOURCE_CODE` (Phase 4 漏掉的 import / API 使用) → 直接生成修補
   - `BUILD_CONFIG` (vite/webpack/next config 在新版本不相容) → 解釋並提示使用者
   - `RUNTIME_ENV` (peer dep / node version / env var 缺失) → 提示使用者
3. 修補後**重跑 Step 6.6** (重抓 post.json + 重 diff)，最多 3 輪
4. 三輪後仍有 regression → 停下來把完整 diff 給使用者，不要自作主張改 dependency 或退版本

**T3 (人眼模式)**：請使用者重新整理同一個瀏覽器頁面，問：

```
請在你的瀏覽器重新整理 <url> (跟你 baseline 看的同一個頁面)。
跟 baseline 比，有沒有：
[1] 一切正常，沒有新錯誤
[2] 有新的 console 錯誤 / 紅字 (請貼上錯誤訊息)
[3] 畫面跑掉 / 元件不見 / white screen
[4] 啟動就失敗，server 起不來
```

把使用者的回答記到 Phase 7.1 報告的 Runtime Regression 章節。

**Screenshot diff (T2)**：兩張截圖路徑都記到報告裡。**不**做 pixel diff (太多偽陽性
誤判)，只用 `dom_node_count` 暴跌 (post < baseline × 0.1) 當 white screen 訊號。

---

## Phase 7: 產出報告與 Commit Message

### Step 7.1: 遷移報告

> 不要用模板填空。用你自己的語言，寫一份有邏輯、有重點的報告。

報告結構 (參照 `templates/report_structure.md` 但不要死板照抄):

0. **References** — 報告**第一節**就放外部來源連結，reviewer 不用翻到深處就看得到。
   格式：

   ```markdown
   ## References

   - **Changelog**: {changelog_url}           ← Phase 3.1; NOT_FOUND 寫 "_(no changelog found — analysis based on git diff only)_"
   - **Diff**: {compare_url}                  ← Phase 3.2 git_diff_source.compare_url
   - **PR**: {pr_url}                          ← Phase 7.3
   - **Jira**: {issue_url}                    ← Phase 1.C, 僅 jira_context 存在時
   - **CVE / GHSA / BDSA**: {ids_and_urls}    ← Phase 1.B, 多個一行一條
   ```

   這份和後面 section 2「📚 Changelog 來源」不衝突 — section 0 給的是「URL clickable
   quick links」，section 2 給的是「來源類型 / 狀態 / 是否找到」這種 provenance metadata。

1. **Executive Summary** — 3-5 句話總結整個升級
   - 升了什麼、從哪個版本到哪個版本、為什麼
   - 有幾個 breaking changes、影響了幾個檔案
   - 測試結果

2. **Breaking Change 分析來源** — **必填、必須具體**

   這個章節證明分析有根據, 不是憑空生成。格式:

   ```markdown
   ### 📚 Changelog 來源
   - 來源類型: {label, e.g. "GitHub Releases API" / "PyPI project_urls[Changelog]" / "Repo file (main/CHANGELOG.md)"}
   - URL: {實際 URL, 從 `changelog_source.url` 取}
   - 狀態: ✅ 找到 / ❌ 未找到 (若未找到, 說明已嘗試的所有來源)

   ### 🔬 Git Diff 雙軌分析
   - Repository: {git_diff_source.repo_url}
   - 舊版本: `{old_version}` → tag `{old_tag}` → commit `{old_sha[:12]}` (完整 SHA: {old_sha})
   - 新版本: `{new_version}` → tag `{new_tag}` → commit `{new_sha[:12]}` (完整 SHA: {new_sha})
   - Compare URL: {compare_url}
   - 涵蓋檔案: 僅 `*.py` (Python 原始碼差異)
   ```

   - Changelog 找不到時, 不要省略此章節 — 改寫「狀態: ❌ 未找到」並列出已嘗試的來源,
     讓 reviewer 知道分析只靠 Git Diff
   - Git tag 找不到時, 把 `git tag --list` 的最近結果列在此節, 說明退而用何種替代 (例如最近的 release commit)

3. **依賴分析** — 引用類型、衝突處理

4. **Breaking Changes 詳情** — 每個變更的影響和解決方式
   - 每個 BC 條目仍要標 `來源: Changelog ✅/❌ + Git Diff ✅/❌` (見 Phase 3.3)
   - 有引用具體 commit 時用 `<short_sha>` 連到 `{repo_url}/commit/{sha}`

5. **程式碼修改清單** — 每個檔案改了什麼、為什麼

6. **測試結果** — 通過/失敗、是否修改了測試程式

7. **後續建議** — 還有哪些相關套件可能需要更新

8. **回退指南** — 如果需要回退，怎麼做

**Go path 額外章節**（只在 `language == "go"` 時加上）：

9. **🛡️ govulncheck 可達性分析**（如有跑）— 列出 called / imported / not_present
   findings，含 call_sites 的 file:line:function。詳見 `references/go/govulncheck.md`
   的「報告中如何呈現」範本。
10. **🔀 Major Version Path Rewrite**（若觸發 `major_version_rewrite` strategy）—
    列舊路徑、新路徑、影響檔案數、改寫工具（gomajor 或 manual）、殘留掃描結果。
11. **📦 Vendor / Replace 影響**（若 `is_vendored` 或 `has_replace_directives`）—
    說明 vendor diff 大小、保留的 replace directives

**JS path 額外章節**（只在 `language == "javascript"` 且 Step 0.5 抓了 baseline 時加上）：

9. **🖥️ Runtime Verification** — Step 0.5 / Step 6.6 的結果摘要，格式：

   ```markdown
   ### 🖥️ Runtime Verification

   - **Tier**: T1 (HTTP probe) / T2 (T1 + Playwright headless) / T3 (manual)
   - **Start cmd**: `npm run dev`
   - **URL**: http://localhost:3000
   - **Baseline**: boot=ready (4.2s), http=200, stderr_errors=0, console_errors=0 (T2)
   - **Post-upgrade**: boot=ready (4.8s), http=200, stderr_errors=0, console_errors=0 (T2)
   - **Verdict**: ✅ 無 regression / ⚠️ N 個 warning / ❌ M 個 regression
   - **Logs**: `.package-upgrade-cache/runtime-{baseline,post}.log`
   - **Screenshots** (T2): `.package-upgrade-cache/screenshot-{baseline,post}.png`
   ```

   有 regression 時，逐條列出對應 Phase 3 breaking change 與處理方式 (修補 commit、
   或仍未解需 reviewer 注意的項目)。T3 模式則直接引用使用者人眼確認的回答。

### Step 7.2: Git Commit Message

**先偵測這個 repo 的 commit message 風格**（IMPROVEMENTS #13）。讀 `git log --oneline -20`，
判斷主流格式：

```python
patterns = [
    (r'^(?P<type>\w+)\((?P<key>[A-Z]+-\d+(?:, [A-Z]+-\d+)*)\)(?:!)?:\s(?P<desc>.+)',
     'type(KEY): desc'),
    (r'^\[(?P<key>[A-Z]+-\d+)\]\s+(?P<type>\w+)(?:\((?P<scope>[^)]+)\))?:\s(?P<desc>.+)',
     '[KEY] type(scope): desc'),
    (r'^(?P<type>\w+)(?:\((?P<scope>[^)]+)\))?(?:!)?:\s(?P<desc>.+)',
     'type(scope): desc (no Jira)'),
]
# 取在 last 20 commits 中匹配 ≥50% 的格式
```

按該格式生成新 commit message。Skill **預設**是 `[<issue_key>] type(scope): description`，
但若 repo 已有不同主流（例 `type(KEY): desc`），順著它，不要硬塞自己的格式。

接著按以下規範寫 commit message (英文):

- 第一行: `type(scope): description` (≤72 字元)
- Body: 解釋「為什麼」(不只是「做了什麼」)
- 如果是 CVE: 包含 CVE 編號和嚴重性
- 如果有 BREAKING CHANGE: 使用 footer

**Trailer 區塊**（footer 之前，body 之後）— 把可追溯來源列出來，按順序：

1. `Changelog: <url>` — Phase 3.1 抓到的 `changelog_source.url`（**若 `NOT_FOUND` 則整行省略，不要寫 None / N/A**）
2. `Jira: <issue_url>` — 僅當 `jira_context` 存在
3. `Diff: <compare_url>` — Phase 3.2 的 `git_diff_source.compare_url`（GitHub/GitLab 等支援 compare 頁面時）

這幾個 trailer 在 GitHub / Bitbucket / GitLab 的 commit 頁面會自動 render 成
可點擊連結，reviewer 用 `git log` 或 commit 頁就能直接跳到外部來源。

**若有 `jira_context` (Phase 1 情況 C 觸發)**:

第一行必須以 `[<issue_key>]` 開頭,讓 git history 一眼可追到 Jira ticket。

格式:
```
[<issue_key>] type(scope): description

<body — 為什麼這樣做>

Changelog: <changelog_url>
Jira: <issue_url>
Diff: <compare_url>
```

範例 (Changelog 有找到):
```
[V1E-148968] chore(deps): upgrade requests from 2.28.0 to 2.32.0

Bumps requests to address CVE-2024-35195 (high severity, urllib3
session cert verification bypass). Touches 3 files in services/http/.

Changelog: https://github.com/psf/requests/releases
Jira: https://trendmicro.atlassian.net/browse/V1E-148968
Diff: https://github.com/psf/requests/compare/v2.28.0...v2.32.0
```

範例 (Changelog 未找到 — 整行省略):
```
[V1E-148968] chore(deps): upgrade ip-address from 10.1.0 to 10.2.0

Pure transitive bump, no source-code impact. Lockfile-only update.

Jira: https://trendmicro.atlassian.net/browse/V1E-148968
Diff: https://github.com/beaugunderson/ip-address/compare/v10.1.0...v10.2.0
```

**注意**: `[<issue_key>]` 含括號是慣例,即使會讓第一行略長也保留 — 這個前綴是
讓 commit log (`git log --oneline`) 可掃描的關鍵。72 字元上限以 description
本身計算 (不含 `[KEY] ` 前綴)。

### Step 7.3: 建立 Pull Request

將所有變更 commit 後,建立 Pull Request:

```bash
# Commit 所有變更
git add .
git commit -m "<Phase 7.2 產生的 commit message>"

# Push 到遠端
git push -u origin feature/Update-{PackageName}-to-{TargetVersion}

# 建立 PR (如有 gh CLI)
gh pr create --title "chore: upgrade {package} to {version}" \
  --body "$(cat <migration_report.md>)"
```

**`gh` 未認證的 fallback（IMPROVEMENTS #2, #16）**:

Phase 0.3 preflight 已偵測過 `gh auth status --hostname <git_remote_host>`。若未認證
（特別是內部 GHE 如 `adc.github.trendmicro.com`），不要放棄；按以下流程處理：

1. 把 PR title/body 寫到本地檔：

   ```bash
   PR_BODY_FILE="/tmp/$(git rev-parse --abbrev-ref HEAD).pr.md"
   cat > "$PR_BODY_FILE" <<EOF
   <Phase 7.1 報告全文>
   EOF
   ```

2. `git push -u origin <branch>` 的輸出含 `Create PR` URL（GHE / Bitbucket / GitLab 都有），**明確高亮顯示**給使用者，加上 file 提示：

   ```
   ✅ Branch pushed.
   📋 PR body saved to: /tmp/feature-XXX.pr.md  (just `pbcopy < $PR_BODY_FILE` to clipboard)
   🔗 Create PR: https://adc.github.trendmicro.com/<owner>/<repo>/pull/new/feature-XXX
   ```

3. 在 commit message body 補一行 `PR: <to-be-created-url>`（使用 push 輸出的 URL），
   reviewer 從 commit 也能跳過去。

4. 提示使用者如何補 `gh` 認證以便下次自動建立：

   ```
   下次跑 skill 前可一次性執行:
     gh auth login --hostname <host> --git-protocol ssh
   ```

**有 gh 但對該 host 未認證** → 引導使用者用 `! gh auth login --hostname <host>`
（`!` 開頭會在當前 Claude session 跑），認證後 retry 一次建 PR。

**若有 `jira_context`**:

PR title 必須以 `[<issue_key>]` 開頭,PR body **第一行** 必須是
`Jira: <issue_url>` (完整 URL),讓 reviewer 在 GitHub/Bitbucket/GitLab
PR 列表頁直接看得到 Jira link、不用點進 description 才找到。

```bash
gh pr create \
  --title "[<issue_key>] chore: upgrade {package} to {version}" \
  --body "$(cat <<'EOF'
Jira: <issue_url>

<Phase 7.1 完整遷移報告>
EOF
)"
```

範例:
```
Title: [V1E-148968] chore: upgrade requests to 2.32.0
Body 開頭:
  Jira: https://trendmicro.atlassian.net/browse/V1E-148968

  ## Executive Summary
  ...
```

PR 內容應包含:
- **(若有 jira_context) PR title 前綴 `[<issue_key>]` + body 第一行 `Jira: <issue_url>`**
- Phase 7.1 產生的完整遷移報告作為 PR description (接在 Jira link 之後)
- 標記為 `dependencies` / `security` label (如果是 CVE 修復)
- 指定 reviewers (如有需要)

### Step 7.4: Jira 整合 — 條件門檻

Step 7.5 和 7.6 **只在以下條件全部成立時才執行**:

- `jira_context` 存在 (Phase 1 情況 C 觸發)
- Phase 6 測試全部通過 (沒有遺留失敗)
- Phase 4 程式碼修改已套用
- Phase 7.3 已建立 commit/PR (即使 PR 建立失敗,只要 commit 已 push 也算)

**任何一項不成立 → 跳過 7.5 和 7.6**,直接進到 7.7。
不要在升級未完成的狀態下動 Jira ticket。

### Step 7.5: 將遷移報告 Comment 回 Jira ticket

詳細格式請參考 `references/common/jira_workflow.md` 的「Comment Template」章節。

#### 7.5.1: 組裝 comment 內容

**PR URL 是必填的第一行**（對稱於 Phase 7.3 PR body 第一行 `Jira: <url>`） —
讓 Jira ticket watcher 不用點進 description 就看得到 PR link，email 通知預覽
也會直接帶到。

依 Phase 7.3 的執行結果，PR URL 有三種型態，必須選對：

| Phase 7.3 結果 | comment 第一行格式 |
|---|---|
| `gh pr create` 成功 → 拿到 PR URL | `🔗 **PR**: <pr_url>` |
| Push 成功但 `gh` 未認證 (fallback) → 只有 "Create PR" URL | `🔗 **PR (pending creation)**: <create_url>` |
| 連 push 都還沒做 / 失敗 | **不要 post comment**，回到 7.3 重做 |

組裝模板（**必須**這個順序，不要把 PR URL 放到 metadata 中間）：

```markdown
🔗 **PR**: {pr_url}

## 🤖 Automated upgrade by Claude Code

**Package**: `{package}` `{old_version}` → `{new_version}`
**Changelog**: {changelog_url}                          ← 若 Phase 3.1 NOT_FOUND, 整行省略
**Branch**: `{branch_name}`
**Commit**: `{commit_sha_short}`
**Tests**: ✅ Passed ({test_count} tests) | ❌ {failed_count} failures
**Runtime**: {runtime_summary}                          ← JS path 且 Step 0.5 抓了 baseline 才出現; Python/Go 整行省略 (見 references/common/jira_workflow.md §4.1)

### Executive Summary
{Phase 7.1 第一節原文}

### Breaking Changes
- 處理 {N} 個 breaking changes
- 修改 {M} 個檔案、{K} 處變更
- 詳情見 PR description 或 attached report

### Acceptance Criteria
{若 Phase 1.C.3 抽到 acceptance criteria,逐條標記 ✅/❌/N/A}

---
*Generated by [package-upgrade skill](https://github.com/.../package-upgrade-skill)*
```

**Changelog 欄位規則**：
- 來源是 Phase 3.1 在 session 中保留的 `changelog_source.url`
- `NOT_FOUND` → **整行省略**，不要寫 `None` / `(none)` / `N/A` — Jira render 出來會像沒處理的 placeholder
- 找到 → 直接放 URL（不要 markdown link，因為 Jira 不同版本對 markdown 的解析行為不一致）

**Pre-post 檢查**（必跑）：

1. `pr_url` 在 session state 中存在 — 否則 **abort comment**，告知使用者「PR 還沒建立 / push 還沒做完，先回到 Phase 7.3 處理」
2. `pr_url` 不是空字串、不是字面 `"未建立"`、不是 `"None"`
3. `pr_url` 看起來像 URL（含 `http://` 或 `https://`），或對應 "Create PR" 的
   `pull/new/<branch>` / `merge_requests/new` 形式

任何一條不過 → 直接不 post，**回 Phase 7.3 retry**，不要用 placeholder 字串糊弄。

#### 7.5.2: 確認點 — 暫停等待使用者同意

> Jira comment 對 ticket watchers 可見,可能觸發 SLA / 通知,務必先確認。

```
即將將上述報告 comment 到 Jira ticket {KEY}:
{url}

預覽:
---
{comment_body}
---

繼續嗎?
[Y] 是, post comment
[E] 我想先編輯 comment 內容
[N] 不要 post, 只完成本機操作
```

#### 7.5.3: 執行 post

根據 `jira_context.auth_mode`:

**MCP 模式**:
```
mcp__claude_ai_Atlassian_Rovo__addCommentToJiraIssue(
  cloudId=<jira_context.cloud_id>,
  issueIdOrKey=<jira_context.issue_key>,
  commentBody=<assembled markdown>,
  contentFormat="markdown"
)
```

**REST token 模式**:
```bash
ATLASSIAN_EMAIL=... ATLASSIAN_API_TOKEN=... \
  python scripts/common/jira_comment.py <site> <issue_key> <comment_file>
```

若 post 失敗 → 不要重試自動,把組好的 comment body 完整輸出給使用者,告知失敗原因,
讓使用者決定是手動貼上還是放棄。**繼續到 7.6** (post 失敗不 block transition,但會在
prompt 中如實告知)。

### Step 7.6: 依目前狀態推進 Jira ticket

#### 7.6.1: 取得可用 transitions

**MCP 模式**:
```
mcp__claude_ai_Atlassian_Rovo__getTransitionsForJiraIssue(
  cloudId=<cloud_id>,
  issueIdOrKey=<issue_key>
)
```

**REST 模式**:
```bash
python scripts/common/jira_transition.py list <site> <issue_key>
```

#### 7.6.2: 依 `current_status` 決定目標 transition

依 ticket **目前狀態** (case-insensitive) 走以下分支:

| 目前狀態 | 第一步 (預設推薦) | 第一步完成後 | 備註 |
|----------|--------------------|--------------|------|
| `To Do` / `Todo` / `Open` | `Ready for Work` | 接著 7.6.4 詢問是否再轉 `Done` | 兩段式:中間態 → Done |
| `Ready for Work` | `Development` / `In Progress` | 接著 7.6.4 詢問是否再轉 `Done` | 兩段式:中間態 → Done |
| 其他 (`Development` / `In Progress` / `Code Review` / ...) | match Done 同義詞 (見下) | — | 單段式,直接走原本 Done 流程 |

**Done 同義詞 match 順序** (case-insensitive,比對 transition `name` 與 `to_status`):

1. `done`
2. `resolved`
3. `closed`
4. `completed`
5. `fixed`

**中間態 transition match**:
- `Ready for Work`: 比對 transition `name` / `to_status` 為 `ready for work` (case-insensitive)
- `Development`: 依序比對 `development`, `in development`, `in progress`,取第一個 match

若任一階段找不到對應 transition → 列出所有可用 transitions 讓使用者挑,
不要硬塞或猜測。

#### 7.6.3: 第一段確認 — 中間態 transition

> 永遠不要自動 transition,即使使用者 7.5 已同意 post comment。
> 狀態變更可能觸發 release notes、SLA 計時、自動通知等下游效應。

`current_status` 為 `To Do` 或 `Ready for Work` 時,先問中間態。

**Bulk-confirm 路徑 (推薦,IMPROVEMENT.md §6.3)**:
對於 `issuetype.name == "Vulnerability"` 或 CVE 修復類型的 ticket,
絕大多數情況走「中間態 → Development」的固定流程,沒必要逐步問。
**預設選項是 `[Y]` (Bulk),少 2 個 prompt**:

```
升級已完成 ✅
- 套件: {package} {old} → {new}
- 測試: 全部通過 ({n} tests)
- PR: {pr_url}
- Comment 已 post 到 Jira: {comment_url_if_available}

目前 ticket {KEY} 狀態為 `{current_status}` (issuetype: {issuetype_name})。
建議路徑: `{current_status}` → `{intermediate_target_name}` → `{development_state}`
(等 PR merge 後手動轉 Done)。

[Y] 是, 一次轉完中間態 + Development (推薦)         ← 預設
[S] 我想逐步確認每一步 (走原本兩段式流程, 7.6.3 + 7.6.4)
[O] 我自己決定要轉哪個狀態 (顯示完整 transition 清單)
[N] 否, 保持 {current_status} (跳過後續 Done 詢問)
```

選擇後續行為:
- `[Y]` Bulk → 依序執行兩個 transition (中間態 → Development),全部成功才進 7.6.4 詢問
  Done; 任一失敗則停下、列出錯誤、不繼續、不繞過
- `[S]` 逐步 → 走下方的 fallback 兩段式 prompt
- `[O]` → 列出完整 transition 清單讓使用者挑
- `[N]` → **不再問 Done**,直接進 7.7

**Fallback (`[S]` 逐步路徑 / 非 Vulnerability issuetype)**:

```
目前 ticket {KEY} 狀態為 `{current_status}`。
是否將狀態推進至 `{intermediate_target_name}`?

[Y] 是, 轉為 {intermediate_target_name}
[O] 轉為其他狀態 (顯示完整 transition 清單)
[N] 否, 保持 {current_status} (跳過後續 Done 詢問)
```

若使用者選 [N] → **不再問 Done**,直接進到 7.7。
若使用者選 [Y] / [O] → 執行 transition (見 7.6.5),完成後進到 7.6.4。

對於非 `To Do` / `Ready for Work` 的目前狀態,**跳過 7.6.3**,直接進入 7.6.4
(套用單段式 Done 流程)。

#### 7.6.4: 第二段確認 — 是否轉為 Done

進到此步驟的兩種情境:
- (a) 已完成 7.6.3 的中間態 transition (此時 `current_status` 已更新)
- (b) 目前狀態本來就不是 `To Do` / `Ready for Work` (跳過 7.6.3)

```
是否再將 Jira ticket {KEY} 從 `{current_status}` 轉為 `{done_transition_name}`?

[Y] 是, 轉為 {done_transition_name}
[O] 轉為其他狀態 (顯示完整 transition 清單)
[N] 否, 保持 {current_status}
```

若 Done 同義詞找不到 match (workflow 不允許從目前狀態直接到 Done) →
列出可用 transitions 讓使用者選,或選 [N] 維持現狀。

#### 7.6.5: 執行 transition

7.6.3 與 7.6.4 中使用者選 [Y] / [O] 時,共用此實作。

**處理 resolution field** (僅在 transition 到 Done 類狀態時):
- 升級類型若為 CVE 修復 → 預設 `resolution: "Fixed"`
- 一般升級 → 預設 `resolution: "Done"`
- 若 transition 不需要 resolution → 不設 fields
- 中間態 transition (Ready for Work / Development) → 通常**不需要** resolution,不要設

**MCP 模式**:
```
mcp__claude_ai_Atlassian_Rovo__transitionJiraIssue(
  cloudId=<cloud_id>,
  issueIdOrKey=<issue_key>,
  transition={"id": "<transition_id>"},
  fields={"resolution": {"name": "Fixed"}}   # 視 workflow 而定,中間態通常不設
)
```

**REST 模式**:
```bash
python scripts/common/jira_transition.py apply <site> <issue_key> <transition_id> [resolution_name]
```

若 transition 因 workflow 限制失敗 (例如必填欄位、permission):
- 將錯誤訊息和該 ticket 的瀏覽器 URL 完整告訴使用者
- 不重試,不繞過,讓使用者手動處理
- 中間態若失敗 → **不要自動繼續**詢問 Done,先讓使用者排除問題

### Step 7.7: 完成

將報告輸出給使用者，並提供:
1. 報告全文
2. 已建立的 commit 和 branch 資訊
3. Pull Request URL (如已建立)
4. **若有 jira_context**: comment URL 和最終 ticket status
5. 回退命令 (以防需要)

### Step 7.8: 邀請使用者回饋

最後，**邀請一次** (不要催)，讓使用者知道有 feedback channel：

> 如果這次跑下來有遇到不順、判斷錯誤、或想到可以改進的地方，
> 歡迎輸入 `/package-upgrade-feedback` 把回饋送出，會自動 sanitize 後
> 開成 GitHub Issue (不會送出任何 token / 絕對路徑 / Jira key)。

**不要** 主動產出 IMPROVEMENT.md 或寫任何檔案 — 由 feedback skill 互動式收集即可。
**不要** 引導使用者去回顧每個 Phase 的問題 — 主 skill 在 Phase 7.7 已經結束工作，
這只是一行 hint。

---

## 錯誤處理

- **Changelog 抓不到**: 只依賴 git diff 分析，告知使用者
- **Git repo 找不到**: 只依賴 changelog，告知使用者
- **兩者都失敗**: 用 web search 搜尋 breaking changes 資訊
- **(JS) `.d.ts` API surface diff strategy=none**: 兩版都沒有型別宣告 — 走 Git diff + Changelog 雙軌，並在報告中標明
- **(JS) `npm pack` 失敗** (registry 連不到 / 版本不存在): 直接告知使用者，跳過 .d.ts diff 走 Git diff
- **(Go) `apidiff` 不可用 / strategy=none**: 走 Git diff + Changelog 雙軌，並在報告中標明
- **(Go) `go mod download` 失敗**: 私有 module — 提醒使用者檢查 GOPRIVATE 與 .netrc，或暫時跳過 apidiff
- **(Go) `govulncheck` 不可用**: 降級為 grep-only CVE 風險評估，報告中標明缺乏 reachability 分析
- **(Go) `gomajor` 不可用且 strategy 是 `major_version_rewrite`**: 走手動 fallback (Phase 5.3 描述)
- **測試持續失敗**: 3 次迴圈後停止，報告給使用者
- **環境損壞**: 用 snapshot script restore 回退

```bash
# Python 回退命令
bash scripts/python/snapshot_env.sh <project_path> restore

# JavaScript 回退命令
bash scripts/javascript/snapshot_env.sh <project_path> restore
# 還原檔案後依 lockfile 重新安裝 (不會跑 lifecycle scripts)
# npm:  npm ci
# yarn: yarn install --frozen-lockfile
# pnpm: pnpm install --frozen-lockfile

# Go 回退命令
bash scripts/go/snapshot_env.sh <project_path> restore
# 還原 go.mod / go.sum 後:
go mod download   # 重新填 module cache
# 若 vendored:
go mod vendor
```

---

## 使用者確認點一覽

在以下時間點，你必須暫停等待使用者確認，不可自動繼續:

| 時間點 | 你要提供的資訊 |
|--------|-------------|
| Phase 0.3: Pre-flight blockers | 列出 ❌ blockers + 修法 + 詢問 [1] 修完再來 / [2] 走 fallback / [3] 中止 |
| Phase 0.3: 缺 auth token | 列出哪個 env var + token portal URL + 詢問 [1] 提供 token / [2] 跳過走 lockfile-only / [3] 中止 |
| Phase 0.3.1: `.env.<service>` 已有同 key | 顯示衝突 + 詢問 [Y] 覆蓋舊 token / [N] 保留現有檔 (新 token 仍 session export) |
| Phase 1.C.4: Jira ticket 解析結果 | 抽到的 package/版本/CVE/驗收條件,等使用者校正 |
| Phase 2.0 (JS workspace): 範圍選擇 | 是否套用到 root / 特定 workspace / 全部 (見 Phase 2.0 表) |
| Phase 2.0.1 (Go workspace): 子模組選擇 | `go.work` 內哪些子模組是目標 |
| Phase 2.2 B/JS-2: 更新已存在的 override/resolution | target 已在 overrides/resolutions, 確認改值 |
| Phase 2.2 B/JS-3: 升級 direct parent (預設推薦) | 哪個 parent / chain / 是否升 |
| Phase 2.2 B/JS-4: 加 override 而非升 parent | 替代路徑, 列出 patch 內容後確認 |
| Phase 2.2 B/JS-5: lock_only last resort | 強烈警告 + 詢問是否真要走 |
| Phase 2.2 B/Go-2: major_version_rewrite | 列舊新 import path + 影響檔數,選 gomajor 或 manual fallback |
| Phase 2.2 B/Go-3: 升 direct parent (預設推薦) | parent chain + 是否升 |
| Phase 2.2 B/Go-4: bump_indirect 直接動 indirect entry | 確認改 `// indirect` 條目 |
| Phase 2.2 B/Go-5: add_replace last resort | 強烈警告 replace 不會傳遞給 downstream consumer |
| Phase 2.2 B-3 (Python): Transitive lock-only 升級確認 | 套件是 transitive、parent 允許,僅更新 lock 不動宣告檔 |
| Phase 2.2 B-4 (Python): Parent 阻擋升級的決策 | parent 約束擋住,問使用者升級 parent / 放棄 / 自選 |
| Phase 2.3: 衝突解決方案 | 多種方案 + 風險評估 + 推薦 |
| Phase 4.4: 程式碼修改預覽 | 完整 diff + 每處修改的理由 |
| Phase 5.1: 建立 Git 分支 | 分支名稱、即將開始修改 |
| Phase 6.4: 測試程式修改 | 為什麼要改 + 改後仍驗證什麼 |
| Phase 7.3: 建立 Pull Request | PR 資訊、是否建立 PR |
| Phase 7.5.1: pr_url 缺漏時 abort comment | 哪一步沒做完 (push 失敗 / 沒建 PR) → 回 Phase 7.3 |
| Phase 7.5.2: 將報告 Comment 回 Jira | comment 預覽 (第一行必為 PR URL) + ticket URL |
| Phase 7.6.3: Jira 中間態 transition (TODO→Ready for Work / Ready for Work→Development) | 目前狀態 + 中間目標,絕不自動執行 |
| Phase 7.6.4: 是否將 Jira status 轉為 Done | 目標狀態 + 目前狀態,絕不自動執行 |
