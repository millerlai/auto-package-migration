# Poetry 套件管理工作流程

## 升級套件

### 升級到指定版本

**重要**: Poetry 需要同時更新 `pyproject.toml` 和 `poetry.lock`

```bash
# 方法 1: 使用 poetry add (推薦 - 自動更新兩個檔案)
poetry add <package>@<version>

# 範例
poetry add requests@2.32.0

# 或指定版本約束
poetry add "requests>=2.32.0,<3.0"
```

**`poetry add` 會自動**:
1. 更新 `pyproject.toml` 中的版本約束
2. 解析所有依賴
3. 更新 `poetry.lock`
4. 安裝新版本套件

**方法 2: 手動編輯 + 更新鎖定**
```bash
# 1. 手動編輯 pyproject.toml
# 修改: requests = "^2.28.0" → requests = "^2.32.0"

# 2. 更新鎖定檔案並安裝
poetry lock
poetry install
```

### 升級到最新版本
```bash
poetry add <package>@latest

# 或更新到最新相容版本
poetry update <package>
```

**注意**: `poetry update` 只更新到 `pyproject.toml` 約束範圍內的最新版本,
如果要跨大版本升級,必須用 `poetry add`。

### 只更新鎖定檔案 (不安裝)
```bash
# 在手動修改 pyproject.toml 後,只更新鎖定檔案
poetry lock --no-update

# 更新所有依賴的鎖定
poetry lock
```

## 依賴檔案管理

### pyproject.toml

**主要依賴**
```toml
[tool.poetry.dependencies]
python = "^3.8"
requests = "^2.32.0"
```

**開發依賴**
```toml
[tool.poetry.group.dev.dependencies]
pytest = "^7.0"
black = "^23.0"
```

**可選依賴群組**
```toml
[tool.poetry.group.docs.dependencies]
sphinx = "^5.0"

[tool.poetry.group.docs]
optional = true
```

### poetry.lock

- **自動產生**: `poetry add/update` 時自動更新
- **不要手動編輯**: 由 Poetry 管理
- **版本控制**: 應該 commit 到 git

## 版本約束語法

| 語法 | 說明 | 範例 | pip 等價 |
|------|------|------|---------|
| `^` | Caret (相容版本) | `^2.32.0` → `>=2.32.0,<3.0.0` | `~=2.32` |
| `~` | Tilde (patch 升級) | `~2.32.0` → `>=2.32.0,<2.33.0` | `>=2.32,<2.33` |
| `*` | Wildcard | `2.32.*` → `>=2.32.0,<2.33.0` | `>=2.32,<2.33` |
| `==` | 精確版本 | `==2.32.0` | `==2.32.0` |
| `>=,<` | 範圍 | `>=2.30,<3.0` | `>=2.30,<3.0` |

**預設行為**: `poetry add requests` 使用 `^` 約束

## 依賴群組管理

### 安裝特定群組
```bash
# 只安裝主要依賴
poetry install --only main

# 安裝主要 + 開發依賴
poetry install

# 安裝特定群組
poetry install --with docs

# 不安裝特定群組
poetry install --without dev
```

## 衝突處理

### 查看依賴樹
```bash
poetry show --tree

# 查看特定套件的依賴
poetry show <package> --tree
```

### 更新衝突的依賴
```bash
# 同時更新多個套件
poetry update <package1> <package2>

# 更新所有依賴
poetry update
```

### 覆寫依賴約束 (Poetry 1.5+)
```toml
# pyproject.toml
[tool.poetry.dependencies]
requests = "^2.32.0"

# 強制特定子依賴版本
[tool.poetry.dependencies.overrides]
urllib3 = "^2.0"
```

## 檢查依賴

### 查看已安裝版本
```bash
poetry show <package>

# 查看所有套件
poetry show

# 只顯示過期套件
poetry show --outdated
```

### 檢查鎖定檔案
```bash
# 驗證 poetry.lock 與 pyproject.toml 一致
poetry check

# 驗證並更新 lock
poetry lock --check
```

## 虛擬環境

### Poetry 自動管理虛擬環境
```bash
# 安裝依賴 (自動建立 venv)
poetry install

# 在 venv 中執行命令
poetry run python script.py
poetry run pytest

# 啟用 shell
poetry shell

# 查看 venv 路徑
poetry env info --path

# 移除 venv
poetry env remove python3
```

### 使用專案內 venv
```bash
# 設定在專案目錄建立 .venv
poetry config virtualenvs.in-project true

# 之後 poetry install 會建立 .venv/
```

## 從 requirements.txt 遷移

### 匯入 requirements.txt
```bash
# 方法 1: 手動逐一加入
cat requirements.txt | xargs -n 1 poetry add

# 方法 2: 使用 poetry add (Poetry 1.2+)
poetry add $(cat requirements.txt)

# 方法 3: 使用工具
pip install poetry-plugin-export
poetry import requirements.txt
```

### 匯出到 requirements.txt
```bash
# 匯出主要依賴
poetry export -f requirements.txt --output requirements.txt

# 包含開發依賴
poetry export -f requirements.txt --with dev --output requirements-dev.txt

# 不包含 hash
poetry export -f requirements.txt --without-hashes --output requirements.txt
```

## 安全更新

### 檢查漏洞
```bash
# 使用 safety (需安裝)
poetry add --group dev safety
poetry run safety check

# 或使用 pip-audit
poetry run pip-audit
```

## 常見問題

### Q: poetry.lock 與 pyproject.toml 不一致
A: 執行 `poetry lock` 重新產生鎖定檔案

### Q: 升級後衝突
A: 
1. `poetry update <package>` 更新相依套件
2. 檢查 `poetry show --tree` 找出衝突來源
3. 考慮使用 dependency overrides

### Q: 想使用舊版 Python
A: 修改 `pyproject.toml` 中的 `python = "^3.x"`

### Q: venv 位置在哪裡?
A: `poetry env info --path` 或設定 `virtualenvs.in-project = true`

## 最佳實踐

1. **使用 Caret 約束**: `^2.32.0` 允許自動 patch 更新
2. **Commit lock 檔案**: 確保團隊環境一致
3. **分離依賴群組**: dev/test/docs 分開管理
4. **定期更新**: `poetry update` + `poetry show --outdated`
5. **CI/CD 使用**:
   ```bash
   poetry install --no-root --no-dev
   poetry run pytest
   ```

## Poetry vs pip 對照表

| 操作 | pip | Poetry |
|------|-----|--------|
| 安裝套件 | `pip install pkg` | `poetry add pkg` |
| 安裝特定版本 | `pip install pkg==1.0` | `poetry add pkg@1.0` |
| 更新套件 | `pip install -U pkg` | `poetry update pkg` |
| 移除套件 | `pip uninstall pkg` | `poetry remove pkg` |
| 列出套件 | `pip list` | `poetry show` |
| 凍結依賴 | `pip freeze` | `poetry export` |
| 安裝依賴檔 | `pip install -r req.txt` | `poetry install` |
