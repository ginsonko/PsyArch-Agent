@echo off
setlocal EnableExtensions

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\update_napcat.ps1" %*
set "CODE=%ERRORLEVEL%"

echo.
if not "%CODE%"=="0" (
  echo [PA] NapCat update failed. errorlevel=%CODE%
) else (
  echo [PA] NapCat update finished.
)
pause
exit /b %CODE%
