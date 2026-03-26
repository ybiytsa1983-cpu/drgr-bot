@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

title DRGR - Управление AI-сервисами

:MENU
cls
echo.
echo +==============================================================+
echo ^|        DRGR  -  Запуск и настройка AI-сервисов             ^|
echo +==============================================================+
echo.
echo  Текущий статус (порты):

:: Проверяем порты
for /f "tokens=*" %%P in ('netstat -an 2^>nul ^| findstr ":11434 " ^| findstr LISTENING 2^>nul') do set OLLAMA_UP=1
for /f "tokens=*" %%P in ('netstat -an 2^>nul ^| findstr ":5000 "  ^| findstr LISTENING 2^>nul') do set TGWUI_UP=1
for /f "tokens=*" %%P in ('netstat -an 2^>nul ^| findstr ":8188 "  ^| findstr LISTENING 2^>nul') do set COMFY_UP=1
for /f "tokens=*" %%P in ('netstat -an 2^>nul ^| findstr ":7860 "  ^| findstr LISTENING 2^>nul') do set SD_UP=1
for /f "tokens=*" %%P in ('netstat -an 2^>nul ^| findstr ":5001 "  ^| findstr LISTENING 2^>nul') do set VM_UP=1
for /f "tokens=*" %%P in ('netstat -an 2^>nul ^| findstr ":1234 "  ^| findstr LISTENING 2^>nul') do set LMS_UP=1

if defined OLLAMA_UP (echo   [OK] Ollama      :11434) else (echo   [--] Ollama      :11434  - не запущен)
if defined LMS_UP    (echo   [OK] LM Studio   :1234 ) else (echo   [--] LM Studio   :1234   - не запущен)
if defined TGWUI_UP  (echo   [OK] TGWUI       :5000 ) else (echo   [--] TGWUI       :5000   - не запущен)
if defined SD_UP     (echo   [OK] SD WebUI    :7860 ) else (echo   [--] SD WebUI    :7860   - не запущен)
if defined COMFY_UP  (echo   [OK] ComfyUI     :8188 ) else (echo   [--] ComfyUI     :8188   - не запущен)
if defined VM_UP     (echo   [OK] DRGR VM     :5001 ) else (echo   [--] DRGR VM     :5001   - не запущен)

echo.
echo  +----- Меню --------------------------------------------------+
echo  ^|  1. Запустить ВСЕ сервисы (через Docker Compose)           ^|
echo  ^|  2. Остановить все Docker-сервисы                          ^|
echo  ^|  3. Установить Docker Desktop (откроет браузер)            ^|
echo  ^|  4. Установить и запустить Ollama (без Docker)             ^|
echo  ^|  5. Скачать модель в Ollama                                ^|
echo  ^|  6. Открыть DRGR VM в браузере                            ^|
echo  ^|  7. Открыть Ollama WebUI в браузере                        ^|
echo  ^|  8. Запустить только DRGR VM (без Docker)                  ^|
echo  ^|  9. Проверить статус / обновить                            ^|
echo  ^|  0. Выход                                                   ^|
echo  +-------------------------------------------------------------+
echo.
set /p CHOICE="  Введите номер: "

if "%CHOICE%"=="1" goto DOCKER_UP
if "%CHOICE%"=="2" goto DOCKER_DOWN
if "%CHOICE%"=="3" goto INSTALL_DOCKER
if "%CHOICE%"=="4" goto INSTALL_OLLAMA
if "%CHOICE%"=="5" goto PULL_MODEL
if "%CHOICE%"=="6" goto OPEN_VM
if "%CHOICE%"=="7" goto OPEN_WEBUI
if "%CHOICE%"=="8" goto RUN_VM_LOCAL
if "%CHOICE%"=="9" goto MENU
if "%CHOICE%"=="0" exit /b 0
goto MENU

:: ====================================================================
:DOCKER_UP
echo.
echo  [*] Запускаю все AI-сервисы через Docker Compose...
echo      (первый запуск занимает несколько минут - скачиваются образы)
echo.

:: Проверяем наличие Docker
docker --version > nul 2>&1
if errorlevel 1 (
    echo  [ОШИБКА] Docker не найден!
    echo  Выберите пункт 3 для установки Docker Desktop.
    echo.
    pause
    goto MENU
)

:: Находим папку проекта
set "PROJ=%~dp0"
if not exist "%PROJ%docker-compose.yml" (
    echo  [ОШИБКА] docker-compose.yml не найден в %PROJ%
    pause
    goto MENU
)

cd /d "%PROJ%"
docker compose up -d
echo.
echo  [OK] Сервисы запущены!
echo.
echo  Доступные адреса:
echo    DRGR VM:      http://localhost:5001
echo    Ollama WebUI: http://localhost:3000
echo    TGWUI:        http://localhost:5000
echo    ComfyUI:      http://localhost:8188
echo    SD WebUI:     http://localhost:7860
echo.
echo  Подождите 30-60 секунд для полной загрузки сервисов.
echo.
pause
goto MENU

:: ====================================================================
:DOCKER_DOWN
echo.
echo  [*] Останавливаю все Docker-сервисы...
cd /d "%~dp0"
docker compose down
echo  [OK] Сервисы остановлены.
echo.
pause
goto MENU

:: ====================================================================
:INSTALL_DOCKER
echo.
echo  [*] Открываю страницу загрузки Docker Desktop...
start https://www.docker.com/products/docker-desktop/
echo.
echo  После установки Docker Desktop:
echo    1. Перезагрузите компьютер
echo    2. Запустите Docker Desktop
echo    3. Вернитесь сюда и выберите пункт 1
echo.
pause
goto MENU

:: ====================================================================
:INSTALL_OLLAMA
echo.
echo  [*] Проверяю Ollama...
ollama --version > nul 2>&1
if not errorlevel 1 (
    echo  [OK] Ollama уже установлен.
    echo.
    echo  Запускаю сервер Ollama...
    start "Ollama Server" cmd /k "ollama serve"
    echo  [OK] Ollama запущен на http://localhost:11434
) else (
    echo  Ollama не найден. Скачиваю установщик...
    start https://ollama.com/download/OllamaSetup.exe
    echo.
    echo  После установки Ollama вернитесь и выберите этот пункт снова.
)
echo.
pause
goto MENU

:: ====================================================================
:PULL_MODEL
echo.
echo  Популярные модели:
echo    llama3        - LLaMA 3 8B (4.7 GB)
echo    llama3:70b    - LLaMA 3 70B (40 GB, нужен мощный ПК)
echo    mistral       - Mistral 7B (4.1 GB)
echo    codellama     - CodeLlama 7B (3.8 GB, оптимален для кода)
echo    phi3          - Microsoft Phi-3 3.8B (2.3 GB, быстрый)
echo    moondream     - Moondream 1.8B (1.7 GB, распознавание изображений)
echo    qwen2         - Qwen 2 7B (4.4 GB)
echo.
set /p MODEL="  Введите имя модели (или Enter для llama3): "
if "%MODEL%"=="" set MODEL=llama3
echo.
echo  [*] Скачиваю модель %MODEL%...
ollama pull %MODEL%
echo.
echo  [OK] Модель скачана: %MODEL%
pause
goto MENU

:: ====================================================================
:OPEN_VM
start http://localhost:5001
goto MENU

:: ====================================================================
:OPEN_WEBUI
start http://localhost:3000
goto MENU

:: ====================================================================
:RUN_VM_LOCAL
echo.
echo  [*] Запускаю DRGR VM локально (без Docker)...
set "PROJ=%~dp0"
cd /d "%PROJ%"

python --version > nul 2>&1
if errorlevel 1 (
    echo  [ОШИБКА] Python не найден. Установите Python 3.10+.
    pause
    goto MENU
)

pip install flask > nul 2>&1
start "DRGR VM Server" cmd /k "cd /d %PROJ% && python vm/server.py"
timeout /t 3 > nul
start http://localhost:5001
echo.
echo  [OK] DRGR VM запущен: http://localhost:5001
pause
goto MENU
