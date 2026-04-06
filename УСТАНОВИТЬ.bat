@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

:: ===================================================================
::  УСТАНОВИТЬ.bat  -  Первичная установка drgr-bot
::  Скачайте этот файл и запустите - он сделает всё сам:
::   1. Клонирует репозиторий на Рабочий стол
::   2. Создаёт файл .env с токеном бота
::   3. Устанавливает зависимости Python
::   4. Запускает бота и VM-сервер
:: ===================================================================

title drgr-bot - Установка

echo.
echo +----------------------------------------------+
echo ^|        drgr-bot  -  Мастер установки         ^|
echo +----------------------------------------------+
echo.

:: -- Целевая папка на Рабочем столе ------------------------------------
set "DEST=%USERPROFILE%\Desktop\drgr-bot"
set "REPO=https://github.com/ybiytsa1983-cpu/drgr-bot.git"

:: -- 1. Проверка Python -------------------------------------------------
echo  [1/6] Проверка Python...
python --version > nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ОШИБКА] Python не найден!
    echo.
    echo  Установите Python 3.10 или новее:
    echo    https://www.python.org/downloads/
    echo.
    echo  Убедитесь, что при установке отмечена галочка
    echo  "Add Python to PATH", затем запустите этот файл снова.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%V in ('python --version 2^>^&1') do echo  Найден: %%V
echo.

:: -- 2. Проверка Git ----------------------------------------------------
echo  [2/6] Проверка Git...
git --version > nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ОШИБКА] Git не найден!
    echo.
    echo  Установите Git for Windows:
    echo    https://git-scm.com/download/win
    echo.
    echo  После установки запустите этот файл снова.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%V in ('git --version 2^>^&1') do echo  Найден: %%V
echo.

:: -- 3. Клонирование репозитория ----------------------------------------
echo  [3/6] Клонирование репозитория в %DEST%...
echo.

if exist "%DEST%\.git" (
    echo  Папка уже существует. Обновляем...
    cd /d "%DEST%"
    git fetch origin main > nul 2>&1
    git reset --hard origin/main
    if errorlevel 1 (
        echo  [ОШИБКА] Не удалось обновить репозиторий.
        pause
        exit /b 1
    )
    echo  Репозиторий обновлён.
) else (
    if exist "%DEST%" (
        echo  [ОШИБКА] Папка "%DEST%" уже существует, но не является git-репозиторием.
        echo  Переименуйте или удалите её вручную и запустите снова.
        echo.
        pause
        exit /b 1
    )
    git clone "%REPO%" "%DEST%"
    if errorlevel 1 (
        echo.
        echo  [ОШИБКА] Не удалось клонировать репозиторий.
        echo  Проверьте подключение к интернету и попробуйте снова.
        echo.
        pause
        exit /b 1
    )
    echo  Репозиторий успешно склонирован.
)
echo.

:: -- Переходим в папку проекта ------------------------------------------
cd /d "%DEST%"

:: -- 4. Установка зависимостей Python -----------------------------------
echo  [4/6] Установка зависимостей Python...
pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo.
    echo  [ПРЕДУПРЕЖДЕНИЕ] Некоторые Python-зависимости не установились.
    echo  Попробуйте запустить вручную: pip install -r requirements.txt
    echo.
) else (
    echo  Python-зависимости установлены успешно.
)
echo.

:: -- 5. Установка зависимостей Local Comet (Node.js) -------------------
echo  [5/6] Установка Local Comet Editor (Node.js)...
echo.

node --version > nul 2>&1
if errorlevel 1 (
    echo  [!] Node.js не найден.
    echo      Local Comet Editor — необязательный компонент.
    echo      VM-сервер будет работать без него.
    echo.
    echo      Чтобы включить Local Comet Editor позже:
    echo        1. Установите Node.js 18+: https://nodejs.org/
    echo        2. Перезапустите ЗАПУСТИТЬ_БОТА.bat
    echo.
) else (
    for /f "tokens=*" %%V in ('node --version 2^>^&1') do echo  Найден: Node.js %%V
    if exist "%DEST%\local-comet-patch\server\package.json" (
        pushd "%DEST%\local-comet-patch\server"
        echo  Установка npm-зависимостей...
        call npm install --silent
        if errorlevel 1 (
            echo  [ПРЕДУПРЕЖДЕНИЕ] npm install завершился с ошибкой.
        ) else (
            echo  Сборка Local Comet Server...
            call npm run build --silent
            if errorlevel 1 (
                echo  [ПРЕДУПРЕЖДЕНИЕ] npm run build завершился с ошибкой.
            ) else (
                echo  Local Comet Editor установлен и собран успешно.
            )
        )
        popd
    ) else (
        echo  [!] local-comet-patch/server/package.json не найден — пропуск.
    )
)
echo.

:: -- 6. Настройка файла .env --------------------------------------------
echo  [6/6] Настройка файла .env...
echo.

if exist "%DEST%\.env" (
    echo  Файл .env уже существует. Используем его.
    echo  (Чтобы изменить токен - откройте .env в блокноте)
) else (
    echo  Файл .env не найден. Нужно ввести токен Telegram-бота.
    echo.
    echo  Как получить токен:
    echo    1. Откройте Telegram и найдите @BotFather
    echo    2. Отправьте /newbot и следуйте инструкциям
    echo    3. Скопируйте токен вида: 1234567890:AABBccDDeeFFggHH...
    echo.
    set "BOT_TOKEN="
    set /p "BOT_TOKEN= Введите BOT_TOKEN: "

    if "!BOT_TOKEN!"=="" (
        echo.
        echo  [ОШИБКА] Токен не введён. Создайте файл .env вручную:
        echo    1. Откройте Блокнот
        echo    2. Напишите: BOT_TOKEN=ваш_токен
        echo    3. Сохраните как "%DEST%\.env"
        echo.
        pause
        exit /b 1
    )

    echo BOT_TOKEN=!BOT_TOKEN!> "%DEST%\.env"
    echo  Файл .env создан.
)
echo.

:: -- Итог ---------------------------------------------------------------
echo +----------------------------------------------+
echo ^|       Установка завершена успешно!           ^|
echo +----------------------------------------------+
echo ^|  Для запуска используйте:                    ^|
echo ^|    ЗАПУСТИТЬ_БОТА.bat                        ^|
echo ^|    (запустит VM + Local Comet + бот)         ^|
echo ^|                                              ^|
echo ^|  Для обновления:                             ^|
echo ^|    ОБНОВИТЬ.bat                              ^|
echo +----------------------------------------------+
echo.
echo  Папка проекта: %DEST%
echo.

:: -- Предлагаем сразу запустить бота -----------------------------------
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
echo  Запуск VM-сервера и Telegram-бота...
call "%DEST%\ЗАПУСТИТЬ_БОТА.bat"
goto :END

:SKIP_LAUNCH
echo.
echo  Готово! Дважды кликните ЗАПУСТИТЬ_БОТА.bat для запуска.
echo.

:END
pause
