# Психокоррекция -- Скрипт запуска
# Работает и как локальный файл, и через irm ... | iex
# Для полного лаунчера с Ollama: .\start.ps1

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Port = 5005
$RepoUrl = "https://github.com/ybiytsa1983-cpu/drgr-bot.git"

Write-Host ""
Write-Host "=== Психокоррекция ===" -ForegroundColor Cyan
Write-Host ""

# -- Определяем папку проекта --
$ProjectDir = $null

# 1) Если запущен как файл -- папка скрипта
if ($MyInvocation.MyCommand.Path) {
    $ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}

# 2) Если папка не определена (irm | iex) -- ищем drgr-bot
if (-not $ProjectDir -or -not (Test-Path "$ProjectDir\vm\server.py")) {
    # Проверяем текущую папку
    if (Test-Path ".\vm\server.py") {
        $ProjectDir = (Get-Location).Path
    }
    # Проверяем Desktop\drgr-bot
    elseif (Test-Path "$HOME\Desktop\drgr-bot\vm\server.py") {
        $ProjectDir = "$HOME\Desktop\drgr-bot"
    }
    # Клонируем на рабочий стол
    else {
        Write-Host "Скачивание проекта на рабочий стол..." -ForegroundColor Yellow
        $DesktopDir = "$HOME\Desktop\drgr-bot"
        git clone $RepoUrl $DesktopDir 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Ошибка: не удалось скачать проект. Проверьте интернет и Git." -ForegroundColor Red
            return
        }
        $ProjectDir = $DesktopDir
        Write-Host "Проект скачан в: $ProjectDir" -ForegroundColor Green
    }
}

Set-Location $ProjectDir

# -- Обновление из GitHub --
Write-Host "Подтягивание обновлений..." -ForegroundColor Yellow
git pull origin main 2>$null

# -- Зависимости Python --
Write-Host "Установка зависимостей..." -ForegroundColor Yellow
pip install --upgrade typing-extensions pydantic aiohttp aiofiles --quiet 2>$null
pip install -r requirements.txt --quiet 2>$null

# -- Ярлык на рабочем столе --
$ShortcutPath = "$HOME\Desktop\Психокоррекция.bat"
if (-not (Test-Path $ShortcutPath)) {
    $BatContent = "@echo off`r`ncd /d `"$ProjectDir`"`r`npowershell -ExecutionPolicy Bypass -File start_vm.ps1`r`npause"
    [System.IO.File]::WriteAllText($ShortcutPath, $BatContent, [System.Text.Encoding]::GetEncoding(1251))
    Write-Host "Ярлык создан: $ShortcutPath" -ForegroundColor Green
}

# -- Запуск сервера --
$env:DRGR_PORT = $Port
Write-Host ""
Write-Host "Психокоррекция: http://localhost:$Port" -ForegroundColor Green
Write-Host "Отдельная страница: http://localhost:$Port/psycho" -ForegroundColor Green
Write-Host "Ctrl+C -- остановка" -ForegroundColor Gray
Write-Host ""

python vm/server.py
