@echo off
cd /d "%~dp0"

set "PYEXE=%~dp0python\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"

echo.
echo ============================================
echo       Infinite Canvas  v1.0
echo ============================================
echo.
echo   URL: http://127.0.0.1:3571
echo.
echo   Press Ctrl+C to stop
echo ============================================
echo.

REM Add firewall rule
netsh advfirewall firewall add rule name="InfiniteCanvas 3571" dir=in action=allow protocol=tcp localport=3571 >nul 2>&1

REM Kill any previous instance on port 3571
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3571.*LISTENING" 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)

REM Auto-open browser after 3s delay (server needs time to start)
start /b cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:3571"

REM Start server in same window
"%PYEXE%" run.py

pause
