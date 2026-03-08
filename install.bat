@echo off
REM install.bat — First-time setup for Code VM on Windows.
REM
REM Usage: double-click this file or run from cmd/PowerShell:
REM   install.bat
REM
REM What it does:
REM   1. Checks for Python 3.8+
REM   2. Creates a virtual environment (.venv) in the repo root
REM   3. Installs Python dependencies
REM   4. Prints Ollama installation instructions

setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo  +++++++++++++++++++++++++++++++++++++++++++++
echo   ^| ^| Code VM -- First-time setup (Windows)   ^|
echo  +++++++++++++++++++++++++++++++++++++++++++++
echo.

REM ── 1. Check Python ──────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found in PATH.
    echo.
    echo  Please install Python 3.8+ from:
    echo    https://www.python.org/downloads/
    echo.
    echo  IMPORTANT: During installation, check "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo  [OK] Python %PY_VER% found

REM ── 2. Create virtual environment ────────────────────────────────────────────
if exist ".venv\Scripts\python.exe" (
    echo  [OK] Virtual environment already exists
) else (
    echo  [--] Creating virtual environment (.venv)...
    python -m venv .venv
    if errorlevel 1 (
        echo  [ERROR] Failed to create virtual environment.
        echo  Try: python -m pip install virtualenv
        pause
        exit /b 1
    )
    echo  [OK] Virtual environment created
)

REM ── 3. Install dependencies ───────────────────────────────────────────────────
echo  [--] Installing Python dependencies...
.venv\Scripts\pip install flask requests --quiet
if errorlevel 1 (
    echo  [ERROR] Failed to install flask/requests.
    echo  Try running manually: .venv\Scripts\pip install flask requests
    pause
    exit /b 1
)
echo  [OK] Flask + requests installed

if exist "requirements.txt" (
    echo  [--] Installing requirements.txt (Telegram bot deps)...
    .venv\Scripts\pip install -r requirements.txt --quiet 2>nul
    echo  [OK] requirements.txt processed (some optional packages may have been skipped)
)

REM ── 4. Ollama instructions ────────────────────────────────────────────────────
echo.
echo  +++++++++++++++++++++++++++++++++++++++++++++
echo   Ollama (AI features -- optional)
echo  +++++++++++++++++++++++++++++++++++++++++++++
echo.

ollama --version >nul 2>&1
if not errorlevel 1 (
    echo  [OK] Ollama is already installed
) else (
    echo  [!] Ollama not found -- AI code generation will not work.
    echo.
    echo  Download and install from:
    echo    https://ollama.com/download
    echo.
    echo  After installing, run in a separate terminal:
    echo    ollama pull qwen3-vl:8b
    echo    ollama serve
)

REM ── 5. Done ──────────────────────────────────────────────────────────────────
echo.
echo  +++++++++++++++++++++++++++++++++++++++++++++
echo   [OK] Setup complete!
echo  +++++++++++++++++++++++++++++++++++++++++++++
echo.
echo  Launch the VM:
echo    .\vm.bat        (PowerShell or cmd.exe)
echo    vm.bat          (double-click in File Explorer)
echo.
echo  Then open in browser:
echo    http://localhost:5000/             Code VM
echo    http://localhost:5000/navigator/   Android Navigator
echo.
pause
endlocal
