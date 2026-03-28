# drgr-bot

Telegram-бот с веб-интерфейсом и VM-сервером для управления AI-моделями (Ollama, LM Studio и др.).

---

## ⚡ Установить одной командой PowerShell

> **Самый простой способ — без Git, без ручного скачивания файлов!**

Откройте **PowerShell** (Win+R → `powershell`) и вставьте:

```powershell
irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/start_vm.ps1?$(Get-Random)" | iex
```

## 💻 PowerShell команды (скачать / запустить / обновить)

### 1) Скачать и установить (без Git)

```powershell
irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/start_vm.ps1?$(Get-Random)" | iex
```

### 2) Запустить уже установленный проект (надёжный вариант)

```powershell
$RunBat = @(
  (Join-Path ([Environment]::GetFolderPath('Desktop')) 'drgr-bot\ЗАПУСТИТЬ_БОТА.bat'),
  (Join-Path (Join-Path $env:USERPROFILE 'Desktop') 'drgr-bot\ЗАПУСТИТЬ_БОТА.bat')
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if ($RunBat) {
  & $RunBat
} else {
  irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/start_vm.ps1?$(Get-Random)" | iex
}
```

Если в вашей системе плохо работают русские имена файлов, используйте ASCII-алиас:

```powershell
$RunBat = @(
  (Join-Path ([Environment]::GetFolderPath('Desktop')) 'drgr-bot\START.bat'),
  (Join-Path (Join-Path $env:USERPROFILE 'Desktop') 'drgr-bot\START.bat')
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if ($RunBat) {
  & $RunBat
} else {
  irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/start_vm.ps1?$(Get-Random)" | iex
}
```

### 3) Обновить до последней версии (надёжный вариант)

```powershell
$UpdateBat = @(
  (Join-Path ([Environment]::GetFolderPath('Desktop')) 'drgr-bot\ОБНОВИТЬ.bat'),
  (Join-Path (Join-Path $env:USERPROFILE 'Desktop') 'drgr-bot\ОБНОВИТЬ.bat')
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if ($UpdateBat) {
  & $UpdateBat
} else {
  irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/start_vm.ps1?$(Get-Random)" | iex
}
```

ASCII-алиас для обновления:

```powershell
$UpdateBat = @(
  (Join-Path ([Environment]::GetFolderPath('Desktop')) 'drgr-bot\UPDATE.bat'),
  (Join-Path (Join-Path $env:USERPROFILE 'Desktop') 'drgr-bot\UPDATE.bat')
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if ($UpdateBat) {
  & $UpdateBat
} else {
  irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/start_vm.ps1?$(Get-Random)" | iex
}
```

Скрипт автоматически:

1. Скачает все файлы проекта с GitHub (ZIP, **Git не нужен**)
2. Создаст папку `drgr-bot` на **Рабочем столе**
3. Установит зависимости Python
4. Создаст ярлык **🟢 "ЗАПУСТИТЬ БОТА"** на Рабочем столе
5. Создаст ярлык **📁 "drgr-bot (папка)"** для быстрого доступа к файлам
6. Создаст совместимые файлы **`ЗАПУСТИТЬ_БОТА.bat`**, **`ОБНОВИТЬ.bat`**, **`START.bat`** и **`UPDATE.bat`** на Рабочем столе
7. Предложит ввести токен бота и сразу запустить

> ⚠️ Нужен **Python 3.10+** — скачать: https://www.python.org/downloads/
> При установке обязательно отметьте **"Add Python to PATH"**

После этого — двойной клик по **"ЗАПУСТИТЬ БОТА"** — и всё работает! 🚀

---

## 🖥️ Скачать вручную (без PowerShell)

Если PowerShell недоступен — скачайте и запустите **[УСТАНОВИТЬ.bat](https://github.com/ybiytsa1983-cpu/drgr-bot/raw/main/%D0%A3%D0%A1%D0%A2%D0%90%D0%9D%D0%9E%D0%92%D0%98%D0%A2%D0%AC.bat)**

---

## 🆘 Папка пропала / ничего не работает

**Быстрое восстановление — одной командой PowerShell** (Win+R → `powershell`):

```powershell
irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/start_vm.ps1?$(Get-Random)" | iex
```

Или запустите из папки проекта:

```
Рабочий стол\drgr-bot\ЗАПУСТИТЬ_БОТА.bat
```

---

## 🚀 Быстрый старт (с Git)

### Шаг 1 — Установите зависимости (один раз)

| Программа | Зачем | Ссылка |
|-----------|-------|--------|
| **Python 3.10+** | Запуск бота и сервера | https://www.python.org/downloads/ |
| **Git** | Клонирование и обновление репозитория | https://git-scm.com/download/win |

> ⚠️ При установке Python обязательно отметьте **"Add Python to PATH"**.

### Шаг 2 — Скачайте скрипт установки

Скачайте файл **[УСТАНОВИТЬ.bat](https://github.com/ybiytsa1983-cpu/drgr-bot/raw/main/%D0%A3%D0%A1%D0%A2%D0%90%D0%9D%D0%9E%D0%92%D0%98%D0%A2%D0%AC.bat)** и сохраните его в любое место (например, на Рабочий стол).

### Шаг 3 — Запустите УСТАНОВИТЬ.bat

Дважды кликните по скачанному файлу. Скрипт автоматически:

1. Клонирует репозиторий в папку `Рабочий стол\drgr-bot`
2. Установит все зависимости Python
3. Попросит ввести токен Telegram-бота (один раз)
4. Создаст значок **"ЗАПУСТИТЬ БОТА"** прямо на Рабочем столе
5. Предложит сразу запустить бота

---

## ▶️ Запуск бота

После установки используйте файл в папке проекта:

```
Рабочий стол\drgr-bot\ЗАПУСТИТЬ_БОТА.bat
```

Скрипт запустит окно:
- **DRGR VM Server** — локальный сервер (`http://localhost:5001`)

Telegram-бот запускается и останавливается из веб-интерфейса VM.

---

## 🔄 Обновление

Для получения новой версии запустите:

```
Рабочий стол\drgr-bot\ОБНОВИТЬ.bat
```

Скрипт обновит код, установит новые зависимости и предложит откатиться, если что-то пошло не так.

---

## ⚙️ Ручная установка

Если автоматический скрипт не работает, выполните в командной строке:

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
├── bot.py                 # Telegram-бот
├── vm/
│   ├── server.py          # VM-сервер (Flask)
│   └── static/
│       └── index.html     # Веб-интерфейс
├── requirements.txt       # Зависимости Python
├── .env                   # Токен бота (не в репозитории!)
├── start_vm.ps1           # ⭐ Установщик — одна команда PowerShell (рекомендуется)
├── УСТАНОВИТЬ.bat         # Первичная установка (требует Git)
├── ЗАПУСТИТЬ_БОТА.bat     # Запуск VM-сервера (бот управляется из UI)
└── ОБНОВИТЬ.bat           # Обновление до последней версии
```

---

## ❓ Решение проблем

**Хочу установить всё одной командой**
→ PowerShell (Win+R → `powershell`): `irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/start_vm.ps1?$(Get-Random)" | iex`

**Хочу скачать файлы без Git**
→ Используйте команду PowerShell выше — она скачает ZIP без Git.

**Папка drgr-bot пропала с Рабочего стола**
→ Запустите команду PowerShell выше — восстановит всё, токен сохранится.

**PowerShell пишет, что ЗАПУСТИТЬ_БОТА.bat / ОБНОВИТЬ.bat не найден**
→ Используйте блоки команд из раздела **"💻 PowerShell команды (скачать / запустить / обновить)"** — они сами проверяют путь, и если папки нет, автоматически запускают установщик.

**"Python не найден"**
→ Установите Python с https://www.python.org/downloads/ (отметьте "Add Python to PATH") и запустите скрипт снова.

**"Git не найден"**
→ Используйте команду PowerShell выше (Git не нужен) или установите Git с https://git-scm.com/download/win

**Бот не отвечает в Telegram**
→ Проверьте, что токен в файле `.env` правильный, и запустите/проверьте бота в веб-интерфейсе VM (`http://localhost:5001`).

**VM-сервер недоступен (http://localhost:5001)**
→ Проверьте, что окно "DRGR VM Server" открыто. Если нет — запустите `ЗАПУСТИТЬ_БОТА.bat` снова.
