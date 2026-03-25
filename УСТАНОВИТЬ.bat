@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

:: ═══════════════════════════════════════════════════════════════════
::  УСТАНОВИТЬ.bat  —  Первоначальная установка drgr-bot на Windows
::  Запустить ОДИН РАЗ на чистом компьютере.
::  Повторные обновления — через ОБНОВИТЬ.bat
:: ═══════════════════════════════════════════════════════════════════

title drgr-bot — Установка

echo.
echo ╔══════════════════════════════════════════════╗
echo ║       drgr-bot  —  Установка                 ║
echo ╚══════════════════════════════════════════════╝
echo.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

:: ── 1. Проверка Python ───────────────────────────────────────────────
echo [1/5] Проверка Python...
python --version >nul 2>&1
if %errorlevel% NEQ 0 (
    echo.
    echo  [ОШИБКА] Python не найден!
    echo.
    echo  Скачайте и установите Python 3.10+ с сайта:
    echo    https://www.python.org/downloads/
    echo.
    echo  ВАЖНО: При установке поставьте галочку "Add Python to PATH"
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%V in ('python --version 2^>^&1') do echo   Найден: %%V

:: ── 2. Проверка git ──────────────────────────────────────────────────
echo.
echo [2/5] Проверка git...
git --version >nul 2>&1
if %errorlevel% NEQ 0 (
    echo.
    echo  [ОШИБКА] git не найден!
    echo.
    echo  Скачайте и установите git с сайта:
    echo    https://git-scm.com/download/win
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%V in ('git --version 2^>^&1') do echo   Найден: %%V

:: ── 3. Установка зависимостей ────────────────────────────────────────
echo.
echo [3/5] Установка зависимостей Python (pip install)...
pip install -r "%SCRIPT_DIR%requirements.txt"
if %errorlevel% NEQ 0 (
    echo.
    echo  [ОШИБКА] pip install завершился с ошибкой.
    pause
    exit /b 1
)
echo   Зависимости установлены.

:: ── 4. Создание .env ─────────────────────────────────────────────────
echo.
echo [4/5] Настройка файла .env...
if exist "%SCRIPT_DIR%.env" (
    echo   Файл .env уже существует — пропускаем создание.
) else (
    if exist "%SCRIPT_DIR%.env.example" (
        copy "%SCRIPT_DIR%.env.example" "%SCRIPT_DIR%.env" >nul
        echo   Файл .env создан из шаблона .env.example
        echo.
        echo  ┌─────────────────────────────────────────────────────┐
        echo  │  ВАЖНО: Откройте файл .env и заполните:             │
        echo  │    BOT_TOKEN=       ← токен от @BotFather           │
        echo  │    HUGGINGFACE_API_KEY=  ← ключ с huggingface.co   │
        echo  └─────────────────────────────────────────────────────┘
        echo.
        echo  Нажмите любую клавишу — откроем .env в блокноте...
        pause >nul
        notepad "%SCRIPT_DIR%.env"
        echo.
        echo  После сохранения .env нажмите любую клавишу для продолжения...
        pause >nul
    ) else (
        echo  [ПРЕДУПРЕЖДЕНИЕ] Шаблон .env.example не найден.
        echo  Создайте .env вручную и укажите BOT_TOKEN и HUGGINGFACE_API_KEY.
        pause
        exit /b 1
    )
)

:: ── 5. Проверка токена и запуск ──────────────────────────────────────
echo.
echo [5/5] Запуск бота...

:: Проверяем что BOT_TOKEN заполнен
findstr /i "BOT_TOKEN=ВАШ_ТОКЕН_БОТА" "%SCRIPT_DIR%.env" >nul 2>&1
if %errorlevel% EQU 0 (
    echo.
    echo  [ОШИБКА] Токен бота не заполнен в .env !
    echo  Откройте .env и замените "ВАШ_ТОКЕН_БОТА" на реальный токен.
    echo.
    pause
    exit /b 1
)

findstr /i "HUGGINGFACE_API_KEY=ВАШ_КЛЮЧ_HUGGINGFACE" "%SCRIPT_DIR%.env" >nul 2>&1
if %errorlevel% EQU 0 (
    echo.
    echo  [ОШИБКА] Hugging Face ключ не заполнен в .env !
    echo  Откройте .env и замените "ВАШ_КЛЮЧ_HUGGINGFACE" на реальный ключ.
    echo.
    pause
    exit /b 1
)

if exist "%SCRIPT_DIR%bot.py" (
    start "drgr-bot" python "%SCRIPT_DIR%bot.py"
    echo.
    echo ╔══════════════════════════════════════════════╗
    echo ║      Установка завершена! Бот запущен.       ║
    echo ╠══════════════════════════════════════════════╣
    echo ║  Для обновления используйте ОБНОВИТЬ.bat     ║
    echo ╚══════════════════════════════════════════════╝
) else (
    echo  [ОШИБКА] bot.py не найден в %SCRIPT_DIR%
    pause
    exit /b 1
)

echo.
echo  Окно закроется через 10 секунд...
timeout /t 10 /nobreak >nul
exit /b 0
