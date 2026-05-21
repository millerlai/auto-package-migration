# Go Module Semantics — `tidy` 與 `replace` 兩條容易踩雷的規範

> 這份文件記錄兩條本 skill 反覆撞到的 Go module 規範。任何
> `dep_tree_go.py` 對策略的 rationale 應該引用本檔。

---

## 規範 1 — `go mod tidy` 會剪除 build path 上沒人 import 的 indirect requires

`go mod tidy` 的行為是 **以 main module 的 build graph 為準**，把 `go.mod` 收斂成最小
必要集合。對於 `// indirect` entry：

- 若該 module 仍然在 build graph 上 (有任何其他 require 鏈最終讓 main module 載入它) →
  保留，可能版本被向上調整成 graph 中最高
- 若該 module **不在 build path 上** (例如它原本只是某個 parent 的 build-time tool，
  或我們手動加進來卻沒有任何來源) → **直接刪掉 require 行**

實務後果：當 target 是 indirect 且 `go mod why <pkg>` 回傳
`main module does not need package <pkg>` 時：

```bash
# 直接編輯 indirect entry 升版
go get example.com/leaf@v4.1.4
# go.mod 從 v4.1.3 → v4.1.4 ✅

# 之後跑 tidy
go mod tidy
# go.mod 中 example.com/leaf 整行消失 ❌
```

`bump_indirect` 與 `bump_parent` 都會被 tidy 沖掉 — **只有 `replace` directive 不受
tidy 影響**，因為 `replace` 是規範性指令而非「require」。

判斷依據：

```bash
go mod why -m <target>
```

輸出範例：

```
# example.com/leaf
(main module does not need package example.com/leaf)
```

只要看到 `(main module does not need ...)`，預設策略要改為 `add_replace`。

### 偵測欄位

`dep_tree_go.py` 把 `go mod why -m <target>` 解析結果放在 `go_mod_why_status`：

| 值 | 意義 | 策略含意 |
|----|------|---------|
| `needed` | target 在 build path 上 | bump_indirect / bump_parent 都可考慮 |
| `not_needed_by_main_module` | target 不在 build path,只是 graph 殘留 | **降權 bump_indirect / bump_parent;升權 add_replace** |
| `not_in_module_graph` | target 已不在 graph 上 | not_present,純加新 dep |
| `unknown` | `go mod why` 跑失敗 / 解析失敗 | 不調權,但 rationale 標明此降級 |

---

## 規範 2 — dep module 的 `replace` directive **不繼承** 給 downstream consumer

Go modules 規範明確規定 (見 [Go Modules Reference — replace](https://go.dev/ref/mod#go-mod-file-replace))：

> `replace` directives only apply in the **main module**'s `go.mod` file
> and are **ignored** in other modules.

具體後果：

假設目錄結構：

```
我的 module (main)
  └─ require library-go v1.1.159
                └─ require example.com/leaf v4.1.3
                └─ replace example.com/leaf => example.com/leaf v4.1.4   ← library-go 自己改的
```

`library-go` 內部的 `replace` directive 只在編譯 library-go 自己時生效。當我的 module
import library-go 時，**那條 replace 完全被忽略**。結果是我的 module build 出來仍然
拉的是 `example.com/leaf v4.1.3`（CVE 未修復）。

### 換句話說

- 我想升 `example.com/leaf`，建議「升 library-go 到最新 v1.1.159」這策略 (`bump_parent`)
  ✘ 沒用 — library-go 的 replace 在我這邊不起作用
- 唯一有效的修法是**我自己的** `go.mod` 寫 `replace example.com/leaf => example.com/leaf v4.1.4`

### 偵測欄位

`dep_tree_go.py` 對每個 `direct_parent` fetch 它的 latest `.mod` 檔，並標出兩個欄位：

```jsonc
{
  "type": "bump_parent",
  "target": "library-go",
  "parent_latest_version": "v1.1.159",
  "parent_pins_target_to": "v4.1.3",        // parent 的 require 對 target 的版本
  "parent_uses_replace_for_target": {        // 若 parent 對 target 有 replace
    "new_path": "example.com/leaf",
    "new_version": "v4.1.4"
  },
  "status": "would_not_help",                // 升 parent 無法解決
  "reason": "parent's replace directive does NOT flow to downstream (Go spec)",
  "confidence": 0.05
}
```

當 parent 對 target 有 replace → 直接標 `status: "would_not_help"`，因為升 parent
帶不出我們要的新版。

當 parent 的最新版仍 pin 舊 target 版本 → 標 `status: "would_not_help"` (但 reason
不同：「parent 還沒發版本帶新 target」)。

---

## 兩條規範的合流：CVE patch 場景

最常見的 CVE patch 場景同時踩中這兩條規範：

1. CVE 在某個 transitive dep `L` (leaf)
2. L 在 main module 看起來是 indirect，`go mod why -m L` 回 `not needed`
3. 唯一的 direct parent `P` 的最新版本要嘛還沒升 L (規範 1 失效)，要嘛已升但用 replace (規範 2 失效)

此時 skill 的決策樹應該直接走 `add_replace`：

```jsonc
{
  "recommended_strategy": "add_replace",
  "rationale": "Target is indirect AND not on build path (`go mod why`: not needed). "
               "Parent bump won't help: `P@latest` still pins `L@old` OR uses a local replace. "
               "Per Go spec, replace doesn't flow to downstream consumers. "
               "Only adding a `replace` directive to our own go.mod survives `tidy` and "
               "applies to our build."
}
```

對應的 patch:

```
// In our own go.mod
replace example.com/leaf => example.com/leaf v4.1.4
```

⚠️ **重要 follow-up**: replace 是臨時解。當上游 P 發新版正式 bump L 時，要回來移除
replace。skill 應在 Phase 7.2 commit message + project memory 中記下這個 follow-up。

---

## 偵測腳本要做的事 (給 dep_tree_go.py 實作參考)

```python
# 1. go mod why -m <target>
rc, out, _ = run(["go", "mod", "why", "-m", current_module_path], cwd=project)
if rc == 0:
    if "(main module does not need" in out:
        go_mod_why_status = "not_needed_by_main_module"
    elif "module not in module graph" in out:
        go_mod_why_status = "not_in_module_graph"
    else:
        go_mod_why_status = "needed"
else:
    go_mod_why_status = "unknown"

# 2. for each direct_parent, fetch latest .mod
for parent in direct_parents:
    latest = go_list_versions(parent)[-1]
    # `go mod download -json -x <parent>@<latest>` 會把 .mod 放在 GOMODCACHE
    # 用 GOMODCACHE=$(mktemp -d) 避免污染專案 cache
    parent_mod = fetch_mod_via_download(parent, latest)
    parent_require_target = parse_require_target(parent_mod, target_base)
    parent_replace_target = parse_replace_target(parent_mod, target_base)
    # ... 計算 status
```

---

## 相關參考

- [Go Modules Reference — replace directive](https://go.dev/ref/mod#go-mod-file-replace)
- [Go Modules Reference — go mod tidy](https://go.dev/ref/mod#go-mod-tidy)
- [Go Modules Reference — minimal version selection](https://go.dev/ref/mod#minimal-version-selection)
- [proposal: cmd/go: print why a package is in go.mod (#26988)](https://github.com/golang/go/issues/26988)
