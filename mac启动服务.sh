#!/bin/bash
# macOS 启动脚本 — 258 无限画布
# 用法：bash mac启动服务.sh  或  ./mac启动服务.sh（需先 chmod +x）

cd "$(dirname "$0")"

# --- Banner: version read live from VERSION file ---
CANVAS_VER="dev"
if [ -f "./VERSION" ]; then
    CANVAS_VER=$(head -1 ./VERSION)
fi

echo ""
echo "============================================"
echo "      Infinite Canvas  v${CANVAS_VER}"
echo "      258-Canvas / github.com/ken571571"
echo "============================================"
echo ""

# --- 1. Find Python 3 ---
PYEXE=""
if command -v python3 &> /dev/null; then
    PYEXE="python3"
    echo "[OK] Using system Python3"
elif command -v python &> /dev/null; then
    PYEXE="python"
    echo "[OK] Using system Python"
else
    echo ""
    echo "[ERROR] Python not found."
    echo "   Please install Python 3.10+:"
    echo "     brew install python@3.10"
    echo "   Or download from: https://www.python.org/downloads/"
    echo ""
    read -p "Press Enter to exit..."
    exit 1
fi

echo "   Python: $($PYEXE --version 2>&1)"

# --- 2. First-run: install dependencies ---
if [ ! -f ./.venv_installed ]; then
    echo ""
    echo "[SETUP] First run - installing dependencies..."
    $PYEXE -m pip install -r requirements.txt --quiet
    if [ $? -eq 0 ]; then
        touch ./.venv_installed
        echo "[OK] Dependencies installed"
    else
        echo "[WARN] Some dependencies failed, trying to start anyway..."
    fi
fi

echo ""
echo "  Starting server..."
echo "  URL: http://127.0.0.1:3571"
echo "  Press Ctrl+C to stop"
echo "============================================"
echo ""

# --- 3. Kill previous instance on port 3571 ---
PREV_PID=$(lsof -ti:3571 2>/dev/null)
if [ -n "$PREV_PID" ]; then
    echo "[INFO] Stopping previous instance (PID: $PREV_PID)..."
    kill -9 $PREV_PID 2>/dev/null
fi

# --- 4. Auto-open browser (after 3 seconds) ---
(sleep 3 && open "http://127.0.0.1:3571") &

# --- 5. Start ---
$PYEXE run.py

# Keep terminal open on exit
read -p "Press Enter to exit..."
