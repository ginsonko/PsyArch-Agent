@echo off
setlocal EnableExtensions

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-napcat-pa.ps1" %*
set "CODE=%ERRORLEVEL%"

echo.
if not "%CODE%"=="0" (
  echo [PA] NapCat launcher exited with errorlevel=%CODE%.
)
pause
exit /b %CODE%
