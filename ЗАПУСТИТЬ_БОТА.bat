@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ======================================
echo   DRGR BOT + VM Server
echo ======================================
echo.

REM Проверка Python
python --version > nul 2>&1
if errorlevel 1 (
    echo ❌ Python не установлен! Установите Python 3.10+
    pause
    exit /b 1
)

echo ✅ Python найден
echo.

REM Обновление из GitHub (если Git есть)
git --version > nul 2>&1
if not errorlevel 1 (
    echo 📥 Обновление из GitHub...
    git fetch origin main 2>nul
    if not errorlevel 1 (
        git reset --hard origin/main 2>nul
    )
    echo.
)

REM Установка зависимостей
echo 📦 Установка зависимостей...
pip install --upgrade -r requirements.txt >nul 2>&1
if errorlevel 1 (
    echo ⚠️ Некоторые зависимости не установились
)
echo.

REM Проверка .env файла
if not exist .env (
    echo ⚠️ Файл .env не найден
    echo    Бот не запустится автоматически.
    echo    Создайте .env через веб-интерфейс ^(Настройки^)
    echo.
)

REM Запуск VM сервера (бот запускается автоматически из сервера если BOT_TOKEN задан)
echo ======================================
echo   🟢 Запуск VM сервера...
echo   📌 Веб-интерфейс: http://localhost:5000
echo   📌 Бот автозапустится если BOT_TOKEN задан
echo   📌 Ctrl+C — остановка
echo ======================================
echo.

python vm/server.py

echo.
echo Сервер остановлен.
pause
