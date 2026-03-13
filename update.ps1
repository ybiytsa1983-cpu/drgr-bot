# update.ps1 — скачать новые файлы из GitHub (обновление репозитория)
# Использование: .\update.ps1
# Или через PowerShell без клонирования репозитория:
#   irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/update.ps1" | iex
#
# Если main ещё не обновлён — используй ветку напрямую:
#   irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/copilot/create-monaco-code-generator/update.ps1" | iex

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
        "$env:USERPROFILE\projects\drgr-bot",
        "$env:USERPROFILE\Projects\drgr-bot",
        "$env:USERPROFILE\code\drgr-bot",
        "$env:USERPROFILE\Code\drgr-bot",
        "$env:USERPROFILE\repos\drgr-bot",
        "$env:USERPROFILE\Repos\drgr-bot",
        "C:\drgr-bot",
        "C:\projects\drgr-bot",
        "C:\Projects\drgr-bot",
        "C:\code\drgr-bot",
        "C:\Code\drgr-bot",
        "C:\Users\$env:USERNAME\drgr-bot",
        "D:\drgr-bot",
        "D:\projects\drgr-bot",
        "D:\Projects\drgr-bot",
        "D:\code\drgr-bot",
        "D:\Code\drgr-bot"
    )
    foreach ($d in $candidates) {
        if (Test-Path (Join-Path $d ".git")) {
            $repoDir = $d
            break
        }
    }
}

# 3. Disk scan fallback (C: and D:) — limited depth to avoid slowness
if (-not $repoDir) {
    Write-Host "  Поиск репозитория на дисках C: и D: ..." -ForegroundColor Cyan
    foreach ($root in @('C:\', 'D:\')) {
        Get-ChildItem $root -Filter 'drgr-bot' -Directory -Recurse -Depth 5 -ErrorAction SilentlyContinue | ForEach-Object {
            if (-not $repoDir -and (Test-Path (Join-Path $_.FullName '.git'))) {
                $repoDir = $_.FullName
            }
        }
        if ($repoDir) { break }
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
    # Try common Git install locations
    $gitPaths = @(
        "$env:ProgramFiles\Git\bin\git.exe",
        "${env:ProgramFiles(x86)}\Git\bin\git.exe",
        "$env:LOCALAPPDATA\Programs\Git\bin\git.exe"
    )
    $gitFound = $false
    foreach ($gp in $gitPaths) {
        if (Test-Path $gp) {
            $env:PATH = "$([System.IO.Path]::GetDirectoryName($gp));$env:PATH"
            $gitFound = $true
            break
        }
    }
    if (-not $gitFound) {
        Write-Host ""
        Write-Host "ОШИБКА: Git не установлен. Скачать: https://git-scm.com/download/win" -ForegroundColor Red
        pause
        exit 1
    }
}

# --- Остановить сервер перед обновлением (чтобы не было блокировки файлов) ---
Write-Host ""
Write-Host "Останавливаю запущенный сервер (если работает)..." -ForegroundColor Cyan
try {
    # Find python processes running server.py and stop them
    $serverProcs = Get-Process -Name python,python3,pythonw -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*server.py*' -or $_.MainWindowTitle -like '*server*' }
    foreach ($sp in $serverProcs) {
        Stop-Process -Id $sp.Id -Force -ErrorAction SilentlyContinue
        Write-Host "  Остановлен процесс $($sp.Id)" -ForegroundColor Gray
    }
} catch { }

# --- Проверка наличия обновлений (git fetch + compare) ---
Push-Location $repoDir
$hasUpdates = $false
$currentBranch = "main"   # default; overwritten below if git is available
try {
    Write-Host ""
    Write-Host "Проверяю наличие обновлений..." -ForegroundColor Cyan
    git fetch origin 2>&1 | Out-Null

    # Узнаём текущую ветку
    $currentBranch = (& git rev-parse --abbrev-ref HEAD 2>&1).Trim()
    if (-not $currentBranch -or $currentBranch -eq "HEAD") { $currentBranch = "main" }

    $localRev  = (& git rev-parse HEAD 2>&1).Trim()
    $remoteRev = (& git rev-parse "origin/$currentBranch" 2>&1).Trim()

    if ($localRev -eq $remoteRev) {
        Write-Host "  Всё уже актуально (нет новых коммитов)." -ForegroundColor Green
    } else {
        Write-Host ""
        Write-Host "  Найдены обновления! Список изменённых файлов:" -ForegroundColor Yellow
        $changedFiles = & git diff --name-only HEAD "origin/$currentBranch" 2>&1
        foreach ($f in $changedFiles) { Write-Host "    • $f" -ForegroundColor Gray }
        $hasUpdates = $true
    }
} catch {
    Write-Host "  Предупреждение: не удалось проверить обновления — продолжаю." -ForegroundColor Yellow
    $hasUpdates = $true
} finally {
    Pop-Location
}

# --- git pull ---
Push-Location $repoDir
try {
    Write-Host ""
    Write-Host "Получаю обновления..." -ForegroundColor Cyan
    $output = & git pull origin $currentBranch 2>&1
    Write-Host $output
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "Ошибка git pull. Попытка сброса..." -ForegroundColor Yellow
        git fetch --all 2>&1 | Out-Null
        git reset --hard "origin/$currentBranch" 2>&1
    }
} finally {
    Pop-Location
}

# --- Обновление Python-зависимостей ---
$reqFile = Join-Path $repoDir "requirements.txt"
if (Test-Path $reqFile) {
    # Find a working pip: prefer standalone pip/pip3, fall back to python -m pip
    $pipExe    = $null
    $pipIsPython = $false  # true when we need "python -m pip" style
    foreach ($exe in @("pip", "pip3")) {
        if (Get-Command $exe -ErrorAction SilentlyContinue) {
            $pipExe = $exe; break
        }
    }
    if (-not $pipExe) {
        foreach ($pyExe in @("python", "python3")) {
            if (Get-Command $pyExe -ErrorAction SilentlyContinue) {
                # Verify the pip module is actually available
                $check = & $pyExe -m pip --version 2>&1
                if ($LASTEXITCODE -eq 0) {
                    $pipExe = $pyExe
                    $pipIsPython = $true
                    break
                }
            }
        }
    }
    if ($pipExe) {
        # Prefer venv pip if available
        $venvPipExe = Join-Path $repoDir ".venv\Scripts\pip.exe"
        if (Test-Path $venvPipExe) { $pipExe = $venvPipExe; $pipIsPython = $false }
        Write-Host ""
        Write-Host "Обновляю Python-зависимости (pip install -r requirements.txt)..." -ForegroundColor Cyan
        try {
            if ($pipIsPython) {
                & $pipExe -m pip install -r $reqFile --upgrade --quiet 2>&1
            } else {
                & $pipExe install -r $reqFile --upgrade --quiet 2>&1
            }
            Write-Host "  Зависимости обновлены." -ForegroundColor Green
        } catch {
            Write-Host "  Предупреждение: не удалось обновить зависимости: $_" -ForegroundColor Yellow
        }
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Файлы обновлены!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Чтобы запустить Code VM:" -ForegroundColor Yellow
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$repoDir\start.ps1`"" -ForegroundColor Cyan
Write-Host ""

# --- Спросить о перезапуске ---
$startPs1 = Join-Path $repoDir "start.ps1"
if (Test-Path $startPs1) {
    $ans = Read-Host "Запустить Code VM сейчас? (Y/N, Enter = да)"
    if ($ans -eq "" -or $ans -match '^[YyДд]') {
        Write-Host "Запускаю Code VM..." -ForegroundColor Cyan
        Start-Process -FilePath "powershell.exe" `
            -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$startPs1`"" `
            -WorkingDirectory $repoDir
    }
} else {
    pause
}
