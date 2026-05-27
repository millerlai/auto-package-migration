# Python Override Semantics — pin transitive 不改 parent 的四種寫法

> 這份文件統整 pip / poetry / uv 三種工具強制升降 transitive dependency 的語法與
> 約束。Phase 2 在挑選策略 `bump_override` 時應引用本檔。對應 Go 的
> `../go/replace_semantics.md`，但 Python 生態更分歧。

---

## 為什麼需要 override

Phase 2 dep_tree 把 target 標為 `transitive`，且 parent 不肯升或 parent 升上去後其他
chain 會破。此時不要硬改 `pyproject.toml [project.dependencies]`，而是用 override
明確 pin transitive 版本——這樣：

1. lockfile 中的 target 版本被強制提升到安全版
2. 不改 manifest 中的 parent 宣告 → 下次 `add`/`update` parent 仍能正常解析
3. override 可在報告中明確說明：「為什麼這個版本不是 solver 自然選擇」

但 **override 是雙面刃**：parent 之後正式升上去後忘了拿掉 override，就會 silently
holding back parent 預期的版本。每個 override 要在 commit message 註記 expected
removal condition。

---

## pip / pip-tools — `--constraint` 與 `requirements.in`

### 純 pip（無 lockfile）

```bash
# constraints.txt
urllib3==2.0.7   # CVE-2023-45803 fix; remove when requests >= 2.32.0
```

```bash
pip install -r requirements.txt --constraint constraints.txt
```

語意：constraint 只在「該套件已經被某條 require 鏈拉進來」時生效。它**不會主動安裝**
未被 require 的套件。這正是 override 想要的行為。

### pip-tools (`requirements.in` + `requirements.txt`)

```ini
# requirements.in
requests>=2.31

# constraints.txt（被 .in 透過 -c 引用）
urllib3==2.0.7
```

```ini
# requirements.in
-c constraints.txt
requests>=2.31
```

然後：

```bash
pip-compile requirements.in --output-file requirements.txt
```

`pip-compile` 會在解析時應用 constraint，產出的 `requirements.txt` 中 urllib3 被 pin
到 2.0.7。

---

## Poetry — `[tool.poetry.dependencies]` 直接列 transitive

Poetry 沒有獨立的 override 機制，做法是**在主 `[tool.poetry.dependencies]` 直接加一行**
讓 solver 知道這個 transitive 也是 main module 的 direct dep：

```toml
[tool.poetry.dependencies]
python = "^3.11"
requests = "^2.31"
# Pin transitive: CVE-2023-45803; remove when requests >= 2.32.0
urllib3 = "==2.0.7"
```

副作用是：transitive 變成 direct，往後 `poetry show --tree` 會把它列在第一層。語意上
這是 Poetry 認可的 override 模式，但代價是 manifest 中多一行不屬於業務邏輯的 dep。

### Poetry 1.5+ 的 `extras` / `groups` 細部 pin

可以放進 `[tool.poetry.group.security.dependencies]` 區分目的：

```toml
[tool.poetry.group.security.dependencies]
urllib3 = "==2.0.7"  # security override; track removal in TODO
```

這樣業務 deps 與 security override 分群顯示。

---

## uv — `[tool.uv.sources]` 與 `[tool.uv.override-dependencies]`

uv 提供了 Python 生態最完整的 override 語法。

### `override-dependencies` —— 強制版本，**不**加到 dep tree

```toml
[tool.uv]
override-dependencies = [
    "urllib3==2.0.7",  # CVE-2023-45803; remove when requests >= 2.32.0
]
```

語意：solver 解析時看到 urllib3 一律 clamp 到 2.0.7，無論 require 鏈要求什麼版本。
**不會主動安裝**未被 require 的套件——這是 uv 文件明確標示的「pin transitive」用法
（uv docs: "Overriding dependencies"）。

### `constraint-dependencies` —— 較寬鬆的版本上下界

```toml
[tool.uv]
constraint-dependencies = [
    "urllib3>=2.0.7,<2.1",
]
```

語意：對 solver 給範圍提示，但仍由 solver 在範圍內挑最高。比 `override` 寬鬆。

### `[tool.uv.sources]` —— 從特定來源拉

```toml
[tool.uv.sources]
my-fork = { git = "https://github.com/me/forked.git", rev = "abcdef" }
```

這不是 version override 而是**來源** override，類似 Go 的 `replace`。常見於：套件官方
還沒釋出 fix，先用自己 fork 的版本擋。

---

## 對應策略表

`dep_tree*.py` 偵測 transitive 後，Phase 2 依下列順序挑：

| 偵測情境 | 推薦工具 | 推薦語法 | 對應 SKILL.md 策略 |
|----------|----------|----------|---------------------|
| Pip / pip-tools，有 lockfile | pip-tools | `requirements.in` + `-c constraints.txt` | `bump_override` |
| Pip 無 lockfile（手動裝） | pip + 文件 | `pip install --constraint constraints.txt -r requirements.txt` | `bump_override` |
| Poetry | poetry | `[tool.poetry.dependencies]` 加一行 | `bump_override` |
| Poetry 1.5+，想分群 | poetry | `[tool.poetry.group.security.dependencies]` | `bump_override` |
| uv，已知 fix 版本 | uv | `[tool.uv] override-dependencies` | `bump_override` |
| uv，僅範圍 hint | uv | `[tool.uv] constraint-dependencies` | `bump_override` |
| 套件官方無 fix release，需 fork | poetry / uv | `[tool.poetry.source]` 或 `[tool.uv.sources]` git+ | `add_source_override` |

`add_source_override` 是 Python 版的 `add_replace`（Go），新策略名建議在 Phase 2 加入。

---

## 偵測欄位（detect_env.sh 應補的 hint）

升級 skill 的 `detect_env.sh` 偵測到下列檔案存在時，應在 `memory_hints` 加註：

| 檔案 / 段落 | hint |
|-------------|------|
| `constraints.txt` 存在於 repo root | `has_pip_constraints` |
| `requirements.in` 引用 `-c` | `pip_tools_with_constraints` |
| `pyproject.toml` 含 `[tool.uv.override-dependencies]` | `uv_overrides` |
| `pyproject.toml` 含 `[tool.uv.sources]` | `uv_sources` |
| `pyproject.toml` 含 `[tool.poetry.group.<x>.dependencies]` 且該 group 名稱含 `security` / `override` / `pin` | `poetry_security_group` |

這些 hint 讓 Phase 2 策略選擇有依據。

---

## 常見陷阱

1. **`poetry update` 會無視 `dependencies` 區塊中的 transitive override**：
   `poetry update` 視所有 `[tool.poetry.dependencies]` entry 為 direct，會主動找最新版。
   要保持 pin 必須加 `==` 而非 `^` / `~`。

2. **`pip install -U` 忽略 `--constraint`**：
   ```bash
   pip install -U urllib3 --constraint constraints.txt   # ❌ -U 優先，constraint 被忽略
   ```
   要 pin 就不要加 `-U`。

3. **`uv lock --upgrade-package <pkg>` 會繞過 `override-dependencies`**：
   uv 0.4+ 修正了此行為，但 0.3.x 有 bug。檢查 `uv --version`。

4. **Poetry monorepo（path dep）忽略 root override**：
   `path = "../libs/foo"` 形式的 dep 走 editable install，path 內部的 deps 不受 root
   `[tool.poetry.dependencies]` override 影響。要分別在 path 內部 pin。

5. **`constraints.txt` 不支援 extras**：
   `urllib3[secure]==2.0.7` 在 constraint 中無效（pip 會 warn 並忽略 extras）。
   要用 extras 必須改用 direct require。

---

## 為什麼有這份文件

Go 有 `../go/replace_semantics.md` 統整 replace 語意，但 Python 對應的 override 知識散落
在 `pip_workflow.md` / `poetry_workflow.md` / `uv_workflow.md`，使用者要在三個檔案間
跳。本文件統整 Python 三套工具的 override 寫法，並對應到 Phase 2 策略表，
讓 `bump_override` 策略可被機械化選擇（TODO.md 任務 2.2）。
