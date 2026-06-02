@echo off
REM uninstall.bat - Remove the skill installed by install.bat (Windows cmd).
REM Usage: uninstall.bat [--global^|--project] [--skip-permissions] [--yes]
REM
REM SAFETY: fingerprints each target dir (SKILL.md name + signature files) and
REM only removes a dir that is THIS skill — a same-named third-party skill is
REM left untouched.

setlocal enabledelayedexpansion

set "MODE=global"
set "SKIP_PERMISSIONS=false"
set "ASSUME_YES=false"

:parse_args
if "%~1"=="" goto after_args
if /i "%~1"=="--project" ( set "MODE=project" & shift & goto parse_args )
if /i "%~1"=="--global"  ( set "MODE=global"  & shift & goto parse_args )
if /i "%~1"=="--skip-permissions" ( set "SKIP_PERMISSIONS=true" & shift & goto parse_args )
if /i "%~1"=="--yes" ( set "ASSUME_YES=true" & shift & goto parse_args )
if /i "%~1"=="-y"    ( set "ASSUME_YES=true" & shift & goto parse_args )
if /i "%~1"=="-h" goto usage
if /i "%~1"=="--help" goto usage
shift & goto parse_args

:usage
echo Usage: uninstall.bat [--global^|--project] [--skip-permissions] [--yes]
echo.
echo   --global              Remove from %%USERPROFILE%%\.claude\skills\ (default)
echo   --project             Remove from .\.claude\skills\
echo   --skip-permissions    Don't touch settings.json
echo   --yes, -y             Non-interactive (also implied by CI). Implies --skip-permissions.
echo.
echo Only directories that fingerprint as THIS skill are removed.
endlocal
exit /b 0

:after_args
if defined CI set "ASSUME_YES=true"
if /i "%PACKAGE_UPGRADE_ASSUME_YES%"=="1" set "ASSUME_YES=true"
if /i "!ASSUME_YES!"=="true" set "SKIP_PERMISSIONS=true"

if /i "!MODE!"=="global" (
    set "SKILLS_ROOT=%USERPROFILE%\.claude\skills"
    set "SETTINGS_FILE=%USERPROFILE%\.claude\settings.json"
) else (
    set "SKILLS_ROOT=.\.claude\skills"
    set "SETTINGS_FILE=.\.claude\settings.json"
)

set "PYTHON_CMD="
where python >nul 2>nul && set "PYTHON_CMD=python"
if not defined PYTHON_CMD ( where py >nul 2>nul && set "PYTHON_CMD=py -3" )

echo ==========================================
echo Package Upgrade Skill Uninstaller
echo ==========================================
echo Location: !SKILLS_ROOT!
echo.

set "REMOVED_ANY=false"
call :process_skill package-upgrade
call :process_skill package-upgrade-feedback

echo.
if /i "!SKIP_PERMISSIONS!"=="true" (
    echo --skip-permissions / non-interactive: settings.json left untouched.
    if defined PYTHON_CMD echo   !PYTHON_CMD! "%~dp0grant_permissions.py" --settings "!SETTINGS_FILE!" --mode !MODE! --uninstall
) else (
    if /i "!REMOVED_ANY!"=="true" (
        if defined PYTHON_CMD if exist "!SETTINGS_FILE!" (
            echo Cleaning provenance Stop hook from settings.json...
            !PYTHON_CMD! "%~dp0grant_permissions.py" --settings "!SETTINGS_FILE!" --mode "!MODE!" --uninstall
        )
    )
)

echo.
echo Done.
endlocal
exit /b 0

REM ----- subroutine: remove one skill if it fingerprints as ours -----
:process_skill
set "SKILL=%~1"
set "DIR=!SKILLS_ROOT!\!SKILL!"
if not exist "!DIR!\" (
    echo - !SKILL!: not installed, skipping
    goto :eof
)
call :is_ours "!SKILL!" "!DIR!"
if not "!IS_OURS!"=="true" (
    echo WARNING: !SKILL!: "!DIR!" does not look like the skill we installed -- skipping ^(avoids deleting a same-named skill^).
    goto :eof
)
set "REPLY=y"
if /i not "!ASSUME_YES!"=="true" set /p "REPLY=Remove !SKILL! (!DIR!)? (y/N) "
if /i "!REPLY!"=="y" (
    rmdir /s /q "!DIR!"
    echo + removed !SKILL!
    set "REMOVED_ANY=true"
) else (
    echo - !SKILL!: skipped
)
goto :eof

REM ----- subroutine: set IS_OURS=true iff dir fingerprints as <skill> -----
:is_ours
set "IS_OURS=false"
set "S=%~1"
set "D=%~2"
if not exist "!D!\SKILL.md" goto :eof
findstr /b /c:"name: !S!" "!D!\SKILL.md" >nul 2>nul || goto :eof
if /i "!S!"=="package-upgrade" (
    if not exist "!D!\scripts\common\save_token.sh" goto :eof
    if not exist "!D!\scripts\common\provenance_stop_hook.py" goto :eof
    if not exist "!D!\scripts\go\dep_tree.py" goto :eof
    set "IS_OURS=true"
    goto :eof
)
if /i "!S!"=="package-upgrade-feedback" (
    if not exist "!D!\scripts\sanitize_feedback.sh" goto :eof
    if not exist "!D!\scripts\submit_feedback.sh" goto :eof
    set "IS_OURS=true"
    goto :eof
)
goto :eof
