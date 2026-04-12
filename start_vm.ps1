# DRGR Code VM -- Скрипт запуска
# Работает и как локальный файл, и через irm ... | iex
# Для полного лаунчера с Ollama: .\start.ps1

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Port = 5000
$RepoUrl = "https://github.com/ybiytsa1983-cpu/drgr-bot.git"

Write-Host ""
Write-Host "=== DRGR Code VM ===" -ForegroundColor Cyan
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

# -- Ярлык Code VM на рабочем столе (всегда обновляем путь) --
$CodeVmShortcut = "$HOME\Desktop\Code VM.lnk"
try {
    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut($CodeVmShortcut)
    $Shortcut.TargetPath = "powershell.exe"
    $Shortcut.Arguments = "-ExecutionPolicy Bypass -NoProfile -File `"$ProjectDir\start_vm.ps1`""
    $Shortcut.WorkingDirectory = $ProjectDir
    $Shortcut.Description = "DRGR Code VM"
    $Shortcut.Save()
    Write-Host "Ярлык обновлён: $CodeVmShortcut" -ForegroundColor Green
} catch {
    Write-Host "Предупреждение: не удалось создать ярлык: $_" -ForegroundColor Yellow
}

# -- Запуск сервера --
$env:DRGR_PORT = $Port
Write-Host ""
Write-Host "DRGR Code VM: http://localhost:$Port" -ForegroundColor Green
Write-Host "Ctrl+C -- остановка" -ForegroundColor Gray
Write-Host ""

# Открываем браузер через 2 секунды, пока сервер стартует
$vmUrl = "http://localhost:$Port"
Start-Job -ScriptBlock {
    param($u)
    Start-Sleep 2
    Start-Process $u
} -ArgumentList $vmUrl | Out-Null

python "$ProjectDir\vm\server.py"
