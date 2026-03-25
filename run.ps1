#Requires -Version 5.1
<#
.SYNOPSIS
    Launches drgr-bot (ASCII-name alias for ЗАПУСТИТЬ.ps1).
.DESCRIPTION
    Checks for .env and an unfilled token, then runs bot.py.
    Use this script if the Cyrillic-named ЗАПУСТИТЬ.ps1 cannot be found on your system.

    Run from a PowerShell session already open in the bot folder:
        .\run.ps1

    Or from cmd.exe / Win+R:
        powershell -ExecutionPolicy Bypass -File ".\run.ps1"
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host ""
Write-Host "╔══════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║          drgr-bot  -  Запуск бота            ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# Check .env exists
$envPath = Join-Path $ScriptDir ".env"
if (-not (Test-Path $envPath)) {
    Write-Host "  [ОШИБКА] Файл .env не найден!" -ForegroundColor Red
    Write-Host "  Сначала запустите УСТАНОВИТЬ.bat для первоначальной настройки." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Нажмите Enter для выхода"
    exit 1
}

# Check token placeholder not still present
$envContent = Get-Content $envPath -Raw -ErrorAction SilentlyContinue
if ($envContent -match 'BOT_TOKEN=ВАШ_ТОКЕН_БОТА') {
    Write-Host "  [ОШИБКА] Токен бота не заполнен в .env!" -ForegroundColor Red
    Write-Host "  Откройте .env и замените `"ВАШ_ТОКЕН_БОТА`" на реальный токен." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Нажмите Enter для выхода"
    exit 1
}

# Check bot.py present
$botPath = Join-Path $ScriptDir "bot.py"
if (-not (Test-Path $botPath)) {
    Write-Host "  [ОШИБКА] bot.py не найден в $ScriptDir" -ForegroundColor Red
    Write-Host "  Убедитесь, что скрипт запускается из папки бота." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Нажмите Enter для выхода"
    exit 1
}

Write-Host "  Запуск bot.py..." -ForegroundColor Green
Write-Host "  Чтобы остановить бота - нажмите Ctrl+C." -ForegroundColor Gray
Write-Host ""

python $botPath

Write-Host ""
Write-Host "  Бот остановлен." -ForegroundColor Yellow
Read-Host "Нажмите Enter для выхода"
