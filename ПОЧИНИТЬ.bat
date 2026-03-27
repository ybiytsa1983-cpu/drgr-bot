@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

:: ===================================================================
::  ПОЧИНИТЬ.bat  -  Экстренное восстановление drgr-bot
::
::  Используйте этот файл если:
::   - Папка drgr-bot пропала с Рабочего стола
::   - Бот или VM не запускаются
::   - ЗАПУСТИТЬ_БОТА.bat выдаёт ошибки
::   - Файлы проекта повреждены
::
::  Скрипт УДАЛИТ папку на Рабочем столе и заново скачает проект.
::  Файл .env (токен) будет СОХРАНЁН если он существует.
:: ===================================================================

title drgr-bot - Восстановление

echo.
echo +============================================+
echo ^|     drgr-bot  -  Экстренное восстановление ^|
echo +============================================+
echo.
echo  Этот скрипт:
echo    1. Сохранит ваш токен (.env)
echo    2. Удалит повреждённую папку
echo    3. Заново скачает проект с GitHub
echo    4. Восстановит токен
echo    5. Предложит запустить бота
echo.

set "DEST=%USERPROFILE%\Desktop\drgr-bot"
set "REPO=https://github.com/ybiytsa1983-cpu/drgr-bot.git"
set "ENV_BACKUP=%TEMP%\drgr_bot_env_backup.txt"

:: ── Проверка Python ───────────────────────────────────────────────────────
echo  Проверка Python...
python --version > nul 2>&1
if errorlevel 1 (
    echo  [ОШИБКА] Python не найден!
    echo  Установите Python 3.10+ с https://www.python.org/downloads/
    echo  Обязательно отметьте "Add Python to PATH" при установке.
    pause
    exit /b 1
)
for /f "tokens=*" %%V in ('python --version 2^>^&1') do echo  Найден: %%V

:: ── Проверка Git ──────────────────────────────────────────────────────────
echo  Проверка Git...
git --version > nul 2>&1
if errorlevel 1 (
    echo  [ОШИБКА] Git не найден!
    echo  Установите Git с https://git-scm.com/download/win
    pause
    exit /b 1
)
for /f "tokens=*" %%V in ('git --version 2^>^&1') do echo  Найден: %%V
echo.

:: ── Предупреждение ───────────────────────────────────────────────────────
echo  ВНИМАНИЕ! Папка "%DEST%" будет УДАЛЕНА и скачана заново.
echo.
set "CONFIRM="
set /p "CONFIRM= Продолжить? (да/нет): "
if /i "!CONFIRM!"=="да"  goto :START_REPAIR
if /i "!CONFIRM!"=="yes" goto :START_REPAIR
if /i "!CONFIRM!"=="д"   goto :START_REPAIR
if /i "!CONFIRM!"=="y"   goto :START_REPAIR
echo  Отменено.
pause
exit /b 0

:START_REPAIR
echo.

:: ── Сохраняем .env ───────────────────────────────────────────────────────
if exist "%DEST%\.env" (
    echo  Сохраняем файл .env...
    copy /y "%DEST%\.env" "%ENV_BACKUP%" > nul 2>&1
    if errorlevel 1 (
        echo  [ПРЕДУПРЕЖДЕНИЕ] Не удалось сохранить .env. Токен придётся ввести заново.
        set "HAS_ENV=0"
    ) else (
        echo  .env сохранён во временное место.
        set "HAS_ENV=1"
    )
) else (
    echo  Файл .env не найден. Токен будет запрошен при установке.
    set "HAS_ENV=0"
)
echo.

:: ── Удаляем старую папку ─────────────────────────────────────────────────
if exist "%DEST%" (
    echo  Удаляем старую папку "%DEST%"...
    rmdir /s /q "%DEST%" 2>&1
    if errorlevel 1 (
        echo  [ОШИБКА] Не удалось удалить папку. Возможно, она используется.
        echo  Закройте все программы и попробуйте снова.
        pause
        exit /b 1
    )
    echo  Папка удалена.
) else (
    echo  Папка не существует (это нормально, продолжаем).
)
echo.

:: ── Клонируем репозиторий ─────────────────────────────────────────────────
echo  Клонирование репозитория...
echo  (Может занять 1-2 минуты...)
echo.
git clone "%REPO%" "%DEST%"
if errorlevel 1 (
    echo.
    echo  [ОШИБКА] Не удалось клонировать репозиторий!
    echo.
    echo  Проверьте:
    echo    1. Подключение к интернету
    echo    2. Доступ к GitHub (попробуйте открыть в браузере):
    echo       https://github.com/ybiytsa1983-cpu/drgr-bot
    echo.
    if "!HAS_ENV!"=="1" (
        echo  Ваш токен сохранён в: %ENV_BACKUP%
        echo  Не удаляйте этот файл!
    )
    pause
    exit /b 1
)
echo.
echo  Репозиторий успешно скачан.
echo.

:: ── Восстанавливаем .env ─────────────────────────────────────────────────
if "!HAS_ENV!"=="1" (
    echo  Восстанавливаем .env...
    copy /y "%ENV_BACKUP%" "%DEST%\.env" > nul 2>&1
    del /q "%ENV_BACKUP%" > nul 2>&1
    echo  Токен восстановлен.
) else (
    :: Запрашиваем токен
    echo  Введите токен Telegram-бота.
    echo  (Получить у @BotFather в Telegram)
    echo.
    set "BOT_TOKEN="
    set /p "BOT_TOKEN= BOT_TOKEN: "
    if "!BOT_TOKEN!"=="" (
        echo.
        echo  [ПРЕДУПРЕЖДЕНИЕ] Токен не введён.
        echo  Создайте файл .env вручную в папке "%DEST%":
        echo    Содержимое: BOT_TOKEN=ваш_токен
        echo.
    ) else (
        echo BOT_TOKEN=!BOT_TOKEN!> "%DEST%\.env"
        echo  Токен сохранён в .env
    )
)
echo.

:: ── Установка зависимостей ────────────────────────────────────────────────
echo  Установка зависимостей Python...
cd /d "%DEST%"
pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo  [ПРЕДУПРЕЖДЕНИЕ] Некоторые пакеты не установились.
    echo  Попробуйте вручную: pip install -r requirements.txt
) else (
    echo  Зависимости установлены.
)
echo.

:: ── Создание значка на Рабочем столе ─────────────────────────────────────
echo  Создание значка на Рабочем столе...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ws=New-Object -ComObject WScript.Shell; $sc=$ws.CreateShortcut('%USERPROFILE%\Desktop\ЗАПУСТИТЬ БОТА.lnk'); $sc.TargetPath='%DEST%\ЗАПУСТИТЬ_БОТА.bat'; $sc.WorkingDirectory='%DEST%'; $sc.Description='Запустить VM-сервер (бот управляется из веб-интерфейса)'; $sc.IconLocation='%SystemRoot%\System32\cmd.exe,0'; $sc.Save()" > nul 2>&1
if errorlevel 1 (
    echo  [ПРЕДУПРЕЖДЕНИЕ] Значок не создан. Используйте ЗАПУСТИТЬ_БОТА.bat напрямую.
) else (
    echo  Значок "ЗАПУСТИТЬ БОТА" создан на Рабочем столе!
)
echo.

:: ── Итог ─────────────────────────────────────────────────────────────────
echo +============================================+
echo ^|        Восстановление завершено!           ^|
echo +============================================+
echo.
echo  Папка проекта: %DEST%
echo  Значок "ЗАПУСТИТЬ БОТА" — на Рабочем столе.
echo.

:ASK_LAUNCH
set "LAUNCH="
set /p "LAUNCH= Запустить бота прямо сейчас? (да/нет): "
if /i "!LAUNCH!"=="да"  goto :DO_LAUNCH
if /i "!LAUNCH!"=="yes" goto :DO_LAUNCH
if /i "!LAUNCH!"=="д"   goto :DO_LAUNCH
if /i "!LAUNCH!"=="y"   goto :DO_LAUNCH
if /i "!LAUNCH!"=="нет" goto :SKIP_LAUNCH
if /i "!LAUNCH!"=="no"  goto :SKIP_LAUNCH
if /i "!LAUNCH!"=="н"   goto :SKIP_LAUNCH
if /i "!LAUNCH!"=="n"   goto :SKIP_LAUNCH
echo  Введите "да" или "нет".
goto :ASK_LAUNCH

:DO_LAUNCH
echo.
call "%DEST%\ЗАПУСТИТЬ_БОТА.bat"
goto :END

:SKIP_LAUNCH
echo.
echo  Дважды кликните ЗАПУСТИТЬ_БОТА.bat для запуска.
echo.

:END
pause
