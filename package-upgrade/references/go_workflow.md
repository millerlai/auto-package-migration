# Go Workflow

> Phase 0 偵測到 `language: "go"` 時，整個流程改走這份文件 +
> `go_major_version_paths.md` + `breaking_change_patterns_go.md` + `govulncheck.md`。

## 為什麼 Go 要獨立一條 path

Go 跟 Python / JavaScript 有幾個結構性差異，這些差異直接影響升級工作流：

1. **單一套件管理工具 (Go modules)** — 不像 Python 要分 pip/poetry/uv。但要偵測 legacy
   工具（`Gopkg.toml` = dep、`glide.yaml` = glide、`vendor.json` = govendor）並提醒使用者
   先 migrate 到 modules。
2. **Major version 在 import path** — `v2+` 要改 import path 為 `pkg/v2`。這代表
   升 major 版本要動 **所有 source 檔的 import 字串**，不是只動 `go.mod`。
   詳見 `go_major_version_paths.md`。
3. **Minimum Version Selection (MVS)** — Go 選滿足條件的「最低」版本，而非「最新」。
   `go get pkg@latest` 才會升到最新，`go get -u ./...` 會升所有 transitive。
4. **沒有獨立 lockfile** — `go.mod` 同時是 manifest 與「準 lockfile」（含 indirect entries
   與 minimum version 鎖定），`go.sum` 純粹是 hash 驗證。升級 transitive 必然動 `go.mod`，
   沒有像 JS 那種 lock-only 完全不動 manifest 的路徑。
5. **govulncheck reachability 分析** — 官方工具，會做 call graph 分析判斷漏洞函式
   是否真的被呼叫到。比 `npm audit` / `pip-audit` 只看 dep tree 精準很多。這是 Go path
   相對其他語言的價值。詳見 `govulncheck.md`。
6. **Replace directive** — 在 `go.mod` 可以重寫某個模組的來源（用於 fork、私有 mirror、
   安全 pin）。升級流程必須保留這些 directive，不能直接覆蓋。
7. **Vendor mode** — 部分專案 (`vendor/modules.txt` 存在) build 時用 `vendor/` 目錄
   而非模組 cache。升級後必須跑 `go mod vendor`，不然 build 仍用舊版。
8. **GOPROXY / GOPRIVATE** — 公司網段常使用內部 Go proxy (JFrog 等)。認證走
   `~/.netrc` 而非 env var。`GOPRIVATE` 列出不走 proxy 的私有路徑 pattern。

---

## 觸發後讀什麼

| 工具 / 場景 | reference |
|------------|-----------|
| 基本流程 | 本檔 `go_workflow.md` |
| Major version (`v2+`) 升級 | `go_major_version_paths.md` |
| CVE / 漏洞分析 | `govulncheck.md` |
| Breaking change pattern | `breaking_change_patterns_go.md` |
| Auth (`.netrc`, GOPROXY) | `auth_tokens.md`（與 JS 共用） |
| BDSA / GHSA → CVE | `bdsa_mapping.md`（與其他語言共用） |
| Jira / commit / PR | `jira_workflow.md`（與其他語言共用） |

---

## Phase 對應總覽

| Phase | Helper | 與其他 language 的差異 |
|-------|--------|----------------------|
| 0 環境偵測 | `scripts/detect_env_go.sh` | 多偵測 `go.work`、`vendor/`、legacy（dep/glide）、GOPROXY/GOPRIVATE、govulncheck/apidiff 是否安裝 |
| 0.3 Pre-flight | `scripts/preflight.sh`（共用） | 多檢查 `go` 在 PATH、私有 module 認證 `.netrc`、govulncheck 可用 |
| 1 輸入解析 | 共用 | CVE 場景**多一條 govulncheck path**：先跑掃描判斷可達性 |
| 2 依賴分析 | `scripts/dep_tree_go.sh` | 多一個 `major_version_rewrite` strategy；無 lock-only strategy |
| 3 Breaking change | `scripts/api_surface_diff_go.sh` + `scripts/git_diff_go.sh` + `scripts/fetch_changelog.py` | **三軌**：`apidiff` 取代 `.d.ts` diff；Git diff 過濾 `*.go` 排除 `_test.go` / `vendor/` |
| 4 程式碼影響 | `scripts/ast_scanner_go.go` (`go run`) | 使用 `go/parser` + `go/ast`；symbol 命名規則見下 |
| 5 執行升級 | `go get` + 可能的 `gomajor` + `go mod tidy` + `go mod vendor`（若 vendor mode） | 與 JS 不同：沒有 lifecycle script 隱憂；major version 要 path rewrite |
| 6 測試 | `scripts/run_tests_go.sh` | `go test ./...`、`-race`、`-count=1` 防 cache |
| 7 報告 | 共用模板 | Report 多一節：**govulncheck 可達性分析**（若觸發） |

---

## Symbol 命名規則（對應 Phase 3 ↔ Phase 4 串接）

`ast_scanner_go.go` 把 source 中的 usage normalize 成
`<import-path>.<Symbol>[.<Member>...]`，規則：

| 你寫的 code | 記錄的 symbol |
|------------|--------------|
| `import "github.com/foo/bar"` + `bar.NewClient()` | `github.com/foo/bar.NewClient` |
| `import b "github.com/foo/bar"` + `b.Foo` | `github.com/foo/bar.Foo` (alias 還原為原 path) |
| `import . "github.com/foo/bar"` + `Foo()` | `github.com/foo/bar.Foo`（dot import — 標 `dot_import: true`） |
| `import _ "github.com/foo/bar"` | `<path>` 標 `blank_import: true`（純 side-effect） |
| `import "github.com/foo/bar/v2"` + `bar.Client{}` | `github.com/foo/bar/v2.Client`（保留 `/v2` 後綴在 symbol prefix） |
| 同一檔內 `b.Inner.Method()` | `github.com/foo/bar.Inner.Method`（最多展開一層 selector） |

`api_surface_diff_go.sh`（apidiff 包裝）也用同樣 `<package-path>.<Symbol>` 格式輸出
removed/added/changed，兩邊集合可直接比對。

> Dot import (`import . "pkg"`) 在 Go 是反 pattern，升級時遇到的話**警告**使用者：
> AST 掃描只能 best-effort（無法區分本地 symbol 與 dot-import 帶入的 symbol）。

---

## 升級命令 (Phase 5)

### 5.3.1 Direct dependency — minor / patch

```bash
# 升到指定版本
go get example.com/foo@v1.5.2

# 升到該 major 系列最新
go get example.com/foo@latest

# 升 patch（保留 major.minor）
go get -u=patch example.com/foo
```

升完一律補：

```bash
go mod tidy        # 清理 require 區塊
go mod verify      # 驗證 go.sum hash
```

### 5.3.2 Direct dependency — major version (`v1 → v2+`)

**這是 Go 升級最特殊的場景**。詳見 `go_major_version_paths.md`。摘要：

```bash
# 方法 A: gomajor（若已安裝；會自動改 source）
go install github.com/icholy/gomajor@latest
gomajor get example.com/foo/v2@latest

# 方法 B: 手動兩步（gomajor 不可用 fallback）
# 1. go get example.com/foo/v2@latest  → 只動 go.mod
# 2. 用 ast_scanner_go.go 找出所有 `"example.com/foo"` import,
#    逐一改為 `"example.com/foo/v2"`
# 3. go mod tidy 把舊路徑 require entry 拿掉
```

### 5.3.3 Indirect dependency — bump parent

Go 沒有 lock-only 路徑（`go.mod` 同時是 manifest）。Indirect 升級必然在 `go.mod`
新增或更新該條 entry。處理方式：

**5.3.3.a Parent 升級後本來就會拉新版**（首選）：

```bash
go get example.com/parent@<version-that-pulls-new-foo>
go mod tidy
```

**5.3.3.b 直接 bump transitive**（次選，會在 `go.mod` 新增 `// indirect` entry）：

```bash
go get example.com/foo@v1.5.0
go mod tidy
```

Go MVS 規則：`go.mod` 中 indirect entry 的版本是「最低可接受」版本，其他 module
若 require 更高版本，build 時自動升上去。所以 indirect bump 是合法且常見的做法
（CVE 修復時尤其常用）。

**5.3.3.c Replace directive**（last resort，**永遠詢問使用者**）：

```text
require example.com/foo v1.4.0 // indirect
replace example.com/foo => example.com/foo v1.5.0
```

或指向 fork：

```text
replace example.com/foo => github.com/our-org/foo v1.5.0-patch.1
```

只在以下情境推薦：
- 緊急 CVE patch、上游還沒 release
- 上游有 bug 且 maintainer 不修
- 需要 fork 出來自己改

**警告**：`replace` 只對「主模組」生效。如果你的模組被其他人 import，他們**不會**繼承
你的 `replace`，需要自己加。要在報告中明確說明。

### 5.3.4 Vendor mode

若 Phase 0 偵測到 `vendor/modules.txt` 存在，**每次升完都要**：

```bash
go mod vendor
```

不然 build 時 Go 仍從 `vendor/` 讀舊版 source。報告中要列出 vendor diff 大小
（行數通常很大，要警告 reviewer 不用逐行 review）。

### 5.3.5 Workspace mode (`go.work`)

若 `go.work` 存在，這是 multi-module workspace。需要判斷升級目標屬於哪個子模組：

```bash
# 列出 workspace 內所有模組
go work edit -json | jq '.Use[].DiskPath'

# 在特定子模組內升級
cd path/to/submodule && go get example.com/foo@v1.5.0
```

`go.work` / `go.work.sum` **不應 commit** 到大多數 repo（公司政策決定）— Phase 5
不主動修改 `go.work`，但 snapshot 要備份。

---

## Phase 2 升級策略（dep_tree_go.sh 輸出）

`upgrade_strategies[]` 按推薦順序排：

| Strategy | 觸發條件 | 動作 |
|----------|---------|------|
| `direct_bump` | target 在 `go.mod` `require` 區塊且非 `// indirect` | `go get target@version` |
| `major_version_rewrite` | target 新版本是 `v2+`，且當前是 `v0/v1`（major version path 不同） | 走 `go_major_version_paths.md` 流程 |
| `bump_parent` | target 是 indirect，存在直接 parent 在 `go.mod` 中 | `go get <parent>@<version-that-pulls-new>` |
| `bump_indirect` | target 是 indirect，無 parent 路徑或為直接安全 pin | `go get target@version`（在 `go.mod` 中新增/更新 indirect entry） |
| `add_replace` | target 在上游無新版、需 fork、或緊急 patch | 編輯 `go.mod` 加 `replace` directive — **永遠詢問使用者** |

⚠️ **跟 JS path 的差異**：沒有 `lock_only` strategy。原因：`go.mod` 同時是 manifest，
任何升級都會改它。`bump_indirect` 是 Go 的最接近等價物。

---

## CVE / 漏洞流程（Phase 1 情況 B）

Go path 在 Phase 1 情況 B 多一個前置步驟：**先跑 govulncheck**。

```bash
bash scripts/govulncheck_go.sh <project_path> [--cve CVE-XXXX-XXXXX]
```

輸出區分：
- `called_vulns`：call graph 證實有被呼叫 → **🔴 critical**
- `imported_vulns`：在 dep tree 但 call graph 沒走到 → **🟡 medium**
- `not_present`：dep tree 中沒這個套件 → 無需處理

這比 OSV / NVD 描述精準，**Phase 1.B step 3 的「LLM 風險評估」要優先參考
govulncheck 結果，不是只看 grep**。

詳見 `govulncheck.md`。

---

## 測試 (Phase 6)

```bash
# 標準
go test ./...

# 平行 + race detector（推薦每次 CVE 升級都跑）
go test -race ./...

# 不吃 build cache（升級後最好避免 cache 假陽性）
go test -count=1 ./...

# Targeted（Phase 6.2 第一輪 — 只跑受影響 package）
go test ./path/to/affected/package/...
```

`run_tests_go.sh` `--files <go_files>` 模式會把每個檔案 map 回所在 package，
跑 `go test <pkg-paths>`（Go 是 package-level 測試，不像 jest 可以指定單檔）。

**Build tags**：若專案有用 `//go:build <tag>` 區隔不同 OS / 環境，預設 CI 只測單一
組合。Phase 6 報告要列出**未測到的 build tag combination**（從 `git grep '//go:build'`
抓出），讓 reviewer 知道需要在 CI 補測。

---

## 不在 MVP 範圍

下列場景遇到時 **停下來告訴使用者**，不要假設可以自動處理：

- **C 語言 cgo 變更** — 升級時若 `import "C"` 區塊變動，可能需重新處理 build 環境
- **`embed.FS` 內的資源變動** — 升級可能改變嵌入資源的版面
- **Code generation** (`go generate`) — 升級後 generated code 可能需重跑
- **Plugin (`-buildmode=plugin`)** — 動態載入的 .so，ABI 相容性難自動驗證
- **GOEXPERIMENT flags** — 例如 `loopvar`、`rangefunc`，升級 Go runtime 才相關
- **Legacy tooling 遷移**（dep → modules） — 提示使用者先跑 `go mod init`
- **跨 major version 升級（如 v1 → v4）一次跳多版** — 建議分階段，每個 major 各跑一次 skill
