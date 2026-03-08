@echo off
REM vm.bat — launch Code VM from the repository root in Windows Terminal / cmd.
REM Usage:  vm
cd /d "%~dp0"
call vm\start_vm.bat
