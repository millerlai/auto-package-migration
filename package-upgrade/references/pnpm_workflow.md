# pnpm Workflow

> 對應 `npm_workflow.md` / `yarn_workflow.md`。pnpm 的 lockfile 與 hoisting model
> 與另外兩套差很多 — content-addressable global store + project-local symlink
> tree，每個 dep 在 disk 上只存一份，`node_modules/` 是 symlink farm。

## 重要前置條件 (preflight.sh 已偵測)

| 條件 | 來源 | 影響 |
|------|------|------|
| `pkg_manager_bin` 不空 | corepack-managed pnpm 或 PATH | 沒有就無法跑任何 pnpm 命令 — preflight 會 block |
| `pkg_manager` == `pnpm` | `detect_env_js.sh` 看到 `pnpm-lock.yaml` | 後續所有 phase 走 pnpm 分支 |
| 自訂 registry token (例 `JFROG_TOKEN`) 已設定 | `.npmrc` / `.pnpmfile.cjs` 解析 | 沒有 → `pnpm install` 會 `ERR_PNPM_REGISTRIES_MISMATCH` 或 401 |
| pnpm 版本 ≥ 7 | `pnpm --version` | 低於 7 的 lockfile (v5.x) 本 skill 不保證能 parse — 建議先 `pnpm install` 重生 lockfile |

**所有命令呼叫一律用 `$PKG_MANAGER_BIN`**，不要 hardcode `pnpm`：

```bash
$PKG_MANAGER_BIN install --frozen-lockfile
$PKG_MANAGER_BIN up <pkg>@<range>
$PKG_MANAGER_BIN why <pkg>
```

corepack-managed pnpm 通常會在 PATH 中（不像 yarn 3 那樣藏在 `.yarn/releases/`），
但 monorepo 內若 `packageManager: "pnpm@x.y.z"` 不一致仍可能踩雷 — 一律走
`pkg_manager_bin`。

---

## 升級命令 (Phase 5) — 與 npm / yarn 對照

### 升級「直接依賴」(`dependencies`)

```bash
# 升級到指定版本 — 預設更新 package.json + lockfile
$PKG_MANAGER_BIN add <pkg>@<version>

# 升級 dev dependency
$PKG_MANAGER_BIN add -D <pkg>@<version>

# 升級 peer dependency
$PKG_MANAGER_BIN add --save-peer <pkg>@<version>

# 升級到指定 range（不釘 exact，沿用 package.json 既有 caret/tilde 風格）
$PKG_MANAGER_BIN up <pkg>@<range>
```

`pnpm add` vs `pnpm up`：

- `pnpm add <pkg>@<ver>` 永遠覆寫 `package.json` 對應欄位的版本字串（行為等同 `npm install --save`）
- `pnpm up <pkg>@<range>` 只在 range 落在現有 constraint 內時更新；若新 range 跨過原 caret/tilde 就只升 lockfile 不動 manifest
- **Phase 5 預設用 `pnpm add`**，因為要寫入 source of truth

### Transitive 升級策略（按 `dep_tree_js.js` 的優先序執行）

`dep_tree_js.js` 對每個 transitive target 會輸出 `upgrade_strategies[]`，
按以下順序選擇對應命令：

#### 1. `direct_bump` — target 在 package.json `dependencies`/`devDependencies`/`peerDependencies`

```bash
$PKG_MANAGER_BIN add <pkg>@<version>
```

#### 2. `bump_override` — target 在 `pnpm.overrides` 已被釘版

直接編輯 `package.json` 把對應 entry 的 value 改成新版本：

```jsonc
{
  "pnpm": {
    "overrides": {
      "<pkg>": "<new-version>"
    }
  }
}
```

然後：
```bash
$PKG_MANAGER_BIN install --lockfile-only
```

`--lockfile-only` 只重算 lockfile（對應 npm `--package-lock-only`），不會碰
`node_modules/`。Phase 5.4 的 offline 驗證仍會跑完整 install 確認 store 一致。

#### 3. `bump_parent` — **預設推薦** 給沒有 override 的 transitive package

```bash
$PKG_MANAGER_BIN add <direct-parent>@<new-range>
```

升完 parent 後，pnpm 會把新版的 target 一併解析寫入 lockfile。Phase 6 跑足測試
確認 parent 的新版本沒帶來其他 breaking。

#### 4. `add_override` — `bump_parent` 不適用 / 不夠精確時

在 `package.json` 加 `pnpm.overrides`（注意是 nested 在 `pnpm:` 區塊下）：

```jsonc
{
  "pnpm": {
    "overrides": {
      "<pkg>": "<new-version>"
    }
  }
}
```

`pnpm.overrides` 也支援限定 parent 鏈的 `parent>child` 語法（不是 npm 的 nested object）：

```jsonc
{
  "pnpm": {
    "overrides": {
      "axios>form-data": "4.0.4"
    }
  }
}
```

語意：只在 `form-data` 是被 `axios` 拉進來時 pin 到 4.0.4 — 詳見
[js_override_semantics.md](js_override_semantics.md)。

```bash
$PKG_MANAGER_BIN install --lockfile-only
```

> **與 `bump_parent` 的取捨**：`add_override` 一定生效但繞過 parent 的相容性
> 測試；`bump_parent` 安全但 parent 的新版本不一定真的會拉到 target 新版。

#### 5. `lock_only` — **last resort**

```bash
$PKG_MANAGER_BIN update <pkg>
```

或對 `pnpm-lock.yaml` 手動編輯後跑：
```bash
$PKG_MANAGER_BIN install --frozen-lockfile --offline
```

**強烈不建議**走純 hand-edit lockfile — 未來 lock regenerate 會沖掉。

### Lock-only 重新解析（npm `--package-lock-only` 的對應）

```bash
$PKG_MANAGER_BIN install --lockfile-only
```

- 只更新 `pnpm-lock.yaml`，不會碰 `node_modules/`
- 若 store (`~/.local/share/pnpm/store/`) 已含目標版本，無需 network access
- 速度比完整 install 快很多

### 不需要 network 的 lockfile 驗證 (給 Phase 5.4: post-edit validation)

```bash
$PKG_MANAGER_BIN install --frozen-lockfile --offline
```

純本地操作：
- 不會嘗試聯絡 registry
- 不需要 token（沒 JFROG_TOKEN 也能跑）
- 校驗 lockfile 內 `integrity:` 與 store 中內容的 sha512 一致

**這是手動編輯 pnpm-lock.yaml 後一定要跑的 sanity check**（見 `validate_lockfile.sh`）。
若 store 缺對應版本會 fail；正常 dev 環境若 `pnpm install` 跑過就不會有問題。

---

## 依賴查詢 (Phase 2)

### `pnpm why <pkg>` — 取代 `npm ls <pkg>`

```bash
$PKG_MANAGER_BIN why ip-address
```

輸出範例：
```
└─ some-parent@1.0.0
   └─ ip-address@10.1.0
```

說明：ip-address 是 transitive，被 `some-parent` 拉進來。

`pnpm why` 預設只看 production deps；加 `--dev` / `--all` 看 dev / 全部。

### `pnpm list <pkg> --json`

```bash
$PKG_MANAGER_BIN list ip-address --json
```

取得 installed version + parent chain 的 JSON 形式 — `dep_tree_js.js` 不依賴此命令
（lockfile-first），但 debugging 時很實用。

### `pnpm view <pkg>@<ver> --json`

```bash
$PKG_MANAGER_BIN view ip-address@10.2.0 --json
```

取得目標版本的 registry metadata（含 `engines.node` / `peerDependencies` 等）— 對應 npm `npm view`。

---

## pnpm-lock.yaml 格式（給排錯用）

pnpm 從 v7 (lockfileVersion 5) 開始格式穩定，v9 又把 dependencies 從 `packages:`
拆出到 `snapshots:` block。`dep_tree_js.js::parsePnpm` 兩種格式都能讀。

### v6 / v7 格式（單一 `packages:` block）

```yaml
lockfileVersion: '6.0'
packages:
  /lodash@4.17.21:
    resolution: {integrity: sha512-...}
    dependencies:
      is-arrayish: 0.3.2
    peerDependencies:
      react: '>=16'
```

每個 entry 的 key 開頭有 `/`（v6 quote-wrapped、v7 不一定 quote）。

### v9 格式（`packages:` + `snapshots:` 拆兩半）

```yaml
lockfileVersion: '9.0'
packages:
  lodash@4.17.21:
    resolution: {integrity: sha512-...}
    engines: {node: '>=4'}

snapshots:
  lodash@4.17.21:
    dependencies:
      is-arrayish: 0.3.2
```

- `packages:` 只放 version-level metadata（與 peer-resolution 無關）
- `snapshots:` 才放實際解析後的 dep tree（含 peer-id suffix `(react@18)` 區分不同 peer context）

`dep_tree_js.js` 會合併兩個 block 後再算 reverse-index，所以 v6 / v7 / v9 對使用者透明。

---

## Workspace 操作（`pnpm-workspace.yaml`）

```yaml
# pnpm-workspace.yaml
packages:
  - 'packages/*'
  - 'apps/*'
  - '!apps/legacy-*'  # 排除
```

`dep_tree_js.js::readPnpmWorkspaceGlobs` 會解析此檔，輸出 `workspace_info.locations`
告知 target 出現在哪些 workspace。

```bash
# 升級 root 依賴
$PKG_MANAGER_BIN -w add <pkg>@<ver>

# 升級單一 workspace 的依賴（--filter 用 workspace name 或 glob）
$PKG_MANAGER_BIN --filter <workspace-name> add <pkg>@<ver>

# 列出所有 workspace
$PKG_MANAGER_BIN list --recursive --depth -1 --json

# 在所有 workspace 跑同一命令
$PKG_MANAGER_BIN -r <command>
```

**Phase 2.0 workspace 條件分流**（見 SKILL.md）：
- transitive + lock-only 升級 → workspace 不影響，直接走
- transitive + parent-bump → 詢問使用者 parent 要在哪些 workspace 升
- direct → 詢問使用者哪個 workspace 是目標

---

## 與 npm / yarn 命令對照表 (cheat sheet)

| 用途 | npm | yarn 3 (Berry) | pnpm |
|------|-----|----------------|------|
| 安裝所有依賴 | `npm install` | `$PKG_MANAGER_BIN install` | `$PKG_MANAGER_BIN install` |
| 嚴格依 lock 安裝 | `npm ci` | `$PKG_MANAGER_BIN install --immutable` | `$PKG_MANAGER_BIN install --frozen-lockfile` |
| 升級到指定版本 | `npm install <pkg>@<ver>` | `$PKG_MANAGER_BIN up <pkg>@<ver>` | `$PKG_MANAGER_BIN add <pkg>@<ver>` |
| 只更新 lock | `npm install --package-lock-only` | `$PKG_MANAGER_BIN install --mode update-lockfile` | `$PKG_MANAGER_BIN install --lockfile-only` |
| 看 dep tree | `npm ls <pkg>` | `$PKG_MANAGER_BIN why <pkg>` | `$PKG_MANAGER_BIN why <pkg>` |
| 看 package metadata | `npm view <pkg>` | `$PKG_MANAGER_BIN info <pkg> --json` | `$PKG_MANAGER_BIN view <pkg> --json` |
| Workspace 操作 | `npm <cmd> -w <name>` | `$PKG_MANAGER_BIN workspace <name> <cmd>` | `$PKG_MANAGER_BIN --filter <name> <cmd>` |
| 跳過 lifecycle scripts | `npm ... --ignore-scripts` | (yarn berry 預設不跑) | `$PKG_MANAGER_BIN ... --ignore-scripts` |
| Transitive override | `package.json#overrides` | `package.json#resolutions` | `package.json#pnpm.overrides` |
| Offline 驗證 | `npm ci --offline --dry-run` | `$PKG_MANAGER_BIN install --immutable --check-cache --mode update-lockfile` | `$PKG_MANAGER_BIN install --frozen-lockfile --offline` |

---

## hoisting / symlink model（與 npm / yarn 差最大的地方）

pnpm 的 `node_modules/` 是 symlink tree：
```
node_modules/
├── .pnpm/                       # 真正的內容 (content-addressable)
│   ├── lodash@4.17.21/
│   │   └── node_modules/
│   │       └── lodash/          # ← 實際檔案
│   └── axios@1.6.0/
│       └── node_modules/
│           ├── axios/           # ← 實際檔案
│           └── lodash -> ../../lodash@4.17.21/node_modules/lodash
└── lodash -> .pnpm/lodash@4.17.21/node_modules/lodash
└── axios  -> .pnpm/axios@1.6.0/node_modules/axios
```

**關鍵特性**：
- 套件**只能 import 自己宣告過的 dep**（沒有 npm/yarn 那種 "phantom deps" 可以蹭）
- `node_modules/.pnpm/<name>@<version>/` 是每個版本的獨立檔案副本
- 同一個套件多個版本可以共存而不衝突

**對本 skill 的影響**：
- `ast_scanner_js.js` 走 `node_modules/.pnpm/<pkg>@<ver>/node_modules/<pkg>` 也能讀到（`fs.readFileSync` 跟 symlink）
- `api_surface_diff_js.js` 抓 `.d.ts` 同理 — 走 import resolution 從 symlink 進去就拿到 actual files
- 若 `nodeLinker: hoisted`（罕見）會退化成 npm 風格的扁平 node_modules — 不影響本 skill

### `shamefully-hoist` 與相關設定

`.npmrc` 內：
```
shamefully-hoist=true
```

會把 .pnpm 內的 dep 全部 symlink 到頂層 node_modules — 讓不知道有 phantom dep 問題
的舊套件能用。**不建議升級時改動這個設定**，會造成 lockfile 大變動讓 review 困難。

---

## 常見錯誤代碼

| Code | 意義 | 通常原因 | 處理方式 |
|------|------|---------|---------|
| `ERR_PNPM_REGISTRIES_MISMATCH` | registry mismatch | `.npmrc` registry 與 lockfile 紀錄不同 | 確認 `.npmrc` 與 CI 環境一致 |
| `ERR_PNPM_PEER_DEP_ISSUES` | peer dep 不滿足 | parent 對 peer 的 range 與裝的版本不符 | Phase 3 看升級可不可降到滿足條件的版本，或在 `pnpm.overrides` 加釘版 |
| `ERR_PNPM_FROZEN_LOCKFILE_WITH_OUTDATED_LOCKFILE` | `--frozen-lockfile` 模式下 lockfile 與 manifest 不一致 | 升完忘了重生 lockfile | 移除 `--frozen-lockfile` 跑一次 `pnpm install` 重生，再 commit |
| `ERR_PNPM_NO_MATCHING_VERSION` | 找不到符合 range 的版本 | range 寫錯 / registry 沒有對應版本 | 用 `pnpm view <pkg> versions --json` 確認可用版本 |
| `ELIFECYCLE` | postinstall 失敗 | 套件 build script 在當前環境跑不起來 | 加 `--ignore-scripts`，事後 `pnpm rebuild <pkg>` 並驗證 |

`parse_pm_errors.py` 會把這些代碼自動分類（auth / network / conflict / lifecycle），
避免使用者被一堆無關訊息混淆。

---

## 與 corepack 整合

pnpm 9+ 預設透過 corepack 管理版本：

```json
{
  "packageManager": "pnpm@9.7.0"
}
```

- corepack 在 Node 16.10+ 自帶
- 第一次跑 `pnpm` 會自動下載 `pnpm@9.7.0` binary 到 corepack cache
- `detect_env_js.sh` 偵測 `uses_corepack` + `pkg_manager_bin` 都會把 corepack-managed pnpm
  的實際路徑找出來，後續 phase 一律用該路徑呼叫

若 `packageManager` 欄位缺失但 lockfile 是 pnpm → preflight 會 warn，建議補上
讓 CI / 其他開發者用一致版本。
