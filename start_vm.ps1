# DRGR VM — быстрый запуск
# Полный лаунчер с проверкой Ollama: .\start.ps1

# Принудительно TLS 1.2 для надёжного HTTPS (GitHub, pip и т.д.)
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$repoUrl = "https://github.com/ybiytsa1983-cpu/drgr-bot.git"
$defaultBranch = "main"
$desktopDir = [Environment]::GetFolderPath("Desktop")
$defaultInstallDir = Join-Path $desktopDir "drgr-bot"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  DRGR VM — Быстрый запуск" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

function Test-ProjectDir([string]$dir) {
    if (-not $dir) { return $false }
    return (Test-Path (Join-Path $dir "vm\server.py")) -and (Test-Path (Join-Path $dir "requirements.txt"))
}

function Find-ProjectDir {
    $candidates = @()
    $scriptPath = $MyInvocation.MyCommand.Path
    if ($scriptPath) { $candidates += (Split-Path -Parent $scriptPath) }
    $candidates += (Get-Location).Path
    $candidates += $defaultInstallDir

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (Test-ProjectDir $candidate) { return $candidate }
    }
    return $null
}

function Ensure-InstallDir {
    if (Test-ProjectDir $defaultInstallDir) {
        return $defaultInstallDir
    }

    Write-Host "Папка проекта не найдена. Установка в: $defaultInstallDir" -ForegroundColor Yellow

    if (Test-Path $defaultInstallDir) {
        if (-not (Test-Path (Join-Path $defaultInstallDir ".git"))) {
            Write-Host "ОШИБКА: Папка существует, но это не git-репозиторий: $defaultInstallDir" -ForegroundColor Red
            Write-Host "Удалите или переименуйте эту папку, затем запустите снова." -ForegroundColor Yellow
            exit 1
        }
        Write-Host "Обновление существующего репозитория..." -ForegroundColor Yellow
        git -C $defaultInstallDir fetch origin $defaultBranch 2>$null
        git -C $defaultInstallDir reset --hard "origin/$defaultBranch" 2>$null
    }
    else {
        Write-Host "Клонирование репозитория..." -ForegroundColor Yellow
        git clone $repoUrl $defaultInstallDir
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ОШИБКА: Не удалось клонировать репозиторий." -ForegroundColor Red
            exit 1
        }
    }

    if (-not (Test-ProjectDir $defaultInstallDir)) {
        Write-Host "ОШИБКА: Установка завершена, но необходимые файлы отсутствуют." -ForegroundColor Red
        exit 1
    }

    return $defaultInstallDir
}

$projectDir = Find-ProjectDir
if (-not $projectDir) {
    $projectDir = Ensure-InstallDir
}

Set-Location $projectDir
Write-Host "[start] Рабочая папка: $projectDir" -ForegroundColor DarkGray

# Обновление из GitHub
if (Test-Path ".git") {
    Write-Host "Обновление из GitHub..." -ForegroundColor Yellow
    git pull origin $defaultBranch 2>$null
}

# Поиск Python
$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        & $cmd --version *> $null
        if ($LASTEXITCODE -eq 0) {
            $pythonCmd = $cmd
            break
        }
    } catch {}
}

if (-not $pythonCmd) {
    Write-Host "ОШИБКА: Python не установлен или не добавлен в PATH." -ForegroundColor Red
    Write-Host "  Скачайте: https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}

# Установка зависимостей
Write-Host "[start] Установка/обновление зависимостей..." -ForegroundColor Yellow
& $pythonCmd -m pip install --upgrade typing-extensions pydantic aiohttp aiofiles --quiet 2>$null
& $pythonCmd -m pip install -r requirements.txt --quiet 2>$null

# Создание ярлыка DRGR.bat на Рабочем столе (если его нет)
$desktopBat = Join-Path $desktopDir "DRGR.bat"
if (-not (Test-Path $desktopBat)) {
    Write-Host "Создание ярлыка на Рабочем столе: DRGR.bat" -ForegroundColor Yellow
    $batContent = @"
@echo off
chcp 65001 > nul
cd /d "$projectDir"
python vm/server.py
pause
"@
    Set-Content -Path $desktopBat -Value $batContent -Encoding UTF8
    Write-Host "Ярлык создан: $desktopBat" -ForegroundColor Green
}

# Запуск VM сервера
if (-not (Test-Path ".\vm\server.py")) {
    Write-Host "ОШИБКА: vm\server.py не найден в $((Get-Location).Path)" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  VM сервер запускается: http://localhost:5002" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Веб-интерфейс: http://localhost:5002" -ForegroundColor Cyan
Write-Host "  Ctrl+C — остановка" -ForegroundColor DarkGray
Write-Host ""

& $pythonCmd vm/server.py
