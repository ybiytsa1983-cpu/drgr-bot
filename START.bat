@echo off
chcp 65001 > nul
setlocal
set "SCRIPT_DIR=%~dp0"
if exist "%SCRIPT_DIR%ЗАПУСТИТЬ_БОТА.bat" (
    call "%SCRIPT_DIR%ЗАПУСТИТЬ_БОТА.bat"
) else (
    echo [ERROR] File not found: %SCRIPT_DIR%ЗАПУСТИТЬ_БОТА.bat
    pause
    exit /b 1
)

