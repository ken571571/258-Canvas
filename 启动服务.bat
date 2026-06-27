@echo off
cd /d "%~dp0"

echo.
echo ============================================
echo       Infinite Canvas  v2.5.54
echo       258-Canvas / github.com/ken571571
echo ============================================
echo.

REM --- 1. Find Python ---
set PYEXE=
if exist "%~dp0python\python.exe" (
    set "PYEXE=%~dp0python\python.exe"
    echo [OK] Using embedded Python
    goto :check_venv
)

where python >nul 2>&1
if %errorlevel% equ 0 (
    set "PYEXE=python"
    echo [OK] Using system Python
    goto :check_venv
)

where python3 >nul 2>&1
if %errorlevel% equ 0 (
    set "PYEXE=python3"
    echo [OK] Using system Python3
    goto :check_venv
)

echo.
echo [ERROR] Python not found. Please install Python 3.10+
echo          https://www.python.org/downloads/
echo          Check "Add Python to PATH" during install.
echo.
pause
exit /b 1

:check_venv
echo    Python: %PYEXE%

REM --- 2. First-run: install dependencies (only for system Python, not embedded) ---
if "%PYEXE%"=="%~dp0python\python.exe" goto :start_server
if exist "%~dp0.venv_installed" goto :start_server

echo.
echo [SETUP] First run - installing dependencies...
call "%PYEXE%" -m pip install -r requirements.txt --quiet
if %errorlevel% equ 0 (
    type nul > "%~dp0.venv_installed"
    echo [OK] Dependencies installed
) else (
    echo [WARN] Some dependencies failed, trying to start anyway...
)

:start_server
echo.
echo   Starting server...
echo   URL: http://127.0.0.1:3571
echo   Press Ctrl+C to stop
echo ============================================
echo.

REM --- 3. Firewall ---
netsh advfirewall firewall add rule name="InfiniteCanvas 3571" dir=in action=allow protocol=tcp localport=3571 >nul 2>&1

REM --- 4. Kill previous instance ---
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3571.*LISTENING" 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)

REM --- 5. Auto-open browser ---
start /b cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:3571"

REM --- 6. Start ---
call "%PYEXE%" run.py

pause
