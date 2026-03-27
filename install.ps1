#Requires -Version 5.1
<#
.SYNOPSIS
    Устанавливает drgr-bot — одной командой PowerShell, без Git.

.DESCRIPTION
    Запустите в PowerShell (Win+R -> powershell):

        irm https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/install.ps1 | iex

    Скрипт автоматически:
      1. Скачает архив проекта с GitHub (без Git)
      2. Установит в папку "drgr-bot" на Рабочем столе
      3. Установит зависимости Python
      4. Создаст значок "ЗАПУСТИТЬ БОТА" на Рабочем столе
      5. Создаст значок "drgr-bot (папка)" на Рабочем столе
      6. Предложит ввести BOT_TOKEN (если ещё не задан)
      7. Предложит сразу запустить бота

    Требуется только Python 3.10+ (Git НЕ нужен):
      https://www.python.org/downloads/
      (при установке отметьте "Add Python to PATH")
#>

$ErrorActionPreference = 'Stop'

$Repo        = 'ybiytsa1983-cpu/drgr-bot'
$Branch      = 'main'
$ZipUrl      = "https://github.com/$Repo/archive/refs/heads/$Branch.zip"
$DesktopPath = [System.Environment]::GetFolderPath('Desktop')
$InstallDir  = Join-Path $DesktopPath 'drgr-bot'
$ZipFile     = Join-Path $env:TEMP 'drgr-bot-main.zip'
$ZipExtract  = Join-Path $env:TEMP "drgr-bot-$Branch"
$EnvBackup   = Join-Path $env:TEMP 'drgr_bot_env_backup.txt'
$EnvFile     = Join-Path $InstallDir '.env'

# ── Helpers ──────────────────────────────────────────────────────────────────

function Write-Step($n, $text) {
    Write-Host ''
    Write-Host "  [$n] $text" -ForegroundColor Cyan
}

function Write-OK($text) { Write-Host "      $text" -ForegroundColor Green }
function Write-Warn($text) { Write-Host "  [!] $text" -ForegroundColor Yellow }
function Write-Err($text)  { Write-Host "  [X] $text" -ForegroundColor Red }

# ── Banner ────────────────────────────────────────────────────────────────────

Write-Host ''
Write-Host '  ╔══════════════════════════════════════════╗' -ForegroundColor Cyan
Write-Host '  ║     drgr-bot  -  Установка                ║' -ForegroundColor Cyan
Write-Host '  ║     (без Git — только Python)             ║' -ForegroundColor Cyan
Write-Host '  ╚══════════════════════════════════════════╝' -ForegroundColor Cyan
Write-Host ''

# ── 1. Проверка Python ────────────────────────────────────────────────────────

Write-Step '1/6' 'Проверка Python...'
try {
    $pyVer = & python --version 2>&1
    Write-OK "Найден: $pyVer"
} catch {
    Write-Err 'Python не найден!'
    Write-Host ''
    Write-Host '  Установите Python 3.10+ со страницы:' -ForegroundColor Yellow
    Write-Host '    https://www.python.org/downloads/'  -ForegroundColor Yellow
    Write-Host '  Важно: при установке отметьте "Add Python to PATH"' -ForegroundColor Yellow
    Write-Host ''
    Read-Host '  Нажмите Enter для выхода'
    exit 1
}

# ── 2. Сохранить .env если уже установлен ────────────────────────────────────

Write-Step '2/6' 'Проверка существующей установки...'
if (Test-Path $EnvFile) {
    Copy-Item -LiteralPath $EnvFile -Destination $EnvBackup -Force
    Write-OK 'Найден токен (.env) — сохранена резервная копия.'
} else {
    Write-OK 'Новая установка.'
}

# ── 3. Скачать ZIP ────────────────────────────────────────────────────────────

Write-Step '3/6' 'Скачивание файлов с GitHub...'
Write-Host '      (это может занять 10–30 секунд)' -ForegroundColor DarkGray
try {
    Invoke-WebRequest -Uri $ZipUrl -OutFile $ZipFile -UseBasicParsing
    Write-OK 'Архив скачан.'
} catch {
    Write-Err "Не удалось скачать: $_"
    Write-Host ''
    Write-Host '  Возможные причины: нет интернета или брандмауэр.' -ForegroundColor Yellow
    Write-Host "  URL: $ZipUrl" -ForegroundColor Yellow
    Write-Host ''
    Read-Host '  Нажмите Enter для выхода'
    exit 1
}

# ── 4. Распаковать и установить ───────────────────────────────────────────────

Write-Step '4/6' "Установка в: $InstallDir"

if (Test-Path $InstallDir) {
    Write-Warn 'Удаляем старую установку...'
    Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path $InstallDir) {
        Write-Err "Не удалось удалить '$InstallDir'. Закройте открытые файлы и повторите."
        Read-Host 'Нажмите Enter для выхода'
        exit 1
    }
}

if (Test-Path $ZipExtract) {
    Remove-Item -LiteralPath $ZipExtract -Recurse -Force -ErrorAction SilentlyContinue
}

Expand-Archive -LiteralPath $ZipFile -DestinationPath $env:TEMP -Force

# GitHub именует папку внутри архива как «repo-branch»
$Extracted = Join-Path $env:TEMP "drgr-bot-$Branch"
if (-not (Test-Path $Extracted)) {
    # Fallback: ищем любую папку drgr-bot-* в TEMP
    $Extracted = Get-ChildItem $env:TEMP -Directory -Filter 'drgr-bot-*' |
                 Where-Object { $_.FullName -ne $InstallDir } |
                 Select-Object -First 1 -ExpandProperty FullName
}
if (-not $Extracted -or -not (Test-Path $Extracted)) {
    Write-Err 'Не удалось найти распакованную папку. Попробуйте повторить.'
    Read-Host 'Нажмите Enter для выхода'
    exit 1
}

Move-Item -LiteralPath $Extracted -Destination $InstallDir -Force
Remove-Item -LiteralPath $ZipFile -Force -ErrorAction SilentlyContinue
Write-OK "Файлы установлены."

# Восстановить .env
if (Test-Path $EnvBackup) {
    Copy-Item -LiteralPath $EnvBackup -Destination $EnvFile -Force
    Remove-Item -LiteralPath $EnvBackup -Force -ErrorAction SilentlyContinue
    Write-OK 'Токен (.env) восстановлен.'
}

# ── 5. Установить зависимости Python ──────────────────────────────────────────

Write-Step '5/6' 'Установка зависимостей Python...'
Write-Host '      (первый раз может занять 1–3 минуты)' -ForegroundColor DarkGray

Push-Location $InstallDir
try {
    & python -m pip install --upgrade pip --quiet 2>&1 | Out-Null
    & python -m pip install --upgrade -r requirements.txt
    Write-OK 'Зависимости установлены.'
} catch {
    Write-Warn "Некоторые пакеты не установились: $_"
    Write-Host '      Попробуйте вручную: pip install -r requirements.txt' -ForegroundColor Yellow
} finally {
    Pop-Location
}

# ── 6. BOT_TOKEN ──────────────────────────────────────────────────────────────

Write-Step '6/6' 'Настройка токена бота...'
if (-not (Test-Path $EnvFile)) {
    Write-Host ''
    Write-Host '  Для работы бота нужен токен Telegram.' -ForegroundColor Yellow
    Write-Host '  Как получить:' -ForegroundColor Yellow
    Write-Host '    1. Откройте Telegram, найдите @BotFather' -ForegroundColor Yellow
    Write-Host '    2. Отправьте /newbot и следуйте инструкциям' -ForegroundColor Yellow
    Write-Host '    3. Скопируйте токен (формат: 1234567890:AAAB...)' -ForegroundColor Yellow
    Write-Host ''
    $Token = Read-Host '  Введите BOT_TOKEN (или Enter чтобы пропустить)'
    if ($Token -and $Token -match ':') {
        "BOT_TOKEN=$Token" | Set-Content -LiteralPath $EnvFile -Encoding UTF8
        Write-OK 'Файл .env создан.'
    } elseif ($Token) {
        Write-Warn 'Токен выглядит неправильно — сохранён как введён. Проверьте .env'
        "BOT_TOKEN=$Token" | Set-Content -LiteralPath $EnvFile -Encoding UTF8
    } else {
        Write-Warn 'Токен не введён. Создайте файл .env вручную:'
        Write-Host "      $EnvFile" -ForegroundColor DarkGray
        Write-Host '      Содержимое: BOT_TOKEN=ваш_токен' -ForegroundColor DarkGray
    }
} else {
    Write-OK 'Токен (.env) уже настроен.'
}

# ── Создание значков на Рабочем столе ─────────────────────────────────────────

Write-Host ''
Write-Host '  Создание значков на Рабочем столе...' -ForegroundColor Cyan

$WShell = New-Object -ComObject WScript.Shell

# Значок «ЗАПУСТИТЬ БОТА»
try {
    $Sc = $WShell.CreateShortcut("$DesktopPath\ЗАПУСТИТЬ БОТА.lnk")
    $Sc.TargetPath       = "$InstallDir\ЗАПУСТИТЬ_БОТА.bat"
    $Sc.WorkingDirectory = $InstallDir
    $Sc.Description      = 'Запустить VM-сервер (бот управляется из веб-интерфейса)'
    $Sc.IconLocation     = "$env:SystemRoot\System32\cmd.exe,0"
    $Sc.Save()
    Write-OK 'Значок "ЗАПУСТИТЬ БОТА" создан.'
} catch {
    Write-Warn 'Не удалось создать значок «ЗАПУСТИТЬ БОТА».'
}

# Значок «drgr-bot (папка)»
try {
    $Sc2 = $WShell.CreateShortcut("$DesktopPath\drgr-bot (папка).lnk")
    $Sc2.TargetPath   = $InstallDir
    $Sc2.Description  = 'Папка проекта drgr-bot'
    $Sc2.IconLocation = "$env:SystemRoot\System32\imageres.dll,3"
    $Sc2.Save()
    Write-OK 'Значок "drgr-bot (папка)" создан.'
} catch {
    Write-Warn 'Не удалось создать значок папки.'
}

# ── Итог ──────────────────────────────────────────────────────────────────────

Write-Host ''
Write-Host '  ╔══════════════════════════════════════════╗' -ForegroundColor Green
Write-Host '  ║       Установка завершена успешно!        ║' -ForegroundColor Green
Write-Host '  ╚══════════════════════════════════════════╝' -ForegroundColor Green
Write-Host ''
Write-Host '  На Рабочем столе появились два значка:' -ForegroundColor White
Write-Host '    🟢 "ЗАПУСТИТЬ БОТА"    — запускает VM-сервер (бот управляется из веб-интерфейса)' -ForegroundColor White
Write-Host '    📁 "drgr-bot (папка)"  — открывает папку с файлами' -ForegroundColor White
Write-Host ''
Write-Host "  Папка проекта: $InstallDir" -ForegroundColor DarkGray
Write-Host '  Веб-интерфейс: http://localhost:5001' -ForegroundColor DarkGray
Write-Host ''

# ── Предложить запустить ──────────────────────────────────────────────────────

$Launch = Read-Host '  Запустить бота прямо сейчас? (да/нет)'
if ($Launch -match '^(да|д|yes|y)$') {
    Write-Host '  Запуск...' -ForegroundColor Cyan
    Start-Process -FilePath "$InstallDir\ЗАПУСТИТЬ_БОТА.bat" -WorkingDirectory $InstallDir
} else {
    Write-Host '  Готово! Используйте значок "ЗАПУСТИТЬ БОТА" на Рабочем столе.' -ForegroundColor Green
}

Write-Host ''
