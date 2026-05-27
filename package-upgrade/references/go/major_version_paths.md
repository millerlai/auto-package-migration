# Go Major Version Path Rewrite

> 從 v1 升到 v2+（或更高 major 之間互升）的特殊流程。
> Go 把 major version 編進 import path，這是其他語言完全沒有的概念。

## 規則回顧

[Semantic Import Versioning](https://research.swtch.com/vgo-import) — Go modules
規定：

| Module 版本 | Module path | import 寫法 |
|-------------|-------------|-------------|
| `v0.x.x` | `example.com/foo` | `import "example.com/foo"` |
| `v1.x.x` | `example.com/foo` | `import "example.com/foo"`（同 v0） |
| `v2.x.x` | `example.com/foo/v2` | `import "example.com/foo/v2"` |
| `v3.x.x` | `example.com/foo/v3` | `import "example.com/foo/v3"` |

**所以 v1→v2 升級不是一個版本號變更，而是 import path 變更。**

例外：少數 v2+ module 沒走標準路徑（在 `go.mod` 標 `module example.com/foo` 而非
`example.com/foo/v2`），這是 "GOPATH-mode-like" legacy。Phase 2 偵測到時要告知
使用者該套件用了非標準 versioning，無法用 `gomajor` 自動處理。

---

## 偵測 major version jump

`dep_tree_go.sh` 內含偵測邏輯：

```bash
# 取得 target 套件可用版本清單
go list -m -versions example.com/foo

# 範例輸出
# example.com/foo v0.1.0 v0.2.0 v1.0.0 v1.1.0 v1.2.0

# 若使用者指定 target_version 為 v2+，且當前是 v1：
# 1. 先查 v2 對應的 module path 是什麼
go list -m -json example.com/foo/v2@latest 2>/dev/null
# 若存在 → 標準路徑 → 用 gomajor
# 若 404 → 該套件可能用了非標準路徑，提示使用者手動處理
```

設定 strategy = `major_version_rewrite` 後，session state 中保留：

```json
{
  "old_path": "example.com/foo",
  "new_path": "example.com/foo/v2",
  "old_version": "v1.4.3",
  "new_version": "v2.0.0"
}
```

---

## 升級流程：方法 A — gomajor（首選）

[`gomajor`](https://github.com/icholy/gomajor) 是 Go 社群最成熟的 major version 升級
工具。它做的事：
1. 解析所有 source 檔的 import statement
2. 用 AST 把 `"example.com/foo"` 改寫為 `"example.com/foo/v2"`
3. 跑 `go get example.com/foo/v2@latest`
4. 跑 `go mod tidy`

**安裝**（preflight 偵測到沒裝時提示）：

```bash
go install github.com/icholy/gomajor@latest
```

**執行**：

```bash
gomajor get example.com/foo/v2@latest
```

**驗證**：

```bash
git diff --stat               # 看哪些檔案被改
go build ./...                # 確認可以 compile
go vet ./...                  # 抓 obvious bug
```

`gomajor` 偶爾會漏掉的情境：
- 在 string literal 中組出 import path（極罕見，例如 reflect 反射用）
- 在 `go:generate` directive 引用了該套件
- 在 build tag 條件下 import（OK，但需要該 tag 開啟才掃到）

Phase 4 的 `ast_scanner_go.go` 跑一次掃描，比對 gomajor 改完後是否還有殘留的舊
路徑（grep 即可）— 有的話人工處理。

---

## 升級流程：方法 B — 手動兩步（fallback）

當 gomajor 不可用、或 gomajor 改完仍有殘留時。

### Step 1: 動 `go.mod`

```bash
# 取得新版本（在 go.mod 加入新 require entry）
go get example.com/foo/v2@latest
# go.mod 現在有兩個 entry：
#   require example.com/foo v1.4.3       // 舊（其他 transitive 還在用）
#   require example.com/foo/v2 v2.0.0    // 新
```

### Step 2: AST 改寫所有 import

對每個有 `import "example.com/foo"` 的檔案：

```diff
- import "example.com/foo"
+ import "example.com/foo/v2"

  // 注意：別名 `import foo "example.com/foo"` 不用改變數名 —
  // import path 變但 package name 通常還是 foo（go.mod 的 `module` 行決定）
```

可以用 `gofmt -r 'a -> b'` 或 `goimports`，但對 import path 字串它們不會直接處理 —
**還是要 AST 或字串替換**。範例使用 `sed`：

```bash
# DANGER: sed 會炸到 string literal 中的同名字串。只有在確定沒有那種情況時用。
grep -rl '"example.com/foo"' --include='*.go' . | \
  xargs sed -i '' 's|"example.com/foo"|"example.com/foo/v2"|g'
```

**推薦做法**：直接用 `ast_scanner_go.go` 列出所有 import 位置（行號 + 上下文），
Phase 4 用 Edit tool 逐一改。比 sed 安全。

### Step 3: 清理舊 require entry

```bash
go mod tidy
# go.mod 中舊的 require example.com/foo v1.x.x 應該會被移除（前提是
# 沒有 transitive 還在 require 它）
```

若 `go mod tidy` 後舊 entry 還在，代表某個 transitive 還在用舊 path — 這時要：
1. `go mod why example.com/foo` 找出誰
2. 通常是另一個 indirect dep 還沒升 — 評估要不要連那個 dep 一起升
3. 或保留兩個 entry（合法但會有兩份 binary code），在報告中註明

---

## Sub-module 場景

有些 monorepo 模組會用 sub-path tag：

```
example.com/lib              -> 根模組 v1
example.com/lib/cmd/foo      -> v1.x.x 的子工具
example.com/lib/parser/v2    -> sub-module 自己 v2
```

`dep_tree_go.sh` 偵測 `module` declaration 時要注意：upgrade target 可能是
`example.com/lib/parser`（不是根）。

`git_diff_go.sh` 找 tag 時也要支援 monorepo 慣例：
- `v2.0.0`（根模組）
- `parser/v2.0.0`（sub-module）
- `cmd/foo/v2.0.0`

`git_diff_go.sh` 的 `find_tag` 已涵蓋多種 pattern。

---

## 報告中如何呈現

Phase 7.1 報告必須清楚列出兩條 path：

```markdown
### 🔴 Major Version Path Rewrite

- 舊 import path: `example.com/foo`
- 新 import path: `example.com/foo/v2`
- 影響檔案: 14 個 .go 檔，共 17 處 import 改寫
- 改寫工具: `gomajor get example.com/foo/v2@latest` ✅ 成功
- 殘留掃描: AST scanner 已驗證 0 處舊路徑遺留

**Reviewer 注意**：本 PR 同時包含 import path 改寫與套件 API 變更，
diff 行數會比一般 minor 升級多很多。建議先看 `go.mod`，再看 source 變更。
```

---

## 常見坑

1. **`go.mod` 同時有 v1 + v2 entry** — 不一定錯，但若兩者都被使用，binary 會包兩份 code。
   `go mod why` + `go mod graph` 查清楚。
2. **`go mod tidy` 報錯「inconsistent vendoring」** — vendor mode 沒跟著更新。
   跑 `go mod vendor` 補。
3. **`go mod tidy` 把舊 require 加回來** — 某個 dep 透過 dep tree 還在用舊 path。
   要連那個 dep 一起升，或保留共存。
4. **CI fail：unknown package** — 某個 import 沒改到（gomajor 漏 / 改 sed 漏一段）。
   `go build ./...` 本地先跑過。
5. **跨 major 跳多版（v1 → v4）** — 強烈建議**分階段**：v1→v2→v3→v4，每一段獨立 PR。
   每一段都可能引入不同的 breaking change，混在一起 reviewer 看不清楚。
