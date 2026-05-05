# ⚠️ 重要: 依賴檔案更新規則

## 關鍵問題

**錯誤做法**: 只更新鎖定檔案 (`.lock`),沒有更新依賴宣告檔案 (`pyproject.toml` / `requirements.txt`)

**正確做法**: 必須同時更新兩者!

> **例外: transitive (間接) dependency 的 lock-only 升級**
>
> 如果要升級的 pkg **不是** 專案直接引用、而是被某個 direct dep 拉進來的,
> 且所有 parent 對它的版本約束都允許目標版本, 此時 **只更新 lock 檔案** 是正確的做法,
> **不應該**把它加進 `pyproject.toml` / `requirements.txt`。
>
> 把 transitive pkg 加進宣告檔等同於「把間接依賴升級為直接依賴」,
> 這會擴大 API surface、增加未來維護負擔, 通常不是想要的結果。
>
> 詳細決策邏輯見 SKILL.md Phase 2.2 Type B (B-1 ~ B-4) 與 Phase 5.3 「Transitive: lock-only 路徑」。
> 以下章節描述的是 **direct dependency** 升級時兩個檔案要一起改的規則。

---

## 各套件管理工具的正確更新方式

### 📦 pip

**檔案**: 取決於專案配置

#### 情況 1: 使用 pip-tools

**檔案**: `requirements.in` (約束) + `requirements.txt` (lock)

```bash
# ❌ 錯誤: 只編輯 requirements.txt
vim requirements.txt  # 這是 lock 檔案!

# ✅ 正確: 編輯 .in 檔案,重新編譯
# 1. 編輯 requirements.in
#    requests==2.28.0 → requests==2.32.0
# 2. 重新編譯
pip-compile requirements.in
# 3. 安裝
pip-sync requirements.txt
```

#### 情況 2: 有自定義 lock 檔案

**檔案**: `requirements.txt` (約束) + `requirements.lock` / `*.lock` (lock)

```bash
# ❌ 錯誤: 只編輯 requirements.txt,不更新 lock
vim requirements.txt
pip install -r requirements.txt

# ✅ 正確: 同時更新兩者
# 1. 編輯 requirements.txt
#    requests==2.28.0 → requests==2.32.0
# 2. 重新產生 lock 檔案
pip install -r requirements.txt
pip freeze > requirements.lock
# 3. 驗證
pip install -r requirements.lock
```

**常見 lock 檔案名稱**:
- `requirements.lock`
- `requirements.txt.lock`
- `requirements-lock.txt`
- `requirements/production.lock`

#### 情況 3: 無 lock 檔案

**檔案**: `requirements.txt` (精確版本)

```bash
# ✅ 正確: 直接編輯 requirements.txt
# 1. 編輯 requirements.txt
#    requests==2.28.0 → requests==2.32.0
# 2. 安裝
pip install -r requirements.txt
```

**pip 不會自動更新任何檔案** - 你必須手動編輯!

**如何判斷使用哪種模式**:
1. 檢查是否有 `requirements.in` → pip-tools 模式
2. 檢查是否有 `*.lock` 檔案 → 自定義 lock 模式
3. 都沒有 → 無 lock 模式

---

### 📦 poetry

**檔案**: `pyproject.toml` + `poetry.lock`

```bash
# ❌ 錯誤: 只更新 lock,不會修改 pyproject.toml
poetry lock
poetry update requests

# ✅ 正確: 使用 poetry add
poetry add requests@2.32.0
```

**`poetry add` 會同時更新**:
1. ✅ `pyproject.toml` 中的 `[tool.poetry.dependencies]`
2. ✅ `poetry.lock`
3. ✅ 安裝到環境

**替代方案**:
```bash
# 1. 手動編輯 pyproject.toml
#    [tool.poetry.dependencies]
#    requests = "^2.28.0" → requests = "^2.32.0"

# 2. 更新鎖定檔案
poetry lock

# 3. 安裝
poetry install
```

---

### 📦 uv (專案模式)

**檔案**: `pyproject.toml` + `uv.lock`

```bash
# ❌ 錯誤: 只更新 lock,不會修改 pyproject.toml
uv lock --upgrade-package requests

# ✅ 正確: 使用 uv add
uv add "requests>=2.32.0"
# 或精確版本
uv add "requests==2.32.0"
```

**`uv add` 會同時更新**:
1. ✅ `pyproject.toml` 中的 `dependencies` 列表
2. ✅ `uv.lock`
3. ✅ 安裝到環境

**替代方案**:
```bash
# 1. 手動編輯 pyproject.toml
#    dependencies = [
#        "requests>=2.28.0" → "requests>=2.32.0"
#    ]

# 2. 更新鎖定檔案
uv lock

# 3. 同步安裝
uv sync
```

---

### 📦 uv (傳統 pip 模式)

**檔案**: `requirements.txt`

```bash
# ❌ 錯誤: 只安裝,不會寫入檔案
uv pip install requests==2.32.0

# ✅ 正確: 手動編輯 requirements.txt,然後安裝
# 1. 編輯 requirements.txt
#    requests==2.28.0 → requests==2.32.0
# 2. 安裝
uv pip install -r requirements.txt
```

---

## 對比表

| 工具 | 依賴宣告檔 | 鎖定檔案 | 自動更新兩者的命令 | 注意事項 |
|------|-----------|---------|-----------------|---------|
| **pip (pip-tools)** | requirements.in | requirements.txt | ⚠️ `pip-compile requirements.in` | 需編輯 .in 再編譯 |
| **pip (有 lock)** | requirements.txt | requirements.lock | ❌ 需手動編輯 + pip freeze | 需確認 lock 產生方式 |
| **pip (無 lock)** | requirements.txt | ❌ 無 | ❌ 需手動編輯 | pip 不自動寫入任何檔案 |
| **poetry** | pyproject.toml | poetry.lock | ✅ `poetry add pkg@ver` | `poetry update` 不會改 pyproject.toml |
| **uv (專案)** | pyproject.toml | uv.lock | ✅ `uv add "pkg>=ver"` | `uv lock --upgrade-package` 不會改 pyproject.toml |
| **uv (pip)** | requirements.txt | ❌ 無 | ❌ 需手動編輯 | 同 pip 行為 |

---

## 為什麼這很重要?

### 問題場景

```bash
# 開發者 A 升級 requests
poetry update requests  # ❌ 只更新 poetry.lock

# 提交到 git
git add poetry.lock
git commit -m "upgrade requests"
```

**結果**:
- ✅ `poetry.lock` 有新版本 (2.32.0)
- ❌ `pyproject.toml` 還是舊約束 (^2.28.0)

**問題**:
1. 開發者 B clone 專案,執行 `poetry install`
   → 會安裝 2.28.x (因為 pyproject.toml 約束)
2. CI/CD 重新 lock
   → 可能回退到 2.28.x
3. 版本不一致,難以追蹤真實依賴

### 正確場景

```bash
# 開發者 A 升級 requests
poetry add requests@2.32.0  # ✅ 同時更新兩個檔案

# 提交到 git
git add pyproject.toml poetry.lock
git commit -m "upgrade requests to 2.32.0"
```

**結果**:
- ✅ `pyproject.toml` 有新約束 (^2.32.0 或 ==2.32.0)
- ✅ `poetry.lock` 有新版本 (2.32.0)

**好處**:
1. 開發者 B 執行 `poetry install` → 安裝正確版本
2. CI/CD 執行 `poetry install` → 使用 lock 檔案
3. 版本一致,可重現

---

## 在 Claude Code Skill 中的實作

在 `SKILL.md` 的 **Phase 5.3: 更新依賴宣告檔** 中:

### For pip:
```bash
# 1. 使用 Edit tool 修改 requirements.txt
# 2. 執行 pip install -r requirements.txt
```

### For poetry:
```bash
# 直接執行
poetry add <package>@<version>
```

### For uv (專案模式):
```bash
# 直接執行
uv add "<package>>=<version>"
```

**關鍵**: 不要只執行 `poetry lock` 或 `uv lock`!

---

## 驗證是否正確更新

升級後,檢查以下檔案:

### pip:
```bash
# 檢查 requirements.txt
grep "requests" requirements.txt
# 應該顯示: requests==2.32.0
```

### poetry:
```bash
# 檢查 pyproject.toml
grep "requests" pyproject.toml
# 應該顯示: requests = "^2.32.0" 或 "2.32.0"

# 檢查 poetry.lock
grep -A 5 '^\[\[package\]\]' poetry.lock | grep -A 5 'name = "requests"'
# 應該顯示: version = "2.32.0"
```

### uv:
```bash
# 檢查 pyproject.toml
grep "requests" pyproject.toml
# 應該顯示在 dependencies 列表中: "requests>=2.32.0"

# 檢查 uv.lock
grep "requests" uv.lock
# 應該有對應的版本資訊
```

---

## 總結

| ❌ 不要這樣做 | ✅ 應該這樣做 |
|-------------|-------------|
| 只執行 `poetry lock` | 執行 `poetry add pkg@ver` |
| 只執行 `poetry update pkg` | 執行 `poetry add pkg@ver` |
| 只執行 `uv lock --upgrade-package pkg` | 執行 `uv add "pkg>=ver"` |
| 只執行 `pip install --upgrade pkg` | 先編輯檔案,再 `pip install` |

**記住**: 
- **pip 不自動寫檔案** → 必須手動編輯
- **poetry/uv 用 `add` 命令** → 同時更新兩個檔案
- **檢查兩個檔案** → 確保版本一致
