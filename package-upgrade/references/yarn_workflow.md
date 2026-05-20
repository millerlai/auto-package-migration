# Yarn (Berry / v3+) Workflow

> 對應 Python 的 `pip_workflow.md`，但 yarn 3 (Berry) 的指令與 yarn 1 差異很大，
> 而且 corepack-managed 的 yarn 通常**不在 PATH**，必須透過 `pkg_manager_bin`
> 變數呼叫 (見 `detect_env_js.sh` 輸出)。

## 重要前置條件 (preflight.sh 已偵測)

| 條件 | 來源 | 影響 |
|------|------|------|
| `pkg_manager_bin` 不空 | `.yarn/releases/yarn-*.cjs` 或 PATH | 沒有就無法跑任何 yarn 命令 — preflight 會 block |
| `JFROG_TOKEN` (或對應 env var) 已設定 | `.yarnrc.default.yml` 解析 | 沒有 → install / yarn up 會 `YN0041 Invalid authentication` |
| `nodeLinker` (pnp vs node-modules) | `.yarnrc.yml` / `.yarnrc.default.yml` | 決定有無 `node_modules`；pnp 模式下 ts-morph / 部分工具會 fail |

**所有命令呼叫一律用 `$PKG_MANAGER_BIN`**，不要 hardcode `yarn`：

```bash
$PKG_MANAGER_BIN install --immutable
$PKG_MANAGER_BIN up <pkg>
$PKG_MANAGER_BIN why <pkg>
```

---

## 升級命令 (Phase 5) — 與 npm 的差異很大

### 升級「直接依賴」(yarn 3)

```bash
# 升級到指定範圍 (語意同 npm install <pkg>@<range>)
$PKG_MANAGER_BIN up <pkg>@<range>

# 範例
$PKG_MANAGER_BIN up axios@^1.6.0
```

`yarn up` 會：
1. ✅ 更新 `package.json` 中的範圍
2. ✅ 更新 `yarn.lock`
3. ✅ 下載到 `.yarn/cache/`（pnp 模式）或 `node_modules/`（node-modules 模式）

### ⚠️ `yarn up -R <pkg>` **不能接 range** (踩過坑)

`-R` 是 "recursive"，意思是同時升級所有 workspaces / 所有重複實例。但加 `@<range>` 會炸：

```bash
# ❌ 會錯: Ranges aren't allowed when using --recursive
$PKG_MANAGER_BIN up -R ip-address@10.2.0

# ✅ 正確: 分兩步
$PKG_MANAGER_BIN up ip-address@10.2.0   # 設定範圍
$PKG_MANAGER_BIN dedupe                  # recursive update lockfile
```

### Transitive override (lock-only 升級的乾淨做法)

當目標是 transitive package 而 parent 約束允許新版本時：

```bash
$PKG_MANAGER_BIN set resolution "<descriptor>" "npm:<exact-version>"

# 範例: 把所有 ip-address 都鎖到 10.2.0
$PKG_MANAGER_BIN set resolution "ip-address@npm:^10.1.0" "npm:10.2.0"
```

這比 `yarn up <pkg>` 更精準 — 只動 `yarn.lock` 中的 `resolution:` 欄位，不動 `package.json`。

對應 `package.json` 的 manifest 寫法：

```jsonc
{
  "resolutions": {
    "ip-address": "10.2.0"
  }
}
```

→ 然後跑 `yarn install --mode update-lockfile`。

### Lock-only 重新解析（npm `--package-lock-only` 的對應）

```bash
$PKG_MANAGER_BIN install --mode update-lockfile
```

- 只更新 `yarn.lock`，不會下載到 `.yarn/cache/`
- 不需要 network access（如果版本已在本地 cache 中）
- 速度比完整 install 快很多

### 不需要 network 的 lockfile 驗證 (給 #8: post-edit validation)

```bash
$PKG_MANAGER_BIN install --immutable --check-cache --mode update-lockfile
```

純本地操作：
- 不會嘗試聯絡 registry
- 不需要 token (沒 JFROG_TOKEN 也能跑)
- 校驗 `.yarn/cache/*.zip` 的 SHA-512 與 lockfile 中宣告的 `checksum:` 欄位
- 如果有人手動編輯 lockfile 但抄錯 checksum → 這步會擋下，不會等到 CI 才炸

**這是手動編輯 yarn.lock 後一定要跑的 sanity check** (見 `validate_lockfile.sh`)。

---

## 依賴查詢 (Phase 2)

### `yarn why <pkg>` — 取代 `npm ls <pkg>`

```bash
$PKG_MANAGER_BIN why ip-address
```

輸出範例：
```
└─ some-parent@npm:1.0.0
   └─ ip-address@npm:10.1.0 (via npm:^10.0.0)
```

說明: ip-address 是 transitive，被 `some-parent` 從 `^10.0.0` 範圍解析過來。

### `yarn info <pkg> --json`

```bash
$PKG_MANAGER_BIN info ip-address@npm:10.2.0 --json
```

取得目標版本的 metadata（含 `engines.node` / `peerDependencies` 等）— 對應 npm `npm view`。

---

## `.yarn/cache` 命名規則 (給排錯用)

```
.yarn/cache/<name>-npm-<version>-<hash>-<sum>.zip
```

- `<hash>`: 倒數第二段，10 字元，resolution 內容 hash
- `<sum>`: 倒數第一段，10 字元，SHA-512 前 10 字元
- 完整 SHA-512: `shasum -a 512 <zip>` 或 `openssl dgst -sha512 <zip>`

`yarn.lock` 的 `checksum:` 欄位是 `10/<full-sha-512-hex>` 格式（前綴 `10/` 是 zlib version marker）。

---

## nodeLinker: pnp vs node-modules

| | pnp (default) | node-modules |
|---|---------------|--------------|
| `node_modules/` 目錄 | ❌ 不存在 | ✅ 存在 |
| ts-morph / `@babel/parser` 走專案 path | ✅ 沒問題 (讀檔案本身) | ✅ |
| ts-morph 解 import 路徑 | ❌ 找不到 (要靠 `.pnp.cjs`) | ✅ |
| `npm ls` / `pip` 風格工具 | ❌ 不適用 | ✅ |
| build tools (webpack/vite) | 需要 `pnpapi` 整合 | 標準 |

**判斷規則**：若專案 `nodeLinker == "pnp"` 且 helper script 需要走 `node_modules`，
preflight 應該告知使用者「local install 走不到 node_modules，會走 lockfile-first 路徑」。

---

## Workspace 操作 (`is_workspace: true`)

```bash
# 升級 root workspace 的依賴
$PKG_MANAGER_BIN up <pkg>

# 升級單一 workspace 的依賴
$PKG_MANAGER_BIN workspace <workspace-name> up <pkg>

# 列出所有 workspace
$PKG_MANAGER_BIN workspaces list --json
```

**Phase 2.2 workspace 條件分流** (見 SKILL.md)：
- transitive + lock-only 升級 → workspace 不影響，直接走
- transitive + parent-bump → 詢問使用者 parent 要在哪些 workspace 升
- direct → 詢問使用者哪個 workspace 是目標

---

## 與 npm 命令對照表 (cheat sheet)

| 用途 | npm | yarn 3 (Berry) |
|------|-----|----------------|
| 安裝所有依賴 | `npm install` | `$PKG_MANAGER_BIN install` |
| 嚴格依 lock 安裝 | `npm ci` | `$PKG_MANAGER_BIN install --immutable` |
| 升級到指定版本 | `npm install <pkg>@<ver>` | `$PKG_MANAGER_BIN up <pkg>@<ver>` |
| 只更新 lock | `npm install --package-lock-only` | `$PKG_MANAGER_BIN install --mode update-lockfile` |
| 看 dep tree | `npm ls <pkg>` | `$PKG_MANAGER_BIN why <pkg>` |
| 看 package metadata | `npm view <pkg>` | `$PKG_MANAGER_BIN info <pkg> --json` |
| Workspace 操作 | `npm <cmd> -w <name>` | `$PKG_MANAGER_BIN workspace <name> <cmd>` |
| 跳過 lifecycle scripts | `npm ... --ignore-scripts` | (yarn berry 預設不跑 build scripts，例外用 `enableScripts: false` 在 .yarnrc.yml) |
| Transitive override | `package.json#overrides` | `$PKG_MANAGER_BIN set resolution` 或 `package.json#resolutions` |
| Offline 驗證 | `npm ci --offline --dry-run` | `$PKG_MANAGER_BIN install --immutable --check-cache --mode update-lockfile` |

---

## 常見錯誤代碼

| Code | 意義 | 通常原因 | 處理方式 |
|------|------|---------|---------|
| `YN0041` | Invalid authentication | 缺 token (e.g. `JFROG_TOKEN`) | 走 preflight，補 token 重試 |
| `YN0050` | A network error occurred | DNS / 代理 / VPN | 確認可連上 registry host |
| `YN0066` | Builtin patch failed | 通常是 typescript 之類包的 yarn 內建 patch fail | **多半是 noise**，不影響升級本身 — 看 `parse_pm_errors.py` 的 `primary_blocker` 不要被分心 |
| `YN0086` | Lockfile would change | `--immutable` 模式下 lockfile 跟 manifest 不一致 | 移除 `--immutable` 或先解 manifest |

`parse_pm_errors.py` 會把這些代碼自動分類成 auth/network/patch/conflict，避免使用者被一堆無關訊息混淆。
