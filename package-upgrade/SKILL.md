---
name: package-upgrade
description: >
  升級 Python 套件或修復 CVE 漏洞的完整工作流。當使用者提到
  「升級 package」、「更新套件」、「fix CVE」、「修復漏洞」、
  「package migration」、「dependency update」、「bump version」
  時觸發此 skill。也適用於使用者提供 CVE 編號 (如 CVE-2024-xxxxx)
  並希望修復的場景，以及提供 Atlassian Jira ticket URL
  (如 https://trendmicro.atlassian.net/browse/V1E-148968) 或
  Jira issue key (如 V1E-148968) — 此時會自動讀取 ticket 內容、
  分析應升級的套件、完成後將報告 comment 回 ticket，並依目前 ticket
  狀態提議推進 (To Do → Ready for Work → Development → Done)。
  支援 pip、poetry、uv 三種套件管理工具，
  自動偵測專案使用的工具。即使使用者只是隨口問「這個套件能不能升級」，
  也應觸發此 skill 來做完整分析。
---

# Package Upgrade / CVE Fix Skill

## 概觀

你是一位資深的 Python 套件遷移專家。當使用者要求升級套件或修復 CVE 時，
按照以下工作流程逐步執行。你自己就是分析引擎 — 不需要呼叫外部 LLM API。

關鍵原則:
- **在修改任何專案內容之前，必須先建立新的 Git 分支** (Phase 5.1)
- 每個步驟先用 helper script 取得結構化數據，再用你的推理能力分析
- 在修改任何檔案之前，先備份環境
- 測試程式的修改必須經過使用者確認
- 完成後建立 Pull Request 供 review
- 全程保持可回退
- **若觸發來源是 Jira ticket** (Phase 1 情況 C)，在整個 session 中保留
  `jira_context = { site_host, cloud_id, issue_key, url }`，
  完成後 (Phase 7.5/7.6) 將報告 comment 回 ticket、並依目前狀態
  分階段提議轉換 (To Do → Ready for Work、Ready for Work → Development，
  最後在使用者同意下才轉 Done)

---

## Phase 0: 環境偵測

執行 helper script 偵測專案環境:

```bash
bash scripts/detect_env.sh <project_path>
```

輸出為 JSON，包含:
- `pkg_manager`: pip | poetry | uv
- `python_version`: 例 3.11.4
- `lockfile_path`: 鎖定檔路徑 (如有)
- `pip_lock_file`: pip 專案的 lock 檔案 (如 requirements.lock)
- `has_pip_tools`: 是否使用 pip-tools (requirements.in)
- `dependency_files`: 依賴宣告檔清單

根據偵測到的 pkg_manager，讀取對應的 references 文件:
- pip → 讀 `references/pip_workflow.md`
- poetry → 讀 `references/poetry_workflow.md`
- uv → 讀 `references/uv_workflow.md`

**特別注意 pip 專案的 lock 檔案**:

如果偵測到 `pip_lock_file` 不為空,表示專案使用了 lock 機制:
- `requirements.in` + `requirements.txt` → 使用 pip-tools
- `requirements.txt` + `requirements.lock` → 使用自定義 lock
- `requirements.txt.lock` 或其他 `*.lock` → 自定義 lock 模式

**⚠️ 重要**: 在開始前,先閱讀 `references/IMPORTANT_DEPENDENCY_UPDATE.md`,
了解如何正確更新依賴檔案。關鍵要點:
- **pip**: 必須手動編輯 `requirements.txt` 或 `pyproject.toml`
- **poetry**: 使用 `poetry add pkg@version` (不是 `poetry update`)
- **uv**: 使用 `uv add "pkg>=version"` (不是 `uv lock --upgrade-package`)

---

## Phase 1: 輸入解析

### 情況 A: 使用者指定 package 名稱

直接進入 Phase 2。

### 情況 B: 使用者提供 CVE 編號

1. 用 web search 查詢 CVE 資訊:
   - 搜尋 `{CVE-ID} python package fix`
   - 搜尋 `site:osv.dev {CVE-ID}`
   - 搜尋 `site:nvd.nist.gov {CVE-ID}`

2. 從搜尋結果中提取:
   - 受影響的 package 名稱
   - 受影響的版本範圍
   - 修復版本
   - 嚴重性 (CVSS)
   - 漏洞描述

3. **你的分析任務** (這是你作為 LLM 的價值):
   - 閱讀 CVE 描述，理解漏洞的攻擊向量
   - 用 `grep -rn` 搜尋專案中對該 package 的使用方式
   - 判斷這個漏洞是否真的影響到專案的用法
   - 產出風險評估:
     - critical: 專案直接使用了受影響的功能
     - high: 專案間接使用了受影響的功能
     - medium: 專案使用了該 package 但不涉及漏洞路徑
     - low: 專案幾乎不使用受影響的功能
   - 將評估結果告知使用者

### 情況 C: 使用者提供 Jira URL 或 Jira ID

範例輸入:
- `https://trendmicro.atlassian.net/browse/V1E-148968`
- `V1E-148968`
- 任何包含 `/browse/<KEY>` pattern 的 URL

詳細流程請讀 `references/jira_workflow.md`。摘要如下:

#### Step 1.C.1: 解析輸入

用 regex 抽出:
- `site_host`: 例 `trendmicro.atlassian.net`
- `issue_key`: 例 `V1E-148968` (格式 `[A-Z][A-Z0-9]+-\d+`)

如果只給 issue key (沒有 URL):
- 先檢查 auto-memory 是否有先前儲存的 default site (reference type)
- 若有 → 直接使用
- 若無 → 詢問使用者並在使用者回答後將 site host 存到 memory

**組出完整 URL 並保留** (後續 Phase 7 commit/PR 必須引用):

```
issue_url = f"https://{site_host}/browse/{issue_key}"
```

範例: `https://trendmicro.atlassian.net/browse/V1E-148968`

這個 URL 是必須的 — 即使使用者一開始只給 issue key,也要在這一步補出完整連結,
並在 Phase 7.2 commit message 第一行、Phase 7.3 PR title/body 中明顯呈現,
讓 git web portal (GitHub/Bitbucket/GitLab) 上的 reviewer 一眼就能跳到 Jira ticket。

#### Step 1.C.2: 抓取 ticket 內容

**優先用 Atlassian MCP** (使用者多半已透過 claude.ai 連接):

```
mcp__claude_ai_Atlassian_Rovo__getJiraIssue(
  cloudId=<site_host>,           # 直接傳 site hostname; MCP 會自動解析
  issueIdOrKey=<issue_key>,
  responseContentFormat="markdown",
  fields=["summary", "description", "status", "labels", "comment"]
)
```

**權限失敗 fallback**: 若 MCP 回傳 401 / 403 / `unauthorized` / `not accessible`:

> 暫停並詢問使用者:
>
> 無法存取 `{site}/browse/{key}` (HTTP {status})。請選擇:
> - **[1]** 提供 Atlassian email + API token (我會用環境變數呼叫 Atlassian REST API,
>        token 只在這個 session 暫存,不會寫到任何檔案;⚠️ token 會出現在這個對話的 transcript 中)
> - **[2]** 我已在瀏覽器登入 Atlassian MCP 連線,請重試
> - **[3]** 我會手動貼上 ticket 的內容到對話中

若使用者選 [1]:
1. 詢問 email 和 API token (token 連結: `https://id.atlassian.com/manage-profile/security/api-tokens`)
2. 設定環境變數 `ATLASSIAN_EMAIL` 和 `ATLASSIAN_API_TOKEN`
3. 呼叫 `python scripts/jira_fetch.py <site_host> <issue_key>` 取得 JSON

#### Step 1.C.3: 分析 ticket 內容 (LLM 任務)

從 ticket 的 summary / description / comments / labels 中抽取:

- **目標 package 名稱** — 找以下 pattern:
  - `pkg==X.Y` / `pkg X.Y` / `upgrade <pkg>` / `bump <pkg>`
  - `affects <package>` / `<package> needs update`
  - 程式碼區塊中的 import 或 requirements 內容
  - 標題中明確提到的套件名

- **目標版本** (如有明確指定): `X.Y.Z` 或範圍 `>=X.Y`
- **CVE 編號** (若提到): 抽出 `CVE-XXXX-XXXXX` → 串接情況 B 的 CVE 流程
- **驗收條件** (Acceptance Criteria): ticket 描述中是否有明確的 done 條件

#### Step 1.C.4: 確認點 — 等待使用者校正

向使用者報告解析結果並暫停:

```
從 Jira ticket {KEY} 解析到:
- Ticket 標題: {summary}
- 狀態: {status}
- 分析結果:
  - 套件: {package_name}
  - 目標版本: {target_version} ({"明確指定" | "推論"})
  - 相關 CVE: {cve_id_if_any}
  - 驗收條件: {acceptance_criteria_if_any}

要繼續以這個套件 + 版本進行升級嗎？
[Y] 是, 繼續 Phase 2
[N] 不對, 我會告訴你正確的套件/版本
```

#### Step 1.C.5: 保存 jira_context

在 session 中保留:
```
jira_context = {
  "site_host": "trendmicro.atlassian.net",
  "cloud_id": "<resolved cloud id, or site_host if MCP accepted it>",
  "issue_key": "V1E-148968",
  "url": "https://.../browse/V1E-148968",
  "auth_mode": "mcp" | "rest_token",   # Phase 7.5/7.6 要用同一個方式
  "summary": "<for the comment header>"
}
```

---

## Phase 2: 依賴分析

### Step 2.1: 取得依賴樹

```bash
python scripts/dep_tree.py <project_path> <package_name>
```

輸出 JSON 包含:
- `dependency_type`: direct | transitive | both
- `current_version`: 目前使用的版本
- `parent_packages`: 如果是 transitive，哪些 direct pkg 引用它
- `version_constraints`: 各 parent 對此 pkg 的版本約束
- `full_tree`: 完整依賴子樹

### Step 2.2: 判斷升級路徑

根據 `dependency_type` 分支處理:

#### Type A — 直接引用

1. 用 web search 查 PyPI 上目標版本的 `python_requires`
   - 搜尋 `{package_name} {target_version} pypi python_requires`
   - 或 `web_fetch https://pypi.org/pypi/{package_name}/{target_version}/json`
2. 比對專案的 python 版本
3. 若相容 → 可升級，進入 Phase 3
4. 若不相容 → 告知使用者 Python 版本不滿足

#### Type B — 間接引用 (transitive)

> **核心原則**: transitive dependency 不應該動依賴宣告檔 (`pyproject.toml` /
> `requirements.txt`)。優先嘗試「只更新 lock 檔案」這條最小擾動路徑;
> 只有在 parent 的版本約束擋住目標版本時,才升級 parent (而且必須先問使用者)。

按以下順序判斷處理路徑,選定後在 Phase 5.3 對應執行:

**B-1. 檢查是否有 lock 檔案** (從 Phase 0 的 `lockfile_path` / `pip_lock_file`)

- ✅ 有 lock 檔案 → 進入 B-2
- ❌ 無 lock 檔案 → transitive 升級沒有意義 (重新解析時還是會回到舊版本),
  告知使用者並建議改為「升級直接依賴的 parent package」, 進入 B-4

**B-2. 檢查所有 parent 的版本約束是否允許目標版本**

對每個 parent package, 查 `version_constraints[parent]` 對此 transitive pkg 的約束:
- 用 web search / `pip index versions` / 解析 PyPI metadata 確認 parent 對此 pkg
  宣告的版本範圍 (如 `requests = ">=2.0,<3.0"`) 是否涵蓋 `target_version`

- ✅ 全部 parent 都允許 → 進入 B-3 (lock-only 升級)
- ❌ 至少一個 parent 鎖住版本不允許目標版本 → 進入 B-4 (詢問是否升級 parent)

**B-3. Lock-only 升級路徑** (parent 約束允許, 不動宣告檔)

報告給使用者並暫停確認:

```
{package} 是 transitive dependency, 由 {parent_list} 引用。
所有 parent 的版本約束都允許目標版本 {target_version}。

升級策略: 只更新 lock 檔案 ({lockfile_path}), 不動 pyproject.toml / requirements.txt。
這是最小擾動的方式, parent 不變、宣告不變, 只刷新被鎖定的解析結果。

繼續嗎?
[Y] 是, 進入 Phase 3 並在 Phase 5.3 走 lock-only 路徑
[N] 取消
```

使用者同意 → 在 session 中標記 `upgrade_strategy = "lock_only"`,
Phase 5.3 走對應的 lock-only 命令 (見 Phase 5.3 的「Transitive: lock-only 路徑」)。

**B-4. Parent 約束阻擋 → 詢問是否升級 parent**

> 這是新增的關鍵分支: 不要自己決定升級 parent, 永遠先問。

對每個阻擋的 parent, 收集以下資訊:
- parent 目前版本
- parent 對 target pkg 的約束 (例: `<2.0`)
- parent 的最新版本 (web search / PyPI)
- parent 的最新版本對 target pkg 的約束是否放寬

報告並暫停:

```
無法直接升級 transitive package {package} 到 {target_version},
因為以下 parent package 鎖定了 {package} 的版本:

| Parent | 目前版本 | 對 {package} 的約束 | parent 最新版本 | 升級後是否允許 |
|--------|---------|-------------------|---------------|-------------|
| {parent_a} | {ver} | {constraint} | {latest} | ✅/❌ |
| ...     |       |                  |             |        |

請選擇:
[1] 升級 parent package(s) 以放寬約束 (我會把每個 parent 當成新的升級目標跑一次完整流程)
[2] 放棄升級 {package}, 結束此次任務
[3] 我來決定 (告訴我具體要升哪些 parent / 跳過哪些)

注意: 升級 parent 會修改宣告檔 (pyproject.toml / requirements.txt),
影響範圍比 lock-only 大, 請確認後再繼續。
```

根據使用者選擇:
- 選 [1] → 對每個阻擋的 parent 遞迴執行 Phase 2 (作為新的升級目標, dependency_type 通常是 direct)
- 選 [2] → 紀錄到報告中、結束流程
- 選 [3] → 等使用者列出 parent 清單, 對每個跑 Phase 2~6

#### Type C — 直接 + 間接引用

最複雜的情況。你需要:
1. 先做 Type A 的 python 相容性檢查
2. 再檢查所有 parent 的版本約束 (走 Type B 的 B-2 / B-4 邏輯)
3. 因為 pkg 本身是直接依賴, 必須更新宣告檔, lock-only 路徑不適用
4. 如果有 parent 約束衝突 → 走 Type B 的 B-4 詢問流程

### Step 2.3: 衝突解決 (如有衝突)

**這是你作為 LLM 的關鍵價值所在。** 不要只給出機械式的「升級 parent」建議。

你要綜合分析整個依賴圖，考慮以下策略並排序:

1. **同時升級** — 能否同時升級衝突的 parent packages？
2. **版本範圍** — 是否有中間版本同時滿足所有約束？
3. **約束寬鬆** — 衝突是否只是宣告性的？(實際 API 相容但 parent 的 requirements 寫太緊)
4. **替代套件** — 是否有 drop-in replacement 可以繞過衝突？
5. **分階段升級** — 先升到某個中間版本，再升到目標版本
6. **Override** — 使用 pip --force / poetry 的 dependency overrides

對每個方案給出:
- 具體操作步驟
- 風險評估
- 預估工作量

然後 **暫停，等使用者選擇方案** 再繼續。

---

## Phase 3: Breaking Change 分析

> **這是整個流程中你的 LLM 能力最重要的階段。**
> 你需要同時從 Changelog 和 Git Diff 兩個維度分析，然後合併結果。

### Step 3.1: Changelog 分析

```bash
python scripts/fetch_changelog.py <package_name> <git_repo_url>
```

script 會嘗試以下來源並輸出原文:
- PyPI metadata 中的 changelog URL
- GitHub Releases API
- 常見路徑: CHANGELOG.md, CHANGES.rst, HISTORY.md

**先抓 metadata header**: stdout 開頭有兩行 HTML comment:

```
<!-- changelog_source_label: ... -->
<!-- changelog_source_url: ... -->
```

**在 session 中保留** `changelog_source = { label, url }` (若 `NOT_FOUND` → 記為 missing)。
這要在 Phase 7.1 報告中明確列出, 不可省略。

**你的分析任務:**

拿到 changelog 原文後，你要:

1. 定位從 `current_version` 到 `target_version` 之間的所有條目
2. 逐條分類:
   - 🔴 BREAKING — API 刪除、更名、行為變更、預設值變更
   - 🟡 DEPRECATED — 標記為棄用但仍可用
   - 🟢 FEATURE — 新增功能
   - ⚪ FIX — Bug 修復

3. **特別注意隱含 breaking change 的措辭** (讀 `references/breaking_change_patterns.md`):
   - "improved default behavior" → 預設行為變更
   - "now returns X instead of Y" → 回傳型別變更
   - "parameter X is now required" → 簽名變更
   - "moved from A to B" → 模組路徑變更

4. 對每個 BREAKING/DEPRECATED 條目，記錄:
   - 影響的模組路徑和符號
   - 舊用法 → 新用法
   - 你的信心分數 (0.0~1.0)

### Step 3.2: Git Diff 分析

```bash
bash scripts/git_diff.sh <git_repo_url> <current_version> <target_version>
```

輸出: stdout 開頭的 metadata header + 兩個版本 tag 之間的 `*.py` diff

**先抓 metadata header**: stdout 前幾行是 HTML comment, 形如:

```
<!-- git_diff_repo_url: https://github.com/owner/repo -->
<!-- git_diff_old_version: 2.28.0 -->
<!-- git_diff_new_version: 2.32.0 -->
<!-- git_diff_old_tag: v2.28.0 -->
<!-- git_diff_new_tag: v2.32.0 -->
<!-- git_diff_old_sha: <40-char SHA> -->
<!-- git_diff_new_sha: <40-char SHA> -->
<!-- git_diff_compare_url: https://github.com/owner/repo/compare/v2.28.0...v2.32.0 -->
```

**在 session 中保留** `git_diff_source = { repo_url, old_version, new_version,
old_tag, new_tag, old_sha, new_sha, compare_url }`。Phase 7.1 報告必須引用這組數值
(尤其是 old_sha / new_sha 和 compare_url), 不可只寫版本號就帶過。

**你的分析任務:**

> 這是 AST 做不到、只有 LLM 能做的部分。

如果 diff 很大，分批閱讀 (每次一個檔案或一組相關檔案)。
聚焦在以下 public API 變更:

1. **被刪除的** public function / class / method
2. **函式簽名變更** — 參數增減、預設值改變、type hint 變更
3. **回傳值型別變更** — 例: list → generator (會影響 len/index 操作)
4. **行為邏輯變更** — 同一函式的輸出結果不同
5. **預設參數值變更** — 例: timeout 從 None 改為 30
6. **Exception 類型變更** — 例: ValueError 改為 TypeError
7. **`__all__` 清單變更** — 影響 `from pkg import *`
8. **新增 `warnings.warn` / `@deprecated`** — 標記即將棄用

判斷準則:
- `_` 開頭的是 private → 忽略
- 新增帶預設值的參數 → 通常不 breaking
- 刪除參數或改變順序 → breaking

### Step 3.3: 合併分析結果

將 Changelog 和 Git Diff 兩份分析合併:
- **去重**: 同一個變更可能兩邊都提到
- **交叉驗證**: 兩邊都提到 → 信心提高
- **補充**: Diff 發現但 changelog 沒提 → 標記為「未記錄的 breaking change ⚠️」
- **按影響程度排序**: 刪除 > 簽名變更 > 行為變更 > 棄用

產出最終的 breaking changes 清單，格式:

```
## Breaking Changes 清單

### 🔴 BC-001: `module.func_name` 已被移除
- 來源: Changelog ✅ + Git Diff ✅
- 信心: 0.98
- 舊用法: `from pkg.module import func_name`
- 新用法: `from pkg.module import new_func_name`
- 遷移說明: ...

### 🟡 BC-002: `module.old_api` 標記為棄用
- 來源: Git Diff ✅ (Changelog 未記錄 ⚠️)
- 信心: 0.75
- 說明: 新增了 DeprecationWarning，建議改用 new_api
```

---

## Phase 4: 專案程式碼影響分析

### Step 4.1: AST 掃描

```bash
python scripts/ast_scanner.py <project_path> <package_name>
```

輸出 JSON，包含每個 .py 檔案中:
- import 了 package 的哪些模組
- 使用了哪些 symbol (函式、類別、常數)
- 使用的行號
- 周圍 ±5 行的程式碼上下文

### Step 4.2: 交叉比對

將 AST 掃描結果與 Phase 3 的 breaking changes 清單交叉比對，
找出專案中實際受影響的程式碼位置。

### Step 4.3: 生成修改建議

**這是你作為 LLM 的核心價值 — 不只標記問題，還要提供解法。**

對每個受影響的程式碼位置:

1. 閱讀周圍上下文 (至少前後 10 行)
2. 理解這段程式碼的業務邏輯意圖
3. 結合 breaking change 的遷移說明
4. 生成具體的修改程式碼 (不是泛泛的建議)
5. 確保:
   - 保持原有的程式碼風格 (縮排、引號、命名)
   - 新的 import 路徑正確
   - 如有多種修改方式，選最簡潔且向後相容的
   - 不修改與 breaking change 無關的程式碼

6. 以 unified diff 格式展示每處修改

### Step 4.4: 預覽確認

將所有待修改的檔案和 diff 展示給使用者，**暫停等待確認** 再繼續。

列出:
- 總共影響 N 個檔案、M 處修改
- 每個檔案的修改摘要
- 完整的 diff 預覽

---

## Phase 5: 執行升級

### Step 5.1: 建立 Git 分支

**在修改任何專案內容之前，必須先建立新的 feature 分支。**

分支命名取決於觸發類型 — **若有 `jira_context`,issue key 一律放在最前面**,
讓 git 端 (branch list / PR list / `git log --all`) 可以直接掃到 Jira ticket。

#### 一般升級 (沒有 Jira / 沒有 CVE)

```bash
git checkout -b feature/Update-{PackageName}-to-{TargetVersion}
```

範例:
```bash
git checkout -b feature/Update-requests-to-2.32.0
git checkout -b feature/Update-django-to-5.1
```

#### CVE 修復 (沒有 Jira)

```bash
git checkout -b fix/CVE-{CVE-ID}-{PackageName}
# 範例: git checkout -b fix/CVE-2024-35195-cryptography
```

#### Jira 觸發 (Phase 1 情況 C)

```bash
# 一般升級
git checkout -b feature/{ISSUE_KEY}-Update-{PackageName}-to-{TargetVersion}

# CVE 修復 + Jira (兩者都有時, Jira 優先放最前面)
git checkout -b fix/{ISSUE_KEY}-CVE-{CVE-ID}-{PackageName}
```

範例:
```bash
git checkout -b feature/V1E-148968-Update-requests-to-2.32.0
git checkout -b fix/V1E-148968-CVE-2024-35195-cryptography
```

**為什麼 Jira ID 放最前面**:
- `git branch --list 'feature/V1E-*'` 可以一次列出某個 epic / project 的所有分支
- PR 列表頁排序後同一 ticket 的相關 branch 會聚在一起
- 配合 Phase 7.2 commit 的 `[<issue_key>]` 前綴、Phase 7.3 PR title 的 `[<issue_key>]` 前綴,
  branch / commit / PR 三層都能一眼追到 Jira ticket

**字元限制**: 分支名只用 `[A-Za-z0-9._-]`,不要放空白或中文。
若 `{PackageName}` 含特殊字元 (例 `python-dateutil`),保留原 `-` 即可。

### Step 5.2: 環境備份

```bash
bash scripts/snapshot_env.sh <project_path> save
```

### Step 5.3: 更新依賴宣告檔

**先決定走哪條路徑** (來自 Phase 2.2):

- `upgrade_strategy == "lock_only"` (Type B, parent 約束允許)
  → 走下方「Transitive: lock-only 路徑」, **不要動 pyproject.toml / requirements.txt**
- 其他情況 (Type A 直接引用、Type C 直接+間接、Type B 升級 parent)
  → 走下方「Direct: 同時更新宣告檔 + lock」

---

#### Transitive: lock-only 路徑

> 目標: 只刷新 lock 檔案中該 transitive pkg 的版本, 不動依賴宣告檔。
> 這條路徑只在 parent 的版本約束已經允許目標版本時才走。

**For poetry**:
```bash
# 只更新 lock, pyproject.toml 不變
poetry update <package>
# 或更精準: 只重新解析這一個 pkg
# poetry update --lock <package>   # 視 poetry 版本而定
```

**For uv (專案模式)**:
```bash
# 只升級 lock 中的特定 pkg, pyproject.toml 不動
uv lock --upgrade-package <package>
# 同步到環境 (不會修改 pyproject.toml)
uv sync
```

**For pip (有 lock 檔案)**:

依 lock 檔案類型:
- pip-tools: `pip-compile --upgrade-package <package> requirements.in`
  (注意: 不要編輯 requirements.in, 只升級指定 transitive pkg)
- 自定義 lock (如 requirements.lock): 需要詢問使用者如何重新產生 lock,
  常見方式 `pip install --upgrade <package>==<target_version> && pip freeze > <lock_file>`

**驗證 lock-only 結果**:
- ✅ 確認依賴宣告檔 (`pyproject.toml` / `requirements.txt` / `requirements.in`)
  在 `git diff` 中**沒有變化**
- ✅ 確認 lock 檔案中該 pkg 版本已更新到 target
- 若宣告檔也被改到 → 還原宣告檔的變更 (`git checkout -- <file>`),
  保留 lock 變更

---

#### Direct: 同時更新宣告檔 + lock

**重要**: 必須同時更新依賴宣告檔和鎖定檔案,不能只更新鎖定檔案!

根據 pkg_manager 執行對應的更新命令:

#### For pip:

**檢查是否有 lock 檔案** (從 Phase 0 的 `pip_lock_file` 欄位):

**情況 A: 使用 pip-tools (有 requirements.in)**

```bash
# 1. 手動編輯 requirements.in
# 例: requests==2.28.0 → requests==2.32.0

# 2. 重新編譯產生 requirements.txt (lock 檔案)
pip-compile requirements.in --output-file requirements.txt

# 或只升級特定套件
pip-compile --upgrade-package requests requirements.in

# 3. 安裝
pip-sync requirements.txt
```

**如果沒有 pip-compile 命令**:
```bash
pip install pip-tools
```

**情況 B: 有自定義 lock 檔案 (如 requirements.lock)**

**暫停並詢問使用者**:
```
偵測到專案使用 lock 檔案: {pip_lock_file}

請確認更新流程:
1. 更新 requirements.txt 中的版本約束
2. 重新產生 {pip_lock_file}

產生 lock 檔案的方式:
a) 使用 pip freeze: pip install -r requirements.txt && pip freeze > {pip_lock_file}
b) 使用專案自定義腳本 (如 make lock)
c) 手動管理

請選擇:
[1] 自動執行方式 a (pip freeze)
[2] 告訴我使用哪個腳本
[3] 我會手動處理,繼續下一步
```

根據使用者選擇執行對應操作。

**情況 C: 無 lock 檔案 (只有 requirements.txt)**

```bash
# 1. 手動編輯 requirements.txt
# 例: requests==2.28.0 → requests==2.32.0

# 2. 安裝新版本
pip install --upgrade <package>==<version>

# 或從檔案安裝
pip install -r requirements.txt
```

#### For poetry:

```bash
# 使用 poetry add 自動更新 pyproject.toml 和 poetry.lock
poetry add <package>@<version>

# 範例
poetry add requests@2.32.0
```

**`poetry add` 會自動**:
1. ✅ 更新 `pyproject.toml` 中的版本約束
2. ✅ 更新 `poetry.lock`
3. ✅ 安裝新版本

**不要只執行 `poetry lock` 或 `poetry update`**,這些命令不會修改 `pyproject.toml`!

#### For uv (專案模式):

```bash
# 使用 uv add 自動更新 pyproject.toml 和 uv.lock
uv add "<package>>=<version>"

# 範例
uv add "requests>=2.32.0"
# 或精確版本
uv add "requests==2.32.0"
```

**`uv add` 會自動**:
1. ✅ 更新 `pyproject.toml` 的 dependencies 列表
2. ✅ 更新 `uv.lock`
3. ✅ 安裝新版本

**不要只執行 `uv lock --upgrade-package`**,這只會更新鎖定檔案,不會更新 `pyproject.toml`!

#### For uv (傳統 pip 模式):

```bash
# 1. 手動編輯 requirements.txt
# 例: requests==2.28.0 → requests==2.32.0

# 2. 安裝新版本
uv pip install -r requirements.txt
```

**驗證更新**:

更新後,檢查以下檔案確認版本已正確更新:

- pip: `requirements.txt` 或 `pyproject.toml`
- poetry: `pyproject.toml` (檢查 `[tool.poetry.dependencies]`) 和 `poetry.lock`
- uv: `pyproject.toml` (檢查 `dependencies` 列表) 和 `uv.lock`

### Step 5.4: 套用程式碼修改

使用 file editing 工具 (str_replace) 逐一套用 Phase 4 確認的修改。

---

## Phase 6: 測試驗證

### Step 6.1: 識別相關測試

根據 affected_files 推斷對應的 test 檔案:
- `src/foo/bar.py` → `tests/test_bar.py` 或 `tests/foo/test_bar.py`
- 也檢查 `conftest.py` 中對該 package 的 fixture

### Step 6.2: 分層執行測試

```bash
# 第一輪: 只跑受影響的測試
bash scripts/run_tests.sh <project_path> --files <test_files>

# 第二輪 (若第一輪通過): 跑完整測試
bash scripts/run_tests.sh <project_path> --all
```

### Step 6.3: 測試失敗診斷

> **這是你作為 LLM 第二重要的分析任務。**

如果有測試失敗，你需要做 **三向交叉分析**:

1. 閱讀完整的 pytest traceback
2. 閱讀失敗測試的原始碼
3. 閱讀被測試的業務程式碼 (source code)
4. 參照本次升級的 breaking changes 清單

然後對每個失敗的測試判斷:

**根因分類:**
- `SOURCE_CODE` — 業務程式碼還需要修改 (Phase 4 漏掉的)
- `TEST_CODE` — 測試程式碼需要修改 (測試了已變更的行為)
- `BOTH` — 兩者都需要修改
- `CONFIG` — 配置問題 (fixture、conftest、mock 設定)

**判斷準則:**
- ImportError / ModuleNotFoundError → 通常是 SOURCE_CODE
- AssertionError 且 assert 值反映行為變更 → TEST_CODE
- TypeError (參數不匹配) → 看是業務碼還是測試碼直接呼叫
- 測試 mock 了被變更的 API → TEST_CODE
- 測試直接呼叫了被刪除的 API → TEST_CODE

### Step 6.4: 處理測試失敗

#### 如果是 SOURCE_CODE 問題:
- 生成額外的程式碼修改
- 套用修改
- 重新跑測試

#### 如果是 TEST_CODE 問題:
- **必須暫停，等使用者確認**
- 向使用者解釋:
  - 為什麼這個測試需要改 (不是 bug，而是上游行為的預期變更)
  - 具體要怎麼改
  - 改後的測試仍然在驗證什麼
- 使用者確認後才修改測試
- 修改後重新跑測試

### Step 6.5: 迴圈

重複 6.2 ~ 6.4 直到所有測試通過 (或使用者決定停止)。

最大迴圈次數: 3 次。超過 3 次仍有失敗 → 停下來，把所有資訊報告給使用者。

---

## Phase 7: 產出報告與 Commit Message

### Step 7.1: 遷移報告

> 不要用模板填空。用你自己的語言，寫一份有邏輯、有重點的報告。

報告結構 (參照 `templates/report_structure.md` 但不要死板照抄):

1. **Executive Summary** — 3-5 句話總結整個升級
   - 升了什麼、從哪個版本到哪個版本、為什麼
   - 有幾個 breaking changes、影響了幾個檔案
   - 測試結果

2. **Breaking Change 分析來源** — **必填、必須具體**

   這個章節證明分析有根據, 不是憑空生成。格式:

   ```markdown
   ### 📚 Changelog 來源
   - 來源類型: {label, e.g. "GitHub Releases API" / "PyPI project_urls[Changelog]" / "Repo file (main/CHANGELOG.md)"}
   - URL: {實際 URL, 從 `changelog_source.url` 取}
   - 狀態: ✅ 找到 / ❌ 未找到 (若未找到, 說明已嘗試的所有來源)

   ### 🔬 Git Diff 雙軌分析
   - Repository: {git_diff_source.repo_url}
   - 舊版本: `{old_version}` → tag `{old_tag}` → commit `{old_sha[:12]}` (完整 SHA: {old_sha})
   - 新版本: `{new_version}` → tag `{new_tag}` → commit `{new_sha[:12]}` (完整 SHA: {new_sha})
   - Compare URL: {compare_url}
   - 涵蓋檔案: 僅 `*.py` (Python 原始碼差異)
   ```

   - Changelog 找不到時, 不要省略此章節 — 改寫「狀態: ❌ 未找到」並列出已嘗試的來源,
     讓 reviewer 知道分析只靠 Git Diff
   - Git tag 找不到時, 把 `git tag --list` 的最近結果列在此節, 說明退而用何種替代 (例如最近的 release commit)

3. **依賴分析** — 引用類型、衝突處理

4. **Breaking Changes 詳情** — 每個變更的影響和解決方式
   - 每個 BC 條目仍要標 `來源: Changelog ✅/❌ + Git Diff ✅/❌` (見 Phase 3.3)
   - 有引用具體 commit 時用 `<short_sha>` 連到 `{repo_url}/commit/{sha}`

5. **程式碼修改清單** — 每個檔案改了什麼、為什麼

6. **測試結果** — 通過/失敗、是否修改了測試程式

7. **後續建議** — 還有哪些相關套件可能需要更新

8. **回退指南** — 如果需要回退，怎麼做

### Step 7.2: Git Commit Message

寫一個符合 Conventional Commits 規範的 commit message (英文):

- 第一行: `type(scope): description` (≤72 字元)
- Body: 解釋「為什麼」(不只是「做了什麼」)
- 如果是 CVE: 包含 CVE 編號和嚴重性
- 如果有 BREAKING CHANGE: 使用 footer

**若有 `jira_context` (Phase 1 情況 C 觸發)**:

第一行必須以 `[<issue_key>]` 開頭,讓 git history 一眼可追到 Jira ticket。
Body 中加上 `Jira: <issue_url>` 一行 (用完整 URL,不要只寫 issue key),
這在 GitHub/Bitbucket/GitLab 的 commit 頁面會自動 render 成可點擊連結。

格式:
```
[<issue_key>] type(scope): description

<body — 為什麼這樣做>

Jira: <issue_url>
```

範例:
```
[V1E-148968] chore(deps): upgrade requests from 2.28.0 to 2.32.0

Bumps requests to address CVE-2024-35195 (high severity, urllib3
session cert verification bypass). Touches 3 files in services/http/.

Jira: https://trendmicro.atlassian.net/browse/V1E-148968
```

**注意**: `[<issue_key>]` 含括號是慣例,即使會讓第一行略長也保留 — 這個前綴是
讓 commit log (`git log --oneline`) 可掃描的關鍵。72 字元上限以 description
本身計算 (不含 `[KEY] ` 前綴)。

### Step 7.3: 建立 Pull Request

將所有變更 commit 後,建立 Pull Request:

```bash
# Commit 所有變更
git add .
git commit -m "<Phase 7.2 產生的 commit message>"

# Push 到遠端
git push -u origin feature/Update-{PackageName}-to-{TargetVersion}

# 建立 PR (如有 gh CLI)
gh pr create --title "chore: upgrade {package} to {version}" \
  --body "$(cat <migration_report.md>)"
```

**若有 `jira_context`**:

PR title 必須以 `[<issue_key>]` 開頭,PR body **第一行** 必須是
`Jira: <issue_url>` (完整 URL),讓 reviewer 在 GitHub/Bitbucket/GitLab
PR 列表頁直接看得到 Jira link、不用點進 description 才找到。

```bash
gh pr create \
  --title "[<issue_key>] chore: upgrade {package} to {version}" \
  --body "$(cat <<'EOF'
Jira: <issue_url>

<Phase 7.1 完整遷移報告>
EOF
)"
```

範例:
```
Title: [V1E-148968] chore: upgrade requests to 2.32.0
Body 開頭:
  Jira: https://trendmicro.atlassian.net/browse/V1E-148968

  ## Executive Summary
  ...
```

PR 內容應包含:
- **(若有 jira_context) PR title 前綴 `[<issue_key>]` + body 第一行 `Jira: <issue_url>`**
- Phase 7.1 產生的完整遷移報告作為 PR description (接在 Jira link 之後)
- 標記為 `dependencies` / `security` label (如果是 CVE 修復)
- 指定 reviewers (如有需要)

### Step 7.4: Jira 整合 — 條件門檻

Step 7.5 和 7.6 **只在以下條件全部成立時才執行**:

- `jira_context` 存在 (Phase 1 情況 C 觸發)
- Phase 6 測試全部通過 (沒有遺留失敗)
- Phase 4 程式碼修改已套用
- Phase 7.3 已建立 commit/PR (即使 PR 建立失敗,只要 commit 已 push 也算)

**任何一項不成立 → 跳過 7.5 和 7.6**,直接進到 7.7。
不要在升級未完成的狀態下動 Jira ticket。

### Step 7.5: 將遷移報告 Comment 回 Jira ticket

詳細格式請參考 `references/jira_workflow.md` 的「Comment Template」章節。

#### 7.5.1: 組裝 comment 內容

Markdown 格式,結構:

```markdown
## 🤖 Automated upgrade by Claude Code

**Package**: `{package}` `{old_version}` → `{new_version}`
**Branch**: `{branch_name}`
**PR**: {pr_url_or_"未建立"}
**Commit**: `{commit_sha}`
**Tests**: ✅ Passed ({test_count} tests) | ❌ {failed_count} failures

### Executive Summary
{Phase 7.1 第一節原文}

### Breaking Changes
- 處理 {N} 個 breaking changes
- 修改 {M} 個檔案、{K} 處變更
- 詳情見 PR description 或 attached report

### Acceptance Criteria
{若 Phase 1.C.3 抽到 acceptance criteria,逐條標記 ✅/❌/N/A}

---
*Generated by [package-upgrade skill](https://github.com/.../package-upgrade-skill)*
```

#### 7.5.2: 確認點 — 暫停等待使用者同意

> Jira comment 對 ticket watchers 可見,可能觸發 SLA / 通知,務必先確認。

```
即將將上述報告 comment 到 Jira ticket {KEY}:
{url}

預覽:
---
{comment_body}
---

繼續嗎?
[Y] 是, post comment
[E] 我想先編輯 comment 內容
[N] 不要 post, 只完成本機操作
```

#### 7.5.3: 執行 post

根據 `jira_context.auth_mode`:

**MCP 模式**:
```
mcp__claude_ai_Atlassian_Rovo__addCommentToJiraIssue(
  cloudId=<jira_context.cloud_id>,
  issueIdOrKey=<jira_context.issue_key>,
  commentBody=<assembled markdown>,
  contentFormat="markdown"
)
```

**REST token 模式**:
```bash
ATLASSIAN_EMAIL=... ATLASSIAN_API_TOKEN=... \
  python scripts/jira_comment.py <site> <issue_key> <comment_file>
```

若 post 失敗 → 不要重試自動,把組好的 comment body 完整輸出給使用者,告知失敗原因,
讓使用者決定是手動貼上還是放棄。**繼續到 7.6** (post 失敗不 block transition,但會在
prompt 中如實告知)。

### Step 7.6: 依目前狀態推進 Jira ticket

#### 7.6.1: 取得可用 transitions

**MCP 模式**:
```
mcp__claude_ai_Atlassian_Rovo__getTransitionsForJiraIssue(
  cloudId=<cloud_id>,
  issueIdOrKey=<issue_key>
)
```

**REST 模式**:
```bash
python scripts/jira_transition.py list <site> <issue_key>
```

#### 7.6.2: 依 `current_status` 決定目標 transition

依 ticket **目前狀態** (case-insensitive) 走以下分支:

| 目前狀態 | 第一步 (預設推薦) | 第一步完成後 | 備註 |
|----------|--------------------|--------------|------|
| `To Do` / `Todo` / `Open` | `Ready for Work` | 接著 7.6.4 詢問是否再轉 `Done` | 兩段式:中間態 → Done |
| `Ready for Work` | `Development` / `In Progress` | 接著 7.6.4 詢問是否再轉 `Done` | 兩段式:中間態 → Done |
| 其他 (`Development` / `In Progress` / `Code Review` / ...) | match Done 同義詞 (見下) | — | 單段式,直接走原本 Done 流程 |

**Done 同義詞 match 順序** (case-insensitive,比對 transition `name` 與 `to_status`):

1. `done`
2. `resolved`
3. `closed`
4. `completed`
5. `fixed`

**中間態 transition match**:
- `Ready for Work`: 比對 transition `name` / `to_status` 為 `ready for work` (case-insensitive)
- `Development`: 依序比對 `development`, `in development`, `in progress`,取第一個 match

若任一階段找不到對應 transition → 列出所有可用 transitions 讓使用者挑,
不要硬塞或猜測。

#### 7.6.3: 第一段確認 — 中間態 transition

> 永遠不要自動 transition,即使使用者 7.5 已同意 post comment。
> 狀態變更可能觸發 release notes、SLA 計時、自動通知等下游效應。

`current_status` 為 `To Do` 或 `Ready for Work` 時,先問中間態:

```
升級已完成 ✅
- 套件: {package} {old} → {new}
- 測試: 全部通過 ({n} tests)
- PR: {pr_url}
- Comment 已 post 到 Jira: {comment_url_if_available}

目前 ticket {KEY} 狀態為 `{current_status}`。
是否將狀態推進至 `{intermediate_target_name}`?

[Y] 是, 轉為 {intermediate_target_name}
[O] 轉為其他狀態 (顯示完整 transition 清單)
[N] 否, 保持 {current_status} (跳過後續 Done 詢問)
```

若使用者選 [N] → **不再問 Done**,直接進到 7.7。
若使用者選 [Y] / [O] → 執行 transition (見 7.6.5),完成後進到 7.6.4。

對於非 `To Do` / `Ready for Work` 的目前狀態,**跳過 7.6.3**,直接進入 7.6.4
(套用單段式 Done 流程)。

#### 7.6.4: 第二段確認 — 是否轉為 Done

進到此步驟的兩種情境:
- (a) 已完成 7.6.3 的中間態 transition (此時 `current_status` 已更新)
- (b) 目前狀態本來就不是 `To Do` / `Ready for Work` (跳過 7.6.3)

```
是否再將 Jira ticket {KEY} 從 `{current_status}` 轉為 `{done_transition_name}`?

[Y] 是, 轉為 {done_transition_name}
[O] 轉為其他狀態 (顯示完整 transition 清單)
[N] 否, 保持 {current_status}
```

若 Done 同義詞找不到 match (workflow 不允許從目前狀態直接到 Done) →
列出可用 transitions 讓使用者選,或選 [N] 維持現狀。

#### 7.6.5: 執行 transition

7.6.3 與 7.6.4 中使用者選 [Y] / [O] 時,共用此實作。

**處理 resolution field** (僅在 transition 到 Done 類狀態時):
- 升級類型若為 CVE 修復 → 預設 `resolution: "Fixed"`
- 一般升級 → 預設 `resolution: "Done"`
- 若 transition 不需要 resolution → 不設 fields
- 中間態 transition (Ready for Work / Development) → 通常**不需要** resolution,不要設

**MCP 模式**:
```
mcp__claude_ai_Atlassian_Rovo__transitionJiraIssue(
  cloudId=<cloud_id>,
  issueIdOrKey=<issue_key>,
  transition={"id": "<transition_id>"},
  fields={"resolution": {"name": "Fixed"}}   # 視 workflow 而定,中間態通常不設
)
```

**REST 模式**:
```bash
python scripts/jira_transition.py apply <site> <issue_key> <transition_id> [resolution_name]
```

若 transition 因 workflow 限制失敗 (例如必填欄位、permission):
- 將錯誤訊息和該 ticket 的瀏覽器 URL 完整告訴使用者
- 不重試,不繞過,讓使用者手動處理
- 中間態若失敗 → **不要自動繼續**詢問 Done,先讓使用者排除問題

### Step 7.7: 完成

將報告輸出給使用者，並提供:
1. 報告全文
2. 已建立的 commit 和 branch 資訊
3. Pull Request URL (如已建立)
4. **若有 jira_context**: comment URL 和最終 ticket status
5. 回退命令 (以防需要)

---

## 錯誤處理

- **Changelog 抓不到**: 只依賴 git diff 分析，告知使用者
- **Git repo 找不到**: 只依賴 changelog，告知使用者
- **兩者都失敗**: 用 web search 搜尋 breaking changes 資訊
- **測試持續失敗**: 3 次迴圈後停止，報告給使用者
- **環境損壞**: 用 snapshot_env.sh restore 回退

```bash
# 回退命令
bash scripts/snapshot_env.sh <project_path> restore
```

---

## 使用者確認點一覽

在以下時間點，你必須暫停等待使用者確認，不可自動繼續:

| 時間點 | 你要提供的資訊 |
|--------|-------------|
| Phase 1.C.4: Jira ticket 解析結果 | 抽到的 package/版本/CVE/驗收條件,等使用者校正 |
| Phase 2.2 B-3: Transitive lock-only 升級確認 | 套件是 transitive、parent 允許,僅更新 lock 不動宣告檔 |
| Phase 2.2 B-4: Parent 阻擋升級的決策 | parent 約束擋住,問使用者升級 parent / 放棄 / 自選 |
| Phase 2.3: 衝突解決方案 | 多種方案 + 風險評估 + 推薦 |
| Phase 4.4: 程式碼修改預覽 | 完整 diff + 每處修改的理由 |
| Phase 5.1: 建立 Git 分支 | 分支名稱、即將開始修改 |
| Phase 6.4: 測試程式修改 | 為什麼要改 + 改後仍驗證什麼 |
| Phase 7.3: 建立 Pull Request | PR 資訊、是否建立 PR |
| Phase 7.5.2: 將報告 Comment 回 Jira | comment 預覽 + ticket URL |
| Phase 7.6.3: Jira 中間態 transition (TODO→Ready for Work / Ready for Work→Development) | 目前狀態 + 中間目標,絕不自動執行 |
| Phase 7.6.4: 是否將 Jira status 轉為 Done | 目標狀態 + 目前狀態,絕不自動執行 |
