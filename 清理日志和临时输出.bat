@echo off
setlocal EnableExtensions

cd /d "%~dp0" || goto :err_cd

echo ======================================
echo   AP Prototype - Cleanup Runtime Logs
echo ======================================
echo Current directory: %cd%
echo.
echo This tool cleans generated logs, temp probes, run outputs, and cache files.
echo It does not clean source code, datasets, config files, HDB data, latest reports, stickers, or generated images.
echo.
echo Choose cleanup mode:
echo   1. Preview only
echo   2. Delete all cleanup targets
echo   3. Keep last 1 day
echo   4. Keep custom number of days
echo.
set /p "MODE=Input 1/2/3/4: "

set "KEEP_DAYS="
set "PREVIEW_ARGS="

if "%MODE%"=="1" (
  set "PREVIEW_ARGS=-Preview"
  goto :run
)

if "%MODE%"=="2" (
  set "KEEP_DAYS=0"
  goto :run
)

if "%MODE%"=="3" (
  set "KEEP_DAYS=1"
  goto :run
)

if "%MODE%"=="4" (
  set /p "KEEP_DAYS=Keep how many days? Input a number: "
  goto :run
)

echo.
echo [ERROR] Invalid mode.
echo.
pause
exit /b 1

:run
set "PS_CMD="
where powershell >nul 2>nul
if not errorlevel 1 (
  set "PS_CMD=powershell"
) else (
  where pwsh >nul 2>nul
  if not errorlevel 1 (
    set "PS_CMD=pwsh"
  )
)

if "%PS_CMD%"=="" (
  echo [ERROR] PowerShell not found.
  echo.
  pause
  exit /b 1
)

if not exist "tools\cleanup_runtime_outputs.ps1" (
  echo [ERROR] Missing tools\cleanup_runtime_outputs.ps1
  echo.
  pause
  exit /b 1
)

echo.
echo Running cleanup helper...
echo.
if "%PREVIEW_ARGS%"=="" (
  %PS_CMD% -NoProfile -ExecutionPolicy Bypass -File "tools\cleanup_runtime_outputs.ps1" -Root "%cd%" -KeepDays "%KEEP_DAYS%"
) else (
  %PS_CMD% -NoProfile -ExecutionPolicy Bypass -File "tools\cleanup_runtime_outputs.ps1" -Root "%cd%" %PREVIEW_ARGS%
)

if errorlevel 1 (
  echo.
  echo [ERROR] Cleanup helper exited with errorlevel=%errorlevel%.
  echo.
  pause
  exit /b %errorlevel%
)

echo.
echo Done.
echo.
pause
exit /b 0

:err_cd
echo [ERROR] Failed to cd to script directory.
echo.
pause
exit /b 1

endlocal
