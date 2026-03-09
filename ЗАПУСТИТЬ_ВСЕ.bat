<# 2>nul
@echo off
:: ============================================================
::  DRGR — единый запуск: VM + Telegram-бот + браузер
::
::  ТОКЕН БОТА: укажите токен из @BotFather ниже
::  (или запустите с параметром: ЗАПУСТИТЬ_ВСЕ.bat ТОКЕН)
:: ============================================================
set "BOT_TOKEN_DEFAULT=YOUR_BOT_TOKEN_HERE"

:: Если токен передан параметром — использовать его
set "TOKEN_ARG=%~1"
if not "%TOKEN_ARG%"=="" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ЗАПУСТИТЬ_ВСЕ.ps1" -Token "%TOKEN_ARG%"
) else if not "%BOT_TOKEN_DEFAULT%"=="YOUR_BOT_TOKEN_HERE" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ЗАПУСТИТЬ_ВСЕ.ps1" -Token "%BOT_TOKEN_DEFAULT%"
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ЗАПУСТИТЬ_ВСЕ.ps1"
)
exit /b
#>
# PowerShell fallback when bat is run directly from PS console
$f = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$t = if ($args.Count -gt 0) { $args[0] } else { "" }
if ($t) { & (Join-Path $f 'ЗАПУСТИТЬ_ВСЕ.ps1') -Token $t }
else    { & (Join-Path $f 'ЗАПУСТИТЬ_ВСЕ.ps1') }
