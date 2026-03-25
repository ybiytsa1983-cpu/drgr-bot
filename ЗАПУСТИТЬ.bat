@echo off
chcp 65001 > nul
cd /d "%~dp0"
title drgr-bot

echo.
echo  ==========================================
echo   drgr-bot  -  Запуск
echo  ==========================================
echo.

REM -- Проверить Python ------------------------------------------
python --version > nul 2>&1
if errorlevel 1 (
    echo  ОШИБКА: Python не найден!
    echo.
    echo  Установите Python 3.10+:
    echo    https://www.python.org/downloads/
    echo.
    echo  Отметьте галочку "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

REM -- Установить зависимости если нет Flask ---------------------
python -c "import flask" > nul 2>&1
if errorlevel 1 (
    echo  Установка зависимостей (первый запуск)...
    pip install -r requirements.txt --quiet
    echo  Готово.
    echo.
)

REM -- Запустить сервер в отдельном окне -------------------------
echo  Запуск сервера...
start "drgr-bot Server" python vm\server.py

REM -- Подождать 4 секунды и открыть браузер ---------------------
echo  Открываем браузер через 4 секунды...
timeout /t 4 /nobreak > nul
start http://localhost:5000

echo.
echo  ==========================================
echo   Интерфейс: http://localhost:5000
echo.
echo   Для ввода токена бота:
echo   нажмите "Настройки" в верхнем меню
echo  ==========================================
echo.
echo  Нажмите любую клавишу для выхода.
echo  Сервер продолжит работу в фоне.
pause > nul
