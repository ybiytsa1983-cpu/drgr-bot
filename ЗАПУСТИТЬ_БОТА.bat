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

REM Обновление из GitHub (пропускается если нет сети или git)
git --version > nul 2>&1
if errorlevel 1 (
    echo ⚠️ git не найден — пропускаю обновление
    goto :SKIP_UPDATE
)

echo 📥 Проверка обновлений из GitHub...
git fetch origin --quiet 2>nul
if errorlevel 1 (
    echo ⚠️ Нет связи с GitHub или репозиторий недоступен. Продолжаю с текущей версией...
    goto :SKIP_UPDATE
)

REM Обновляем только если есть новые коммиты
for /f %%i in ('git rev-parse HEAD') do set LOCAL=%%i
for /f %%i in ('git rev-parse @{u} 2^>nul') do set REMOTE=%%i
if "%LOCAL%"=="%REMOTE%" (
    echo ✅ Версия актуальна.
    goto :SKIP_UPDATE
)

echo 📦 Применяю обновления...
git reset --hard origin/main
if errorlevel 1 (
    echo ⚠️ Не удалось применить обновления. Продолжаю с текущей версией...
)

:SKIP_UPDATE
echo.

REM Установка зависимостей
echo 📦 Установка зависимостей...
pip install --upgrade -r requirements.txt --quiet
if errorlevel 1 (
    echo ⚠️ Некоторые зависимости не установились, но продолжаю...
)
echo.

REM Проверка .env файла
if not exist .env (
    echo ⚠️ Файл .env не найден!
    echo Создайте файл .env с содержимым из .env.example
    echo Минимум: BOT_TOKEN=ваш_токен
    if exist .env.example (
        echo.
        echo Содержимое .env.example:
        type .env.example
    )
    pause
    exit /b 1
)

echo ✅ Файл .env найден
echo.

REM Запуск VM в отдельном окне
echo 🟢 Запуск VM сервера (порт 5001)...
start "DRGR VM Server" cmd /k "cd /d %CD% && python vm/server.py"

REM Задержка 3 секунды для запуска VM
timeout /t 3 /nobreak > nul

REM Запуск бота
echo 🤖 Запуск Telegram бота...
start "DRGR Telegram Bot" cmd /k "cd /d %CD% && python bot.py"

echo.
echo ✅ Бот и VM запущены в отдельных окнах!
echo.
echo 📌 Для остановки закройте окна "DRGR VM Server" и "DRGR Telegram Bot"
echo 🌐 Веб-интерфейс VM: http://localhost:5001
echo 🔬 Раздел Исследование: http://localhost:5001  (вкладка 🔬)
echo.
pause
