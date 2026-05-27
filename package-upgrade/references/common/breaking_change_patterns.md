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

## 分析技巧

### 從 Changelog 分析
1. 搜尋關鍵字: "removed", "breaking", "renamed", "changed", "deprecated"
2. 注意版本號跳躍 (1.x → 2.x 通常有 breaking changes)
3. 查看 "Migration Guide" 或 "Upgrade Guide" 章節

### 從 Git Diff 分析
1. 聚焦 public API (非 `_` 開頭的函式/類別)
2. 檢查 `__init__.py` 中的 `__all__` 變更
3. 注意函式簽名的參數順序和預設值
4. 檢查回傳值的 type hint 變更

### 信心分數參考
- **0.95-1.0**: Changelog + Diff 雙重確認,明確說明
- **0.8-0.94**: Changelog 明確提到或 Diff 顯示清楚刪除
- **0.6-0.79**: Diff 顯示但 Changelog 未記錄
- **0.4-0.59**: 推測可能有影響,需進一步驗證
- **< 0.4**: 不確定,建議標記為 "需要人工確認"
