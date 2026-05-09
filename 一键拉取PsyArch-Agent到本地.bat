@echo off
setlocal EnableExtensions

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\clone_psyarch_agent.ps1" %*
set "CODE=%ERRORLEVEL%"

echo.
if not "%CODE%"=="0" (
  echo [PA] PsyArch-Agent clone/update failed. errorlevel=%CODE%
) else (
  echo [PA] PsyArch-Agent clone/update finished.
)
pause
exit /b %CODE%
