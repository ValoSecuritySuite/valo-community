@echo off
setlocal
echo Stopping Valo services on ports 8000 and 8080...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ports = 8000,8080; foreach ($port in $ports) { Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue } }"
echo Valo services stopped.
exit /b 0
