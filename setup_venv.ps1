#Requires -Version 5.1
<#
.SYNOPSIS
    Создаёт виртуальное окружение venv_bot и устанавливает все зависимости из requirements.txt.
.DESCRIPTION
    1. Проверяет наличие Python.
    2. Создаёт виртуальное окружение venv_bot в папке проекта (если ещё не создано).
    3. Активирует venv_bot.
    4. Устанавливает зависимости из requirements.txt.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ScriptDir = $PSScriptRoot
Set-Location $ScriptDir

Write-Host "`n============================================" -ForegroundColor Cyan
Write-Host "   drgr-bot — настройка виртуального окружения" -ForegroundColor Cyan
Write-Host "============================================`n" -ForegroundColor Cyan

# 1. Проверка Python
Write-Host "[1/3] Проверка Python..." -ForegroundColor Yellow
try {
    $pyVersion = & python --version 2>&1
    Write-Host "  OK  $pyVersion" -ForegroundColor Green
} catch {
    Write-Host "  FAIL  Python не найден. Установите Python 3.10+ и добавьте его в PATH." -ForegroundColor Red
    exit 1
}

# 2. Создание виртуального окружения venv_bot
$VenvDir = Join-Path $ScriptDir 'venv_bot'
Write-Host "[2/3] Создание виртуального окружения venv_bot..." -ForegroundColor Yellow
if (Test-Path (Join-Path $VenvDir 'Scripts\python.exe')) {
    Write-Host "  INFO  venv_bot уже существует, пропускаем создание." -ForegroundColor DarkGray
} else {
    python -m venv "$VenvDir"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  FAIL  Не удалось создать виртуальное окружение." -ForegroundColor Red
        exit 2
    }
    Write-Host "  OK  venv_bot создан: $VenvDir" -ForegroundColor Green
}

# 3. Установка зависимостей внутри venv_bot
$VenvPip = Join-Path $VenvDir 'Scripts\pip.exe'
$ReqFile = Join-Path $ScriptDir 'requirements.txt'

Write-Host "[3/3] Установка зависимостей из requirements.txt..." -ForegroundColor Yellow
if (-not (Test-Path $ReqFile)) {
    Write-Host "  FAIL  Файл requirements.txt не найден." -ForegroundColor Red
    exit 3
}

& "$VenvPip" install --upgrade pip | Out-Null
& "$VenvPip" install --upgrade -r "$ReqFile"
if ($LASTEXITCODE -ne 0) {
    Write-Host "  FAIL  Не удалось установить зависимости." -ForegroundColor Red
    exit 4
}
Write-Host "  OK  Зависимости установлены." -ForegroundColor Green

Write-Host "`n============================================" -ForegroundColor Green
Write-Host "   Виртуальное окружение готово к работе!" -ForegroundColor Green
Write-Host "   Для ручной активации выполните:" -ForegroundColor Green
Write-Host "   .\venv_bot\Scripts\Activate.ps1" -ForegroundColor White
Write-Host "============================================`n" -ForegroundColor Green
