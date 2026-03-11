# update.ps1 — скачать новые файлы из GitHub (обновление репозитория)
# Использование: .\update.ps1
# Или через PowerShell без клонирования репозитория:
#   irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/update.ps1" | iex

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Code VM — Обновление файлов" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# --- Найти папку репозитория ---
$repoDir = $null

# 1. Если скрипт запущен из папки репозитория
if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot ".git"))) {
    $repoDir = $PSScriptRoot
}

# 2. Стандартные расположения
if (-not $repoDir) {
    $candidates = @(
        "$env:USERPROFILE\drgr-bot",
        "$env:USERPROFILE\Documents\drgr-bot",
        "$env:USERPROFILE\Desktop\drgr-bot",
        "$env:USERPROFILE\Downloads\drgr-bot",
        "C:\drgr-bot",
        "D:\drgr-bot"
    )
    foreach ($d in $candidates) {
        if (Test-Path (Join-Path $d ".git")) {
            $repoDir = $d
            break
        }
    }
}

if (-not $repoDir) {
    Write-Host "ОШИБКА: папка репозитория drgr-bot не найдена." -ForegroundColor Red
    Write-Host ""
    Write-Host "Если ты ещё не установил Code VM, используй:" -ForegroundColor Yellow
    Write-Host "  irm 'https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/run.ps1' | iex" -ForegroundColor Cyan
    Write-Host ""
    pause
    exit 1
}

Write-Host "Папка репозитория: $repoDir" -ForegroundColor Green

# --- Проверка Git ---
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "ОШИБКА: Git не установлен. Скачать: https://git-scm.com/download/win" -ForegroundColor Red
    pause
    exit 1
}

# --- git pull ---
Push-Location $repoDir
try {
    Write-Host ""
    Write-Host "Получаю обновления..." -ForegroundColor Cyan
    $output = & git pull 2>&1
    Write-Host $output
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "Ошибка git pull. Попытка сброса..." -ForegroundColor Yellow
        git fetch --all 2>&1 | Out-Null
        git reset --hard origin/main 2>&1
    }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "Файлы обновлены!" -ForegroundColor Green
Write-Host ""
Write-Host "Чтобы запустить Code VM:" -ForegroundColor Yellow
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$repoDir\start.ps1`"" -ForegroundColor Cyan
Write-Host ""
