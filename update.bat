@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

:: ═══════════════════════════════════════════════════════════════════
::  update.bat  —  Запускает update.ps1, спрашивает подтверждение,
::                    при отказе откатывает, при согласии перезапускает бот.
:: ═══════════════════════════════════════════════════════════════════

title drgr-bot - Update

echo.
echo ╔══════════════════════════════════════════════╗
echo ║      drgr-bot  —  Мастер обновления          ║
echo ╚══════════════════════════════════════════════╝
echo.

:: ── Определяем папку скрипта ────────────────────────────────────────
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

:: ── Сохраняем текущий хеш ДО обновления ─────────────────────────────
for /f "delims=" %%H in ('git rev-parse HEAD 2^>nul') do set "OLD_HASH=%%H"
if "%OLD_HASH%"=="" (
    echo  [ОШИБКА] Не удалось получить текущий коммит.
    echo           Убедитесь, что git установлен и папка является репозиторием.
    pause
    exit /b 1
)
echo  Текущий коммит: %OLD_HASH%
echo.

:: ── Запускаем update.ps1 (без автоперезапуска — мы сделаем его сами) ──
echo  Запуск update.ps1 — показ прогресса обновления...
echo  ─────────────────────────────────────────────────
powershell.exe -ExecutionPolicy Bypass -NoProfile ^
    -File "%SCRIPT_DIR%update.ps1" -SkipRestart

set "UPDATE_EXIT=%errorlevel%"
echo  ─────────────────────────────────────────────────

if %UPDATE_EXIT% NEQ 0 (
    echo.
    echo  [ОШИБКА] Обновление завершилось с кодом %UPDATE_EXIT%.
    echo           Откат был выполнен автоматически скриптом update.ps1.
    echo.
    pause
    exit /b %UPDATE_EXIT%
)

:: ── Получаем новый хеш ───────────────────────────────────────────────
for /f "delims=" %%H in ('git rev-parse HEAD 2^>nul') do set "NEW_HASH=%%H"

echo.
echo ╔══════════════════════════════════════════════╗
echo ║        Обновление выполнено успешно!         ║
echo ╠══════════════════════════════════════════════╣
echo ║  Старый коммит : %OLD_HASH:~0,12%...
echo ║  Новый коммит  : %NEW_HASH:~0,12%...
echo ╚══════════════════════════════════════════════╝
echo.

:: ── Спрашиваем пользователя ──────────────────────────────────────────
:ASK
set "CHOICE="
set /p "CHOICE= Вам нравится обновление? (да/нет): "

if /i "!CHOICE!"=="да"  goto :ACCEPT
if /i "!CHOICE!"=="yes" goto :ACCEPT
if /i "!CHOICE!"=="д"   goto :ACCEPT
if /i "!CHOICE!"=="y"   goto :ACCEPT
if /i "!CHOICE!"=="нет" goto :REJECT
if /i "!CHOICE!"=="no"  goto :REJECT
if /i "!CHOICE!"=="н"   goto :REJECT
if /i "!CHOICE!"=="n"   goto :REJECT

echo  Пожалуйста, введите "да" или "нет".
goto :ASK

:: ── Пользователь доволен — запускаем бот ─────────────────────────────
:ACCEPT
echo.
echo  Отлично! Запускаем bot.py...
call :STOP_BOT
timeout /t 2 /nobreak >nul
call :START_BOT
echo.
echo  Бот запущен. Окно закроется через 5 секунд.
timeout /t 5 /nobreak >nul
exit /b 0

:: ── Пользователь недоволен — откат и перезапуск ──────────────────────
:REJECT
echo.
echo  Выполняется откат к предыдущей версии (%OLD_HASH:~0,12%)...
git reset --hard %OLD_HASH%
if %errorlevel% NEQ 0 (
    echo  [ОШИБКА] Откат не удался!
    pause
    exit /b 1
)
echo  Откат выполнен.
echo.
echo  Восстанавливаем зависимости...
pip install -r requirements.txt
if %errorlevel% NEQ 0 (
    echo  [ПРЕДУПРЕЖДЕНИЕ] pip install завершился с ошибкой при откате.
)
echo.
echo  Запускаем bot.py с предыдущей версией...
call :STOP_BOT
timeout /t 2 /nobreak >nul
call :START_BOT
echo.
echo  Бот запущен с предыдущей версией. Окно закроется через 5 секунд.
timeout /t 5 /nobreak >nul
exit /b 0

:: ── Подпрограмма: остановить bot.py ─────────────────────────────────
:STOP_BOT
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
    "Get-CimInstance Win32_Process -Filter 'Name LIKE ''python%%''' | Where-Object { $_.CommandLine -match 'bot\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
goto :EOF

:: ── Подпрограмма: запустить bot.py ──────────────────────────────────
:START_BOT
if exist "%SCRIPT_DIR%bot.py" (
    start "drgr-bot" python "%SCRIPT_DIR%bot.py"
) else (
    echo  [ПРЕДУПРЕЖДЕНИЕ] bot.py не найден в %SCRIPT_DIR%
)
goto :EOF
