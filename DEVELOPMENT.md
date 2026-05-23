# 開發指南

本專案 (`auto-package-migration`) 是一個 Claude Code Skill 的 source repo —
出貨單位是 `package-upgrade/` 目錄。Repo 本身用 **UV** 管理開發環境，
helper scripts 分成 Python / JavaScript / Go 三軌。

> 📌 想了解 repo 的整體規範與「工作原則」，請先讀 `CLAUDE.md`。

---

## 專案套件管理

本專案使用 **UV** 作為套件管理工具。

### 安裝 UV

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# 或使用 brew (macOS)
brew install uv

# 或使用 pip
pip install uv
```

---

## 開發環境設定

### 初始設定

```bash
# Clone 專案
git clone https://github.com/millerlai/auto-package-migration.git
cd auto-package-migration

# 用 uv 安裝所有依賴 (包含 dev 依賴)
uv sync

# (可選) 啟用 pre-commit hook，每次 commit 自動跑 ruff
uv run pre-commit install

# (可選) 啟用虛擬環境
source .venv/bin/activate
```

**`uv sync` 會自動**：
1. ✅ 建立虛擬環境 (`.venv/`)
2. ✅ 安裝主要依賴 (requests)
3. ✅ 安裝開發依賴 (pipdeptree、pytest、black、ruff、mypy、pre-commit)
4. ✅ 以 editable 模式安裝本專案

### JS helper 開發環境

JS helpers 在 `package-upgrade/scripts/` 有自己的 `package.json`：

```bash
cd package-upgrade/scripts
npm install
cd ../..
```

`scripts/node_modules/` 已在 `.gitignore`。

### Go helper 開發環境

```bash
# Go ≥ 1.21
go install golang.org/x/vuln/cmd/govulncheck@latest
go install golang.org/x/exp/cmd/apidiff@latest
```

`ast_scanner_go.go` 是獨立檔案，由 SKILL.md Phase 4 透過 `go run` 直接執行；
不需要建 Go module。

---

## 依賴管理

### 新增 Python 依賴

```bash
uv add <package>            # 主要依賴
uv add --dev <package>      # 開發依賴
```

### 更新

```bash
uv lock --upgrade                   # 更新所有
uv lock --upgrade-package requests  # 更新特定套件
uv sync                             # 同步安裝
```

### 移除

```bash
uv remove <package>
```

### JS helper 依賴

```bash
cd package-upgrade/scripts
npm install <pkg>
npm update
```

---

## 執行 Scripts

### 使用 uv run (推薦)

```bash
# Python
uv run python package-upgrade/scripts/dep_tree.py . requests
uv run python package-upgrade/scripts/ast_scanner.py . requests
uv run python package-upgrade/scripts/fetch_changelog.py requests https://github.com/psf/requests

# JS / TS
node package-upgrade/scripts/dep_tree_js.js . axios
node package-upgrade/scripts/ast_scanner_js.js . axios

# Go
bash package-upgrade/scripts/detect_env_go.sh .
bash package-upgrade/scripts/dep_tree_go.sh . github.com/spf13/cobra
go run package-upgrade/scripts/ast_scanner_go.go . github.com/spf13/cobra
```

### 或啟用虛擬環境

```bash
source .venv/bin/activate
python package-upgrade/scripts/dep_tree.py . requests
deactivate
```

---

## 測試

```bash
uv run pytest                                     # 跑全部
uv run pytest tests/test_dep_tree.py              # 跑單檔
uv run pytest --cov=package-upgrade --cov-report=html
```

CI (GitHub Actions) 會在 push / PR 時自動跑 pytest 與 `ruff check .`。

---

## 程式碼品質

### 格式化

```bash
uv run black package-upgrade/scripts/*.py
uv run black --check package-upgrade/scripts/*.py
```

### Linting

```bash
uv run ruff check .
uv run ruff check --fix .
uv run pre-commit run --all-files     # 跑所有 pre-commit hooks (含 ruff)
```

> Pre-commit hook 已在初始設定步驟啟用，每次 `git commit` 會自動跑 ruff。
> CI 也會在 push / PR 時跑 `ruff check .`，commit 前讓 ruff 通過很重要。

### 型別檢查

```bash
uv run mypy package-upgrade/scripts/*.py
```

---

## 修改 Scripts

### 工作流程

1. **修改 scripts**
   ```bash
   vim package-upgrade/scripts/dep_tree.py
   # 或對應的 *_js.js / *_go.sh
   ```

2. **測試修改**
   ```bash
   uv run python package-upgrade/scripts/dep_tree.py . requests
   ```

3. **格式化與檢查**
   ```bash
   uv run black package-upgrade/scripts/dep_tree.py
   uv run ruff check package-upgrade/scripts/dep_tree.py
   ```

4. **同步更新 SKILL.md**
   helper script 的 CLI 與 JSON output schema 都是 SKILL.md 在使用 ——
   改動 helper 時同步更新 SKILL.md 中對應 phase 的描述 (參考 `CLAUDE.md` § Working principles)。

5. **提交變更**
   ```bash
   git add package-upgrade/scripts/dep_tree.py package-upgrade/SKILL.md
   git commit -m "feat: improve dep_tree.py error handling"
   ```

---

## 安裝測試

```bash
# 執行安裝腳本
bash install.sh             # macOS / Linux
# install.bat               # Windows
# bash install-cygwin64.sh  # Cygwin64

# 驗證安裝
bash verify_installation.sh

# 測試 Skill (建立測試專案 — 詳見 INSTALLATION_GUIDE.md 進階驗證一節)
mkdir -p /tmp/test-skill && cd /tmp/test-skill
python3 -m venv .venv && source .venv/bin/activate
pip install requests==2.28.0
echo "requests==2.28.0" > requirements.txt
claude "檢查 requests 能不能升級到 2.32.0"
```

---

## 發布準備

### 檢查清單

- [ ] 所有 scripts 都有執行權限
  ```bash
  chmod +x package-upgrade/scripts/*.sh
  chmod +x package-upgrade/scripts/*.py
  ```

- [ ] 所有 scripts 都有正確的 shebang
  ```bash
  head -1 package-upgrade/scripts/*.py    # #!/usr/bin/env python3
  head -1 package-upgrade/scripts/*.sh    # #!/usr/bin/env bash
  ```

- [ ] 更新版本號與 `CHANGELOG.md`
- [ ] 執行完整驗證
  ```bash
  bash verify_installation.sh
  uv run pytest
  uv run ruff check .
  ```

- [ ] 測試三平台安裝腳本 (`install.sh` / `install.bat` / `install-cygwin64.sh`)

---

## 專案結構

```
auto-package-migration/
├── pyproject.toml             # UV 專案配置 ⭐
├── uv.lock                    # UV 鎖定檔案 ⭐
├── .venv/                     # 虛擬環境 (不 commit)
├── tests/                     # pytest UT suite
│
├── package-upgrade/           # ⭐ Skill 目錄 (發布單位)
│   ├── SKILL.md
│   ├── README.md
│   ├── QUICK_REFERENCE.md
│   ├── LICENSE
│   ├── scripts/               # 三軌 helper：Python / JS / Go
│   │   ├── detect_env.sh / detect_env_js.sh / detect_env_go.sh
│   │   ├── dep_tree.py / dep_tree_js.js / dep_tree_go.{sh,py}
│   │   ├── ast_scanner.py / ast_scanner_js.js / ast_scanner_go.go
│   │   ├── git_diff*.sh
│   │   ├── run_tests*.sh
│   │   ├── snapshot_env*.sh
│   │   ├── preflight*.sh
│   │   ├── validate_lockfile.sh / validate_modfile_go.sh
│   │   ├── api_surface_diff_js.js / api_surface_diff_go.sh
│   │   ├── govulncheck_go.sh
│   │   ├── fetch_changelog.py / parse_pm_errors.py
│   │   ├── save_token.sh
│   │   ├── jira_fetch.py / jira_comment.py / jira_transition.py
│   │   ├── package.json       # JS helper deps
│   │   └── node_modules/      # JS helper deps (gitignored)
│   ├── references/            # 語言別 reference 文件
│   └── templates/
│
├── install.sh / install.bat / install-cygwin64.sh
├── verify_installation.sh
├── grant_permissions.py       # 寫入 Claude Code settings.json 的權限
├── CLAUDE.md                  # repo 層級的 Claude Code 指示
├── README.md / README.zh-TW.md
└── package-upgrade-agent-architecture.md
```

**注意**：
- ✅ Python scripts 直接在 `package-upgrade/scripts/`
- ✅ 不使用 `src/` 目錄
- ✅ 不使用 symlinks
- ✅ JS helpers 用 `scripts/package.json` 自有依賴；不會污染 Python 環境

---

## UV 常用命令

### 依賴管理

```bash
uv sync                 # 安裝所有依賴
uv sync --no-dev        # 只安裝主要依賴
uv add requests         # 新增套件
uv add --dev pytest     # 新增開發套件
uv remove requests      # 移除套件

# 更新套件
uv lock --upgrade-package requests
uv sync
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

---

## 貢獻流程

1. **Fork 專案**

2. **Clone 並設定環境**
   ```bash
   git clone https://github.com/YOUR_USERNAME/auto-package-migration.git
   cd auto-package-migration
   uv sync
   uv run pre-commit install
   ```

3. **建立 feature branch**
   ```bash
   git checkout -b feature/your-feature
   ```

4. **開發並測試**
   ```bash
   vim package-upgrade/scripts/your_script.py
   uv run black package-upgrade/scripts/your_script.py
   uv run ruff check package-upgrade/scripts/your_script.py
   uv run pytest
   ```

5. **Commit (Conventional Commits)**
   ```bash
   git add .
   git commit -m "feat: add new feature"
   ```

6. **Push 並建立 PR**
   ```bash
   git push origin feature/your-feature
   gh pr create
   ```

更多細節請看 `CONTRIBUTING.md`。

---

## 故障排除

### Q: uv sync 失敗

```bash
uv --version
uv check pyproject.toml
```

### Q: 缺少依賴

```bash
uv sync --reinstall
```

### Q: 虛擬環境損壞

```bash
rm -rf .venv
uv sync
```

### Q: JS helper 缺 node_modules

```bash
cd package-upgrade/scripts && npm install
```

### Q: pre-commit hook 沒跑

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

---

## UV vs Poetry / Pip

| 操作 | pip | poetry | uv |
|------|-----|--------|-----|
| 安裝依賴 | `pip install -r req.txt` | `poetry install` | `uv sync` |
| 新增套件 | 編輯檔案 + `pip install` | `poetry add pkg` | `uv add pkg` |
| 更新套件 | 編輯檔案 + `pip install` | `poetry add pkg@ver` | `uv add pkg` |
| 移除套件 | 編輯檔案 + `pip uninstall` | `poetry remove pkg` | `uv remove pkg` |
| 執行腳本 | `python script.py` | `poetry run python script.py` | `uv run python script.py` |
| 速度 | 慢 | 中 | 極快 (10–100×) |

---

## 參考資源

- [CLAUDE.md](./CLAUDE.md) — repo 工作原則
- [UV 官方文件](https://docs.astral.sh/uv/) / [UV GitHub](https://github.com/astral-sh/uv)
- [Python Packaging Guide](https://packaging.python.org/)
- [Node.js corepack](https://nodejs.org/api/corepack.html)
- [Go modules reference](https://go.dev/ref/mod)
