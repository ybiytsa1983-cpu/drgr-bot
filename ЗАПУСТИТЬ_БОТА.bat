@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

title drgr-bot - Запуск

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo.
echo +============================================+
echo ^|       drgr-bot  -  Запуск                  ^|
echo +============================================+
echo.

if not exist "%SCRIPT_DIR%bot.py" goto :FOLDER_MISSING
if not exist "%SCRIPT_DIR%vm\server.py" goto :FOLDER_MISSING
goto :FOLDER_OK

:FOLDER_MISSING
echo  [ОШИБКА] Папка проекта не найдена или повреждена!
echo.
echo  Переустановите одной командой PowerShell (Win+R -^> powershell):
echo.
echo    irm https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/install.ps1 ^| iex
echo.
pause
exit /b 1

:FOLDER_OK
echo  Проверка Python...
python --version > nul 2>&1
if errorlevel 1 (
    echo  [ОШИБКА] Python не установлен!
    echo  Скачайте: https://www.python.org/downloads/
    echo  (при установке отметьте "Add Python to PATH")
    pause
    exit /b 1
)
for /f "tokens=*" %%V in ('python --version 2^>^&1') do echo  Python: %%V
echo.

if not exist "%SCRIPT_DIR%.env" (
    echo  [ОШИБКА] Файл .env не найден!
    echo  Создайте файл .env : BOT_TOKEN=ваш_токен
    echo  Токен — у @BotFather в Telegram.
    pause
    exit /b 1
)
echo  Файл .env найден.
echo.

echo  Запуск VM-сервера (порт 5001)...
start "DRGR VM Server" cmd /k "title DRGR VM Server && cd /d %SCRIPT_DIR% && python vm/server.py"

timeout /t 3 /nobreak > nul

echo  Запуск Telegram-бота...
start "DRGR Telegram Bot" cmd /k "title DRGR Telegram Bot && cd /d %SCRIPT_DIR% && python bot.py"

echo.
echo +============================================+
echo ^|         Запуск выполнен успешно!           ^|
echo +============================================+
echo.
echo  Веб-интерфейс VM: http://localhost:5001
echo.
echo  Для остановки -- закройте оба окна.
echo  Для обновления -- запустите ОБНОВИТЬ.bat
echo.
pause
