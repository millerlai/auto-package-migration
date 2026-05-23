# 貢獻指南

感謝你對 Package Upgrade Skill 的興趣！我們歡迎各種形式的貢獻。

## 🚀 快速開始

### 設定開發環境

```bash
# 1. Fork 並 Clone 專案
git clone https://github.com/YOUR_USERNAME/auto-package-migration.git
cd auto-package-migration

# 2. 安裝 UV (如果還沒安裝)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. 安裝依賴 (Python)
uv sync

# 4. 安裝 JS helper 依賴 (若要動到 JS / TS 軌)
cd package-upgrade/scripts && npm install && cd ../..

# 5. 啟用 pre-commit hook (每次 commit 自動跑 ruff)
uv run pre-commit install

# 6. 驗證安裝
bash verify_installation.sh
```

現在你的開發環境已就緒！🎉

> 📌 修改前請先讀 `CLAUDE.md` —— 上面有 repo 層級的工作原則 (Think before coding /
> Simplicity first / Surgical changes / Goal-driven execution)。

---

## 📂 專案結構

本專案**使用 UV 管理依賴**：

- `pyproject.toml` - 專案配置和依賴宣告
- `uv.lock` - 鎖定檔案 (應 commit)
- `.venv/` - 虛擬環境 (不 commit)
- `tests/` - pytest UT suite

### 主要目錄

- `package-upgrade/` - Claude Code Skill (發布單位)
  - `scripts/` - 三軌 helper scripts (Python / JS / Go) + JS 的 `package.json`
  - `references/` - 語言別參考文件
  - `templates/` - 報告模板
- `install.sh` / `install.bat` / `install-cygwin64.sh` - 各平台安裝腳本
- `*.md` - 文件
- `tests/` - pytest UT suite

---

## 🛠️ 開發工作流程

### 1. 建立 Feature Branch

```bash
git checkout -b feature/your-feature-name
```

### 2. 修改程式碼

```bash
# Python helper
vim package-upgrade/scripts/dep_tree.py

# JS / TS helper
vim package-upgrade/scripts/dep_tree_js.js

# Go helper
vim package-upgrade/scripts/dep_tree_go.sh
```

> 三語言軌道是平行的 (`*.py` / `*_js.js` / `*_go.sh`)。動其中一個時
> **不要**順手把其他軌道也改掉 —— 除非你的需求真的要 cross-cut。
> (參考 `CLAUDE.md` § Surgical changes)

### 3. 測試修改

```bash
# Python
uv run python package-upgrade/scripts/dep_tree.py . requests

# JS
node package-upgrade/scripts/dep_tree_js.js . axios

# Go
bash package-upgrade/scripts/dep_tree_go.sh . github.com/spf13/cobra
```

### 4. 格式化與檢查

```bash
# 格式化 (black)
uv run black package-upgrade/scripts/*.py

# Lint 檢查 (ruff)
uv run ruff check .
uv run ruff check --fix .

# 跑所有 pre-commit hooks (含 ruff)
uv run pre-commit run --all-files

# 跑單元測試
uv run pytest
```

> Pre-commit hook 已在環境設定步驟啟用，每次 `git commit` 會自動跑 ruff。
> CI 也會在 push / PR 時跑 `ruff check .` 與 `pytest`，所以 commit 前讓兩者通過很重要。

### 5. 同步更新 SKILL.md

helper script 的 CLI 與 JSON output schema 是 SKILL.md 對外的介面 ——
動 helper 時也要更新 SKILL.md 對應 phase 的描述，兩者必須保持同步。

### 6. 測試安裝流程

```bash
bash install.sh                # POSIX
# install.bat                  # Windows
# bash install-cygwin64.sh     # Cygwin64

bash verify_installation.sh
```

### 7. Commit 變更

```bash
git add .
git commit -m "feat: add your feature description"

# Commit message 格式 (Conventional Commits):
# - feat: 新功能
# - fix: 修復
# - docs: 文件
# - refactor: 重構
# - test: 測試
# - chore: 雜項
```

### 8. Push 並建立 PR

```bash
git push origin feature/your-feature-name

# 使用 gh CLI
gh pr create --title "feat: your feature" --body "Description of changes"
```

---

## 🎯 貢獻方向

### 優先級 High

- [ ] 支援 **pnpm** / **bun** (繼 npm / yarn 3 之後的下一個 stage)
- [ ] 支援 **conda** / **pipenv**
- [ ] 改進 breaking change 偵測準確度 (Python / JS / Go 三軌都歡迎)
- [ ] 增加更多測試框架支援
  - Python: nose2 / tox
  - JS: mocha / playwright
  - Go: ginkgo
- [ ] 增加 monorepo 結構支援 (Lerna / Nx / Turborepo / pnpm workspaces / go.work)

### 優先級 Medium

- [ ] 跨語言移植：**Ruby (bundler)** / **Rust (cargo)** / **Java (maven / gradle)**
- [ ] 改進 CVE 風險評估邏輯 (參考 Go govulncheck 的 reachability，做到 JS / Python)
- [ ] 改進三向診斷 (SOURCE_CODE / TEST_CODE / BOTH / CONFIG)
- [ ] 整合更多 issue tracker：GitHub Issues / GitLab Issues / Linear

### 優先級 Low

- [ ] Web UI 介面
- [ ] VS Code 擴充套件整合

> ✅ Python (pip / poetry / uv)、JavaScript / TypeScript (npm / yarn 3)、
>    Go (modules) 已支援；不要重複貢獻。

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
    pass


if __name__ == "__main__":
    main()
```

**規範**：
- ✅ 使用 `#!/usr/bin/env python3` shebang
- ✅ 包含 docstring 說明用法和輸出
- ✅ 使用 type hints (Python 3.8+)
- ✅ 錯誤處理要完善，errors 輸出到 stderr (`file=sys.stderr`)
- ✅ JSON 輸出到 stdout，結構化
- ✅ 行長度 ≤ 100 字元 (black 設定)
- ✅ ruff 必須 pass

### Bash Scripts

```bash
#!/usr/bin/env bash
# script_name.sh - Description
# Usage: bash script_name.sh <args>
# Output: Description

set -euo pipefail

# Implementation
```

**規範**：
- ✅ 使用 `#!/usr/bin/env bash` shebang
- ✅ 包含用法說明註解
- ✅ 使用 `set -euo pipefail` 嚴格模式
- ✅ 錯誤訊息輸出到 stderr (`>&2`)
- ✅ JSON 輸出使用 `jq` 處理

### JavaScript Scripts

```javascript
#!/usr/bin/env node
/**
 * script_name.js - Description
 * Usage: node script_name.js <args>
 * Output: Description (JSON to stdout)
 */

'use strict';

const fs = require('fs');
// ...
```

**規範**：
- ✅ 使用 `#!/usr/bin/env node` shebang
- ✅ 依賴宣告在 `package-upgrade/scripts/package.json`
- ✅ 錯誤訊息輸出到 `process.stderr`
- ✅ JSON 輸出到 `process.stdout`

### Markdown 文件

- ✅ 使用清楚的標題層級
- ✅ 程式碼區塊標註語言
- ✅ 使用表格組織資訊
- ✅ 加入範例和使用說明
- ✅ 繁體中文或英文皆可 (技術文件優先英文)

---

## 🧪 測試

本專案已有 **pytest UT suite**，並且 CI (GitHub Actions) 會在 push / PR 時自動跑。

### 執行測試

```bash
uv run pytest                                     # 所有測試
uv run pytest tests/test_dep_tree.py              # 單檔
uv run pytest --cov=package-upgrade --cov-report=html
```

### 寫新的測試

新增 helper script 時，請同步在 `tests/` 加入對應測試：

```
tests/
├── conftest.py                  # pytest fixture
├── test_dep_tree.py
├── test_ast_scanner.py
├── test_fetch_changelog.py
└── fixtures/                    # 測試用 sample 專案
    ├── sample_project_pip/
    ├── sample_project_poetry/
    ├── sample_project_uv/
    ├── sample_project_npm/
    └── sample_project_go/
```

---

## 📋 PR 檢查清單

提交 PR 前請確認：

- [ ] 程式碼已格式化 (`uv run black .`)
- [ ] 通過 lint 檢查 (`uv run ruff check .`)
- [ ] 通過單元測試 (`uv run pytest`)
- [ ] 所有 scripts 有執行權限 (`chmod +x`)
- [ ] 所有 scripts 有正確的 shebang
- [ ] 已測試 `install.sh` 和 `verify_installation.sh`
- [ ] 若動到三平台 installer，已測試 `install.bat` / `install-cygwin64.sh`
- [ ] 更新相關文件 (README、CHANGELOG、SKILL.md)
- [ ] PR 描述清楚說明變更內容
- [ ] 遵循 Conventional Commits 格式

---

## 💡 開發技巧

### 快速測試 Scripts

```bash
# Python
mkdir -p /tmp/test-pkg-py && cd /tmp/test-pkg-py
echo "requests==2.28.0" > requirements.txt
bash ~/path/to/package-upgrade/scripts/detect_env.sh .
uv run python ~/path/to/package-upgrade/scripts/dep_tree.py . requests

# JS
mkdir -p /tmp/test-pkg-js && cd /tmp/test-pkg-js
npm init -y && npm install axios@1.6.0
bash ~/path/to/package-upgrade/scripts/detect_env_js.sh .
node ~/path/to/package-upgrade/scripts/dep_tree_js.js . axios

# Go
mkdir -p /tmp/test-pkg-go && cd /tmp/test-pkg-go
go mod init example.com/test
go get github.com/spf13/cobra@v1.7.0
bash ~/path/to/package-upgrade/scripts/detect_env_go.sh .
bash ~/path/to/package-upgrade/scripts/dep_tree_go.sh . github.com/spf13/cobra
```

### 使用 UV 命令

```bash
uv add --dev pytest-mock
uv run python package-upgrade/scripts/ast_scanner.py . requests
uv pip tree
uv lock --upgrade
uv sync
```

### 除錯技巧

```bash
# Python — 輸出 debug 訊息到 stderr (不污染 JSON stdout)
import sys
print(f"DEBUG: {variable}", file=sys.stderr)

# Bash — 啟用 trace
set -x

# JS — 寫到 stderr
process.stderr.write(`DEBUG: ${variable}\n`);

# Go
fmt.Fprintln(os.Stderr, "DEBUG:", variable)
```

---

## 🐛 回報 Bug

### 建立 Issue 時請包含

1. **環境資訊**：
   - OS 版本
   - 語言 (Python / Node.js / Go) 版本
   - 對應的套件管理工具版本 (pip / poetry / uv / npm / yarn / go)
   - UV 版本
   - Claude Code 版本

2. **重現步驟**：
   - 完整的命令
   - 預期行為
   - 實際行為

3. **相關日誌**：
   - 錯誤訊息
   - Traceback
   - 相關的 JSON 輸出

### 範例 Issue

```markdown
**環境**：
- Windows 11 / macOS 14.0
- Python 3.11.4
- Node.js 20.10.0
- Go 1.21.5
- UV 0.5.0
- Claude Code 1.2.0

**問題描述**：
執行 `detect_env_js.sh` 時無法偵測到 yarn 3 (corepack-managed)

**重現步驟**：
1. cd /path/to/yarn3-project
2. bash detect_env_js.sh .
3. 輸出 `"pkg_manager": "unknown"`

**預期**：應該輸出 `"pkg_manager": "yarn"` 與 `pkg_manager_bin` 解析到 .yarn/releases/...

**實際輸出**：
```json
{"pkg_manager": "unknown", ...}
```
```

---

## 📞 聯絡方式

- **Issues**: <https://github.com/millerlai/auto-package-migration/issues>
- **Discussions**: <https://github.com/millerlai/auto-package-migration/discussions>

---

## 🙏 致謝

感謝所有貢獻者！你的貢獻讓這個專案更好。

特別感謝：
- Anthropic 的 Claude Code 團隊
- Python / Node.js / Go 社群
- 所有提供回饋和建議的使用者
