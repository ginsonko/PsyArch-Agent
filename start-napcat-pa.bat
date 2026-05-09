@echo off
setlocal EnableExtensions

cd /d "%~dp0" || goto :err_cd

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-napcat-pa.ps1" %*
exit /b %ERRORLEVEL%

:err_cd
echo [PA] Failed to enter script directory.
pause
exit /b 1

