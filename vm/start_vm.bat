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

REM --- Resolve the absolute path of the Python executable -----------------
REM     %%~fF only works for file paths, NOT bare command names like "python".
REM     Ask Python itself for sys.executable — always returns the full path.
set "PYTHON_ABS=%PYTHON%"
for /f "usebackq tokens=*" %%p in (`"%PYTHON%" -c "import sys; print(sys.executable)" 2^>nul`) do set "PYTHON_ABS=%%p"
set "WORK_DIR=%CD%"

REM --- Start the Flask server without any console window -------------------
REM     powershell Start-Process -WindowStyle Hidden works on all Windows 7+
REM     without requiring pythonw.exe.  Run powershell synchronously (no
REM     outer "start") — it launches python in the background and exits fast.
echo [Code VM] Starting server on port %VM_PORT%...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process '!PYTHON_ABS!' 'vm\server.py' -WorkingDirectory '!WORK_DIR!' -WindowStyle Hidden"

REM --- Wait until server responds (up to 20 seconds) ---
echo [Code VM] Waiting for server to be ready...
set /a TRIES=0
:WAIT_LOOP
timeout /t 1 /nobreak >nul
%PYTHON% -c "import urllib.request; urllib.request.urlopen('http://localhost:%VM_PORT%/')" >nul 2>&1
if not errorlevel 1 goto SERVER_READY
set /a TRIES+=1
if !TRIES! lss 20 goto WAIT_LOOP

echo.
echo  [ERROR] Server did not start after 20 seconds!
echo.
echo  --- server.log ---
if exist "%REPO_DIR%\server.log" (
    type "%REPO_DIR%\server.log"
) else (
    echo (no log found -- pythonw.exe may be missing, trying with python.exe)
    REM Fallback: start with visible console so user can see the error
    start "Code VM Server (debug)" "%PYTHON%" vm\server.py
)
echo  ------------------
echo.
echo  Fix the error above, then run start.bat again.
echo  Tip: reinstall dependencies with:  .venv\Scripts\pip install -r requirements.txt
echo.
pause
popd
endlocal
exit /b 1

:SERVER_READY
REM --- Record the server PID for stop.bat ---
for /f "tokens=5" %%p in ('netstat -aon 2^>nul ^| findstr ":%VM_PORT%.*LISTEN"') do (
    echo %%p > "%REPO_DIR%\server.pid"
)

REM --- Find local IP ---
for /f "tokens=*" %%i in ('%PYTHON% -c "import socket; s=socket.socket(); s.connect((\"8.8.8.8\",80)); print(s.getsockname()[0]); s.close()" 2^>nul') do set LOCAL_IP=%%i
if "%LOCAL_IP%"=="" set LOCAL_IP=YOUR_IP

REM --- Allow port through Windows Firewall (for access from other devices) ---
netsh advfirewall firewall show rule name="Code VM (port %VM_PORT%)" >nul 2>&1
if errorlevel 1 (
    netsh advfirewall firewall add rule name="Code VM (port %VM_PORT%)" dir=in action=allow protocol=TCP localport=%VM_PORT% profile=any >nul 2>&1
)

REM --- Open the browser ---
echo [Code VM] Opening browser...
start "" "http://localhost:%VM_PORT%"

echo.
echo  +----------------------------------------------------+
echo  ^|  Code VM is running!                              ^|
echo  +----------------------------------------------------+
echo  ^|  This device:                                     ^|
echo  ^|    http://localhost:%VM_PORT%/                         ^|
echo  ^|    http://localhost:%VM_PORT%/navigator/               ^|
echo  +----------------------------------------------------+
echo  ^|  Other devices on the same network:               ^|
echo  ^|    http://%LOCAL_IP%:%VM_PORT%/                         ^|
echo  ^|    http://%LOCAL_IP%:%VM_PORT%/navigator/               ^|
echo  +----------------------------------------------------+
echo  ^|  Server runs in the background.                   ^|
echo  ^|  This window can be closed safely.                ^|
echo  ^|  To stop: double-click stop.bat                   ^|
echo  +----------------------------------------------------+
echo.
popd
endlocal
