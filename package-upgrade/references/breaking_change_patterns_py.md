# Python Breaking Change Patterns

> 對應 JS 的 `breaking_change_patterns_js.md` / Go 的 `breaking_change_patterns_go.md`。
> 通用語言無關規則仍放在 `breaking_change_patterns.md`，本檔放 Python 慣例。

---

## Changelog / Release Notes 措辭

下列措辭強烈暗示 breaking change：

| 措辭 | 推測的 breaking change | 信心 |
|------|---------------------|------|
| "drop support for Python X.Y" | runtime 不相容 | 高 |
| "removed deprecated `X`" | symbol 刪除 | 高 |
| "renamed `X` to `Y`" | symbol 重命名 | 高 |
| "X is now keyword-only" | positional 呼叫失敗 | 高 |
| "X is now positional-only" | keyword 呼叫失敗 | 高 |
| "now returns a coroutine" / "is now async" | 同步呼叫變 `RuntimeWarning: coroutine ... was never awaited` | 高 |
| "default value of `X` changed" | 行為靜默改變（**隱含 breaking**） | 中 |
| "`X` raises `Y` instead of `Z`" | except 句子要改 | 高 |
| "`X` is now strict by default" | 過去 lenient 的輸入會 raise | 中 |
| "removed C extension support for ..." | wheel 缺、ABI break | 高 |
| "minimum requires `numpy >= 2`" | parent peer 升級（連鎖反應） | 高 |
| "deprecated in 1.x, removed in 2.0" | 已知舊路徑被砍 | 高 |

---

## Python 特有的 breaking patterns

### A. `@deprecated` decorator（PEP 702, Python 3.13+）

新版套件常用 `warnings.warn(DeprecationWarning)` 或 `@typing_extensions.deprecated`
標記即將移除的 API。Phase 3 應 grep changelog 中提到此 decorator 的位置，
列入「下版會炸但這版還能用」清單，Phase 4 修改建議優先處理這些。

偵測：在 source diff 中找新增的 `warnings.warn`、`@deprecated`、`@typing_extensions.deprecated`。

### B. `__getattr__` module-level 攔截（PEP 562）

```python
# pkg/__init__.py — 舊版
def __getattr__(name):
    if name == "ClientSession":
        warnings.warn("import from pkg.client instead", DeprecationWarning)
        from pkg.client import ClientSession
        return ClientSession
    raise AttributeError(name)

# 新版直接拿掉這個 fallback
```

效果：`from pkg import ClientSession` 在舊版會 work（透過 `__getattr__`），
新版直接 `ImportError`。AST scanner 找 `from pkg import` 的位置會抓到這類用法。

Phase 4 修法：依 deprecation message 改 import 路徑為新位置。

### C. `from __future__ import annotations` 影響

新版套件若加上 `from __future__ import annotations`，所有 type hint 變字串。
對使用 `inspect.signature(...).return_annotation` 或 `typing.get_type_hints()`
讀取型別資訊的下游程式碼有影響——舊版拿到 type object，新版拿到 string。

偵測：source diff 中該語句出現在新增的 `__init__.py` / 主模組頂層。

### D. Type hint 變更（`Optional[X]` → `X | None`）

純語法層面變更（PEP 604）。對 runtime 沒影響，但對下游用 mypy strict 跑型別檢查的
專案會炸——`Optional[int]` 與 `int | None` 在 mypy 解析時某些 corner case 處理不一樣
（特別是和 generic / Protocol 互動時）。

### E. async / sync API 切換

```python
# 舊版
result = client.get(url)

# 新版
result = await client.get(url)   # 變 coroutine
# 舊呼叫 silently 拿到 coroutine object 而非 result
```

最痛點是**沒有錯誤**，只是 `result` 變成 coroutine。Phase 4 應 grep changelog 找
"async by default"、"now returns a coroutine"，並在 AST scanner 中標記所有對應呼叫。

### F. `__all__` 變更（隱性 export 移除）

```python
# 舊版 pkg/__init__.py
__all__ = ["Client", "Server", "_helper"]

# 新版
__all__ = ["Client", "Server"]
```

`from pkg import *` 不再帶 `_helper`，但 `from pkg import _helper` 仍 work——
只是 pylint / ruff 會 warn `unused-import`。
Breaking 對 wildcard import 的下游；對 explicit import 無影響。

### G. C extension ABI 變更

`numpy 1.x → 2.x` 重新編譯了 ABI，所有依賴 numpy C API 的套件
（`scipy`、`pandas`、`pytorch`、`tensorflow`、`pyarrow` 等）必須 rebuild。

徵兆（changelog 中）：
- "ABI break"
- "all C extension consumers must be rebuilt"
- "minimum supported numpy version is now N"

偵測：`pip show numpy` 與 `pip show <dependent>` 比對；若 dependent 編譯時的 numpy
ABI version 與 runtime numpy 不一致，import 期會 `RuntimeError: module compiled
against API version 0x10 but this version of numpy is 0x11`。

### H. `pyproject.toml` 必填欄位變更

新版 packaging 工具（`setuptools 77+`、`hatchling 1.x`、`uv 0.4+`）開始嚴格要求
`[project]` 中某些欄位（如 `requires-python`）。consumer 升級時 `pip install -e .`
會 fail 而非 silent ignore。

### I. `pkg_resources` 取消

setuptools 75+ 強烈建議改用 `importlib.metadata`，部分 distribution 已停用
`pkg_resources`。徵兆：
- changelog 提到 "removed pkg_resources"
- 套件原本提供的 `pkg_resources.iter_entry_points(...)` 介面不再回 plugin

對 consumer 影響：所有 `pkg_resources.*` 呼叫要改 `importlib.metadata.*` 或
`importlib.resources.*`。

### J. Pickle 格式變更

若套件 internal class 在 pickle 中被序列化（用於 cache / DB），新版可能因
`__reduce__` / `__setstate__` 改變而無法 unpickle 舊資料。

徵兆：major version bump + class layout 變更。建議升級時 invalidate 所有
pickle cache。

---

## `api_surface_diff_py.sh` 報告類別對應

`api_surface_diff_py.sh` 比對 inspect 模組 surface：

| 報告類別 | 對 consumer 的衝擊 |
|---------|-------------------|
| `removed` (function) | 🔴 `from pkg import x` ImportError |
| `removed` (class) | 🔴 `pkg.Cls()` AttributeError / NameError |
| `signature_change`（positional/keyword 變化） | 🔴 TypeError 在 call site |
| `default_change`（預設值變） | 🟡 行為靜默變更 |
| `return_type_change`（type hint 變） | 🟡 mypy / static 警告，runtime 通常 OK |
| `deprecated_new` | 🟡 短期可用，需排程移除 |
| `exception_type_change` | 🔴 `except` 句子失效 |
| `added` | 🟢 |

`api_surface_diff_py.sh` 信心分數 baseline 0.65（vs Go 的 0.9）—— Python 動態本質
讓 surface 抽取無法 100% 涵蓋 `__getattr__` / 動態 class 等情境。

---

## Phase 4 常見修法 cookbook

| 偵測情境 | 修法 |
|---------|------|
| `from pkg import X`，新版 X 從 pkg 移到 pkg.submod | 改 `from pkg.submod import X`；保留 fallback try/except 以支援舊版直到 parent 也升級 |
| `pkg.f(a, b)`，新版 f 變 keyword-only | 改 `pkg.f(a=a, b=b)` |
| `result = client.get(url)`，新版返 coroutine | 在 async context: `result = await client.get(url)`；非 async: 用 `asyncio.run(client.get(url))` 或維持舊版 |
| `try: ... except ValueError`，新版改 raise `ClientError` | 改 except；若需向後相容用 `(ValueError, ClientError)` tuple |
| `from pkg import *` 拿不到舊符號（`__all__` 收緊） | 改成 explicit import |
| `pkg_resources.iter_entry_points("group")` | 改 `importlib.metadata.entry_points(group="group")`（Python 3.10+） |

---

## 為什麼有這份文件

JS / Go 各有專屬的 breaking_change_patterns，Python 一直只有通用版
`breaking_change_patterns.md`，缺 `@deprecated` / `__getattr__` / async/sync 切換 / C ext ABI
等 Python 慣例（TODO.md 任務 2.3）。Phase 3 報告 Python 升級時，本檔提供：

1. changelog 措辭辭典（語意分析的 anchor）
2. 動態語言特有的 breaking 機制
3. `api_surface_diff_py.sh` 類別到衝擊的對應表
4. Phase 4 修法 cookbook
