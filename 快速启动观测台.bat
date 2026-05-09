@echo off
setlocal EnableExtensions

cd /d "%~dp0"

echo ======================================
echo          Start Observatory
echo ======================================
echo Current directory: %cd%
echo.

set "PY_CMD="
set "PY_ARGS="

if exist ".venv\\Scripts\\python.exe" (
  set "PY_CMD=.venv\\Scripts\\python.exe"
) else (
  echo [WARN] .venv not found. It is recommended to run the dependency installer first.
  echo.

  where py >nul 2>nul
  if %errorlevel%==0 (
    set "PY_CMD=py"
    set "PY_ARGS=-3"
  ) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
      set "PY_CMD=python"
    )
  )
)

if "%PY_CMD%"=="" (
  echo [ERROR] Python not found.
  echo Please install Python 3.10+ and ensure it is on PATH.
  echo.
  pause
  exit /b 1
)

echo Running: %PY_CMD% %PY_ARGS% -m observatory
echo.
echo [INFO] Backend is starting, please wait...
echo.
%PY_CMD% %PY_ARGS% -m observatory

if %errorlevel% neq 0 (
  echo.
  echo [ERROR] Observatory exited with errorlevel=%errorlevel%.
  echo.
  pause
  exit /b %errorlevel%
)

echo.
echo ======================================
echo           Observatory End
echo ======================================
pause

endlocal


