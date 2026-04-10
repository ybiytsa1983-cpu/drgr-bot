# DRGR VM - Скрипт запуска (быстрый)
# Для полного лаунчера с Ollama: .\start.ps1
Write-Host "🚀 Запуск DRGR VM..." -ForegroundColor Cyan

# cd в папку скрипта
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

# Обновление из GitHub
Write-Host "📥 Подтягивание изменений из GitHub..." -ForegroundColor Yellow
git pull origin main 2>$null

# Обновление зависимостей
Write-Host "📦 Обновление зависимостей..." -ForegroundColor Yellow
pip install --upgrade typing-extensions pydantic aiohttp aiofiles --quiet 2>$null
pip install -r requirements.txt --quiet 2>$null

# Запуск VM сервера
Write-Host "✅ Запуск VM сервера на http://localhost:5002" -ForegroundColor Green
Write-Host "   Веб-интерфейс: http://localhost:5002" -ForegroundColor Cyan
Write-Host "   Ctrl+C — остановка" -ForegroundColor Gray

python vm/server.py
