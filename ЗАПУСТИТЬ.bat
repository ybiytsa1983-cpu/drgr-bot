<# 2>nul
@echo off
:: Try zapustit.ps1 next to this bat first (repo folder)
if exist "%~dp0zapustit.ps1" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0zapustit.ps1" %*
    exit /b
)
:: Not found here — search common repo locations
for %%D in (
    "%USERPROFILE%\drgr-bot"
    "%USERPROFILE%\Documents\drgr-bot"
    "%USERPROFILE%\Desktop\drgr-bot"
    "%USERPROFILE%\Downloads\drgr-bot"
    "%USERPROFILE%\projects\drgr-bot"
    "%USERPROFILE%\Projects\drgr-bot"
    "%USERPROFILE%\code\drgr-bot"
    "%USERPROFILE%\Code\drgr-bot"
    "%USERPROFILE%\repos\drgr-bot"
    "%USERPROFILE%\Repos\drgr-bot"
    "C:\drgr-bot"
    "C:\projects\drgr-bot"
    "C:\Projects\drgr-bot"
    "C:\code\drgr-bot"
    "C:\Code\drgr-bot"
    "C:\Users\%USERNAME%\drgr-bot"
    "D:\drgr-bot"
    "D:\projects\drgr-bot"
    "D:\Projects\drgr-bot"
    "D:\code\drgr-bot"
    "D:\Code\drgr-bot"
) do (
    if exist "%%~D\zapustit.ps1" (
        powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%%~D\zapustit.ps1" %*
        exit /b
    )
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Write-Host '' ; Write-Host '  ERROR: папка drgr-bot не найдена.' -ForegroundColor Red ; Write-Host '  Установите: git clone https://github.com/ybiytsa1983-cpu/drgr-bot' -ForegroundColor Yellow ; Write-Host '' ; Read-Host '  Нажмите Enter для выхода'"
exit /b 1
#>
# PowerShell fallback — runs when .bat is invoked directly from PS
$here = if ($PSScriptRoot) { $PSScriptRoot } `
        elseif ($MyInvocation.MyCommand.Path) { Split-Path $MyInvocation.MyCommand.Path } `
        else { (Get-Location).Path }
$zap = Join-Path $here 'zapustit.ps1'
if (Test-Path $zap) { & $zap @args; exit }
# zapustit.ps1 not beside this bat (e.g. bat is on Desktop) — search repo
foreach ($d in @(
    "$env:USERPROFILE\drgr-bot",
    "$env:USERPROFILE\Documents\drgr-bot",
    "$env:USERPROFILE\Desktop\drgr-bot",
    "$env:USERPROFILE\Downloads\drgr-bot",
    "$env:USERPROFILE\projects\drgr-bot",
    "$env:USERPROFILE\Projects\drgr-bot",
    "$env:USERPROFILE\code\drgr-bot",
    "$env:USERPROFILE\Code\drgr-bot",
    "$env:USERPROFILE\repos\drgr-bot",
    "$env:USERPROFILE\Repos\drgr-bot",
    "C:\drgr-bot",
    "C:\projects\drgr-bot",
    "C:\Projects\drgr-bot",
    "C:\code\drgr-bot",
    "C:\Code\drgr-bot",
    "C:\Users\$env:USERNAME\drgr-bot",
    "D:\drgr-bot",
    "D:\projects\drgr-bot",
    "D:\Projects\drgr-bot",
    "D:\code\drgr-bot",
    "D:\Code\drgr-bot"
)) {
    $zap = Join-Path $d 'zapustit.ps1'
    if (Test-Path $zap) { & $zap @args; exit }
}
Write-Host ''
Write-Host '  ERROR: папка drgr-bot не найдена.' -ForegroundColor Red
Write-Host '  Установите: git clone https://github.com/ybiytsa1983-cpu/drgr-bot' -ForegroundColor Yellow
Write-Host ''
Read-Host '  Нажмите Enter для выхода'
exit 1
