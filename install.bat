@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

REM ===================================================================
REM  install.bat  -  Pervichnaya ustanovka drgr-bot
REM  Skachayte etot fayl i zapustite - on sdelaet vsyo sam:
REM   1. Kloniruet repozitoriy na Rabochiy stol
REM   2. Sozdayet fayl .env s tokenom bota
REM   3. Ustanavlivayet zavisimosti Python
REM   4. Zapuskayet bota i VM-server
REM ===================================================================

title drgr-bot - Ustanovka

echo.
echo +----------------------------------------------+
echo ^|        drgr-bot  -  Master ustanovki         ^|
echo +----------------------------------------------+
echo.

REM -- Tselevaya papka na Rabochem stole -----------------------------------
set "DEST=%USERPROFILE%\Desktop\drgr-bot"
set "REPO=https://github.com/ybiytsa1983-cpu/drgr-bot.git"

REM -- 1. Proverka Python --------------------------------------------------
echo  [1/5] Proverka Python...
python --version > nul 2>&1
if errorlevel 1 (
    echo.
    echo  [OSHIBKA] Python ne nayden!
    echo.
    echo  Ustanovite Python 3.10 ili pozzhe:
    echo    https://www.python.org/downloads/
    echo.
    echo  Pri ustanovke otmetyte galochku "Add Python to PATH"
    echo  Zatem zapustite etot fayl snova.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%V in ('python --version 2^>^&1') do echo  Nayden: %%V
echo.

REM -- 2. Proverka Git -----------------------------------------------------
echo  [2/5] Proverka Git...
git --version > nul 2>&1
if errorlevel 1 (
    echo.
    echo  [OSHIBKA] Git ne nayden!
    echo.
    echo  Ustanovite Git for Windows:
    echo    https://git-scm.com/download/win
    echo.
    echo  Posle ustanovki zapustite etot fayl snova.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%V in ('git --version 2^>^&1') do echo  Nayden: %%V
echo.

REM -- 3. Klonirovanie repozitoriya ----------------------------------------
echo  [3/5] Klonirovanie repozitoriya v %DEST%...
echo.

if exist "%DEST%\.git" (
    echo  Papka uzhe sushchestvuyet. Obnovlyaem...
    cd /d "%DEST%"
    git fetch origin main > nul 2>&1
    git reset --hard origin/main
    if errorlevel 1 (
        echo  [OSHIBKA] Ne udalos obnovit repozitoriy.
        pause
        exit /b 1
    )
    echo  Repozitoriy obnovlyon.
) else (
    if exist "%DEST%" (
        echo  [OSHIBKA] Papka "%DEST%" uzhe sushchestvuyet, no ne yavlyayetsya git-repozitoriem.
        echo  Pereymenuyte ili udalite yeyo vruchnuyu i zapustite snova.
        echo.
        pause
        exit /b 1
    )
    git clone "%REPO%" "%DEST%"
    if errorlevel 1 (
        echo.
        echo  [OSHIBKA] Ne udalos klonirovat repozitoriy.
        echo  Proverte podklyucheniye k internetu i poporobuite snova.
        echo.
        pause
        exit /b 1
    )
    echo  Repozitoriy uspeshno sklonirovan.
)
echo.

REM -- Perekhod v papku proyekta ------------------------------------------
cd /d "%DEST%"

REM -- 4. Ustanovka zavisimostey ------------------------------------------
echo  [4/5] Ustanovka zavisimostey Python...
pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo.
    echo  Preduprezhdenie: nekotorye zavisimosti ne ustanovilis.
    echo  Poprobuite vruchnuyu: pip install -r requirements.txt
    echo.
) else (
    echo  Zavisimosti ustanovleny uspeshno.
)
echo.

REM -- 5. Nastroyka .env --------------------------------------------------
echo  [5/5] Nastroyka .env...
echo.

if exist "%DEST%\.env" (
    echo  Fayl .env uzhe sushchestvuyet. Ispolzuyem ego.
    echo  Chtoby izmenit token - otkroyte .env v bloknote.
) else (
    echo  Fayl .env ne nayden. Nuzhno vvesti token Telegram-bota.
    echo.
    echo  Kak poluchit token:
    echo    1. Otkroyte Telegram i naydite @BotFather
    echo    2. Otpravte /newbot i sledujte instruktsiyam
    echo    3. Skopiruyte token vida: 1234567890:AABBccDDeeFF...
    echo.
    set "BOT_TOKEN="
    set /p "BOT_TOKEN= Vvedite BOT_TOKEN: "

    if "!BOT_TOKEN!"=="" (
        echo.
        echo  [OSHIBKA] Token ne vveden. Sozdayte .env vruchnuyu:
        echo    1. Otkroyte Bloknet (Notepad)
        echo    2. Napishite: BOT_TOKEN=vash_token
        echo    3. Sokhranite kak "%DEST%\.env"
        echo.
        pause
        exit /b 1
    )

    echo BOT_TOKEN=!BOT_TOKEN!> "%DEST%\.env"
    echo  Fayl .env sozdan.
)
echo.

REM -- Rezumat ------------------------------------------------------------
echo +----------------------------------------------+
echo ^|      Ustanovka zavershena uspeshno!          ^|
echo +----------------------------------------------+
echo ^|  Dlya zapuska bota ispolzuyte:               ^|
echo ^|    start.bat                                 ^|
echo ^|  Dlya obnovleniya ispolzuyte:                ^|
echo ^|    update.bat                                ^|
echo +----------------------------------------------+
echo.
echo  Papka proyekta: %DEST%
echo.

REM -- Predlagaem zapustit bota -------------------------------------------
:ASK_LAUNCH
set "LAUNCH="
set /p "LAUNCH= Zapustit bota pryamo seychas? (yes/no): "

if /i "!LAUNCH!"=="yes" goto :DO_LAUNCH
if /i "!LAUNCH!"=="y"   goto :DO_LAUNCH
if /i "!LAUNCH!"=="no"  goto :SKIP_LAUNCH
if /i "!LAUNCH!"=="n"   goto :SKIP_LAUNCH

echo  Vvedite "yes" ili "no".
goto :ASK_LAUNCH

:DO_LAUNCH
echo.
echo  Zapusk VM-servera i Telegram-bota...
call "%DEST%\start.bat"
goto :END

:SKIP_LAUNCH
echo.
echo  Gotovo! Dvazhdy klikite start.bat dlya zapuska.
echo.

:END
pause
