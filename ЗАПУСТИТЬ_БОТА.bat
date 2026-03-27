@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

title drgr-bot - Запуск

:: ── Определяем папку скрипта ────────────────────────────────────────────
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo.
echo +============================================+
echo ^|       drgr-bot  -  Запуск бота и VM        ^|
echo +============================================+
echo.

:: ── Проверка: находимся ли мы в правильной папке ─────────────────────────
if not exist "%SCRIPT_DIR%bot.py" goto :FOLDER_MISSING
if not exist "%SCRIPT_DIR%vm\server.py" goto :FOLDER_MISSING
goto :FOLDER_OK

:FOLDER_MISSING
echo  [ОШИБКА] Папка проекта не найдена или повреждена!
echo.
echo  Ожидается папка: %SCRIPT_DIR%
echo  В ней должны быть: bot.py, vm\server.py
echo.
set "INSTALL_BAT=%USERPROFILE%\Desktop\drgr-bot\УСТАНОВИТЬ.bat"
if exist "!INSTALL_BAT!" (
    echo  Найден УСТАНОВИТЬ.bat на рабочем столе. Запускаем...
    call "!INSTALL_BAT!"
    exit /b
)
echo  Скачайте УСТАНОВИТЬ.bat с GitHub и запустите его:
echo    https://github.com/ybiytsa1983-cpu/drgr-bot/raw/main/УСТАНОВИТЬ.bat
echo.
pause
exit /b 1

:FOLDER_OK

:: ── Проверка Python ───────────────────────────────────────────────────────
echo  [1/5] Проверка Python...
python --version > nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ОШИБКА] Python не установлен!
    echo.
    echo  Установите Python 3.10+ со страницы:
    echo    https://www.python.org/downloads/
    echo  Обязательно отметьте "Add Python to PATH" при установке.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%V in ('python --version 2^>^&1') do echo  Найден: %%V
echo.

:: ── Обновление из GitHub ──────────────────────────────────────────────────
echo  [2/5] Обновление из GitHub...
git --version > nul 2>&1
if errorlevel 1 (
    echo  [ПРЕДУПРЕЖДЕНИЕ] Git не найден. Пропускаем обновление.
    goto :SKIP_GIT
)

git fetch origin main > nul 2>&1
if errorlevel 1 (
    echo  [ПРЕДУПРЕЖДЕНИЕ] Нет доступа к GitHub. Запускаем текущую версию.
    goto :SKIP_GIT
)

git reset --hard origin/main > nul 2>&1
if errorlevel 1 (
    echo  [ПРЕДУПРЕЖДЕНИЕ] Не удалось применить обновления. Запускаем текущую версию.
    goto :SKIP_GIT
)

for /f "delims=" %%H in ('git rev-parse --short HEAD 2^>nul') do set "CUR_HASH=%%H"
echo  Обновлено до коммита: !CUR_HASH!

:SKIP_GIT
echo.

:: ── Установка зависимостей ────────────────────────────────────────────────
echo  [3/5] Установка/обновление зависимостей Python...
pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo.
    echo  [ПРЕДУПРЕЖДЕНИЕ] Некоторые пакеты не установились.
    echo  Попробуйте запустить вручную: pip install -r requirements.txt
    echo.
) else (
    echo  Зависимости установлены.
)
echo.

:: ── Проверка .env ─────────────────────────────────────────────────────────
echo  [4/5] Проверка файла .env...
if not exist "%SCRIPT_DIR%.env" (
    echo.
    echo  [ОШИБКА] Файл .env не найден!
    echo.
    echo  Создайте файл .env в папке %SCRIPT_DIR%
    echo  Содержимое файла:
    echo    BOT_TOKEN=ваш_токен_бота
    echo.
    echo  Токен можно получить у @BotFather в Telegram.
    echo.
    pause
    exit /b 1
)
echo  Файл .env найден.
echo.

:: ── Запуск VM и бота ─────────────────────────────────────────────────────
echo  [5/5] Запуск сервисов...
echo.

echo  Запуск VM сервера (порт 5000)...
start "DRGR VM Server" cmd /k "title DRGR VM Server && cd /d %SCRIPT_DIR% && python vm/server.py"

echo  Ожидание запуска VM (3 сек)...
timeout /t 3 /nobreak > nul

echo  Запуск Telegram бота...
start "DRGR Telegram Bot" cmd /k "title DRGR Telegram Bot && cd /d %SCRIPT_DIR% && python bot.py"

echo.
echo +============================================+
echo ^|         Запуск выполнен успешно!           ^|
echo +============================================+
echo.
echo  Открыто 2 окна:
echo    - "DRGR VM Server"    — веб-сервер
echo    - "DRGR Telegram Bot" — Telegram бот
echo.
echo  Веб-интерфейс VM: http://localhost:5000
echo.
echo  Для остановки — закройте оба окна.
echo  Для обновления — запустите ОБНОВИТЬ.bat
echo.
pause
