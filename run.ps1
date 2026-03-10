# Code VM -- bootstrap / one-liner installer.
# Usage (from any PowerShell window -- no repo needed):
#   irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/copilot/create-monaco-code-generator/run.ps1" | iex
#
# Steps:
#   1. Checks that Git is installed.
#   2. Clones or updates the drgr-bot repository to $HOME\drgr-bot.
#   3. Runs install.ps1 from the cloned repo.

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

# --- Ensure we have the full codebase (main may be empty before PR merge) ---
# If install.ps1 is absent, fetch all remote branches and checkout the first
# one that contains it.  This is fully automatic and handles both pre-merge
# (code lives on a dev branch) and post-merge (code lives on main) scenarios.
$installScript = Join-Path $repoDir "install.ps1"
if (-not (Test-Path $installScript)) {
    Write-Host ""
    Write-Host "  The default branch appears incomplete — searching all branches for the full code..." -ForegroundColor Yellow
    Push-Location $repoDir
    try {
        # Fetch every remote branch (non-fatal — we may still have what we need locally)
        $fetchOutput = & git fetch --all 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  Warning: git fetch failed — trying locally cached branches." -ForegroundColor Yellow
        }
        $remoteBranches = & git branch -r 2>&1 |
            Where-Object { $_ -notmatch 'HEAD' } |
            ForEach-Object { $_.Trim() -replace '^origin/', '' }
        $found = $false
        foreach ($branch in $remoteBranches) {
            if ($branch -eq 'main') { continue }   # already tried main
            $checkoutOutput = & git checkout -B $branch "origin/$branch" --quiet 2>&1
            if ($LASTEXITCODE -ne 0) { continue }   # branch not accessible — try next
            if (Test-Path $installScript) {
                Write-Host "  Found full code on branch: $branch" -ForegroundColor Green
                $found = $true
                break
            }
        }
        if (-not $found) {
            Write-Host ""
            Write-Host "  ERROR: Could not find install.ps1 in any branch." -ForegroundColor Red
            Write-Host "  Please try again in a few minutes, or visit:" -ForegroundColor Yellow
            Write-Host "    https://github.com/ybiytsa1983-cpu/drgr-bot" -ForegroundColor Cyan
            exit 1
        }
    } finally {
        Pop-Location
    }
}

# --- Run install ---
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
