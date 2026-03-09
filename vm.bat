@echo off
REM vm.bat - launch Code VM from the repository root in Windows Terminal / cmd.
REM Usage:  .\vm.bat  (PowerShell)  or  vm.bat  (cmd.exe / double-click)
cd /d "%~dp0"

if not exist "vm\start_vm.bat" (
    echo.
    echo  [ERROR] vm\start_vm.bat not found.
    echo  Make sure you are running this from the drgr-bot repo root.
    echo  Current directory: %CD%
    echo.
    echo  Expected files here: install.bat  vm.bat  vm\
    echo.
    pause
    exit /b 1
)

call vm\start_vm.bat
