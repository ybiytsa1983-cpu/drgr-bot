#Requires -Version 5.1
<#
.SYNOPSIS
    Устанавливает и запускает drgr-bot — одной командой PowerShell, без Git.

.DESCRIPTION
    Запустите в PowerShell (Win+R -> powershell):

        irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/start_vm.ps1?$(Get-Random)" | iex

    Скрипт автоматически:
      1. Скачает все файлы проекта с GitHub (ZIP, Git НЕ нужен)
      2. Установит в папку "drgr-bot" на Рабочем столе
      3. Установит зависимости Python
      4. Создаёт ярлык "ЗАПУСТИТЬ БОТА" на Рабочем столе
      5. Создаёт ярлык "drgr-bot (папка)" на Рабочем столе
      6. Предлагает ввести BOT_TOKEN и сразу запустить

    Требуется только Python 3.10+ (Git НЕ нужен):
      https://www.python.org/downloads/
      (при установке отметьте "Add Python to PATH")
#>

$ErrorActionPreference = 'Stop'

$Repo        = 'ybiytsa1983-cpu/drgr-bot'
$Branch      = 'main'
$ZipUrl      = "https://github.com/$Repo/archive/refs/heads/$Branch.zip"
$DesktopPath = [System.Environment]::GetFolderPath('Desktop')
$DesktopFallback = Join-Path $env:USERPROFILE 'Desktop'
$DesktopCandidates = @($DesktopPath, $DesktopFallback) |
    Where-Object { $_ } |
    Select-Object -Unique

$InstallBase = $DesktopCandidates |
    Where-Object { Test-Path $_ } |
    Select-Object -First 1

if (-not $InstallBase) {
    $InstallBase = $DesktopFallback
    New-Item -ItemType Directory -Path $InstallBase -Force | Out-Null
}

$InstallDir  = Join-Path $InstallBase 'drgr-bot'
$ZipFile     = Join-Path $env:TEMP 'drgr-bot-main.zip'
$EnvBackup   = Join-Path $env:TEMP 'drgr_bot_env_backup.txt'
$EnvFile     = Join-Path $InstallDir '.env'

function Write-Step($n, $text) {
    Write-Host ''
    Write-Host "  [$n] $text" -ForegroundColor Cyan
}
function Write-OK($text)   { Write-Host "      $text" -ForegroundColor Green }
function Write-Warn($text) { Write-Host "  [!] $text" -ForegroundColor Yellow }
function Write-Err($text)  { Write-Host "  [X] $text" -ForegroundColor Red }

Write-Host ''
Write-Host '  +==========================================+' -ForegroundColor Cyan
Write-Host '  |   drgr-bot  -  Установка и запуск        |' -ForegroundColor Cyan
Write-Host '  |   (без Git -- только Python)              |' -ForegroundColor Cyan
Write-Host '  +==========================================+' -ForegroundColor Cyan
Write-Host ''

# 1. Python
Write-Step '1/6' 'Проверка Python...'
try {
    $pyVer = & python --version 2>&1
    Write-OK "Найден: $pyVer"
} catch {
    Write-Err 'Python не найден!'
    Write-Host '  Установите Python 3.10+ со страницы:' -ForegroundColor Yellow
    Write-Host '    https://www.python.org/downloads/'  -ForegroundColor Yellow
    Write-Host '  Важно: при установке отметьте "Add Python to PATH"' -ForegroundColor Yellow
    Read-Host '  Нажмите Enter для выхода'
    exit 1
}

# 2. Backup .env
Write-Step '2/6' 'Проверка существующей установки...'
if (Test-Path $EnvFile) {
    Copy-Item -LiteralPath $EnvFile -Destination $EnvBackup -Force
    Write-OK 'Найден токен (.env) -- сохранена резервная копия.'
} else {
    Write-OK 'Новая установка.'
}

# 3. Download ZIP
Write-Step '3/6' 'Скачивание файлов с GitHub...'
Write-Host '      (это может занять 10-30 секунд)' -ForegroundColor DarkGray
try {
    Invoke-WebRequest -Uri $ZipUrl -OutFile $ZipFile -UseBasicParsing
    Write-OK 'Архив скачан.'
} catch {
    Write-Err "Не удалось скачать: $_"
    Write-Host '  Нет интернета или брандмауэр блокирует запрос.' -ForegroundColor Yellow
    Read-Host '  Нажмите Enter для выхода'
    exit 1
}

# 4. Extract
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

$ZipExtract = Join-Path $env:TEMP "drgr-bot-$Branch"
if (Test-Path $ZipExtract) {
    Remove-Item -LiteralPath $ZipExtract -Recurse -Force -ErrorAction SilentlyContinue
}

Expand-Archive -LiteralPath $ZipFile -DestinationPath $env:TEMP -Force

$Extracted = Join-Path $env:TEMP "drgr-bot-$Branch"
if (-not (Test-Path $Extracted)) {
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
Write-OK 'Файлы установлены.'

if (Test-Path $EnvBackup) {
    Copy-Item -LiteralPath $EnvBackup -Destination $EnvFile -Force
    Remove-Item -LiteralPath $EnvBackup -Force -ErrorAction SilentlyContinue
    Write-OK 'Токен (.env) восстановлен.'
}

# 5. Install deps
Write-Step '5/6' 'Установка зависимостей Python...'
Write-Host '      (первый раз может занять 1-3 минуты)' -ForegroundColor DarkGray
Push-Location $InstallDir
try {
    & python -m pip install --upgrade pip --quiet 2>&1 | Out-Null
    & python -m pip install --upgrade -r requirements.txt
    Write-OK 'Зависимости установлены.'
} catch {
    Write-Warn "Некоторые пакеты не установились. Попробуйте: pip install -r requirements.txt"
} finally {
    Pop-Location
}

# 6. BOT_TOKEN
Write-Step '6/6' 'Настройка токена бота...'
if (-not (Test-Path $EnvFile)) {
    Write-Host ''
    Write-Host '  Для работы бота нужен токен Telegram.' -ForegroundColor Yellow
    Write-Host '    1. Откройте Telegram, найдите @BotFather' -ForegroundColor Yellow
    Write-Host '    2. Отправьте /newbot и следуйте инструкциям' -ForegroundColor Yellow
    Write-Host '    3. Скопируйте токен (формат: 1234567890:AAAB...)' -ForegroundColor Yellow
    Write-Host ''
    $Token = Read-Host '  Введите BOT_TOKEN (или Enter чтобы пропустить)'
    if ($Token) {
        "BOT_TOKEN=$Token" | Set-Content -LiteralPath $EnvFile -Encoding UTF8
        Write-OK 'Файл .env создан.'
    } else {
        Write-Warn 'Токен не введён. Создайте .env вручную: BOT_TOKEN=ваш_токен'
    }
} else {
    Write-OK 'Токен (.env) уже настроен.'
}

# Shortcuts + совместимые BAT-запускатели на рабочем столе
Write-Host ''
Write-Host '  Создание ярлыков и BAT-запускателей на Рабочем столе...' -ForegroundColor Cyan
$WShell = New-Object -ComObject WScript.Shell

$ShortcutDesktopCandidates = @($InstallBase, $DesktopPath, $DesktopFallback) |
    Where-Object { $_ } |
    Select-Object -Unique

$InstallDirBatSafe = $InstallDir.Replace('"', '""')
$InstallDirBatSafe = $InstallDirBatSafe.Replace('%', '%%')
$InstallDirPsSafe  = $InstallDirBatSafe.Replace('`', '``').Replace('$', '`$')

foreach ($Desktop in $ShortcutDesktopCandidates) {
    if (-not (Test-Path $Desktop)) {
        New-Item -ItemType Directory -Path $Desktop -Force | Out-Null
    }
    $DesktopLabel = if ($Desktop -eq $DesktopPath) { 'основной Рабочий стол' } else { 'альтернативный Рабочий стол (%USERPROFILE%\Desktop)' }
    $DesktopCompatDir = Join-Path $Desktop 'drgr-bot'
    $InstallDirNorm = [System.IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
    $DesktopCompatDirNorm = [System.IO.Path]::GetFullPath($DesktopCompatDir).TrimEnd('\')

    try {
        $Sc = $WShell.CreateShortcut((Join-Path $Desktop 'ЗАПУСТИТЬ БОТА.lnk'))
        $Sc.TargetPath       = "$InstallDir\ЗАПУСТИТЬ_БОТА.bat"
        $Sc.WorkingDirectory = $InstallDir
        $Sc.Description      = 'Запустить drgr-bot VM-сервер'
        $Sc.IconLocation     = "$env:SystemRoot\System32\cmd.exe,0"
        $Sc.Save()
        Write-OK "Ярлык ""ЗАПУСТИТЬ БОТА"" создан ($DesktopLabel)."
    } catch { Write-Warn "Не удалось создать ярлык запуска ($Desktop)." }

    try {
        $Sc2 = $WShell.CreateShortcut((Join-Path $Desktop 'drgr-bot (папка).lnk'))
        $Sc2.TargetPath   = $InstallDir
        $Sc2.Description  = 'Папка проекта drgr-bot'
        $Sc2.IconLocation = "$env:SystemRoot\System32\imageres.dll,3"
        $Sc2.Save()
        Write-OK "Ярлык ""drgr-bot (папка)"" создан ($DesktopLabel)."
    } catch { Write-Warn "Не удалось создать ярлык папки ($Desktop)." }

    try {
        @"
@echo off
chcp 65001 > nul
set "INSTALL_DIR=$InstallDirPsSafe"
if exist "%INSTALL_DIR%\ЗАПУСТИТЬ_БОТА.bat" (
    call "%INSTALL_DIR%\ЗАПУСТИТЬ_БОТА.bat"
) else (
    echo [ОШИБКА] Папка drgr-bot не найдена: %INSTALL_DIR%
    echo Запустите в PowerShell:
    echo   irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/start_vm.ps1?%%RANDOM%%" ^| iex
    pause
)
"@ | Set-Content -LiteralPath (Join-Path $Desktop 'ЗАПУСТИТЬ_БОТА.bat') -Encoding OEM
        Write-OK "BAT ""ЗАПУСТИТЬ_БОТА.bat"" создан ($DesktopLabel)."
    } catch { Write-Warn "Не удалось создать BAT запуска ($Desktop)." }

    try {
        @"
@echo off
chcp 65001 > nul
set "INSTALL_DIR=$InstallDirPsSafe"
if exist "%INSTALL_DIR%\ОБНОВИТЬ.bat" (
    call "%INSTALL_DIR%\ОБНОВИТЬ.bat"
) else (
    echo [ОШИБКА] Папка drgr-bot не найдена: %INSTALL_DIR%
    echo Запустите в PowerShell:
    echo   irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/start_vm.ps1?%%RANDOM%%" ^| iex
    pause
)
"@ | Set-Content -LiteralPath (Join-Path $Desktop 'ОБНОВИТЬ.bat') -Encoding OEM
        Write-OK "BAT ""ОБНОВИТЬ.bat"" создан ($DesktopLabel)."
    } catch { Write-Warn "Не удалось создать BAT обновления ($Desktop)." }

    if ($DesktopCompatDirNorm -ne $InstallDirNorm) {
        try {
            if (-not (Test-Path $DesktopCompatDir)) {
                New-Item -ItemType Directory -Path $DesktopCompatDir -Force | Out-Null
            }
            @"
@echo off
chcp 65001 > nul
set "INSTALL_DIR=$InstallDirPsSafe"
if exist "%INSTALL_DIR%\ЗАПУСТИТЬ_БОТА.bat" (
    call "%INSTALL_DIR%\ЗАПУСТИТЬ_БОТА.bat"
) else (
    echo [ОШИБКА] Папка drgr-bot не найдена: %INSTALL_DIR%
    echo Запустите в PowerShell:
    echo   irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/start_vm.ps1?%%RANDOM%%" ^| iex
    pause
)
"@ | Set-Content -LiteralPath (Join-Path $DesktopCompatDir 'ЗАПУСТИТЬ_БОТА.bat') -Encoding OEM
            Write-OK "Совместимый BAT создан: $DesktopCompatDir\ЗАПУСТИТЬ_БОТА.bat"
        } catch { Write-Warn "Не удалось создать совместимый BAT запуска ($DesktopCompatDir)." }

        try {
            @"
@echo off
chcp 65001 > nul
set "INSTALL_DIR=$InstallDirPsSafe"
if exist "%INSTALL_DIR%\ОБНОВИТЬ.bat" (
    call "%INSTALL_DIR%\ОБНОВИТЬ.bat"
) else (
    echo [ОШИБКА] Папка drgr-bot не найдена: %INSTALL_DIR%
    echo Запустите в PowerShell:
    echo   irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/start_vm.ps1?%%RANDOM%%" ^| iex
    pause
)
"@ | Set-Content -LiteralPath (Join-Path $DesktopCompatDir 'ОБНОВИТЬ.bat') -Encoding OEM
            Write-OK "Совместимый BAT создан: $DesktopCompatDir\ОБНОВИТЬ.bat"
        } catch { Write-Warn "Не удалось создать совместимый BAT обновления ($DesktopCompatDir)." }
    }
}

# Done
Write-Host ''
Write-Host '  +==========================================+' -ForegroundColor Green
Write-Host '  |      Установка завершена успешно!         |' -ForegroundColor Green
Write-Host '  +==========================================+' -ForegroundColor Green
Write-Host ''
Write-Host '  На Рабочем столе появились два ярлыка:' -ForegroundColor White
Write-Host '    "ЗАПУСТИТЬ БОТА"    -- запускает VM-сервер (бот управляется из веб-интерфейса)' -ForegroundColor White
Write-Host '    "drgr-bot (папка)"  -- открывает папку с файлами' -ForegroundColor White
Write-Host '  И совместимые BAT-файлы: "ЗАПУСТИТЬ_БОТА.bat" и "ОБНОВИТЬ.bat".' -ForegroundColor White
Write-Host ''
Write-Host "  Папка проекта: $InstallDir" -ForegroundColor DarkGray
Write-Host '  Веб-интерфейс: http://localhost:5001'     -ForegroundColor DarkGray
Write-Host ''

$Launch = Read-Host '  Запустить бота прямо сейчас? (да/нет)'
if ($Launch -match '^(да|д|yes|y)$') {
    Write-Host '  Запуск...' -ForegroundColor Cyan
    Start-Process -FilePath "$InstallDir\ЗАПУСТИТЬ_БОТА.bat" -WorkingDirectory $InstallDir
} else {
    Write-Host '  Готово! Используйте ярлык "ЗАПУСТИТЬ БОТА" на Рабочем столе.' -ForegroundColor Green
}
Write-Host ''
