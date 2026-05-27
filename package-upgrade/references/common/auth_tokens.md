# Auth Token Acquisition Reference

> 當 `preflight.sh` 偵測到設定檔 (`.yarnrc.yml` / `.npmrc` / `.yarnrc.default.yml`)
> 引用了 `${ENV_VAR}` 但該變數未設定時，skill 應該**主動詢問使用者**並提供取得
> token 的具體 URL — 不要悄悄繞過走 lockfile-only fallback。
>
> 使用者提供 token 後，skill 應將其寫入 **`<project>/.env.<service>`** 並
> chmod 600 + gitignore — 下次 session 由 `preflight.sh` 自動 source，
> 不需要再次詢問。

---

## Known host → env var → acquisition URL

| Host pattern | Env var | Persist file | Acquisition URL |
|---|---|---|---|
| `jfrog.trendmicro.com` | `JFROG_TOKEN` | `.env.jfrog` | https://jfrog.trendmicro.com/ui/admin/artifactory/user_profile |
| `*.pkgs.visualstudio.com` | `AZURE_DEVOPS_EXT_PAT` | `.env.azure` | https://dev.azure.com/`<org>`/_usersSettings/tokens |
| `npm.pkg.github.com` | `NPM_TOKEN` (PAT) | `.env.npm` | https://github.com/settings/tokens |
| `<host>` (內部 GHE) | `GITHUB_TOKEN` | `.env.github` | `https://<host>/settings/tokens` |
| `<custom artifactory>` | varies | `.env.<service>` | (問使用者) |
| Atlassian Cloud | `ATLASSIAN_API_TOKEN` | (不持久化) | https://id.atlassian.com/manage-profile/security/api-tokens |

> **不持久化的例外**: `ATLASSIAN_API_TOKEN` 用於 Phase 1.C MCP fallback，
> 通常只在單次 session 使用。建議使用者**用完就 revoke**，不要寫入檔案。

---

## JFROG_TOKEN 完整詢問流程（範本）

當 `preflight.sh` 報出 `env_JFROG_TOKEN_missing`，**逐字**用以下訊息詢問
使用者（這是 IMPROVEMENTS feedback 指定的措辭）：

```
⚠️ 缺少 token: $JFROG_TOKEN

來源: 由 .yarnrc.default.yml 第 N 行的 ${JFROG_TOKEN} 占位符引用
影響範圍 (從 custom_registries 推斷):
  - scope `@tonic-one` → https://jfrog.trendmicro.com/artifactory/api/npm/npm-virtual/
  - scope `@internal`  → https://jfrog.trendmicro.com/artifactory/api/npm/internal/

🔑 取得 token:
  go to https://jfrog.trendmicro.com/ui/admin/artifactory/user_profile.
  In the next step, click "Generate Identity Token" to generate a token
  that will be used as part of CURL.

提供 token 後，我會：
  1. export JFROG_TOKEN 到目前 session (供 Phase 5 yarn 命令使用)
  2. 寫入 <project>/.env.jfrog (chmod 600，自動加進 .gitignore)
  3. 下次跑 skill 時 preflight 自動讀取，不再詢問

請選擇:
[1] 提供 token (我會在下一個 prompt 接收 token，請貼上)
[2] 跳過 (走 lockfile-only fallback；無法在本地驗證 yarn install / yarn up)
[3] 中止本次升級
```

---

## 取得 token 後的儲存流程

使用 `scripts/save_token.sh`，按 `.env.jfrog` 是否已存在 + 是否含同名 key
走以下三條路：

### 流程 A: `.env.jfrog` 不存在 → 直接創建

```bash
bash scripts/save_token.sh <project_path> .env.jfrog JFROG_TOKEN "<token>"
```

腳本會：
1. 創建 `<project>/.env.jfrog` 並寫入 `JFROG_TOKEN=<token>`
2. `chmod 600`（只有 owner 能讀寫）
3. 在 `<project>/.gitignore` 加入 `.env.jfrog`（若 `.gitignore` 不存在會幫忙建立）

回傳 JSON `{"status":"created", ...}`。

### 流程 B: `.env.jfrog` 已存在，**沒有** `JFROG_TOKEN=` 行 → 直接追加

同樣指令，腳本偵測到沒有同名 key 會直接 append，回傳
`{"status":"appended", ...}`。

### 流程 C: `.env.jfrog` 已存在，**有** `JFROG_TOKEN=` 行 → 詢問是否覆蓋

第一次呼叫腳本不加 `--force`：

```bash
bash scripts/save_token.sh <project_path> .env.jfrog JFROG_TOKEN "<token>"
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
bash scripts/save_token.sh <project_path> .env.jfrog JFROG_TOKEN "<token>" --force
# status: "replaced"
```

選 `[N]` → 不再寫檔，僅 `export JFROG_TOKEN=<token>` 進當前 session。

---

## Token 接收方式

收 token 時務必：

1. 使用者用 prompt 直接貼上 — token 會出現在這個對話的 transcript 中
2. **永遠不要 echo 回去** — 收到後接著問下一個問題即可
3. **永遠不要把 token 放進報告 / commit message / Jira comment** — 即使是片段 / mask 過的也不要
4. session 中用 `export <ENV_VAR>=<value>` 接過去；後續 Phase 5/6 的命令會繼承
5. 寫入 `.env.<service>` 必須走 `save_token.sh`（保證 chmod 600 + gitignore）

---

## preflight.sh 自動讀取機制

`preflight.sh` 啟動時會 source 以下檔案（若存在於 `<project>` 根目錄）：

- `.env.jfrog`
- `.env.npm`
- `.env.github`

`set -a` 讓檔案內的 `KEY=VALUE` 自動 `export`，於是後續 env 檢查直接 ✅ 通過。
所有讀取在 subshell 中進行，不汙染呼叫端 shell。

新增 service 對應的 `.env.<name>` 時，記得：
1. 上面 mapping table 加一行
2. `preflight.sh` 的 for-loop 加該檔名
3. 提示使用者 token 取得 URL

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
