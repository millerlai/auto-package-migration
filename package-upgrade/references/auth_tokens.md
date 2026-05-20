# Auth Token Acquisition Reference

> 當 `preflight.sh` 偵測到設定檔 (`.yarnrc.yml` / `.npmrc` / `.yarnrc.default.yml`)
> 引用了 `${ENV_VAR}` 但該變數未設定時，skill 應該**主動詢問使用者**並提供取得 token
> 的具體 URL — 不要悄悄繞過走 lockfile-only fallback。

## Known host → env var → acquisition URL

| Host pattern | Env var | Acquisition URL | 備註 |
|---|---|---|---|
| `jfrog.trendmicro.com` | `JFROG_TOKEN` | https://jfrog.trendmicro.com/ui/admin/artifactory/user_profile | "Generate Identity Token" 按鈕；token 有效期通常為 90 天 |
| `*.pkgs.visualstudio.com` | `AZURE_DEVOPS_EXT_PAT` | https://dev.azure.com/`<org>`/_usersSettings/tokens | 需給予 Packaging (read) 權限 |
| `npm.pkg.github.com` | `NPM_TOKEN` (PAT) | https://github.com/settings/tokens | PAT 至少需 `read:packages` scope |
| `<host>` (內部 GHE) | `GITHUB_TOKEN` | `https://<host>/settings/tokens` | GHE 自架實例的 PAT 頁面 |
| `<custom artifactory>` | varies | (問使用者) | 任何 `*.artifactory.*` / `*.jfrog.*` |
| Atlassian Cloud | `ATLASSIAN_API_TOKEN` | https://id.atlassian.com/manage-profile/security/api-tokens | 配合 `ATLASSIAN_EMAIL` |

## 互動式詢問 template

當 detect_env_js.sh 輸出的 `env_var_placeholders` 含未設定的變數時，Phase 0.3 pre-flight
應該按以下格式詢問每個變數：

```
⚠️ 缺少 token: {ENV_VAR}

來源: 由 {.yarnrc.default.yml} 第 N 行的 ${{ENV_VAR}} 占位符引用
影響範圍 (從 custom_registries 推斷):
  - scope `@tonic-one` → https://jfrog.trendmicro.com/artifactory/api/npm/npm-virtual/
  - scope `@internal`  → https://jfrog.trendmicro.com/artifactory/api/npm/internal/

取得 token:
  https://jfrog.trendmicro.com/ui/admin/artifactory/user_profile
  (點 "Generate Identity Token"，scope 選 npm read)

請選擇:
[1] 提供 token (我會 export 到 session env，不會寫到任何檔案；token 會出現在 transcript 中)
[2] 跳過 (走 lockfile-only fallback；無法在本地驗證 install / yarn up，需依賴 CI)
[3] 中止本次升級
```

若使用者選 [1]：
- 用 `read -rs ENV_VAR_VALUE` 取得 token（不 echo 到 terminal）
- 在 session 內 `export ENV_VAR=$VALUE`
- 後續 Phase 5 / 6 的命令都繼承這個 env

若使用者選 [2]：
- 在 session memory 中標記 `auth_mode: lockfile_only`
- Phase 5 強制走「手動編輯 lockfile + validate_lockfile.sh」路徑
- Phase 7.1 報告明確列出 "Auth fallback: lockfile-only, CI must validate"

若使用者選 [3]：
- 立即終止，不做任何修改

## 自動 mapping 規則 (preflight.sh 用)

```bash
# pseudo: 從 custom_registries 的 host 推導需要的 env var
case "$registry_host" in
    *.jfrog.trendmicro.com)      auth_url="https://jfrog.trendmicro.com/ui/admin/artifactory/user_profile" ;;
    *.pkgs.visualstudio.com)     auth_url="https://dev.azure.com/<org>/_usersSettings/tokens" ;;
    npm.pkg.github.com)          auth_url="https://github.com/settings/tokens" ;;
    *.github.trendmicro.com)     auth_url="https://${registry_host}/settings/tokens" ;;
    *)                           auth_url="(unknown — ask user for the registry's token portal URL)" ;;
esac
```

## 注意事項

- **絕不**把 token 寫入任何檔案 — 只用 `export` 進 session env
- 若使用者已經 `export` 過該變數，preflight 偵測到就直接 ✅，不重複詢問
- 同一個 token (`JFROG_TOKEN`) 可能被多個 scope 引用，只問一次即可
- Phase 7 報告必須註明哪些 token 在本次 session 被使用過（不附 token 本身），方便 reviewer 重現
