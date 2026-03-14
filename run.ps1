# Code VM -- скрипт скачивания и запуска (однострочник).
# Использование (из любого окна PowerShell — репозиторий не нужен):
#   irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/run.ps1" | iex
#
# Что делает скрипт:
#   1. Проверяет, установлен ли Git.
#   2. Клонирует или обновляет репозиторий drgr-bot в $HOME\drgr-bot.
#   3. Запускает install.ps1 из скачанного репозитория.

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Code VM — Установка и запуск" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# --- Проверка Git ---
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "ОШИБКА: Git не установлен." -ForegroundColor Red
    Write-Host ""
    Write-Host "Сначала установи Git:" -ForegroundColor Yellow
    Write-Host "  https://git-scm.com/download/win" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "После установки Git повтори эту команду." -ForegroundColor Yellow
    Write-Host ""
    pause
    exit 1
}

# --- Клонирование или обновление ---
$repoDir = Join-Path $env:USERPROFILE "drgr-bot"
$repoUrl = "https://github.com/ybiytsa1983-cpu/drgr-bot"

if (Test-Path (Join-Path $repoDir ".git")) {
    Write-Host "Репозиторий уже существует — обновление (git pull)..." -ForegroundColor Green
    Push-Location $repoDir
    try {
        git pull
    } finally {
        Pop-Location
    }
} else {
    Write-Host "Клонирование репозитория в: $repoDir" -ForegroundColor Green
    Push-Location $env:USERPROFILE
    try {
        git clone $repoUrl
    } finally {
        Pop-Location
    }
}

# --- Поиск полного кода во всех ветках (на случай если main ещё пустой) ---
# Если install.ps1 отсутствует, перебираем все удалённые ветки и
# переключаемся на первую, где есть install.ps1.
$installScript = Join-Path $repoDir "install.ps1"
if (-not (Test-Path $installScript)) {
    Write-Host ""
    Write-Host "  Ветка main выглядит неполной — ищу полный код во всех ветках..." -ForegroundColor Yellow
    Push-Location $repoDir
    try {
        # Загружаем все удалённые ветки (ошибки некритичны)
        $fetchOutput = & git fetch --all 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  Предупреждение: git fetch завершился с ошибкой — пробую локальные ветки." -ForegroundColor Yellow
        }
        $remoteBranches = & git branch -r 2>&1 |
            Where-Object { $_ -notmatch 'HEAD' } |
            ForEach-Object { $_.Trim() -replace '^origin/', '' }
        $found = $false
        foreach ($branch in $remoteBranches) {
            if ($branch -eq 'main') { continue }   # main уже проверен
            $checkoutOutput = & git checkout -B $branch "origin/$branch" --quiet 2>&1
            if ($LASTEXITCODE -ne 0) { continue }   # ветка недоступна — пробуем следующую
            if (Test-Path $installScript) {
                Write-Host "  Полный код найден в ветке: $branch" -ForegroundColor Green
                $found = $true
                break
            }
        }
        if (-not $found) {
            Write-Host ""
            Write-Host "  ОШИБКА: Не удалось найти install.ps1 ни в одной ветке." -ForegroundColor Red
            Write-Host "  Попробуй ещё раз через несколько минут или зайди на:" -ForegroundColor Yellow
            Write-Host "    https://github.com/ybiytsa1983-cpu/drgr-bot" -ForegroundColor Cyan
            exit 1
        }
    } finally {
        Pop-Location
    }
}

# --- Запуск установщика ---
if (-not (Test-Path $installScript)) {
    Write-Host "ОШИБКА: файл install.ps1 не найден по пути: $installScript" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Запуск install.ps1..." -ForegroundColor Green
Write-Host ""
# Разрешаем выполнение локальных скриптов для текущей сессии (нужно при irm | iex)
Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process -Force
& $installScript
