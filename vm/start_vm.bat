@echo off
setlocal EnableDelayedExpansion
title Code VM — Monaco Editor

REM ── Locate repo root (parent of this script's directory) ──────────────────
set "SCRIPT_DIR=%~dp0"
set "REPO_DIR=%SCRIPT_DIR%.."
pushd "%REPO_DIR%"

REM ── Check Python ──────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERROR] Python not found in PATH.
    echo  Please install Python 3.8+ from https://www.python.org/downloads/
    echo  and make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

REM ── Check if server already running ────────────────────────────────────────
set VM_PORT=5000
netstat -an 2>nul | findstr ":%VM_PORT%.*LISTEN" >nul
if not errorlevel 1 (
    echo [Code VM] Server already running on port %VM_PORT%.
    start "" "http://localhost:%VM_PORT%"
    popd
    exit /b 0
)

REM ── Install Flask / requests if missing ────────────────────────────────────
python -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo [Code VM] Installing dependencies (first run)...
    pip install flask requests --quiet
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies.
        echo Please run manually:  pip install flask requests
        pause
        exit /b 1
    )
)

REM ── Start the Flask server in the background ───────────────────────────────
echo [Code VM] Starting server on port %VM_PORT%...
start /b "" python vm\server.py

REM ── Wait until server responds (up to 15 seconds) ─────────────────────────
echo [Code VM] Waiting for server to be ready...
set /a TRIES=0
:WAIT_LOOP
timeout /t 1 /nobreak >nul
python -c "import urllib.request; urllib.request.urlopen('http://localhost:%VM_PORT%/')" >nul 2>&1
if not errorlevel 1 goto SERVER_READY
set /a TRIES+=1
if !TRIES! lss 15 goto WAIT_LOOP
echo [Code VM] Warning: server may not be ready yet — opening browser anyway.

:SERVER_READY
REM ── Open the browser ───────────────────────────────────────────────────────
echo [Code VM] Opening http://localhost:%VM_PORT% in your browser...
start "" "http://localhost:%VM_PORT%"

echo.
echo  +------------------------------------------+
echo  ^|  Code VM is running!                     ^|
echo  ^|  http://localhost:%VM_PORT%                  ^|
echo  ^|                                          ^|
echo  ^|  Ollama AI is supported — make sure      ^|
echo  ^|  ollama serve  is running separately.    ^|
echo  ^|                                          ^|
echo  ^|  Close this window to stop the server.   ^|
echo  +------------------------------------------+
echo.
pause >nul

REM ── Stop server when window is closed ──────────────────────────────────────
echo [Code VM] Stopping server...
for /f "tokens=5" %%p in ('netstat -aon 2^>nul ^| findstr ":%VM_PORT%.*LISTEN"') do (
    taskkill /f /pid %%p >nul 2>&1
)
echo [Code VM] Done.
popd
endlocal
