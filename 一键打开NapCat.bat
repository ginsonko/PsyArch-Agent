@echo off
setlocal EnableExtensions

cd /d "%~dp0" || goto :err_cd

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-napcat-pa.ps1" %*
set "CODE=%ERRORLEVEL%"

echo.
if not "%CODE%"=="0" (
  echo [PA] NapCat launcher exited with errorlevel=%CODE%.
)
pause
exit /b %CODE%

:err_cd
echo [PA] Failed to enter script directory.
pause
exit /b 1

