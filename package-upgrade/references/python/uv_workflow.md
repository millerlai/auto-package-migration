# UV 套件管理工作流程

> UV 是新一代極速 Python 套件管理工具,由 Rust 編寫,相容 pip 但速度快 10-100 倍

## 升級套件

### UV 專案模式 (有 pyproject.toml + uv.lock)

**重要**: UV 專案模式需要同時更新 `pyproject.toml` 和 `uv.lock`

```bash
# 方法 1: 使用 uv add (推薦 - 自動更新兩個檔案)
uv add "requests>=2.32.0"

# 升級到精確版本
uv add "requests==2.32.0"

# 範例
uv add "requests>=2.32.0,<3.0"
```

**`uv add` 會自動**:
1. 更新 `pyproject.toml` 中的 dependencies 列表
2. 解析所有依賴
3. 更新 `uv.lock`
4. 安裝新版本套件

**方法 2: 手動編輯 + 更新鎖定**
```bash
# 1. 手動編輯 pyproject.toml
# 修改 dependencies 列表:
# "requests>=2.28.0" → "requests>=2.32.0"

# 2. 更新鎖定檔案
uv lock

# 3. 同步安裝
uv sync
```

**方法 3: 只升級鎖定檔案中的版本 (不改 pyproject.toml)**
```bash
# 升級 requests 到約束範圍內的最新版本
uv lock --upgrade-package requests

# 然後同步安裝
uv sync
```

**注意**: `uv lock --upgrade-package` 不會修改 `pyproject.toml`,
只會更新 `uv.lock` 中的解析版本。如果要跨版本升級,必須用 `uv add`。

### 傳統 pip 模式 (只有 requirements.txt)

```bash
# 升級到指定版本
uv pip install <package>==<version>

# 範例
uv pip install requests==2.32.0

# 升級到最新版本
uv pip install --upgrade <package>

# 批次升級
uv pip install --upgrade -r requirements.txt
```

## 依賴檔案管理

### requirements.txt (傳統模式)

```bash
# 從 requirements.txt 安裝
uv pip install -r requirements.txt

# 產生鎖定檔案
uv pip freeze > requirements.lock.txt

# 編譯 requirements (解析依賴)
uv pip compile requirements.in -o requirements.txt
```

### pyproject.toml + uv.lock (推薦)

**pyproject.toml**
```toml
[project]
name = "myproject"
version = "0.1.0"
requires-python = ">=3.8"
dependencies = [
    "requests>=2.32.0",
]

[tool.uv]
dev-dependencies = [
    "pytest>=7.0",
]
```

**使用 uv 專案命令**
```bash
# 初始化專案
uv init

# 新增依賴 (自動更新 pyproject.toml 和 uv.lock)
uv add requests

# 新增開發依賴
uv add --dev pytest

# 安裝所有依賴
uv sync

# 更新鎖定檔案
uv lock

# 更新特定套件
uv lock --upgrade-package requests
```

## 版本約束語法

| 語法 | 說明 | 範例 |
|------|------|------|
| `==` | 精確版本 | `requests==2.32.0` |
| `>=` | 大於等於 | `requests>=2.30.0` |
| `<` | 小於 | `requests<3.0` |
| `>=,<` | 範圍 | `requests>=2.30,<3.0` |
| `~=` | 相容版本 | `requests~=2.32.0` |

## UV 專案模式 (推薦)

### 初始化專案
```bash
# 建立新專案
uv init myproject
cd myproject

# 或在現有專案初始化
uv init
```

### 管理依賴
```bash
# 新增套件
uv add requests

# 新增特定版本
uv add "requests>=2.32.0,<3.0"

# 新增開發依賴
uv add --dev pytest black ruff

# 移除套件
uv remove requests

# 同步環境 (安裝 pyproject.toml 中的所有依賴)
uv sync

# 只安裝主要依賴
uv sync --no-dev
```

### 更新依賴
```bash
# 更新所有依賴
uv lock --upgrade

# 更新特定套件
uv lock --upgrade-package requests

# 更新多個套件
uv lock --upgrade-package requests --upgrade-package urllib3
```

## 虛擬環境

### 自動管理 (推薦)
```bash
# uv sync 自動建立 .venv
uv sync

# 執行命令 (自動使用 venv)
uv run python script.py
uv run pytest

# 啟用 shell
source .venv/bin/activate  # Unix/Mac
.venv\Scripts\activate     # Windows
```

### 手動管理
```bash
# 建立虛擬環境
uv venv

# 使用特定 Python 版本
uv venv --python 3.11

# 指定路徑
uv venv .venv
```

## pip 相容命令

UV 完全相容 pip 命令,可直接替換:

```bash
# pip → uv pip
pip install requests      → uv pip install requests
pip install -r req.txt    → uv pip install -r req.txt
pip freeze                → uv pip freeze
pip list                  → uv pip list
pip show requests         → uv pip show requests
pip uninstall requests    → uv pip uninstall requests
```

## 速度優化特性

### 全域快取
```bash
# UV 自動使用全域快取,相同套件只下載一次
# 快取位置: ~/.cache/uv (Linux/Mac) 或 %LOCALAPPDATA%\uv\cache (Windows)

# 查看快取
uv cache dir

# 清理快取
uv cache clean
```

### 平行下載
```bash
# UV 自動平行下載多個套件,無需額外設定
```

## 從其他工具遷移

### 從 pip 遷移
```bash
# 方法 1: 直接使用現有 requirements.txt
uv pip install -r requirements.txt

# 方法 2: 轉換為 uv 專案
uv init
# 手動將 requirements.txt 內容加到 pyproject.toml
uv sync
```

### 從 poetry 遷移
```bash
# Poetry 的 pyproject.toml 可以直接使用
# 但需要將 [tool.poetry] 轉為 [project]

# 範例轉換:
# [tool.poetry.dependencies]  →  [project.dependencies]
# [tool.poetry.dev-dependencies]  →  [tool.uv.dev-dependencies]

uv sync
```

## 衝突處理

### 查看依賴樹
```bash
uv pip tree

# 查看特定套件
uv pip show requests
```

### 解決衝突
```bash
# 方法 1: 同時更新衝突套件
uv lock --upgrade-package package1 --upgrade-package package2

# 方法 2: 使用約束檔案
uv pip install -r requirements.txt -c constraints.txt

# 方法 3: 強制特定版本 (在 pyproject.toml)
[project]
dependencies = [
    "requests>=2.32.0",
]

[tool.uv.override-dependencies]
urllib3 = "==2.0.0"
```

## Python 版本管理

### UV 可管理 Python 版本
```bash
# 列出可用 Python 版本
uv python list

# 安裝特定 Python 版本
uv python install 3.11

# 使用特定版本建立 venv
uv venv --python 3.11
```

## 安全更新

### 檢查漏洞
```bash
# 使用 pip-audit (需安裝)
uv pip install pip-audit
uv run pip-audit

# 或使用 safety
uv pip install safety
uv run safety check
```

## 常見問題

### Q: UV 與 pip 有什麼差異?
A: UV 完全相容 pip,但速度快 10-100 倍,且有更好的依賴解析

### Q: uv.lock 要 commit 嗎?
A: 是的,類似 poetry.lock,確保環境一致性

### Q: 可以只用 UV 不改 pyproject.toml 嗎?
A: 可以,使用 `uv pip` 命令完全相容 pip 工作流

### Q: UV 支援 editable install 嗎?
A: 支援,使用 `uv pip install -e .`

## 最佳實踐

1. **使用專案模式**: `uv init` + `uv add` 自動管理依賴
2. **Commit uv.lock**: 確保團隊環境一致
3. **利用快取**: UV 自動共享全域快取,加速安裝
4. **版本約束**: 使用 `>=,<` 範圍約束避免過於寬鬆
5. **CI/CD 優化**:
   ```bash
   # 使用 UV 快取加速 CI
   uv sync --no-dev
   uv run pytest
   ```

## UV vs pip vs Poetry

| 特性 | pip | Poetry | UV |
|------|-----|--------|-----|
| 安裝速度 | 慢 | 中等 | 極快 (10-100x) |
| 依賴解析 | 基礎 | 優秀 | 優秀 |
| 鎖定檔案 | 手動 | 自動 | 自動 |
| 虛擬環境 | 手動 | 自動 | 自動 |
| Python 管理 | ❌ | ❌ | ✅ |
| pip 相容 | - | ❌ | ✅ |
| 學習曲線 | 低 | 中 | 低 |

## 推薦場景

- **新專案**: 直接使用 UV 專案模式 (`uv init`)
- **現有 pip 專案**: 用 `uv pip` 替換 `pip` 命令
- **現有 Poetry 專案**: 轉換 pyproject.toml 格式後使用 UV
- **CI/CD**: UV 的速度優勢在 CI 中最明顯

## 參考資源

- 官方文件: https://docs.astral.sh/uv/
- GitHub: https://github.com/astral-sh/uv
