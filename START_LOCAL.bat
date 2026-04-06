@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

echo ======================================
echo   DRGR BOT + VM Server + Local Comet
echo ======================================
echo.

REM -- Find the drgr-bot repo folder ------------------------------------
REM   The .bat may live on the Desktop while the repo is elsewhere.
set "REPO_DIR="

REM 1) Check the folder where this .bat file lives
cd /d "%~dp0"
if exist "vm\server.py" (
    set "REPO_DIR=%~dp0"
    goto :FOUND_REPO
)

REM 2) Check drgr-bot subfolder next to this .bat
if exist "%~dp0drgr-bot\vm\server.py" (
    set "REPO_DIR=%~dp0drgr-bot"
    goto :FOUND_REPO
)

REM 3) Check Desktop\drgr-bot
if exist "%USERPROFILE%\Desktop\drgr-bot\vm\server.py" (
    set "REPO_DIR=%USERPROFILE%\Desktop\drgr-bot"
    goto :FOUND_REPO
)

REM 4) Repo not found — try to clone it
echo [!] drgr-bot folder not found. Cloning from GitHub...
echo.
git --version > nul 2>&1
if errorlevel 1 (
    echo [X] Git not found! Install Git: https://git-scm.com/download/win
    echo     Then run this file again.
    pause
    exit /b 1
)
set "REPO_DIR=%USERPROFILE%\Desktop\drgr-bot"
git clone "https://github.com/ybiytsa1983-cpu/drgr-bot.git" "%REPO_DIR%"
if errorlevel 1 (
    echo [X] Failed to clone repository. Check your internet connection.
    pause
    exit /b 1
)
echo [OK] Repository cloned to %REPO_DIR%
echo.

:FOUND_REPO
cd /d "%REPO_DIR%"
echo [OK] Project folder: %CD%
echo.

REM Check Python
python --version > nul 2>&1
if errorlevel 1 (
    echo [X] Python not found! Install Python 3.10+
    pause
    exit /b 1
)

echo [OK] Python found
echo.

REM Update from GitHub (if Git is available)
git --version > nul 2>&1
if not errorlevel 1 (
    echo [*] Updating from GitHub...
    git fetch origin main 2>nul
    if not errorlevel 1 (
        git reset --hard origin/main 2>nul
    )
    echo.
)

REM Install Python dependencies
echo [*] Installing Python dependencies...
pip install --upgrade -r requirements.txt >nul 2>&1
if errorlevel 1 (
    echo [!] Some Python dependencies failed to install
)
echo.

REM -- Local Comet Editor Server (Node.js) ----------------------------
set "COMET_READY=0"
node --version > nul 2>&1
if errorlevel 1 (
    echo [!] Node.js not found - Local Comet Editor will not start.
    echo     Install Node.js 18+: https://nodejs.org/
    echo     VM server will start without it.
    echo.
) else (
    echo [OK] Node.js found
    if exist "local-comet-patch\server\package.json" (
        echo [*] Installing Local Comet Node.js dependencies...
        pushd "local-comet-patch\server"
        call npm install --silent >nul 2>&1
        if errorlevel 1 (
            echo [!] npm install failed
            popd
        ) else (
            echo [*] Building Local Comet Server...
            call npm run build --silent >nul 2>&1
            if errorlevel 1 (
                echo [!] npm run build failed
                popd
            ) else (
                popd
                set "COMET_READY=1"
                echo [OK] Local Comet Editor built
            )
        )
    ) else (
        echo [!] local-comet-patch/server/package.json not found
    )
    echo.
)

REM Check .env file
if not exist .env (
    echo [!] .env file not found
    echo     Bot will not auto-start.
    echo     Create .env via web UI (Settings tab)
    echo.
)

REM -- Start Local Comet Editor Server in a separate window -----------
if "%COMET_READY%"=="1" (
    echo [*] Starting Local Comet Editor Server (port 5052)...
    start "Local Comet Editor" /min cmd /c "cd /d "%REPO_DIR%\local-comet-patch\server" && node dist\index.cjs"
    echo.
)

REM -- Start VM Server ------------------------------------------------
echo ======================================
echo   [START] VM Server launching...
echo   VM:     http://localhost:5002
if "%COMET_READY%"=="1" (
echo   Editor: http://localhost:5052
)
echo   Bot auto-starts if BOT_TOKEN is set
echo   Ctrl+C to stop
echo ======================================
echo.

python vm/server.py

echo.
echo Server stopped.

REM Stop Local Comet Editor if running
if "%COMET_READY%"=="1" (
    taskkill /fi "WINDOWTITLE eq Local Comet Editor" >nul 2>&1
)
pause
