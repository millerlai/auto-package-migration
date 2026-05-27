# JavaScript / TypeScript Workflow

> Phase 0 偵測到 `language: "javascript"` 時，整個流程改走這份文件 +
> `npm_workflow.md` / (未來) `yarn_workflow.md` 等。

## 觸發後讀什麼

| 套件管理工具 | reference |
|--------------|-----------|
| npm          | `references/npm_workflow.md` |
| yarn (含 yarn 3 Berry) | `references/yarn_workflow.md` |
| pnpm         | `references/pnpm_workflow.md` |
| bun          | (後續 stage 尚未支援；`bun.lock` 為二進位格式，dep_tree 無法 robust 解析) |

JS path **必讀** `references/js_ast_strategy.md` 與
`references/breaking_change_patterns_js.md`。

---

## Phase 對應

| Phase | Helper | 與 Python path 的差異 |
|-------|--------|----------------------|
| 0 環境偵測 | `scripts/detect_env_js.sh` | 輸出含 `language`, `pkg_manager`, `has_typescript`, `is_workspace`, `test_framework_hint` |
| 1 輸入解析 | （無 JS 專屬） | Jira / CVE 流程完全沿用 |
| 2 依賴分析 | `scripts/dep_tree_js.js` | 多一個 `is_peer` flag 與 `peer` dependency_type |
| 3 Breaking change | `scripts/api_surface_diff_js.js` + `scripts/git_diff_js.sh` + `scripts/fetch_changelog.py` | **三軌**：`.d.ts` API surface diff (新增) + Git diff 過濾 `*.{js,ts,jsx,tsx,d.ts}` + Changelog |
| 4 程式碼影響 | `scripts/ast_scanner_js.js` | 使用 `@babel/parser` + `@babel/traverse`；symbol 命名規則見下方 |
| 5 執行升級 | `npm install <pkg>@<ver>` / `npm install <pkg>@<ver> --save-peer` | `npm install` 會自動寫回 `package.json` 與 `package-lock.json` — 與 pip 不同；**預設加 `--ignore-scripts`** |
| 0.5 Runtime baseline (optional) | `scripts/runtime_verify_js.js --mode baseline` | **JS 專屬**；偵測 web app → 升前抓 dev server boot + HTTP probe + (T2) console errors，作為 Step 6.6 的對照組。詳見 `references/runtime_verification_js.md`。 |
| 6 測試 | `scripts/run_tests_js.sh` | Auto-detect jest / vitest / mocha / node:test |
| 6.6 Runtime verify (僅 0.5 抓了 baseline) | `scripts/runtime_verify_js.js --mode verify` | 重跑同一指令，diff baseline → 標出新出現的 stderr / console / HTTP / render regression |
| 7 報告 / commit / PR / Jira | 沿用既有模板 | Report 多一節：**API Surface Diff 來源**；若跑了 0.5/6.6 再多一節 **Runtime Verification** |

---

## Symbol 命名規則（重要 — Phase 4 與 Phase 3 串接）

`ast_scanner_js.js` 把專案內的 usage normalize 成
`<package>.<symbol>[.<member>...]`，規則：

| 你寫的 code | 記錄的 symbol |
|------------|--------------|
| `import x from 'axios'` + `x.get(...)` | `axios.default.get` |
| `import { create } from 'axios'` + `create()` | `axios.create` |
| `import * as ax from 'axios'` + `ax.foo.bar` | `axios.foo.bar` |
| `const x = require('axios')` + `x.post(...)` | `axios.default.post` |
| `const { get } = require('axios')` + `get(...)` | `axios.get` |
| `await import('axios')` + `mod.default.get` | `axios.default.get` |
| `import type { T } from 'axios'` | (記錄為 `esm_type_only`，不算 runtime usage) |

`api_surface_diff_js.js` 列 export 時用同一份命名規則 — `default` 就叫
`default`，named export 用原名 — 所以兩邊的 symbol set 可以直接做集合運算。

---

## 升級命令 (Phase 5)

### npm — 直接依賴

```bash
# 預設加 --ignore-scripts，避免升級時跑 postinstall lifecycle
npm install <package>@<version> --save --ignore-scripts

# devDependencies
npm install <package>@<version> --save-dev --ignore-scripts

# peerDependencies (需要 npm >= 7)
npm install <package>@<version> --save-peer --ignore-scripts
```

`npm install` 會自動更新 `package.json` + `package-lock.json`。

### npm — Transitive lock-only（對應 Phase 2 B-3）

```bash
# 只更新 lock，不動 package.json
npm update <package> --depth Infinity --ignore-scripts
```

實作上 `npm update` 會走最高匹配 semver；如果需要強制升到 lock-only 路徑做不到的版本，得回到 Phase 2 B-4 詢問是否升級 parent。

### `@types/<pkg>` 同步升級

若 `package.json` 同時存在 `<pkg>` 和 `@types/<pkg>`：
- 升級主套件後，**主動建議**也升級 `@types/<pkg>`（可能有同步的型別變更）
- 在 Phase 4 預覽時把 `@types/<pkg>` 列為「相關套件」一併處理

### Lifecycle scripts 警告

`npm install` 預設會跑 `preinstall` / `install` / `postinstall` / `prepare`。
**Phase 5 預設都加 `--ignore-scripts`**，並在報告中註明：

> ⚠️ 升級時加了 `--ignore-scripts` 跳過套件的 lifecycle script。如果該
> 套件需要 postinstall 才能正常運作（例如 `esbuild`、`sharp`、`puppeteer`），
> 請手動執行 `npm rebuild <pkg>` 並驗證。

---

## 測試 (Phase 6)

`scripts/run_tests_js.sh` 偵測順序：
1. `node_modules/.bin/vitest` → vitest
2. `node_modules/.bin/jest` → jest
3. `node_modules/.bin/mocha` → mocha
4. fallback：用 `<pkg_manager> test` 跑 `scripts.test`

分層測試（`--files`）：
- jest: `--findRelatedTests <files>`
- vitest: `vitest related --run <files>`
- mocha: 直接傳 file path
- node:test / 未知框架：跳過分層、只跑 `--all`

`scripts/run_tests_js.sh` 輸出的 JSON 與 Python `run_tests.sh` 完全相同（`passed` / `failed` / `exit_code` / `traceback`），Phase 6 三向診斷邏輯可直接重用。

---

## peerDependency 處理（JS 特有，對應 Phase 2 新分支）

當 `dep_tree_js.js` 輸出 `is_peer: true` 時：
- `peerDependencies` 是「我這個套件需要 consumer 自己裝 X」的宣告
- 升級它不會像 dependencies 那樣有「被誰拉進來」的問題
- 但要檢查：是否有其他 dependency 也宣告了對這個 peer 的不同範圍？
- 處理流程：和 Phase 2 Type A 一樣（直接升），但在報告中標 `(peer)`

---

## 不在 MVP 範圍

下列功能後續 stage 才加，遇到時暫停並告知使用者：
- bun 套件管理工具（`bun.lock` / `bun.lockb` 為二進位格式，需 bun runtime 才能 robust 解析）
- Codemod discovery（react-codemod, @next/codemod, ...）
- Bun runtime 專屬 API 的 breaking change
