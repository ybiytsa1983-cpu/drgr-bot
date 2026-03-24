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

REM Создание виртуального окружения venv_bot (если отсутствует)
if not exist "%~dp0venv_bot\Scripts\python.exe" (
    echo 🐍 Создание виртуального окружения venv_bot...
    python -m venv "%~dp0venv_bot"
    if errorlevel 1 (
        echo ❌ Не удалось создать виртуальное окружение!
        pause
        exit /b 1
    )
    echo ✅ venv_bot создан
    echo.
)

REM Активация виртуального окружения venv_bot
echo 🔄 Активация venv_bot...
call "%~dp0venv_bot\Scripts\activate.bat"
echo ✅ venv_bot активирован
echo.

REM Обновление из GitHub
echo 📥 Обновление из GitHub...
git pull origin main
if errorlevel 1 (
    echo ⚠️ Не удалось обновить. Продолжаю с текущей версией...
)
echo.

REM Установка зависимостей в виртуальное окружение
echo 📦 Установка зависимостей в venv_bot...
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
start "DRGR VM Server" cmd /k "cd /d %CD% && call venv_bot\Scripts\activate.bat && python vm/server.py"

REM Задержка 3 секунды для запуска VM
timeout /t 3 /nobreak > nul

echo 🤖 Запуск Telegram бота...
start "DRGR Telegram Bot" cmd /k "cd /d %CD% && call venv_bot\Scripts\activate.bat && python bot.py"

echo.
echo ✅ Бот и VM запущены в отдельных окнах!
echo.
echo 📌 Для остановки закройте окна "DRGR VM Server" и "DRGR Telegram Bot"
echo 🌐 Веб-интерфейс VM: http://localhost:5000
echo.
pause
