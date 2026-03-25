# drgr-bot

Telegram-бот с веб-интерфейсом и VM-сервером для управления AI-моделями.

---

## 🔽 КАК СКАЧАТЬ / УСТАНОВИТЬ

> **Нет папки на Рабочем столе? Не знаете с чего начать? — сделайте это:**

### ⚡ Способ 1 — Скачать и запустить BAT-файл (самый простой)

**Шаг 1.** Откройте **PowerShell** (Win+X → Windows PowerShell).

**Шаг 2.** Вставьте команду ниже — она скачает `УСТАНОВИТЬ.bat` на Рабочий стол и сразу запустит его:

```powershell
Invoke-WebRequest -Uri "https://github.com/ybiytsa1983-cpu/drgr-bot/raw/main/%D0%A3%D0%A1%D0%A2%D0%90%D0%9D%D0%9E%D0%92%D0%98%D0%A2%D0%AC.bat" -OutFile "$env:USERPROFILE\Desktop\УСТАНОВИТЬ.bat"; Start-Process "$env:USERPROFILE\Desktop\УСТАНОВИТЬ.bat"
```

> Батник всё сделает сам: клонирует репо, установит зависимости, попросит токен бота, создаст **значки на Рабочем столе** и предложит сразу запустить бота.

---

### ⚡ Способ 2 — PowerShell одной строкой (без BAT)

```powershell
Set-ExecutionPolicy -Scope Process Bypass; git clone https://github.com/ybiytsa1983-cpu/drgr-bot.git "$env:USERPROFILE\Desktop\drgr-bot"; Set-Location "$env:USERPROFILE\Desktop\drgr-bot"; pip install -r requirements.txt; .\create_shortcuts.ps1; Write-Host "Готово! Запустите ЗАПУСТИТЬ_БОТА.bat или значок на Рабочем столе." -ForegroundColor Green
```

> После выполнения появится папка `drgr-bot` и три ярлыка на Рабочем столе.  
> Укажите токен бота в файле `.env`, затем используйте значок **DRGR Bot**.

---

## ⚡ Команды PowerShell (быстрый справочник)

Откройте **PowerShell** (Win+X → Windows PowerShell) и вставьте нужную команду:

### 📥 Установить (первый раз)

```powershell
Set-ExecutionPolicy -Scope Process Bypass; git clone https://github.com/ybiytsa1983-cpu/drgr-bot.git "$env:USERPROFILE\Desktop\drgr-bot"; Set-Location "$env:USERPROFILE\Desktop\drgr-bot"; pip install -r requirements.txt; .\create_shortcuts.ps1; Write-Host "Готово! Укажите токен в файле .env, затем запустите ЗАПУСТИТЬ_БОТА.bat" -ForegroundColor Green
```

### 📥 Скачать только установщик (BAT-файл)

```powershell
Invoke-WebRequest -Uri "https://github.com/ybiytsa1983-cpu/drgr-bot/raw/main/%D0%A3%D0%A1%D0%A2%D0%90%D0%9D%D0%9E%D0%92%D0%98%D0%A2%D0%AC.bat" -OutFile "$env:USERPROFILE\Desktop\УСТАНОВИТЬ.bat"; Start-Process "$env:USERPROFILE\Desktop\УСТАНОВИТЬ.bat"
```

### ▶️ Запустить бота

**Способ 1 — BAT-файл (двойной клик):**

```powershell
Start-Process "$env:USERPROFILE\Desktop\drgr-bot\ЗАПУСТИТЬ_БОТА.bat"
```

Или просто дважды кликните **`DRGR Bot`** на Рабочем столе.

**Способ 2 — PowerShell-скрипт:**

```powershell
Set-ExecutionPolicy -Scope Process Bypass
Set-Location "$env:USERPROFILE\Desktop\drgr-bot"
.\run.ps1
```

### 🔄 Обновить бота

```powershell
Set-ExecutionPolicy -Scope Process Bypass; & "$env:USERPROFILE\Desktop\drgr-bot\update.ps1"
```

### 🔗 Восстановить ярлыки (значки) на Рабочем столе

```powershell
Set-ExecutionPolicy -Scope Process Bypass; & "$env:USERPROFILE\Desktop\drgr-bot\create_shortcuts.ps1"
```

### 🧩 Установить браузерное расширение

```powershell
Set-ExecutionPolicy -Scope Process Bypass; & "$env:USERPROFILE\Desktop\drgr-bot\УСТАНОВИТЬ_РАСШИРЕНИЕ.ps1"
```

---

## 🚀 Быстрый старт (первая установка)

> **Папка пропала с Рабочего стола?** Выполните шаги ниже — всё восстановится за пару минут.

### Шаг 1 — Установите зависимости (один раз)

| Программа | Зачем | Ссылка |
|-----------|-------|--------|
| **Python 3.10+** | Запуск бота и сервера | https://www.python.org/downloads/ |
| **Git** | Клонирование и обновление репозитория | https://git-scm.com/download/win |

> ⚠️ При установке Python обязательно отметьте **"Add Python to PATH"**.

### Шаг 2 — Скачайте скрипт установки

Выберите удобный способ:

| Способ | Как |
|--------|-----|
| **Батник (двойной клик)** | Команда PowerShell ниже скачает батник и сразу запустит его |
| **PowerShell (одна строка)** | Скопируйте команду и вставьте в PowerShell |

#### Скачать и запустить УСТАНОВИТЬ.bat (PowerShell, одна строка)

```powershell
Invoke-WebRequest -Uri "https://github.com/ybiytsa1983-cpu/drgr-bot/raw/main/%D0%A3%D0%A1%D0%A2%D0%90%D0%9D%D0%9E%D0%92%D0%98%D0%A2%D0%AC.bat" -OutFile "$env:USERPROFILE\Desktop\УСТАНОВИТЬ.bat"; Start-Process "$env:USERPROFILE\Desktop\УСТАНОВИТЬ.bat"
```

#### Или установить полностью через PowerShell (одна строка)

```powershell
Set-ExecutionPolicy -Scope Process Bypass; git clone https://github.com/ybiytsa1983-cpu/drgr-bot.git "$env:USERPROFILE\Desktop\drgr-bot"; Set-Location "$env:USERPROFILE\Desktop\drgr-bot"; pip install -r requirements.txt; .\create_shortcuts.ps1; Write-Host "Готово! Укажите токен в файле .env, затем запустите ЗАПУСТИТЬ_БОТА.bat" -ForegroundColor Green
```

Или если файл `install.ps1` уже скачан локально:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

### Шаг 3 — Запустите установщик

Скрипт автоматически:

1. Клонирует репозиторий в папку `Рабочий стол\drgr-bot`
2. Установит все зависимости Python
3. Попросит ввести токен Telegram-бота (один раз)
4. Создаст **значки прямо на Рабочем столе** для запуска, обновления и расширения
5. Предложит сразу запустить бота

---

## ▶️ Запуск бота

После установки используйте **ярлык на Рабочем столе** `DRGR Bot.lnk`, либо bat-файл напрямую:

```
Рабочий стол\drgr-bot\ЗАПУСТИТЬ_БОТА.bat
```

Скрипт запустит два окна:
- **DRGR VM Server** — локальный сервер (`http://localhost:5001`)
- **DRGR Telegram Bot** — Telegram-бот

---

## 🧩 Браузерное расширение

Расширение добавляет кнопку **D** в панель браузера: один клик — и открывается веб-интерфейс DRGR Bot.

### Установить расширение

**Способ 1 — Батник (двойной клик):**

Дважды кликните `УСТАНОВИТЬ_РАСШИРЕНИЕ.bat` в папке `drgr-bot` на Рабочем столе.  
Или используйте ярлык **DRGR Bot - Rasshirenie** на Рабочем столе (появляется после установки).

**Способ 2 — PowerShell:**

```powershell
Set-ExecutionPolicy -Scope Process Bypass; & "$env:USERPROFILE\Desktop\drgr-bot\УСТАНОВИТЬ_РАСШИРЕНИЕ.ps1"
```

**Способ 3 — Вручную (если автоматический не работает):**

1. Откройте в браузере: `chrome://extensions` (Chrome) или `edge://extensions` (Edge)
2. Включите **Режим разработчика** (переключатель в правом верхнем углу)
3. Нажмите **Загрузить распакованное**
4. Укажите папку: `C:\Users\ИМЯ\Desktop\drgr-bot\extension`
5. Значок **D** появится в панели браузера!

> **Иконки** генерируются автоматически при первом запуске расширения через Python + Pillow.  
> Если иконок нет: откройте PowerShell в папке проекта и выполните: `python extension\make_icons.py`

### Использование расширения

1. Убедитесь, что бот запущен (`ЗАПУСТИТЬ_БОТА.bat`)
2. Кликните значок **D** в панели браузера
3. Откроется всплывающее окно с кнопками:
   - **Открыть веб-интерфейс** — переходит на `http://localhost:5001`
   - **Открыть чат** — чат-комната
   - **Исследование** — веб-поиск с AI
   - **Генерация изображений** — создание картинок
   - **Проверить состояние** — проверяет, запущен ли сервер

---

## 🔄 Обновление

Используйте ярлык на Рабочем столе `DRGR Bot - Obnovit.lnk`, либо:

```
Рабочий стол\drgr-bot\ОБНОВИТЬ.bat
```

Или через PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
& "$env:USERPROFILE\Desktop\drgr-bot\update.ps1"
```

Скрипт обновит код, установит новые зависимости, восстановит ярлыки на Рабочем столе и предложит откатиться, если что-то пошло не так.

---

## ⚙️ Ручная установка

Если автоматический скрипт не работает, выполните команды вручную.

### Вариант A — CMD / Командная строка

```bat
:: Клонировать репозиторий на Рабочий стол
git clone https://github.com/ybiytsa1983-cpu/drgr-bot.git %USERPROFILE%\Desktop\drgr-bot

:: Перейти в папку
cd %USERPROFILE%\Desktop\drgr-bot

:: Установить зависимости
pip install -r requirements.txt

:: Создать файл .env с токеном бота
echo BOT_TOKEN=ВАШ_ТОКЕН_ЗДЕСЬ > .env
```

Затем запустите `ЗАПУСТИТЬ_БОТА.bat`.

### Вариант B — PowerShell

```powershell
# Разрешить выполнение скриптов в текущем сеансе
Set-ExecutionPolicy -Scope Process Bypass

# Клонировать репозиторий на Рабочий стол
git clone https://github.com/ybiytsa1983-cpu/drgr-bot.git "$env:USERPROFILE\Desktop\drgr-bot"

# Перейти в папку
Set-Location "$env:USERPROFILE\Desktop\drgr-bot"

# Установить зависимости
pip install -r requirements.txt

# Создать файл .env с токеном бота
"BOT_TOKEN=ВАШ_ТОКЕН_ЗДЕСЬ" | Set-Content .env -Encoding UTF8

# Создать ярлыки на Рабочем столе
.\create_shortcuts.ps1
```

Затем запустите `ЗАПУСТИТЬ_БОТА.bat` или ярлык `DRGR Bot.lnk` на Рабочем столе.

### Восстановление ярлыков (если пропали с Рабочего стола)

```powershell
Set-ExecutionPolicy -Scope Process Bypass
& "$env:USERPROFILE\Desktop\drgr-bot\create_shortcuts.ps1"
```

---

## 🔑 Файл .env

Файл `.env` должен находиться в папке `drgr-bot` и содержать токен бота:

```
BOT_TOKEN=1234567890:AABBccDDeeFFggHHiiJJkkLLmmNNooPP
```

Получить токен: откройте Telegram → найдите **@BotFather** → `/newbot`.

---

## 📁 Структура проекта

```
drgr-bot/
├── bot.py                        # Telegram-бот
├── vm/
│   ├── server.py                 # VM-сервер (Flask, порт 5001)
│   └── static/
│       └── index.html            # Веб-интерфейс
├── extension/                    # Браузерное расширение (Chrome/Edge)
│   ├── manifest.json             # Манифест расширения (MV3)
│   ├── popup.html                # Всплывающее окно
│   ├── popup.js                  # Логика popup
│   ├── make_icons.py             # Генератор PNG-иконок (Pillow)
│   └── icons/                   # PNG-иконки (16/48/128px, создаются скриптом)
├── requirements.txt              # Зависимости Python
├── .env                          # Токен бота (не в репозитории!)
├── УСТАНОВИТЬ.bat                # Первичная установка (двойной клик)
├── УСТАНОВИТЬ.ps1                # Первичная установка (PowerShell, кириллица)
├── install.ps1                   # Первичная установка (PowerShell, ASCII имя)
├── УСТАНОВИТЬ_РАСШИРЕНИЕ.bat     # Установка браузерного расширения (двойной клик)
├── УСТАНОВИТЬ_РАСШИРЕНИЕ.ps1     # Установка браузерного расширения (PowerShell)
├── ЗАПУСТИТЬ_БОТА.bat            # Запуск бота и VM-сервера
├── ОБНОВИТЬ.bat                  # Обновление до последней версии
├── update.ps1                    # Обновление (PowerShell, с откатом)
├── run.ps1                       # Запуск (PowerShell)
└── create_shortcuts.ps1          # Создание/восстановление ярлыков на Рабочем столе
```

---

## ❓ Решение проблем

**Ярлыков/значков нет на Рабочем столе**
→ Откройте PowerShell и выполните:
```powershell
Set-ExecutionPolicy -Scope Process Bypass; & "$env:USERPROFILE\Desktop\drgr-bot\create_shortcuts.ps1"
```
Появятся значки: `DRGR Bot`, `DRGR Bot - Obnovit`, `DRGR Bot - Rasshirenie`.

**Расширения нет / не устанавливается**
→ Откройте PowerShell и выполните:
```powershell
Set-ExecutionPolicy -Scope Process Bypass; & "$env:USERPROFILE\Desktop\drgr-bot\УСТАНОВИТЬ_РАСШИРЕНИЕ.ps1"
```
Или дважды кликните `УСТАНОВИТЬ_РАСШИРЕНИЕ.bat` в папке `drgr-bot`.

**Папка drgr-bot пропала с Рабочего стола**
→ Откройте PowerShell (Win+X) и выполните (скачает батник и запустит):
```powershell
Invoke-WebRequest -Uri "https://github.com/ybiytsa1983-cpu/drgr-bot/raw/main/%D0%A3%D0%A1%D0%A2%D0%90%D0%9D%D0%9E%D0%92%D0%98%D0%A2%D0%AC.bat" -OutFile "$env:USERPROFILE\Desktop\УСТАНОВИТЬ.bat"; Start-Process "$env:USERPROFILE\Desktop\УСТАНОВИТЬ.bat"
```

**"Python не найден"**
→ Установите Python с https://www.python.org/downloads/ (отметьте "Add Python to PATH") и запустите скрипт снова.

**"Git не найден"**
→ Установите Git с https://git-scm.com/download/win и запустите скрипт снова.

**Бот не отвечает в Telegram**
→ Проверьте, что токен в файле `.env` правильный и что окно "DRGR Telegram Bot" открыто и не показывает ошибок.

**VM-сервер недоступен (http://localhost:5001)**
→ Проверьте, что окно "DRGR VM Server" открыто. Если нет — запустите `ЗАПУСТИТЬ_БОТА.bat` снова.