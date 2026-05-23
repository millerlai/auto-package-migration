@echo off
REM install.bat - 快速安裝 Package Upgrade Skill (Windows)
REM Usage: install.bat [--global|--project] [--skip-permissions]

REM 切換到 UTF-8 codepage,否則 CP950 下 cmd 解析器會把以 9D 結尾的中文字 (如 "裝")
REM 後面的 % / ! 吃掉,造成 %NC% / !NC! 無法展開、ANSI reset 漏掉等顯示錯誤。
chcp 65001 >nul

setlocal enabledelayedexpansion

REM 啟用 ANSI 色彩 (Windows 10+ Terminal / cmd 支援)
for /f "delims=" %%a in ('powershell -NoP -C "[char]27" 2^>nul') do set "ESC=%%a"
if defined ESC (
    set "RED=!ESC![31m"
    set "GREEN=!ESC![32m"
    set "YELLOW=!ESC![33m"
    set "BLUE=!ESC![34m"
    set "NC=!ESC![0m"
) else (
    set "RED="
    set "GREEN="
    set "YELLOW="
    set "BLUE="
    set "NC="
)

REM 預設安裝模式
set "MODE=global"
set "SKIP_PERMISSIONS=false"

REM 解析參數
:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="--project" ( set "MODE=project" & shift & goto parse_args )
if /i "%~1"=="--global"  ( set "MODE=global"  & shift & goto parse_args )
if /i "%~1"=="--skip-permissions" ( set "SKIP_PERMISSIONS=true" & shift & goto parse_args )
if /i "%~1"=="-h" goto show_help
if /i "%~1"=="--help" goto show_help
echo Unknown option: %~1
shift
goto parse_args

:show_help
echo Usage: install.bat [--global^|--project] [--skip-permissions]
echo.
echo   --global              Install to %%USERPROFILE%%\.claude\skills\package-upgrade (default)
echo   --project             Install to .\.claude\skills\package-upgrade
echo   --skip-permissions    Don't offer to write the recommended Claude Code
echo                         permissions into settings.json
endlocal
exit /b 0

:args_done

echo %BLUE%==========================================%NC%
echo Package Upgrade Skill 安裝程式
echo %BLUE%==========================================%NC%
echo.

REM 檢查是否在專案根目錄
if not exist "package-upgrade\" (
    echo %RED%錯誤: 請在專案根目錄執行此腳本%NC%
    echo 目前路徑: %CD%
    echo 預期看到: package-upgrade\ 目錄
    endlocal
    exit /b 1
)

REM 安裝目標
if /i "%MODE%"=="global" (
    set "TARGET_DIR=%USERPROFILE%\.claude\skills\package-upgrade"
    echo %GREEN%安裝模式: 全域安裝%NC%
) else (
    set "TARGET_DIR=.\.claude\skills\package-upgrade"
    echo %GREEN%安裝模式: 專案級安裝%NC%
)
echo 安裝位置: !TARGET_DIR!

echo.
set "REPLY="
set /p "REPLY=繼續安裝? (y/N) "
if /i not "!REPLY!"=="y" (
    echo 安裝已取消
    endlocal
    exit /b 0
)

REM 建立目標目錄
echo.
echo %BLUE%步驟 1/8: 建立目錄%NC%
for %%I in ("!TARGET_DIR!") do set "PARENT_DIR=%%~dpI"
if not exist "!PARENT_DIR!" mkdir "!PARENT_DIR!" 2>nul

if exist "!TARGET_DIR!\" (
    echo %YELLOW%警告: 目標目錄已存在,將會覆蓋%NC%
    set "REPLY="
    set /p "REPLY=確定要覆蓋嗎? (y/N) "
    if /i not "!REPLY!"=="y" (
        echo 安裝已取消
        endlocal
        exit /b 0
    )
    rmdir /S /Q "!TARGET_DIR!"
)

REM 複製檔案
echo.
echo %BLUE%步驟 2/8: 複製檔案%NC%
xcopy /E /I /Y /Q "package-upgrade" "!TARGET_DIR!" >nul
if errorlevel 1 (
    echo %RED%✗ 檔案複製失敗%NC%
    endlocal
    exit /b 1
)
echo %GREEN%✓ 檔案已複製%NC%

REM 設定執行權限 (Windows 不需要)
echo.
echo %BLUE%步驟 3/8: 設定執行權限%NC%
echo %GREEN%✓ Windows 不需設定執行權限,略過%NC%

REM 偵測 Python 命令
set "PYTHON_CMD="
where python >nul 2>nul && set "PYTHON_CMD=python"
if not defined PYTHON_CMD (
    where py >nul 2>nul && set "PYTHON_CMD=py -3"
)

REM 檢查並安裝 Python 依賴
echo.
echo %BLUE%步驟 4/8: 檢查 Python 依賴%NC%

set "PY_MISSING_FLAG=false"
if not defined PYTHON_CMD (
    echo %YELLOW%⚠ 未偵測到 python,跳過 Python 依賴檢查%NC%
    echo   請安裝 Python 3.8+:
    echo     winget install Python.Python.3.12
    echo     或從 https://www.python.org/downloads/ 下載
    set "PY_MISSING_FLAG=true"
) else (
    set "MISSING_DEPS="
    !PYTHON_CMD! -c "import pipdeptree" 2>nul
    if errorlevel 1 set "MISSING_DEPS=!MISSING_DEPS! pipdeptree"
    !PYTHON_CMD! -c "import requests" 2>nul
    if errorlevel 1 set "MISSING_DEPS=!MISSING_DEPS! requests"

    if defined MISSING_DEPS (
        echo %YELLOW%缺少依賴:!MISSING_DEPS!%NC%
        set "REPLY="
        set /p "REPLY=是否安裝? (y/N) "
        if /i "!REPLY!"=="y" (
            !PYTHON_CMD! -m pip install !MISSING_DEPS!
            echo %GREEN%✓ 依賴已安裝%NC%
        ) else (
            echo %YELLOW%⚠ 跳過依賴安裝,稍後請手動執行:%NC%
            echo   !PYTHON_CMD! -m pip install!MISSING_DEPS!
            set "PY_MISSING_FLAG=true"
        )
    ) else (
        echo %GREEN%✓ 所有依賴已安裝%NC%
    )
)

REM 檢查並安裝 Node 依賴 (JavaScript 支援)
echo.
echo %BLUE%步驟 5/8: 安裝 JavaScript 支援的 Node 依賴%NC%

where node >nul 2>nul
if errorlevel 1 (
    echo %YELLOW%⚠ 未偵測到 node — JavaScript 套件升級功能將無法使用%NC%
    echo   安裝建議:
    echo     winget install OpenJS.NodeJS.LTS
    echo     或從 https://nodejs.org/ 下載安裝
    echo   Python 套件升級不受影響。
) else (
    where npm >nul 2>nul
    if errorlevel 1 (
        echo %YELLOW%⚠ 偵測到 node 但找不到 npm%NC%
        echo   JavaScript 支援會缺少 dep_tree_js.js 與 api_surface_diff_js.js 所需的 npm 命令
    ) else (
        for /f "delims=" %%v in ('node --version 2^>nul') do set "NODE_VER=%%v"
        echo   node 版本: !NODE_VER!
        if exist "!TARGET_DIR!\scripts\package.json" (
            echo   安裝 @babel/parser, @babel/traverse, ts-morph, semver...
            pushd "!TARGET_DIR!\scripts" >nul
            call npm install --no-audit --no-fund --loglevel=error >nul 2>&1
            if errorlevel 1 (
                echo %YELLOW%⚠ npm install 失敗 — 可稍後手動執行: cd "!TARGET_DIR!\scripts" ^&^& npm install%NC%
            ) else (
                echo %GREEN%✓ Node 依賴已安裝到 !TARGET_DIR!\scripts\node_modules%NC%
            )
            popd >nul
        ) else (
            echo %YELLOW%⚠ 找不到 !TARGET_DIR!\scripts\package.json,跳過 Node 依賴安裝%NC%
        )
    )
)

REM 檢查系統工具
echo.
echo %BLUE%步驟 6/8: 檢查系統工具%NC%

set "TOOLS_MISSING_FLAG=false"
set "MISSING_TOOLS="
where jq  >nul 2>nul || set "MISSING_TOOLS=!MISSING_TOOLS! jq"
where git >nul 2>nul || set "MISSING_TOOLS=!MISSING_TOOLS! git"

if defined MISSING_TOOLS (
    echo %YELLOW%⚠ 缺少系統工具:!MISSING_TOOLS!%NC%
    echo.
    echo 安裝建議:
    for %%t in (!MISSING_TOOLS!) do (
        if /i "%%t"=="jq"  echo   jq:  winget install jqlang.jq        或 choco install jq
        if /i "%%t"=="git" echo   git: winget install Git.Git           或 choco install git
    )
    set "TOOLS_MISSING_FLAG=true"
) else (
    echo %GREEN%✓ 所有系統工具已安裝%NC%
)

REM 檢查 / 安裝 gh CLI (PR 自動化)
echo.
echo %BLUE%步驟 7/8: 檢查 gh CLI (GitHub PR 自動化)%NC%

set "GH_AVAILABLE=false"
where gh >nul 2>nul
if not errorlevel 1 (
    echo %GREEN%✓ 已安裝 gh%NC%
    gh --version 2>nul
    set "GH_AVAILABLE=true"
) else (
    echo %YELLOW%未偵測到 gh CLI%NC%
    echo   gh 用於 Phase 7 自動建立 GitHub PR; 沒裝的話 skill 會 fallback 為印 URL 讓你手動建。
    set "REPLY="
    set /p "REPLY=  是否現在安裝 gh? (y/N) "
    if /i "!REPLY!"=="y" (
        where winget >nul 2>nul
        if not errorlevel 1 (
            echo   使用 winget 安裝...
            winget install --id GitHub.cli -e --source winget
            REM PATH 可能要重開 terminal 才生效,但先重新嘗試
            where gh >nul 2>nul
            if not errorlevel 1 (
                echo %GREEN%✓ gh 已就緒%NC%
                set "GH_AVAILABLE=true"
            ) else (
                echo %YELLOW%⚠ 安裝後仍找不到 gh — 可能要重開 terminal 讓 PATH 生效%NC%
            )
        ) else (
            echo   未偵測到 winget。請在另一個 terminal 執行以下任一方式:
            echo     1^) scoop install gh
            echo     2^) choco install gh
            echo     3^) 從 https://github.com/cli/cli/releases 下載 .msi 安裝
            set "REPLY="
            set /p "REPLY=  安裝完成後按 Enter 繼續 (或 Ctrl-C 中止)..."
            where gh >nul 2>nul
            if not errorlevel 1 set "GH_AVAILABLE=true"
        )
    ) else (
        echo   已跳過 gh 安裝。
    )
)

REM gh 認證
if /i "!GH_AVAILABLE!"=="true" (
    gh auth status >nul 2>nul
    if not errorlevel 1 (
        echo %GREEN%✓ gh 已認證%NC%
    ) else (
        echo %YELLOW%gh 尚未認證 — Skill 建立 PR 時會失敗%NC%
        set "REPLY="
        set /p "REPLY=  現在執行 gh auth login? (y/N) "
        if /i "!REPLY!"=="y" (
            gh auth login
        ) else (
            echo   已跳過。日後請執行: gh auth login
        )
    )
)

REM 設定 Claude Code 權限
echo.
echo %BLUE%步驟 8/8: 設定 Claude Code 權限%NC%

if /i "%MODE%"=="global" (
    set "SETTINGS_FILE=%USERPROFILE%\.claude\settings.json"
) else (
    set "SETTINGS_FILE=.\.claude\settings.json"
)

set "GRANT_SCRIPT=%~dp0grant_permissions.py"
if not exist "!GRANT_SCRIPT!" (
    echo %YELLOW%⚠ 找不到 grant_permissions.py,跳過權限設定%NC%
    goto :done
)

if /i "%SKIP_PERMISSIONS%"=="true" (
    echo %YELLOW%已指定 --skip-permissions,跳過權限設定%NC%
    echo 若要稍後手動套用,執行:
    echo   python "!GRANT_SCRIPT!" --settings "!SETTINGS_FILE!" --mode %MODE% [--gh-entries all^|none^|^<keys^>]
    goto :done
)

if not defined PYTHON_CMD (
    echo %YELLOW%⚠ 沒有可用的 python,無法套用權限。安裝 Python 後手動執行:%NC%
    echo   python "!GRANT_SCRIPT!" --settings "!SETTINGS_FILE!" --mode %MODE%
    goto :done
)

echo.
echo Skill 執行時會用到以下類型的權限:
echo   - Bash: skill 內建 scripts、git status/diff/log、poetry/pip/uv 套件操作、
echo           npm install/ls/show/pack/audit、node、grep、docker ps、tar -xzf
echo   - WebFetch: pypi.org、registry.npmjs.org、www.npmjs.com、github.com、
echo               raw.githubusercontent.com、api.github.com
echo   - WebSearch (用於查詢 CVE / changelog)
echo   - MCP (Jira): getJiraIssue、getTransitionsForJiraIssue、getAccessibleAtlassianResources
echo.
echo 下列動作會放入 'ask' 清單,執行前仍會提示確認:
echo   - git push、git commit (非 -m 形式)
echo   - 對 Jira 寫入留言 / 轉狀態
echo.

REM --- gh 權限 (opt-in) ---
set "GH_ENTRIES=none"
echo gh CLI 權限 (4 個 entries) 為 opt-in:
echo   - Bash^(gh auth status:*^)  — 檢查 gh 認證狀態 (建議,Phase 0/preflight 會用到)
echo   - Bash^(gh pr create:*^)    — 自動建立 GitHub PR (建議,Phase 7 核心動作)
echo   - Bash^(gh pr view:*^)      — 查 PR 狀態與內容
echo   - Bash^(gh api:*^)          — 呼叫 GitHub REST API (例: GHE 認證檢查、PR 細節)

if /i "!GH_AVAILABLE!"=="true" (
    set "GH_DEFAULT=Y"
    set "REPLY="
    set /p "REPLY=開啟 gh 權限? [Y]全開 / [N]全不開 / [S]逐項選 (預設 Y,因偵測到 gh): "
) else (
    set "GH_DEFAULT=N"
    set "REPLY="
    set /p "REPLY=開啟 gh 權限? [y]全開 / [N]全不開 / [s]逐項選 (預設 N,因未偵測到 gh): "
)
if "!REPLY!"=="" set "REPLY=!GH_DEFAULT!"

if /i "!REPLY!"=="Y" (
    set "GH_ENTRIES=all"
) else if /i "!REPLY!"=="S" (
    set "GH_ENTRIES="
    call :ask_gh_entry "auth_status" "Bash(gh auth status:*)"
    call :ask_gh_entry "pr_create"   "Bash(gh pr create:*)"
    call :ask_gh_entry "pr_view"     "Bash(gh pr view:*)"
    call :ask_gh_entry "api"         "Bash(gh api:*)"
    if not defined GH_ENTRIES set "GH_ENTRIES=none"
) else (
    set "GH_ENTRIES=none"
)
echo   -^> gh-entries: !GH_ENTRIES!
echo.

echo 預覽 (dry-run) 將要寫入 !SETTINGS_FILE! 的變更...
echo.
!PYTHON_CMD! "!GRANT_SCRIPT!" --settings "!SETTINGS_FILE!" --mode %MODE% --gh-entries !GH_ENTRIES! --dry-run
if errorlevel 1 (
    echo %RED%✗ 權限預覽失敗,請檢查 !SETTINGS_FILE! 是否為合法 JSON%NC%
    goto :done
)

echo.
set "REPLY="
set /p "REPLY=套用這些權限? (y/N) "
if /i "!REPLY!"=="y" (
    !PYTHON_CMD! "!GRANT_SCRIPT!" --settings "!SETTINGS_FILE!" --mode %MODE% --gh-entries !GH_ENTRIES!
    echo %GREEN%✓ 權限已寫入 !SETTINGS_FILE!%NC%
) else (
    echo %YELLOW%已跳過,可日後執行:%NC%
    echo   !PYTHON_CMD! "!GRANT_SCRIPT!" --settings "!SETTINGS_FILE!" --mode %MODE% --gh-entries !GH_ENTRIES!
)

:done
echo.
echo %GREEN%==========================================%NC%
echo %GREEN%✓ 安裝完成^^!%NC%
echo %GREEN%==========================================%NC%
echo.
echo 安裝位置: !TARGET_DIR!
echo.
echo %BLUE%下一步:%NC%
echo.
echo 1. 驗證安裝 (若無 .bat 版可在 Git Bash / WSL 內執行 .sh):
echo    bash verify_installation.sh
echo.
echo 2. 測試使用:
echo    claude
echo    然後輸入: list available skills
echo.
echo 3. 開始使用:
echo    升級 requests 到 2.32.0      (Python)
echo    升級 axios 到 1.6.0           (JavaScript)
echo    修復 CVE-2024-35195
echo.

if /i "!PY_MISSING_FLAG!"=="true" (
    echo %YELLOW%⚠ 注意: 請先安裝缺少的 Python 依賴%NC%
)
if /i "!TOOLS_MISSING_FLAG!"=="true" (
    echo %YELLOW%⚠ 注意: 請先安裝缺少的系統工具%NC%
)

echo.
echo 更多資訊請參考:
echo   - INSTALLATION_GUIDE.md
echo   - package-upgrade\README.md
echo.

endlocal
exit /b 0


REM ====================================================================
REM Helper: ask one gh permission entry. %~1 = key, %~2 = display label
REM ====================================================================
:ask_gh_entry
set "R="
set /p "R=  - %~2? (y/N) "
if /i "!R!"=="y" (
    if defined GH_ENTRIES (
        set "GH_ENTRIES=!GH_ENTRIES!,%~1"
    ) else (
        set "GH_ENTRIES=%~1"
    )
)
exit /b 0
