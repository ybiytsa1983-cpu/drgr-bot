@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ======================================
echo   DRGR BOT + VM Server + Local Comet
echo ======================================
echo.

REM Проверка Python
python --version > nul 2>&1
if errorlevel 1 (
    echo [X] Python не установлен! Установите Python 3.10+
    pause
    exit /b 1
)

echo [OK] Python найден
echo.

REM Обновление из GitHub (если Git есть)
git --version > nul 2>&1
if not errorlevel 1 (
    echo [*] Обновление из GitHub...
    git fetch origin main 2>nul
    if not errorlevel 1 (
        git reset --hard origin/main 2>nul
    )
    echo.
)

REM Установка Python-зависимостей
echo [*] Установка Python-зависимостей...
pip install --upgrade -r requirements.txt >nul 2>&1
if errorlevel 1 (
    echo [!] Некоторые Python-зависимости не установились
)
echo.

REM ── Local Comet Editor Server (Node.js) ──────────────────────────
set "COMET_READY=0"
node --version > nul 2>&1
if errorlevel 1 (
    echo [!] Node.js не найден — Local Comet Editor не запустится.
    echo     Установите Node.js 18+: https://nodejs.org/
    echo     VM-сервер запустится без него.
    echo.
) else (
    echo [OK] Node.js найден
    if exist "local-comet-patch\server\package.json" (
        echo [*] Установка Node.js зависимостей Local Comet...
        pushd "local-comet-patch\server"
        call npm install --silent >nul 2>&1
        if errorlevel 1 (
            echo [!] npm install не удался
            popd
        ) else (
            echo [*] Сборка Local Comet Server...
            call npm run build --silent >nul 2>&1
            if errorlevel 1 (
                echo [!] npm run build не удался
                popd
            ) else (
                popd
                set "COMET_READY=1"
                echo [OK] Local Comet Editor собран
            )
        )
    ) else (
        echo [!] local-comet-patch/server/package.json не найден
    )
    echo.
)

REM Проверка .env файла
if not exist .env (
    echo [!] Файл .env не найден
    echo     Бот не запустится автоматически.
    echo     Создайте .env через веб-интерфейс (Настройки)
    echo.
)

REM ── Запуск Local Comet Editor Server в отдельном окне ─────────────
if "%COMET_READY%"=="1" (
    echo [*] Запуск Local Comet Editor Server (порт 5052)...
    start "Local Comet Editor" /min cmd /c "cd /d "%~dp0local-comet-patch\server" && node dist\index.cjs"
    echo.
)

REM ── Запуск VM сервера ────────────────────────────────────────────
echo ======================================
echo   [START] Запуск VM сервера...
echo   VM:     http://localhost:5001
if "%COMET_READY%"=="1" (
echo   Editor: http://localhost:5052
)
echo   Бот автозапустится если BOT_TOKEN задан
echo   Ctrl+C — остановка
echo ======================================
echo.

python vm/server.py

echo.
echo Сервер остановлен.

REM Останавливаем Local Comet Editor если он запущен
if "%COMET_READY%"=="1" (
    taskkill /fi "WINDOWTITLE eq Local Comet Editor" >nul 2>&1
)
pause
