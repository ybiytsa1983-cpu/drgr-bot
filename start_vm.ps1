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
            Read-Host "Нажмите Enter для выхода"
            return
        }
        $ProjectDir = $DesktopDir
        Write-Host "Проект скачан в: $ProjectDir" -ForegroundColor Green
    }
}

Set-Location $ProjectDir

# -- Проверка Python --
$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($LASTEXITCODE -eq 0) { $pythonCmd = $cmd; break }
    } catch {}
}
if (-not $pythonCmd) {
    Write-Host ""
    Write-Host "ОШИБКА: Python не найден!" -ForegroundColor Red
    Write-Host "Установите Python 3.10+ с https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "(при установке поставьте галочку 'Add Python to PATH')" -ForegroundColor Yellow
    Read-Host "Нажмите Enter для выхода"
    return
}
Write-Host "Python: $(&$pythonCmd --version 2>&1)" -ForegroundColor Gray

# -- Обновление из GitHub --
Write-Host "Подтягивание обновлений..." -ForegroundColor Yellow
git pull origin main 2>$null

# -- Зависимости Python --
Write-Host "Установка зависимостей..." -ForegroundColor Yellow
& $pythonCmd -m pip install --upgrade typing-extensions pydantic aiohttp aiofiles 2>&1 | Where-Object { $_ -match "ERROR|error" } | ForEach-Object { Write-Host $_ -ForegroundColor Red }
& $pythonCmd -m pip install -r requirements.txt 2>&1 | Where-Object { $_ -match "ERROR|error" } | ForEach-Object { Write-Host $_ -ForegroundColor Red }

# Проверяем, что flask установлен
$flaskCheck = & $pythonCmd -c "import flask" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "ОШИБКА: flask не установлен. Пробуем установить вручную..." -ForegroundColor Red
    & $pythonCmd -m pip install flask flask-cors requests
    $flaskCheck2 = & $pythonCmd -c "import flask" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Не удалось установить flask. Сервер не запустится." -ForegroundColor Red
        Read-Host "Нажмите Enter для выхода"
        return
    }
}

# -- Удаляем старый ярлык DRGR.bat если он есть (содержал буквальный путь "...") --
$OldBatShortcut = "$HOME\Desktop\DRGR.bat"
if (Test-Path $OldBatShortcut) {
    Remove-Item $OldBatShortcut -Force -ErrorAction SilentlyContinue
    Write-Host "Старый ярлык DRGR.bat удалён." -ForegroundColor Gray
}

# -- Ярлык Code VM на рабочем столе (всегда обновляем путь) --
$CodeVmShortcut = "$HOME\Desktop\Code VM.lnk"
try {
    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut($CodeVmShortcut)
    $Shortcut.TargetPath = "powershell.exe"
    $Shortcut.Arguments = "-ExecutionPolicy Bypass -NoProfile -WindowStyle Normal -File `"$ProjectDir\start_vm.ps1`""
    $Shortcut.WorkingDirectory = $ProjectDir
    $Shortcut.WindowStyle = 1
    $Shortcut.Description = "DRGR Code VM"
    $Shortcut.Save()
    Write-Host "Ярлык обновлён: $CodeVmShortcut" -ForegroundColor Green
} catch {
    Write-Host "Предупреждение: не удалось создать ярлык: $_" -ForegroundColor Yellow
}

# -- Подсказка по расширению Chrome --
Write-Host ""
Write-Host "--- Chrome-расширение DRGR VM ---" -ForegroundColor Cyan
Write-Host "Чтобы использовать расширение в браузере:" -ForegroundColor White
Write-Host "  1. Откройте Chrome -> chrome://extensions" -ForegroundColor Gray
Write-Host "  2. Включите 'Режим разработчика' (Developer mode)" -ForegroundColor Gray
Write-Host "  3. Нажмите 'Загрузить распакованное' -> выберите папку:" -ForegroundColor Gray
Write-Host "     $ProjectDir\extension" -ForegroundColor Yellow
Write-Host "  4. Расширение появится на панели браузера" -ForegroundColor Gray
Write-Host ""
Write-Host "  ИЛИ просто откройте: http://localhost:$Port" -ForegroundColor Green
Write-Host ""

# -- Запуск сервера --
$env:DRGR_PORT = $Port
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

& $pythonCmd "$ProjectDir\vm\server.py"

# Если сервер завершился -- показываем сообщение (не закрываем окно сразу)
Write-Host ""
Write-Host "Сервер завершил работу (код выхода: $LASTEXITCODE)." -ForegroundColor Yellow
Write-Host "Если сервер упал с ошибкой -- прокрутите лог вверх." -ForegroundColor Gray
Read-Host "Нажмите Enter для закрытия"
