# 貢獻指南

感謝你對 Package Upgrade Skill 的興趣! 我們歡迎各種形式的貢獻。

## 🚀 快速開始

### 設定開發環境

```bash
# 1. Fork 並 Clone 專案
git clone https://github.com/YOUR_USERNAME/package-upgrade-skill.git
cd package-upgrade-skill

# 2. 安裝 UV (如果還沒安裝)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. 安裝依賴
uv sync

# 4. 啟用 pre-commit hooks (每次 commit 自動跑 ruff)
uv run pre-commit install

# 5. 驗證安裝
bash verify_installation.sh
```

現在你的開發環境已就緒! 🎉

---

## 📂 專案結構

本專案**使用 UV 管理依賴**:

- `pyproject.toml` - 專案配置和依賴宣告
- `uv.lock` - 鎖定檔案 (應 commit)
- `.venv/` - 虛擬環境 (不 commit)

### 主要目錄

- `package-upgrade/` - Claude Code Skill (發布單位)
  - `scripts/` - 所有 helper scripts (.sh 和 .py)
  - `references/` - 參考文件
  - `templates/` - 報告模板
- `*.md` - 文件
- `*.sh` - 工具腳本

---

## 🛠️ 開發工作流程

### 1. 建立 Feature Branch

```bash
git checkout -b feature/your-feature-name
```

### 2. 修改程式碼

編輯 `package-upgrade/scripts/` 中的檔案:

```bash
# 使用你喜歡的編輯器
vim package-upgrade/scripts/dep_tree.py
```

### 3. 測試修改

```bash
# 執行 script 測試
uv run python package-upgrade/scripts/dep_tree.py . requests

# 或啟用虛擬環境
source .venv/bin/activate
python package-upgrade/scripts/dep_tree.py . requests
```

### 4. 格式化與檢查

```bash
# 格式化 (black)
uv run black package-upgrade/scripts/*.py

# Lint 檢查 (ruff)
uv run ruff check .

# 自動修復
uv run ruff check --fix .

# 手動跑所有 pre-commit hooks (含 ruff)
uv run pre-commit run --all-files
```

> Pre-commit hook 已在環境設定步驟啟用，每次 `git commit` 會自動跑 ruff。
> CI 也會在 push / PR 時跑 `ruff check .`，所以 commit 前讓 ruff 通過很重要。

### 5. 測試安裝流程

```bash
# 測試安裝腳本
bash install.sh

# 驗證安裝
bash verify_installation.sh
```

### 6. Commit 變更

```bash
git add .
git commit -m "feat: add your feature description"

# Commit message 格式:
# - feat: 新功能
# - fix: 修復
# - docs: 文件
# - refactor: 重構
# - test: 測試
# - chore: 雜項
```

### 7. Push 並建立 PR

```bash
git push origin feature/your-feature-name

# 使用 gh CLI
gh pr create --title "feat: your feature" --body "Description of changes"
```

---

## 🎯 貢獻方向

### 優先級 High

- [ ] 支援 conda 套件管理工具
- [ ] 支援 pipenv
- [ ] 增加單元測試 (tests/)
- [ ] 改進 breaking change 偵測準確度
- [ ] 支援更多測試框架 (nose2, tox)

### 優先級 Medium

- [ ] 支援 Node.js (npm/yarn/pnpm)
- [ ] 支援 Ruby (bundler)
- [ ] 改進 CVE 風險評估邏輯
- [ ] 支援 monorepo 結構
- [ ] 增加 CI/CD 範例

### 優先級 Low

- [ ] 支援 Go (go modules)
- [ ] 支援 Rust (cargo)
- [ ] Web UI 介面
- [ ] VS Code 擴充套件整合

---

## 📝 程式碼規範

### Python Scripts

```python
#!/usr/bin/env python3
"""Module docstring.

Usage: python script.py <args>
Output: Description of output
"""

import json
import sys
from typing import Dict, List

def main():
    """Main entry point."""
    # Implementation
    pass

if __name__ == "__main__":
    main()
```

**規範**:
- ✅ 使用 `#!/usr/bin/env python3` shebang
- ✅ 包含 docstring 說明用法和輸出
- ✅ 使用 type hints (Python 3.8+)
- ✅ 錯誤處理要完善
- ✅ JSON 輸出要結構化
- ✅ 行長度 ≤ 100 字元 (black 設定)

### Bash Scripts

```bash
#!/usr/bin/env bash
# script_name.sh - Description
# Usage: bash script_name.sh <args>
# Output: Description

set -euo pipefail

# Implementation
```

**規範**:
- ✅ 使用 `#!/usr/bin/env bash` shebang
- ✅ 包含用法說明註解
- ✅ 使用 `set -euo pipefail` 嚴格模式
- ✅ 錯誤訊息輸出到 stderr (`>&2`)
- ✅ JSON 輸出使用 `jq` 處理

### Markdown 文件

**規範**:
- ✅ 使用清楚的標題層級
- ✅ 程式碼區塊標註語言
- ✅ 使用表格組織資訊
- ✅ 加入範例和使用說明
- ✅ 繁體中文或英文 (技術文件優先英文)

---

## 🧪 測試

### 目前狀態

⚠️ 本專案目前沒有自動化測試,這是優先貢獻項目!

### 測試結構 (待建立)

```
tests/
├── test_dep_tree.py
├── test_ast_scanner.py
├── test_fetch_changelog.py
├── test_detect_env.sh
└── fixtures/
    ├── sample_project_pip/
    ├── sample_project_poetry/
    └── sample_project_uv/
```

### 執行測試

```bash
# 執行所有測試
uv run pytest

# 執行特定測試
uv run pytest tests/test_dep_tree.py

# 顯示覆蓋率
uv run pytest --cov=package-upgrade --cov-report=html
```

---

## 📋 PR 檢查清單

提交 PR 前請確認:

- [ ] 程式碼已格式化 (`uv run black .`)
- [ ] 通過 lint 檢查 (`uv run ruff check .`)
- [ ] 所有 scripts 有執行權限 (`chmod +x`)
- [ ] 所有 scripts 有正確的 shebang
- [ ] 已測試 install.sh 和 verify_installation.sh
- [ ] 更新相關文件 (README, CHANGELOG)
- [ ] PR 描述清楚說明變更內容
- [ ] 遵循 Conventional Commits 格式

---

## 💡 開發技巧

### 快速測試 Scripts

```bash
# 建立測試專案
mkdir -p /tmp/test-pkg
cd /tmp/test-pkg
echo "requests==2.28.0" > requirements.txt

# 測試 detect_env.sh
bash ~/path/to/package-upgrade/scripts/detect_env.sh .

# 測試 dep_tree.py
uv run python ~/path/to/package-upgrade/scripts/dep_tree.py . requests
```

### 使用 UV 命令

```bash
# 新增開發依賴
uv add --dev pytest-mock

# 執行 Python 腳本
uv run python package-upgrade/scripts/ast_scanner.py . requests

# 查看依賴樹
uv pip tree

# 更新所有依賴
uv lock --upgrade
uv sync
```

### 除錯技巧

```bash
# 在 Python scripts 中加入除錯輸出
import sys
print(f"DEBUG: {variable}", file=sys.stderr)

# 在 Bash scripts 中啟用除錯
set -x  # 顯示執行的命令
```

---

## 🐛 回報 Bug

### 建立 Issue 時請包含

1. **環境資訊**:
   - OS 版本
   - Python 版本
   - UV 版本
   - Claude Code 版本

2. **重現步驟**:
   - 完整的命令
   - 預期行為
   - 實際行為

3. **相關日誌**:
   - 錯誤訊息
   - Traceback
   - 相關的 JSON 輸出

### 範例 Issue

```markdown
**環境**:
- macOS 14.0
- Python 3.11.4
- UV 0.5.0
- Claude Code 1.2.0

**問題描述**:
執行 `detect_env.sh` 時無法檢測到 poetry

**重現步驟**:
1. cd /path/to/poetry-project
2. bash detect_env.sh .
3. 輸出 `"pkg_manager": "unknown"`

**預期**: 應該輸出 `"pkg_manager": "poetry"`

**實際輸出**:
```json
{"pkg_manager": "unknown", ...}
```
```

---

## 📞 聯絡方式

- **Issues**: https://github.com/YOUR_USERNAME/package-upgrade-skill/issues
- **Discussions**: https://github.com/YOUR_USERNAME/package-upgrade-skill/discussions

---

## 🙏 致謝

感謝所有貢獻者! 你的貢獻讓這個專案更好。

主要貢獻者:
- (待補充)

特別感謝:
- Anthropic 的 Claude Code 團隊
- Python 社群
- 所有提供回饋和建議的使用者
