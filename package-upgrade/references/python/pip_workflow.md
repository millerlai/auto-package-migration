# Pip 套件管理工作流程

## 升級套件

**重要**: pip 不會自動更新 `requirements.txt` 或 `pyproject.toml`,
必須手動編輯依賴檔案!

### 升級到指定版本

**完整流程**:
```bash
# 1. 手動編輯 requirements.txt
# 修改: requests==2.28.0 → requests==2.32.0

# 2. 安裝新版本
pip install --upgrade <package>==<version>

# 範例
pip install --upgrade requests==2.32.0

# 或從 requirements.txt 安裝
pip install -r requirements.txt
```

**注意**: `pip install` 只會安裝套件到環境中,
**不會**自動修改 `requirements.txt` 或 `pyproject.toml`!

### 升級到最新版本
```bash
# 1. 手動編輯 requirements.txt (移除版本限制)
# 修改: requests==2.28.0 → requests

# 2. 安裝最新版本
pip install --upgrade <package>

# 範例
pip install --upgrade requests

# 3. 更新 requirements.txt 為新版本
# 修改: requests → requests==2.32.0
```

## 依賴檔案管理

### requirements.txt

**直接引用 - 必須手動更新版本**
```bash
# 1. 手動編輯 requirements.txt
# requests==2.28.0  →  requests==2.32.0

# 2. 安裝更新
pip install -r requirements.txt

# 或針對單一套件
pip install --upgrade requests==2.32.0
```

### Lock 檔案 (requirements.lock / requirements.txt.lock)

**檢測 lock 檔案**

一些專案會使用 lock 檔案來鎖定精確版本:
- `requirements.lock`
- `requirements.txt.lock`
- `requirements-lock.txt`
- `requirements.prod.lock`
- `requirements/production.lock`

**完整的更新流程 (如有 lock 檔案)**:

```bash
# 1. 手動編輯 requirements.txt (或 requirements.in)
# requests==2.28.0  →  requests==2.32.0

# 2. 重新產生 lock 檔案
pip-compile requirements.txt --output-file requirements.lock
# 或使用 pip freeze
pip install -r requirements.txt
pip freeze > requirements.lock

# 3. 從 lock 檔案安裝 (驗證)
pip install -r requirements.lock
```

**使用 pip-tools 的專案**:

```bash
# 安裝 pip-tools
pip install pip-tools

# 1. 編輯 requirements.in
# requests==2.28.0  →  requests==2.32.0

# 2. 重新編譯 lock 檔案
pip-compile requirements.in --output-file requirements.txt

# 或更新特定套件
pip-compile --upgrade-package requests requirements.in

# 3. 安裝
pip-sync requirements.txt
```

**常見 lock 檔案模式**:

| 模式 | 說明 |
|------|------|
| `requirements.in` + `requirements.txt` | pip-tools 模式: .in 是約束,.txt 是鎖定 |
| `requirements.txt` + `requirements.lock` | 雙檔案模式: .txt 是約束,.lock 是鎖定 |
| `requirements.txt` (只有一個) | 無 lock,直接使用精確版本 |

**如何判斷專案使用哪種模式**:

1. 檢查是否有 `requirements.in` → 使用 pip-tools
2. 檢查是否有 `*.lock` 檔案 → 使用 lock 模式
3. 都沒有 → 直接使用 requirements.txt

### setup.py / setup.cfg

**setup.py 中宣告依賴**
```python
setup(
    install_requires=[
        'requests>=2.32.0,<3.0',
    ],
)

# 安裝專案依賴
pip install -e .
```

**setup.cfg 中宣告依賴**
```ini
[options]
install_requires =
    requests>=2.32.0,<3.0
```

### pyproject.toml (PEP 621)

```toml
[project]
dependencies = [
    "requests>=2.32.0,<3.0",
]

# 安裝
pip install -e .
```

## 版本約束語法

| 語法 | 說明 | 範例 |
|------|------|------|
| `==` | 精確版本 | `requests==2.32.0` |
| `>=` | 大於等於 | `requests>=2.30.0` |
| `<=` | 小於等於 | `requests<=2.35.0` |
| `>` | 大於 | `requests>2.30.0` |
| `<` | 小於 | `requests<3.0` |
| `~=` | 相容版本 | `requests~=2.32` (≈ `>=2.32, <3.0`) |
| `,` | 組合約束 | `requests>=2.30,<3.0` |

## 衝突處理

### 使用 constraints.txt
```bash
# constraints.txt - 限制版本範圍但不強制安裝
requests>=2.32.0
urllib3>=2.0

# 安裝時套用約束
pip install -c constraints.txt -r requirements.txt
```

### 使用 --force-reinstall (謹慎使用)
```bash
# 強制重新安裝,忽略已安裝版本
pip install --force-reinstall <package>==<version>
```

## 檢查依賴

### 查看已安裝版本
```bash
pip show <package>

# 查看依賴樹
pip install pipdeptree
pipdeptree -p <package>
```

### 檢查相容性
```bash
# 檢查是否有衝突
pip check

# 列出過期套件
pip list --outdated
```

## 安全更新

### 使用 pip-audit 檢查漏洞
```bash
pip install pip-audit
pip-audit

# 自動修復
pip-audit --fix
```

## 虛擬環境

### 建立與啟用
```bash
# 建立虛擬環境
python3 -m venv .venv

# 啟用 (Unix/Mac)
source .venv/bin/activate

# 啟用 (Windows)
.venv\Scripts\activate

# 離開
deactivate
```

## 常見問題

### Q: 升級後其他套件壞掉了
A: 使用 `pip install <broken-package> --upgrade` 嘗試升級相依套件,或檢查版本約束

### Q: 無法升級因為版本衝突
A: 
1. 檢查 `pipdeptree` 找出哪個套件限制版本
2. 考慮同時升級衝突的 parent package
3. 使用虛擬環境測試升級

### Q: 想回退到舊版本
A: `pip install <package>==<old_version>`

## 最佳實踐

1. **使用虛擬環境**: 避免全域套件污染
2. **鎖定版本**: 生產環境使用精確版本 (`==`)
3. **定期更新**: 至少每季檢查安全更新
4. **測試升級**: 在測試環境先驗證升級
5. **記錄依賴**: 保持 requirements.txt 更新
