# DRGR VM quick launcher
# For full launcher with Ollama checks: .\start.ps1

$repoUrl = "https://github.com/ybiytsa1983-cpu/drgr-bot.git"
$defaultBranch = "main"
$desktopDir = [Environment]::GetFolderPath("Desktop")
$defaultInstallDir = Join-Path $desktopDir "drgr-bot"

Write-Host "Starting DRGR VM..." -ForegroundColor Cyan

function Test-ProjectDir([string]$dir) {
    if (-not $dir) { return $false }
    return (Test-Path (Join-Path $dir "vm\server.py")) -and (Test-Path (Join-Path $dir "requirements.txt"))
}

function Find-ProjectDir {
    $candidates = @()
    $scriptPath = $MyInvocation.MyCommand.Path
    if ($scriptPath) { $candidates += (Split-Path -Parent $scriptPath) }
    $candidates += (Get-Location).Path
    $candidates += $defaultInstallDir

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (Test-ProjectDir $candidate) { return $candidate }
    }
    return $null
}

function Ensure-InstallDir {
    if (Test-ProjectDir $defaultInstallDir) {
        return $defaultInstallDir
    }

    Write-Host "Project folder not found. Installing to: $defaultInstallDir" -ForegroundColor Yellow

    if (Test-Path $defaultInstallDir) {
        if (-not (Test-Path (Join-Path $defaultInstallDir ".git"))) {
            Write-Host "ERROR: Folder exists but is not a git repo: $defaultInstallDir" -ForegroundColor Red
            Write-Host "Delete or rename this folder, then run again." -ForegroundColor Yellow
            exit 1
        }
        Write-Host "Updating existing repo..." -ForegroundColor Yellow
        git -C $defaultInstallDir fetch origin $defaultBranch 2>$null
        git -C $defaultInstallDir reset --hard "origin/$defaultBranch" 2>$null
    }
    else {
        Write-Host "Cloning repo..." -ForegroundColor Yellow
        git clone $repoUrl $defaultInstallDir
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ERROR: Failed to clone repository." -ForegroundColor Red
            exit 1
        }
    }

    if (-not (Test-ProjectDir $defaultInstallDir)) {
        Write-Host "ERROR: Installation completed, but required files are missing." -ForegroundColor Red
        exit 1
    }

    return $defaultInstallDir
}

$projectDir = Find-ProjectDir
if (-not $projectDir) {
    $projectDir = Ensure-InstallDir
}

Set-Location $projectDir
Write-Host "Working directory: $projectDir" -ForegroundColor DarkGray

# Update from GitHub when repository metadata exists
if (Test-Path ".git") {
    Write-Host "Pulling latest changes from GitHub..." -ForegroundColor Yellow
    git pull origin $defaultBranch 2>$null
}

# Resolve Python command
$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        & $cmd --version *> $null
        if ($LASTEXITCODE -eq 0) {
            $pythonCmd = $cmd
            break
        }
    } catch {}
}

if (-not $pythonCmd) {
    Write-Host "ERROR: Python is not installed or not in PATH." -ForegroundColor Red
    exit 1
}

# Update dependencies
Write-Host "Updating dependencies..." -ForegroundColor Yellow
& $pythonCmd -m pip install --upgrade typing-extensions pydantic aiohttp aiofiles --quiet 2>$null
& $pythonCmd -m pip install -r requirements.txt --quiet 2>$null

# Start VM server
if (-not (Test-Path ".\vm\server.py")) {
    Write-Host "ERROR: vm\\server.py not found in $((Get-Location).Path)" -ForegroundColor Red
    exit 1
}

Write-Host "VM server starting on http://localhost:5000" -ForegroundColor Green
Write-Host "Web UI: http://localhost:5000" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop" -ForegroundColor Gray

& $pythonCmd vm/server.py
