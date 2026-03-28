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

if not exist "%SCRIPT_DIR%vm\server.py" goto :FOLDER_MISSING
goto :FOLDER_OK

:FOLDER_MISSING
echo  [ОШИБКА] Папка проекта не найдена или повреждена!
echo.
echo  Переустановите одной командой PowerShell (Win+R -^> powershell):
echo.
echo    irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/start_vm.ps1?%%RANDOM%%" ^| iex
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
    echo  [!] Файл .env не найден. Добавьте BOT_TOKEN в веб-интерфейсе после запуска.
    echo.
)

echo  Запуск VM-сервера (порт 5001)...
start "DRGR VM Server" cmd /k "title DRGR VM Server && cd /d ""%SCRIPT_DIR%"" && python ""vm/server.py"""

echo.
echo +============================================+
echo ^|         VM-сервер запущен!                 ^|
echo +============================================+
echo.
echo  Веб-интерфейс: http://localhost:5001
echo  Бот запускается / останавливается из веб-интерфейса.
echo.
echo  Для остановки -- закройте окно VM-сервера.
echo  Для обновления -- запустите ОБНОВИТЬ.bat
echo.
pause
