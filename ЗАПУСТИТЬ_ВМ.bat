<# 2>nul
@echo off
title ЗАПУСТИТЬ ВМ - Code VM + Visor AI
echo.
echo  =====================================================
echo   ЗАПУСТИТЬ ВМ — Code VM + Visor AI (qwen3-vl)
echo  =====================================================
echo.

REM Ищем ЗАПУСТИТЬ_ВМ.ps1 рядом со скриптом (если запущен из папки репозитория)
if exist "%~dp0ЗАПУСТИТЬ_ВМ.ps1" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ЗАПУСТИТЬ_ВМ.ps1"
    exit /b
)

REM ЗАПУСТИТЬ_ВМ.ps1 не рядом — ищем в стандартных папках репозитория
for %%D in (
    "%USERPROFILE%\drgr-bot"
    "%USERPROFILE%\Documents\drgr-bot"
    "%USERPROFILE%\Desktop\drgr-bot"
    "%USERPROFILE%\Downloads\drgr-bot"
    "%USERPROFILE%\projects\drgr-bot"
    "%USERPROFILE%\Projects\drgr-bot"
    "%USERPROFILE%\code\drgr-bot"
    "%USERPROFILE%\Code\drgr-bot"
    "%USERPROFILE%\repos\drgr-bot"
    "%USERPROFILE%\Repos\drgr-bot"
    "C:\drgr-bot"
    "C:\projects\drgr-bot"
    "C:\Projects\drgr-bot"
    "C:\code\drgr-bot"
    "C:\Code\drgr-bot"
    "D:\drgr-bot"
    "D:\projects\drgr-bot"
    "D:\Projects\drgr-bot"
    "D:\code\drgr-bot"
    "D:\Code\drgr-bot"
) do (
    if exist "%%~D\ЗАПУСТИТЬ_ВМ.ps1" (
        powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%%~D\ЗАПУСТИТЬ_ВМ.ps1"
        exit /b
    )
)

REM ЗАПУСТИТЬ_ВМ.ps1 не найден нигде — запускаем онлайн через irm
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "try { irm 'https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/run.ps1' | iex } catch { Write-Host 'Ошибка запуска онлайн. Установите репозиторий: git clone https://github.com/ybiytsa1983-cpu/drgr-bot' -ForegroundColor Red; pause }"
exit /b
#>
# PowerShell path — runs when the .bat is executed via PowerShell directly
$ps1 = $null

# 1. Next to this script (repo folder)
$here = if ($PSScriptRoot) { $PSScriptRoot } elseif ($MyInvocation.MyCommand.Path) { Split-Path $MyInvocation.MyCommand.Path } else { (Get-Location).Path }
$candidate = Join-Path $here 'ЗАПУСТИТЬ_ВМ.ps1'
if (Test-Path $candidate) { $ps1 = $candidate }

# 2. Common repo locations
if (-not $ps1) {
    foreach ($d in @(
        "$env:USERPROFILE\drgr-bot",
        "$env:USERPROFILE\Documents\drgr-bot",
        "$env:USERPROFILE\Desktop\drgr-bot",
        "$env:USERPROFILE\Downloads\drgr-bot",
        "$env:USERPROFILE\projects\drgr-bot",
        "$env:USERPROFILE\Projects\drgr-bot",
        "$env:USERPROFILE\code\drgr-bot",
        "$env:USERPROFILE\Code\drgr-bot",
        "$env:USERPROFILE\repos\drgr-bot",
        "$env:USERPROFILE\Repos\drgr-bot",
        "C:\drgr-bot", "C:\projects\drgr-bot", "C:\Projects\drgr-bot", "C:\code\drgr-bot", "C:\Code\drgr-bot",
        "D:\drgr-bot", "D:\projects\drgr-bot", "D:\Projects\drgr-bot", "D:\code\drgr-bot", "D:\Code\drgr-bot"
    )) {
        $c = Join-Path $d 'ЗАПУСТИТЬ_ВМ.ps1'
        if (Test-Path $c) { $ps1 = $c; break }
    }
}

if ($ps1) { & $ps1 }
else {
    Write-Host 'Репозиторий drgr-bot не найден. Установите: git clone https://github.com/ybiytsa1983-cpu/drgr-bot' -ForegroundColor Red
    Read-Host 'Нажмите Enter для выхода'
}
