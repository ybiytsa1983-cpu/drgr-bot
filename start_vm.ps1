# DRGR VM - Скрипт запуска
Write-Host "🚀 Запуск DRGR VM..." -ForegroundColor Cyan

# Обновление из GitHub
Write-Host "📥 Подтягивание изменений из GitHub..." -ForegroundColor Yellow
git pull origin main

# Обновление зависимостей
Write-Host "📦 Обновление зависимостей..." -ForegroundColor Yellow
pip install --upgrade typing-extensions pydantic aiohttp aiofiles
pip install -r requirements.txt

# Запуск VM сервера
Write-Host "✅ Запуск VM сервера на http://localhost:5001" -ForegroundColor Green
Write-Host "Нажмите Ctrl+C для остановки" -ForegroundColor Gray

python vm/server.py
