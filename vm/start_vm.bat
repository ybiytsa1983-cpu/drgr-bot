@echo off
setlocal EnableDelayedExpansion
title Code VM - Monaco Editor

REM --- Locate repo root (parent of this script's directory) ---
set "SCRIPT_DIR=%~dp0"
set "REPO_DIR=%SCRIPT_DIR%.."
pushd "%REPO_DIR%"

set VM_PORT=5000

REM --- Pick Python: prefer .venv, then system ---
set "PYTHON="
if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
    set "PIP=.venv\Scripts\pip.exe"
) else (
    python --version >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON=python"
        set "PIP=pip"
    )
)

if "%PYTHON%"=="" (
    echo.
    echo  [ERROR] Python not found.
    echo  Run install.bat first, or install Python 3.8+ from:
    echo    https://www.python.org/downloads/
    echo  (check "Add Python to PATH" during installation)
    echo.
    pause
    exit /b 1
)

REM --- Check if server already running ---
netstat -an 2>nul | findstr ":%VM_PORT%.*LISTEN" >nul
if not errorlevel 1 (
    echo [Code VM] Server already running on port %VM_PORT%.
    start "" "http://localhost:%VM_PORT%"
    popd
    exit /b 0
)

REM --- Install Flask / requests if missing ---
%PYTHON% -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo [Code VM] Installing dependencies (first run)...
    %PIP% install flask requests --quiet
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies.
        echo Run install.bat first, or: %PIP% install flask requests
        pause
        exit /b 1
    )
)

REM --- Determine Ollama port from OLLAMA_HOST env var (default 11434) ---
REM server.py reads OLLAMA_HOST too; set it here if not already set.
if "%OLLAMA_HOST%"=="" set "OLLAMA_HOST=http://localhost:11434"
set "OLLAMA_PORT=11434"
for /f "tokens=*" %%p in ('%PYTHON% -c "import urllib.parse,sys; u=sys.argv[1]; print(urllib.parse.urlparse(u).port or 11434)" "%OLLAMA_HOST%" 2^>nul') do set OLLAMA_PORT=%%p
if "%OLLAMA_PORT%"=="" set OLLAMA_PORT=11434

REM --- Auto-start Ollama if installed but not yet running ---
ollama --version >nul 2>&1
if not errorlevel 1 (
    netstat -an 2>nul | findstr ":%OLLAMA_PORT%.*LISTEN" >nul
    if errorlevel 1 (
        echo [Code VM] Starting Ollama service on port %OLLAMA_PORT%...
        start /min "Ollama" ollama serve
        timeout /t 2 /nobreak >nul
    ) else (
        echo [Code VM] Ollama already running on port %OLLAMA_PORT%.
    )
)

REM --- Start the Flask server in the background ---
echo [Code VM] Starting server on port %VM_PORT%...
start /b "" "%PYTHON%" vm\server.py

REM --- Wait until server responds (up to 15 seconds) ---
echo [Code VM] Waiting for server to be ready...
set /a TRIES=0
:WAIT_LOOP
timeout /t 1 /nobreak >nul
%PYTHON% -c "import urllib.request; urllib.request.urlopen('http://localhost:%VM_PORT%/')" >nul 2>&1
if not errorlevel 1 goto SERVER_READY
set /a TRIES+=1
if !TRIES! lss 15 goto WAIT_LOOP
echo [Code VM] Warning: server may not be ready yet - opening browser anyway.

:SERVER_READY
REM --- Find local IP ---
for /f "tokens=*" %%i in ('%PYTHON% -c "import socket; s=socket.socket(); s.connect((\"8.8.8.8\",80)); print(s.getsockname()[0]); s.close()" 2^>nul') do set LOCAL_IP=%%i
if "%LOCAL_IP%"=="" set LOCAL_IP=YOUR_IP

REM --- Open the browser ---
echo [Code VM] Opening browser...
start "" "http://localhost:%VM_PORT%"

echo.
echo  +--------------------------------------------------+
echo  ^|  Code VM is running!                            ^|
echo  +--------------------------------------------------+
echo  ^|  Code VM    -^>  http://localhost:%VM_PORT%/          ^|
echo  ^|  Navigator  -^>  http://localhost:%VM_PORT%/navigator/^|
echo  +--------------------------------------------------+
echo  ^|  Android: open in Chrome on your phone:         ^|
echo  ^|    http://%LOCAL_IP%:%VM_PORT%/navigator/         ^|
echo  +--------------------------------------------------+
echo  ^|  Keep this window open while using the editor.  ^|
echo  ^|  Close this window to stop the server.          ^|
echo  +--------------------------------------------------+
echo.
pause >nul

REM --- Stop server when window is closed ---
echo [Code VM] Stopping server...
for /f "tokens=5" %%p in ('netstat -aon 2^>nul ^| findstr ":%VM_PORT%.*LISTEN"') do (
    taskkill /f /pid %%p >nul 2>&1
)
echo [Code VM] Done.
popd
endlocal
