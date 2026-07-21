@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Valo Community Native Launcher

echo.
echo ============================================================
echo   Valo Community Edition - Native Windows Launcher
echo ============================================================
echo.

if not exist "requirements.txt" (
  echo ERROR: requirements.txt was not found.
  echo Run this file from the root of the complete repository.
  pause
  exit /b 1
)

if not exist "app\main.py" (
  echo ERROR: app\main.py was not found.
  pause
  exit /b 1
)

if not exist "web\package.json" (
  echo ERROR: web\package.json was not found.
  pause
  exit /b 1
)

where py >nul 2>&1
if not errorlevel 1 (
  set "PYTHON_CMD=py -3"
) else (
  where python >nul 2>&1
  if errorlevel 1 (
    echo ERROR: Python 3 was not found.
    echo Install Python 3 and select Add Python to PATH.
    pause
    exit /b 1
  )
  set "PYTHON_CMD=python"
)

where node >nul 2>&1
if errorlevel 1 (
  echo ERROR: Node.js was not found.
  echo Install the current Node.js LTS release.
  pause
  exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
  echo ERROR: npm was not found.
  pause
  exit /b 1
)

if not exist ".env" if exist ".env.example" copy /Y ".env.example" ".env" >nul

if not exist ".venv\Scripts\python.exe" (
  echo Creating Python virtual environment...
  %PYTHON_CMD% -m venv ".venv"
  if errorlevel 1 goto :fail
)

echo Installing Python dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo Installing web dependencies...
pushd web
call npm install
if errorlevel 1 (
  popd
  goto :fail
)
popd

set "APP_EDITION=community"
set "APP_ENFORCEMENT_MODE=monitor"
set "APP_LOG_LEVEL=INFO"
set "APP_RATE_LIMIT=100/minute"
set "APP_CORRELATION_ENGINE_ENABLED=false"
set "APP_EXECUTIVE_METRICS_ENABLED=false"
set "APP_REPORTS_ENABLED=false"
set "APP_PLAYBOOKS_ENABLED=false"
set "APP_LEARNING_LOOP_ENABLED=false"

echo.
echo Starting Valo API...
start "Valo Community API" cmd /k "cd /d "%CD%" ^&^& "%CD%\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000"

echo Waiting for API health...
set /a tries=0
:wait_api
timeout /t 2 /nobreak >nul
curl.exe -sf "http://localhost:8000/health" >nul 2>&1
if not errorlevel 1 goto :api_ready
set /a tries+=1
if %tries% geq 30 goto :api_fail
goto :wait_api

:api_ready
echo Starting Valo Web UI...
start "Valo Community Web" cmd /k "cd /d "%CD%\web" ^&^& set VITE_BACKEND_URL=http://localhost:8000 ^&^& set VITE_VALO_EDITION=community ^&^& npm run dev -- --host 0.0.0.0 --port 8080"

echo Waiting for Web UI...
set /a webtries=0
:wait_web
timeout /t 2 /nobreak >nul
curl.exe -sf "http://localhost:8080" >nul 2>&1
if not errorlevel 1 goto :web_ready
set /a webtries+=1
if %webtries% geq 30 goto :web_fail
goto :wait_web

:web_ready
start "" "http://localhost:8080/demo"
echo.
echo Valo Community is ready.
echo Demo: http://localhost:8080/demo
echo API:  http://localhost:8000/docs
echo.
exit /b 0

:api_fail
echo ERROR: The API did not start. Review the Valo Community API window.
goto :fail

:web_fail
echo ERROR: The Web UI did not start. Review the Valo Community Web window.
goto :fail

:fail
echo.
echo Valo could not be started. Review the error above.
pause
exit /b 1
