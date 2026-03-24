#Requires -Version 5.1
<#
.SYNOPSIS
    Обновляет drgr-bot: git pull, pip install, резервная копия и автоматический откат при ошибке.
.DESCRIPTION
    1. Сохраняет текущий хеш коммита (резервная копия).
    2. Выполняет git pull origin main.
    3. Устанавливает зависимости из requirements.txt.
    4. При ошибке на любом шаге — откатывается к предыдущему коммиту.
    5. После успешного обновления перезапускает bot.py.
#>

param(
    [switch]$SkipRestart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ── вспомогательные функции ────────────────────────────────────────────────

function Write-Step {
    param([string]$Message)
    Write-Host "`n[UPDATE] $Message" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "  OK  $Message" -ForegroundColor Green
}

function Write-Fail {
    param([string]$Message)
    Write-Host "  FAIL  $Message" -ForegroundColor Red
}

function Stop-BotProcess {
    try {
        $wmi = Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" -ErrorAction SilentlyContinue |
               Where-Object { $_.CommandLine -match 'bot\.py' }
        if ($wmi) {
            $wmi | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
            Write-Ok "Процесс bot.py остановлен."
        } else {
            Write-Host "  INFO  Запущенный процесс bot.py не найден." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "  INFO  Не удалось проверить процессы: $_" -ForegroundColor Yellow
    }
}

function Start-Bot {
    $botScript = Join-Path $PSScriptRoot 'bot.py'
    if (-not (Test-Path $botScript)) {
        Write-Fail "bot.py не найден по пути: $botScript"
        return
    }
    Write-Step "Запуск bot.py..."
    Start-Process -FilePath 'python' -ArgumentList "`"$botScript`"" -WindowStyle Normal
    Write-Ok "bot.py запущен."
}

function Invoke-Rollback {
    param([string]$PreviousHash)
    Write-Step "Выполняется откат к коммиту $PreviousHash ..."
    try {
        git reset --hard $PreviousHash 2>&1 | ForEach-Object { Write-Host "  $_" }
        Write-Ok "Откат выполнен успешно."
    } catch {
        Write-Fail "Не удалось выполнить откат: $_"
    }
}

# ── основной скрипт ────────────────────────────────────────────────────────

$ScriptDir = $PSScriptRoot
Set-Location $ScriptDir

Write-Host "`n============================================" -ForegroundColor Magenta
Write-Host "   drgr-bot — скрипт обновления (update.ps1)" -ForegroundColor Magenta
Write-Host "============================================`n" -ForegroundColor Magenta

# 1. Сохранение текущего хеша (резервная копия)
Write-Step "Шаг 1/4: Сохранение резервной копии (текущий коммит)..."
try {
    $backupHash = (git rev-parse HEAD 2>&1).Trim()
    if ($backupHash -notmatch '^[0-9a-f]{40}$') {
        throw "Получен некорректный хеш: $backupHash"
    }
    $backupHash | Out-File -FilePath (Join-Path $ScriptDir '.update_backup_hash') -Encoding UTF8 -NoNewline
    Write-Ok "Резервный хеш сохранён: $backupHash"
} catch {
    Write-Fail "Не удалось получить текущий коммит. Убедитесь, что папка является git-репозиторием."
    Write-Fail $_
    exit 1
}

# 2. git fetch + reset --hard origin/main
Write-Step "Шаг 2/4: Получение обновлений (git fetch origin main)..."
$fetchOutput = git fetch origin main 2>&1
$fetchOutput | ForEach-Object { Write-Host "  $_" }
if ($LASTEXITCODE -ne 0) {
    Write-Fail "git fetch завершился с ошибкой."
    Invoke-Rollback $backupHash
    exit 2
}
Write-Ok "git fetch выполнен успешно."

Write-Step "Применение обновлений (git reset --hard origin/main)..."
$resetOutput = git reset --hard origin/main 2>&1
$resetOutput | ForEach-Object { Write-Host "  $_" }
if ($LASTEXITCODE -ne 0) {
    Write-Fail "git reset --hard origin/main завершился с ошибкой."
    Invoke-Rollback $backupHash
    exit 2
}
Write-Ok "Локальные файлы синхронизированы с origin/main."

# 3. pip install -r requirements.txt
Write-Step "Шаг 3/4: Установка зависимостей (pip install -r requirements.txt)..."
$reqFile = Join-Path $ScriptDir 'requirements.txt'
if (-not (Test-Path $reqFile)) {
    Write-Fail "Файл requirements.txt не найден."
    Invoke-Rollback $backupHash
    exit 3
}
$pipOutput = pip install -r $reqFile 2>&1
$pipOutput | ForEach-Object { Write-Host "  $_" }
if ($LASTEXITCODE -ne 0) {
    Write-Fail "pip install завершился с ошибкой."
    Invoke-Rollback $backupHash
    exit 3
}
Write-Ok "Зависимости установлены."

# 4. Получение нового хеша для информации
$newHash = (git rev-parse HEAD 2>&1).Trim()
Write-Host "`n  Предыдущий коммит : $backupHash" -ForegroundColor DarkGray
Write-Host "  Новый коммит      : $newHash" -ForegroundColor DarkGray

Write-Host "`n============================================" -ForegroundColor Green
Write-Host "   Обновление завершено успешно!" -ForegroundColor Green
Write-Host "============================================`n" -ForegroundColor Green

# Recreate Desktop shortcuts so they survive git reset --hard
$shortcutsScript = Join-Path $ScriptDir 'create_shortcuts.ps1'
if (Test-Path $shortcutsScript) {
    try {
        & $shortcutsScript -BotDir $ScriptDir
    } catch {
        Write-Host "  INFO  Не удалось обновить ярлыки на рабочем столе: $_" -ForegroundColor Yellow
    }
}

# 5. Перезапуск bot.py
if (-not $SkipRestart) {
    Write-Step "Шаг 4/4: Перезапуск bot.py..."
    Stop-BotProcess
    Start-Sleep -Seconds 2
    Start-Bot
}

exit 0
