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
try { git pull --ff-only --quiet 2>$null } catch { }

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

# -- Copy ЗАПУСТИТЬ.bat to Desktop as self-discovering backup launcher ---------
# Always overwrite so the Desktop copy stays up-to-date with the repo version.
try {
    $batSrc  = Join-Path $scriptRoot 'ЗАПУСТИТЬ.bat'
    $batDest = Join-Path ([Environment]::GetFolderPath('Desktop')) 'ЗАПУСТИТЬ.bat'
    if (Test-Path $batSrc) {
        Copy-Item -Path $batSrc -Destination $batDest -Force -ErrorAction SilentlyContinue
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
        foreach ($tryPort in (11434..11444)) {
            try {
                $r = Invoke-WebRequest -Uri "http://localhost:$tryPort/api/tags" `
                        -UseBasicParsing -TimeoutSec 1 -ErrorAction SilentlyContinue
                if ($r -and $r.StatusCode -eq 200) { $ollamaUp = $true; break }
            } catch { }
        }
        if (-not $ollamaUp) {
            Start-Process -FilePath $ollamaExe -ArgumentList 'serve' `
                -WindowStyle Minimized -ErrorAction SilentlyContinue
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
        $shortcut.WindowStyle      = 7   # Start minimized (browser opens automatically)
        $icoLib = Join-Path $env:SystemRoot "System32\imageres.dll"
        $shortcut.IconLocation = if (Test-Path $icoLib) { "$icoLib,97" } else { "$psExe,0" }
        $shortcut.Save()
        Write-Host "  [OK] Ярлык 'Code VM' создан на Рабочем столе" -ForegroundColor Green
    } catch {
        # Non-fatal - icon is nice but not required
        Write-Host "  [!] Ярлык не создан (не критично): $_" -ForegroundColor Yellow
    }

    # -- Copy ЗАПУСТИТЬ.bat to Desktop as backup/recovery launcher ---------------
    try {
        $batSrc = Join-Path $scriptRoot 'ЗАПУСТИТЬ.bat'
        if (Test-Path $batSrc) {
            Copy-Item -Path $batSrc -Destination (Join-Path $desktopPath 'ЗАПУСТИТЬ.bat') -Force
            Write-Host "  [OK] ЗАПУСТИТЬ.bat скопирован на Рабочий стол (запасной лаунчер)" -ForegroundColor Green
        }
    } catch { }

    Write-Host ""
    Write-Host "  [OK] Установка завершена!" -ForegroundColor Green
    Write-Host ""
}

# -- Launch the VM server minimized so browser opens without a full console window --
$vmPs1 = Join-Path $scriptRoot "vm.ps1"
Write-Host "  [-->] Запуск Code VM..." -ForegroundColor Cyan
Start-Process -FilePath "powershell.exe" `
    -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$vmPs1`"" `
    -WorkingDirectory $scriptRoot `
    -WindowStyle Minimized
Write-Host "  [OK] Code VM запускается - браузер откроется через несколько секунд." -ForegroundColor Green
Write-Host ""
