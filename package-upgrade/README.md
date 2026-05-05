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

4. **Atlassian MCP** (可選, 啟用 Jira 整合)
   - 只在你想用 Jira URL / Jira ID 觸發升級流程時需要
   - 細節見下方「可選: Atlassian MCP 安裝」

### 安裝步驟

#### 方法 1: 全域安裝 (推薦)

安裝到全域目錄，在所有專案中都可使用:

```bash
# 1. Clone 或下載此 Skill
git clone https://github.com/YOUR_USERNAME/package-upgrade-skill.git

# 2. 複製到 Claude Code 的全域 skills 目錄
mkdir -p ~/.claude/skills/
cp -r package-upgrade-skill/package-upgrade ~/.claude/skills/

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
cp -r package-upgrade-skill/package-upgrade .claude/skills/

# 3. 賦予 scripts 執行權限
chmod +x .claude/skills/package-upgrade/scripts/*.sh
chmod +x .claude/skills/package-upgrade/scripts/*.py

# 4. (可選) 加入 .gitignore 如果不想 commit
echo ".claude/skills/package-upgrade/" >> .gitignore
```

### 可選: Atlassian MCP 安裝 (Jira 整合)

啟用後,你可以用 Jira URL (例 `https://trendmicro.atlassian.net/browse/V1E-148968`)
或 Jira ID (例 `V1E-148968`) 觸發升級流程,完成後自動將報告 comment 回 ticket
並可選擇將 status 轉為 Done。

#### 路徑 A: claude.ai connectors (推薦)

最簡單的方式 — 你的環境多半已預裝。確認:

```bash
claude mcp list | grep -i atlassian
```

預期輸出:
```
claude.ai Atlassian Rovo: https://mcp.atlassian.com/v1/mcp - ✓ Connected
```

若顯示 `! Needs authentication` → 啟動 Claude Code 後執行 `/mcp` 登入即可,
無需手動配置 token。

#### 路徑 B: 自架 MCP + API token (適合 CI 或無 OAuth 的情境)

```bash
# 1. 取得 Atlassian API token
# 開啟: https://id.atlassian.com/manage-profile/security/api-tokens
# 點 "Create API token"

# 2. 註冊 MCP server (token 會寫入 ~/.claude.json)
claude mcp add atlassian \
  --env ATLASSIAN_SITE=trendmicro.atlassian.net \
  --env ATLASSIAN_EMAIL=you@example.com \
  --env ATLASSIAN_API_TOKEN=<your_token> \
  -- npx -y @modelcontextprotocol/server-atlassian

# 3. 驗證
claude mcp list | grep atlassian
```

⚠️ Token 會寫入 `~/.claude.json`,建議:
- 使用最小權限的 token (僅讀寫所需 project)
- 用完後到 Atlassian 後台 revoke

#### 路徑 C: 不安裝 MCP, 用 REST API fallback

Skill 內建 fallback — 若 MCP 不可用,會主動詢問你是否提供 API token,
然後透過 `scripts/jira_fetch.py` / `jira_comment.py` / `jira_transition.py`
直接呼叫 REST API。Token 只在當前 session 暫存,不寫入任何檔案。

⚠️ 這個模式下,token 會出現在對話 transcript 中,慎用。

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

處理這張 Jira ticket: https://trendmicro.atlassian.net/browse/V1E-148968

V1E-148968
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

#### 範例 4: 從 Jira ticket 觸發 (需 Atlassian MCP)

```
使用者: https://trendmicro.atlassian.net/browse/V1E-148968

Claude Code:
1. 用 Atlassian MCP 抓取 ticket 內容
   ├── 若 401/403 → 詢問是否提供 API token (REST fallback)
   └── 若 200 → 解析
2. 從 summary/description 抽出: 套件 = requests, 目標版本 = 2.32.0
3. 列出解析結果並等待確認 ✋
4. (執行標準升級流程 Phase 2-7)
5. 升級完成後:
   ├── 確認後將遷移報告 comment 回 ticket ✋
   └── 詢問是否將 ticket status 轉為 Done ✋
        ├── [Y] → 自動 transition (CVE 修復用 resolution=Fixed,一般升級用 Done)
        ├── [O] → 列出所有 transitions 讓你挑
        └── [N] → 保持目前狀態
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
| **Jira ticket 解析** | 從 ticket 抽到的 package/版本/驗收條件,等你校正 (僅 Jira 觸發) |
| **依賴衝突** | 如有多種解決方案，會列出風險評估並等待選擇 |
| **程式碼修改** | 套用修改前會展示完整 diff 並等待確認 |
| **建立分支** | 建立 Git branch 前會告知分支名稱 |
| **測試程式修改** | 修改測試程式前會解釋原因並等待確認 |
| **建立 PR** | 建立 Pull Request 前會展示 PR 內容 |
| **Post Jira comment** | comment 預覽 + ticket URL,確認後才 post (僅 Jira 觸發) |
| **Jira status 轉換** | 列出目前狀態 → 目標狀態,絕不自動執行 (僅 Jira 觸發) |

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

可以使用 LangGraph 包裝多個套件的升級流程。詳見架構文件 § 8。

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
