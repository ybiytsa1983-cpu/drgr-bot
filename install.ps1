<#
.SYNOPSIS
    First-time setup for Code VM on Windows (PowerShell).

.DESCRIPTION
    Run once after cloning the repository:
        .\install.ps1

    What it does:
      1. Checks for Python 3.8+
      2. Creates a virtual environment (.venv)
      3. Installs Python dependencies (Flask, requests)
      4. Bundles Monaco Editor locally (works without internet after this)
      5. Downloads and installs Ollama automatically
      6. Starts downloading the AI model in the background
      7. Creates a "Code VM" shortcut on your Desktop

.NOTES
    If you see "script cannot be loaded because running scripts is disabled",
    run this once to allow local scripts:
        Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
    Then re-run: .\install.ps1
#>

$ErrorActionPreference = "Stop"

# $PSScriptRoot is empty when PS is invoked without -File (e.g. some shortcuts
# or "powershell install.ps1" instead of "powershell -File install.ps1").
# Fall back to $MyInvocation, then to the current working directory.
$repoDir = if ($PSScriptRoot) {
    $PSScriptRoot
} elseif ($MyInvocation.MyCommand.Path) {
    Split-Path -Parent $MyInvocation.MyCommand.Path
} else {
    (Get-Location).Path
}
Set-Location $repoDir

# -- 0. Auto-update repo -------------------------------------------------------
# If this is a git repo, pull latest changes so old installs get fixes.
# If install.ps1 itself changed, re-exec the new version immediately so the
# user doesn't have to run the script twice to benefit from the latest fixes.
$selfPath = Join-Path $repoDir "install.ps1"
if (Test-Path (Join-Path $repoDir ".git")) {
    $hashBefore = if (Test-Path $selfPath) { (Get-FileHash $selfPath -Algorithm MD5).Hash } else { "" }
    try {
        $gitLines = & git pull 2>&1
        foreach ($line in $gitLines) {
            Write-Host "  [GIT] $line" -ForegroundColor DarkGray
        }
    } catch { }
    if ($hashBefore -ne "" -and (Test-Path $selfPath)) {
        $hashAfter = (Get-FileHash $selfPath -Algorithm MD5).Hash
        if ($hashBefore -ne $hashAfter) {
            Write-Host "  [UPDATED] install.ps1 was updated - restarting with the new version..." -ForegroundColor Cyan
            $psExe = try {
                (Get-Process -Id $PID).Path
            } catch {
                Write-Host "  [!!] Could not detect PowerShell path; falling back to powershell.exe" -ForegroundColor Yellow
                "powershell.exe"
            }
            & $psExe -ExecutionPolicy Bypass -File $selfPath @args
            exit
        }
    }
}

$venvDir = Join-Path $repoDir ".venv"

# -- Helpers -------------------------------------------------------------------
function Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Info($msg) { Write-Host "  [--] $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Err($msg)  { Write-Host "  [ERROR] $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "  =============================================" -ForegroundColor White
Write-Host "   Code VM - First-time setup (PowerShell)    " -ForegroundColor White
Write-Host "  =============================================" -ForegroundColor White
Write-Host ""

# -- 1. Find Python ------------------------------------------------------------
$python = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3\.(\d+)") {
            $minor = [int]$Matches[1]
            if ($minor -ge 8) {
                $python = $cmd
                Ok "Python found: $ver"
                break
            }
        }
    } catch { }
}

if (-not $python) {
    Err "Python 3.8+ not found."
    Write-Host ""
    Write-Host "  Download Python from:" -ForegroundColor Yellow
    Write-Host "    https://www.python.org/downloads/" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  IMPORTANT: During installation, check 'Add Python to PATH'" -ForegroundColor Yellow
    Write-Host ""
    Read-Host "  Press Enter to exit"
    exit 1
}

# -- 2. Create virtual environment ---------------------------------------------
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$venvPip    = Join-Path $venvDir "Scripts\pip.exe"

if (Test-Path $venvPython) {
    Ok "Virtual environment already exists (.venv)"
} else {
    Info "Creating virtual environment (.venv)..."
    & $python -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        Err "Failed to create virtual environment."
        Read-Host "  Press Enter to exit"
        exit 1
    }
    Ok "Virtual environment created"
}

# -- 3. Upgrade pip ------------------------------------------------------------
# Use python -m pip (not pip.exe) so Windows can replace the executable.
# 2>&1 | Out-Null merges stderr→stdout then discards all output, preventing
# $ErrorActionPreference="Stop" from aborting on a NativeCommandError.
# try/catch makes the upgrade non-fatal (a newer pip is nice but not required).
Info "Upgrading pip..."
try { & $venvPython -m pip install --upgrade pip 2>&1 | Out-Null } catch { }
Ok "pip up to date"

# -- 4. Install Flask + requests -----------------------------------------------
Info "Installing Flask + requests..."
& $venvPip install flask requests --quiet
if ($LASTEXITCODE -ne 0) {
    Err "Failed to install Flask/requests."
    Read-Host "  Press Enter to exit"
    exit 1
}
Ok "Flask + requests installed"

# -- 5. Install requirements.txt (optional extras) -----------------------------
$reqFile = Join-Path $repoDir "requirements.txt"
if (Test-Path $reqFile) {
    Info "Installing requirements.txt (Telegram bot deps)..."
    & $venvPip install -r $reqFile --quiet 2>$null
    Ok "requirements.txt processed"
}

# -- 4. Bundle Monaco Editor locally ------------------------------------------
Write-Host ""
Write-Host "  =============================================" -ForegroundColor White
Write-Host "   Bundling Monaco Editor (offline support)   " -ForegroundColor White
Write-Host "  =============================================" -ForegroundColor White
Write-Host ""

$bundleScript = Join-Path $repoDir "vm\bundle_monaco.ps1"
if (Test-Path $bundleScript) {
    Info "Bundling Monaco Editor files locally..."
    try {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $bundleScript
        Ok "Monaco Editor bundled (editor works without internet)"
    } catch {
        Warn "Monaco bundle failed - CDN fallback will be used automatically."
    }
} else {
    Warn "vm\bundle_monaco.ps1 not found - CDN fallback will be used."
}

# -- 5. Install Ollama automatically ------------------------------------------
Write-Host ""
Write-Host "  =============================================" -ForegroundColor White
Write-Host "   Ollama (AI features)                       " -ForegroundColor White
Write-Host "  =============================================" -ForegroundColor White
Write-Host ""

$ollamaInstalled = $false
try {
    $ollamaVer = & ollama --version 2>&1
    if ($LASTEXITCODE -eq 0) { $ollamaInstalled = $true }
} catch { }

if ($ollamaInstalled) {
    Ok "Ollama already installed: $ollamaVer"
} else {
    Info "Downloading Ollama installer (this may take a minute)..."
    $ollamaInstaller = Join-Path $env:TEMP "OllamaSetup.exe"
    try {
        Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" `
            -OutFile $ollamaInstaller -UseBasicParsing
        Info "Installing Ollama silently..."
        $proc = Start-Process -FilePath $ollamaInstaller `
            -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART" `
            -Wait -PassThru
        if ($proc.ExitCode -eq 0) {
            # Make ollama visible in current session PATH
            $ollamaDir = Join-Path $env:LOCALAPPDATA "Programs\Ollama"
            if (Test-Path $ollamaDir) {
                $env:PATH = "$ollamaDir;$env:PATH"
            }
            Ok "Ollama installed"
            $ollamaInstalled = $true
        } else {
            Warn "Ollama installation returned exit code $($proc.ExitCode)."
            Warn "Install manually later: https://ollama.com/download"
        }
    } catch {
        Warn "Download or install failed: $_"
        Warn "Install manually later: https://ollama.com/download"
    }
}

# -- 6. Start AI model download in background ---------------------------------
$modelName = "qwen3-vl:8b"
if ($ollamaInstalled) {
    $modelPresent = $false
    try {
        $list = & ollama list 2>&1
        # Check each line: model name should appear as the first token on a data line
        foreach ($line in ($list -split "`n")) {
            if ($line -match "^\s*$([regex]::Escape($modelName))\b") {
                $modelPresent = $true
                break
            }
        }
    } catch { }

    if ($modelPresent) {
        Ok "AI model already downloaded ($modelName)"
    } else {
        Info "Starting AI model download in background ($modelName, ~5 GB)..."
        Info "A small window will show download progress - it can run while you work."
        # Write a temp batch file instead of embedding && in ArgumentList
        # (avoids HTML-entity corruption when the script is downloaded via a browser)
        $pullBat = Join-Path $env:TEMP "ollama_pull_model.bat"
        "@echo off`r`necho Downloading $modelName ...`r`nollama pull $modelName`r`necho [OK] Model ready!`r`npause`r`ndel `"%~f0`"`r`n" |
            Out-File -FilePath $pullBat -Encoding ascii
        Start-Process cmd -ArgumentList "/c `"$pullBat`"" -WindowStyle Minimized
        Ok "Model download started in background"
    }
} else {
    Warn "Ollama not installed - skipping model download."
    Write-Host "  To enable AI features later:" -ForegroundColor Yellow
    Write-Host "    1. Install from https://ollama.com/download" -ForegroundColor Cyan
    Write-Host "    2. Run: ollama pull $modelName" -ForegroundColor Cyan
    Write-Host "    3. Run: ollama serve" -ForegroundColor Cyan
}

# -- 7. Create Desktop shortcut ------------------------------------------------
Write-Host ""
Write-Host "  =============================================" -ForegroundColor White
Write-Host "   Desktop shortcut                           " -ForegroundColor White
Write-Host "  =============================================" -ForegroundColor White
Write-Host ""

Info "Creating 'Code VM' shortcut on your Desktop..."
$desktopPath     = [Environment]::GetFolderPath("Desktop")
$startPs1        = Join-Path $repoDir "start.ps1"
$createShortcut  = Join-Path $repoDir "vm\create_shortcut.ps1"
$shortcutOk = $false
if (Test-Path $createShortcut) {
    try {
        $psExeLocal = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
        if (-not (Test-Path $psExeLocal)) { $psExeLocal = "powershell.exe" }
        $proc = Start-Process -FilePath $psExeLocal `
            -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$createShortcut`" -NoLaunch" `
            -WorkingDirectory $repoDir -Wait -PassThru -ErrorAction Stop
        if ($proc.ExitCode -eq 0) {
            $shortcutOk = $true
            Ok "Desktop shortcut created - 'Code VM' icon is on your Desktop"
        } else {
            Warn "create_shortcut.ps1 exited with code $($proc.ExitCode)."
        }
    } catch {
        Warn "Shortcut creation failed: $_"
    }
}

# Fallback: inline shortcut creation if the script approach failed
if (-not $shortcutOk) {
    Warn "Trying inline shortcut creation as fallback..."
    $psExe    = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    if (-not (Test-Path $psExe)) { $psExe = "powershell.exe" }
    $shortcutPath = Join-Path $desktopPath "Code VM.lnk"
    try {
        $shell    = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath       = $psExe
        $shortcut.Arguments        = "-NoProfile -ExecutionPolicy Bypass -File `"$startPs1`""
        $shortcut.WorkingDirectory = $repoDir
        $shortcut.Description      = "Launch Code VM - Monaco Editor with Ollama AI"
        $shortcut.WindowStyle      = 1
        $customIco = Join-Path $repoDir "vm\static\code_vm.ico"
        if (Test-Path $customIco) {
            $shortcut.IconLocation = "$customIco,0"
        } else {
            $icoLib = Join-Path $env:SystemRoot "System32\shell32.dll"
            $shortcut.IconLocation = if (Test-Path $icoLib) { "$icoLib,77" } else { "$psExe,0" }
        }
        $shortcut.Save()
        $shortcutOk = $true
        Ok "Desktop shortcut created (fallback) - 'Code VM' icon is on your Desktop"
    } catch {
        Warn "Inline shortcut creation also failed: $_"
    }
}

# -- 8. Copy self-discovering launcher to Desktop------------------------------
$launcherSrc  = Join-Path $repoDir "ЗАПУСТИТЬ.bat"
$launcherDest = Join-Path $desktopPath "ЗАПУСТИТЬ.bat"
if (Test-Path $launcherSrc) {
    try {
        Copy-Item -Path $launcherSrc -Destination $launcherDest -Force
        Ok "Backup launcher copied: 'ЗАПУСТИТЬ.bat' on Desktop (double-click if main shortcut fails)"
    } catch {
        Warn "Could not copy ЗАПУСТИТЬ.bat to Desktop: $_"
    }
}
# Also copy the PS1 helper script that ЗАПУСТИТЬ.bat delegates to
$zapustitPsSrc  = Join-Path $repoDir "zapustit.ps1"
$zapustitPsDest = Join-Path $desktopPath "zapustit.ps1"
if (Test-Path $zapustitPsSrc) {
    try {
        Copy-Item -Path $zapustitPsSrc -Destination $zapustitPsDest -Force
    } catch {
        Warn "Could not copy zapustit.ps1 to Desktop: $_"
    }
}

# Copy ЗАПУСТИТЬ_ВМ.bat (launcher for retrained VM with drgr-visor model)
$vmLauncherSrc  = Join-Path $repoDir "ЗАПУСТИТЬ_ВМ.bat"
$vmLauncherDest = Join-Path $desktopPath "ЗАПУСТИТЬ_ВМ.bat"
if (Test-Path $vmLauncherSrc) {
    try {
        Copy-Item -Path $vmLauncherSrc -Destination $vmLauncherDest -Force
        Ok "Visor VM launcher copied: 'ЗАПУСТИТЬ_ВМ.bat' on Desktop"
    } catch {
        Warn "Could not copy ЗАПУСТИТЬ_ВМ.bat to Desktop: $_"
    }
}

# -- 9. Done -------------------------------------------------------------------
Write-Host ""
Write-Host "  =============================================" -ForegroundColor Green
Write-Host "   Setup complete!                            " -ForegroundColor Green
Write-Host "  =============================================" -ForegroundColor Green
Write-Host ""
if ($shortcutOk) {
    Write-Host "  Three launchers are on your Desktop:" -ForegroundColor White
    Write-Host "    'Code VM'          - main shortcut (double-click to launch)" -ForegroundColor Cyan
    Write-Host "    'ЗАПУСТИТЬ.bat'    - backup launcher (double-click in File Explorer)" -ForegroundColor Cyan
    Write-Host "    'ЗАПУСТИТЬ_ВМ.bat' - Visor VM launcher (creates drgr-visor model)" -ForegroundColor Green
    Write-Host "                          (from a PowerShell terminal: .\ЗАПУСТИТЬ_ВМ.bat)" -ForegroundColor DarkGray
} else {
    Write-Host "  [!!] Desktop shortcut could not be created automatically." -ForegroundColor Yellow
    Write-Host "  To create the 'Code VM' icon on your Desktop, run this command:" -ForegroundColor Yellow
    Write-Host "    powershell -ExecutionPolicy Bypass -File `"$repoDir\vm\create_shortcut.ps1`"" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Backup launcher 'ЗАПУСТИТЬ.bat' may still be on your Desktop." -ForegroundColor White
}
Write-Host ""
Write-Host "  Or launch directly from PowerShell (paste this):" -ForegroundColor White
Write-Host "    powershell -ExecutionPolicy Bypass -File `"$repoDir\start.ps1`"" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Then open in browser:" -ForegroundColor White
Write-Host "    http://localhost:5000/" -ForegroundColor Cyan
Write-Host ""
if ($shortcutOk) {
    Write-Host "  Tip: to recreate the shortcut at any time, run:" -ForegroundColor DarkGray
    Write-Host "    powershell -ExecutionPolicy Bypass -File `"$repoDir\vm\create_shortcut.ps1`"" -ForegroundColor DarkGray
    Write-Host ""
}

# -- 10. Auto-launch the VM so browser opens immediately after first-time setup ---
# Skip auto-launch only when the caller passes -NoLaunch (e.g., CI/test runs).
if ($args -notcontains '-NoLaunch') {
    if (Test-Path $startPs1) {
        Write-Host "  [-->] Запуск Code VM (браузер откроется автоматически) / launching Code VM..." -ForegroundColor Cyan
        $psExeLaunch = try { (Get-Process -Id $PID).Path } catch { "powershell.exe" }
        Start-Process -FilePath $psExeLaunch `
            -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$startPs1`"" `
            -WorkingDirectory $repoDir
    }
}
