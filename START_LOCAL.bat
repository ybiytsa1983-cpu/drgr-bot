@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ======================================
echo   DRGR BOT + VM Server (LOCAL)
echo ======================================
echo.

REM Проверка Python
python --version > nul 2>&1
if errorlevel 1 (
    echo [X] Python not found! Install Python 3.10+
    pause
    exit /b 1
)

echo [OK] Python found
echo.

REM Обновление из GitHub (если Git есть)
git --version > nul 2>&1
if not errorlevel 1 (
    echo [*] Updating from GitHub...
    git fetch origin main 2>nul
    if not errorlevel 1 (
        git reset --hard origin/main 2>nul
    )
    echo.
)

REM Установка зависимостей
echo [*] Installing dependencies...
pip install --upgrade -r requirements.txt >nul 2>&1
if errorlevel 1 (
    echo [!] Some dependencies failed to install
)
echo.

REM Проверка .env файла
if not exist .env (
    echo [!] .env file not found
    echo     Bot will not auto-start.
    echo     Create .env via web UI (Settings tab)
    echo.
)

REM Запуск VM сервера
echo ======================================
echo   [START] VM Server launching...
echo   Web UI: http://localhost:5001
echo   Bot auto-starts if BOT_TOKEN is set
echo   Ctrl+C to stop
echo ======================================
echo.

python vm/server.py

echo.
echo Server stopped.
pause
