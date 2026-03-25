@echo off
chcp 65001 > nul
title drgr-bot - Установка

echo.
echo  ==========================================
echo   drgr-bot  -  Установка
echo  ==========================================
echo.

REM -- Если уже в папке репозитория — просто запускаем ----------
if exist "%~dp0vm\server.py" (
    cd /d "%~dp0"
    goto :INSTALL_DEPS
)

REM -- Проверить Python -----------------------------------------
python --version > nul 2>&1
if errorlevel 1 (
    echo  ОШИБКА: Python не найден!
    echo.
    echo  Установите Python 3.10+:
    echo    https://www.python.org/downloads/
    echo.
    echo  Отметьте галочку "Add Python to PATH"
    pause
    exit /b 1
)

REM -- Проверить Git --------------------------------------------
git --version > nul 2>&1
if errorlevel 1 (
    echo  ОШИБКА: Git не найден!
    echo.
    echo  Установите Git:
    echo    https://git-scm.com/download/win
    pause
    exit /b 1
)

REM -- Клонировать репозиторий ----------------------------------
set "DEST=%USERPROFILE%\Desktop\drgr-bot"
set "REPO=https://github.com/ybiytsa1983-cpu/drgr-bot.git"

echo  Клонирование в: %DEST%
echo.

if exist "%DEST%\.git" (
    echo  Папка уже есть — обновляем...
    cd /d "%DEST%"
    git pull origin main 2>&1
) else (
    git clone "%REPO%" "%DEST%"
    if errorlevel 1 (
        echo.
        echo  ОШИБКА: Не удалось клонировать!
        echo  Проверьте интернет-соединение.
        pause
        exit /b 1
    )
    cd /d "%DEST%"
)
echo.

:INSTALL_DEPS
REM -- Установить зависимости -----------------------------------
echo  Установка зависимостей Python...
pip install -r requirements.txt --quiet
echo  Готово.
echo.

REM -- Запустить сервер -----------------------------------------
echo  Запуск сервера...
start "drgr-bot Server" python vm\server.py

echo  Открываем браузер через 4 секунды...
timeout /t 4 /nobreak > nul
start http://localhost:5000

echo.
echo  ==========================================
echo   Установка завершена!
echo.
echo   Интерфейс: http://localhost:5000
echo.
echo   Для ввода токена бота Telegram:
echo   нажмите "Настройки" в интерфейсе
echo  ==========================================
echo.
pause
