@echo off
setlocal EnableExtensions

cd /d "%~dp0" || goto :err_cd

echo ======================================
echo   AP Prototype - Dependency Check
echo ======================================
echo Current directory: %cd%
echo.

if not exist "requirements.txt" goto :err_requirements

if exist ".venv\\Scripts\\python.exe" goto :have_venv

set "SYS_PY_CMD="
set "SYS_PY_ARGS="

where py >nul 2>nul
if not errorlevel 1 (
  set "SYS_PY_CMD=py"
  set "SYS_PY_ARGS=-3"
  goto :create_venv
)

where python >nul 2>nul
if not errorlevel 1 (
  set "SYS_PY_CMD=python"
  goto :create_venv
)

goto :err_python

:create_venv
echo Creating venv: .venv
%SYS_PY_CMD% %SYS_PY_ARGS% -m venv .venv
if errorlevel 1 goto :err_venv

:have_venv
set "PY=.venv\\Scripts\\python.exe"

echo Using venv python: %PY%
%PY% --version
if errorlevel 1 goto :err_venv_python

echo.
echo Upgrading pip...
%PY% -m pip install -U pip
if errorlevel 1 goto :err_pip

echo.
echo Installing dependencies: requirements.txt
%PY% -m pip install -r requirements.txt
if errorlevel 1 goto :err_install

echo.
echo Optional import checks:
%PY% -c "import yaml; print('PyYAML OK')" >nul 2>nul
if errorlevel 1 (
  echo - PyYAML: NOT FOUND
) else (
  echo - PyYAML: OK
)

%PY% -c "import jieba; print('jieba OK')" >nul 2>nul
if errorlevel 1 (
  echo - jieba: NOT FOUND (the system will auto-disable jieba at runtime)
) else (
  echo - jieba: OK
)

echo.
echo ======================================
echo Done.
echo Next step: run the Observatory launcher.
echo ======================================
echo.
pause
exit /b 0

:err_cd
echo [ERROR] Failed to cd to script directory.
echo.
pause
exit /b 1

:err_requirements
echo [ERROR] requirements.txt not found.
echo.
pause
exit /b 1

:err_python
echo [ERROR] Python not found.
echo Please install Python 3.10+ and ensure it is on PATH.
echo.
pause
exit /b 1

:err_venv
echo.
echo [ERROR] Failed to create venv: .venv
echo.
pause
exit /b 1

:err_venv_python
echo.
echo [ERROR] venv python is not usable: %PY%
echo.
pause
exit /b 1

:err_pip
echo.
echo [ERROR] Failed to upgrade pip.
echo.
pause
exit /b 1

:err_install
echo.
echo [ERROR] pip install failed.
echo Tips:
echo - Check network / proxy / firewall.
echo - Retry in a terminal:
echo   %PY% -m pip install -r requirements.txt
echo.
pause
exit /b 1

endlocal


