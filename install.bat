@echo off
REM install.bat - First-time setup for Code VM on Windows.
REM
REM Usage: double-click this file, or run in PowerShell/cmd:
REM   .\install.bat
REM
REM What it does:
REM   1. Checks for Python 3.8+
REM   2. Creates .venv virtual environment
REM   3. Installs Python dependencies
REM   4. Bundles Monaco Editor locally (editor works without internet)
REM   5. Downloads and installs Ollama automatically
REM   6. Starts downloading the AI model in the background
REM   7. Creates a "Code VM" shortcut on your Desktop

setlocal EnableDelayedExpansion
cd /d "%~dp0"

set MODEL_NAME=qwen3-vl:8b

echo.
echo  ============================================
echo   Code VM -- First-time setup (Windows)
echo  ============================================
echo.

REM --- 1. Check Python ---
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

REM --- 2. Create virtual environment ---
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

REM --- 3. Install Python dependencies ---
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
    echo  [--] Installing requirements.txt...
    .venv\Scripts\pip install -r requirements.txt --quiet 2>nul
    echo  [OK] requirements.txt processed
)

REM --- 4. Bundle Monaco Editor locally ---
echo.
echo  [--] Bundling Monaco Editor (editor will work without internet)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0vm\bundle_monaco.ps1"
if errorlevel 1 (
    echo  [!] Monaco bundle failed -- CDN fallback will be used
) else (
    echo  [OK] Monaco ready
)

REM --- 5. Install Ollama automatically ---
echo.
echo  [--] Checking for Ollama...
ollama --version >nul 2>&1
if not errorlevel 1 (
    echo  [OK] Ollama already installed
    goto OLLAMA_DONE
)

echo  [--] Downloading Ollama installer (this may take a minute)...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Invoke-WebRequest -Uri 'https://ollama.com/download/OllamaSetup.exe' -OutFile '%TEMP%\OllamaSetup.exe' -UseBasicParsing"

if errorlevel 1 (
    echo  [!] Download failed -- check your internet connection.
    echo      Install manually later: https://ollama.com/download
    goto SHORTCUT
)

echo  [--] Installing Ollama...
"%TEMP%\OllamaSetup.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
if errorlevel 1 (
    echo  [!] Ollama installation failed -- you can install manually: https://ollama.com/download
    goto SHORTCUT
)

REM Add Ollama to PATH for the rest of this session
set "PATH=%PATH%;%LOCALAPPDATA%\Programs\Ollama"
echo  [OK] Ollama installed

:OLLAMA_DONE

REM --- 6. Start AI model download in background ---
ollama --version >nul 2>&1
if not errorlevel 1 (
    ollama list 2>nul | findstr "%MODEL_NAME%" >nul
    if errorlevel 1 (
        echo  [--] Starting AI model download in background (%MODEL_NAME% ~5 GB)
        echo       A small window will show download progress -- it can run while you work.
        start "Ollama model pull" /min cmd /c "ollama pull %MODEL_NAME% && echo [OK] Model ready! && pause"
        echo  [OK] Model download started
    ) else (
        echo  [OK] AI model already downloaded
    )
)

:SHORTCUT

REM --- 7. Create desktop shortcut ---
echo.
echo  [--] Creating "Code VM" shortcut on your Desktop...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0vm\create_shortcut.ps1"
if errorlevel 1 (
    echo  [!] Shortcut creation failed (non-fatal).
    echo      You can create it later by running: vm\create_shortcut.ps1
) else (
    echo  [OK] Desktop shortcut created
)

REM --- Done ---
echo.
echo  ============================================
echo   [OK] Setup complete!
echo  ============================================
echo.
echo  A "Code VM" icon is now on your Desktop.
echo  Double-click it to launch the editor!
echo.
echo  Or run from this window:
echo    .\vm.bat
echo.
pause
endlocal
