@echo off
REM start.bat -- ONE command to launch Code VM on Windows.
REM
REM   First launch:  installs everything automatically, then opens the editor.
REM   Later launches: opens the editor immediately (no reinstall).
REM
REM Usage:
REM   Double-click this file in Explorer
REM   OR in cmd.exe:  .\start.bat
REM   In PowerShell:  .\start.ps1   (recommended)

cd /d "%~dp0"

REM -- Auto-update from remote (silent, best-effort) ------------------------
git pull --ff-only --quiet >nul 2>&1

REM -- First-time setup if .venv is missing ---------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo  +-------------------------------------------------------+
    echo  ^|  Code VM - first launch, installing...               ^|
    echo  ^|  Please wait ~1-2 minutes.                           ^|
    echo  +-------------------------------------------------------+
    echo.
    python --version >nul 2>&1
    if errorlevel 1 (
        echo  [ERROR] Python not found.
        echo.
        echo  Install Python 3.8+ from:
        echo    https://www.python.org/downloads/
        echo.
        echo  IMPORTANT: check "Add Python to PATH" during installation.
        echo.
        pause
        exit /b 1
    )
    python -m venv .venv
    .venv\Scripts\pip install flask requests --quiet
    if exist "requirements.txt" (
        .venv\Scripts\pip install -r requirements.txt --quiet 2>nul
    )
    echo  [OK] Setup complete.
    echo.
)

REM -- Launch the VM --------------------------------------------------------
call "%~dp0vm\start_vm.bat"
