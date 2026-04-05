# DRGR VM - Скрипт запуска (быстрый)
# Для полного лаунчера с Ollama: .\start.ps1
Write-Host "🚀 Запуск DRGR VM..." -ForegroundColor Cyan

# Пытаемся перейти в корень проекта (работает и при запуске через IEX)
$scriptPath = $MyInvocation.MyCommand.Path
if ($scriptPath) {
    Set-Location (Split-Path -Parent $scriptPath)
} elseif (Test-Path ".\vm\server.py") {
    # Уже в корне проекта
} else {
    Write-Host "❌ Не удалось определить папку проекта." -ForegroundColor Red
    Write-Host "   Перейдите в папку drgr-bot и запустите снова." -ForegroundColor Yellow
    exit 1
}

# Обновление из GitHub
Write-Host "📥 Подтягивание изменений из GitHub..." -ForegroundColor Yellow
git pull origin main 2>$null

# Обновление зависимостей
Write-Host "📦 Обновление зависимостей..." -ForegroundColor Yellow
pip install --upgrade typing-extensions pydantic aiohttp aiofiles --quiet 2>$null
pip install -r requirements.txt --quiet 2>$null

# Запуск VM сервера
Write-Host "✅ Запуск VM сервера на http://localhost:5000" -ForegroundColor Green
Write-Host "   Веб-интерфейс: http://localhost:5000" -ForegroundColor Cyan
Write-Host "   Ctrl+C — остановка" -ForegroundColor Gray

python vm/server.py
