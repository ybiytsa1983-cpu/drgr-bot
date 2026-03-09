<#
.SYNOPSIS
    Code VM — bootstrap / one-liner installer.
    Usage (from any PowerShell window — no repo needed):
        irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/run.ps1" | iex

.DESCRIPTION
    1. Checks that Git is installed.
    2. Clones or updates the drgr-bot repository to $HOME\drgr-bot.
    3. Runs install.ps1 from the cloned repo.
#>

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Code VM — Bootstrap" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# --- Git check ---
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Git is not installed." -ForegroundColor Red
    Write-Host ""
    Write-Host "Install Git first:" -ForegroundColor Yellow
    Write-Host "  https://git-scm.com/download/win" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Then re-run this command." -ForegroundColor Yellow
    Write-Host ""
    pause
    exit 1
}

# --- Clone or pull ---
$repoDir = Join-Path $env:USERPROFILE "drgr-bot"
$repoUrl = "https://github.com/ybiytsa1983-cpu/drgr-bot"

if (Test-Path (Join-Path $repoDir ".git")) {
    Write-Host "Repository already exists — running git pull..." -ForegroundColor Green
    Push-Location $repoDir
    try {
        git pull
    } finally {
        Pop-Location
    }
} else {
    Write-Host "Cloning repository to: $repoDir" -ForegroundColor Green
    Push-Location $env:USERPROFILE
    try {
        git clone $repoUrl
    } finally {
        Pop-Location
    }
}

# --- Run install ---
$installScript = Join-Path $repoDir "install.ps1"
if (-not (Test-Path $installScript)) {
    Write-Host "ERROR: install.ps1 not found at $installScript" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Running install.ps1..." -ForegroundColor Green
Write-Host ""
# Allow local scripts for this process session (needed when invoked via irm | iex)
Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process -Force
& $installScript
