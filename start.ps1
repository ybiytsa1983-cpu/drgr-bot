<#
.SYNOPSIS
    ONE-COMMAND launcher for Code VM.

.DESCRIPTION
    Run this script ONCE - it installs everything on first launch, then opens
    the editor.  On every subsequent run it just opens the editor immediately.

    Usage in PowerShell (always include .\):
        .\start.ps1

    If you see "running scripts is disabled", run this ONCE first, then retry:
        Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

.NOTES
    You can also double-click start.bat in Windows Explorer (no .\  needed there).
#>

# -- Resolve the directory containing this script ------------------------------
# $PSScriptRoot is empty when PS is started without -File (e.g. some shortcuts
# or "powershell start.ps1" instead of "powershell -File start.ps1").
# Fall back to $MyInvocation, then to the current working directory.
$scriptRoot = if ($PSScriptRoot) {
    $PSScriptRoot
} elseif ($MyInvocation.MyCommand.Path) {
    Split-Path -Parent $MyInvocation.MyCommand.Path
} else {
    (Get-Location).Path
}

# -- Always run from the repository root ---------------------------------------
Set-Location $scriptRoot

# -- Auto-update from remote (silent, best-effort) ----------------------------
try {
    $branch = (& git rev-parse --abbrev-ref HEAD 2>$null).Trim()
    if (-not $branch -or $branch -eq 'HEAD') { $branch = 'main' }
    # Stash local modifications so they never block the pull
    $stashOut = (& git stash --quiet 2>$null)
    $stashed  = $stashOut -notmatch 'No local changes'
    $null = & git pull origin $branch --quiet 2>$null
    if ($LASTEXITCODE -ne 0) {
        # Fallback: hard-reset to remote HEAD — warn before overwriting
        Write-Host "  [!] git pull failed — resetting to remote origin/$branch." -ForegroundColor Yellow
        $null = & git fetch origin --quiet 2>$null
        $null = & git reset --hard "origin/$branch" --quiet 2>$null
    }
    # Restore stashed changes (if any)
    if ($stashed) { $null = & git stash pop --quiet 2>$null }
} catch { }

# -- Normalize .bat files to CRLF (cmd.exe requires CRLF; git may checkout as LF
#    on machines that cloned before the .gitattributes eol=crlf rule was active) -
@('start.bat', 'vm.bat', 'install.bat', 'stop.bat',
  'vm\start_vm.bat', "ЗАПУСТИТЬ.bat") | ForEach-Object {
    $f = Join-Path $scriptRoot $_
    try {
        if (Test-Path $f) {
            $t = [IO.File]::ReadAllText($f)
            $n = ($t -replace "`r`n", "`n" -replace "`r", "`n") -replace "`n", "`r`n"
            if ($t -ne $n) { [IO.File]::WriteAllText($f, $n) }
        }
    } catch { }
}

# -- Copy launcher/update .bat files to Desktop so the user has easy access ----
# Always overwrite so the Desktop copies stay up-to-date with the repo version.
try {
    $desktopDir = [Environment]::GetFolderPath('Desktop')
    foreach ($batName in @('ЗАПУСТИТЬ.bat', 'ОБНОВИТЬ.bat')) {
        $batSrc = Join-Path $scriptRoot $batName
        if (Test-Path $batSrc) {
            Copy-Item -Path $batSrc -Destination (Join-Path $desktopDir $batName) `
                      -Force -ErrorAction SilentlyContinue
        }
    }
} catch { }

# -- Start Ollama early so server.py connects on first heartbeat ---------------
try {
    $ollamaExe = $null
    $ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($ollamaCmd) { $ollamaExe = $ollamaCmd.Source }
    if (-not $ollamaExe) {
        foreach ($c in @(
            "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
            "$env:USERPROFILE\AppData\Local\Programs\Ollama\ollama.exe",
            "C:\Program Files\Ollama\ollama.exe",
            "C:\Program Files (x86)\Ollama\ollama.exe"
        )) { if (Test-Path $c) { $ollamaExe = $c; break } }
    }
    if ($ollamaExe) {
        $ollamaUp = $false
        foreach ($tryHost in @("127.0.0.1", "localhost")) {
            foreach ($tryPort in (11434..11444)) {
                try {
                    $r = Invoke-WebRequest -Uri "http://${tryHost}:$tryPort/api/tags" `
                            -UseBasicParsing -TimeoutSec 1 -ErrorAction SilentlyContinue
                    if ($r -and $r.StatusCode -eq 200) { $ollamaUp = $true; break }
                } catch { }
            }
            if ($ollamaUp) { break }
        }
        if (-not $ollamaUp) {
            Start-Process -FilePath $ollamaExe -ArgumentList 'serve' `
                -WindowStyle Minimized -ErrorAction SilentlyContinue
            # Wait up to 15 s so vm.ps1 detects Ollama immediately (avoids duplicate start)
            # Probe both 127.0.0.1 and localhost on ports 11434-11444, in case Ollama
            # starts on a non-standard port or binds to 127.0.0.1 only.
            for ($attempt = 0; $attempt -lt 15; $attempt++) {
                Start-Sleep -Seconds 1
                $detected = $false
                foreach ($tryHost2 in @("127.0.0.1", "localhost")) {
                    foreach ($tryPort in (11434..11444)) {
                        try {
                            $r2 = Invoke-WebRequest -Uri "http://${tryHost2}:$tryPort/api/tags" `
                                    -UseBasicParsing -TimeoutSec 1 -ErrorAction SilentlyContinue
                            if ($r2 -and $r2.StatusCode -eq 200) { $detected = $true; break }
                        } catch { }
                    }
                    if ($detected) { break }
                }
                if ($detected) { break }
            }
        }
    }
} catch { }

# -- Start LM Studio early if installed ----------------------------------------
try {
    $lmsExe = $null
    foreach ($c in @(
        "$env:LOCALAPPDATA\Programs\LM Studio\LM Studio.exe",
        "$env:USERPROFILE\AppData\Local\Programs\LM Studio\LM Studio.exe",
        "C:\Program Files\LM Studio\LM Studio.exe",
        "C:\Program Files (x86)\LM Studio\LM Studio.exe"
    )) { if (Test-Path $c) { $lmsExe = $c; break } }
    if ($lmsExe) {
        $lmsUp = $false
        try {
            $lr = Invoke-WebRequest -Uri "http://localhost:1234/v1/models" `
                    -UseBasicParsing -TimeoutSec 1 -ErrorAction SilentlyContinue
            if ($lr -and $lr.StatusCode -eq 200) { $lmsUp = $true }
        } catch { }
        if (-not $lmsUp) {
            Start-Process -FilePath $lmsExe -WindowStyle Minimized -ErrorAction SilentlyContinue
        }
    }
} catch { }

# -- First-time setup if .venv is missing --------------------------------------
$venvPython = Join-Path $scriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host ""
    Write-Host "  +-------------------------------------------------------+" -ForegroundColor Cyan
    Write-Host "  |  Code VM - первый запуск, выполняется установка...   |" -ForegroundColor Cyan
    Write-Host "  |  Подождите ~1-2 минуты.                              |" -ForegroundColor Cyan
    Write-Host "  +-------------------------------------------------------+" -ForegroundColor Cyan
    Write-Host ""

    # -- Find Python -----------------------------------------------------------
    $python = $null
    foreach ($cmd in @("python", "python3", "py")) {
        try {
            $ver = & $cmd --version 2>&1
            if ($ver -match "Python 3\.(\d+)" -and [int]$Matches[1] -ge 8) {
                $python = $cmd
                Write-Host "  [OK] Python найден: $ver" -ForegroundColor Green
                break
            }
        } catch { }
    }

    if (-not $python) {
        Write-Host ""
        Write-Host "  [ОШИБКА] Python 3.8+ не найден." -ForegroundColor Red
        Write-Host ""
        Write-Host "  Установите Python с сайта:" -ForegroundColor Yellow
        Write-Host "    https://www.python.org/downloads/" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "  ВАЖНО: при установке поставьте галочку 'Add Python to PATH'" -ForegroundColor Yellow
        Write-Host ""
        Read-Host "  Нажмите Enter для выхода"
        exit 1
    }

    # -- Create .venv ----------------------------------------------------------
    Write-Host "  [--] Создание виртуального окружения..." -ForegroundColor Cyan
    & $python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [ОШИБКА] Не удалось создать .venv." -ForegroundColor Red
        Read-Host "  Нажмите Enter для выхода"
        exit 1
    }

    # -- Install dependencies --------------------------------------------------
    Write-Host "  [--] Установка зависимостей (flask, requests)..." -ForegroundColor Cyan
    & ".venv\Scripts\pip" install flask requests --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [ОШИБКА] Не удалось установить пакеты." -ForegroundColor Red
        Read-Host "  Нажмите Enter для выхода"
        exit 1
    }

    # -- Optional full requirements.txt ---------------------------------------
    if (Test-Path "requirements.txt") {
        Write-Host "  [--] Установка requirements.txt..." -ForegroundColor Cyan
        & ".venv\Scripts\pip" install -r requirements.txt --quiet 2>$null
    }

    # -- Create Desktop shortcut (so user has icon next time) -----------------
    # Target powershell.exe directly to avoid .bat-file association issues on
    # Windows 11 (Windows Terminal can open .bat shortcuts in a PS profile,
    # causing PowerShell to parse batch syntax and fail with %~dp0 errors).
    try {
        $desktopPath  = [Environment]::GetFolderPath("Desktop")
        $shortcutPath = Join-Path $desktopPath "Code VM.lnk"
        $startPs1     = Join-Path $scriptRoot "start.ps1"
        $psExe        = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
        if (-not (Test-Path $psExe)) { $psExe = "powershell.exe" }
        $shell        = New-Object -ComObject WScript.Shell
        $shortcut     = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath       = $psExe
        $shortcut.Arguments        = "-NoProfile -ExecutionPolicy Bypass -File `"$startPs1`""
        $shortcut.WorkingDirectory = $scriptRoot
        $shortcut.Description      = "Launch Code VM - Monaco Editor with Ollama AI"
        $shortcut.WindowStyle      = 1   # Normal window so progress and errors are visible
        $customIco = Join-Path $scriptRoot "vm\static\code_vm.ico"
        if (Test-Path $customIco) {
            $shortcut.IconLocation = "$customIco,0"
        } else {
            $icoLib = Join-Path $env:SystemRoot "System32\shell32.dll"
            $shortcut.IconLocation = if (Test-Path $icoLib) { "$icoLib,77" } else { "$psExe,0" }
        }
        $shortcut.Save()
        Write-Host "  [OK] Ярлык 'Code VM' создан на Рабочем столе" -ForegroundColor Green
    } catch {
        # Non-fatal - icon is nice but not required
        Write-Host "  [!] Ярлык не создан (не критично): $_" -ForegroundColor Yellow
    }

    # -- Copy launcher/update .bat files to Desktop as backup/recovery launchers --
    try {
        foreach ($batName in @('ЗАПУСТИТЬ.bat', 'ОБНОВИТЬ.bat')) {
            $batSrc = Join-Path $scriptRoot $batName
            if (Test-Path $batSrc) {
                Copy-Item -Path $batSrc -Destination (Join-Path $desktopPath $batName) -Force
            }
        }
        Write-Host "  [OK] ЗАПУСТИТЬ.bat и ОБНОВИТЬ.bat скопированы на Рабочий стол" -ForegroundColor Green
    } catch { }

    Write-Host ""
    Write-Host "  [OK] Установка завершена!" -ForegroundColor Green
    Write-Host ""
}

# -- Always ensure Desktop shortcut exists (re-run or fresh machine) ----------
try {
    $desktopCheck  = [Environment]::GetFolderPath("Desktop")
    $shortcutCheck = Join-Path $desktopCheck "Code VM.lnk"
    if (-not (Test-Path $shortcutCheck)) {
        $startPs1Lnk = Join-Path $scriptRoot "start.ps1"
        $psExeLnk    = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
        if (-not (Test-Path $psExeLnk)) { $psExeLnk = "powershell.exe" }
        $shellLnk    = New-Object -ComObject WScript.Shell
        $sc          = $shellLnk.CreateShortcut($shortcutCheck)
        $sc.TargetPath       = $psExeLnk
        $sc.Arguments        = "-NoProfile -ExecutionPolicy Bypass -File `"$startPs1Lnk`""
        $sc.WorkingDirectory = $scriptRoot
        $sc.Description      = "Launch Code VM - Monaco Editor with Ollama AI"
        $sc.WindowStyle      = 1
        $customIcoLnk = Join-Path $scriptRoot "vm\static\code_vm.ico"
        if (Test-Path $customIcoLnk) {
            $sc.IconLocation = "$customIcoLnk,0"
        } else {
            $icoLibLnk = Join-Path $env:SystemRoot "System32\shell32.dll"
            $sc.IconLocation = if (Test-Path $icoLibLnk) { "$icoLibLnk,77" } else { "$psExeLnk,0" }
        }
        $sc.Save()
        Write-Host "  [OK] Ярлык 'Code VM' создан на Рабочем столе" -ForegroundColor Green
        # Also copy bat backups
        foreach ($batBakName in @('ЗАПУСТИТЬ.bat', 'ОБНОВИТЬ.bat')) {
            $batBak = Join-Path $scriptRoot $batBakName
            if (Test-Path $batBak) {
                Copy-Item -Path $batBak -Destination (Join-Path $desktopCheck $batBakName) -Force -ErrorAction SilentlyContinue
            }
        }
    }
} catch { }

# -- Launch the VM server so browser opens (Normal window so errors are visible) --
$vmPs1 = Join-Path $scriptRoot "vm.ps1"
Write-Host "  [-->] Запуск Code VM..." -ForegroundColor Cyan
Start-Process -FilePath "powershell.exe" `
    -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$vmPs1`"" `
    -WorkingDirectory $scriptRoot `
    -WindowStyle Normal
Write-Host "  [OK] Code VM запускается - браузер откроется через несколько секунд." -ForegroundColor Green
Write-Host ""

# -- Auto-open Chrome with AI-Vision-Ultra extension (if present) --------------
try {
    $extPath = $env:DRGR_CHROME_EXT
    if (-not $extPath) {
        $desktop = [Environment]::GetFolderPath('Desktop')
        foreach ($d in @(
            (Join-Path $desktop 'AI-Vision-Ultra-Google-v11_ext'),
            (Join-Path $desktop 'AI-Vision-Ultra-Google-v11'),
            (Join-Path $desktop 'AI-Vision-Ultra-Google')
        )) {
            if (Test-Path (Join-Path $d 'manifest.json')) { $extPath = $d; break }
        }
    }
    if ($extPath -and (Test-Path (Join-Path $extPath 'manifest.json'))) {
        $chromeExe = $null
        foreach ($c in @(
            "$env:PROGRAMFILES\Google\Chrome\Application\chrome.exe",
            "${env:PROGRAMFILES(X86)}\Google\Chrome\Application\chrome.exe",
            "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
        )) { if (Test-Path $c) { $chromeExe = $c; break } }
        if ($chromeExe) {
            Start-Sleep -Seconds 3   # wait for VM server to start
            # Detect HTTPS mode: cert files present → use https
            $certExists = (Test-Path (Join-Path $scriptRoot 'ssl_cert.pem')) -and (Test-Path (Join-Path $scriptRoot 'ssl_key.pem'))
            $vmScheme   = if ($certExists) { 'https' } else { 'http' }
            $vmPort     = if ($env:VM_PORT) { $env:VM_PORT } else { '5000' }
            Start-Process -FilePath $chromeExe `
                -ArgumentList "--load-extension=`"$extPath`"", "--no-first-run", "${vmScheme}://localhost:${vmPort}" `
                -ErrorAction SilentlyContinue
            Write-Host "  [OK] Chrome запущен с расширением AI-Vision-Ultra." -ForegroundColor Green
        }
    }
} catch { }
