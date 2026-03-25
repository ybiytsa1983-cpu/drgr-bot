@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

title DRGR Bot — Установка браузерного расширения

echo.
echo +------------------------------------------------+
echo ^|   DRGR Bot  ^|  Браузерное расширение            ^|
echo +------------------------------------------------+
echo.

:: ── Определяем папку проекта (батник лежит в корне) ──────────────────────
set "BOTDIR=%~dp0"
if "%BOTDIR:~-1%"=="\" set "BOTDIR=%BOTDIR:~0,-1%"
set "EXTDIR=%BOTDIR%\extension"

:: ── 1. Генерируем иконки через Python ────────────────────────────────────
echo  [1/3] Генерация иконок...
python "%EXTDIR%\make_icons.py"
if errorlevel 1 (
    echo.
    echo  [ПРЕДУПРЕЖДЕНИЕ] Иконки не созданы.
    echo  Проверьте, что Python и Pillow установлены: pip install pillow
    echo.
) else (
    echo  Иконки созданы.
)
echo.

:: ── 2. Открываем страницу расширений Chrome / Edge ───────────────────────
echo  [2/3] Открытие страницы управления расширениями...
echo.
echo  +----------------------------------------------------+
echo  ^|  КАК УСТАНОВИТЬ РАСШИРЕНИЕ ВРУЧНУЮ (один раз):     ^|
echo  ^|                                                     ^|
echo  ^|  Chrome:  chrome://extensions                       ^|
echo  ^|  Edge:    edge://extensions                         ^|
echo  ^|  Brave:   brave://extensions                        ^|
echo  ^|                                                     ^|
echo  ^|  1. Включите "Режим разработчика" (правый верхний) ^|
echo  ^|  2. Нажмите "Загрузить распакованное"              ^|
echo  ^|  3. Укажите папку:                                  ^|
echo  ^|     %EXTDIR%
echo  ^|  4. Готово — значок появится на панели браузера!   ^|
echo  +----------------------------------------------------+
echo.

:: Пробуем открыть Chrome
set "_CHROME="
for %%P in (
    "%ProgramFiles%\Google\Chrome\Application\chrome.exe"
    "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
    "%LocalAppData%\Google\Chrome\Application\chrome.exe"
) do (
    if exist "%%~P" set "_CHROME=%%~P"
)

if defined _CHROME (
    echo  Открываем Chrome на странице расширений...
    start "" "%_CHROME%" "chrome://extensions"
) else (
    :: Пробуем Edge
    set "_EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
    if exist "!_EDGE!" (
        echo  Chrome не найден. Открываем Edge на странице расширений...
        start "" "!_EDGE!" "edge://extensions"
    ) else (
        echo  Браузер не найден автоматически.
        echo  Откройте браузер вручную и перейдите на chrome://extensions
    )
)
echo.

:: ── 3. Итог ──────────────────────────────────────────────────────────────
echo  [3/3] Готово!
echo.
echo  Папка расширения: %EXTDIR%
echo.
echo  После установки расширения кликните значок D в панели браузера,
echo  чтобы открыть интерфейс DRGR Bot (требуется запущенный сервер).
echo.
pause
