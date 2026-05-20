# BlackDuck BDSA → Public CVE / GHSA mapping

> 內部 BlackDuck ticket 經常只給 `BDSA-YYYY-NNNNN` 內部 URL
> (`blackduck.trendmicro.com/api/vulnerabilities/...`)，外部不可存取，
> 對應的 public CVE/GHSA 編號得自己查。下面這個 fallback 鏈是已驗證能找到的最快路徑。

---

## 觸發條件 (Phase 1.C.3)

Jira ticket summary / description 符合以下 pattern 任一即觸發：

- `[BlackDuck] [<project>/<branch>] BDSA-... <pkg>-<ver>`
- description 含 `blackduck.trendmicro.com/api/vulnerabilities/BDSA-...`
- comments 含「BDSA-」開頭的 ID 字串

抽取 `<pkg>` (含 ecosystem 推斷) 和 `<ver>`，準備跑 fallback 鏈。

---

## Fallback 鏈 (按優先序試)

### Step 1: 查本檔案下方的「已知 mapping cache」

直接 grep — 若已有則用，避免重複查詢。

### Step 2: `osv.dev` API 查當前版本是否含已知漏洞

```bash
curl -sX POST https://api.osv.dev/v1/query \
  -H 'Content-Type: application/json' \
  -d '{"package": {"name": "<pkg>", "ecosystem": "npm"}, "version": "<ver>"}' | jq
```

回傳會列出所有匹配的 advisory，含 `aliases` 欄位（通常含對應的 CVE-/GHSA-）。

例：
```jsonc
{
  "vulns": [{
    "id": "GHSA-v2v4-37r5-5v8g",
    "aliases": ["CVE-2026-42338"],
    "summary": "..."
  }]
}
```

OSV 對 npm / PyPI / Maven / RubyGems / Cargo / Go 都覆蓋良好。

### Step 3: GitHub Advisory Database

```bash
gh api graphql -f query='
query($pkg: String!) {
  securityVulnerabilities(first: 5, package: $pkg, ecosystem: NPM) {
    nodes {
      advisory { ghsaId identifiers { type value } summary severity }
      vulnerableVersionRange
    }
  }
}' -F pkg='<pkg>'
```

或更簡單的 web search：`site:github.com/advisories <pkg> <ver>`

### Step 4: `npm audit` (僅 npm 專案、且有 node_modules)

```bash
cd <project> && npm audit --json | jq '.advisories'
```

通常會列出 `cves` 與 `ghsa_id` 欄位 — 是 in-repo 最快的方式但需要 install state。

### Step 5: `pip-audit` / `safety check` (僅 Python 專案)

```bash
pip-audit --format json
# or
safety check --json
```

---

## 報告中怎麼寫

Phase 7.1 報告必須包含「BDSA → CVE → GHSA 三方對映」：

```markdown
## Vulnerability Mapping

| Source | ID | URL |
|--------|-----|-----|
| BlackDuck (internal) | BDSA-2026-10197 | https://blackduck.trendmicro.com/api/vulnerabilities/BDSA-2026-10197 (internal only) |
| Public CVE | CVE-2026-42338 | https://nvd.nist.gov/vuln/detail/CVE-2026-42338 |
| GitHub Advisory | GHSA-v2v4-37r5-5v8g | https://github.com/advisories/GHSA-v2v4-37r5-5v8g |
| OSV | GHSA-v2v4-37r5-5v8g | https://osv.dev/vulnerability/GHSA-v2v4-37r5-5v8g |

**Severity**: Moderate (CVSS 5.3)
**Mapping source**: OSV API query at <UTC timestamp>
```

讓 PR reviewer 不用再翻內部 BlackDuck 系統就能驗證對映正確。

---

## 已知 mapping cache (新發現的請追加)

| BDSA | Public CVE | GHSA | Package | Ecosystem | Severity | Discovered |
|---|---|---|---|---|---|---|
| BDSA-2026-10197 | CVE-2026-42338 | GHSA-v2v4-37r5-5v8g | `ip-address` | npm | Moderate (CVSS 5.3) | 2026-05-20 |

<!-- skill 升級遇到新 BDSA → 找到 public mapping 後，請將該行 append 到上表。下次 session 跑 Step 1 就能直接命中。 -->

---

## Phase 1.C.3 抽取規則 update

原本只抽 `CVE-XXXX-XXXXX`。改為同時抽：

```python
patterns = [
    re.compile(r'CVE-\d{4}-\d{4,7}'),           # public CVE
    re.compile(r'BDSA-\d{4}-\d+'),              # BlackDuck internal
    re.compile(r'GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}'),  # GitHub Advisory
]
```

若只抽到 `BDSA-...` 而沒有 `CVE-...` → 走上面的 fallback 鏈把 mapping 補齊，
再以 public CVE/GHSA 進入 Phase 2 後續流程（外部資料才能查到 fixed version）。
