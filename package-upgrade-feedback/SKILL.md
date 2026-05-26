---
name: package-upgrade-feedback
description: >
  收集使用者跑完 `package-upgrade` skill 後的回饋並開成 GitHub Issue。
  當使用者輸入「/package-upgrade-feedback」、「回報 package-upgrade 問題」、
  「想給 package-upgrade 建議」、「package-upgrade 哪裡可以改」、
  「report package-upgrade issue」、「package-upgrade feedback」時觸發。
  互動式收集問題描述 + 重現步驟 + 建議改善方向，做 PII / secret sanitization，
  最後用 `gh issue create` 送到 millerlai/auto-package-migration 的 GitHub Issue
  (label=feedback)。不會送出任何 token、`/Users/...` 路徑、Jira key、
  內部 hostname、email 等敏感資料。
---

# Package Upgrade Feedback Skill

收集使用者對 `package-upgrade` skill 的改進建議，送出為 GitHub Issue。

## 設計原則

1. **互動式、不假設**：不自動讀任何檔案，從對話中問出問題與建議。
2. **Sanitization first**：所有送出的內容都要先過 `scripts/sanitize_feedback.sh`，
   token / 路徑 / Jira key / 內部 hostname / email 一律 redacted。
3. **使用者最後確認**：送出前一定 print 完整 issue body 給使用者看，等他點頭才呼叫 `gh`。
4. **失敗不阻擋**：`gh` 未認證 / 無 repo 寫權限時，fallback 印出可以手動 paste 到瀏覽器的
   pre-filled issue URL。

## Phase 1: 收集問題

**從零開始**，不要去找 `.package-upgrade-cache/` 或任何 IMPROVEMENT.md 檔案
(主 skill 不會自動產這種檔；如果使用者有手寫的 notes，會在 Phase 1 主動貼上來)。

逐項問使用者 (一次問一題，等他回完再問下一題)：

1. **這次跑 package-upgrade 你是想升什麼套件 / 修什麼 CVE？**
   - 用來判斷 language (Python / JS / Go) 與情境
   - 範例答案：「升 axios 1.6.0」、「修 CVE-2024-35195」、「BDSA-2024-xxxx」

2. **流程跑到哪一個 Phase 出問題？** (Phase 0 / 1 / 2 / 3 / 4 / 5 / 6 / 7 / 「順利跑完但有建議」)
   - 用來在 issue 上 tag 對的子系統

3. **具體遇到什麼問題？** (一段話描述 — 可多輪追問)
   - 鼓勵使用者描述「期待 vs 實際」
   - 例：「期待 Phase 4 AST 掃描列出所有 call sites，實際只列了 import statement」

4. **你建議怎麼改？** (這題最重要 — 若使用者沒想法可以跳過)
   - 鼓勵具體：「Phase 4 應該追到 method call 層級」比「掃得更深」更有用

5. **(選填) 還有什麼相關 context 想補充？**

注意事項：
- **不要問使用者套件管理 token、Jira ticket URL、檔案絕對路徑** — 那些是敏感資訊。
  如果使用者主動提，要在 Phase 3 sanitize 掉並提醒他。
- **不要要求使用者貼完整 stderr / log** — 一段關鍵錯誤訊息 (5-10 行) 已足夠，
  完整 log 容易夾帶路徑與 token。

## Phase 2: 草擬 Issue Body

把 Phase 1 蒐集的回答組成 markdown，遵循這個結構：

```markdown
## 情境
<語言、套件、CVE/BDSA/GHSA、或 Jira 觸發模式 — 都不含具體 ticket key>

## 出問題的 Phase
Phase <N> — <該 Phase 的名稱>

## 期待 vs 實際
**期待**: <一句話>
**實際**: <一句話>

## 詳細描述
<使用者的敘述，過濾敏感資料後>

## 建議改善方向
<使用者的建議；若無，寫 "_(no specific suggestion)_">

## 補充 Context
<選填>

---
_Submitted via `/package-upgrade-feedback`._
```

Title 取使用者問題的一句話摘要，prefix 用 `[feedback]`，全長 < 70 字。
例：`[feedback] Phase 4 AST scanner 漏掉 method call sites`

## Phase 3: Sanitize

把 Phase 2 草擬好的 markdown 寫到暫存檔，跑 `scripts/sanitize_feedback.sh`：

```bash
DRAFT=$(mktemp)
cat > "$DRAFT" <<'EOF'
<上一步的 markdown>
EOF

# Sanitization pass — 印 sanitized markdown 到 stdout、redaction list 到 stderr
SANITIZED=$(mktemp)
bash scripts/sanitize_feedback.sh "$DRAFT" > "$SANITIZED" 2> "$DRAFT.redactions"
```

**讀 `$DRAFT.redactions`** — 它會告訴你哪些 pattern 被替換了 (絕對路徑、token、Jira key、
internal hostname、email)。**如果有任何 redaction**，務必把這個清單 print 給使用者，
讓他知道：

```
🛡️ Sanitization 報告
- 移除了 1 個絕對路徑 (替換為 <path>)
- 移除了 1 個 Jira key (替換為 <JIRA-KEY>)
```

若 sanitizer 偵測到 **疑似 secret / token / API key**，**強制中斷流程**，告訴使用者：
「偵測到疑似 token 字串，請手動確認你貼的內容是否含敏感資料」並印出有問題的那幾行。

## Phase 4: 預覽 + 確認

把 sanitized 後的 final body print 給使用者，問：

> 以下是即將開的 GitHub Issue。確認沒問題後回 `y` 送出，回 `n` 取消，回 `edit` 進入修改模式。
>
> Repository: `millerlai/auto-package-migration`
> Label: `feedback`
> Title: `<title>`
>
> ```markdown
> <sanitized body>
> ```

`edit` 模式：問使用者要改哪一段、改成什麼，更新 draft 後**重新跑 Phase 3 sanitize**
(不要省略，使用者新貼的內容可能含敏感資料)。

## Phase 5: 送出

使用者確認後：

```bash
bash scripts/submit_feedback.sh \
    --title "<title>" \
    --body-file "$SANITIZED"
```

成功時 script 會 print issue URL，把 URL 給使用者。

**Fallback** — 若 script exit code != 0：

- exit 2: `gh` not installed → 印安裝指引 + 用 `https://github.com/millerlai/auto-package-migration/issues/new?...` URL 讓使用者手動開
- exit 3: `gh` not authed → 印 `gh auth login` 指引 + 手動 URL fallback
- exit 4: API 拒絕 (權限 / repo not found) → 印手動 URL fallback
- exit 其他: 印 stderr 並建議使用者手動 paste

手動 URL 格式 (URL-encode body)：
```
https://github.com/millerlai/auto-package-migration/issues/new?title=<encoded-title>&body=<encoded-body>&labels=feedback
```

## 流程總結

```
Phase 1 (互動收集)
  → Phase 2 (Claude 寫 markdown)
  → Phase 3 (sanitize_feedback.sh)
  → Phase 4 (預覽 + 使用者確認)
  → Phase 5 (submit_feedback.sh → gh issue create)
```

只有 Phase 5 會碰外部世界，其它都是 local。
