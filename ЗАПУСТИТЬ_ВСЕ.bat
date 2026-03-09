<# 2>nul
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ЗАПУСТИТЬ_ВСЕ.ps1" %*
exit /b
#>
$f = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
& (Join-Path $f 'ЗАПУСТИТЬ_ВСЕ.ps1') @args
