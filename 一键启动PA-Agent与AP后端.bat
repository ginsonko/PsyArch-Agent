@echo off
setlocal EnableExtensions

set "REPO_DIR=%~dp0"
set "PY_CMD="
set "PY_ARGS="
set "PA_HOST=127.0.0.1"
set "PA_PORT=8765"
set "PA_URL=http://%PA_HOST%:%PA_PORT%/next/"

if not exist "%REPO_DIR%observatory\_web.py" (
  echo [PA] This launcher must be placed in the PsyArch-Agent repository root.
  echo [PA] Missing file:
  echo      %REPO_DIR%observatory\_web.py
  echo.
  pause
  exit /b 1
)

if exist "%REPO_DIR%.venv\Scripts\python.exe" (
  set "PY_CMD=%REPO_DIR%.venv\Scripts\python.exe"
) else (
  echo [PA] .venv not found. It is recommended to run dependency installer first.
  echo.

  where py >nul 2>nul
  if not errorlevel 1 (
    set "PY_CMD=py"
    set "PY_ARGS=-3"
  ) else (
    where python >nul 2>nul
    if not errorlevel 1 (
      set "PY_CMD=python"
    )
  )
)

if not defined PY_CMD (
  echo [PA] Python 3.10+ not found.
  echo [PA] Please install Python and run dependency installer first.
  echo.
  pause
  exit /b 1
)

echo ======================================
echo Start PA-Agent + AP Backend
echo ======================================
echo Repository: %REPO_DIR%
echo Python: %PY_CMD% %PY_ARGS%
echo URL: %PA_URL%
echo.

if /i "%~1"=="--dry-run" (
  echo [PA] Dry run only. No backend process will be started.
  echo [PA] Command:
  echo "%PY_CMD%" %PY_ARGS% -m observatory --mode web --no-browser --host %PA_HOST% --port %PA_PORT%
  echo.
  exit /b 0
)

start "PA Agent + AP Backend" /D "%REPO_DIR%" cmd /k ""%PY_CMD%" %PY_ARGS% -m observatory --mode web --no-browser --host %PA_HOST% --port %PA_PORT%"

echo [PA] Waiting 5 seconds for backend startup...
timeout /t 5 /nobreak >nul

start "" "%PA_URL%"

echo.
echo [PA] Done. If the browser did not open, visit:
echo %PA_URL%
echo.
pause

endlocal
