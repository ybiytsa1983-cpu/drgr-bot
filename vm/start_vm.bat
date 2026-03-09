<# 2>nul
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\vm.ps1" %*
exit /b
#>
$dir = if ($PSScriptRoot) { $PSScriptRoot } else { $PWD.Path }
& (Join-Path (Split-Path $dir -Parent) 'vm.ps1') @args
