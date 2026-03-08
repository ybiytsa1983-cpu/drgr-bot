@echo off
REM stop.bat -- Stop the Code VM server that is running in the background.
REM
REM Usage:  double-click, or in cmd/PowerShell: .\stop.bat

cd /d "%~dp0"

set VM_PORT=5000
set "STOPPED="

REM --- Try the PID file written by start_vm.bat first -----------------------
if exist "server.pid" (
    set /p SERVER_PID=<server.pid
    if defined SERVER_PID (
        taskkill /f /pid %SERVER_PID% >nul 2>&1
        if not errorlevel 1 (
            set "STOPPED=1"
            del "server.pid" >nul 2>&1
        )
    )
)

REM --- Fallback: find by port -----------------------------------------------
if not defined STOPPED (
    for /f "tokens=5" %%p in ('netstat -aon 2^>nul ^| findstr ":%VM_PORT%.*LISTEN"') do (
        taskkill /f /pid %%p >nul 2>&1
        if not errorlevel 1 set "STOPPED=1"
    )
)

if defined STOPPED (
    echo  [OK] Code VM server stopped.
    if exist "server.pid" del "server.pid" >nul 2>&1
) else (
    echo  [--] Code VM server was not running on port %VM_PORT%.
)
echo.
