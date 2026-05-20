# JavaScript / TypeScript Breaking Change Patterns

> 對應 Python 的 `breaking_change_patterns.md`。

## Changelog / Release Notes 措辭

下列措辭強烈暗示 breaking change（同 Python，但 JS 生態多些慣用語）：

| 措辭 | 推測的 breaking change | 信心 |
|------|---------------------|------|
| "drop support for Node X" | runtime 不相容 | 高 |
| "removed deprecated `X`" | export 刪除 | 高 |
| "rename `X` to `Y`" | symbol 重命名 | 高 |
| "now defaults to ES modules" | CJS consumer 可能爆 | 高 |
| "no longer accepts `X` option" | 函式簽名變 | 高 |
| "type `X` is now stricter" | 型別變嚴（TS 編譯失敗） | 中 |
| "promise-only API" / "async by default" | 同步呼叫變非同步 | 高 |
| "improved default behavior" | 預設行為變更（**隱含 breaking**） | 中 |
| "X is now required" | 必填參數 | 高 |
| "moved from `pkg/X` to `pkg-X`" | 套件拆分（deep import 路徑變） | 高 |

---

## .d.ts diff 對應的 breaking 模式

| `api_surface_diff_js.js` 報告類別 | 對 consumer 的衝擊 |
|---------------------------------|------------------|
| `removed` (function) | 🔴 `import { X }` 編譯失敗 |
| `removed` (default) | 🔴 `import X from` 或 `require()` 拿不到東西 |
| `changed` category=`signature_change` | 🔴 參數數/型別/順序變更 |
| `changed` category=`type_change`，但簽名同 | 🟡 TS 型別錯誤，runtime 多半 OK |
| `changed` category=`kind_change`（function → class etc.） | 🔴 |
| `deprecated_new` | 🟡 短期可用 |
| `added` | 🟢 |

---

## JS 特有的 breaking patterns

### A. ESM ↔ CJS 切換

最近期最常見的 breaking — 例如 `node-fetch` 3.x、`chalk` 5.x、`got` 12.x 都改為 pure ESM。
徵兆：
- `package.json` 加了 `"type": "module"` 或移除了 CJS entry
- `exports` field 不再列 `require`
- `main` 改成 `.mjs`

對 consumer 影響：
- CJS consumer (`const X = require('pkg')`) 會直接 `ERR_REQUIRE_ESM`
- 修法：將呼叫端改為 dynamic `await import('pkg')` 或整個專案升級到 ESM

Phase 3 偵測：比對舊新版 `package.json` 的 `type` / `exports` / `main` 欄位。

### B. Default export 變 named export（或反之）

```js
// 0.x
const sliced = require('pkg');  // sliced 是函式

// 1.x — module shape 變了
const { slice } = require('pkg');  // 必須解構
```

Phase 4 修法：找出所有 `require('pkg')` 後的呼叫位置，依新 export 結構改寫。

### C. TS strictness 提升

很常見：`undefined` 從 union 中拿掉、`any` 改 `unknown`、加上 `readonly`。
- Runtime 沒影響
- 但 consumer 的 `tsc` 會失敗
- 報告應分開標「Runtime breaking」與「Type breaking」

### D. Peer dependency range 變更

```json
// 舊版 package.json
"peerDependencies": { "react": ">=16.8" }
// 新版
"peerDependencies": { "react": ">=18.0" }
```

升完新版後 `npm install` 可能整個失敗（peer mismatch），或裝得起來但 runtime 在 react hooks 階段炸。

Phase 3 一定要對比兩版的 `peerDependencies` — 若範圍縮小，**升級門檻變高**，要在報告中列出每個 peer 並建議使用者先升 peer。

### E. Default option 值變更

```js
// 0.x — axios 預設 timeout 是 0 (no timeout)
// 1.x — 沒變，但 paramsSerializer 預設行為換了
```

Changelog 常用「improved」、「smarter」、「now properly handles」這種弱措辭描述，但對既有
程式碼可能是 breaking。

### F. Submodule path 變更

```js
// 0.x
import { Foo } from 'pkg/lib/foo';
// 1.x
import { Foo } from 'pkg/foo';  // 'lib/' 拿掉了
```

Phase 4 偵測：`ast_scanner_js.js` 會記錄 `imports[].module` 含完整路徑，比對 new 版的
`exports` map 即可發現失效的 deep import path。

### G. `engines.node` 收緊

```json
// 舊
"engines": { "node": ">=14" }
// 新
"engines": { "node": ">=20" }
```

如果專案的 CI 用了 16 / 18，升級後 `npm install` 會 warning 但不會 fail（除非有 `engineStrict`）。
要在報告中標：升級後 Node 最低版本變高，請檢查 CI matrix。

---

## 給 LLM 的判斷準則

1. **`.d.ts` removed** 是最硬的訊號 — 一定 🔴
2. **`exports` field 收緊** ＝ deep import 失效 — 🔴
3. **`type: "module"` 加入** ＝ CJS 不能 require — 🔴
4. **TS 型別變嚴格** ＝ 編譯時 breaking，runtime 多半 OK — 🟡
5. **`peerDependencies` 範圍收緊** ＝ 升級前需要先升 peer — 🔴 (block)
6. **Major version bump 但 `.d.ts` diff 空** ＝ 可能只是 runtime 行為變了（很少見但有），加大 Git diff 閱讀深度
