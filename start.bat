@echo off
setlocal EnableExtensions
REM One-command launcher for Valo Community Edition (Windows).
cd /d "%~dp0"

if not defined VALO_API_URL set "VALO_API_URL=http://localhost:8000"
if not defined VALO_UI_URL set "VALO_UI_URL=http://localhost:8080"

if exist ".env.example" if not exist ".env" (
  echo ==^> Creating .env from .env.example...
  copy /Y ".env.example" ".env" >nul
)

echo ==^> Starting Valo Community Edition (Docker)...
docker compose up --build -d
if errorlevel 1 (
  echo ERROR: docker compose failed. Is Docker Desktop running?
  exit /b 1
)

echo ==^> Waiting for API health...
set /a _tries=0
:wait_health
curl.exe -sf "%VALO_API_URL%/health" >nul 2>&1
if not errorlevel 1 goto healthy
set /a _tries+=1
if %_tries% geq 30 goto unhealthy
timeout /t 2 /nobreak >nul
goto wait_health

:unhealthy
echo ERROR: API did not become healthy at %VALO_API_URL%/health
exit /b 1

:healthy
echo.
echo Valo Community Edition is ready.
echo.
echo   Web UI                     %VALO_UI_URL%/
echo   API docs                   %VALO_API_URL%/docs
echo   Health check               %VALO_API_URL%/health
echo.
echo Stop:  docker compose down
echo Logs:  docker compose logs -f
echo.
endlocal
exit /b 0
