# Package Upgrade / CVE Fix Agent — 架構設計 v3

## Claude Code Skill Edition

> **核心轉變**: 從「獨立 Python 應用 + 呼叫 Claude API」
> 轉為「Claude Code 原生 Skill — Claude 自己就是 Orchestrator + LLM」。
>
> Claude Code 本身就是 Claude 4.6，不需要額外的 API 呼叫。
> 所有推理、分析、程式碼生成都由 Claude Code 的原生能力完成。
> 確定性任務交給 helper scripts 透過 bash 執行。

---

## 0. 發布前檢查清單

在將此 Skill 公開發布或分享給他人使用前，請確保以下檔案都已完備:

### 必要檔案 (Must Have)

- [ ] **README.md** — 完整的安裝與使用指南 (見 § 6)
  - 前置需求清楚列出
  - 安裝步驟詳細說明 (全域 vs 專案級)
  - 快速開始範例
  - 故障排除指南
  
- [ ] **SKILL.md** — 主技能文件 (見 § 3)
  - frontmatter 正確設定 (name, description)
  - 所有 Phase 流程完整
  - 使用者確認點清楚標記
  
- [ ] **LICENSE** — 授權條款 (建議 MIT)

- [ ] **scripts/*.sh** — 所有 bash scripts (含三軌的 `*_js.sh` / `*_go.sh`)
  - 已賦予執行權限 (`chmod +x`)
  - 有錯誤處理 (`set -euo pipefail`)
  - 有使用說明註解
  
- [ ] **scripts/*.py** — Python scripts (含 jira_*.py、save_token、parse_pm_errors)
  - 已賦予執行權限 (`chmod +x`)
  - shebang 正確: `#!/usr/bin/env python3`
  - 有 docstring 和使用範例

- [ ] **scripts/*.js / package.json** — JS helper scripts
  - shebang 正確: `#!/usr/bin/env node`
  - JS 依賴宣告在 `scripts/package.json`
  - 安裝時跑 `npm install` (install.sh 已處理)

- [ ] **scripts/*.go** — Go helper scripts (透過 `go run` 執行，免 build)

### 重要檔案 (Should Have)

- [ ] **references/*.md** — 參考文件 (三軌 references)
  - Python: pip_workflow / poetry_workflow / uv_workflow / PIP_LOCK_PATTERNS /
    IMPORTANT_DEPENDENCY_UPDATE / breaking_change_patterns
  - JS / TS: js_workflow / npm_workflow / yarn_workflow / js_ast_strategy /
    breaking_change_patterns_js
  - Go: go_workflow / go_major_version_paths / go_replace_semantics /
    govulncheck / breaking_change_patterns_go
  - 跨語言: jira_workflow / bdsa_mapping / auth_tokens
  
- [ ] **templates/report_structure.md** — 報告結構指南

- [ ] **.gitignore** — 排除不必要的檔案
  ```
  __pycache__/
  *.pyc
  .DS_Store
  .upgrade_snapshot/
  ```

### 可選檔案 (Nice to Have)

- [x] **CHANGELOG.md** — 版本更新紀錄 (已具備)
- [x] **CONTRIBUTING.md** — 貢獻指南 (已具備)
- [x] **tests/** — Skill 本身的測試 (pytest UT + GitHub Actions CI 已具備)
- [ ] **examples/** — 使用範例專案

### 測試驗證

- [ ] 在乾淨環境中測試全域安裝流程
- [ ] 在乾淨環境中測試專案級安裝流程
- [ ] 驗證所有 helper scripts 可執行
- [ ] 驗證 Skill 在 Claude Code 中可被識別
- [ ] 用真實專案測試完整工作流
- [ ] 檢查 README 中的所有範例都可執行

### 文件品質

- [ ] README.md 中所有連結都有效
- [ ] 範例程式碼可以直接複製執行
- [ ] 故障排除指南涵蓋常見問題
- [ ] 版本號一致 (README / SKILL.md / CHANGELOG)

---

## 1. 架構對比: v2 vs v3

```
v2: 獨立 Python 應用                    v3: Claude Code Skill
─────────────────────                   ────────────────────
┌─────────────┐                        ┌──────────────────────┐
│ Python App  │                        │   Claude Code CLI    │
│  LangGraph  │                        │   (Claude 4.6 本體)   │
│  ┌────────┐ │                        │                      │
│  │ Node 1 │─┼─► Claude API ──►回來   │  讀取 SKILL.md       │
│  │ Node 2 │─┼─► Claude API ──►回來   │  → 自己就是 LLM      │
│  │ Node 3 │─┼─► Claude API ──►回來   │  → bash 跑 helper    │
│  └────────┘ │                        │  → 自己分析結果       │
│  N 次 API    │                        │  → 自己生成 patch    │
│  來回呼叫    │                        │  0 次額外 API 呼叫    │
└─────────────┘                        └──────────────────────┘

開發成本: 高 (完整 Python 專案)          開發成本: 低 (SKILL.md + scripts)
執行成本: 高 (每節點 1 次 API call)      執行成本: 低 (Claude Code 自身算力)
部署方式: pip install / docker          部署方式: 放入 .claude/skills/
```

---

## 2. Skill 檔案結構

```
package-upgrade/
├── README.md                         # 📘 安裝與使用指南 (重要!)
├── SKILL.md                          # 主技能文件 — Claude Code 讀這個
├── QUICK_REFERENCE.md                # Python / JS / Go 對照卡
├── LICENSE                           # 授權條款
│
├── scripts/                          # 三軌 helper：Python / JS / Go
│   # ── 環境偵測 ────────────────────────────────
│   ├── detect_env.sh                 # Python: pkg manager / lock 模式 / Python 版本
│   ├── detect_env_js.sh              # JS / TS: npm / yarn 3 + pkg_manager_bin
│   ├── detect_env_go.sh              # Go: go modules / vendor / go.work / replace
│   # ── Pre-flight ─────────────────────────────
│   ├── preflight.sh                  # Python / JS pre-flight 檢查
│   ├── preflight_go.sh               # Go pre-flight
│   # ── 依賴樹 ─────────────────────────────────
│   ├── dep_tree.py                   # Python
│   ├── dep_tree_js.js                # JS / TS
│   ├── dep_tree_go.{sh,py}           # Go
│   # ── AST 掃描 ───────────────────────────────
│   ├── ast_scanner.py                # Python
│   ├── ast_scanner_js.js             # JS / TS
│   ├── ast_scanner_go.go             # Go (透過 go run 執行)
│   # ── API surface diff ──────────────────────
│   ├── api_surface_diff_js.js        # TypeScript .d.ts surface diff
│   ├── api_surface_diff_go.sh        # Go apidiff
│   # ── Vulnerability reachability ─────────────
│   ├── govulncheck_go.sh             # Go govulncheck
│   # ── Changelog / Git diff ──────────────────
│   ├── fetch_changelog.py            # 通用 changelog 抓取
│   ├── git_diff.sh                   # Python
│   ├── git_diff_js.sh                # JS / TS
│   ├── git_diff_go.sh                # Go
│   # ── 測試 ───────────────────────────────────
│   ├── run_tests.sh                  # Python (pytest / unittest)
│   ├── run_tests_js.sh               # JS / TS (jest / vitest)
│   ├── run_tests_go.sh               # Go (go test)
│   # ── Snapshot / 回退 ────────────────────────
│   ├── snapshot_env.sh               # Python
│   ├── snapshot_env_js.sh            # JS / TS
│   ├── snapshot_env_go.sh            # Go
│   # ── Lock / mod 驗證 ───────────────────────
│   ├── validate_lockfile.sh          # Python / JS lock 驗證
│   ├── validate_modfile_go.sh        # Go go.mod / go.sum 驗證
│   # ── Auth / Jira ──────────────────────────
│   ├── save_token.sh                 # 寫入 auth token (chmod 600 + .gitignore)
│   ├── jira_fetch.py                 # Jira REST fallback: 抓 ticket
│   ├── jira_comment.py               # Jira REST fallback: post comment
│   ├── jira_transition.py            # Jira REST fallback: list/apply transitions
│   # ── 其他 ────────────────────────────────
│   ├── parse_pm_errors.py            # 解析 pip/poetry/uv/npm/go 錯誤輸出
│   └── package.json                  # JS helpers 自己的依賴宣告
│
├── references/
│   # Python
│   ├── pip_workflow.md
│   ├── poetry_workflow.md
│   ├── uv_workflow.md
│   ├── PIP_LOCK_PATTERNS.md
│   ├── IMPORTANT_DEPENDENCY_UPDATE.md
│   ├── breaking_change_patterns.md
│   # JS / TS
│   ├── js_workflow.md
│   ├── npm_workflow.md
│   ├── yarn_workflow.md
│   ├── js_ast_strategy.md
│   ├── breaking_change_patterns_js.md
│   # Go
│   ├── go_workflow.md
│   ├── go_major_version_paths.md
│   ├── go_replace_semantics.md
│   ├── govulncheck.md
│   ├── breaking_change_patterns_go.md
│   # 跨語言
│   ├── jira_workflow.md
│   ├── bdsa_mapping.md
│   └── auth_tokens.md
│
└── templates/
    └── report_structure.md           # 報告結構範本 (非填空模板)
```

---

## 3. SKILL.md 完整設計

```markdown
---
name: package-upgrade
description: >
  升級 Python / JavaScript / TypeScript / Go 套件或修復 CVE 漏洞的完整工作流。
  當使用者提到「升級 package」、「更新套件」、「fix CVE」、「修復漏洞」、
  「package migration」、「dependency update」、「bump version」、
  「升級 npm package」、「update axios / react / lodash」、「bump <pkg>」、
  「升級 go module」、「update go.mod」、「go get upgrade」、
  「govulncheck」、「v1 升 v2」、「major version upgrade」
  時觸發此 skill。也適用於使用者提供 CVE 編號 (如 CVE-2024-xxxxx)
  並希望修復的場景，以及提供 Atlassian Jira ticket URL
  (如 https://trendmicro.atlassian.net/browse/V1E-148968) 或
  Jira issue key (如 V1E-148968) — 此時會自動讀取 ticket 內容、
  分析應升級的套件、完成後將報告 comment 回 ticket，並依目前 ticket
  狀態提議推進 (To Do → Ready for Work → Development → Done)。
  Python: 支援 pip、poetry、uv 三種套件管理工具。
  JavaScript/TypeScript: 支援 npm + yarn 3 + TypeScript .d.ts API surface diff
  (pnpm / bun 後續 stage)。
  Go: 支援 go modules、major version path rewrite (v1→v2+)、apidiff API surface
  diff、govulncheck reachability 分析、vendor mode、go.work workspace、
  replace directives。
  自動偵測專案使用的語言與工具。即使使用者只是隨口問「這個套件能不能升級」，
  也應觸發此 skill 來做完整分析。
---

# Package Upgrade / CVE Fix Skill

## 概觀

你是一位資深的套件遷移專家，同時熟悉 Python、JavaScript / TypeScript 與 Go 生態。
當使用者要求升級套件或修復 CVE 時，按照以下工作流程逐步執行。你自己就是分析引擎
— 不需要呼叫外部 LLM API。

關鍵原則:
- **在修改任何專案內容之前，必須先建立新的 Git 分支** (Phase 5.1)
- 每個步驟先用 helper script 取得結構化數據，再用你的推理能力分析
- 在修改任何檔案之前，先備份環境
- 測試程式的修改必須經過使用者確認
- 完成後建立 Pull Request 供 review
- 全程保持可回退

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
- `dependency_files`: 依賴宣告檔清單

根據偵測到的 pkg_manager，讀取對應的 references 文件:
- pip → 讀 `references/pip_workflow.md`
- poetry → 讀 `references/poetry_workflow.md`
- uv → 讀 `references/uv_workflow.md`

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

1. 找到所有直接引用此 pkg 的 parent packages
2. 檢查 parent 的版本約束是否允許目標版本
3. 若 parent 本身是直接引用 → 走 Type A 流程升級 parent
4. 若無法透過升級 parent 解決 → 走衝突解決流程

#### Type C — 直接 + 間接引用

最複雜的情況。你需要:
1. 先做 Type A 的 python 相容性檢查
2. 再檢查所有 parent 的版本約束
3. 如果有衝突 → 走衝突解決流程

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

輸出: 兩個版本 tag 之間的 `*.py` diff

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

分支命名規則:
```bash
git checkout -b feature/Update-{PackageName}-to-{TargetVersion}
```

範例:
```bash
git checkout -b feature/Update-requests-to-2.32.0
git checkout -b feature/Update-django-to-5.1
```

如果是修復 CVE:
```bash
git checkout -b fix/CVE-{CVE-ID}-{PackageName}
# 範例: git checkout -b fix/CVE-2024-35195-cryptography
```

### Step 5.2: 環境備份

```bash
bash scripts/snapshot_env.sh <project_path> save
```

### Step 5.3: 更新依賴宣告檔

根據 pkg_manager 執行對應的更新命令
(參照先前讀取的 references/{pkg_manager}_workflow.md)。

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

2. **依賴分析** — 引用類型、衝突處理

3. **Breaking Changes 詳情** — 每個變更的影響和解決方式

4. **程式碼修改清單** — 每個檔案改了什麼、為什麼

5. **測試結果** — 通過/失敗、是否修改了測試程式

6. **後續建議** — 還有哪些相關套件可能需要更新

7. **回退指南** — 如果需要回退，怎麼做

### Step 7.2: Git Commit Message

寫一個符合 Conventional Commits 規範的 commit message (英文):

- 第一行: `type(scope): description` (≤72 字元)
- Body: 解釋「為什麼」(不只是「做了什麼」)
- 如果是 CVE: 包含 CVE 編號和嚴重性
- 如果有 BREAKING CHANGE: 使用 footer

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

PR 內容應包含:
- Phase 7.1 產生的完整遷移報告作為 PR description
- 標記為 `dependencies` / `security` label (如果是 CVE 修復)
- 指定 reviewers (如有需要)

### Step 7.4: 完成

將報告輸出給使用者，並提供:
1. 報告全文
2. 已建立的 commit 和 branch 資訊
3. Pull Request URL (如已建立)
4. 回退命令 (以防需要)

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
| Phase 2.3: 衝突解決方案 | 多種方案 + 風險評估 + 推薦 |
| Phase 4.4: 程式碼修改預覽 | 完整 diff + 每處修改的理由 |
| Phase 5.1: 建立 Git 分支 | 分支名稱、即將開始修改 |
| Phase 6.4: 測試程式修改 | 為什麼要改 + 改後仍驗證什麼 |
| Phase 7.3: 建立 Pull Request | PR 資訊、是否建立 PR |
```

---

## 4. Helper Scripts 詳細設計

每個 script 負責「確定性的數據收集」，把非結構化的工具輸出轉為 JSON，
供 Claude Code (你自己) 讀取並用 LLM 推理能力分析。

### 4.1 detect_env.sh

```bash
#!/usr/bin/env bash
# 偵測專案的套件管理工具和 Python 版本
# 用法: bash detect_env.sh <project_path>
# 輸出: JSON

PROJECT_PATH="${1:-.}"
cd "$PROJECT_PATH" || exit 1

PYTHON_VERSION=$(python3 --version 2>/dev/null | grep -oP '\d+\.\d+\.\d+')
PKG_MANAGER="unknown"
LOCKFILE=""
DEP_FILES="[]"

# 偵測順序: uv > poetry > pip
if [ -f "uv.lock" ] || grep -q '\[tool\.uv\]' pyproject.toml 2>/dev/null; then
    PKG_MANAGER="uv"
    LOCKFILE="uv.lock"
elif [ -f "poetry.lock" ] || grep -q '\[tool\.poetry\]' pyproject.toml 2>/dev/null; then
    PKG_MANAGER="poetry"
    LOCKFILE="poetry.lock"
elif [ -f "requirements.txt" ] || [ -f "setup.py" ] || [ -f "setup.cfg" ]; then
    PKG_MANAGER="pip"
    [ -f "requirements.txt" ] && LOCKFILE="requirements.txt"
fi

# 收集依賴宣告檔
DEP_FILES=$(find . -maxdepth 2 \( \
    -name "requirements*.txt" -o \
    -name "pyproject.toml" -o \
    -name "setup.py" -o \
    -name "setup.cfg" \
\) -not -path "./.venv/*" | jq -R -s 'split("\n") | map(select(. != ""))')

cat <<EOF
{
  "pkg_manager": "$PKG_MANAGER",
  "python_version": "$PYTHON_VERSION",
  "lockfile_path": "$LOCKFILE",
  "dependency_files": $DEP_FILES
}
EOF
```

### 4.2 dep_tree.py

```python
#!/usr/bin/env python3
"""解析依賴樹，判斷 package 的引用類型。

用法: python dep_tree.py <project_path> <package_name> [--pkg-manager pip|poetry|uv]
輸出: JSON
"""
import subprocess, json, sys, re
from pathlib import Path

def get_dep_tree_pip(project_path: str) -> dict:
    """用 pipdeptree 取得依賴樹"""
    result = subprocess.run(
        ["pipdeptree", "--json-tree"],
        capture_output=True, text=True, cwd=project_path
    )
    return json.loads(result.stdout)

def get_dep_tree_poetry(project_path: str) -> dict:
    """用 poetry show 取得依賴樹"""
    result = subprocess.run(
        ["poetry", "show", "--tree", "--no-ansi"],
        capture_output=True, text=True, cwd=project_path
    )
    return {"raw": result.stdout}

def get_dep_tree_uv(project_path: str) -> dict:
    """用 uv pip tree 取得依賴樹"""
    result = subprocess.run(
        ["uv", "pip", "tree"],
        capture_output=True, text=True, cwd=project_path
    )
    return {"raw": result.stdout}

def get_installed_version(package_name: str, pkg_manager: str, project_path: str) -> str:
    """取得已安裝的版本"""
    cmds = {
        "pip": ["pip", "show", package_name],
        "poetry": ["poetry", "show", package_name],
        "uv": ["uv", "pip", "show", package_name],
    }
    result = subprocess.run(cmds[pkg_manager], capture_output=True, text=True, cwd=project_path)
    for line in result.stdout.splitlines():
        if line.lower().startswith("version:"):
            return line.split(":", 1)[1].strip()
    return "unknown"

def classify_dependency(package_name: str, dep_tree: dict, dep_files: list[str]) -> dict:
    """
    判斷 package 的引用類型:
    - direct: 在 requirements.txt / pyproject.toml 中直接宣告
    - transitive: 僅作為其他 package 的依賴被安裝
    - both: 既是直接宣告也是其他 package 的依賴
    """
    is_direct = False
    parent_packages = []
    version_constraints = {}

    # 檢查是否在依賴宣告檔中直接列出
    for dep_file in dep_files:
        content = Path(dep_file).read_text()
        pattern = rf'^{re.escape(package_name)}\b'
        if re.search(pattern, content, re.MULTILINE | re.IGNORECASE):
            is_direct = True

    # 從依賴樹中找 parent packages
    # (簡化版 — 實際實作需要遞迴搜尋 JSON 樹)
    parent_packages, version_constraints = find_parents_in_tree(package_name, dep_tree)

    is_transitive = len(parent_packages) > 0

    if is_direct and is_transitive:
        dep_type = "both"
    elif is_direct:
        dep_type = "direct"
    elif is_transitive:
        dep_type = "transitive"
    else:
        dep_type = "unknown"

    return {
        "dependency_type": dep_type,
        "is_direct": is_direct,
        "is_transitive": is_transitive,
        "parent_packages": parent_packages,
        "version_constraints": version_constraints,
    }

def find_parents_in_tree(package_name: str, tree: dict) -> tuple[list, dict]:
    """遞迴搜尋依賴樹找出 parent packages"""
    parents = []
    constraints = {}
    # 實作略 — 遞迴走訪 JSON 樹
    return parents, constraints

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("project_path")
    parser.add_argument("package_name")
    parser.add_argument("--pkg-manager", default="pip")
    args = parser.parse_args()

    tree_funcs = {"pip": get_dep_tree_pip, "poetry": get_dep_tree_poetry, "uv": get_dep_tree_uv}
    dep_tree = tree_funcs[args.pkg_manager](args.project_path)
    version = get_installed_version(args.package_name, args.pkg_manager, args.project_path)

    dep_files_raw = subprocess.run(
        ["find", args.project_path, "-maxdepth", "2",
         "(", "-name", "requirements*.txt", "-o", "-name", "pyproject.toml", ")"],
        capture_output=True, text=True
    ).stdout.strip().splitlines()

    classification = classify_dependency(args.package_name, dep_tree, dep_files_raw)

    result = {
        "package_name": args.package_name,
        "current_version": version,
        **classification,
        "full_tree": dep_tree,
    }
    print(json.dumps(result, indent=2))
```

### 4.3 ast_scanner.py

```python
#!/usr/bin/env python3
"""AST 掃描專案中對指定 package 的所有引用。

用法: python ast_scanner.py <project_path> <package_name>
輸出: JSON — 每個檔案中的 import 和 symbol 使用
"""
import ast, json, sys
from pathlib import Path

class PackageUsageVisitor(ast.NodeVisitor):
    """掃描 AST 找出對目標 package 的所有引用"""

    def __init__(self, package_name: str, source_lines: list[str]):
        self.package_name = package_name
        self.source_lines = source_lines
        self.imports = []       # import 語句
        self.usages = []        # symbol 使用位置
        self.imported_names = {} # alias → 原始名稱 的映射

    def visit_Import(self, node):
        for alias in node.names:
            if alias.name == self.package_name or alias.name.startswith(f"{self.package_name}."):
                local_name = alias.asname or alias.name
                self.imported_names[local_name] = alias.name
                self.imports.append({
                    "type": "import",
                    "module": alias.name,
                    "alias": alias.asname,
                    "line": node.lineno,
                    "context": self._get_context(node.lineno),
                })
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module and (node.module == self.package_name or
                           node.module.startswith(f"{self.package_name}.")):
            for alias in node.names:
                local_name = alias.asname or alias.name
                full_name = f"{node.module}.{alias.name}"
                self.imported_names[local_name] = full_name
                self.imports.append({
                    "type": "from_import",
                    "module": node.module,
                    "name": alias.name,
                    "alias": alias.asname,
                    "line": node.lineno,
                    "context": self._get_context(node.lineno),
                })
        self.generic_visit(node)

    def visit_Attribute(self, node):
        # 追蹤 obj.method() 等屬性存取
        chain = self._resolve_attr_chain(node)
        if chain:
            root = chain.split(".")[0]
            if root in self.imported_names:
                full_name = self.imported_names[root] + chain[len(root):]
                self.usages.append({
                    "symbol": full_name,
                    "line": node.lineno,
                    "context": self._get_context(node.lineno),
                })
        self.generic_visit(node)

    def visit_Name(self, node):
        if node.id in self.imported_names:
            self.usages.append({
                "symbol": self.imported_names[node.id],
                "line": node.lineno,
                "context": self._get_context(node.lineno),
            })
        self.generic_visit(node)

    def _resolve_attr_chain(self, node) -> str | None:
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
            return ".".join(reversed(parts))
        return None

    def _get_context(self, lineno: int, radius: int = 5) -> str:
        start = max(0, lineno - radius - 1)
        end = min(len(self.source_lines), lineno + radius)
        lines = self.source_lines[start:end]
        return "\n".join(f"{start + i + 1:4d} | {line}" for i, line in enumerate(lines))

def scan_file(filepath: Path, package_name: str) -> dict | None:
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError):
        return None

    visitor = PackageUsageVisitor(package_name, source.splitlines())
    visitor.visit(tree)

    if not visitor.imports and not visitor.usages:
        return None

    return {
        "file": str(filepath),
        "imports": visitor.imports,
        "usages": visitor.usages,
    }

def scan_project(project_path: str, package_name: str) -> list[dict]:
    results = []
    for py_file in Path(project_path).rglob("*.py"):
        # 跳過 venv、__pycache__、.git
        if any(part.startswith(('.', '__pycache__', 'venv', '.venv', 'node_modules'))
               for part in py_file.parts):
            continue
        result = scan_file(py_file, package_name)
        if result:
            results.append(result)
    return results

if __name__ == "__main__":
    project_path = sys.argv[1]
    package_name = sys.argv[2]
    results = scan_project(project_path, package_name)
    print(json.dumps({"scan_results": results, "total_files": len(results)}, indent=2))
```

### 4.4 git_diff.sh

```bash
#!/usr/bin/env bash
# Clone repo (shallow) 並 diff 兩個版本 tag
# 用法: bash git_diff.sh <repo_url> <old_version> <new_version>
# 輸出: diff 內容到 stdout

REPO_URL="$1"
OLD_VER="$2"
NEW_VER="$3"
WORK_DIR=$(mktemp -d)

cd "$WORK_DIR" || exit 1

# Shallow clone (只拿 tags)
git clone --bare --filter=tree:0 "$REPO_URL" repo.git 2>/dev/null
cd repo.git || exit 1

# 嘗試多種 tag 格式
find_tag() {
    local ver="$1"
    for pattern in "v$ver" "$ver" "release-$ver" "release/$ver"; do
        if git rev-parse "$pattern" >/dev/null 2>&1; then
            echo "$pattern"
            return 0
        fi
    done
    return 1
}

OLD_TAG=$(find_tag "$OLD_VER")
NEW_TAG=$(find_tag "$NEW_VER")

if [ -z "$OLD_TAG" ]; then
    echo "ERROR: Cannot find tag for version $OLD_VER" >&2
    echo "Available tags:" >&2
    git tag --list | head -20 >&2
    exit 1
fi

if [ -z "$NEW_TAG" ]; then
    echo "ERROR: Cannot find tag for version $NEW_VER" >&2
    echo "Available tags:" >&2
    git tag --list | head -20 >&2
    exit 1
fi

# 輸出 diff (只看 .py 檔案)
git diff "$OLD_TAG".."$NEW_TAG" -- "*.py"

# 清理
rm -rf "$WORK_DIR"
```

### 4.5 snapshot_env.sh

```bash
#!/usr/bin/env bash
# 環境備份與回退
# 用法: bash snapshot_env.sh <project_path> save|restore

PROJECT_PATH="${1:-.}"
ACTION="${2:-save}"
SNAPSHOT_DIR="$PROJECT_PATH/.upgrade_snapshot"

cd "$PROJECT_PATH" || exit 1

case "$ACTION" in
    save)
        mkdir -p "$SNAPSHOT_DIR"
        # 備份依賴檔案
        for f in requirements*.txt pyproject.toml poetry.lock uv.lock setup.py setup.cfg; do
            [ -f "$f" ] && cp "$f" "$SNAPSHOT_DIR/"
        done
        # 備份已安裝套件清單
        pip freeze > "$SNAPSHOT_DIR/pip_freeze.txt" 2>/dev/null
        echo "Snapshot saved to $SNAPSHOT_DIR"
        ;;
    restore)
        if [ ! -d "$SNAPSHOT_DIR" ]; then
            echo "ERROR: No snapshot found at $SNAPSHOT_DIR" >&2
            exit 1
        fi
        # 還原依賴檔案
        for f in "$SNAPSHOT_DIR"/*; do
            fname=$(basename "$f")
            [ "$fname" = "pip_freeze.txt" ] && continue
            cp "$f" "$PROJECT_PATH/"
        done
        # 還原套件
        pip install -r "$SNAPSHOT_DIR/pip_freeze.txt" 2>/dev/null
        echo "Environment restored from $SNAPSHOT_DIR"
        ;;
esac
```

---

## 5. Reference Documents

### 5.1 breaking_change_patterns.md

```markdown
# Breaking Change 識別模式速查

## Changelog 措辭 → 實際影響

| Changelog 措辭 | 實際影響 | 嚴重性 |
|---------------|---------|-------|
| "removed X" / "X has been removed" | API 刪除 | 🔴 |
| "renamed X to Y" | API 更名 | 🔴 |
| "X is now required" | 必要參數增加 | 🔴 |
| "X now returns Y" / "return type changed" | 回傳型別變更 | 🔴 |
| "moved X from A to B" | 模組路徑變更 | 🔴 |
| "default value of X changed" | 預設值變更 | 🔴 |
| "improved default behavior" | 行為變更 (隱含) | 🔴 |
| "X is deprecated" / "use Y instead" | 棄用 (仍可用) | 🟡 |
| "added DeprecationWarning" | 棄用警告 | 🟡 |
| "minimum Python version is now X" | Python 版本要求 | 🔴 |

## Git Diff 模式 → 實際影響

| Diff 模式 | 影響 | 範例 |
|-----------|------|------|
| 函式定義整行被刪 | API 被移除 | `-def old_func(...)` |
| 參數列表改變 | 簽名不相容 | `-def f(a, b):` / `+def f(a, b, c):` (無預設值) |
| return type hint 改變 | 回傳型別變更 | `-> list` → `-> Generator` |
| `__all__` 清單項目被移除 | 公開 API 縮減 | |
| `warnings.warn` 被加入 | 棄用預警 | `+warnings.warn("deprecated", DeprecationWarning)` |
| default 參數值改變 | 行為變更 | `timeout=None` → `timeout=30` |
| Exception 類型改變 | 錯誤處理受影響 | `raise ValueError` → `raise TypeError` |

## 容易遺漏的隱含 Breaking Change

1. **list → generator**: 影響 `len()`, `[index]`, 多次迭代
2. **dict → NamedTuple/dataclass**: 影響 `["key"]` 存取方式
3. **sync → async**: 需要 `await`
4. **encoding 預設值改變**: 影響非 ASCII 資料處理
5. **錯誤從 silently ignore → raise**: 影響錯誤恢復邏輯
6. **ordering 保證改變**: dict/set 迭代順序
```

### 5.2 report_structure.md

```markdown
# 遷移報告結構指南

## 寫作原則
- 用你自己的語言，不要模板填空
- 先結論，後細節
- 每個 section 開頭一句話總結
- 技術細節用程式碼區塊呈現

## 結構

### 1. Executive Summary (必要)
用 3-5 句話回答:
- 升了什麼？為什麼？
- 影響範圍多大？
- 結果如何？

### 2. 依賴分析 (如有衝突才需要詳述)
- 引用類型
- 衝突處理過程
- 最終方案

### 3. Breaking Changes (核心章節)
按影響程度排列，每個包含:
- 什麼變了
- 影響了專案中的哪些檔案
- 怎麼修的

### 4. 程式碼修改 (核心章節)
按檔案分組，每個檔案:
- 改了幾處
- 每處改了什麼、為什麼

### 5. 測試結果
- 通過率
- 是否修改了測試 (如有，說明理由)

### 6. 後續建議 (加分項)
- 相關套件是否也該更新
- 被棄用但這次沒改的 API (可以列為 tech debt)

### 7. 回退指南 (必要)
- 回退命令
- 注意事項
```

---

## 6. README.md 設計

> **這是讓其他人能夠順利安裝和使用此 Skill 的關鍵文件。**

> ⚠️ **本節 (含下方所有 README 範例) 為 v1 (Python-only) 時期的設計快照。**
> 真正出貨的 README 已擴充覆蓋 Python / JavaScript / TypeScript / Go 三軌
> 與 Jira 觸發、Windows / Cygwin 安裝等，請以 repo 根目錄的 `README.md` /
> `README.zh-TW.md` 與 `package-upgrade/README.md` 為準。
> 以下範例僅保留作為「README 應包含哪些區塊」的結構參考。

```markdown
# Package Upgrade / CVE Fix Skill for Claude Code

> 自動化 Python 套件升級與 CVE 漏洞修復的 Claude Code Skill

一個基於 Claude Code 的智能套件升級助手，能夠:
- 🔍 自動分析 breaking changes (從 changelog + git diff)
- 🛠️ 自動修改受影響的程式碼
- ✅ 自動執行測試並診斷失敗原因
- 📝 產出完整的遷移報告和 PR
- 🔒 支援 CVE 漏洞修復與風險評估

支援 `pip`、`poetry`、`uv` 三種套件管理工具。

---

## 安裝

### 前置需求

1. **Claude Code CLI** (版本 ≥ 1.0)
   ```bash
   # 安裝 Claude Code CLI
   # 參考: https://docs.anthropic.com/claude/docs/claude-code
   ```

2. **Python 環境**
   - Python 3.8+
   - 以下 Python 套件 (用於 helper scripts):
     ```bash
     pip install pipdeptree requests
     ```

3. **Git**
   - git CLI (用於建立分支和 PR)
   - `gh` CLI (可選，用於自動建立 GitHub PR)
     ```bash
     # macOS
     brew install gh
     
     # 其他平台
     # https://cli.github.com/
     ```

### 安裝步驟

#### 方法 1: 全域安裝 (推薦)

安裝到全域目錄，在所有專案中都可使用:

```bash
# 1. Clone 或下載此 Skill
git clone https://github.com/YOUR_USERNAME/package-upgrade-skill.git

# 2. 複製到 Claude Code 的全域 skills 目錄
mkdir -p ~/.claude/skills/
cp -r package-upgrade-skill/ ~/.claude/skills/package-upgrade/

# 3. 賦予 scripts 執行權限
chmod +x ~/.claude/skills/package-upgrade/scripts/*.sh
chmod +x ~/.claude/skills/package-upgrade/scripts/*.py
```

#### 方法 2: 專案級安裝

只在特定專案中使用:

```bash
cd /path/to/your/project

# 1. Clone 或下載此 Skill
git clone https://github.com/YOUR_USERNAME/package-upgrade-skill.git

# 2. 複製到專案的 .claude/skills/ 目錄
mkdir -p .claude/skills/
cp -r package-upgrade-skill/ .claude/skills/package-upgrade/

# 3. 賦予 scripts 執行權限
chmod +x .claude/skills/package-upgrade/scripts/*.sh
chmod +x .claude/skills/package-upgrade/scripts/*.py

# 4. (可選) 加入 .gitignore 如果不想 commit
echo ".claude/skills/package-upgrade/" >> .gitignore
```

### 驗證安裝

```bash
# 在任何專案中執行
claude

# 然後在 Claude Code 中輸入:
# "list available skills" 或 "show me the package-upgrade skill"

# 你應該會看到 package-upgrade 出現在 skills 列表中
```

---

## 快速開始

### 基本使用

直接在 Claude Code 中輸入升級指令:

```bash
claude
```

然後輸入以下任一指令:

```
升級 requests 到 2.32.0

幫我把 django 從 4.2 升到 5.1

修復 CVE-2024-35195

檢查 flask 能不能升級到 3.0
```

### 使用範例

#### 範例 1: 升級指定版本

```
使用者: 升級 requests 到 2.32.0

Claude Code:
1. 偵測環境 → 發現使用 pip
2. 分析依賴 → requests 是直接引用
3. 分析 breaking changes → 發現 3 個 API 變更
4. 掃描專案程式碼 → 找到 5 處受影響
5. 產生修改建議 → 展示 diff 並等待確認
6. 建立分支 feature/Update-requests-to-2.32.0
7. 執行升級 → 套用程式碼修改
8. 執行測試 → 通過
9. 產出報告 → 建立 PR
```

#### 範例 2: 修復 CVE

```
使用者: 修復 CVE-2024-35195

Claude Code:
1. 搜尋 CVE 資訊 → 找到受影響的套件: cryptography
2. 評估風險 → critical (專案直接使用受影響功能)
3. 找到修復版本 → 42.0.5
4. (後續流程同範例 1)
5. 建立分支 fix/CVE-2024-35195-cryptography
6. PR 標記為 security label
```

#### 範例 3: 依賴衝突處理

```
使用者: 升級 pydantic 到 2.0

Claude Code:
1. 偵測依賴 → pydantic 被 fastapi 和 sqlmodel 依賴
2. 發現衝突 → fastapi 要求 pydantic<2.0
3. 提出 3 種解決方案:
   - 方案 A: 同時升級 fastapi 到 0.100+ (推薦)
   - 方案 B: 使用 pydantic 1.10 (中間版本)
   - 方案 C: 使用 pip --force-reinstall (風險高)
4. 等待使用者選擇 → 使用者選 A
5. (繼續升級流程)
```

---

## 功能說明

### 自動化分析

- ✅ **環境偵測**: 自動識別 pip / poetry / uv
- ✅ **依賴樹分析**: 判斷直接 / 間接引用，識別版本衝突
- ✅ **Breaking Change 分析**: 
  - 解析 Changelog (PyPI / GitHub Releases)
  - 分析 Git Diff (tag 之間的程式碼變更)
  - 交叉驗證並合併結果
- ✅ **程式碼影響掃描**: AST 靜態分析找出所有受影響的使用位置
- ✅ **CVE 風險評估**: 判斷漏洞是否實際影響專案用法

### 智能修改

- ✅ 理解程式碼上下文，生成符合專案風格的修改
- ✅ 保持原有縮排、引號、命名慣例
- ✅ 只修改受影響的部分，不做無關的「改進」
- ✅ 提供完整 diff 預覽，等待確認後才套用

### 測試診斷

- ✅ 分層執行測試 (先跑受影響的，再跑全部)
- ✅ 三向交叉分析失敗原因:
  - 業務程式碼需要修改
  - 測試程式碼需要修改
  - 配置問題 (mock / fixture)
- ✅ 自動修復或提供修改建議
- ✅ 最多 3 次迴圈，避免無限嘗試

### Git 整合

- ✅ 自動建立 feature branch: `feature/Update-{Package}-to-{Version}`
- ✅ 環境備份與回退機制
- ✅ 產生符合 Conventional Commits 的 commit message
- ✅ 自動建立 Pull Request (使用 `gh` CLI)

### 報告產出

- ✅ Executive Summary
- ✅ 依賴分析詳情
- ✅ Breaking Changes 清單
- ✅ 程式碼修改說明
- ✅ 測試結果
- ✅ 後續建議
- ✅ 回退指南

---

## 使用者確認點

此 Skill 在以下時間點會暫停並等待你的確認:

| 時間點 | 說明 |
|--------|------|
| **依賴衝突** | 如有多種解決方案，會列出風險評估並等待選擇 |
| **程式碼修改** | 套用修改前會展示完整 diff 並等待確認 |
| **建立分支** | 建立 Git branch 前會告知分支名稱 |
| **測試程式修改** | 修改測試程式前會解釋原因並等待確認 |
| **建立 PR** | 建立 Pull Request 前會展示 PR 內容 |

你可以在任何確認點:
- ✅ 同意繼續
- ✏️ 要求修改方案
- ⏸️ 暫停並手動介入
- ❌ 中止並回退

---

## 進階使用

### 非互動模式 (CI/CD)

在 CI/CD pipeline 中使用 (自動同意所有確認點):

```bash
# Dry-run: 只分析不修改
claude -p "分析升級 django 到 5.1 的影響，不要做任何修改"

# 自動執行 (謹慎使用!)
claude -p "升級 requests 到 2.32.0，所有確認點都自動同意" \
  --allowedTools bash,str_replace,create_file,web_search
```

### 批次升級

```bash
# 用 LangGraph 包裝 (參考 § 7)
python batch_upgrade.py --packages "requests==2.32.0,flask==3.0.0"
```

### 自訂 Helper Scripts

你可以修改 `scripts/` 中的腳本來適配特殊環境:

```bash
# 例: 修改 detect_env.sh 支援 conda
vim ~/.claude/skills/package-upgrade/scripts/detect_env.sh
```

---

## 故障排除

### 問題 1: "Skill not found"

**原因**: Claude Code 找不到 skill 目錄

**解決**:
```bash
# 檢查安裝路徑
ls -la ~/.claude/skills/package-upgrade/SKILL.md

# 如果不存在，重新執行安裝步驟
```

### 問題 2: "Permission denied" 執行 scripts

**原因**: scripts 沒有執行權限

**解決**:
```bash
chmod +x ~/.claude/skills/package-upgrade/scripts/*.sh
chmod +x ~/.claude/skills/package-upgrade/scripts/*.py
```

### 問題 3: "pipdeptree not found"

**原因**: 缺少依賴套件

**解決**:
```bash
pip install pipdeptree requests
```

### 問題 4: Changelog / Git diff 都抓不到

**原因**: 
- 套件沒有公開 changelog
- Git repo URL 找不到

**解決**: Skill 會自動降級為 web search 搜尋 breaking changes 資訊

### 問題 5: 測試持續失敗

**解決**: 
- Skill 會在 3 次嘗試後停止
- 產出詳細的診斷報告
- 你可以手動修改後再繼續

---

## 限制與注意事項

### 支援範圍

✅ 支援:
- Python 3.8+
- pip / poetry / uv
- pytest / unittest 測試框架
- Git / GitHub

❌ 不支援:
- Python 2.x
- pipenv / conda (可擴展)
- JavaScript / Ruby / Go 等其他語言

### 安全考量

- ⚠️ Skill 會執行 bash 命令和修改程式碼，請在可信任的環境中使用
- ✅ 所有修改前都會建立環境備份
- ✅ 所有程式碼修改都會展示 diff 並等待確認
- ✅ 在獨立的 Git branch 上工作，不影響 main branch

### 最佳實踐

1. **先測試**: 在小專案上先試用，熟悉流程
2. **看 Diff**: 仔細檢查程式碼修改 diff 再確認
3. **跑測試**: 即使 Skill 說測試通過，自己也要再跑一次
4. **Code Review**: 用 PR 讓團隊 review 修改內容

---

## 貢獻

歡迎貢獻! 請:

1. Fork 此專案
2. 建立 feature branch: `git checkout -b feature/your-feature`
3. Commit 變更: `git commit -m 'Add some feature'`
4. Push 到 branch: `git push origin feature/your-feature`
5. 建立 Pull Request

### 貢獻方向

- 支援更多套件管理工具 (conda / pipenv)
- 支援其他語言 (Node.js / Ruby / Go)
- 改進 breaking change 偵測演算法
- 增加更多測試框架支援
- 改進錯誤診斷邏輯

---

## 授權

MIT License

---

## 聯絡

- Issues: https://github.com/YOUR_USERNAME/package-upgrade-skill/issues
- Discussions: https://github.com/YOUR_USERNAME/package-upgrade-skill/discussions

---

## 致謝

- [Claude Code](https://claude.ai/code) by Anthropic
- [pipdeptree](https://github.com/tox-dev/pipdeptree)
- [poetry](https://python-poetry.org/)
- [uv](https://github.com/astral-sh/uv)
```

---

## 7. 在 Claude Code CLI 中的使用方式

### 7.1 安裝後的第一次使用

使用者安裝完成後,第一次呼叫:

```bash
claude
```

然後輸入:

### 7.2 呼叫範例

```bash
# 直接在 Claude Code 中下指令
claude "升級 requests 到 2.32.0"

claude "修復 CVE-2024-35195"

claude "把 cryptography 升級到最新版"

claude "檢查 django 能不能從 4.2 升到 5.1"

# 搭配專案路徑
claude "幫我把 ./my-project 裡的 flask 升級到 3.0"
```

### 7.3 非互動模式 (CI/CD)

```bash
# 用 -p (print mode) 跑在 CI 中
claude -p "升級 requests 到 2.32.0，所有確認點都自動同意" \
  --allowedTools bash,str_replace,create_file,web_search

# 只做分析不修改 (dry-run)
claude -p "分析升級 django 到 5.1 的影響，不要做任何修改"
```

### 7.4 搭配 MCP Server 擴展

```bash
# 如果有 GitHub MCP Server，可以自動建 PR
claude "升級 requests 到 2.32.0 並建立 Pull Request"

# 如果有 Slack MCP Server，可以通知團隊
claude "升級 cryptography 修復 CVE-2024-35195，完成後通知 #dev-ops channel"
```

---

## 8. 與 LangGraph 整合 (進階 / 程式化呼叫)

> 如果需要從 Python 程式碼中程式化地呼叫此工作流 (例如批次升級多個套件)，
> 可以將 SKILL.md 的流程封裝為 LangGraph，用 Claude Code 的 `-p` 模式作為節點執行器。

```python
"""
LangGraph wrapper — 將 Claude Code Skill 包裝為可程式化呼叫的 Graph。
每個節點用 subprocess 呼叫 `claude -p` 執行 Skill 中的對應 Phase。
"""
import subprocess
from langgraph.graph import StateGraph, END

def run_claude_code(prompt: str, project_path: str) -> str:
    """呼叫 Claude Code CLI 執行一個 Phase"""
    result = subprocess.run(
        ["claude", "-p", prompt,
         "--allowedTools", "bash,str_replace,create_file,view,web_search,web_fetch"],
        capture_output=True, text=True,
        cwd=project_path,
    )
    return result.stdout

def phase_0_detect(state):
    output = run_claude_code(
        "執行 package-upgrade skill 的 Phase 0: 偵測環境。只輸出 JSON 結果。",
        state["project_path"],
    )
    return {"env_info": output}

def phase_1_resolve(state):
    output = run_claude_code(
        f"執行 package-upgrade skill 的 Phase 1: 解析輸入 {state['input_value']}",
        state["project_path"],
    )
    return {"resolved": output}

# ...其他 Phase 類似...

def build_batch_upgrade_graph():
    """用於批次升級多個套件的 LangGraph"""
    graph = StateGraph(dict)
    graph.add_node("detect", phase_0_detect)
    graph.add_node("resolve", phase_1_resolve)
    # ... 串接所有 Phase ...
    graph.set_entry_point("detect")
    graph.add_edge("detect", "resolve")
    # ...
    return graph.compile()

# 批次升級
packages_to_upgrade = ["requests==2.32.0", "flask==3.0.0", "django==5.1"]
graph = build_batch_upgrade_graph()
for pkg in packages_to_upgrade:
    result = graph.invoke({"input_value": pkg, "project_path": "./my-project"})
```

---

## 9. 總覽對比表

| 面向 | v2 (獨立 Python App) | v3 (Claude Code Skill) |
|------|---------------------|----------------------|
| **Orchestrator** | LangGraph (Python) | Claude Code 本身 |
| **LLM 引擎** | 透過 API 呼叫 Claude | Claude Code 自己就是 |
| **工具呼叫** | Python function | bash scripts |
| **狀態管理** | LangGraph StateGraph | Claude Code 對話上下文 |
| **使用者確認** | LangGraph interrupt | Claude Code 自然對話暫停 |
| **安裝方式** | pip install + 設定 API key | 複製到 ~/.claude/skills/ (全域) 或 .claude/skills/ (專案) |
| **安裝複雜度** | 高 (需管理依賴、API key) | 低 (複製檔案 + chmod) |
| **API 成本** | 每節點 1 次 API call (7+ 次) | 0 次額外 API call |
| **分發方式** | PyPI package | Git clone + 複製 |
| **擴展性** | 改 Python 程式碼 | 改 SKILL.md + scripts |
| **CI/CD** | Python script | `claude -p` |
| **批次處理** | LangGraph batch | LangGraph + `claude -p` |
| **MCP 整合** | 需自行實作 | 原生支援 |
| **Web Search** | 需整合 search API | Claude Code 原生工具 |
| **檔案編輯** | 自行實作 file I/O | str_replace / create_file |

---

## 10. 設計決策摘要

| 決策 | 選擇 | 理由 |
|------|------|------|
| 架構形式 | Claude Code Skill | 零額外 API 成本、零部署成本、原生工具鏈 |
| 分發方式 | Git clone + 檔案複製 | 簡單、透明、使用者可自訂 scripts |
| 安裝位置 | ~/.claude/skills/ (推薦全域) | 所有專案共用,一次安裝處處可用 |
| 前置依賴 | 最小化 (pipdeptree + requests) | 降低安裝門檻 |
| LLM 引擎 | Claude Code 本身 (4.6) | 不需要獨立呼叫 API，Claude Code 自己就是最強模型 |
| 確定性任務 | Helper scripts (bash/py) | AST 掃描、dep tree 解析等需要精確工具 |
| 分析任務 | Claude Code 原生推理 | Changelog 解析、diff 語意、測試診斷 |
| 使用者確認 | 對話自然暫停 | 不需要 interrupt 機制，Claude Code 會自然停下來問 |
| Breaking change | Changelog + Git Diff 雙軌 | 互補 — Claude 自己做合併去重 |
| 程式碼修改 | AST 定位 + Claude 生成 patch | AST 精確定位，Claude 理解上下文生成正確修改 |
| 測試修改 | 必須使用者確認 | 測試是品質防線，Claude 會解釋為什麼要改 |
| 批次處理 | LangGraph + claude -p | 可選的進階用法，不是核心依賴 |
| 回退機制 | snapshot_env.sh | 簡單可靠的檔案備份 |
| 報告生成 | Claude 自由撰寫 | 比模板填空更有洞察力和可讀性 |
