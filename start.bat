@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

REM ============================================================
REM  start.bat  —  Запуск drgr-bot VM + браузер
REM  Запустите из папки репозитория (или с Рабочего стола).
REM  Открывает http://localhost:5000 автоматически.
REM ============================================================

title drgr-bot - Запуск

REM -- Найти папку репозитория -----------------------------------
set "REPO_DIR=%~dp0"
if not exist "%REPO_DIR%vm\server.py" (
    REM Может быть на рабочем столе
    set "REPO_DIR=%USERPROFILE%\Desktop\drgr-bot\"
)
if not exist "%REPO_DIR%vm\server.py" (
    echo.
    echo  [ОШИБКА] Не найден vm\server.py !
    echo  Сначала запустите install.bat для установки.
    echo.
    pause
    exit /b 1
)

cd /d "%REPO_DIR%"

REM -- Если есть vm.ps1 — запускаем через PowerShell (лучше) -----
if exist "%REPO_DIR%vm.ps1" (
    echo  Запуск через vm.ps1...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%REPO_DIR%vm.ps1"
    exit /b
)

REM -- Fallback: запуск Python напрямую --------------------------
echo.
echo  +--------------------------------------------------+
echo  ^|    drgr-bot VM  — Запуск                        ^|
echo  +--------------------------------------------------+
echo.

set "PORT=5000"

REM Найти Python (venv или системный)
set "PYTHON="
if exist "%REPO_DIR%.venv\Scripts\python.exe" (
    set "PYTHON=%REPO_DIR%.venv\Scripts\python.exe"
) else (
    python --version > nul 2>&1
    if not errorlevel 1 set "PYTHON=python"
)
if "%PYTHON%"=="" (
    echo  [ОШИБКА] Python не найден!
    echo  Запустите install.bat для установки.
    pause
    exit /b 1
)

REM Проверить, не запущен ли сервер
netstat -an 2>nul | find ":%PORT% " | find "LISTEN" > nul 2>&1
if not errorlevel 1 (
    echo  Сервер уже запущен на порту %PORT%
    echo  Открываем браузер...
    start http://localhost:%PORT%
    exit /b
)

REM Запустить Flask сервер в фоне
echo  Запуск Flask сервера на порту %PORT% ...
set "VM_PORT=%PORT%"
start /b "" %PYTHON% vm\server.py > server.log 2>&1

REM Ждать запуска (до 20 секунд)
echo  Ждём запуска сервера...
set /a TRIES=0
:WAIT_LOOP
set /a TRIES+=1
if %TRIES% GTR 20 goto :TIMEOUT
timeout /t 1 /nobreak > nul 2>&1
powershell -NoProfile -Command "try { Invoke-WebRequest http://127.0.0.1:%PORT%/ping -UseBasicParsing -TimeoutSec 2 -EA Stop | Out-Null; exit 0 } catch { if ($_.Exception.Response) { exit 0 } else { exit 1 } }" > nul 2>&1
if not errorlevel 1 goto :READY
goto :WAIT_LOOP

:TIMEOUT
echo  [ПРЕДУПРЕЖДЕНИЕ] Сервер не ответил за 20 сек.
echo  Проверьте server.log на ошибки.

:READY
echo  Сервер запущен!
echo.
echo  +--------------------------------------------------+
echo  ^|  Открываем: http://localhost:%PORT%              ^|
echo  ^|                                                  ^|
echo  ^|  Вкладка Настройки — введите токен бота TG      ^|
echo  +--------------------------------------------------+
echo.
start http://localhost:%PORT%

echo  Нажмите Ctrl+C для остановки сервера.
echo  Или закройте это окно.
echo.
pause
