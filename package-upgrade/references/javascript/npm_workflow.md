# npm 工作流程（package-upgrade JS path）

> 對應 Python 的 `../python/pip_workflow.md` / `../python/poetry_workflow.md` / `../python/uv_workflow.md`。

## 關鍵差異（vs pip）

| | pip | npm |
|--|-----|-----|
| 安裝命令是否自動寫回宣告檔? | ❌ 必須手動編輯 `requirements.txt` 或 `pyproject.toml` | ✅ `npm install pkg@ver --save` 自動更新 `package.json` |
| Lock 檔案 | 不一定有（pip-tools / 自定義） | 一律有 `package-lock.json` |
| Lifecycle scripts | 沒有此概念 | 有 `preinstall` / `install` / `postinstall` / `prepare` — **可執行任意程式**，預設要小心 |
| 依賴宣告欄位 | 單一 `requirements.txt` 行 / `pyproject.toml` table | 四個欄位：`dependencies` / `devDependencies` / `peerDependencies` / `optionalDependencies` |

## Phase 5: 升級命令

### 直接依賴 (`dependencies`)

```bash
# 預設加 --ignore-scripts (見 workflow.md 的警告章節)
npm install <package>@<version> --save --ignore-scripts

# 範例
npm install axios@1.6.0 --save --ignore-scripts
```

### Dev 依賴 (`devDependencies`)

```bash
npm install <package>@<version> --save-dev --ignore-scripts
```

### Peer 依賴 (`peerDependencies`)

```bash
# npm >= 7 才支援 --save-peer
npm install <package>@<version> --save-peer --ignore-scripts
```

### Transitive 升級策略（按 `dep_tree_js.js` 的優先序執行）

`dep_tree_js.js` 對每個 transitive target 會輸出 `upgrade_strategies[]`，
按以下順序選擇對應命令：

#### 1. `direct_bump` — target 在 package.json `dependencies`/`devDependencies`/`peerDependencies`

```bash
npm install <pkg>@<range> --save --ignore-scripts
```

#### 2. `bump_override` — target 在 `overrides` (npm 慣例) 已被釘版

直接編輯 `package.json` 把對應 entry 的 value 改成新版本：

```jsonc
{
  "overrides": {
    "<pkg>": "<new-version>"
  }
}
```

然後：
```bash
npm install --package-lock-only --ignore-scripts
```

#### 3. `bump_parent` — **預設推薦** 給沒有 override 的 transitive package

```bash
npm install <direct-parent>@<new-range> --save --ignore-scripts
```

升完 parent 後，npm 會把新版的 target 一併拉進 lock。記得 Phase 6 跑測試。

#### 4. `add_override` — `bump_parent` 不適用 / 不夠精確時

在 `package.json` 加 `overrides` (npm 8+)：

```jsonc
{
  "overrides": {
    "<pkg>": "<new-version>"
  }
}
```

然後：
```bash
npm install --package-lock-only --ignore-scripts
```

> **與 `bump_parent` 的取捨**: `add_override` 一定生效但繞過 parent 的相容性
> 測試；`bump_parent` 安全但 parent 的新版本不一定真的會拉到 target 新版。

#### 5. `lock_only` — **last resort**，僅在 `dep_tree_js.js` 確認無 override 且無 direct parent 可達時

```bash
npm update <package> --ignore-scripts
# 或對 package-lock.json 手動編輯後跑：
npm ci --offline --dry-run    # 驗證 checksum
```

**強烈不建議**走純 hand-edit lockfile — 未來 lock regenerate 會沖掉，且無 manifest 審計軌跡。

**驗證所有 transitive 升級**：
- `bump_parent` / `direct_bump` → `git diff package.json` 有變動、`git diff package-lock.json` 也有
- `bump_override` / `add_override` → 同上（overrides 的變動算 manifest 變動）
- `lock_only` → 只有 `package-lock.json` 動

### `@types/<pkg>` 同步升級

```bash
# 升完主套件後檢查
node -e "const p = require('./package.json'); console.log('@types/${PKG}:', p.devDependencies?.['@types/${PKG}'] || 'not present')"

# 若存在，建議同時升
npm install @types/<pkg>@<matching-version> --save-dev --ignore-scripts
```

## Phase 0 偵測欄位（`detect_env_js.sh` 輸出）

```json
{
  "language": "javascript",
  "pkg_manager": "npm",
  "node_version": "20.x.x",
  "lockfile_path": "package-lock.json",
  "manifest_files": ["./package.json"],
  "is_workspace": false,
  "has_typescript": true,
  "tsconfig_path": "tsconfig.json",
  "test_framework_hint": "jest"
}
```

## 常見地雷

1. **`npm ci` vs `npm install`**：
   - `npm ci` 嚴格依 lock 安裝，不會修改 lock
   - `npm install` 會根據 `package.json` 重新解析、可能修改 lock
   - Phase 5 用 `install`（要寫回），Phase 5 restore 用 `ci`（要重現）

2. **`overrides` (npm 8+) / `resolutions` (yarn)**：
   - 如果 `package.json` 有 `overrides`，transitive lock-only 路徑可能因 override 卡住
   - Phase 2 B-3 之前先檢查 overrides

3. **Workspaces**：
   - root `package.json` + 每個 workspace 各一份 `package.json`
   - 升級 root 用 `npm install <pkg>@<ver> -w root` 或 `--workspaces`
   - 升級單一 workspace：`npm install <pkg>@<ver> -w <workspace-name>`
   - **MVP 不處理**，偵測到 `is_workspace: true` 時暫停告知使用者

4. **`npm install <pkg>@<ver>` 會 dedupe**：
   - 升級一個套件可能改動其他 transitive package 的解析版本（hoisted），這是正常的
   - 報告中要說明 `package-lock.json` 為什麼有意外的變動行
