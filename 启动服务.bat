@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal enabledelayedexpansion

echo.
echo ============================================
echo       Infinite Canvas  v2.5.54
echo       258-Canvas / github.com/ken571571
echo ============================================
echo.

REM ——— 1. 找到可用的 Python ———
set PYEXE=
if exist "%~dp0python\python.exe" (
    set "PYEXE=%~dp0python\python.exe"
    echo [OK] 使用内置 Python 运行时
) else (
    where python >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYEXE=python"
        echo [OK] 使用系统 Python
    ) else (
        where python3 >nul 2>&1
        if !errorlevel! equ 0 (
            set "PYEXE=python3"
            echo [OK] 使用系统 Python3
        )
    )
)

if "!PYEXE!"=="" (
    echo.
    echo [ERROR] 未找到 Python，请先安装 Python 3.10+
    echo         下载地址：https://www.python.org/downloads/
    echo         安装时请勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

echo    Python: !PYEXE!

REM ——— 2. 首次运行自动安装依赖 ———
if not exist "%~dp0.venv_installed" (
    echo.
    echo [SETUP] 首次运行，正在安装依赖...
    "!PYEXE!" -m pip install -r requirements.txt --quiet
    if !errorlevel! equ 0 (
        type nul > "%~dp0.venv_installed"
        echo [OK] 依赖安装完成
    ) else (
        echo [WARN] 部分依赖安装失败，尝试继续启动...
    )
)

echo.
echo   启动服务...
echo   URL: http://127.0.0.1:3571
echo   Press Ctrl+C to stop
echo ============================================
echo.

REM ——— 3. 防火墙规则 ———
netsh advfirewall firewall add rule name="InfiniteCanvas 3571" dir=in action=allow protocol=tcp localport=3571 >nul 2>&1

REM ——— 4. 释放被占用的端口 ———
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3571.*LISTENING" 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)

REM ——— 5. 延迟 3 秒后自动打开浏览器 ———
start /b cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:3571"

REM ——— 6. 启动服务 ———
"!PYEXE!" run.py

pause
