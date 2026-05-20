# 遷移報告結構指南

## 寫作原則

- **用你自己的語言,不要模板填空**
- **先結論,後細節**
- **每個 section 開頭一句話總結**
- **技術細節用程式碼區塊呈現**
- **避免冗長的敘述,重點在「為什麼」和「影響」**

---

## 報告結構

### 0. References (必要) — 報告**第一節**就放外部連結

**目的**: 讓 reviewer 在 5 秒內找到所有外部來源 (Changelog / Diff / PR / Jira / CVE)，
不用翻到報告深處找。

**應包含**：
- Changelog URL (Phase 3.1 `changelog_source.url`)
- Diff / Compare URL (Phase 3.2 `git_diff_source.compare_url`)
- PR URL (Phase 7.3)
- Jira URL (僅當 `jira_context` 存在)
- CVE / GHSA / BDSA URL (若 Phase 1.B 觸發)

**格式**：

```markdown
## References

- **Changelog**: https://github.com/psf/requests/releases
- **Diff**: https://github.com/psf/requests/compare/v2.28.0...v2.32.0
- **PR**: https://github.com/your-org/your-repo/pull/123
- **Jira**: https://trendmicro.atlassian.net/browse/V1E-148968
- **CVE-2024-35195**: https://nvd.nist.gov/vuln/detail/CVE-2024-35195
```

**Changelog 找不到時**：寫 `_(no changelog found — analysis based on git diff only)_`
而不是省略整行 — 讓 reviewer 知道分析的局限。

---

### 1. Executive Summary (必要)

**目的**: 用 3-5 句話讓讀者快速掌握整個升級的重點

**應包含**:
- 升級了什麼套件、從哪個版本到哪個版本
- 為什麼要升級 (新功能 / 安全修復 / 依賴要求)
- 影響範圍 (幾個 breaking changes / 幾個檔案受影響)
- 最終結果 (測試通過 / 部分失敗 / 需要後續處理)

**範例**:
```markdown
## Executive Summary

Upgraded `requests` from 2.28.0 to 2.32.0 to fix CVE-2024-35195 (High severity).
Found 3 breaking changes affecting 8 files across the codebase.
Modified 12 locations to adapt to new API signatures.
All 47 tests passed after modifications.
```

---

### 2. 依賴分析 (如有衝突才需要詳述)

**目的**: 說明此套件在專案中的角色和依賴關係

**應包含**:
- 直接引用 / 間接引用 / 兩者皆有
- 如果是間接引用,列出所有 parent packages
- 版本衝突的處理過程
- 最終採用的解決方案

**何時可以簡化**:
- 直接引用且無衝突 → 一句話帶過
- 間接引用但 parent 版本相容 → 列出 parent 即可

**範例** (有衝突時):
```markdown
## Dependency Analysis

**Type**: Both direct and transitive dependency

**Direct usage**: Declared in `requirements.txt` for HTTP client
**Transitive usage**: Also required by `httpx` (>=2.30) and `aiohttp` (>=2.28)

**Conflict detected**: `httpx` requires `requests>=2.30,<2.31`

**Resolution**: Upgraded `httpx` from 0.24.0 to 0.27.0 simultaneously to allow `requests==2.32.0`.
```

---

### 3. Breaking Changes (核心章節)

**目的**: 詳細記錄所有 breaking changes,按影響程度排序

**應包含**:
- 變更的 API / 模組 / 行為
- 來源 (Changelog / Git Diff / 兩者)
- 信心分數
- 舊用法 → 新用法
- 影響了專案中的哪些檔案
- 如何修改的

**格式建議**:
```markdown
## Breaking Changes

### 🔴 BC-001: `requests.models.Response.content` encoding changed

**Source**: Changelog ✅ + Git Diff ✅  
**Confidence**: 0.98  
**Impact**: Default encoding changed from `latin-1` to `utf-8`

**Old behavior**:
```python
response.content.decode('latin-1')  # Was the default
```

**New behavior**:
```python
response.content.decode('utf-8')  # Now the default
```

**Files affected**:
- `src/api/client.py:45` - HTTP response parsing
- `src/utils/http.py:123` - Response body handling
- `tests/test_api.py:67` - Response assertion

**Migration**: Updated all `.decode()` calls to explicitly specify encoding.
```

---

### 4. 程式碼修改 (核心章節)

**目的**: 清楚記錄每個檔案的修改內容和原因

**應包含**:
- 按檔案分組
- 每個檔案改了幾處、為什麼改
- 關鍵的 diff (不需要完整 diff,只要關鍵片段)

**格式建議**:
```markdown
## Code Modifications

### `src/api/client.py` (2 changes)

**Change 1** (Line 45): Update response parsing  
Related to: BC-001  
```diff
- data = response.content.decode('latin-1')
+ data = response.content.decode('utf-8')
```

**Change 2** (Line 78): Update error handling  
Related to: BC-002  
```diff
- except requests.exceptions.RequestException as e:
+ except requests.exceptions.HTTPError as e:
```

### `tests/test_api.py` (1 change)

**Change 1** (Line 67): Update test assertion for new encoding  
```diff
- assert response.text == expected_latin1
+ assert response.text == expected_utf8
```
```

---

### 5. 測試結果

**目的**: 記錄測試執行結果和診斷過程

**應包含**:
- 通過 / 失敗 / 總共的測試數量
- 是否修改了測試程式 (如有,說明為什麼)
- 失敗診斷的迴圈次數 (如有)
- 最終狀態

**格式建議**:
```markdown
## Test Results

**Final Status**: ✅ All tests passed

**Test Suite**:
- Total tests: 47
- Passed: 47
- Failed: 0
- Skipped: 0

**Test Modifications**: Yes (3 tests updated)

**Modified tests**:
1. `tests/test_api.py::test_response_encoding` - Updated expected encoding from latin-1 to utf-8
2. `tests/test_client.py::test_error_handling` - Updated exception type assertion
3. `tests/test_utils.py::test_parse_response` - Updated mock response encoding

**Reason for modifications**: Tests were asserting on old behavior. Updated to verify new behavior is correct.

**Diagnosis iterations**: 2
- Iteration 1: Fixed source code (2 locations)
- Iteration 2: Fixed test code (3 tests)
```

---

### 6. 後續建議 (加分項)

**目的**: 提供有價值的後續改進建議

**應包含**:
- 相關套件是否也該更新
- 被棄用但這次沒改的 API (可列為 tech debt)
- 新功能可以考慮使用
- 需要追蹤的警告

**範例**:
```markdown
## Follow-up Recommendations

### Related package updates to consider:
- `urllib3`: Current 1.26.x has security warnings, recommend upgrading to 2.x
- `certifi`: Should be updated to latest for certificate bundle

### Deprecated APIs (not yet breaking):
- `requests.utils.get_encodings_from_content()` marked as deprecated, use `charset_normalizer` instead
- Migration can be deferred to next major release

### New features available:
- Connection pooling improvements in 2.32.x
- Consider enabling `trust_env=True` for proxy support

### Warnings to monitor:
- 3 deprecation warnings detected in test runs
- Should be addressed before next major upgrade
```

---

### 7. 回退指南 (必要)

**目的**: 提供清楚的回退步驟,以防需要緊急回退

**應包含**:
- 回退命令
- 注意事項
- 影響評估

**格式建議**:
```markdown
## Rollback Guide

### Quick rollback

**For pip**:
```bash
# Restore from snapshot
bash scripts/snapshot_env.sh . restore

# Or manually downgrade
pip install requests==2.28.0
```

**For poetry**:
```bash
poetry add requests@2.28.0
```

**For uv**:
```bash
uv pip install requests==2.28.0
```

### Rollback checklist

- [ ] Restore dependency files from `.upgrade_snapshot/`
- [ ] Revert code changes: `git revert <commit_hash>`
- [ ] Revert test changes if modified
- [ ] Run tests to verify rollback
- [ ] Clear package cache if needed

### Impact of rollback

⚠️ **Security warning**: Rolling back will reintroduce CVE-2024-35195 (High severity)

**Alternative**: If rollback is necessary, ensure the vulnerable endpoint is not exposed or add WAF rules to mitigate.
```

---

## 寫作技巧

### ✅ 好的寫法

```markdown
Upgraded requests from 2.28.0 to 2.32.0 to fix CVE-2024-35195. 
Found 3 breaking changes, modified 8 files, all tests passed.
```

### ❌ 避免的寫法

```markdown
This report documents the comprehensive migration process undertaken 
to upgrade the requests library package from version 2.28.0 to the 
newer version 2.32.0, which was necessary due to...
```

### ✅ 好的技術說明

```markdown
**BC-001**: `Response.content` encoding changed from latin-1 to utf-8
**Impact**: 8 files parsing HTTP responses needed `.decode()` update
```

### ❌ 避免的技術說明

```markdown
The Response object's content attribute has undergone a modification 
in its default encoding behavior, transitioning from the previously 
utilized latin-1 encoding to...
```

---

## 完整範例

參考 [package-upgrade-agent-architecture.md](../package-upgrade-agent-architecture.md) § 3 Phase 7 中的報告範例。

---

## 關鍵提醒

1. **不是模板填空**: 依據實際情況調整內容,不要機械式照抄結構
2. **簡潔為上**: 每句話都要有資訊價值,避免冗詞贅字
3. **程式碼為證**: 用 diff 和程式碼片段說話,少用抽象描述
4. **面向讀者**: 寫給會 review PR 的工程師,不是寫論文
5. **可操作性**: 提供具體的後續行動項和回退步驟
