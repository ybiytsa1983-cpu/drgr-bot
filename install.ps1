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
$desktopPath  = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopPath "Code VM.lnk"
# Target powershell.exe directly to avoid .bat-file association issues on
# Windows 11 (Windows Terminal can open .bat shortcuts in a PS profile,
# causing PowerShell to parse batch syntax and fail with %~dp0 errors).
$startPs1     = Join-Path $repoDir "start.ps1"
$psExe        = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
if (-not (Test-Path $psExe)) { $psExe = "powershell.exe" }

$shortcutOk = $false
try {
    $shell    = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath       = $psExe
    $shortcut.Arguments        = "-NoProfile -ExecutionPolicy Bypass -File `"$startPs1`""
    $shortcut.WorkingDirectory = $repoDir
    $shortcut.Description      = "Launch Code VM - Monaco Editor with Ollama AI"
    $shortcut.WindowStyle      = 1   # Normal window so progress and errors are visible
    # Prefer bundled custom icon; fall back to a reliably-visible system icon
    $customIco = Join-Path $repoDir "vm\static\code_vm.ico"
    if (Test-Path $customIco) {
        $shortcut.IconLocation = "$customIco,0"
    } else {
        $icoLib = Join-Path $env:SystemRoot "System32\shell32.dll"
        $shortcut.IconLocation = if (Test-Path $icoLib) { "$icoLib,77" } else { "$psExe,0" }
    }
    $shortcut.Save()
    $shortcutOk = $true
    Ok "Desktop shortcut created - 'Code VM' icon is on your Desktop"
} catch {
    Warn "WScript.Shell shortcut failed ($_). Creating .bat fallback on Desktop..."
    try {
        $fallbackPath = Join-Path $desktopPath "Code VM.bat"
        # Polyglot: works in both cmd.exe and PowerShell (Windows Terminal may open
        # .bat shortcuts in a PS profile on Windows 11, causing @echo off to fail).
        $polyglot  = "<# 2>nul`r`n"
        $polyglot += "@echo off`r`n"
        $polyglot += "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$startPs1`"`r`n"
        $polyglot += "exit /b`r`n"
        $polyglot += "#>`r`n"
        $polyglot += "`$f = if (`$PSScriptRoot) { `$PSScriptRoot } else { (Get-Location).Path }`r`n"
        $polyglot += "& (Join-Path `$f 'start.ps1') @args`r`n"
        [System.IO.File]::WriteAllText($fallbackPath, $polyglot, [System.Text.Encoding]::ASCII)
        $shortcutOk = $true
        Ok "Desktop launcher created: '$fallbackPath' - double-click it to launch Code VM"
    } catch {
        Warn "Could not create Desktop shortcut: $_"
        Warn "Run manually later: powershell -ExecutionPolicy Bypass -File vm\create_shortcut.ps1"
    }
}

# -- 8. Copy self-discovering launcher to Desktop ------------------------------
$launcherSrc  = Join-Path $repoDir "ЗАПУСТИТЬ.bat"
$launcherDest = Join-Path ([Environment]::GetFolderPath("Desktop")) "ЗАПУСТИТЬ.bat"
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
$zapustitPsDest = Join-Path ([Environment]::GetFolderPath("Desktop")) "zapustit.ps1"
if (Test-Path $zapustitPsSrc) {
    try {
        Copy-Item -Path $zapustitPsSrc -Destination $zapustitPsDest -Force
    } catch {
        Warn "Could not copy zapustit.ps1 to Desktop: $_"
    }
}

# -- 9. Done -------------------------------------------------------------------
Write-Host ""
Write-Host "  =============================================" -ForegroundColor Green
Write-Host "   Setup complete!                            " -ForegroundColor Green
Write-Host "  =============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Two launchers are on your Desktop:" -ForegroundColor White
Write-Host "    'Code VM'        - main shortcut (double-click to launch)" -ForegroundColor Cyan
Write-Host "    'ЗАПУСТИТЬ.bat'  - backup launcher (double-click in File Explorer)" -ForegroundColor Cyan
Write-Host "                       (from a PowerShell terminal: .\ЗАПУСТИТЬ.bat)" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Or launch directly from PowerShell (paste this):" -ForegroundColor White
Write-Host "    powershell -ExecutionPolicy Bypass -File `"$repoDir\start.ps1`"" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Then open in browser:" -ForegroundColor White
Write-Host "    http://localhost:5000/" -ForegroundColor Cyan
Write-Host ""

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
