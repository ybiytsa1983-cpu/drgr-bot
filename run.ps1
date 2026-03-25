#Requires -Version 5.1
<#
.SYNOPSIS
    Запуск drgr-bot и VM-сервера.
.DESCRIPTION
    Запустите из папки проекта:

        Set-ExecutionPolicy -Scope Process Bypass
        .\run.ps1

    Скрипт:
      1. Проверит Python
      2. Подтянет обновления из GitHub
      3. Установит/обновит зависимости Python
      4. Запустит VM-сервер (http://localhost:5001)
      5. Запустит Telegram-бот
    Каждый процесс запускается в отдельном окне PowerShell.
#>

$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot

function Write-Step([string]$msg) {
    Write-Host "`n[RUN] $msg" -ForegroundColor Cyan
}

function Write-OK([string]$msg) {
    Write-Host "  ✅ $msg" -ForegroundColor Green
}

function Write-Warn([string]$msg) {
    Write-Host "  ⚠️  $msg" -ForegroundColor Yellow
}

function Write-Err([string]$msg) {
    Write-Host "  ❌ $msg" -ForegroundColor Red
}

# ── 1. Python ──────────────────────────────────────────────────────────────
Write-Step "Проверка Python..."
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Err "Python не найден! Установите Python 3.10+ (https://www.python.org/downloads/) и отметьте 'Add Python to PATH'."
    Read-Host "Нажмите Enter для выхода"
    exit 1
}
$pyver = python --version 2>&1
Write-OK "Найден: $pyver"

# ── 2. Обновление из GitHub ────────────────────────────────────────────────
Write-Step "Подтягивание обновлений из GitHub..."
if (Get-Command git -ErrorAction SilentlyContinue) {
    git fetch origin main 2>&1 | Out-Null
    git reset --hard origin/main 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-OK "Обновление применено."
    } else {
        Write-Warn "Не удалось применить обновления. Продолжаю с текущей версией."
    }
} else {
    Write-Warn "Git не найден — пропускаю обновление."
}

# ── 3. Зависимости ────────────────────────────────────────────────────────
Write-Step "Обновление зависимостей Python..."
pip install --upgrade -r requirements.txt 2>&1 | Select-String -NotMatch '^Requirement already'
if ($LASTEXITCODE -ne 0) {
    Write-Warn "Некоторые зависимости не установились, пробую продолжить."
} else {
    Write-OK "Зависимости актуальны."
}

# ── 4. Проверка .env ──────────────────────────────────────────────────────
Write-Step "Проверка .env..."
if (-not (Test-Path '.env')) {
    Write-Err "Файл .env не найден! Создайте его:"
    Write-Host "    echo BOT_TOKEN=ваш_токен > .env" -ForegroundColor Gray
    Read-Host "Нажмите Enter для выхода"
    exit 1
}
Write-OK "Файл .env найден."

# ── 5. Запуск VM-сервера ──────────────────────────────────────────────────
Write-Step "Запуск VM-сервера..."
$dir = $PWD.Path
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$dir'; python vm/server.py" `
    -WindowStyle Normal
Write-OK "VM-сервер запущен в отдельном окне."

Start-Sleep -Seconds 3

# ── 6. Запуск бота ────────────────────────────────────────────────────────
Write-Step "Запуск Telegram-бота..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$dir'; python bot.py" `
    -WindowStyle Normal
Write-OK "Бот запущен в отдельном окне."

Write-Host ""
Write-Host "======================================" -ForegroundColor Green
Write-Host "  ✅  Бот и VM запущены!" -ForegroundColor Green
Write-Host "======================================" -ForegroundColor Green
Write-Host "  🌐  Веб-интерфейс VM: http://localhost:5001" -ForegroundColor Cyan
Write-Host "  📌  Для остановки закройте открытые окна PowerShell." -ForegroundColor Gray
Write-Host ""
Read-Host "Нажмите Enter для закрытия этого окна"
