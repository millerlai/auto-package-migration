# govulncheck Integration

> `govulncheck` 是 Go 官方提供的漏洞掃描工具（`golang.org/x/vuln/cmd/govulncheck`）。
> 它跟 `npm audit` / `pip-audit` 最大差別是：**會做 call graph 分析**，
> 報告漏洞函式是否真的被呼叫到 — 而不只是看 dep tree 是否包含該套件。
> 這是 Go path 相對其他語言的**價值差異化**。

## 安裝

```bash
go install golang.org/x/vuln/cmd/govulncheck@latest
```

需要 Go 1.18+。Preflight 偵測到沒裝時提示這個指令。

---

## 輸出格式（JSON）

```bash
govulncheck -json ./...
```

stdout 是「JSON object stream」（每行一個 object，非陣列）。重要的 entry 類型：

### config
```json
{"config":{"protocol_version":"v1.0.0","scanner_name":"govulncheck",...}}
```

### progress
```json
{"progress":{"message":"Loading packages..."}}
```

### osv（漏洞描述）
```json
{
  "osv": {
    "id": "GO-2024-2611",
    "aliases": ["CVE-2024-24786"],
    "summary": "Infinite loop in protojson.Unmarshal ...",
    "details": "...",
    "affected": [{
      "package": {"name": "google.golang.org/protobuf"},
      "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "1.33.0"}]}]
    }],
    "database_specific": {"url": "https://pkg.go.dev/vuln/GO-2024-2611"}
  }
}
```

### finding（call graph 命中）
```json
{
  "finding": {
    "osv": "GO-2024-2611",
    "fixed_version": "v1.33.0",
    "trace": [
      {"module": "google.golang.org/protobuf", "version": "v1.31.0",
       "package": ".../protojson", "function": "Unmarshal",
       "position": {"filename": "...", "line": 123}},
      {"module": "github.com/myorg/myapp", "version": "",
       "package": "github.com/myorg/myapp/handler", "function": "ParseRequest",
       "position": {"filename": "handler.go", "line": 42}}
    ]
  }
}
```

**trace 的長度與內容是分類關鍵**：
- `trace` 有多個 frame 且最後一個在使用者專案內 → `called`（可達，🔴）
- `trace` 只有單一 frame（在 vulnerable module 內，沒鏈到使用者專案） → `imported`（不可達，🟡）

govulncheck 1.0+ 用 `finding.trace[].function` 是否有 frame 在使用者 module 來區分。
更穩妥的做法：直接看 govulncheck 文字模式輸出的 "Your code is affected by N
vulnerabilities" vs "N other vulnerabilities exist in packages you import"。

---

## 風險分類（Phase 1.B step 3）

`govulncheck_go.sh` 把結果切成三類：

| 分類 | 條件 | 對應 risk |
|------|------|-----------|
| `called` | call graph 走到漏洞函式 | **critical** — 必須升 |
| `imported` | dep tree 含套件，但沒呼叫到漏洞函式 | **medium** — 建議升（防後續 code 改動意外觸發） |
| `not_present` | dep tree 不含此套件 | n/a — 不需處理 |

CVE 來自 Phase 1.B 時，**LLM 風險評估要優先用 govulncheck 結果**，不要再用
`grep -r` 自己判斷 — 後者只看 import 不看 call graph，會把 imported 誤判成 critical。

---

## 報告中如何呈現

Phase 7.1 報告新增一節：

```markdown
### 🛡️ govulncheck 可達性分析

- 掃描指令: `govulncheck -json ./...`
- govulncheck 版本: 1.1.3

#### 🔴 Reachable（call graph 可達）— {N} 個

| OSV ID | CVE | 套件 | 函式 | 修復版本 | 我們的 call site |
|--------|-----|-----|------|---------|-----------------|
| GO-2024-2611 | CVE-2024-24786 | google.golang.org/protobuf | protojson.Unmarshal | v1.33.0 | handler.go:42 |

#### 🟡 Imported but not reachable — {M} 個

| OSV ID | CVE | 套件 | 函式 | 修復版本 |
|--------|-----|-----|------|---------|
| GO-2023-1840 | CVE-2023-39320 | cmd/go | (build-time) | golang 1.21.1 |

> 升此次 PR 後再跑一次 govulncheck，確認 reachable 部分已歸零。
```

---

## 整合到 Phase 1（CVE 觸發場景）

當 Phase 1 是情況 B（使用者提供 CVE）：

```bash
# Step 1: 先跑 govulncheck，看這個 CVE 在本專案是否可達
bash scripts/govulncheck_go.sh <project_path> --cve CVE-2024-24786

# 輸出 JSON
{
  "cve": "CVE-2024-24786",
  "osv_id": "GO-2024-2611",
  "match": "called",   // or "imported" / "not_present"
  "affected_modules": ["google.golang.org/protobuf"],
  "call_sites": [{"file": "handler.go", "line": 42, "function": "handler.ParseRequest"}],
  "fixed_in": "v1.33.0"
}
```

LLM 看到 `match: "called"` → 走 critical 流程，直接進 Phase 2。
LLM 看到 `match: "imported"` → 告知使用者「漏洞存在但 call graph 不可達，仍建議升以防後續 code 改動」，問是否繼續。
LLM 看到 `match: "not_present"` → 告知「此 CVE 不影響本專案」，問是否要強制升（可能是合規要求）。

---

## 整合到 Phase 6（測試後驗證）

升完後再跑一次 govulncheck，確認該 CVE 已不再 reachable：

```bash
bash scripts/govulncheck_go.sh <project_path> --cve CVE-2024-24786 --post-upgrade
```

期望輸出：`match: "not_present"`（漏洞版本已不在 dep tree）。

若仍出現：
- transitive 路徑還有舊版本 → `go mod why <pkg>` 找出來，可能需要升 parent
- 升級沒生效（go.sum 衝突等） → 回 Phase 5 排查

---

## 限制

1. **govulncheck 只認 Go vulnerability database (OSV)** — 自定義 CVE / BDSA 要先用
   `../common/bdsa_mapping.md` 流程轉成 GO-ID 或對應的 CVE
2. **Call graph 是靜態分析** — 動態 reflection / plugin 走不到的部分可能漏報
3. **build tags 影響** — 預設只掃 default build，要其他 OS / 環境要設定 `GOOS=...`
4. **vendor mode** — govulncheck 支援，但需要 vendor 是最新的（先 `go mod vendor`）
5. **私有 module** — 需要先設定好 GOPROXY / GOPRIVATE，不然 govulncheck 拿不到 mod info
