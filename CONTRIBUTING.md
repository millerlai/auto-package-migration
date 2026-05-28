# 貢獻指南

感謝你對 Package Upgrade Skill 的興趣。這份文件涵蓋兩種角色：
- **貢獻者**（修 bug、加功能、補測試）
- **開發者**（在本機跑、改、debug skill 本身）

修改前請先讀 `CLAUDE.md` — 那裡有 repo 層級的工作原則
（Think before coding / Simplicity first / Surgical changes / Goal-driven execution）。

---

## 🚀 設定開發環境

本專案使用 **UV** 管理 Python 依賴。

```bash
# 1. Fork + clone
git clone https://github.com/YOUR_USERNAME/auto-package-migration.git
cd auto-package-migration

# 2. 安裝 UV（任一）
curl -LsSf https://astral.sh/uv/install.sh | sh    # macOS / Linux
brew install uv                                     # macOS via brew
pip install uv                                      # 任何平台

# 3. 安裝 Python 依賴（uv sync 會建 .venv/、裝主依賴 + dev 依賴、editable 安裝本專案）
uv sync

# 4. 安裝 JS helper 依賴（要動 JS / TS 軌才需要）
cd package-upgrade/scripts/javascript && npm install && cd ../../..

# 5. 安裝 Go 工具（要動 Go 軌才需要）
go install golang.org/x/vuln/cmd/govulncheck@latest
go install golang.org/x/exp/cmd/apidiff@latest

# 6. 啟用 pre-commit hook（每次 commit 自動跑 ruff）
uv run pre-commit install

# 7. 驗證安裝
bash verify_installation.sh
```

---

## 📂 專案結構

```
auto-package-migration/
├── pyproject.toml             # UV 專案配置
├── uv.lock                    # UV 鎖定（commit）
├── .venv/                     # 虛擬環境（gitignored）
├── tests/                     # pytest UT suite
│
├── package-upgrade/           # ⭐ Skill 出貨單位
│   ├── SKILL.md
│   ├── README.md
│   ├── QUICK_REFERENCE.md
│   ├── LICENSE
│   ├── scripts/
│   │   ├── common/            # 跨語言：fetch_changelog / save_token / jira_* / parse_pm_errors / git_diff
│   │   ├── python/            # detect_env / dep_tree / ast_scanner / api_surface_diff / preflight / run_tests / snapshot_env / validate_lockfile / pip_audit
│   │   ├── javascript/        # 同上 + runtime_verify + package.json + node_modules
│   │   └── go/                # 同上 + govulncheck + validate_modfile
│   ├── references/
│   │   ├── common/            # auth_tokens / bdsa_mapping / jira_workflow / breaking_change_patterns / important_dependency_update
│   │   ├── python/
│   │   ├── javascript/
│   │   └── go/
│   └── templates/
│
├── package-upgrade-feedback/  # 第二個 skill（feedback 收集）
│
├── install.sh / install.bat / install-cygwin64.sh
├── verify_installation.sh / verify_installation.bat / verify_installation_cygwin64.sh
├── grant_permissions.py       # 寫入 Claude Code settings.json 的權限
├── CLAUDE.md                  # repo 層級的 Claude Code 指示
├── CHANGELOG.md
├── CONTRIBUTING.md            # 這份
├── README.md / README.zh-TW.md
└── docs/
    ├── installation.md
    └── project-status.md
```

設計要點：
- ✅ Python scripts 直接在 `package-upgrade/scripts/python/`，無 `src/` 中介層
- ✅ 無 symlinks（早期版本曾用，已移除）
- ✅ JS helpers 在 `scripts/javascript/` 有自己的 `package.json`；不會污染 Python 環境
- ✅ 三語言軌道是**平行的**（`scripts/python/dep_tree.py` / `scripts/javascript/dep_tree.js` / `scripts/go/dep_tree.sh`）
- ✅ 動一條時**不要**順手把另外兩條也改掉（除非需求真的要 cross-cut），詳見 `CLAUDE.md § Surgical changes`

---

## 🛠️ 開發工作流程

### 1. Branch

```bash
git checkout -b feature/your-feature-name
```

### 2. 修改

```bash
# Python helper
vim package-upgrade/scripts/python/dep_tree.py

# JS / TS helper
vim package-upgrade/scripts/javascript/dep_tree.js

# Go helper
vim package-upgrade/scripts/go/dep_tree.sh
```

### 3. 測試修改

```bash
# Python
uv run python package-upgrade/scripts/python/dep_tree.py . requests

# JS
node package-upgrade/scripts/javascript/dep_tree.js . axios

# Go
bash package-upgrade/scripts/go/dep_tree.sh . github.com/spf13/cobra
```

### 4. 格式化 + Lint + 測試

```bash
# 格式化
uv run black package-upgrade/scripts/python/*.py

# Lint
uv run ruff check .
uv run ruff check --fix .

# 全部 pre-commit hooks（含 ruff）
uv run pre-commit run --all-files

# 型別檢查
uv run mypy package-upgrade/scripts/python/*.py

# 單元測試
uv run pytest
uv run pytest tests/test_dep_tree.py                          # 單檔
uv run pytest --cov=package-upgrade --cov-report=html         # 含 coverage
```

CI（GitHub Actions）push / PR 時會跑 `ruff check .` + `pytest`。本機 pre-commit 過了，CI 才會過。

### 5. 同步更新 SKILL.md

helper script 的 CLI 與 JSON output schema 是 SKILL.md 對外的介面。**改 helper 必同步改 SKILL.md 對應 phase 的描述**，兩者不能漂。

### 6. 測試安裝流程

```bash
bash install.sh                # POSIX
# install.bat                  # Windows
# bash install-cygwin64.sh     # Cygwin64

bash verify_installation.sh
```

### 7. Commit

依 Conventional Commits 格式：

```bash
git add .
git commit -m "feat: add your feature description"

# 前綴:
#   feat:     新功能
#   fix:      修復
#   docs:     文件
#   refactor: 重構
#   test:     測試
#   chore:    雜項
```

### 8. Push + PR

```bash
git push origin feature/your-feature-name
gh pr create --title "feat: your feature" --body "Description"
```

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


def main() -> None:
    """Main entry point."""
    pass


if __name__ == "__main__":
    main()
```

- ✅ `#!/usr/bin/env python3` shebang
- ✅ Type hints（Python 3.10+ 相容）
- ✅ Errors → stderr (`file=sys.stderr`)；JSON → stdout
- ✅ 行長 ≤ 100 字元（black）
- ✅ ruff clean

### Bash Scripts

```bash
#!/usr/bin/env bash
# script_name.sh - Description
# Usage: bash script_name.sh <args>
# Output: Description

set -euo pipefail
```

- ✅ `#!/usr/bin/env bash` + `set -euo pipefail`
- ✅ Errors → stderr (`>&2`)
- ✅ JSON 處理用 `jq`

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
```

- ✅ `#!/usr/bin/env node` shebang
- ✅ 依賴宣告在 `package-upgrade/scripts/javascript/package.json`
- ✅ Errors → `process.stderr`；JSON → `process.stdout`

---

## 🎯 貢獻方向

### 優先級 High

- [ ] 支援 **bun**（pnpm 已支援）
- [ ] 支援 **conda** / **pipenv**
- [ ] 改進 breaking change 偵測準確度（Python / JS / Go 三軌都歡迎）
- [ ] 增加更多測試框架支援
  - Python: nose2 / tox
  - JS: mocha / playwright
  - Go: ginkgo

### 優先級 Medium

- [ ] 跨語言移植：**Ruby (bundler)** / **Rust (cargo)** / **Java (maven / gradle)** — `scripts/` 已分 per-language 子資料夾，加新語言只要新增子資料夾 + SKILL.md 對應 phase 分支
- [ ] 改進 CVE 風險評估邏輯（參考 Go govulncheck 的 reachability，做到 JS / Python）
- [ ] 改進三向診斷（SOURCE_CODE / TEST_CODE / BOTH / CONFIG）
- [ ] 整合更多 issue tracker：GitHub Issues / GitLab Issues / Linear

### 優先級 Low

- [ ] Web UI 介面
- [ ] VS Code 擴充套件整合

> ✅ Python (pip / poetry / uv)、JavaScript / TypeScript (npm / yarn 3 / pnpm)、
>    Go (modules) 已支援；不要重複貢獻。

---

## 🧪 測試

`tests/` 有 pytest UT suite，CI 會在 push / PR 時自動跑。

### 寫新測試

新增 helper script 時，請同步在 `tests/` 加對應測試。`tests/conftest.py` 已把
`scripts/common/` 與 `scripts/python/` 加進 `sys.path`，所以 Python 模組直接
`import` 就能用；`scripts/go/dep_tree.py` 跟 `scripts/python/dep_tree.py`
撞名，所以 Go 的版本要用 `importlib.util` 顯式 load（見 `tests/test_dep_tree_go.py`）。

---

## 📋 PR 檢查清單

提交 PR 前：

- [ ] 程式碼已格式化 (`uv run black .`)
- [ ] 通過 lint 檢查 (`uv run ruff check .`)
- [ ] 通過單元測試 (`uv run pytest`)
- [ ] 所有 scripts 有執行權限 (`chmod +x`)
- [ ] 所有 scripts 有正確的 shebang
- [ ] 已測試 `install.sh` 與 `verify_installation.sh`
- [ ] 若動到三平台 installer，已測試 `install.bat` / `install-cygwin64.sh`
- [ ] 更新相關文件（`README.md`、`CHANGELOG.md`、`SKILL.md`）
- [ ] PR 描述清楚說明變更內容
- [ ] 遵循 Conventional Commits 格式

---

## 💡 UV 速查（給 Python 軌貢獻者）

### 依賴管理

```bash
uv sync                 # 安裝所有依賴
uv sync --no-dev        # 只安裝主要依賴
uv add requests         # 新增主依賴
uv add --dev pytest     # 新增 dev 依賴
uv remove requests      # 移除
uv lock --upgrade-package requests  # 更新單一套件
uv sync                 # 套用 lockfile 變更
```

### 執行命令

```bash
uv run python script.py
uv run pytest
uv run black .
uv run ruff check .
```

### 環境管理

```bash
uv pip list             # 已安裝套件
uv pip show requests
uv pip tree             # 依賴樹

# 重建環境
rm -rf .venv && uv sync
```

### UV vs Poetry / Pip 速覽

| 操作 | pip | poetry | uv |
|------|-----|--------|-----|
| 安裝依賴 | `pip install -r req.txt` | `poetry install` | `uv sync` |
| 新增套件 | 編輯檔案 + `pip install` | `poetry add pkg` | `uv add pkg` |
| 更新套件 | 編輯檔案 + `pip install` | `poetry add pkg@ver` | `uv add pkg` |
| 移除套件 | 編輯檔案 + `pip uninstall` | `poetry remove pkg` | `uv remove pkg` |
| 執行腳本 | `python script.py` | `poetry run python script.py` | `uv run python script.py` |
| 速度 | 慢 | 中 | 極快（10–100×）|

---

## 💡 開發技巧

### 快速測試 scripts（一次性測試專案）

```bash
# Python
mkdir -p /tmp/test-pkg-py && cd /tmp/test-pkg-py
echo "requests==2.28.0" > requirements.txt
bash ~/path/to/package-upgrade/scripts/python/detect_env.sh .
uv run python ~/path/to/package-upgrade/scripts/python/dep_tree.py . requests

# JS
mkdir -p /tmp/test-pkg-js && cd /tmp/test-pkg-js
npm init -y && npm install axios@1.6.0
bash ~/path/to/package-upgrade/scripts/javascript/detect_env.sh .
node ~/path/to/package-upgrade/scripts/javascript/dep_tree.js . axios

# Go
mkdir -p /tmp/test-pkg-go && cd /tmp/test-pkg-go
go mod init example.com/test
go get github.com/spf13/cobra@v1.7.0
bash ~/path/to/package-upgrade/scripts/go/detect_env.sh .
bash ~/path/to/package-upgrade/scripts/go/dep_tree.sh . github.com/spf13/cobra
```

### 除錯技巧

```bash
# Python — debug 訊息到 stderr（不污染 JSON stdout）
import sys
print(f"DEBUG: {variable}", file=sys.stderr)

# Bash — trace
set -x

# JS — 寫到 stderr
process.stderr.write(`DEBUG: ${variable}\n`);

# Go
fmt.Fprintln(os.Stderr, "DEBUG:", variable)
```

---

## 🐛 故障排除（開發環境）

### `uv sync` 失敗

```bash
uv --version
uv check pyproject.toml
```

### 依賴衝突

```bash
uv sync --reinstall
```

### 虛擬環境損壞

```bash
rm -rf .venv && uv sync
```

### JS helper 缺 `node_modules`

```bash
cd package-upgrade/scripts/javascript && npm install
```

### pre-commit hook 沒跑

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

### ruff 在 CI 失敗但 local 通過

清 ruff 的 per-file cache，加 `--no-cache`：

```bash
uv run ruff check . --no-cache
```

（cache 在 reorg / rename 後容易跟新狀態漂掉。）

---

## 🐛 回報 Bug

建立 Issue 時請附：

1. **環境資訊**：OS、Python / Node.js / Go 版本、UV 版本、Claude Code 版本
2. **重現步驟**：完整命令、預期行為、實際行為
3. **相關日誌**：錯誤訊息、traceback、相關 JSON 輸出

---

## 📞 聯絡

- **Issues**: <https://github.com/millerlai/auto-package-migration/issues>
- **Discussions**: <https://github.com/millerlai/auto-package-migration/discussions>

---

## 🔗 相關資源

- [`CLAUDE.md`](./CLAUDE.md) — repo 工作原則
- [`docs/installation.md`](./docs/installation.md) — 安裝與驗證
- [`package-upgrade/SKILL.md`](./package-upgrade/SKILL.md) — Skill 完整工作流程
- [UV 官方文件](https://docs.astral.sh/uv/)
- [Python Packaging Guide](https://packaging.python.org/)
- [Node.js corepack](https://nodejs.org/api/corepack.html)
- [Go modules reference](https://go.dev/ref/mod)
