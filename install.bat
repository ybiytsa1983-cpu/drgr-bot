@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

REM ============================================================
REM  install.bat  —  Установка drgr-bot
REM  Скачайте этот файл и запустите — он сделает всё сам:
REM    1. Клонирует репозиторий на Рабочий стол
REM    2. Устанавливает зависимости Python
REM    3. Запускает VM-сервер и открывает браузер
REM ============================================================

title drgr-bot - Установка

echo.
echo  +--------------------------------------------------+
echo  ^|       drgr-bot  —  Установка                    ^|
echo  +--------------------------------------------------+
echo.

REM -- Целевая папка ------------------------------------------------
set "DEST=%USERPROFILE%\Desktop\drgr-bot"
set "REPO=https://github.com/ybiytsa1983-cpu/drgr-bot.git"

REM -- Если запущен из папки репозитория — просто запускаем vm.ps1 --
if exist "%~dp0vm\server.py" (
    echo  Репозиторий найден рядом. Запуск...
    if exist "%~dp0vm.ps1" (
        powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0vm.ps1"
    ) else (
        powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
    )
    goto :EOF
)

REM -- Проверка Python ---------------------------------------------
echo  [1/5] Проверка Python...
python --version > nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ОШИБКА] Python не найден!
    echo.
    echo  Установите Python 3.10 или позже:
    echo    https://www.python.org/downloads/
    echo.
    echo  При установке отметьте "Add Python to PATH"
    echo  Затем запустите этот файл снова.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%V in ('python --version 2^>^&1') do echo  Найден: %%V
echo.

REM -- Проверка Git ------------------------------------------------
echo  [2/5] Проверка Git...
git --version > nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ОШИБКА] Git не найден!
    echo.
    echo  Установите Git для Windows:
    echo    https://git-scm.com/download/win
    echo.
    echo  Затем запустите этот файл снова.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%V in ('git --version 2^>^&1') do echo  Найден: %%V
echo.

REM -- Клонирование / обновление -----------------------------------
echo  [3/5] Клонирование/обновление репозитория...
if exist "%DEST%\.git" (
    echo  Папка уже существует, обновляем...
    cd /d "%DEST%"
    git pull origin main 2>&1
    if errorlevel 1 (
        echo  Предупреждение: не удалось обновить. Продолжаем...
    )
) else (
    echo  Клонируем в: %DEST%
    git clone "%REPO%" "%DEST%"
    if errorlevel 1 (
        echo.
        echo  [ОШИБКА] Не удалось клонировать репозиторий!
        echo  Проверьте подключение к интернету.
        echo.
        pause
        exit /b 1
    )
    cd /d "%DEST%"
)
echo.

REM -- Установка зависимостей Python ------------------------------
echo  [4/5] Установка зависимостей Python...
cd /d "%DEST%"

REM Создать venv если не существует
if not exist "%DEST%\.venv" (
    echo  Создание виртуального окружения .venv ...
    python -m venv "%DEST%\.venv"
)

REM Установить зависимости в venv
"%DEST%\.venv\Scripts\pip.exe" install --upgrade -r "%DEST%\requirements.txt" --quiet
if errorlevel 1 (
    echo  Предупреждение: некоторые зависимости не установились.
    echo  Попытка глобальной установки...
    pip install --upgrade -r "%DEST%\requirements.txt" --quiet
)
echo  Зависимости установлены.
echo.

REM -- Запуск VM-сервера -------------------------------------------
echo  [5/5] Запуск VM-сервера...
cd /d "%DEST%"

REM Запустить сервер в отдельном окне
start "drgr-bot VM Server" /min cmd /c ""%DEST%\.venv\Scripts\python.exe" vm\server.py > server.log 2>&1"

REM Ждать запуска (до 20 секунд)
echo  Ждём запуска сервера...
set "PORT=5000"
set /a TRIES=0
:WAIT_LOOP
set /a TRIES+=1
if %TRIES% GTR 20 goto :OPEN_BROWSER
timeout /t 1 /nobreak > nul 2>&1
powershell -NoProfile -Command "try { Invoke-WebRequest http://127.0.0.1:%PORT%/ping -UseBasicParsing -TimeoutSec 2 -EA Stop | Out-Null; exit 0 } catch { if ($_.Exception.Response) { exit 0 } else { exit 1 } }" > nul 2>&1
if not errorlevel 1 goto :OPEN_BROWSER
goto :WAIT_LOOP

:OPEN_BROWSER
echo.
echo  +--------------------------------------------------+
echo  ^|  Установка завершена!                           ^|
echo  ^|                                                  ^|
echo  ^|  Открываем: http://localhost:%PORT%              ^|
echo  ^|                                                  ^|
echo  ^|  В интерфейсе — вкладка "Настройки":            ^|
echo  ^|    * Введите токен Telegram-бота                 ^|
echo  ^|    * Нажмите "Сохранить токен"                   ^|
echo  ^|                                                  ^|
echo  ^|  Для следующих запусков используйте:            ^|
echo  ^|    %DEST%\start.bat                              ^|
echo  +--------------------------------------------------+
echo.
start http://localhost:%PORT%

echo  Нажмите любую клавишу для выхода из установщика.
echo  Сервер продолжит работу в фоне.
pause > nul
