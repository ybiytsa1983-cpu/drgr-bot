<# 2>nul
@echo off
title ОБНОВИТЬ - скачать новые файлы
echo.
echo  =====================================================
echo   ОБНОВИТЬ - скачать и установить новые файлы
echo  =====================================================
echo.

REM Определяем директорию скрипта
set "REPO=%~dp0"
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"

REM Проверяем наличие update.ps1 рядом со скриптом
if exist "%REPO%\update.ps1" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%REPO%\update.ps1"
    exit /b
)

REM update.ps1 не рядом — ищем в стандартных папках репозитория
for %%D in (
    "%USERPROFILE%\drgr-bot"
    "%USERPROFILE%\Documents\drgr-bot"
    "%USERPROFILE%\Desktop\drgr-bot"
    "%USERPROFILE%\Downloads\drgr-bot"
    "C:\drgr-bot"
    "D:\drgr-bot"
) do (
    if exist "%%~D\update.ps1" (
        powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%%~D\update.ps1"
        exit /b
    )
)

REM update.ps1 не найден — запускаем онлайн через irm
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "irm 'https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/update.ps1' | iex"
exit /b
#>
# PowerShell path — runs when the .bat is executed via PowerShell directly
$repoDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$updatePs1 = Join-Path $repoDir 'update.ps1'
if (Test-Path $updatePs1) {
    & $updatePs1
} else {
    # Search common repo locations
    $found = $false
    foreach ($d in @(
        "$env:USERPROFILE\drgr-bot",
        "$env:USERPROFILE\Documents\drgr-bot",
        "$env:USERPROFILE\Desktop\drgr-bot",
        "$env:USERPROFILE\Downloads\drgr-bot",
        "C:\drgr-bot",
        "D:\drgr-bot"
    )) {
        $p = Join-Path $d 'update.ps1'
        if (Test-Path $p) { & $p; $found = $true; break }
    }
    if (-not $found) {
        # Fall back to online version
        irm 'https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/update.ps1' | iex
    }
}
