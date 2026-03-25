#Requires -Version 5.1
<#
.SYNOPSIS
    Zapuskayet drgr-bot VM server + Telegram bot.
.DESCRIPTION
    Obnovlyayet kod iz GitHub, ustanavlivayet zavisimosti, zatem zapuskayet:
      - vm/server.py  v otdelnom okne  (Veb-interfeys: http://localhost:5000)
      - bot.py        v otdelnom okne  (Telegram bot)

    Zapusk iz PowerShell v papke bota:
        .\ЗАПУСТИТЬ.ps1

    Ili iz cmd.exe:
        powershell -ExecutionPolicy Bypass -File ".\ЗАПУСТИТЬ.ps1"
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

# 1. Proverka Python
Write-Host "Proverka Python..." -ForegroundColor Yellow
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

# 2. Obnovleniye iz GitHub
Write-Host "Obnovleniye iz GitHub..." -ForegroundColor Yellow
try {
    git fetch origin main 2>&1 | Out-Null
    git reset --hard origin/main 2>&1 | Out-Null
    Write-Host "  Kod obnovlyon." -ForegroundColor Green
} catch {
    Write-Host "  Preduprezhdenie: ne udalos obnovit. Prodolzhayu s tekushchey versiey." -ForegroundColor Yellow
}
Write-Host ""

# 3. Zavisimosti
Write-Host "Obnovleniye zavisimostey..." -ForegroundColor Yellow
pip install --upgrade -r (Join-Path $ScriptDir "requirements.txt") 2>&1 | Out-Null
Write-Host "  Zavisimosti: OK" -ForegroundColor Green
Write-Host ""

# 4. Proverka .env
$envPath = Join-Path $ScriptDir ".env"
if (-not (Test-Path $envPath)) {
    Write-Host "[OSHIBKA] Fayl .env ne nayden!" -ForegroundColor Red
    Write-Host "Sozdayte .env s BOT_TOKEN=vash_token" -ForegroundColor Yellow
    Read-Host "Nazhmite Enter dlya vykhoda"
    exit 1
}
Write-Host "  .env: OK" -ForegroundColor Green
Write-Host ""

# 5. Zapusk VM servera
$vmScript = Join-Path $ScriptDir "vm\server.py"
if (-not (Test-Path $vmScript)) {
    Write-Host "[OSHIBKA] vm/server.py ne nayden v $ScriptDir" -ForegroundColor Red
    Read-Host "Nazhmite Enter dlya vykhoda"
    exit 1
}

Write-Host "Zapusk VM servera (http://localhost:5000)..." -ForegroundColor Green
Start-Process -FilePath "cmd.exe" -ArgumentList "/k", "cd /d `"$ScriptDir`" && python vm\server.py" `
    -WindowStyle Normal -WorkingDirectory $ScriptDir

Start-Sleep -Seconds 3

# 6. Zapusk Telegram bota
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
