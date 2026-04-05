# DRGR VM - Quick start script
# For full launcher with Ollama: .\start.ps1
Write-Host "Starting DRGR VM..." -ForegroundColor Cyan

# Resolve project directory robustly (script can be downloaded to %TEMP%)
$projectDir = $null
$candidates = @()

$scriptPath = $MyInvocation.MyCommand.Path
if ($scriptPath) {
    $candidates += (Split-Path -Parent $scriptPath)
}
$candidates += (Get-Location).Path

foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path (Join-Path $candidate "vm\server.py")) -and (Test-Path (Join-Path $candidate "requirements.txt"))) {
        $projectDir = $candidate
        break
    }
}

if (-not $projectDir) {
    Write-Host "ERROR: Could not find drgr-bot project directory." -ForegroundColor Red
    Write-Host "Run this script from the drgr-bot folder (where requirements.txt and vm\\server.py exist)." -ForegroundColor Yellow
    exit 1
}

Set-Location $projectDir

# Update from GitHub
Write-Host "Pulling latest changes from GitHub..." -ForegroundColor Yellow
git pull origin main 2>$null

# Update dependencies
Write-Host "Updating dependencies..." -ForegroundColor Yellow
pip install --upgrade typing-extensions pydantic aiohttp aiofiles --quiet 2>$null
pip install -r requirements.txt --quiet 2>$null

# Start VM server
if (-not (Test-Path ".\vm\server.py")) {
    Write-Host "ERROR: vm\\server.py not found in $((Get-Location).Path)" -ForegroundColor Red
    exit 1
}

Write-Host "VM server started on http://localhost:5000" -ForegroundColor Green
Write-Host "Web UI: http://localhost:5000" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop" -ForegroundColor Gray

python vm/server.py
