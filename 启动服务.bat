@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo.
echo ============================================
echo       Infinite Canvas  v2.5.61
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

REM --- 2. No Python found - auto download embedded Python ---
echo.
echo [INFO] Python not found. Auto-downloading embedded Python...
echo.
goto :download_python

:download_python
set "PY_ZIP=%TEMP%\258-canvas-python-env.zip"
set "PY_URL=https://github.com/ken571571/258-Canvas/releases/latest/download/python-env.zip"

echo    Downloading from:
echo    %PY_URL%
echo    (about 50 MB, please wait...)
echo.

REM --- Try curl first (Windows 10 1803+ built-in) ---
where curl >nul 2>&1
if %errorlevel% equ 0 (
    echo    [1/2] Trying curl...
    curl -L -o "%PY_ZIP%" "%PY_URL%" --progress-bar
    if %errorlevel% equ 0 (
        if exist "%PY_ZIP%" (
            echo    [OK] Download complete
            goto :extract_python
        )
    )
    echo    [WARN] curl download failed, trying PowerShell...
)

REM --- Fallback: PowerShell Invoke-WebRequest ---
echo    [2/2] Trying PowerShell...
powershell -Command "try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; $ProgressPreference = 'SilentlyContinue'; Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%PY_ZIP%' -UseBasicParsing } catch { Write-Host $_.Exception.Message; exit 1 }"
if %errorlevel% equ 0 (
    if exist "%PY_ZIP%" (
        echo    [OK] Download complete
        goto :extract_python
    )
)

echo.
echo [ERROR] Auto-download failed.
echo.
echo    Please manually download Python 3.10+ from:
echo      https://www.python.org/downloads/
echo    Remember to check "Add Python to PATH" during install.
echo    Then run this script again.
echo.
pause
exit /b 1

:extract_python
echo.
echo    Extracting Python environment...
echo    (this may take a moment...)
echo.

REM --- Create python directory and extract ---
if not exist "%~dp0python" mkdir "%~dp0python"

powershell -Command "try { Expand-Archive -Path '%PY_ZIP%' -DestinationPath '%~dp0python' -Force } catch { Write-Host $_.Exception.Message; exit 1 }"
if %errorlevel% neq 0 (
    echo [ERROR] Extraction failed.
    echo    Please install Python 3.10+ manually:
echo      https://www.python.org/downloads/
    pause
    exit /b 1
)

REM --- Cleanup zip ---
del "%PY_ZIP%" >nul 2>&1

REM --- Verify ---
if not exist "%~dp0python\python.exe" (
    echo [ERROR] Python extraction incomplete - python.exe not found.
    echo    Please install Python 3.10+ manually:
echo      https://www.python.org/downloads/
    pause
    exit /b 1
)

echo    [OK] Python environment ready
set "PYEXE=%~dp0python\python.exe"

:check_venv
echo    Python: %PYEXE%

REM --- 3. First-run: install dependencies (only for system Python, not embedded) ---
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

REM --- 4. Firewall ---
netsh advfirewall firewall add rule name="InfiniteCanvas 3571" dir=in action=allow protocol=tcp localport=3571 >nul 2>&1

REM --- 5. Kill previous instance ---
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3571.*LISTENING" 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)

REM --- 6. Auto-open browser ---
start /b cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:3571"

REM --- 7. Start ---
call "%PYEXE%" run.py

pause
