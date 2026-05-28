# 快速參考卡片

## 🎯 正確的套件升級命令

### Python — pip

#### 有 pip-tools (requirements.in)
```bash
# 1. 編輯 requirements.in
vim requirements.in  # requests==2.28.0 → requests==2.32.0

# 2. 重新編譯
pip-compile requirements.in

# 3. 安裝
pip-sync requirements.txt
```

#### 有 lock 檔案 (requirements.lock)
```bash
# 1. 編輯 requirements.txt
vim requirements.txt  # requests==2.28.0 → requests==2.32.0

# 2. 重新產生 lock
pip install -r requirements.txt
pip freeze > requirements.lock
```

#### 無 lock 檔案
```bash
# 1. 編輯 requirements.txt
vim requirements.txt  # requests==2.28.0 → requests==2.32.0

# 2. 安裝
pip install -r requirements.txt
```

### Python — poetry
```bash
# 一個命令同時更新 pyproject.toml 和 poetry.lock
poetry add requests@2.32.0
```

### Python — uv (專案模式)
```bash
# 一個命令同時更新 pyproject.toml 和 uv.lock
uv add "requests>=2.32.0"
```

### JavaScript / TypeScript — npm
```bash
# 同時更新 package.json 和 package-lock.json
npm install axios@1.7.0 --save           # production dep
npm install --save-dev typescript@5.5.0  # dev dep

# 升級到 latest minor / patch
npm update axios
```

### JavaScript / TypeScript — yarn 3 (corepack)
```bash
# corepack-managed yarn 通常不在 PATH，
# Skill 會用 detect_env_js.sh 解析的 pkg_manager_bin (如 node .yarn/releases/yarn-3.8.2.cjs)

corepack enable                          # 第一次啟用

yarn add axios@1.7.0                     # 更新 package.json + yarn.lock
yarn add --dev typescript@5.5.0
yarn up axios                            # 升到目前 range 內最新
```

### Go — go modules
```bash
# 一般升級 (minor / patch)
go get -u github.com/spf13/cobra@v1.8.0
go mod tidy

# 大版本跳躍 (v1 → v2+) — 需 rewrite import path
go get github.com/spf13/viper/v2@latest
# 同時把所有 *.go 的 import "github.com/spf13/viper" 改成 ".../v2"
go mod tidy

# 升級 indirect dep (lock-only 路徑)
go get -u golang.org/x/net@v0.20.0
go mod tidy

# CVE reachability 檢查
govulncheck ./...
```

---

## ❌ 常見錯誤

### Python

#### 錯誤 1: Poetry 只更新 lock
```bash
❌ poetry update requests  # 不會改 pyproject.toml
❌ poetry lock             # 不會改 pyproject.toml

✅ poetry add requests@2.32.0  # 同時更新兩者
```

#### 錯誤 2: UV 只更新 lock
```bash
❌ uv lock --upgrade-package requests  # 不會改 pyproject.toml

✅ uv add "requests>=2.32.0"  # 同時更新兩者
```

#### 錯誤 3: Pip 只安裝不更新檔案
```bash
❌ pip install --upgrade requests==2.32.0  # 不會寫入任何檔案

✅ 先編輯 requirements.txt (或 .in)，再執行對應命令
```

#### 錯誤 4: Pip 編輯錯誤的檔案
```bash
❌ vim requirements.txt  # 如果這是 pip-tools 的 lock 檔案!

✅ 檢查是否有 requirements.in，有的話編輯 .in 檔案
```

### JavaScript / TypeScript

#### 錯誤 5: 沒加 `--save` / `--save-dev`
```bash
❌ npm install axios@1.7.0  # 沒寫入 package.json (npm 7+ 預設會寫，但 6 不會)

✅ npm install axios@1.7.0 --save
```

#### 錯誤 6: 在 yarn 3 專案直接呼叫全域 yarn
```bash
❌ yarn add axios   # 用到全域舊版 yarn，與 .yarn/releases 不一致

✅ 啟用 corepack，或用 detect_env_js.sh 解析的 pkg_manager_bin
```

#### 錯誤 7: 手改 `package-lock.json` / `yarn.lock`
```bash
❌ 手動編輯 lock 檔案

✅ Skill 對 JS transitive 走 bump parent，而不是手改 lock
```

### Go

#### 錯誤 8: v1 → v2 沒 rewrite import path
```bash
❌ go get github.com/spf13/viper@v2.0.0   # 直接報錯 (module path 不同)

✅ go get github.com/spf13/viper/v2@latest
✅ 同時把所有 *.go 的 import 改成 ".../v2"
```

#### 錯誤 9: 忘記 `go mod tidy`
```bash
❌ 只跑 go get 不跑 go mod tidy → go.sum 留下垃圾

✅ go get 後一律 go mod tidy
```

---

## 📋 驗證更新

### Python — pip

#### pip-tools 模式
```bash
grep "requests" requirements.in        # 約束檔案 → requests==2.32.0
grep "requests" requirements.txt       # lock 檔案 → requests==2.32.0 (+ 子依賴)
```

#### 有 lock 檔案
```bash
grep "requests" requirements.txt       # 應該: requests==2.32.0
grep "requests" requirements.lock      # 應該: requests==2.32.0 (+ 子依賴)
```

#### 無 lock 檔案
```bash
grep "requests" requirements.txt       # 應該: requests==2.32.0
```

### Python — poetry
```bash
grep "requests" pyproject.toml         # 應該: requests = "^2.32.0"
poetry show requests                   # 應該: version : 2.32.0
```

### Python — uv
```bash
grep "requests" pyproject.toml         # dependencies: "requests>=2.32.0"
uv pip list | grep requests            # requests 2.32.0
```

### JavaScript / TypeScript
```bash
# npm
jq '.dependencies.axios' package.json         # "1.7.0"
jq '.packages."node_modules/axios".version' package-lock.json

# yarn 3
jq '.dependencies.axios' package.json
grep -A1 '"axios@' yarn.lock                  # 找該版本是否寫進 lock
```

### Go
```bash
grep "github.com/spf13/cobra" go.mod          # cobra v1.8.0
go list -m github.com/spf13/cobra             # cobra v1.8.0
go mod verify                                 # 驗證 go.sum 一致

# 大版本跳躍後
grep -rn "spf13/viper\"" .                    # 不該再有 v1 path
grep -rn "spf13/viper/v2" .                   # 應該全部改為 v2
```

---

## 🔍 快速診斷

### 症狀: Lock 檔案有新版本，但宣告檔是舊版本

**原因**: 使用了錯誤的命令

**修復**:
```bash
# Python — Poetry
poetry add <package>@<version>

# Python — UV
uv add "<package>>=<version>"

# JS — npm
npm install <package>@<version> --save

# JS — yarn 3
yarn add <package>@<version>

# Go
go get <module>@<version>; go mod tidy

# 然後 commit 兩個檔案
git add pyproject.toml poetry.lock        # 或對應的宣告 + lock
git commit -m "upgrade package to version"
```

### 症狀: Go v1 → v2 後 import 報 "module not found"

**修復**: 大版本 path 沒改。把所有 `*.go` 的舊 import path 加 `/v2`：

```bash
grep -rln "github.com/spf13/viper\"" --include="*.go" | \
  xargs sed -i 's|github.com/spf13/viper"|github.com/spf13/viper/v2"|g'
go mod tidy
```

### 症狀: corepack-managed yarn 找不到

```bash
corepack enable                          # 啟用 corepack
corepack prepare yarn@3.8.2 --activate   # 鎖定版本
# 或讓 Skill 直接用 detect_env_js.sh 解析出來的 pkg_manager_bin
```

---

## 🎫 Jira 觸發 (可選)

### 觸發方式

```
# 完整 URL
https://trendmicro.atlassian.net/browse/V1E-148968

# 純 issue key (前提:已設過 default site)
V1E-148968
```

### 流程

| Phase | 行為 |
|-------|------|
| 1.C | 解析 URL/key → 用 MCP 抓 ticket → 解析 package/版本 → 確認 ✋ |
| 2-6 | 標準升級流程 |
| 7.5 | Post 遷移報告 comment 回 ticket (確認後) ✋ |
| 7.6 | 詢問是否依目前狀態 transition (確認後) ✋ |

### MCP 不可用時

Skill 會詢問是否改用 REST API + token：
- Token 取得：<https://id.atlassian.com/manage-profile/security/api-tokens>
- ⚠️ Token 會出現在對話 transcript 中
- 完成後到 Atlassian 後台 revoke

### Done 同義詞 match 順序

`done` → `resolved` → `closed` → `completed` → `fixed`

(workflow 名稱 case-insensitive 比對。多個 match 時取第一個並列出其他選項。)

---

## 🛡️ Dependabot 批次 (可選)

### 觸發方式

```
# Dependabot 安全警示頁面 URL（github.com 或企業 GHE）
https://github.com/OWNER/REPO/security/dependabot

# 單一警示 → batch-of-one
https://github.com/OWNER/REPO/security/dependabot/123
```

### 流程

| Phase | 行為 |
|-------|------|
| 1.D | 解析 URL → `dependabot_fetch.py` 抓所有 open 警示 → 依語言/manifest 分組 → 出計畫 ✋ |
| 核可 | 選升哪些 (`all` / `crit+high` / 編號) + PR 怎麼包 (`per-package` / `per-group` / `combined`) ✋ |
| 2-6 | 對每個項目重用標準升級流程（帶 CVE context；單項失敗不中止整批） |
| 7 | 彙整批次摘要；每個 PR 加 `Dependabot:` / `GHSA:` / `CVE:` trailer |

### 認證

- 優先 `gh api`（沿用 `gh auth`，企業 host 走 `--hostname`）
- fallback：`GITHUB_TOKEN`（需 `security_events` scope）+ `requests`
- 補 scope：`gh auth refresh -h github.com -s security_events`

### 收斂規則

- 同套件多警示 → 一個目標版本（取最高 `first_patched`）
- 無 patched version → 列「無法自動修」，不臆造版本
- 非 pip/npm/go 的 ecosystem → 列「不支援」，排除升級
- 合併 PR 後 Dependabot 自動關閉警示，**不需要 API write-back**

---

## 📚 詳細文件

### Python
- **IMPORTANT_DEPENDENCY_UPDATE.md** - 完整說明與對比表
- **pip_workflow.md** / **poetry_workflow.md** / **uv_workflow.md** - 對應工具細節
- **PIP_LOCK_PATTERNS.md** - Pip lock 檔案模式

### JavaScript / TypeScript
- **js_workflow.md** - 整體 JS / TS 流程
- **npm_workflow.md** / **yarn_workflow.md** - 對應工具細節
- **js_ast_strategy.md** - JS AST 掃描策略
- **breaking_change_patterns_js.md** - JS breaking change pattern

### Go
- **go_workflow.md** - 整體 Go 流程
- **go_major_version_paths.md** - v1 → v2+ rewrite 規則
- **go_replace_semantics.md** - `replace` directive 處理
- **govulncheck.md** - reachability 分析
- **breaking_change_patterns_go.md** - Go breaking change pattern

### 跨語言
- **breaking_change_patterns.md** - 通用 pattern
- **jira_workflow.md** - Jira 整合詳細流程 (Phase 1.C, 7.5, 7.6)
- **dependabot_workflow.md** - Dependabot 批次模式詳細流程 (Phase 1.D)
- **bdsa_mapping.md** - BDSA → CVE 對應
- **auth_tokens.md** - 各種 auth token 的安全寫入方式
