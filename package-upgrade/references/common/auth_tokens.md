# Auth Token Acquisition Reference

> **核心政策：capability-first，raw token 是最後手段。**
> 當需要對某服務 (Jira / GitHub / 私有 registry) 認證時，**依序**嘗試三層，
> 能在前一層解決就絕不進到下一層 —— 目的是盡量**不讓 skill 讀取 / 持有 token**：
>
> ```
> Tier 1  偵測既有能力        → 環境已能認證就直接用，完全不碰 token
> Tier 2  引導使用者自助 auth  → 給指令讓使用者自己連，做完重試 Tier 1
> Tier 3  (最後手段) 收 raw token → 明示會進 transcript；預設只在 session 內生效、不寫檔
> ```

---

## 三層對每個服務的對應

| 服務 | Tier 1 偵測既有能力 | Tier 2 引導自助 auth | Tier 3 最後手段 (raw token) |
|---|---|---|---|
| **Jira** | 可用工具清單中是否有 `mcp__*Atlassian*` / Jira MCP 工具 → 有就直接用 | 「請在瀏覽器連接 Atlassian MCP 後告訴我，我重試」 | `ATLASSIAN_EMAIL` + `ATLASSIAN_API_TOKEN` → `jira_fetch.py`（**不持久化**） |
| **GitHub** (PR / Dependabot) | `gh auth status --hostname <host>`（preflight 已驗證） | `! gh auth login --hostname <host>` | `GITHUB_TOKEN` env（**不持久化**） |
| **私有 registry** (JFrog / 內部 npm / Azure) | preflight 偵測 env var 已設 **或** npmrc/yarnrc 已有非 `${VAR}` 真實憑證（`registry_auth_native`） | `! npm login --registry <url>` (npm/pnpm) / `! yarn npm login` (yarn berry) / 自行編 `~/.npmrc` / `~/.netrc` (Go) | 貼 token → `save_token.sh`（**僅在使用者明確同意「記住下次」時才寫檔**） |

> **預設不持久化**：Tier 3 收到的 token 一律先只 `export` 進當前 session。
> 只有在使用者**明確選擇「記住下次」**時，才對 registry token 跑 `save_token.sh`
> 寫入 `.env.<service>`。`ATLASSIAN_API_TOKEN` / `GITHUB_TOKEN` 一律不寫檔。

---

## Known host → env var → acquisition URL

| Host pattern | Env var | Persist file (僅 opt-in) | Acquisition URL |
|---|---|---|---|
| `jfrog.trendmicro.com` | `JFROG_TOKEN` | `.env.jfrog` | https://jfrog.trendmicro.com/ui/admin/artifactory/user_profile |
| `*.pkgs.visualstudio.com` | `AZURE_DEVOPS_EXT_PAT` | `.env.azure` | https://dev.azure.com/`<org>`/_usersSettings/tokens |
| `npm.pkg.github.com` | `NPM_TOKEN` (PAT) | `.env.npm` | https://github.com/settings/tokens |
| `<host>` (內部 GHE) | `GITHUB_TOKEN` | `.env.github` | `https://<host>/settings/tokens` |
| `<custom artifactory>` | varies | `.env.<service>` | (問使用者) |
| Atlassian Cloud | `ATLASSIAN_API_TOKEN` | (不持久化) | https://id.atlassian.com/manage-profile/security/api-tokens |

> **不持久化的例外**: `ATLASSIAN_API_TOKEN`（與 `GITHUB_TOKEN`）只在單次 session 使用，
> **永遠不寫檔**。建議使用者**用完就 revoke**。

---

## JFROG_TOKEN 完整詢問流程（範本）

當 `preflight.sh` 報出 `env_JFROG_TOKEN_missing`，**先確認 Tier 1 已落空**
（preflight 沒有報 `registry_auth_native`），再用以下訊息詢問使用者。
注意：**選項順序把「自助 auth」排在「貼 token」之前**，貼 token 是最後手段。
取得 token 的措辭（🔑 區塊）是 IMPROVEMENTS feedback 指定的，**逐字保留**：

```
⚠️ 缺少 registry 認證: $JFROG_TOKEN

來源: 由 .yarnrc.default.yml 第 N 行的 ${JFROG_TOKEN} 占位符引用
影響範圍 (從 custom_registries 推斷):
  - scope `@tonic-one` → https://jfrog.trendmicro.com/artifactory/api/npm/npm-virtual/
  - scope `@internal`  → https://jfrog.trendmicro.com/artifactory/api/npm/internal/

請選擇 (建議優先用自助 auth，token 不會經過這個對話):
[1] 我自己做 native auth — 推薦
    我會帶你跑 `npm login --registry <url>`（npm/pnpm）或 `yarn npm login`（yarn berry），
    或你自行在 ~/.npmrc 設好憑證；完成後我重跑 preflight，Tier 1 就會通過。
[2] 提供 token (最後手段)
    我會在下一個 prompt 接收 token；⚠️ token 會出現在這個對話的 transcript 中。
[3] 跳過 (走 lockfile-only fallback；無法在本地驗證 yarn install / yarn up)
[4] 中止本次升級
```

若使用者選 [2]，再顯示取得 token 的步驟（**逐字**）：

```
🔑 取得 token:
  go to https://jfrog.trendmicro.com/ui/admin/artifactory/user_profile.
  In the next step, click "Generate Identity Token" to generate a token
  that will be used as part of CURL.

提供 token 後，我會:
  1. export JFROG_TOKEN 到目前 session (供 Phase 5 yarn 命令使用)
  2. 預設**不寫檔**。若你要下次免問，我再問一次是否寫入 <project>/.env.jfrog
```

---

## Tier 3 收到 token 後的處理

### 預設：只在 session 內生效，不寫檔

1. `export <ENV_VAR>=<value>` 進當前 session（讓 Phase 5/6 命令繼承）。
2. **不要**自動寫 `.env.<service>`。
3. 接著額外問一句（**只對 registry token**；`ATLASSIAN_API_TOKEN` / `GITHUB_TOKEN` 跳過此問）：

```
要不要記住這個 token，下次 session 免再提供?
[Y] 記住 — 寫入 <project>/.env.jfrog (chmod 600 + gitignore，下次 preflight 自動讀取)
[N] 不記住 (預設) — token 只在這個 session 有效
```

選 `[N]`（預設）→ 結束，不寫檔。
選 `[Y]` → 走下方 `save_token.sh` opt-in 持久化流程。

### Opt-in 持久化流程（僅在使用者選 `[Y]` 時）

使用 `scripts/common/save_token.sh`，按 `.env.jfrog` 是否已存在 + 是否含同名 key
走以下三條路：

#### 流程 A: `.env.jfrog` 不存在 → 直接創建

```bash
bash scripts/common/save_token.sh <project_path> .env.jfrog JFROG_TOKEN "<token>"
```

腳本會：
1. 創建 `<project>/.env.jfrog` 並寫入 `JFROG_TOKEN=<token>`
2. `chmod 600`（只有 owner 能讀寫）
3. 在 `<project>/.gitignore` 加入 `.env.jfrog`（若 `.gitignore` 不存在會幫忙建立）

回傳 JSON `{"status":"created", ...}`。

#### 流程 B: `.env.jfrog` 已存在，**沒有** `JFROG_TOKEN=` 行 → 直接追加

同樣指令，腳本偵測到沒有同名 key 會直接 append，回傳
`{"status":"appended", ...}`。

#### 流程 C: `.env.jfrog` 已存在，**有** `JFROG_TOKEN=` 行 → 詢問是否覆蓋

第一次呼叫腳本不加 `--force`：

```bash
bash scripts/common/save_token.sh <project_path> .env.jfrog JFROG_TOKEN "<token>"
# Exit code 2, status: "conflict"
```

→ **詢問使用者**：

```
⚠️ <project>/.env.jfrog 已經有 JFROG_TOKEN 值。
是否覆蓋成你剛才提供的新 token?

[Y] 是, 覆蓋舊 token
[N] 否, 保留現有 .env.jfrog 內容 (我仍會 export 新 token 到當前 session)
```

選 `[Y]` → 重跑加 `--force`:

```bash
bash scripts/common/save_token.sh <project_path> .env.jfrog JFROG_TOKEN "<token>" --force
# status: "replaced"
```

選 `[N]` → 不再寫檔，僅 `export JFROG_TOKEN=<value>` 進當前 session。

---

## Token 接收方式

收 token 時務必：

1. 使用者用 prompt 直接貼上 — token 會出現在這個對話的 transcript 中
2. **永遠不要 echo 回去** — 收到後接著問下一個問題即可
3. **永遠不要把 token 放進報告 / commit message / Jira comment** — 即使是片段 / mask 過的也不要
4. session 中用 `export <ENV_VAR>=<value>` 接過去；後續 Phase 5/6 的命令會繼承
5. 寫入 `.env.<service>` 必須走 `save_token.sh`（保證 chmod 600 + gitignore），且**只在使用者明確同意持久化時**

---

## preflight.sh 的 Tier 1 偵測機制

### 自動讀取既有持久化 token

`preflight.sh` 啟動時會 source 以下檔案（若存在於 `<project>` 根目錄）：

- `.env.jfrog`
- `.env.npm`
- `.env.github`

透過 `load_token_files.sh` 以**純文字 KEY=VALUE 解析**（不 `source`，避免執行 token 內
嵌入的 `$(...)`），於是後續 env 檢查直接 ✅ 通過。

### registry native auth 偵測（`registry_auth_native`）

對 JS 專案，`preflight.sh` 在 env var **未設**時，會**離線**檢查該 registry host
是否已有非 `${VAR}` placeholder 的真實憑證：

- `<project>/.npmrc` 或 `~/.npmrc` 內 `//<host>[/path]:_authToken|_auth|_password=<literal>`
- `<project>/.yarnrc.yml` / `.yarnrc.default.yml` 內非 placeholder 的 `npmAuthToken`

命中 → 不報 `env_<VAR>_missing` blocker，改報 `registry_auth_native` ok
（代表 Tier 1 通過，PM 可自行認證，**完全不需要 token**）。
未命中 → 維持 blocker，但 remediation 會把 Tier 2 自助指令排在貼 token 之前。

> Python 私有 index 的認證儲存位置分散（pip.conf inline creds / `~/.netrc` / keyring /
> `~/.config/pypoetry/auth.toml`），無法可靠地離線 host-match，因此 Python preflight
> **不自動降級**，只在 remediation 補上 Tier 2 自助指令（poetry config http-basic /
> netrc / keyring）。

新增 service 對應的 `.env.<name>` 時，記得：
1. 上面 mapping table 加一行
2. `preflight.sh` 的 `load_token_files` 清單加該檔名
3. 提示使用者 Tier 2 自助方式與 Tier 3 token 取得 URL

---

## 自動 mapping 規則 (preflight.sh 用)

```bash
case "$registry_host" in
    *.jfrog.trendmicro.com)      auth_url="https://jfrog.trendmicro.com/ui/admin/artifactory/user_profile" ;;
    *.pkgs.visualstudio.com)     auth_url="https://dev.azure.com/<org>/_usersSettings/tokens" ;;
    npm.pkg.github.com)          auth_url="https://github.com/settings/tokens" ;;
    *.github.trendmicro.com)     auth_url="https://${registry_host}/settings/tokens" ;;
    *)                           auth_url="(unknown — ask user for the registry's token portal URL)" ;;
esac
```

---

## 注意事項

- `.env.<service>` 一定要在 `.gitignore` 中 — `save_token.sh` 強制檢查、缺則加入
- 檔案權限一律 `600` — `save_token.sh` 用 `chmod 600` 保證
- token 寫進檔案後，仍會出現在這個對話的 transcript（已是不可避免的）— 強烈建議使用者
  在 90 天 token 到期前到 JFrog portal **手動 revoke** 已洩漏到 transcript 的舊 token
- 同一個 token (如 `JFROG_TOKEN`) 可能被多個 scope 引用 — 只問一次即可
- Phase 7 報告必須**註明哪些 token 在本次 session 被使用過**（不附 token 本身），
  reviewer 可以快速判斷 PR 在哪些網路依賴下產生
