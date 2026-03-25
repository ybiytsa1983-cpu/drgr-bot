# ⚡ Code VM — AI-редактор кода с qwen / llama

Monaco Editor + Flask + Ollama. Пишешь промпт — получаешь код.  
Переобучение моделей через вкладку **🧠 Переученная ВМ**.

---

## ▶▶▶ КОМАНДА ДЛЯ СКАЧИВАНИЯ И ЗАПУСКА ◀◀◀

**Открой PowerShell** (Win+X → «Windows PowerShell») и вставь одну строку:

```powershell
irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/run.ps1" | iex
```

> Скрипт сам: скачает репозиторий, установит зависимости, создаст ярлыки на Рабочем столе и запустит VM.  
> **Git не установлен?** → Сначала: <https://git-scm.com/download/win> — затем повтори команду выше.

---

## 🔄 КОМАНДА ДЛЯ СКАЧИВАНИЯ НОВЫХ ФАЙЛОВ (ОБНОВЛЕНИЕ)

**Способ 1 — двойной клик:** найди файл `ОБНОВИТЬ.bat` на Рабочем столе (или в папке `drgr-bot`) и дважды кликни по нему.

**Способ 2 — через PowerShell** (Win+X → Windows PowerShell):

```powershell
irm 'https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/update.ps1' | iex
```

**Способ 3 — вручную** (если репозиторий уже скачан в `%USERPROFILE%\drgr-bot`):

```powershell
Set-Location "$env:USERPROFILE\drgr-bot"; git pull
```

Скрипт автоматически:
- проверит наличие новых коммитов и покажет список изменённых файлов
- скачает обновления (`git pull`)
- обновит Python-зависимости (`pip install -r requirements.txt`)

> После обновления перезапусти Code VM:
> ```powershell
> powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\drgr-bot\start.ps1"
> ```

---

## 🧠 ГДЕ ПЕРЕУЧЕННАЯ ВМ?

После запуска открой браузер на **http://localhost:5000/** и нажми вкладку **`🧠 Переученная ВМ`** в верхней панели.

Там есть большая кнопка **«⚡ Создать переученную ВМ (drgr-visor)»** — нажми её и жди 1–3 минуты.

**Или с рабочего стола — двойной клик:**

| Файл на рабочем столе | Что делает |
|----------------------|-----------|
| **`ЗАПУСТИТЬ_ВМ.bat`** | Запускает Code VM + **автоматически создаёт drgr-visor** |
| **`ПЕРЕУЧИТЬ_ВМ.bat`** | Только переучить — создать / обновить drgr-visor |
| **`ОБНОВИТЬ.bat`** | Скачать и установить новые файлы (обновление) |
| **`Code VM.lnk`** | Обычный запуск Code VM без переучивания |
| **`ЗАПУСТИТЬ.bat`** | Резервный лаунчер — найдёт repo сам |

**Если файлов нет на рабочем столе** — вставь в PowerShell (Win+X → Windows PowerShell):

```powershell
irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/run.ps1" | iex
```

---

## 🔑 КАК СМЕНИТЬ ТОКЕН БОТА

1. Открой **http://localhost:5000/**
2. Нажми кнопку **☰** (левый верхний угол)
3. Найди раздел **«📱 Telegram Bot Token»**
4. Введи токен → нажми **«💾 Сохранить токен»**
5. ✅ **Бот перезапустится автоматически** — никаких дополнительных действий не нужно

> Если бот почему-то не отвечает после смены токена — запусти вручную:
> `powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\drgr-bot\ЗАПУСТИТЬ_ВСЕ.ps1"`

---

## 🚀 ОДНА КОМАНДА — УСТАНОВКА И ЗАПУСК

**Открой PowerShell (Win+X → Windows PowerShell) и вставь:**

```powershell
irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/run.ps1" | iex
```

> Это **единственная команда**, которую нужно знать.  
> Она сама: скачает репозиторий, установит Python-зависимости, создаст ярлыки на Рабочем столе и запустит VM.  
> **Git не установлен?** → Сначала: https://git-scm.com/download/win — потом повтори команду выше.

---

## 🖱 ЗАПУСК С РАБОЧЕГО СТОЛА (после установки)

После установки на Рабочем столе появятся **четыре файла**:

| Файл | Описание |
|------|----------|
| **`Code VM`** | Основной ярлык — двойной клик запускает всё |
| **`ЗАПУСТИТЬ.bat`** | Резервный — находит repo сам и запускает VM |
| **`ЗАПУСТИТЬ_ВМ.bat`** | Запуск VM + **создание переученной модели drgr-visor** |
| **`ПЕРЕУЧИТЬ_ВМ.bat`** | **Только переучить** — создать / обновить drgr-visor |
| **`ОБНОВИТЬ.bat`** | **Скачать и установить новые файлы** (обновление) |

Или из PowerShell (всегда работает):
```powershell
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\drgr-bot\start.ps1"
```

---

## ⬇ СКАЧАТЬ ВСЁ (ZIP, без команд)

Если не хочешь вводить команды — просто скачай архив и распакуй:

**[📦 Скачать drgr-bot.zip](https://github.com/ybiytsa1983-cpu/drgr-bot/archive/refs/heads/main.zip)**

После распаковки:
1. Открой папку из архива (имя вроде `drgr-bot-...`) — переименуй её в `drgr-bot`
2. Запусти **PowerShell** в этой папке (Shift+ПКМ → «Открыть окно PowerShell здесь»)
3. Вставь: `Set-ExecutionPolicy Bypass -Scope Process -Force; .\install.ps1`

---

## 🆘 НЕТ НИЧЕГО? НЕТ ЯРЛЫКА? НЕТ ФАЙЛОВ? НАЧНИ ЗДЕСЬ

**Нажми Win+X → «Windows PowerShell» и вставь одну строку:**

```powershell
irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/run.ps1" | iex
```

> Это скачает и запустит установщик — он сам склонирует репозиторий, установит зависимости и создаст ярлык.  
> **Git не установлен?** → Сначала: https://git-scm.com/download/win — потом повтори команду выше.  
> ⚠️ Перед запуском убедись что URL ведёт именно на `github.com/ybiytsa1983-cpu/drgr-bot`.

---

## 🖥 ЧТО ВСТАВИТЬ В ТЕРМИНАЛ — ОДИН РАЗ

Открой **PowerShell** (Win+X → Windows PowerShell) и вставь всё сразу:

```powershell
$d="$env:USERPROFILE\drgr-bot"; if(Test-Path "$d\.git"){Set-Location $d; git pull}else{git clone https://github.com/ybiytsa1983-cpu/drgr-bot $d; Set-Location $d}; Set-ExecutionPolicy Bypass -Scope Process -Force; .\install.ps1
```

> **Папка уже есть?** Команда автоматически переключит ветку и обновит файлы.

> **Git не установлен?** Скачай: https://git-scm.com/download/win — установи с настройками по умолчанию, потом снова вставь команду выше.

> **Python не установлен?** Скачай: https://www.python.org/downloads/ — **ОБЯЗАТЕЛЬНО** поставь галочку «Add Python to PATH», потом снова вставь команду.

> ⚠️ **ЧАСТЫЕ ОШИБКИ при ручном клонировании** (не делай так):
> ```
> ❌  git clone https://...drgr-bot в%USERPROFILE%\drgr-bot    ← содержит 2 ошибки:
>                                   ↑ лишний символ              %USERPROFILE% не работает в PS
>
> ❌  install.ps1       ← PS не ищет скрипты в текущей папке без .\
> ❌  cd drgr-bot       ← только если уже в правильной папке
> ```
> **Правильный ручной вариант** (или просто используй однострочник выше):
> ```powershell
> Set-Location "$env:USERPROFILE"
> git clone https://github.com/ybiytsa1983-cpu/drgr-bot
> Set-Location drgr-bot
> .\install.ps1
> ```

Установка займёт ~2 минуты. После неё на Рабочем столе появятся два файла:
- **`Code VM`** — основной ярлык
- **`ЗАПУСТИТЬ.bat`** — резервный, на случай если ярлык не сработает

---

## 🖱 ПРОПАЛ ЯРЛЫК НА РАБОЧЕМ СТОЛЕ?

Если ярлык «Code VM» пропал или не работает — пересоздай его одной командой в PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\drgr-bot\vm\create_shortcut.ps1"
```

Или зайди в папку `drgr-bot` и дважды кликни по **`ЗАПУСТИТЬ_ВМ.bat`** — он пересоздаст ярлыки автоматически.

---

## ▶ ЗАПУСК (каждый раз после установки)

Вставь в **PowerShell** (Win+X → Windows PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\drgr-bot\start.ps1"
```

Или просто дважды кликни по ярлыку **«Code VM»** на Рабочем столе.

> ⚠️ **Видишь ошибки `'cal' is not recognized` или `'"SCRIPT_DIR=..."'`?**  
> Это проблема окончаний строк в `.bat` файлах. Исправляется [командой из раздела «ЕСЛИ ЧТО-ТО СЛОМАЛОСЬ»](#-если-что-то-сломалось) ниже, или просто запусти `.ps1` напрямую (команда выше — всегда работает).

---

## 🖱 ВСЕ СПОСОБЫ ЗАПУСКА

### Вариант 1 — двойной клик по ярлыку «Code VM»
Просто дважды кликни. Откроется браузер на `http://localhost:5000/`

### Вариант 2 — двойной клик по «ЗАПУСТИТЬ.bat»
Если ярлык не работает — кликай по этому файлу.  
Он сам найдёт папку `drgr-bot` на компьютере, обновится через git и откроет VM.

### Вариант 3 — из PowerShell (всегда работает)
```powershell
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\drgr-bot\start.ps1"
```

---

## ✅ ПРОВЕРКА — VM РАБОТАЕТ

После запуска открой в браузере: **http://localhost:5000/**

Должен увидеть редактор кода с шапкой «⚡ Code VM» и вкладками:

| Вкладка | Что делает |
|---------|-----------|
| ⚠ **Issues** | ошибки в коде |
| 🌐 **HTML** | предпросмотр HTML-страниц |
| 🧠 **AI** | чат с qwen / llama |
| 🚀 **Tasks** | готовые сложные задачи |
| 📈 **Stats** | статистика генераций |
| 🔧 **Workshop** | скачать / создать / удалить модель Ollama |

**Проверка кода:** вставь в редактор:
```python
print("VM работает!")
```
Нажми **▶ Run** (или Ctrl+Enter). В панели Output появится `VM работает!`

**Проверка AI:** открой вкладку **🧠 AI** → если видишь «Ollama not connected» — Ollama не запущена (смотри раздел ниже).

---

## 🤖 КАК ПОДКЛЮЧИТЬ OLLAMA (qwen)

Ollama — движок для запуска qwen, llama и других моделей локально.

**Шаг 1 — установка Ollama** (если не установлена):
```powershell
winget install Ollama.Ollama
```
или скачай вручную: https://ollama.com/download

**Шаг 2 — скачай модель** (один раз, ~4 ГБ):
```powershell
ollama pull qwen:latest
```
или прямо в VM → вкладка **🔧 Workshop** → поле Pull → введи `qwen:latest` → кнопка «⬇ Pull»

**Шаг 3 — запусти Ollama** (если не запущена):
```powershell
ollama serve
```
Оставь это окно открытым, открой новый PowerShell и запусти VM.

После этого в вкладке **🧠 AI** статус изменится на зелёный «Connected».

---

## 🔧 WORKSHOP — создать свою модель кодера

1. Запусти VM → вкладка **🔧 Workshop**
2. В блоке **Pull** — введи `qwen:latest` → кнопка **⬇ Pull** (скачает модель, ~4 ГБ)
3. В блоке **Create** — имя `my-coder` → нажми **🛠 Create**  
   Modelfile уже заполнен — система-промпт для программирования с `temperature 0.4`
4. Готово! Модель `my-coder` появится в выпадающих списках вкладок AI и Generate

---

## ⚡ ГЕНЕРАЦИЯ КОДА (qwen → код)

Нажми **⚡ Generate** (или Ctrl+G):
- Выбери модель (например `my-coder` или `qwen:latest`)
- Выбери язык (Python / JavaScript)
- Напиши промпт: `HTTP-сервер с endpoint /health`
- Кнопка **▶ Code** — код вставится в редактор автоматически

Или вкладка **🌐 HTML** → напиши промпт → **🌐 Generate HTML Page** — получишь готовую страницу с превью.

---

## 🌐 АДРЕСА В БРАУЗЕРЕ

| Адрес | Что открывает |
|-------|--------------|
| `http://localhost:5000/` | ⚡ Code VM — редактор кода |
| `http://localhost:5000/navigator/` | 🧭 Android-навигатор (PWA) |

---

## 🛑 ЕСЛИ ЧТО-ТО СЛОМАЛОСЬ

### ❌ Ошибки вроде `'cal' is not recognized` / `'"SCRIPT_DIR=..."'` / `'xist'` / `'se'` при запуске .bat файла

Это **проблема окончаний строк** (LF вместо CRLF). Файл `.bat` скачался с неправильными окончаниями строк и Windows `cmd.exe` «проглатывает» первый символ каждой строки.

**Исправление — вставь в PowerShell** (Win+X → Windows PowerShell):

```powershell
# 1. Перейти в папку репозитория и обновить файлы
cd "$env:USERPROFILE\drgr-bot"
git pull

# 2. Исправить окончания строк во всех .bat файлах (LF → CRLF)
Get-ChildItem -Recurse -Filter *.bat | ForEach-Object {
    $t = [IO.File]::ReadAllText($_.FullName)
    $n = ($t -replace "`r`n","`n" -replace "`r","`n") -replace "`n","`r`n"
    if ($t -ne $n) { [IO.File]::WriteAllText($_.FullName, $n) }
}

# 3. Запустить Code VM
powershell -ExecutionPolicy Bypass -File start.ps1
```

Выдели **все строки** выше (Ctrl+A в блоке кода), вставь в PowerShell — Code VM откроется автоматически.

> Если папка `drgr-bot` не в домашней директории (`%USERPROFILE%`), замени путь на свой, например `cd "C:\drgr-bot"`.

---

**«Python not found»** → установи Python с https://www.python.org/downloads/ (галочка «Add Python to PATH»)

**«Git не является командой»** → установи Git с https://git-scm.com/download/win

**«running scripts is disabled»** → выполни в PowerShell:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**«fatal: destination path already exists»** → папка уже есть, нужно обновить:
```powershell
Set-Location "$env:USERPROFILE\drgr-bot"; git pull; .\install.ps1
```

**«install.ps1: The term 'install.ps1' is not recognized»** → PowerShell не выполняет скрипты из текущей папки без `.\`. Также убедись, что ты **находишься в папке `drgr-bot`** (`Set-Location "$env:USERPROFILE\drgr-bot"`), а не где-то ещё:
```powershell
Set-Location "$env:USERPROFILE\drgr-bot"; .\install.ps1
```
Или используй однострочник из раздела [«ЧТО ВСТАВИТЬ В ТЕРМИНАЛ»](#-что-вставить-в-терминал--один-раз) — он правильный и обрабатывает всё автоматически.

**Клонировал в неправильную папку** (например, `в%USERPROFILE%\drgr-bot` — лишний символ `в` и `%USERPROFILE%` не работает в PowerShell, нужно `$env:USERPROFILE`) → удали неправильную папку и склонируй заново:
```powershell
# Правильный способ клонирования — 4 команды:
Set-Location "$env:USERPROFILE"
git clone https://github.com/ybiytsa1983-cpu/drgr-bot
Set-Location drgr-bot
.\install.ps1
```
> **Важно:** `%USERPROFILE%` — синтаксис **cmd.exe**. В PowerShell используй `$env:USERPROFILE`.

**Страница не открывается (ERR_CONNECTION_REFUSED)** → сервер не запущен. Запусти снова:
```powershell
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\drgr-bot\start.ps1"
```

**Обновить до последней версии:**
```powershell
Set-Location "$env:USERPROFILE\drgr-bot"; git pull; .\install.ps1
```

---

## 🗂 Структура проекта

```
drgr-bot/
├── run.ps1            ← bootstrap (irm … | iex) — скачать и установить с нуля
├── start.ps1          ← запуск в PowerShell
├── start.bat          ← двойной клик в Проводнике
├── start.sh           ← Linux/macOS
├── install.ps1        ← первоначальная установка
├── ЗАПУСТИТЬ.bat      ← резервный самоопределяющий лаунчер
└── vm/
    ├── server.py      ← Flask backend (порт 5000)
    └── static/
        └── index.html ← Monaco Editor UI
```

---

## 🐧 Linux / macOS

```bash
git clone https://github.com/ybiytsa1983-cpu/drgr-bot.git
cd drgr-bot
chmod +x start.sh && ./start.sh
```

---

## 🛠 Переменные окружения

| Переменная | По умолчанию | Описание |
|-----------|-------------|---------|
| `VM_PORT` | `5000` | Порт сервера |
| `OLLAMA_HOST` | *(авто, порты 11434-11444)* | Адрес Ollama |
| `OLLAMA_TIMEOUT` | `120` | Таймаут ответа AI (секунды) |
| `OLLAMA_DEFAULT_MODEL` | *(первая найденная)* | Принудительно выбрать модель |
