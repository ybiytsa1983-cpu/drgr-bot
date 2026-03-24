#Requires -Version 5.1
<#
.SYNOPSIS
    Первичная установка drgr-bot (PowerShell-версия).
.DESCRIPTION
    Скачайте этот файл и запустите в PowerShell:

        Set-ExecutionPolicy -Scope Process Bypass
        .\install.ps1

    Скрипт выполнит:
      1. Проверку Python и Git
      2. Клонирование репозитория на Рабочий стол
      3. Установку зависимостей Python
      4. Создание файла .env с токеном бота
      5. Создание ярлыков "DRGR Bot.lnk" прямо на Рабочем столе
      6. Предложит сразу запустить бота
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$DEST = Join-Path $env:USERPROFILE 'Desktop\drgr-bot'
$REPO = 'https://github.com/ybiytsa1983-cpu/drgr-bot.git'

# ── вспомогательные функции ────────────────────────────────────────────────

function Write-Step([string]$msg) {
    Write-Host "`n[SETUP] $msg" -ForegroundColor Cyan
}

function Write-Ok([string]$msg) {
    Write-Host "  OK  $msg" -ForegroundColor Green
}

function Write-Fail([string]$msg) {
    Write-Host "  FAIL  $msg" -ForegroundColor Red
}

function Write-Info([string]$msg) {
    Write-Host "  INFO  $msg" -ForegroundColor Yellow
}

# ── шапка ─────────────────────────────────────────────────────────────────

Write-Host "`n+----------------------------------------------+" -ForegroundColor Magenta
Write-Host "|        drgr-bot  -  Мастер установки         |" -ForegroundColor Magenta
Write-Host "+----------------------------------------------+`n" -ForegroundColor Magenta

# ── 1. Проверка Python ────────────────────────────────────────────────────

Write-Step "[1/5] Проверка Python..."
try {
    $pyVer = python --version 2>&1
    Write-Ok "Найден: $pyVer"
} catch {
    Write-Fail "Python не найден!"
    Write-Host ""
    Write-Host "  Установите Python 3.10 или новее:" -ForegroundColor Yellow
    Write-Host "    https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "  Убедитесь, что при установке отмечена галочка 'Add Python to PATH'." -ForegroundColor Yellow
    Read-Host "`n  Нажмите Enter для выхода"
    exit 1
}

# ── 2. Проверка Git ───────────────────────────────────────────────────────

Write-Step "[2/5] Проверка Git..."
try {
    $gitVer = git --version 2>&1
    Write-Ok "Найден: $gitVer"
} catch {
    Write-Fail "Git не найден!"
    Write-Host ""
    Write-Host "  Установите Git for Windows:" -ForegroundColor Yellow
    Write-Host "    https://git-scm.com/download/win" -ForegroundColor Yellow
    Read-Host "`n  Нажмите Enter для выхода"
    exit 1
}

# ── 3. Клонирование / обновление репозитория ─────────────────────────────

Write-Step "[3/5] Подготовка репозитория в $DEST..."

if (Test-Path (Join-Path $DEST '.git')) {
    Write-Info "Папка уже существует. Обновляем..."
    Set-Location $DEST
    git fetch origin main 2>&1 | Out-Null
    $resetOut = git reset --hard origin/main 2>&1
    $resetOut | ForEach-Object { Write-Host "  $_" }
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Не удалось обновить репозиторий."
        Read-Host "  Нажмите Enter для выхода"
        exit 1
    }
    Write-Ok "Репозиторий обновлён."
} elseif (Test-Path $DEST) {
    Write-Fail "Папка '$DEST' уже существует, но не является git-репозиторием."
    Write-Host "  Переименуйте или удалите её вручную и запустите снова." -ForegroundColor Yellow
    Read-Host "  Нажмите Enter для выхода"
    exit 1
} else {
    $cloneOut = git clone $REPO $DEST 2>&1
    $cloneOut | ForEach-Object { Write-Host "  $_" }
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Не удалось клонировать репозиторий. Проверьте подключение к интернету."
        Read-Host "  Нажмите Enter для выхода"
        exit 1
    }
    Write-Ok "Репозиторий успешно склонирован."
}

Set-Location $DEST

# ── 4. Зависимости Python ─────────────────────────────────────────────────

Write-Step "[4/5] Установка зависимостей Python..."
$pipOut = pip install --upgrade -r requirements.txt 2>&1
$pipOut | ForEach-Object { Write-Host "  $_" }
if ($LASTEXITCODE -ne 0) {
    Write-Info "Некоторые зависимости не установились. Попробуйте позже вручную: pip install -r requirements.txt"
} else {
    Write-Ok "Зависимости установлены."
}

# ── 5. Файл .env ──────────────────────────────────────────────────────────

Write-Step "[5/5] Настройка файла .env..."
$envFile = Join-Path $DEST '.env'

if (Test-Path $envFile) {
    Write-Ok "Файл .env уже существует. Используем его."
    Write-Info "(Чтобы изменить токен — откройте .env в блокноте)"
} else {
    Write-Host ""
    Write-Host "  Файл .env не найден. Нужно ввести токен Telegram-бота." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Как получить токен:" -ForegroundColor Gray
    Write-Host "    1. Откройте Telegram и найдите @BotFather" -ForegroundColor Gray
    Write-Host "    2. Отправьте /newbot и следуйте инструкциям" -ForegroundColor Gray
    Write-Host "    3. Скопируйте токен вида: 1234567890:AABBccDDeeFFggHH..." -ForegroundColor Gray
    Write-Host ""
    $botToken = Read-Host "  Введите BOT_TOKEN"

    if ([string]::IsNullOrWhiteSpace($botToken)) {
        Write-Fail "Токен не введён. Создайте файл .env вручную:"
        Write-Host "    Откройте Блокнот, напишите: BOT_TOKEN=ваш_токен" -ForegroundColor Yellow
        Write-Host "    Сохраните как: $envFile" -ForegroundColor Yellow
        Read-Host "`n  Нажмите Enter для выхода"
        exit 1
    }

    "BOT_TOKEN=$botToken" | Set-Content -Encoding UTF8 $envFile
    Write-Ok "Файл .env создан."
}

# ── Создание ярлыков на Рабочем столе ────────────────────────────────────

Write-Host ""
Write-Host "  Создание ярлыков на Рабочем столе..." -ForegroundColor Cyan
$shortcutsScript = Join-Path $DEST 'create_shortcuts.ps1'
if (Test-Path $shortcutsScript) {
    try {
        & $shortcutsScript -BotDir $DEST
    } catch {
        Write-Info "Не удалось создать ярлыки: $_"
        Write-Info "Запускайте бота из папки: $DEST"
    }
} else {
    Write-Info "create_shortcuts.ps1 не найден — ярлыки не созданы."
}

# ── Итог ──────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "+----------------------------------------------+" -ForegroundColor Green
Write-Host "|       Установка завершена успешно!           |" -ForegroundColor Green
Write-Host "|  Ярлыки созданы прямо на Рабочем столе:     |" -ForegroundColor Green
Write-Host '|    "DRGR Bot.lnk"          - запуск бота    |' -ForegroundColor Green
Write-Host '|    "DRGR Bot - Obnovit.lnk" - обновление    |' -ForegroundColor Green
Write-Host "+----------------------------------------------+" -ForegroundColor Green
Write-Host ""
Write-Host "  Папка проекта: $DEST" -ForegroundColor Gray
Write-Host ""

# ── Предлагаем запустить бота ─────────────────────────────────────────────

do {
    $launch = Read-Host "  Запустить бота прямо сейчас? (да/нет)"
    $launch = $launch.Trim().ToLower()
} while ($launch -notin @('да','д','yes','y','нет','н','no','n'))

if ($launch -in @('да','д','yes','y')) {
    Write-Host ""
    Write-Host "  Запуск VM-сервера и Telegram-бота..." -ForegroundColor Cyan
    $launchBat = Join-Path $DEST 'ЗАПУСТИТЬ_БОТА.bat'
    if (Test-Path $launchBat) {
        Start-Process 'cmd.exe' -ArgumentList "/c `"$launchBat`"" -WorkingDirectory $DEST
    } else {
        Write-Info "ЗАПУСТИТЬ_БОТА.bat не найден. Запустите вручную из $DEST"
    }
} else {
    Write-Host ""
    Write-Host '  Готово! Дважды кликните ярлык "DRGR Bot.lnk" на Рабочем столе для запуска.' -ForegroundColor Cyan
    Write-Host ""
}

Read-Host "  Нажмите Enter для закрытия"
