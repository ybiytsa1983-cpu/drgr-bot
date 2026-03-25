<# 2>nul
@echo off
title ПЕРЕУЧИТЬ ВМ - drgr-visor
echo.
echo  =====================================================
echo   ПЕРЕУЧИТЬ ВМ - создать модель drgr-visor
echo  =====================================================
echo.

REM Определяем директорию скрипта
set "REPO=%~dp0"
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"

REM Запускаем через PowerShell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%REPO%\ПЕРЕУЧИТЬ_ВМ.ps1"
exit /b
#>
# PowerShell path — runs when the .bat is executed via PowerShell directly
$repoDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
& (Join-Path $repoDir 'ПЕРЕУЧИТЬ_ВМ.ps1')
