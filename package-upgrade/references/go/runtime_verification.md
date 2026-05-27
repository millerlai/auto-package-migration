# Runtime Verification (Go) — Reference

> Lazy-loaded by `SKILL.md` Step 0.5 (baseline) and Step 6.6 (post-upgrade verify).
> 只在 `language: "go"` 且該模組升級後可能造成 build / link / boot 期破壞時讀。

Go 的型別系統與編譯時檢查比 Python / JS 嚴格，
**`go build ./...` + `go vet ./...` + `go test ./...` 三件套就涵蓋了多數靜態回歸**。
但仍有幾類錯誤要到 runtime 才浮現：

- `init()` order 改變導致全域狀態錯亂
- `embed` / `go:generate` 產出的資源 layout 改變
- `unsafe` / `cgo` ABI 改變
- HTTP / gRPC server 啟動期 reflection 註冊失敗
- DB driver `init()` 註冊失敗（`database/sql` 拿不到 driver）
- CLI flag 介面變更但測試沒涵蓋

Runtime verification 補上這些 gap：升級前抓 baseline，升級後重跑，diff 兩者，
把**新出現的**錯誤歸因為本次升級。

---

## 三層偵測 (tier)

| Tier | 適用 | 內容 | 偵測能力 |
|------|------|------|----------|
| **T1-build** | 任何 Go 模組（最低門檻） | `go build ./...` + `go vet ./...`（皆 exit 0）+ 列出產出 binary 路徑與大小 | API rename / removed、type signature 變、unused import |
| **T1-cli** | 模組有 `main` package 且該 main 是 CLI（讀 `go build -o /tmp/...` 後跑 `--version` / `--help`） | spawn binary with `--version` / `--help`，60 秒 timeout，scan stderr 找 panic / fatal | CLI flag 變更、init panic、依賴包初始化 fail |
| **T2-server** | 偵測到 `main` 啟動了 HTTP / gRPC server（見下表） | T1 + spawn server → 等 ready 訊號 → HTTP/2 探活 → 立即 `SIGTERM` | server 啟動順序問題、port 沒起來、TLS lib 不相容、route registration panic |
| **T3** | fallback | 列印重現指令，請使用者手動驗證 | 仰賴人眼 |

`SKILL.md` 預設一律先跑 T1-build；
有 `main` package 且 build 出 binary < ~50 MB 就加跑 T1-cli；
偵測到 server pattern 就**詢問**使用者是否跑 T2-server（會 bind port、可能 mutate DB）；
其餘退到 T3。

---

## Server 偵測訊號

跑 `grep -rE 'http\.(ListenAndServe|Serve)|net\.Listen|grpc\.NewServer'` 在 `main` package 的目錄。
找到任一就視為「server」：

| Pattern | Server type |
|---------|-------------|
| `http.ListenAndServe` / `http.Serve` | net/http |
| `(*http.Server).ListenAndServe` | net/http with custom server |
| `gin.(*Engine).Run` / `(*gin.Engine).RunTLS` | Gin |
| `echo.(*Echo).Start` | Echo |
| `fiber.(*App).Listen` | Fiber |
| `chi.(*Mux).ServeHTTP` + `http.ListenAndServe` | Chi |
| `grpc.NewServer` + `.Serve(lis)` | gRPC |
| `net.Listen("tcp", ...)` + 自訂 accept loop | raw TCP server |

啟動 port 解析優先序：
1. binary `--port` / `-p` / `-listen` flag（讀 source 中的 `flag.Int` / `flag.String`）
2. env var `PORT` / `LISTEN_ADDR`
3. source 中 hardcoded `:8080` / `:8000`
4. fallback：跑 binary，watch stderr 找 `Listening on :NNNN`

Ready 訊號：
```
Listening on
Server started
Started server at
Ready to accept
gRPC server listening
```

---

## T1-build 細節

```bash
# baseline / post-upgrade 各跑一次，diff 退出碼與 stderr。
go build -o /tmp/_rt_build_check ./... 2>build.log
EXIT=$?
go vet ./... 2>vet.log
VET=$?
```

`go build ./...` 對 multi-package 模組會編譯所有 package，比單純 `go build` 嚴格。
**所有 transitive 編譯誤差會浮現**，包括：

- import 路徑被 rename
- `go:build` tag 變更導致 cross-compile 失敗
- generic type parameter constraint 變更
- 新版套件加 `//go:deprecated`，`go vet` 會 warn

---

## T1-cli 細節

```bash
go build -o /tmp/_rt_cli ./cmd/<bin-name>
timeout 60 /tmp/_rt_cli --version 2>&1
timeout 60 /tmp/_rt_cli --help    2>&1
```

任一非 0 退出碼 → 抓 stderr 最後 30 行進報告。
注意 `--help` 在 cobra-based CLI 應該 exit 0；
若 exit 2（usage error），代表 CLI 介面被 break（例如 flag 移除而舊版預設使用該 flag）。

---

## T2-server 細節

```bash
go build -o /tmp/_rt_srv ./cmd/<server-name>
/tmp/_rt_srv &
SRV_PID=$!
trap "kill $SRV_PID 2>/dev/null" EXIT

# wait for ready (max 30s)
for i in $(seq 1 30); do
    if curl -sf -m 2 http://127.0.0.1:$PORT/healthz >/dev/null 2>&1; then
        echo "READY"
        break
    fi
    sleep 1
done

# Try a couple of probes
curl -sw "\n%{http_code}\n" http://127.0.0.1:$PORT/ | tail -1

kill -TERM $SRV_PID
wait $SRV_PID 2>/dev/null
```

回傳 status code 200/204/404 都視為「server 起來了」（404 因為沒對應 route，但 server 在）。
500 / 503 / `curl: (7)` connection refused 才算 fail。

---

## Edge cases

- **`init()` 副作用**：套件升級可能改變 `init()` 註冊順序，導致 `database/sql.Register()` 兩次而 panic。
  T1-build 不會抓到（編譯期不跑 init），T1-cli 啟動才會炸。
- **CGo**：升級涉及 cgo 套件時，產出 binary 依賴系統 C library 版本；
  baseline 與 post-upgrade 必須在同一機器跑（容器化驗證更穩）。
- **`embed.FS`**：升級後若套件改變嵌入資源的 layout（如 template 路徑），
  build 過但 runtime `tmpl.Lookup("foo")` 回 nil。
- **Vendored module + replace**：`go.mod` 有 `replace` directive 時，
  `go build ./...` 用的是 replace target；要確認 baseline / post-upgrade 都用相同 replace 路徑。
- **`GODEBUG` flag**：Go 1.21+ 引入大量 GODEBUG 預設值變更（如 `httplaxcontentlength=0`）。
  跨 Go runtime 版本升級時，T1-cli / T2-server 必須先 `unset GODEBUG` 跑一次，再加 `GODEBUG=go=1.21,...` 跑一次，比較行為差異。

---

## 報告格式

Phase 7 報告的 `## Runtime Verification` 段落：

```markdown
## Runtime Verification

| Tier      | Cmd                                  | Baseline | Post-upgrade | Diff |
|-----------|--------------------------------------|----------|--------------|------|
| T1-build  | `go build ./...`                     | OK       | OK           | no new warning |
| T1-cli    | `_rt_cli --version`                  | OK       | OK 1.8.0     | (baseline lacked --version, added in new) |
| T2-server | `_rt_srv` + curl `/healthz`          | 200 in 4s | 200 in 4s   | ready time +0s |
| T1-vet    | `go vet ./...`                       | clean    | 1 warning   | new: "printf-style format with non-printf-arg in pkg/x/y.go:42" |
```

新出現的 stderr / panic / vet warning 全文 dump 進報告附錄，原始輸出，不要 paraphrase。

---

## 為什麼有這份文件

`../javascript/runtime_verification.md` 已存在多時，Go track 一直缺對等覆蓋（TODO.md 任務 2.1）。
Go 的 build-time 檢查雖然強，但 `init()` order、`embed` 資源、cgo ABI、server 啟動期
reflection 註冊等仍要 runtime 才會浮現問題；T1-build 不夠，需要 T1-cli / T2-server 補上。
