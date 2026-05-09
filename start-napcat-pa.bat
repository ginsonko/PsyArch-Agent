@echo off
setlocal EnableExtensions

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-napcat-pa.ps1" %*
set "CODE=%ERRORLEVEL%"
exit /b %CODE%
