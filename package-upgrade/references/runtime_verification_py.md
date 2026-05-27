# Runtime Verification (Python) — Reference

> Lazy-loaded by `SKILL.md` Step 0.5 (baseline) and Step 6.6 (post-upgrade verify).
> 只在 `language: "python"` 且該套件升級後可能造成 import-time 或啟動期破壞時讀。

Phase 6 的單元測試 (`run_tests.sh`) 通常只覆蓋業務邏輯。
**`pytest` 全綠但 `python -c "import pkg"` 直接炸**、
**`pytest` 全綠但 `django runserver` 啟動失敗**、
**`pytest` 全綠但 CLI entry point `mypkg --version` 因 plugin 註冊失敗而 segfault** —
都是 Python 升級實務上常見的回歸，特別當套件有 C extension、有 conftest-style auto-discovery、
或本身提供 console entry point 時。

Runtime verification 補上這個 gap：升級前抓 baseline，升級後重跑，diff 兩者，
把**新出現的**錯誤歸因為本次升級。

---

## 三層偵測 (tier)

對應 JS 版的 T1/T2/T3 概念，但 Python 場景更分歧（CLI / web / library / data stack），
需要依專案類型挑 tier：

| Tier | 適用 | 內容 | 偵測能力 |
|------|------|------|----------|
| **T1-import** | 任何 Python 專案（最低門檻） | `python -c "import <pkg>"` + 列印 `<pkg>.__version__`；若失敗則用 `python -X importtime` 補抓哪個 sub-module 死 | C extension ABI 不相容、`importlib.metadata` plugin 註冊失敗、`__init__.py` side-effect 失敗 |
| **T1-cli** | 套件有 console entry point（讀 `pyproject.toml [project.scripts]` / `setup.cfg [options.entry_points]`） | spawn entry point with `--version` 或 `--help`，60 秒 timeout，scan stderr 找 traceback | CLI plugin loader 出錯、argparse 介面變動、deprecated flag 被移除 |
| **T2-web** | 偵測到 web framework（見下表） | T1 + spawn dev server → 等 ready 訊號 → HTTP GET `/` 檢查 status + body 非空 | ORM schema mismatch、middleware load 失敗、ASGI/WSGI 介面變更、SSL/TLS lib 不相容 |
| **T2-data** | 偵測到 scientific stack（`numpy` / `pandas` / `scipy` / `torch` / `sklearn` 在依賴中） | T1 + 執行一個最小 round-trip（建 array / DataFrame → 序列化 → 反序列化 → 數值比對） | dtype 行為改變、API rename、ABI break（特別 `numpy 1.x → 2.x`） |
| **T3** | fallback | 列印重現指令，請使用者手動驗證，記錄 pass/fail/skip | 仰賴人眼 |

`SKILL.md` 預設一律先跑 T1-import；
有 CLI entry point 就加跑 T1-cli；
偵測到 web 就**詢問**使用者是否跑 T2-web（spawn dev server 風險較高，可能 mutate DB）；
偵測到 scientific stack 就**詢問**是否跑 T2-data；
拒絕或無法跑 → 退到 T3。

---

## Web framework 偵測訊號

讀 `pyproject.toml` / `requirements*.txt` 抓依賴名：

| 出現任一就視為 web app | Framework |
|------------------------|-----------|
| `django` | Django |
| `flask` | Flask |
| `fastapi` | FastAPI |
| `starlette` | Starlette |
| `aiohttp` | aiohttp |
| `tornado` | Tornado |
| `pyramid` | Pyramid |
| `sanic` | Sanic |
| `bottle` | Bottle |

Dev-server 啟動指令（依優先序）：

| Framework | 啟動 | Default port | Ready 訊號 |
|-----------|------|--------------|-----------|
| Django | `python manage.py runserver 0:8000 --noreload` | 8000 | `Starting development server at` |
| Flask | `flask --app <app> run --port 5000` | 5000 | `Running on http://` |
| FastAPI | `uvicorn <app>:app --port 8000` | 8000 | `Uvicorn running on` |
| Starlette | `uvicorn <app>:app --port 8000` | 8000 | `Uvicorn running on` |
| aiohttp | `python -m <pkg>` (要 inspect main module) | 8080 | `Running on http://` |
| Tornado | `python <main.py>` | 8888 | `Listening on` |

> ⚠️ Django 在啟動時若有未跑的 migration 可能會卡（`runserver` 不會自動 migrate 但會 warn）。
> 升級前後使用同一 DB / 同一 fixture 才能歸因到「套件升級」而非「schema drift」。

---

## CLI entry point 偵測

讀 `pyproject.toml`：

```toml
[project.scripts]
mypkg = "mypkg.cli:main"
mypkg-admin = "mypkg.admin:cli"
```

或 `setup.cfg`：

```ini
[options.entry_points]
console_scripts =
    mypkg = mypkg.cli:main
```

對每個 entry point 跑：

```bash
timeout 60 <entry-point> --version
timeout 60 <entry-point> --help
```

若兩者皆 exit 0 → T1-cli 通過。
若任一 timeout 或 exit 非 0 → 抓 stderr 最後 30 行進報告。

---

## Scientific stack 最小 round-trip

只在依賴中真實出現對應套件時跑：

```python
# numpy round-trip
import numpy as np
a = np.arange(12).reshape(3, 4).astype(np.float64)
assert (a * 2 / 2 == a).all()
buf = a.tobytes()
b = np.frombuffer(buf, dtype=np.float64).reshape(3, 4)
assert (a == b).all()

# pandas round-trip (僅在 pandas 也升級時跑)
import pandas as pd
df = pd.DataFrame({"x": [1, 2, 3], "y": ["a", "b", "c"]})
df.to_csv("/tmp/_rt.csv", index=False)
df2 = pd.read_csv("/tmp/_rt.csv")
assert df.equals(df2)
```

歷史上 `numpy 1.x → 2.x` 大量 break 隱性 `dtype` 推導行為（如 `np.float_` 被移除）—
此 round-trip 雖簡單，已足以抓「import 過 + 簡單 op 過」的 baseline。

---

## Edge cases

- **Editable install / src-layout**：套件升級後若 `pip install -e .` 沒重跑，import 的是舊版。
  T1-import 必須印 `<pkg>.__version__` 並與 lockfile 期望版本比對。
- **Namespace packages**：`pkg.subpkg` 兩個 distribution 共用一個 namespace；單獨升級其一可能造成
  `pkg.subpkg` import 行為改變。T1-import 要對所有受影響的子套件各跑一次。
- **`.pth` / `usercustomize.py` 介入**：升級前後若有 site-packages 設定差異，runtime 可能拿到
  非預期版本。記錄 `python -c "import sys; print(sys.path)"` 進 baseline 報告。
- **C extension wheel mismatch**：CPython minor version 改變後舊 wheel 不能 load。
  T1-import 失敗時要區分「套件壞了」vs「環境 Python 版本變了」。
- **GIL-disabled CPython (3.13t+)**：愈來愈多 C extension 在 free-threaded build 上會直接拒絕載入。
  T1-import 報告中要記 `sys._is_gil_enabled() if hasattr(sys, '_is_gil_enabled') else 'n/a'`。

---

## 報告格式

Phase 7 報告的 `## Runtime Verification` 段落：

```markdown
## Runtime Verification

| Tier  | Cmd                                    | Baseline | Post-upgrade | Diff      |
|-------|----------------------------------------|----------|--------------|-----------|
| T1-import | `python -c "import requests; ..."` | OK 2.31.0 | OK 2.32.0  | version bumped, no traceback |
| T1-cli    | `req-cli --version`                | OK       | OK 2.32.0    | (CLI not in baseline) |
| T2-web    | `flask --app app run`              | ready 5s | ready 5s     | no new warning |
| T2-data   | (not applicable)                   | —        | —            | — |
```

「新出現」的 stderr / traceback 全文 dump 進報告附錄，以原始輸出形式，不要 paraphrase。

---

## 為什麼有這份文件

`runtime_verification_js.md` 已存在多時，Python track 一直缺對等覆蓋（TODO.md 任務 2.1）。
Python 場景更分歧（library / CLI / web / data），所以本文件比 JS 版多一層 tier 分類，
但執行精神一致：抓 baseline → 升級 → 重跑 → diff → 把新增錯誤歸因為本次升級。
