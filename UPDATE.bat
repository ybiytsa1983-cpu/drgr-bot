@echo off
chcp 65001 > nul
setlocal
set "SCRIPT_DIR=%~dp0"
if exist "%SCRIPT_DIR%ОБНОВИТЬ.bat" (
    call "%SCRIPT_DIR%ОБНОВИТЬ.bat"
) else (
    echo [ERROR] File not found: %SCRIPT_DIR%ОБНОВИТЬ.bat
    pause
    exit /b 1
)

