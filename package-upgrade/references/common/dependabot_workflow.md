# Dependabot Batch Workflow（Phase 1 情況 D）

> 觸發來源：使用者提供 GitHub **Dependabot 安全警示**頁面 URL，例如
> `https://github.com/millerlai/auto-package-migration/security/dependabot`。
>
> 與情況 A/B/C（單一套件）最大的不同：Dependabot 是 **一對多** 來源 —— 一次帶出
> 一批待升套件（可能跨 Python / JS / Go 與多個 manifest）。本流程的核心交付是：
> **把警示分組成一份升級計畫 → 讓使用者核可 → 逐項驅動既有 Phase 2–7 升級。**
>
> ℹ️ **目前狀態**：抓取 + 分組（§2、§3，`dependabot_fetch.py`）與批次編排迴圈
> （§4–§7：核可關卡 → 逐項驅動 Phase 2–7 → 彙整報告）**皆已定義可執行**。仍待補的
> 只剩 `verify_installation.{sh,bat}` 串接（§8）與 README/QUICK_REFERENCE 說明。

本文件只處理 **security alerts**（`/security/dependabot` 頁面，每筆都帶 GHSA/CVE +
patched version）。Dependabot 的 **version updates**（PR 分頁，無 REST 查詢 API）
不在範圍內。

---

## 1. 輸入解析

### 1.1 支援的輸入格式

```
# 警示列表頁（最常見）
https://github.com/<owner>/<repo>/security/dependabot

# 單一警示
https://github.com/<owner>/<repo>/security/dependabot/<number>

# 企業版 GHE host
https://<ghe-host>/<owner>/<repo>/security/dependabot
```

### 1.2 Regex pattern

```python
r'https?://(?P<host>[^/]+)/(?P<owner>[^/]+)/(?P<repo>[^/]+)/security/dependabot(?:/(?P<number>\d+))?'
```

抽出 `host` / `owner` / `repo` / 可選 `number`：

- `host == "github.com"` → 公開雲端；其他值 → 企業 GHE（`gh` 要帶 `--hostname <host>`）。
- 有 `number` → 使用者指向單一警示，仍走批次路徑（只是 batch-of-one）。
- URL query（`?q=ecosystem%3Apip+is%3Aopen`）只當 **hint**，不作為硬性過濾。

### 1.3 偵測順序（重要）

Phase 1 必須先比對情況 D（這個帶 `/security/dependabot` 路徑的 URL），**再**比對
情況 C（Jira `/browse/`）與情況 B（CVE/GHSA token）。否則 URL 中的字串可能被誤判
成裸 CVE 編號或一般套件名。

---

## 2. 抓取 alerts — `gh` vs `requests` decision tree

由 helper script 做所有確定性的網路與資料工作：

```bash
python scripts/common/dependabot_fetch.py <host> <owner> <repo> \
    [--state open] [--alert-number N] [--ecosystem pip,npm,go]
```

輸出 JSON 到 stdout，錯誤到 stderr。Exit code：`0` 成功 / `1` 網路或認證失敗 /
`2` 參數錯誤。

### 2.1 認證優先序（與 jira_fetch.py 的 fallback 形狀一致）

1. **優先 `gh api`** —— 重用 GitHub CLI 既有認證，企業 host 走 `gh --hostname <host>`。
   Phase 0.3 preflight 已驗證過 `gh auth status`，所以多半不需額外詢問 token：

   ```bash
   gh api --paginate -H "Accept: application/vnd.github+json" \
     "repos/<owner>/<repo>/dependabot/alerts?state=open"
   # 企業 host 加 --hostname <host>；單一警示打 .../dependabot/alerts/<number>
   ```

2. **fallback：`GITHUB_TOKEN` + `requests`** —— `gh` 不存在時。token 需要
   `security_events` scope（私有 repo 需 `repo`）。GHE base URL 為
   `https://<host>/api/v3`，公開雲端為 `https://api.github.com`，依 `Link` header 翻頁。

### 2.2 權限 / 404 處理

- `403` / scope 不足 → 提示使用者 `gh auth refresh -h <host> -s security_events`
  後重試（對稱於 jira_workflow 的 token 詢問，但這裡多半只要補 gh scope）。
- `404` → repo 不存在、或 Dependabot 未啟用、或帳號無權限。明確告知使用者並停。

---

## 3. 分組與輸出 schema（確定性，在 script 內完成）

分組、版本取最大值都是 **確定性資料工作**，所以放在 script，不丟給 LLM。判斷工作
（嚴重度排序、major-jump 確認、reachability、要不要批成同一個 PR）留在 SKILL.md。

### 3.1 輸出 schema（與 `dependabot_fetch.py` 的 `OUTPUT_SCHEMA` 常數同步）

```jsonc
{
  "source": { "host": "...", "owner": "...", "repo": "...",
              "alerts_url": "https://{host}/{owner}/{repo}/security/dependabot",
              "fetched_at": "ISO-8601 UTC" },
  "alert_count": 12,
  "unsupported_ecosystems": ["rubygems"],
  "groups": [{
    "group_id": "python:requirements.txt",   // f'{language}:{manifest_path}'
    "language": "python",                     // pip→python, npm→javascript, go→go
    "ecosystem": "pip",
    "manifest_path": "requirements.txt",
    "packages": [{
      "name": "requests",
      "target_version": "2.32.0",             // MAX(first_patched) over this pkg's alerts
      "patched_available": true,              // false → 無法自動修，另外列
      "is_major_jump_hint": false,            // 目前固定 false（警示 payload 無安裝版本）；Phase 2 dep_tree 權威
      "max_severity": "high",
      "alerts": [{ "number": 5, "ghsa_id": "GHSA-…", "cve_id": "CVE-2024-…",
                   "severity": "high", "vulnerable_range": "<2.32.0",
                   "first_patched": "2.32.0", "summary": "…", "html_url": "…" }]
    }]
  }]
}
```

### 3.2 分組與收斂規則

- **分組鍵** = `(language, manifest_path)`。monorepo 多個 manifest 會分成多組。
- **一個套件、多筆警示 → 一個 target**：取所有警示中最高的 `first_patched_version`
  （一次 bump 清掉該套件全部 CVE）。
- **沒有 patched version** → `patched_available:false`、`target_version:null`，
  在計畫中獨立列為「無法自動修（上游尚未修復）」。
- **不支援的 ecosystem**（maven / nuget / rubygems / composer / cargo / actions …）
  → 收進 `unsupported_ecosystems`，排除於升級計畫，但在報告中提醒使用者另行處理。

---

## 4. 計畫呈現與核可（LLM，SKILL.md）

1. 對 repo 跑 **一次** Phase 0 環境偵測（批次可能跨多語言；每個 group 已自帶
   `language`，所以每個項目都知道走哪條 track）。
2. 渲染 **批次計畫表**，依語言/manifest 分組：

   ```
   📋 Dependabot 批次升級計畫  (來源: {alerts_url}, {alert_count} 筆 open 警示)

   ── python : uv.lock ──────────────────────────────────────────
   | # | 套件     | 目標版本 | 最高嚴重度 | #CVE | 可自動修 |
   |---|----------|---------|-----------|------|---------|
   | 1 | urllib3  | 2.7.0   | high      | 6    | ✅      |
   | 2 | black    | 26.3.1  | high      | 1    | ✅      |
   | 3 | requests | 2.33.0  | medium    | 1    | ✅      |

   ── javascript : package.json ─────────────────────────────────
   | 4 | axios    | 1.7.9   | critical  | 1    | ✅      |

   （現況版本與是否 major 跳升，於各項 Phase 2 的 dep_tree 確認後補上 —— 警示
    payload 不含已安裝版本，計畫階段不臆測）

   ⚠️ 無法自動修（上游尚未釋出修補版）：
     - <pkg> (GHSA-…, critical)

   ⏭️ 略過（skill 不支援的 ecosystem）：rubygems
   ```

3. **核可關卡**（使用者的核心需求）—— 兩個選擇：

   **(a) 升哪些**（建議：CVE 驅動預設 `all`）

   ```
   要升級哪些項目？(可多選)
     - all              (推薦) 全部命中項目
     - crit+high        只先處理 critical / high
     - 1 3              指定編號
   ```

   **(b) PR 怎麼包**（建議預設 per-package；理由見 §6）

   ```
   要怎麼開 PR？
     - per-package  (推薦) 每個套件各一條 branch + PR；隔離風險、最貼合現有 pipeline
     - per-group    同一 language/manifest 的 patch/minor 批成一個 PR，major 各自獨立
     - combined     全部一個 PR（最簡單，但任一 breaking change 卡全部）
   ```

4. 在 session 保留 `dependabot_context`（類比 `jira_context`）：

   ```python
   dependabot_context = {
     "host": "github.com", "owner": "...", "repo": "...",
     "alerts_url": "https://.../security/dependabot",
     "pr_strategy": "per-package" | "per-group" | "combined",
     "items": [
       { "language": "python", "manifest": "requirements.txt",
         "package": "requests", "target_version": "2.32.0",
         "alerts": [ { "ghsa_id": "...", "cve_id": "...", "html_url": "..." } ],
         "status": "pending" }   # pending|done|skipped|failed|blocked
     ]
   }
   ```

---

## 5. 批次編排迴圈（LLM，SKILL.md）

核可後，這個迴圈逐項驅動既有單套件 pipeline（Phase 2 → 7），全程維護
`dependabot_context.items[]` 的狀態。

### 5.1 建立工作佇列

從核可結果取出選中的項目，**依嚴重度排序**：`critical → high → medium → low`
（同嚴重度按 group 順序）。理由：security 升級先處理高風險；若使用者中途喊停，已完成
的會是最重要的。`patched_available:false` 的項目**不進佇列**（無法自動修），直接列入
§7 報告的「無法自動修」區塊。

### 5.2 逐項執行（核心迴圈）

對佇列第 `i` 項（共 `N` 項）：

1. **宣告進度**：
   `▶ [i/N] 升級 {package} → {target_version}（{manifest}，最高 {severity}，{n} 個 CVE）`
2. **設定 per-item 升級脈絡並交棒 Phase 2**（**跳過 Phase 1**，目標已知）：
   - `package_name = item.package`、`target_version = item.target_version`
   - `language = item.language` → 直接走 Phase 0 已偵測的對應 track（Phase 0 只跑一次）
   - `cve_context = item.alerts[].{cve_id, ghsa_id, html_url}` → 餵給情況 B 的
     reachability（Go: `govulncheck`；Python: `pip-audit`；其餘 grep）與風險分級。
     **不重跑情況 B 的 CVE 查詢**（編號與修補版本已由 Dependabot 提供）。
3. **branch / snapshot 依 `pr_strategy`**（見 §6）。每項在跑 Phase 5 前都先
   `snapshot_env save`（對應語言的 `snapshot_env*.sh`）。
4. **跑 Phase 2 → Phase 6**（依賴分析、breaking change、AST 影響、執行升級、測試）。
5. **結果處置**並更新 `item.status`：
   | 情況 | status | 動作 |
   |------|--------|------|
   | 測試全綠 | `done` | 進 Phase 7（per-package 建 PR；per-group/combined 只 commit），記 `pr_url`/`commit_sha`/`tests` |
   | 測試 3 次迴圈仍失敗，或 breaking change 需人工決策而使用者中止**該項** | `failed` | `snapshot_env restore`，記原因 |
   | 使用者在該項確認點選擇略過 | `skipped` | 記原因 |
   | 前置阻擋（如目標版本不相容當前語言版本、孤兒 transitive 無法處理） | `blocked` | 記原因 |
6. **錯誤隔離（鐵則）**：任一項丟例外或卡住 → 捕捉、標 `failed`、`snapshot_env restore`、
   **繼續下一項**。批次**絕不**因單項失敗而中止。
7. 每項結束印一行小結（`✅ done` / `❌ failed: <reason>` / `⏭️ skipped` / `🚫 blocked`）。

### 5.3 rollback 邊界

- **per-package**：每項自己的 branch；失敗 → restore 該項 snapshot。失敗的 branch
  保留並在報告標記（讓使用者檢視），不要自動刪。
- **per-group / combined**：同一 branch；每項開始前 `snapshot_env save`，失敗 → restore
  到「該項開始前」狀態。先前**已 commit** 的成功項目不受影響（restore 只還原工作目錄到
  最後一個 commit）。

全部跑完 → 進 §7 彙整報告。

---

## 6. PR 打包策略

| 策略 | branch / PR | 優點 | 缺點 |
|------|-------------|------|------|
| **per-package**（預設推薦） | 每套件各一條 branch（`fix/dependabot-{pkg}-{ver}`）+ 各一 PR | 隔離 breakage；對現有 Phase 5.1/7.3「一條 branch + 一個 PR」零改動 | PR 數量多 |
| per-group | 每 `(language, manifest)` 一條 branch + 一 PR；major 跳升各自獨立 | PR 數量少、安全 patch 批次處理 | 同組一個套件壞了卡整組 |
| combined | 全部一條 branch + 一個 PR | 合併最簡單 | 任一 breaking change 卡全部 |

控制流（branch 名只用 `[A-Za-z0-9._-]`，沿用 Phase 5.1 規範）：

**per-package**（預設）—— 每項獨立：
```
for item in queue:
    git checkout master          # 一律從 master 切，不疊在前一項上（見 memory）
    git checkout -b fix/dependabot-{pkg}-{target_version}    # 有 CVE 時可用 fix/CVE-…-{pkg}
    Phase 5 → 6 → 7（建 PR）
```

**per-group** —— 每組一條 branch、組內逐項 commit、最後一個 PR：
```
for group in groups:
    git checkout master
    git checkout -b fix/dependabot-{language}-{manifest_slug}
    for item in group:
        snapshot_env save
        Phase 2  # 此時 dep_tree 才會權威判定是否 major 跳升
        if 是 major 跳升:        # 侵入性高（改 import path），不混進批次 PR
            該項改走 per-package（自己的 branch + PR），跳過、不 commit 進本組 branch
            continue
        Phase 3 → 6; git commit（一套件一 commit）
    開一個 PR（body 列出本組實際 commit 的套件）
```
> major 跳升只有在該項 Phase 2 的 `dep_tree`（JS `is_major_jump` / Go
> `is_major_version_jump`）才權威確定 —— 計畫階段的 `is_major_jump_hint` 固定 false，
> 不能拿來預先分流。

**combined** —— 全部一條 branch、逐項 commit、一個 PR：
```
git checkout master
git checkout -b fix/dependabot-{YYYY-MM-DD}
for item in queue:
    snapshot_env save; Phase 5 → 6; git commit
開一個 PR（body 列出所有套件）
```

`manifest_slug` = manifest path 去掉斜線與點（`requirements.txt` → `requirements-txt`）。
commit / PR 命名與 trailer 沿用 Phase 7.2 / 7.3；trailer 見 §7。

---

## 7. 彙整報告與 write-back

迴圈跑完後，用**自然語言**寫一份批次摘要給使用者（不要模板填空）。它**疊加在**每個
PR 既有的 Phase 7.1 遷移報告之上 —— per-package 時每個 PR 本來就各帶完整報告，這份
摘要是把所有結果聚合成一眼可讀的總覽。

### 7.1 批次摘要結構

```markdown
## 🤖 Dependabot 批次升級摘要

來源: {alerts_url}  ·  抓取於 {fetched_at}
結果: {done} 成功 / {failed} 失敗 / {skipped} 略過 / {blocked} 阻擋（共 {N} 選中）

| # | 套件 | manifest | 版本 | 最高嚴重度 | #CVE | 結果 | PR |
|---|------|----------|------|-----------|------|------|----|
| 1 | urllib3 | uv.lock | →2.7.0 | high | 6 | ✅ done | #123 |
| 2 | black | uv.lock | →26.3.1 | high | 1 | ❌ failed: 測試 3 次未過 | — |
| 3 | requests | uv.lock | →2.33.0 | medium | 1 | ⏭️ skipped: 使用者選擇 | — |

### ⚠️ 無法自動修（上游尚未釋出修補版）
- {pkg} (GHSA-…, {severity}) — 建議追蹤上游

### ⏭️ 略過（skill 不支援的 ecosystem）
- rubygems: {pkg}（請另行處理）

### 🔔 合併後會自動關閉的警示
- {alert.html_url} (GHSA-…)   ← 僅列 status==done 的項目對應警示
```

- per-group / combined：PR 欄填同一個 PR 編號（多列指向同一 PR），並在 PR body
  列出該 PR 涵蓋的所有套件。
- 失敗 / 阻擋項目務必寫**具體原因**（測試輸出摘要、卡住的 breaking change、版本不相容），
  方便使用者接手。

### 7.2 PR trailer（每個 PR 都加）

沿用既有 trailer 慣例引用來源（對稱於 Phase 7.2 的 `Jira:` / `Diff:`）：

```
Dependabot: https://github.com/<owner>/<repo>/security/dependabot
GHSA: GHSA-xxxx-xxxx-xxxx
CVE: CVE-2024-xxxxx
```

多個 CVE/GHSA（同套件多警示）一行一條全列出。

### 7.3 write-back

**不需要 API write-back**（不像 Jira 要轉狀態）：Dependabot 會在修補 PR 合併後
**自動關閉**對應警示。本摘要只在對話中呈現給使用者，§7.1 的「合併後會自動關閉」清單
是 informational，不對 GitHub 寫入任何東西。

---

## 8. 跨平台注意事項（linux / mac / cygwin64 / windows）

- `dependabot_fetch.py` 刻意用 **純 Python 3.8 + `subprocess`**（不是 `*.sh` variant），
  在四種環境行為一致，且不替這個核心新功能引入 Windows 端對 bash 的依賴。
- `gh` / `git` 等指令本身跨平台；企業 host 走 `gh --hostname`。
- 既有 `*.sh` helper 在 Windows 仍走 git-bash / cygwin（維持現狀）。
- 未來補 `verify_installation.{sh,bat}` 與 cygwin64 verifier 時，需各加一行檢查
  `dependabot_fetch.py` 是否存在（目前尚未串接）。

---

## 9. 邊界情況

- **0 筆 open 警示** → 告知使用者「沒有需要處理的安全警示」，結束。
- **全部 unsupported ecosystem** → 列出 ecosystem、說明 skill 不支援，結束。
- **單一警示（URL 帶 number）** → batch-of-one，仍走核可關卡（保持一致 UX）。
- **同一套件出現在多個 manifest** → 分屬不同 group，各自獨立升級項目。
- **無 patched version 的警示** → 永遠列在「無法自動修」，不要硬升到不存在的版本。
