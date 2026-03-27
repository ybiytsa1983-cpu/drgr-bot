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

echo �� Применяю обновления...
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

REM Запуск VM сервера (бот запускается автоматически изнутри через расширение)
echo 🟢 Запуск VM сервера (порт 5001)...
echo 📌 Веб-интерфейс: http://localhost:5001
echo 📌 Токен бота вводится в расширении: ⚙ Настройки -^> BOT_TOKEN
echo 📌 Для остановки нажмите Ctrl+C
echo.
python vm/server.py
