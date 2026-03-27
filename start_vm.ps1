# DRGR VM - Скрипт запуска
param(
    [switch]$BotOnly,
    [switch]$VmOnly
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "`n============================================" -ForegroundColor Cyan
Write-Host "   drgr-bot — Запуск (start_vm.ps1)" -ForegroundColor Cyan
Write-Host "============================================`n" -ForegroundColor Cyan

# Проверка ключевых файлов
if (-not (Test-Path (Join-Path $ScriptDir 'bot.py'))) {
    Write-Host "  [ОШИБКА] bot.py не найден в $ScriptDir" -ForegroundColor Red
    Write-Host "  Запустите УСТАНОВИТЬ.bat или ПОЧИНИТЬ.bat для восстановления." -ForegroundColor Yellow
    Read-Host "  Нажмите Enter для выхода"
    exit 1
}
if (-not (Test-Path (Join-Path $ScriptDir 'vm\server.py'))) {
    Write-Host "  [ОШИБКА] vm\server.py не найден в $ScriptDir" -ForegroundColor Red
    Write-Host "  Запустите УСТАНОВИТЬ.bat или ПОЧИНИТЬ.bat для восстановления." -ForegroundColor Yellow
    Read-Host "  Нажмите Enter для выхода"
    exit 1
}
if (-not (Test-Path (Join-Path $ScriptDir '.env'))) {
    Write-Host "  [ОШИБКА] Файл .env не найден!" -ForegroundColor Red
    Write-Host "  Создайте файл .env с содержимым: BOT_TOKEN=ваш_токен" -ForegroundColor Yellow
    Read-Host "  Нажмите Enter для выхода"
    exit 1
}

# Обновление из GitHub
Write-Host "  Обновление из GitHub..." -ForegroundColor Yellow
try {
    $null = git fetch origin main 2>&1
    if ($LASTEXITCODE -eq 0) {
        $null = git reset --hard origin/main 2>&1
        $hash = (git rev-parse --short HEAD 2>&1).Trim()
        Write-Host "  Обновлено до коммита: $hash" -ForegroundColor Green
    } else {
        Write-Host "  [ПРЕДУПРЕЖДЕНИЕ] Нет доступа к GitHub. Запускаем текущую версию." -ForegroundColor Yellow
    }
} catch {
    Write-Host "  [ПРЕДУПРЕЖДЕНИЕ] Git недоступен. Запускаем текущую версию." -ForegroundColor Yellow
}

# Обновление зависимостей
Write-Host "`n  Обновление зависимостей..." -ForegroundColor Yellow
pip install --upgrade -r (Join-Path $ScriptDir 'requirements.txt') 2>&1 | ForEach-Object {
    if ($_ -match 'error|ERROR') { Write-Host "  $_" -ForegroundColor Red }
}
Write-Host "  Зависимости обновлены." -ForegroundColor Green

# Запуск VM сервера
if (-not $BotOnly) {
    Write-Host "`n  Запуск VM сервера (порт 5000)..." -ForegroundColor Cyan
    Start-Process -FilePath 'python' `
        -ArgumentList "`"$(Join-Path $ScriptDir 'vm\server.py')`"" `
        -WorkingDirectory $ScriptDir `
        -WindowStyle Normal
    Start-Sleep -Seconds 3
    Write-Host "  VM сервер запущен: http://localhost:5000" -ForegroundColor Green
}

# Запуск бота
if (-not $VmOnly) {
    Write-Host "`n  Запуск Telegram бота..." -ForegroundColor Cyan
    Start-Process -FilePath 'python' `
        -ArgumentList "`"$(Join-Path $ScriptDir 'bot.py')`"" `
        -WorkingDirectory $ScriptDir `
        -WindowStyle Normal
    Write-Host "  Telegram бот запущен." -ForegroundColor Green
}

Write-Host "`n============================================" -ForegroundColor Green
Write-Host "   Запуск выполнен успешно!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Веб-интерфейс VM: http://localhost:5000" -ForegroundColor Cyan
Write-Host "  Для обновления запустите: ОБНОВИТЬ.bat`n" -ForegroundColor Cyan
