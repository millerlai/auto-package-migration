# Package Upgrade Skill for Claude Code

繁體中文 · [English](README.md)

一個 [Claude Code Skill](https://docs.claude.com/en/docs/claude-code/skills)，自動化
**Python**、**JavaScript / TypeScript**、**Go** 三大語言的套件升級、CVE 漏洞修復，以及
Jira ticket 驅動的維護工作。從觸發、依賴分析、breaking change 判讀、程式碼修改、
測試驗證，到 commit / PR / Jira ticket 回寫，一條 pipeline 跑完。

> ⚠️ 這份是 Quick start 指標版。完整介紹、Features、Examples、Documentation map 等
> 內容請看 [`README.md`](README.md)（英文）。

---

## 🚀 三分鐘上手

```bash
# 全域安裝（建議）
bash install.sh

# 驗證
bash verify_installation.sh
```

裝完後，有兩種觸發方式：

**A) Shell 一行觸發** — 從命令列直接帶 prompt 啟動：

```bash
claude "升級 requests 到 2.32.0"
claude "bump axios to 1.7.0"
claude "go get -u github.com/spf13/cobra@v1.8.0"
claude "修復 CVE-2024-35195"
claude "V1E-148968"                                          # Jira issue key
claude "https://trendmicro.atlassian.net/browse/V1E-148968"  # Jira URL
```

**B) 進到 Claude Code session 內** — 用 `/package-upgrade` slash command 顯式觸發：

```text
$ claude
> /package-upgrade 升級 requests 到 2.32.0
> /package-upgrade 修復 CVE-2024-35195
> /package-upgrade V1E-148968
```

或直接打自然語句，skill 的 description 會自動 match「升級 / bump / update / 修復 CVE / go get -u」這類措辭：

```text
> 升級 requests 到 2.32.0
> 看看 django 能不能從 4.2 升到 5.1
```

想要 deterministic 觸發（例如那句話 Claude 可能誤判成一般問題）時用 `/package-upgrade`；想打快就用自然語句。

Windows：`install.bat`（PowerShell）或 `install-cygwin64.sh`（Cygwin）。

完整安裝、手動安裝、故障排除、進階測試專案範本：[`docs/installation.md`](docs/installation.md)。

---

## 🌐 支援的語言與套件管理工具

| 語言 | 套件管理工具 | 進階能力 |
|------|--------------|----------|
| Python | `pip`、`poetry`、`uv` | pip-tools、自定義 `requirements.lock`、無 lock |
| JavaScript / TypeScript | `npm`、`yarn 3` (corepack)、`pnpm`（含 v9 lockfile） | TypeScript `.d.ts` API surface diff、workspace 偵測；`bun` 規劃中 |
| Go | `go modules` | major version path rewrite (v1 → v2+)、`apidiff` surface diff、`govulncheck` reachability、vendor mode、`go.work`、`replace` directives |

Phase 0 偵測順序：**Go > JS > Python**。

---

## 🎫 Jira 觸發

提供 Jira URL 或 issue key 即觸發完整流程：

1. 抓 ticket（MCP 優先 / REST + API token fallback）
2. 解析應升的 package / 版本 / CVE
3. 等你確認後跑 Phase 2–7
4. 把遷移報告 comment 回 ticket，並依目前狀態詢問 transition

Commit / PR 會自動加 `[ISSUE_KEY]` 前綴與 `Jira: <URL>`。

---

## 📚 文件導覽

- **這份** → 中文 Quick start 指標
- **完整 README** → [`README.md`](README.md)
- **安裝 / 驗證 / 測試專案** → [`docs/installation.md`](docs/installation.md)
- **貢獻 / 開發** → [`CONTRIBUTING.md`](CONTRIBUTING.md)
- **專案狀態 + roadmap** → [`docs/project-status.md`](docs/project-status.md)
- **版本歷史** → [`CHANGELOG.md`](CHANGELOG.md)
- **Skill 工作流程細節** → [`package-upgrade/SKILL.md`](package-upgrade/SKILL.md)（Phase 0–7）
- **套件管理工具命令對照** → [`package-upgrade/QUICK_REFERENCE.md`](package-upgrade/QUICK_REFERENCE.md)
- **語言專屬參考** → `package-upgrade/references/{common,python,javascript,go}/*.md`

---

## 📄 授權

MIT — 詳見 `package-upgrade/LICENSE`。
