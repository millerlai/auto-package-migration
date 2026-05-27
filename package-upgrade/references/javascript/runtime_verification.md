# Runtime Verification (JS / TS) — Reference

> Lazy-loaded by `SKILL.md` Step 0.5 (baseline) and Step 6.6 (post-upgrade verify).
> 只在 `language: "javascript"` 且偵測到 web app 時讀。

Phase 6 的單元測試 (`run_tests_js.sh`) 只驗證了「程式碼能編譯、模組能 import、unit
test 行為符合預期」。**type-check 過了、jest 過了，但 `npm run dev` 一啟動就 white
screen** 是 JS 升級最常見的回歸 — peer dep 不相容、ESM/CJS 切換、entry chunk 載入
失敗、framework runtime 改版等錯誤要到實際啟動才會浮現。

Runtime verification 補上這個 gap：升級前抓 baseline、升級後重跑、diff 兩者，把
**新出現的**錯誤歸因為本次升級造成。

---

## 三層偵測 (tier)

| Tier | 內容 | 依賴 | 偵測能力 |
|------|------|------|----------|
| **T1** (預設) | spawn dev server → 等 ready 訊號 → scan stderr/stdout → HTTP GET `/` 檢查 status + body 非空 | 無 (純 Node + http) | 套件 import 失敗、編譯失敗、port 沒起來、SSR 500 |
| **T2** (opt-in) | T1 + Playwright headless 開頁 → 收 console errors / pageerror / requestfailed + 截圖 + DOM node 計數 | `playwright` + chromium (~150MB) | React/Vue runtime error、缺失元件、CSP 報錯、CDN 404、white screen |
| **T3** (fallback) | 列印 URL，請使用者用自己的瀏覽器手動確認，記錄 pass/fail/skip | 無 | 仰賴人眼 |

`SKILL.md` 預設先跑 T1；T1 通過後**詢問**使用者是否額外跑 T2 (告知 +150MB +1~2 分鐘下載 chromium)；
拒絕 T2 → 退到 T3 給使用者一個 manual checkpoint。

---

## Web app 偵測訊號

Step 0.5 在問使用者前，先用以下訊號自動判斷「這個專案是不是 web portal」：

**依賴特徵** (檢查 `package.json#dependencies` + `devDependencies`)：

| 出現任一就視為 web app | Framework |
|------------------------|-----------|
| `next` | Next.js |
| `vite` | Vite (含 vue/svelte/react template) |
| `react-scripts` | Create React App |
| `@vue/cli-service` / `vue-cli-service` | Vue CLI |
| `@angular/cli` / `@angular/core` | Angular |
| `nuxt` / `nuxt3` | Nuxt |
| `@sveltejs/kit` | SvelteKit |
| `@remix-run/dev` | Remix |
| `astro` | Astro |
| `gatsby` | Gatsby |
| `webpack-dev-server` | Webpack dev server |
| `parcel` | Parcel |
| `@nestjs/core` + `@nestjs/platform-express` | NestJS web |
| `express` / `fastify` / `koa` / `hapi` (+ 有 `scripts.dev` 或 `scripts.start`) | 一般 Node web server |

**Script 特徵** (`package.json#scripts`)：

依優先順序選 dev 啟動指令：`dev` → `start` → `serve` → `start:dev` → `dev:server`。
若皆無，視為「非 web app」(library / CLI tool)。

**輸出結構** (給 Phase 0.5 LLM 判讀的 mental model)：

```json
{
  "is_web_app": true,
  "frameworks": ["next"],
  "candidate_start_scripts": [
    { "script": "dev",   "cmd": "next dev",       "guessed_port": 3000, "guessed_url": "http://localhost:3000" },
    { "script": "start", "cmd": "next start",     "guessed_port": 3000, "guessed_url": "http://localhost:3000" }
  ]
}
```

> **注意**：偵測訊號只是 hint。最後一定**問使用者確認**，因為：
> - monorepo 可能在多個 workspace 都有 dev server，需要指定要驗證哪個
> - 同一 dev script 可能需要先跑 `pnpm install --filter ./packages/foo` 等前置
> - 有些專案需要 `.env.local` / `.env.development` 才跑得起來

---

## Framework defaults

啟動指令裡找不到 `--port` / `-p` flag 時的 fallback port：

| Framework      | Default port | Default ready pattern |
|----------------|--------------|------------------------|
| Next.js        | 3000         | `ready - started server on` (≤12) / `ready started server on` (≥13) |
| Vite           | 5173         | `Local:` |
| CRA            | 3000         | `Compiled successfully` |
| Vue CLI        | 8080         | `App running at:` |
| Angular CLI    | 4200         | `Compiled successfully` / `Listening on:` |
| Nuxt 3         | 3000         | `Listening on http` |
| SvelteKit (dev)| 5173         | `Local:` |
| Astro          | 4321         | `Local` / `started in` |
| webpack-dev-server | 8080     | `webpack <ver> compiled` |
| NestJS         | 3000         | `Nest application successfully started` |

`runtime_verify_js.js` 的 `READY_PATTERNS` 涵蓋上表所有 pattern 的 case-insensitive
regex 形式。新增 framework 時記得補。

---

## Edge cases

### 環境變數
- 偵測 `.env`、`.env.local`、`.env.development` 是否存在。若 dev script 需要但檔案
  不存在 → Phase 0.5 不要硬跑 baseline，先警告使用者「server 可能因缺 env 失敗」並
  詢問是否要：[1] 提供 env 後重跑 baseline [2] 仍跑 baseline (預期會 fail，但留作對照組)
  [3] 跳過 runtime verification
- **不要**把使用者填入的 env value 寫進 cache 或 log；只 export 進 spawn 出的子行程環境

### Port conflict
- Spawn 後若立即在 stderr/stdout 抓到 `EADDRINUSE` → `boot_status = "port_conflict"`
- LLM 應提示使用者：先 kill 掉佔用該 port 的舊行程，或改用 `--port <free>` 重跑
- **不要**自動換 port — 使用者可能正在用該 port 開另一個 service，靜默改 port 會混淆

### 需要先 build
- Next.js production: `next start` 需先跑 `next build`。Phase 0.5 偵測到 `scripts.start`
  含 `next start` / `nuxt start` 等時，要在啟動前詢問是否已有 build artefact，或提議
  改用 `scripts.dev`
- 若使用者堅持用 production 啟動指令，LLM 要在 Phase 0.5 baseline 前先 `npm run build`，
  並把 build 失敗也視為 runtime regression 的一部分

### Monorepo
- `is_workspace: true` 時，Phase 0.5 需詢問使用者：要驗證 root 還是某個 workspace？
  通常只有 leaf app workspace 才有 dev server
- 對選定的 workspace 用 `npm --workspace <name> run dev` / `yarn workspace <name> dev` /
  `pnpm --filter <name> dev` 啟動

### SSR / SSG 框架的 hydration error
- Next.js / Nuxt 等的 hydration mismatch 只會在 browser console 顯示，T1 (純 HTTP probe)
  抓不到 — 這是 T2 (Playwright) 主要的補強場景
- T1 給 `http_status: 200` 但實際 React error boundary fallback 已 render，使用者會
  看到「Application error」黃條 — 這就是 T2 該攔下的

### Cookie / 登入頁
- 有些 portal `/` 直接 302 跳轉到 SSO，HTTP probe 看到 302 是**正常**而非 regression
- T1 `http_status` 接受 200/2xx/3xx 為 ok；4xx/5xx 才視為 fail
- T2 跟著重導後若停在 SSO 登入頁，會看到正常的 login form — DOM node 數 > 0、無
  console error → 視為 pass

---

## Output JSON schema

```json
{
  "mode": "baseline" | "verify",
  "tier": "t1" | "t2",
  "start_cmd": "npm run dev",
  "url": "http://localhost:3000",
  "boot_status": "ready" | "timeout" | "crashed" | "port_conflict" | "spawn_error",
  "ready_time_ms": 12345,
  "ready_pattern_matched": "Local:\\s+https?:\\/\\/",
  "stderr_errors": [
    { "line": 42, "text": "Error: Cannot find module 'foo'", "type": "module_not_found" }
  ],
  "stderr_warning_count": 5,
  "http_status": 200,
  "http_body_size": 12345,
  "http_error": "",
  "console_errors": [{ "type": "error", "text": "..." }],   // T2 only
  "failed_requests": [{ "url": "...", "reason": "net::ERR_BLOCKED_BY_CLIENT" }], // T2 only
  "dom_node_count": 1234,                                   // T2 only
  "screenshot_path": ".package-upgrade-cache/screenshot-baseline.png", // T2 only
  "t2_status": "ok" | "playwright_not_installed" | "skipped",
  "log_path": ".package-upgrade-cache/runtime-baseline.log"
}
```

寫到 `<project>/.package-upgrade-cache/runtime-{baseline,post}.json`。
腳本會自動把 `.package-upgrade-cache/` 加進 `.gitignore` (若尚未存在)。

---

## Diff 策略 (Phase 6.6 LLM 判讀)

**不要**對 log 做 raw text diff — dev server 每次啟動的 timestamp / 隨機 hash 都
不同，會被噪音淹沒。改採欄位級分類比對：

### Bucket 1: 新出現的 stderr error 類型
- 條件：`post.stderr_errors[].type` 出現某個 type，但 baseline 沒有
- 動作：對該 type 全部條目列出 → 對照 Phase 3 breaking changes → 判定根因
- 範例：baseline 有 0 條 `module_not_found`、post 有 3 條 → 升級造成 import 解析失敗，
  非常可能是 entry / export shape 變了 (對應 Phase 3 `removed_export` 或 `package_split`)

### Bucket 2: stderr error 數量級回歸
- 條件：同類型的 error 數量 post / baseline > 3x 且絕對增量 ≥ 5
- 動作：列出新增的 5 筆典型 → 通常是 deprecation 變 error / log level 改變

### Bucket 3: boot_status 退化
| Baseline      | Post              | 判定 |
|---------------|-------------------|------|
| `ready`       | `ready`           | 通過 |
| `ready`       | `timeout`         | regression — 升級後啟動變慢或卡住 |
| `ready`       | `crashed`         | regression — 致命錯誤，必修 |
| `ready`       | `port_conflict`   | env 問題，跟升級無關，請使用者處理 |
| `crashed`     | `ready`           | 升級**修好**了既有問題 — 在報告裡標 ✅ |
| `crashed`     | `crashed`         | 升級沒影響 (但 baseline 本身就壞，記得在報告提醒) |

### Bucket 4: HTTP regression
- `baseline.http_status` 2xx/3xx + `post.http_status` 4xx/5xx → regression
- `baseline.http_status` 2xx + `post.http_status` 2xx + body size 變化 > 50% → 警告
  (可能 main bundle 沒打進去 / 重定向到錯誤頁)

### Bucket 5: T2 console errors (僅 tier=t2 時)
- 新出現的 `console_errors[].text` (用 normalized text，去掉 URL 裡的 hash 後比對)
- `pageerror` 一律視為 regression (uncaught exception)
- `failed_requests` 新增 → 列出 URL；常見是 chunk 載入失敗 / CDN 404

### Bucket 6: T2 render broken (僅 tier=t2 時)
- `post.dom_node_count < 10` 且 baseline ≥ 50 → white screen，極可能 React error boundary
  接管了整頁 render
- 或 `post.dom_node_count < baseline.dom_node_count * 0.1` → 主內容沒 render

---

## 限制 & 已知問題

- **HTTPS dev server**：腳本傳 `rejectUnauthorized: false`，可接受 self-signed cert，
  但若 cert chain 完全壞掉仍會 error
- **WebSocket-only health**：少數框架 (e.g. 部分 dev mode) 的 `/` 是 200 但實際內容透過
  WS 推送 — T1 抓不到問題，需用 T2
- **Hot-reload 拉長 ready 時間**：第一次 cold start 通常 > warm start。Baseline 跑兩次
  取較長者，或設較寬的 timeout (預設 60s)
- **Windows**：`taskkill /T /F` 在 npm-via-cmd.exe 啟動的子樹通常 work，但若 dev
  script 中再啟動 detached background process (少見) 可能殺不乾淨。使用者按 Ctrl+C
  幾次即可
- **不適用**：library / CLI tool / 純後端 worker / cron job — 這些沒有 HTTP endpoint，
  Step 0.5 偵測到沒有 web framework dep 會自動跳過
