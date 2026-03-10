<# 2>nul
@echo off
title ЗАПУСТИТЬ ВМ - Code VM + Visor AI
echo.
echo  =====================================================
echo   ЗАПУСТИТЬ ВМ — Code VM + Visor AI (qwen3-vl)
echo  =====================================================
echo.

REM Определяем директорию скрипта
set "REPO=%~dp0"
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"

REM Запускаем через PowerShell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%REPO%\ЗАПУСТИТЬ_ВМ.ps1"
exit /b
#>
# PowerShell path — runs when the .bat is executed via PowerShell directly
$repoDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
& (Join-Path $repoDir 'ЗАПУСТИТЬ_ВМ.ps1')
