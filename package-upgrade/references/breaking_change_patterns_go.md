# Go Breaking Change Patterns

> 對應 Python 的 `breaking_change_patterns.md` 與 JS 的 `breaking_change_patterns_js.md`。

## Changelog / Release Notes 措辭

Go 生態的 release notes 慣用語：

| 措辭 | 推測的 breaking change | 信心 |
|------|---------------------|------|
| "module path changed to .../v2" | Major version path rewrite | 確定 |
| "removed deprecated `Foo`" | exported symbol 刪除 | 高 |
| "renamed `X` to `Y`" | symbol rename | 高 |
| "now requires Go 1.21+" | toolchain 最低版本提升 | 高 |
| "context.Context is now the first parameter" | function signature 新增 ctx | 高 |
| "returns error instead of bool" | return type 變更 | 高 |
| "the X interface now has Y method" | interface 擴充 → implementer 全爆 | 高 |
| "now uses generics" | 簽名從 `interface{}` 改為型別參數 | 中 |
| "switched to errors.Is/As" | 改用 wrapped error，原本 `==` 比對失效 | 中 |
| "default value of X changed from .. to .." | 預設行為變更 | 中 |
| "moved to internal/" | 套件變 internal，不能 import | 高 |
| "deleted X subpackage" | sub-package 刪除 | 高 |

---

## Go 特有的 breaking patterns

### A. Major version path rewrite (v1 → v2+)

最常見、最 disruptive 的 Go 升級場景。詳見 `go_major_version_paths.md`。

偵測：apidiff 在 v2+ 路徑下會列大量「removed」（因為新 module 是新 path，舊 path
的所有 symbol 都「不存在」於新 path）。Phase 3 報告要識別這個 noise — 不是真的所有
API 都被刪了，而是 path 換了。

### B. Interface 新增 method（"the X interface now has Y method"）

```go
// 舊版
type Reader interface {
    Read(p []byte) (n int, err error)
}

// 新版
type Reader interface {
    Read(p []byte) (n int, err error)
    Close() error  // 新增！所有實作 Reader 的 type 都需要補 Close
}
```

對 consumer 影響：
- 任何實作了該 interface 的 user struct 不再「滿足」該 interface
- Compile error: `MyReader does not implement Reader (missing Close method)`

`apidiff` 會標為 `Incompatible: interface method added`。Phase 4 AST 掃描要找出
所有實作了該 interface 的 user struct（透過 method set 比對，較複雜，可以暫時 best
effort：grep for type with matching receiver methods）。

### C. Function signature 加 `context.Context`

```go
// 舊版
func (c *Client) Fetch(url string) ([]byte, error)

// 新版（Go 慣例：context 永遠是第一個參數）
func (c *Client) Fetch(ctx context.Context, url string) ([]byte, error)
```

對 consumer 影響：
- 所有呼叫端要加 `ctx`（通常傳 `context.Background()` 或上層傳下來的 ctx）
- 編譯失敗：`not enough arguments in call to c.Fetch`

Phase 4 修法：用 AST 找出所有 `c.Fetch(...)` 的 call site，逐一加 `ctx` 參數。

### D. Error handling: sentinel error → wrapped error

```go
// 舊版
err := pkg.DoSomething()
if err == pkg.ErrNotFound { ... }

// 新版（套件改用 fmt.Errorf("%w", ErrNotFound)）
err := pkg.DoSomething()
if errors.Is(err, pkg.ErrNotFound) { ... }
```

Changelog 通常寫「switched to wrapped errors」或「use `errors.Is`/`errors.As`」。

對 consumer 影響：
- `err == sentinel` 比對失效（false negative）
- 編譯 OK，runtime 行為錯誤
- 這是**隱藏 breaking**，光看 apidiff 看不出來，要靠 changelog + Git diff

### E. Default option / 結構體欄位變更

```go
// 舊版
type Config struct {
    Timeout time.Duration  // 預設零值 = 0 = 無 timeout
}

// 新版
type Config struct {
    Timeout time.Duration
}
// 但 NewClient(c Config) 內部改為：if c.Timeout == 0 { c.Timeout = 30 * time.Second }
```

對 consumer 影響：
- 沒傳 Timeout 的呼叫端，行為突然變成 30s timeout
- 編譯 OK，runtime 行為改變

只能靠 changelog + git diff 找。**`improved default`、`smarter` 這種弱措辭要特別敏感**。

### F. 引入 generics（Go 1.18+）

```go
// 舊版
func Map(s []interface{}, fn func(interface{}) interface{}) []interface{}

// 新版
func Map[T, U any](s []T, fn func(T) U) []U
```

對 consumer 影響：
- 編譯 OK（如果呼叫端原本傳 interface{}），但需要 Go 1.18+
- 呼叫端可能想改用具體型別參數，省掉 type assertion
- **要連帶檢查 `go.mod` 的 `go` directive 是否需要升**

### G. `go` directive / toolchain 要求提升

```
// 舊版 module
go 1.18

// 新版 module
go 1.21
toolchain go1.21.5
```

對 consumer 影響：
- 若使用者本地 Go 版本 < 1.21 → 升完 build 不過
- CI matrix 需要更新

Phase 5 升完要檢查升級套件的 `go.mod` 中的 `go` directive，若高於專案目前要求，
**警告使用者**並建議是否同步升專案的 `go` directive。

### H. 移到 `internal/`

```
// 舊版
example.com/foo/utils    -> exported, 大家都能 import

// 新版
example.com/foo/internal/utils    -> 只有 example.com/foo/* 自己能 import
```

對 consumer 影響：
- import 直接編譯失敗：`use of internal package not allowed`
- 沒有 workaround（除了 vendor 或 fork）

Phase 3 要對比兩版的 package 拓樸（apidiff 會報 `package removed`）。

### I. Build tags 變更

```go
// 舊版檔頭
//go:build linux

// 新版
//go:build linux && cgo
```

對 consumer 影響：
- 在沒啟用 cgo 的環境 build 失敗
- 編譯失敗：`build constraints exclude all Go files`

罕見但會發生。報告中要提一句「升級後此套件需要 cgo」（若偵測到）。

### J. Deprecated → Removed cycle

Go 慣例：先標 `// Deprecated: use NewFoo instead`，等一個 minor cycle 才真的刪。
升 minor 版本時要看：
- 新版有沒有新增 `// Deprecated:` 註解
- 之前已 deprecated 的這次有沒有真的被 remove

`apidiff` 會列出 `removed` 部分；`// Deprecated:` 註解需要從 git diff 抓
（grep `^// Deprecated:`）。

---

## .apidiff 報告對應的 breaking 分類

| apidiff 標籤 | 對 consumer 衝擊 |
|--------------|------------------|
| `Incompatible: removed` | 🔴 編譯失敗 |
| `Incompatible: changed from func(X) to func(Y)` | 🔴 簽名變 |
| `Incompatible: changed from type A to type B` | 🔴 型別不相容 |
| `Incompatible: method added to interface` | 🔴 user implementer 失敗（見 B） |
| `Incompatible: field removed from struct` | 🔴 |
| `Incompatible: field type changed` | 🔴 |
| `Incompatible: const value changed` | 🟡 行為變更，通常 OK |
| `Compatible: ... added` | 🟢 |

---

## 給 LLM 的判斷準則

1. **`apidiff` 報 Incompatible 一律 🔴** — 編譯期就會擋下，所以一定要處理
2. **`// Deprecated:` 註解** 是 🟡 — 短期可用，需排程改
3. **`go` directive 提升** = 工具鏈升級 — Phase 5 提示但不 block
4. **`internal/` 移動** = 🔴，沒 workaround 除非 fork
5. **`context.Context` 新增** 是改造 toil，影響面廣 — 報告要列出所有 call site
6. **Error wrapping 變更** 是隱藏 breaking，**只看 apidiff 抓不到** — 必須對 changelog 警覺
7. **Major version path rewrite** apidiff 會狂報 removed — Phase 3 要識別 noise，不要當成「一切都刪光」
