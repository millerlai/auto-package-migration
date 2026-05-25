# JS AST 分析策略（Phase 3 + Phase 4）

> 對應 Python path 沒有的部分 — Python 用 stdlib `ast`，JS 沒有 stdlib parser，
> 而且有 `.d.ts` 這個比原始碼乾淨得多的 public API 來源。

## 三個輸入端

1. **`.d.ts` API surface diff**（最強訊號）
2. **Git diff 過濾 JS/TS 原始碼**
3. **Changelog**（PyPI 對應 npm registry / GitHub Releases）

合併規則同 Python：兩邊 / 三邊都提到 → 信心提高；只有單邊提到 → 標
「未記錄的 breaking change ⚠️」。

---

## 1. `.d.ts` API surface diff

執行：
```bash
node scripts/api_surface_diff_js.js <package> <old_version> <new_version>
```

腳本流程：
1. `npm pack <pkg>@<ver>` 下載兩版 tarball（不裝進 node_modules）
2. 解 tarball，找 `package.json#types` → `package.json#typings` → `exports['.'].types` → 推測 `index.d.ts`
3. 用 `ts-morph` 列 `sourceFile.getExportSymbols()`
4. 對每個 symbol 取 `kind`（function / class / interface / type / const / ...）+ `signature`（type text，超過 600 字截斷）
5. JSDoc `@deprecated` tag → flag
6. Diff 兩份 export map：
   - 只在舊版 → `removed`
   - 只在新版 → `added`
   - 兩版都有但 signature 文字不同 → `changed`（再細分 `signature_change` / `type_change` / `kind_change`）
   - 新版才有 `@deprecated` → `deprecated_new`

### 輸出 JSON

```json
{
  "package_name": "axios",
  "old_version": "0.27.2",
  "new_version": "1.6.0",
  "strategy": "dts",
  "old_strategy": "dts",
  "new_strategy": "dts",
  "confidence_score": 0.85,
  "confidence_basis": "both versions ship .d.ts (gold-standard)",
  "old_source_label": "<temp>/old/extracted/package/index.d.ts",
  "new_source_label": "<temp>/new/extracted/package/index.d.ts",
  "removed": [{"name": "...", "kind": "...", "signature": "..."}],
  "added":   [...],
  "changed": [{"name": "...", "kind": "...", "old_signature": "...", "new_signature": "...", "category": "signature_change"}],
  "deprecated_new": [{"name": "...", "reason": "JSDoc @deprecated added"}],
  "warnings": [],
  "errors": []
}
```

`confidence_score` 是**此單一來源（.d.ts/JS）的 baseline 信心**，Phase 3.3 合併三軌時
以此為起點再上修：

| `old_strategy` / `new_strategy` | baseline | 備註 |
|---|---|---|
| `dts` / `dts` | 0.85 | 與 SKILL.md「只 `.d.ts` 標 removed」基準對齊 |
| `js` / `js` | 0.4 | runtime symbol 列舉，無 type 資訊 |
| `dts` / `js` 或反向 | 0.3 | 版本間 type 缺漏，diff 雜訊高 |
| 任一邊 `none` | 0.0 | 不可採信此軌 |

`errors[]` 非空再 × 0.7，`warnings[]` 非空再 × 0.9。例：`dts/dts` + 1 warning → 0.77。

### LLM 的 Phase 3 任務（讀完輸出後）

對 `removed` / `changed` 進一步分類：
- 🔴 BREAKING — `removed`，`changed` 且 category=`signature_change` / `kind_change`
- 🟡 DEPRECATED — `deprecated_new`，或新版仍有但 doc 改為 deprecated
- 🟢 FEATURE — `added`（不會 breaking，但報告中可一併列出供使用者參考）

並計算信心分數（與 Git diff / Changelog 交叉驗證後上修）。

---

## 2. Git diff 過濾 JS/TS

執行：
```bash
bash scripts/git_diff_js.sh <repo_url> <old_version> <new_version>
```

- Filter: `*.{js,jsx,mjs,cjs,ts,tsx,d.ts}`
- 排除：tests / mocks / fixtures / dist / build / *.min.js
- Tag patterns: `v<ver>` / `<ver>` / `release-<ver>` / `<pkg>@<ver>` (monorepo style)

如果 `.d.ts` API surface diff 已經跑成功，Git diff 主要用來做兩件事：
1. **驗證**：API surface diff 標出來的 `removed` / `changed`，能否在 diff 中找到對應的 source code 變動？
2. **補充**：純行為變更（API 簽名沒變、但內部邏輯換掉）— 這只有 source diff 看得到

如果 `.d.ts` 不存在（純 JS 套件，無 `@types/<pkg>`），Git diff 是主力，LLM 要在 diff 中找：
- `export` / `export default` / `module.exports` / `exports.X = ` 的變動
- 函式 / class 的簽名變更
- 預設參數值變更

---

## 3. Changelog

執行（與 Python 共用）：
```bash
python scripts/fetch_changelog.py <package_name> <git_repo_url>
```

對 npm 套件 `fetch_changelog.py` 仍然管用 — 流程是 PyPI → GitHub Releases → repo CHANGELOG。
PyPI 找不到（這是 JS 套件）會跳過，直接走 GitHub Releases。GitHub Releases 對 JS 生態
覆蓋率很高（大多數套件都用 release-please / semantic-release 自動產 release）。

如果 repo URL 解析不出來（package.json#repository 是空的或非 GitHub），Phase 3
就只剩 .d.ts diff + git diff 雙軌。

---

## 4. 為什麼 `.d.ts` 是 JS path 的關鍵優勢

- Python public API 沒有正式宣告，只能靠 `_` 前綴 / `__all__` / convention 推斷
- TypeScript `.d.ts` 是**官方 public API 宣告**，明確列出每個 export 與簽名
- 一個變更如果出現在 `.d.ts` diff 中 → 幾乎一定是 public API 變更
- 一個變更如果只出現在 source diff 但不在 `.d.ts` diff 中 → 大概率是 internal 變更，不影響 consumer

決策樹（Phase 3 起點）：

```
有 .d.ts?
├─ yes → 跑 api_surface_diff_js.js
│  └─ 有結果? → 主軌走 .d.ts diff，git diff 做交叉驗證
│  └─ 無結果? → fallback 到 git diff 主軌
└─ no  → git diff 主軌；提醒使用者「無 TS 宣告，breaking change 偵測較弱」
```

---

## 5. Phase 4 AST 掃描（usage scanning）

執行：
```bash
node scripts/ast_scanner_js.js <project_path> <package_name>
```

輸出 JSON schema 與 Python `ast_scanner.py` 相同（`scan_results` / `imports` / `usages`），
LLM Phase 4 邏輯可直接重用。

Symbol 命名規則見 `js_workflow.md` 的對照表 — 與 `api_surface_diff_js.js` 用同一套
命名規則，所以兩邊產出的 symbol set 可以直接做集合運算找出 affected usages。

### 常見「假陽性」

- `import type { T } from 'pkg'` 被掃出來，但只用在 type position — Phase 4 應該標為「型別影響」、不算 runtime breaking
- `require.resolve('pkg')` 表示專案需要拿到 module path，但沒呼叫任何 API — 通常 ignore
- Side-effect import `import 'pkg/polyfill'` 不取 symbol，但要確認新版是否還有同名 polyfill entry
