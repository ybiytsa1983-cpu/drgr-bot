@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ======================================
echo   🚀 ЗАПУСК DRGR BOT + VM
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

REM Обновление из GitHub
echo 📥 Обновление из GitHub...
git fetch origin main
if errorlevel 1 (
    echo ⚠️ Не удалось получить обновления. Продолжаю с текущей версией...
    goto :SKIP_RESET
)
git reset --hard origin/main
if errorlevel 1 (
    echo ⚠️ Не удалось применить обновления. Продолжаю с текущей версией...
)
:SKIP_RESET
echo.

REM Установка зависимостей
echo 📦 Установка зависимостей...
pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo ⚠️ Некоторые зависимости не установились
)
echo.

REM Проверка .env файла
if not exist .env (
    echo ⚠️ Файл .env не найден!
    echo Создайте файл .env с BOT_TOKEN=ваш_токен
    pause
    exit /b 1
)

echo ✅ Файл .env найден
echo.

REM Запуск бота и VM в разных окнах
echo 🟢 Запуск VM сервера...
start "DRGR VM Server" cmd /k "cd /d %CD% && python vm/server.py"

REM Задержка 3 секунды для запуска VM
timeout /t 3 /nobreak > nul

echo 🤖 Запуск Telegram бота...
start "DRGR Telegram Bot" cmd /k "cd /d %CD% && python bot.py"

echo.
echo ✅ Бот и VM запущены в отдельных окнах!
echo.
echo 📌 Для остановки закройте окна "DRGR VM Server" и "DRGR Telegram Bot"
echo 🌐 Веб-интерфейс VM: http://localhost:5001
echo.
pause
