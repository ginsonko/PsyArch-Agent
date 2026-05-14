@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%" || exit /b 1

echo [PA] Repair library catalog
echo [PA] Working directory: %CD%
echo.

where python >nul 2>nul
if errorlevel 1 goto :err_python

python tools\repair_library_catalog.py
set "CODE=%ERRORLEVEL%"
echo.
if not "%CODE%"=="0" goto :err_repair

echo [PA] Done. You can restart PA and open the library page again.
pause
exit /b 0

:err_python
echo [PA] Python was not found. Please run 依赖自检与安装.bat first.
pause
exit /b 1

:err_repair
echo [PA] Repair failed. errorlevel=%CODE%
pause
exit /b %CODE%
