# DRGR VM - Quick start script
# For full launcher with Ollama: .\start.ps1
Write-Host "Starting DRGR VM..." -ForegroundColor Cyan

# Try to switch to project root (also works via IEX)
$scriptPath = $MyInvocation.MyCommand.Path
if ($scriptPath) {
    Set-Location (Split-Path -Parent $scriptPath)
} elseif (Test-Path ".\vm\server.py") {
    # Already in project root
} else {
    Write-Host "ERROR: Could not determine project directory." -ForegroundColor Red
    Write-Host "Please cd into drgr-bot and run again." -ForegroundColor Yellow
    exit 1
}

# Update from GitHub
Write-Host "Pulling latest changes from GitHub..." -ForegroundColor Yellow
git pull origin main 2>$null

# Update dependencies
Write-Host "Updating dependencies..." -ForegroundColor Yellow
pip install --upgrade typing-extensions pydantic aiohttp aiofiles --quiet 2>$null
pip install -r requirements.txt --quiet 2>$null

# Start VM server
Write-Host "VM server started on http://localhost:5000" -ForegroundColor Green
Write-Host "Web UI: http://localhost:5000" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop" -ForegroundColor Gray

python vm/server.py
