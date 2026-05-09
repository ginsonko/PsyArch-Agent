@echo off
setlocal EnableExtensions

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\configure_napcat_pa.ps1" %*
set "CODE=%ERRORLEVEL%"

echo.
if not "%CODE%"=="0" (
  echo [PA] NapCat configure failed. errorlevel=%CODE%
) else (
  echo [PA] NapCat configure finished.
)
pause
exit /b %CODE%
