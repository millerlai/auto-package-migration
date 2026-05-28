@echo off
REM verify_installation.bat - 驗證 Package Upgrade Skill 安裝 (Windows)
REM Usage: verify_installation.bat
REM
REM 安裝根目錄偵測順序 (對齊 verify_installation.sh):
REM   1. %PACKAGE_UPGRADE_SKILLS_ROOT% (覆蓋,供測試或非標準安裝用)
REM   2. %USERPROFILE%\.claude\skills        (install.bat 預設 --global)
REM   3. .\.claude\skills                    (install.bat --project)
REM
REM 注意: 與 .sh 不同,Windows 沒有「可執行權限」概念,scripts 只檢查存在性。
REM 需要 bash 的 helper (detect_env.sh / preflight.sh / save_token.sh) 的功能性
REM 測試不在此原生 .bat 涵蓋範圍 — 請在 Git Bash 內跑 verify_installation.sh 取得完整覆蓋。

chcp 65001 >nul
setlocal enabledelayedexpansion

REM 啟用 ANSI 色彩 (Windows 10+ Terminal / cmd 支援;無法取得則降級為純文字)
for /f "delims=" %%a in ('powershell -NoP -C "[char]27" 2^>nul') do set "ESC=%%a"
if defined ESC (
    set "RED=!ESC![31m"
    set "GREEN=!ESC![32m"
    set "YELLOW=!ESC![33m"
    set "NC=!ESC![0m"
) else (
    set "RED="
    set "GREEN="
    set "YELLOW="
    set "NC="
)

set "PASSED=0"
set "FAILED=0"

REM --- 偵測安裝根目錄 ---
if defined PACKAGE_UPGRADE_SKILLS_ROOT (
    set "SKILLS_ROOT=%PACKAGE_UPGRADE_SKILLS_ROOT%"
) else (
    set "SKILLS_ROOT=%USERPROFILE%\.claude\skills"
)
if not exist "!SKILLS_ROOT!\package-upgrade\" if exist ".\.claude\skills\package-upgrade\" set "SKILLS_ROOT=.\.claude\skills"
set "SKILL_DIR=!SKILLS_ROOT!\package-upgrade"
set "FEEDBACK_DIR=!SKILLS_ROOT!\package-upgrade-feedback"

REM --- 偵測 Python / jq ---
set "PYTHON_CMD="
where python >nul 2>nul && set "PYTHON_CMD=python"
if not defined PYTHON_CMD ( where py >nul 2>nul && set "PYTHON_CMD=py -3" )
set "HAS_JQ="
where jq >nul 2>nul && set "HAS_JQ=1"

echo ==========================================
echo Package Upgrade Skill 安裝驗證
echo ==========================================
echo 安裝根目錄: !SKILLS_ROOT!
echo.

REM 1. 檢查 Skill 目錄
echo 1. 檢查 Skill 目錄...
if exist "!SKILL_DIR!\" (
    call :check_pass "Skill 目錄存在: !SKILL_DIR!"
) else (
    call :check_fail "Skill 目錄不存在: !SKILL_DIR!"
    echo.
    echo 請執行安裝:
    echo   install.bat            全域安裝到 %USERPROFILE%\.claude\skills
    echo   install.bat --project  專案級安裝到 .\.claude\skills
    endlocal
    exit /b 1
)

REM 2. 檢查核心檔案
echo.
echo 2. 檢查核心檔案...
for %%f in (LICENSE README.md SKILL.md) do (
    if exist "!SKILL_DIR!\%%f" ( call :check_pass "%%f 存在" ) else ( call :check_fail "%%f 不存在" )
)

REM 3. 檢查 SKILL.md frontmatter
echo.
echo 3. 檢查 SKILL.md frontmatter...
if exist "!SKILL_DIR!\SKILL.md" (
    call :first_line "!SKILL_DIR!\SKILL.md"
    if "!FIRST!"=="---" ( call :check_pass "Frontmatter 開始標記正確" ) else ( call :check_fail "Frontmatter 開始標記錯誤" )
    findstr /b /c:"name: package-upgrade" "!SKILL_DIR!\SKILL.md" >nul 2>nul
    if errorlevel 1 ( call :check_fail "Skill 名稱錯誤或缺失" ) else ( call :check_pass "Skill 名稱正確" )
    findstr /b /c:"description:" "!SKILL_DIR!\SKILL.md" >nul 2>nul
    if errorlevel 1 ( call :check_fail "Description 缺失" ) else ( call :check_pass "Description 存在" )
)

REM 4. 檢查 scripts (per-language 子目錄: common / python / javascript / go)
echo.
echo 4. 檢查 Scripts...
for %%f in (fetch_changelog.py git_diff.sh parse_pm_errors.py save_token.sh jira_comment.py jira_fetch.py jira_transition.py) do call :check_one common "%%f"
for %%f in (detect_env.sh dep_tree.py ast_scanner.py run_tests.sh snapshot_env.sh preflight.sh validate_lockfile.sh api_surface_diff.sh pip_audit.sh) do call :check_one python "%%f"
for %%f in (detect_env.sh dep_tree.js ast_scanner.js api_surface_diff.js git_diff.sh run_tests.sh snapshot_env.sh preflight.sh validate_lockfile.sh runtime_verify.js) do call :check_one javascript "%%f"
for %%f in (detect_env.sh dep_tree.sh dep_tree.py ast_scanner.go api_surface_diff.sh git_diff.sh run_tests.sh snapshot_env.sh preflight.sh govulncheck.sh validate_modfile.sh) do call :check_one go "%%f"

REM 5. 檢查 Python scripts 內容 (shebang)
echo.
echo 5. 檢查 Python Scripts 內容...
call :check_shebang "!SKILL_DIR!\scripts\python\dep_tree.py" "python/dep_tree.py"
call :check_shebang "!SKILL_DIR!\scripts\python\ast_scanner.py" "python/ast_scanner.py"
call :check_shebang "!SKILL_DIR!\scripts\common\fetch_changelog.py" "common/fetch_changelog.py"

REM 6. 檢查 references (per-language 子目錄)
echo.
echo 6. 檢查 Reference 文件...
for %%f in (auth_tokens.md bdsa_mapping.md breaking_change_patterns.md important_dependency_update.md jira_workflow.md) do call :check_ref common "%%f"
for %%f in (breaking_change_patterns.md override_semantics.md pip_lock_patterns.md pip_workflow.md poetry_workflow.md runtime_verification.md uv_workflow.md) do call :check_ref python "%%f"
for %%f in (ast_strategy.md breaking_change_patterns.md npm_workflow.md override_semantics.md pnpm_workflow.md runtime_verification.md workflow.md yarn_workflow.md) do call :check_ref javascript "%%f"
for %%f in (breaking_change_patterns.md govulncheck.md major_version_paths.md replace_semantics.md runtime_verification.md workflow.md) do call :check_ref go "%%f"

REM 7. 檢查 templates
echo.
echo 7. 檢查 Templates...
if exist "!SKILL_DIR!\templates\report_structure.md" ( call :check_pass "report_structure.md 存在" ) else ( call :check_fail "report_structure.md 不存在" )

REM 8. 檢查 Python 依賴
echo.
echo 8. 檢查 Python 依賴...
if defined PYTHON_CMD (
    call :check_pass "python3 可用"
    call :check_pymod pipdeptree "pip install pipdeptree"
    call :check_pymod requests "pip install requests"
) else (
    call :check_fail "python3 不可用"
)

REM 9. 檢查系統工具
echo.
echo 9. 檢查系統工具...
call :check_cmd git "git 可用" "git 不可用" fail
call :check_cmd jq "jq 可用" "jq 不可用 [建議安裝: winget install jqlang.jq]" warn
call :check_cmd gh "gh CLI 可用 [可選]" "gh CLI 不可用 [可選,用於自動建立 PR]" warn

REM 9b. Node + JS helper deps
echo.
echo 9b. 檢查 Node 環境與 JS helper 依賴...
where node >nul 2>nul
if errorlevel 1 (
    call :check_warn "node 不可用 — JavaScript 套件升級功能無法使用 [Python 功能不受影響]"
    goto :after_node
)
for /f "delims=" %%v in ('node --version 2^>nul') do set "NODE_VER=%%v"
call :check_pass "node 可用 [!NODE_VER!]"
call :check_cmd npm "npm 可用" "npm 不可用 [JS 升級流程會缺命令]" warn
if exist "!SKILL_DIR!\scripts\javascript\node_modules\@babel\parser\" (
    call :check_pass "JS helper deps 已安裝 [@babel/parser found]"
) else (
    call :check_warn "JS helper deps 未安裝 — 在 scripts\javascript 內執行 npm install"
)
:after_node

REM 9c. Go 工具鏈 (可選 — 僅 Go 套件升級需要)
echo.
echo 9c. 檢查 Go 工具鏈 [可選]...
where go >nul 2>nul
if errorlevel 1 (
    call :check_warn "go 不可用 — Go 套件升級功能無法使用 [Python/JS 功能不受影響]"
    goto :after_go
)
for /f "tokens=3" %%v in ('go version 2^>nul') do set "GO_VER=%%v"
call :check_pass "go 可用 [!GO_VER!]"
call :check_cmd govulncheck "govulncheck 可用 [Go reachability 分析]" "govulncheck 不可用 [可選: go install golang.org/x/vuln/cmd/govulncheck@latest]" warn
:after_go

REM 9d. package-upgrade-feedback skill
echo.
echo 9d. 檢查 package-upgrade-feedback skill...
if not exist "!FEEDBACK_DIR!\" (
    call :check_warn "feedback skill 未安裝 [!FEEDBACK_DIR!] — install 會一併安裝;若只手動複製主 skill 可忽略"
    goto :after_feedback
)
call :check_pass "feedback skill 目錄存在: !FEEDBACK_DIR!"
if exist "!FEEDBACK_DIR!\SKILL.md" (
    call :check_pass "feedback SKILL.md 存在"
    findstr /b /c:"name: package-upgrade-feedback" "!FEEDBACK_DIR!\SKILL.md" >nul 2>nul
    if errorlevel 1 ( call :check_fail "feedback skill 名稱錯誤或缺失" ) else ( call :check_pass "feedback skill 名稱正確" )
) else (
    call :check_fail "feedback SKILL.md 不存在"
)
for %%s in (sanitize_feedback.sh submit_feedback.sh) do (
    if exist "!FEEDBACK_DIR!\scripts\%%s" ( call :check_pass "feedback scripts/%%s 存在" ) else ( call :check_fail "feedback scripts/%%s 不存在" )
)
:after_feedback

REM 10. 功能測試 (僅原生可跑的 python / node helper;bash helper 由 .sh 覆蓋)
echo.
echo 10. 功能測試...
call :func_py_deptree
call :func_parse_pm
call :func_js_ast
if not defined HAS_JQ echo      [略過功能測試: 未偵測到 jq]

REM 總結
echo.
echo ==========================================
echo 驗證結果總結
echo ==========================================
echo %GREEN%通過: !PASSED!%NC%
echo %RED%失敗: !FAILED!%NC%
echo.

if !FAILED! EQU 0 (
    echo %GREEN%[OK] 安裝驗證通過%NC%
    echo.
    echo 下一步:
    echo 1. 啟動 Claude Code: claude
    echo 2. 輸入: list available skills
    echo 3. 確認 package-upgrade 出現在列表中
    echo.
    echo 測試使用:
    echo   輸入: 檢查這個專案能不能升級 requests
    endlocal
    exit /b 0
) else (
    echo %RED%[X] 安裝驗證失敗,請修復上述問題%NC%
    echo.
    echo 常見修復方法:
    echo 1. 重新安裝 skill:
    echo    install.bat
    echo 2. 安裝 Python 依賴:
    echo    pip install pipdeptree requests
    echo 3. 安裝 jq: winget install jqlang.jq
    echo 4. 安裝 JS helper deps: 在 skill 的 scripts\javascript 內執行 npm install
    endlocal
    exit /b 1
)

REM ====================================================================
REM Helpers
REM ====================================================================

:check_pass
echo %GREEN%[PASS]%NC% %~1
set /a PASSED+=1
exit /b 0

:check_fail
echo %RED%[FAIL]%NC% %~1
set /a FAILED+=1
exit /b 0

:check_warn
echo %YELLOW%[WARN]%NC% %~1
exit /b 0

REM %~1 = scripts 子目錄, %~2 = 檔名
:check_one
if exist "!SKILL_DIR!\scripts\%~1\%~2" ( call :check_pass "scripts/%~1/%~2 存在" ) else ( call :check_fail "scripts/%~1/%~2 不存在" )
exit /b 0

REM %~1 = references 子目錄, %~2 = 檔名
:check_ref
if exist "!SKILL_DIR!\references\%~1\%~2" ( call :check_pass "references/%~1/%~2 存在" ) else ( call :check_fail "references/%~1/%~2 不存在" )
exit /b 0

REM %~1 = python 模組名, %~2 = 安裝提示
:check_pymod
!PYTHON_CMD! -c "import %~1" 2>nul
if errorlevel 1 ( call :check_fail "%~1 未安裝" & echo      安裝: %~2 ) else ( call :check_pass "%~1 已安裝" )
exit /b 0

REM %~1 = 待測命令, %~2 = 通過訊息, %~3 = 失敗訊息, %~4 = warn|fail
:check_cmd
where %~1 >nul 2>nul
if errorlevel 1 (
    if /i "%~4"=="warn" ( call :check_warn "%~3" ) else ( call :check_fail "%~3" )
) else (
    call :check_pass "%~2"
)
exit /b 0

REM %~1 = .py 路徑, %~2 = 相對標籤。檢查 shebang。
REM 用 disabledelayedexpansion 讓 findstr 樣式裡的 ! 維持字面值。
:check_shebang
if not exist "%~1" ( call :check_fail "%~2 不存在" & exit /b 0 )
setlocal disabledelayedexpansion
findstr /b /c:"#!/usr/bin/env python3" "%~1" >nul 2>nul
if errorlevel 1 ( endlocal & call :check_warn "%~2 缺少 shebang" & exit /b 0 )
endlocal
call :check_pass "%~2 格式正確 [有 shebang]"
exit /b 0

REM 讀取檔案第一行 (CRLF 由 for /f 自動去除) -> FIRST
:first_line
set "FIRST="
for /f "usebackq delims=" %%a in ("%~1") do if not defined FIRST set "FIRST=%%a"
exit /b 0

REM --- 功能測試: python dep_tree.py ---
:func_py_deptree
if not defined HAS_JQ exit /b 0
if not defined PYTHON_CMD exit /b 0
!PYTHON_CMD! -c "import requests" 2>nul
if errorlevel 1 exit /b 0
!PYTHON_CMD! "!SKILL_DIR!\scripts\python\dep_tree.py" . requests 2>nul | jq -e ".package_name" >nul 2>nul
if errorlevel 1 ( call :check_warn "scripts/python/dep_tree.py 執行異常 [可能是專案沒有 requests]" ) else ( call :check_pass "scripts/python/dep_tree.py 可正常執行" )
exit /b 0

REM --- 功能測試: common parse_pm_errors.py ---
:func_parse_pm
if not defined HAS_JQ exit /b 0
if not defined PYTHON_CMD exit /b 0
echo YN0041: Invalid authentication | !PYTHON_CMD! "!SKILL_DIR!\scripts\common\parse_pm_errors.py" 2>nul | jq -r ".primary_blocker" 2>nul | findstr /x "auth" >nul 2>nul
if errorlevel 1 ( call :check_warn "scripts/common/parse_pm_errors.py 執行異常" ) else ( call :check_pass "scripts/common/parse_pm_errors.py 可正常執行" )
exit /b 0

REM --- 功能測試: javascript ast_scanner.js ---
:func_js_ast
if not defined HAS_JQ exit /b 0
where node >nul 2>nul || exit /b 0
if not exist "!SKILL_DIR!\scripts\javascript\node_modules\" exit /b 0
set "JS_TMP=%TEMP%\pkgupg_verify_%RANDOM%%RANDOM%"
mkdir "!JS_TMP!" 2>nul
>"!JS_TMP!\package.json" echo {"name":"verify","version":"1.0.0","dependencies":{}}
node "!SKILL_DIR!\scripts\javascript\ast_scanner.js" "!JS_TMP!" axios 2>nul | jq -r ".language" 2>nul | findstr /x "javascript" >nul 2>nul
if errorlevel 1 ( call :check_warn "scripts/javascript/ast_scanner.js 執行異常 — 確認已在 scripts\javascript 跑過 npm install" ) else ( call :check_pass "scripts/javascript/ast_scanner.js 可載入 @babel/parser 並執行" )
rmdir /S /Q "!JS_TMP!" 2>nul
exit /b 0
