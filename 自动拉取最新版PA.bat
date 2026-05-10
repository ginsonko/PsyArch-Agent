@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
set "TARGET=%SCRIPT_DIR%PsyArch-Agent"
set "REPO=https://github.com/ginsonko/PsyArch-Agent.git"

echo [PA] PsyArch-Agent one-click clone/update
echo [PA] Repository: %REPO%
echo [PA] Target: %TARGET%
echo.

where git >nul 2>nul
if errorlevel 1 goto :err_git

if exist "%TARGET%\\.git" goto :update
if exist "%TARGET%" goto :err_exists

git clone "%REPO%" "%TARGET%"
if errorlevel 1 goto :err_clone
goto :done

:update
pushd "%TARGET%" || goto :err_cd
git pull --ff-only
set "CODE=%ERRORLEVEL%"
popd
if not "%CODE%"=="0" goto :err_pull
goto :done

:done
echo.
echo [PA] Done.
echo [PA] Next: open "%TARGET%" and run 依赖自检与安装.bat, then 快速启动观测台.bat.
pause
exit /b 0

:err_git
echo [PA] Git was not found. Please install Git for Windows first.
pause
exit /b 1

:err_exists
echo [PA] Target folder already exists but is not a Git checkout:
echo %TARGET%
echo Please rename or remove it, then retry.
pause
exit /b 1

:err_clone
echo [PA] git clone failed.
pause
exit /b 1

:err_cd
echo [PA] Failed to enter target directory:
echo %TARGET%
pause
exit /b 1

:err_pull
echo [PA] git pull failed. errorlevel=%CODE%
pause
exit /b %CODE%
