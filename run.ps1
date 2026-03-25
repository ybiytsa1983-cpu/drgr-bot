#Requires -Version 5.1
<#
.SYNOPSIS
    Launches drgr-bot VM server + Telegram bot (ASCII alias for ZAPUSTIT_BOTA.bat).
.DESCRIPTION
    Pulls latest code from GitHub, installs dependencies, then starts:
      - vm/server.py  in a new window  (Web UI at http://localhost:5000)
      - bot.py        in a new window  (Telegram bot)

    Use this script if the Cyrillic-named ZAPUSTIT_BOTA.bat cannot be found.

    Run from PowerShell already open in the bot folder:
        .\run.ps1

    Or from cmd.exe / Win+R:
        powershell -ExecutionPolicy Bypass -File ".\run.ps1"
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "   ZAPUSK DRGR BOT + VM" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check Python
Write-Host "Checking Python..." -ForegroundColor Yellow
try {
    $null = python --version 2>&1
} catch {
    Write-Host "[OSHIBKA] Python ne ustanovlen!" -ForegroundColor Red
    Write-Host "Ustanovite Python 3.10+: https://www.python.org/downloads/" -ForegroundColor Yellow
    Read-Host "Nazhmite Enter dlya vykhoda"
    exit 1
}
Write-Host "  Python: OK" -ForegroundColor Green
Write-Host ""

# 2. Pull latest from GitHub
Write-Host "Obnovleniye iz GitHub..." -ForegroundColor Yellow
try {
    git fetch origin main 2>&1 | Out-Null
    git reset --hard origin/main 2>&1 | Out-Null
    Write-Host "  Kod obnovlyon." -ForegroundColor Green
} catch {
    Write-Host "  Preduprezhdenie: ne udalos obnovit. Prodolzhayu s tekushchey versiey." -ForegroundColor Yellow
}
Write-Host ""

# 3. Install/update dependencies
Write-Host "Obnovleniye zavisimostey..." -ForegroundColor Yellow
pip install --upgrade -r (Join-Path $ScriptDir "requirements.txt") 2>&1 | Out-Null
Write-Host "  Zavisimosti: OK" -ForegroundColor Green
Write-Host ""

# 4. Check .env
$envPath = Join-Path $ScriptDir ".env"
if (-not (Test-Path $envPath)) {
    Write-Host "[OSHIBKA] Fayl .env ne nayden!" -ForegroundColor Red
    Write-Host "Sozdayte .env s BOT_TOKEN=vash_token_telegram_bota" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Primer:" -ForegroundColor Gray
    Write-Host "  echo BOT_TOKEN=1234567890:AABBcc... > .env" -ForegroundColor Gray
    Write-Host ""
    Read-Host "Nazhmite Enter dlya vykhoda"
    exit 1
}
Write-Host "  .env: OK" -ForegroundColor Green
Write-Host ""

# 5. Start VM server in separate window
$vmScript = Join-Path $ScriptDir "vm\server.py"
if (-not (Test-Path $vmScript)) {
    Write-Host "[OSHIBKA] vm/server.py ne nayden v $ScriptDir" -ForegroundColor Red
    Read-Host "Nazhmite Enter dlya vykhoda"
    exit 1
}

Write-Host "Zapusk VM servera (http://localhost:5000)..." -ForegroundColor Green
Start-Process -FilePath "cmd.exe" -ArgumentList "/k", "cd /d `"$ScriptDir`" && python vm\server.py" `
    -WindowStyle Normal -WorkingDirectory $ScriptDir

# Wait 3 seconds for VM to start
Start-Sleep -Seconds 3

# 6. Start Telegram bot in separate window
$botScript = Join-Path $ScriptDir "bot.py"
if (-not (Test-Path $botScript)) {
    Write-Host "[OSHIBKA] bot.py ne nayden v $ScriptDir" -ForegroundColor Red
    Read-Host "Nazhmite Enter dlya vykhoda"
    exit 1
}

Write-Host "Zapusk Telegram bota..." -ForegroundColor Green
Start-Process -FilePath "cmd.exe" -ArgumentList "/k", "cd /d `"$ScriptDir`" && python bot.py" `
    -WindowStyle Normal -WorkingDirectory $ScriptDir

Write-Host ""
Write-Host "Bot i VM zapushcheny v otdelnykh oknakh!" -ForegroundColor Green
Write-Host ""
Write-Host "Dlya ostanovki zakroyte okna 'DRGR VM Server' i 'DRGR Telegram Bot'" -ForegroundColor Gray
Write-Host "Veb-interfeys VM: http://localhost:5000" -ForegroundColor Cyan
Write-Host ""
Read-Host "Nazhmite Enter dlya zakrytiya"
