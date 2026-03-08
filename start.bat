@echo off
REM start.bat — ONE command to launch Code VM on Windows.
REM
REM   First launch:  installs everything automatically, then opens the editor.
REM   Later launches: opens the editor immediately (no reinstall).
REM
REM Usage:
REM   Double-click this file in Explorer
REM   OR in PowerShell / cmd:   .\start.bat

cd /d "%~dp0"

REM ── First-time setup if .venv is missing ──────────────────────────────────
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo  ╔═══════════════════════════════════════════════════════╗
    echo  ║  Code VM — первый запуск, выполняется установка...   ║
    echo  ║  Подождите ~1-2 минуты. Окно закроется само.         ║
    echo  ╚═══════════════════════════════════════════════════════╝
    echo.
    python --version >nul 2>&1
    if errorlevel 1 (
        echo  [ОШИБКА] Python не найден.
        echo.
        echo  Установите Python 3.8+ с сайта:
        echo    https://www.python.org/downloads/
        echo.
        echo  ВАЖНО: при установке поставьте галочку "Add Python to PATH"
        echo.
        pause
        exit /b 1
    )
    python -m venv .venv
    .venv\Scripts\pip install flask requests --quiet
    if exist "requirements.txt" (
        .venv\Scripts\pip install -r requirements.txt --quiet 2>nul
    )
    echo  [OK] Установка завершена.
    echo.
)

REM ── Launch the VM ─────────────────────────────────────────────────────────
call "%~dp0vm\start_vm.bat"
