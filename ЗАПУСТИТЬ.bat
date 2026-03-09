<# 2>nul
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0zapustit.ps1" %*
exit /b
#>
$f = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
& (Join-Path $f 'zapustit.ps1') @args
