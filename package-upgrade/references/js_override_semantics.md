# JS Override Semantics — npm / yarn / pnpm / bun 的 transitive pin

> 這份文件統整 JS 四套套件管理工具強制升降 transitive dependency 的語法。
> Phase 2 在挑選策略 `bump_override` 時應引用本檔。對應 Python 的
> `python_override_semantics.md`、Go 的 `go_replace_semantics.md`。

---

## 為什麼需要 override

Phase 2 dep_tree 把 target 標為 `transitive`，且 parent 不肯升或 parent 升上去後其他
chain 會破。此時要在 root `package.json` 加 override，**強制** transitive 升到安全版，
而不改 direct dep 宣告。

JS 生態 4 套工具的語法各不相同——npm 用 `overrides`、yarn 1/3+ 用 `resolutions`、
pnpm 用 `pnpm.overrides`、bun 用 `overrides`（與 npm 相容）。本文件統一收錄。

每個 override 都要在 commit message 註記 expected removal condition——
parent 之後正式升上去後忘了拿掉 override，會 silently holding back 預期的版本。

---

## npm — `overrides`

npm 8+ 支援 `package.json`：

```json
{
  "name": "my-app",
  "version": "1.0.0",
  "dependencies": {
    "axios": "^1.5.0"
  },
  "overrides": {
    "form-data": "4.0.4"
  }
}
```

語意：solver 解析時看到 `form-data` 一律 clamp 到 4.0.4，無論是哪條 require 鏈拉進來的。

### 巢狀 override（只限定特定 parent 鏈）

```json
{
  "overrides": {
    "axios": {
      "form-data": "4.0.4"
    }
  }
}
```

語意：只在 `form-data` 是被 `axios` 拉進來時 pin 到 4.0.4；其他 parent 拉進來的不受影響。
適合「`form-data` 4.0.4 修了 CVE，但只在 axios 的版本範圍下才安全」場景。

### 自我參照（pin 到 dep 自身宣告的版本）

```json
{
  "dependencies": {
    "axios": "^1.5.0"
  },
  "overrides": {
    "axios": "$axios"
  }
}
```

`$axios` 是 npm 特定語法，意思是「使用 dependencies 中 axios 的宣告版本」。
這在 monorepo 強制 workspace 各 package 都用同版本 axios 時有用。

---

## yarn 1 (classic) — `resolutions`

yarn 1 用 `resolutions`：

```json
{
  "resolutions": {
    "form-data": "4.0.4",
    "**/form-data": "4.0.4"
  }
}
```

- `"form-data": "4.0.4"` — 任何位置的 form-data 都用 4.0.4
- `"**/form-data": "4.0.4"` — glob pattern，多了一層 wildcard match
- `"axios/form-data": "4.0.4"` — 只在 axios 的 sub-dep 才 pin

yarn 1 的 glob 比 npm overrides 強，但**只在 yarn 1 環境下生效**——若 CI 用 npm install
跑 yarn 1 的 `package.json`，`resolutions` 會被 npm 忽略。

---

## yarn 3+ (berry) — `resolutions`（同名語法但實作不同）

yarn 3+ 也用 `resolutions`，語法與 yarn 1 相容，但實作改用 PnP 或 `node-modules` linker：

```json
{
  "resolutions": {
    "form-data": "4.0.4"
  }
}
```

yarn 3+ 的差異：
- 採 deterministic resolution，跨平台 `yarn.lock` 一致性更高
- 若有 `pnp.cjs` 模式，override 影響 PnP `.zip` 解析
- 配合 `.yarnrc.yml` 的 `packageExtensions` 可以同時 inject 缺失的 peer dep

```yaml
# .yarnrc.yml
packageExtensions:
  axios@^1.5.0:
    peerDependencies:
      form-data: "4.0.4"
```

`packageExtensions` 不是 override 而是「為 package 補 peer 宣告」，常與 `resolutions`
配合處理「parent 沒宣告 peer 但 runtime 需要」的情境。

---

## pnpm — `pnpm.overrides`

pnpm 用獨立的 `pnpm` 區塊：

```json
{
  "pnpm": {
    "overrides": {
      "form-data": "4.0.4"
    }
  }
}
```

語法與 npm `overrides` 高度相似，包括巢狀與 `$pkg-name` 自我參照：

```json
{
  "pnpm": {
    "overrides": {
      "axios>form-data": "4.0.4",
      "react": "$react"
    }
  }
}
```

注意 pnpm 用 `>` 分隔 parent 與 child（npm 用巢狀 object）。
`axios>form-data` 等同 npm 的 `{"axios": {"form-data": "..."}}`。

### pnpm patches（與 override 互補）

pnpm 還支援 `patchedDependencies` 直接打 patch：

```json
{
  "pnpm": {
    "patchedDependencies": {
      "form-data@4.0.3": "patches/form-data@4.0.3.patch"
    }
  }
}
```

用於：套件官方還沒釋出 fix，先用本地 patch 擋。對應 Go 的 `replace`、
Python 的 `[tool.uv.sources]` git+。

---

## bun — `overrides`（npm 相容）

bun 採 npm 相同語法：

```json
{
  "overrides": {
    "form-data": "4.0.4"
  }
}
```

bun 不支援 `resolutions`（yarn 語法）。若專案歷史是 yarn 移植到 bun，需要把
`resolutions` 改名為 `overrides`。

---

## 對應策略表

| pkg_manager | 語法 | 巢狀支援 | 適用 SKILL.md 策略 |
|-------------|------|----------|---------------------|
| npm | `overrides: {...}` | object | `bump_override` |
| yarn 1 | `resolutions: {...}` | glob (`**/`) | `bump_override` |
| yarn 3+ | `resolutions: {...}` + `.yarnrc.yml packageExtensions` | glob (`**/`) | `bump_override` |
| pnpm | `pnpm.overrides: {...}` | `parent>child` | `bump_override` |
| pnpm + patch | `pnpm.patchedDependencies` | path 對版本 | `add_patch_override`（新策略） |
| bun | `overrides: {...}` | object | `bump_override` |

---

## 偵測欄位（detect_env_js.sh 應補的 hint）

| 檔案 / 段落 | hint |
|-------------|------|
| `package.json#overrides` 非空 | `has_npm_overrides` |
| `package.json#resolutions` 非空 | `has_yarn_resolutions` |
| `package.json#pnpm.overrides` 非空 | `has_pnpm_overrides` |
| `package.json#pnpm.patchedDependencies` 非空 | `has_pnpm_patches` |
| `.yarnrc.yml` 含 `packageExtensions:` | `has_yarn_package_extensions` |

這些 hint 讓 Phase 2 策略選擇有依據——當專案已經有 override 機制，bump_override 是
零成本選擇；若還沒有，要新加 override 並更新報告與 commit message。

---

## 常見陷阱

1. **混用 `overrides` 與 `resolutions`**：
   同一個 repo 從 yarn 移植到 npm 後若沒清掉 `resolutions`，npm 會 silently 忽略它。
   每次升級前 grep `package.json` 確認用對 key。

2. **巢狀 override 不能 fall through**：
   ```json
   {"overrides": {"axios": {"form-data": "4.0.4"}}}
   ```
   只在 form-data 是 axios 的直接 dep 時生效；如果 `axios → @1 → @2 → form-data`
   中間多了 wrapper，這個 override 不生效。要用 `"axios": {"**": {"form-data": "..."}}`
   （npm 9+）或扁平 override `{"form-data": "..."}`。

3. **yarn 1 `**/x` 比 yarn 3+ `**/x` 行為不同**：
   yarn 3+ 對 glob 解析更嚴格，某些 yarn 1 expression 在 3+ 失效。升級 yarn 主版本時
   需要 dry-run 確認 `resolutions` 仍生效。

4. **pnpm `patchedDependencies` 路徑相對於 `package.json`**：
   monorepo 中若把 patch 從 root 移到 workspace package，patch 路徑要連帶改，
   否則 silently 不應用 patch。

5. **`$pkg-name` 自我參照只支援 direct dep**：
   `"overrides": {"react": "$react"}` 必須要 `dependencies.react` 也存在；
   若 react 是 peer dep（不在 dependencies / devDependencies）就會 resolve fail。

---

## 為什麼有這份文件

Go 有 `go_replace_semantics.md`、Python 有 `python_override_semantics.md` 統整 override
語意，JS 對應知識散落在 `npm_workflow.md` / `yarn_workflow.md`，使用者要在兩個檔案間跳，
且 pnpm / bun 沒有專屬 workflow.md 涵蓋這塊。本文件統整四套工具的 override 寫法
（TODO.md 任務 2.2），是 Phase 2 `bump_override` 策略的單一參考來源。
