# ⚡ Code VM — AI-редактор кода с qwen / llama

Monaco Editor + Flask + Ollama. Пишешь промпт — получаешь код.  
Переобучение моделей через вкладку **🔧 Workshop**.

---

## 🖥 ЧТО ВСТАВИТЬ В ТЕРМИНАЛ — ОДИН РАЗ

Открой **PowerShell** (Win+X → Windows PowerShell) и вставь всё сразу:

```powershell
$d="$env:USERPROFILE\drgr-bot"; if(Test-Path $d){cd $d; git pull}else{cd "$env:USERPROFILE"; git clone https://github.com/ybiytsa1983-cpu/drgr-bot.git; cd drgr-bot}; powershell -ExecutionPolicy Bypass -File install.ps1
```

> **Папка уже есть?** Команда автоматически сделает `git pull` и обновит файлы вместо повторного клонирования.

> **Git не установлен?** Скачай: https://git-scm.com/download/win — установи с настройками по умолчанию, потом снова вставь команду выше.

> **Python не установлен?** Скачай: https://www.python.org/downloads/ — **ОБЯЗАТЕЛЬНО** поставь галочку «Add Python to PATH», потом снова вставь команду.

Установка займёт ~2 минуты. После неё на Рабочем столе появятся два файла:
- **`Code VM`** — основной ярлык
- **`ЗАПУСТИТЬ.bat`** — резервный, на случай если ярлык не сработает

---

## ▶ ЗАПУСК (каждый раз после установки)

Вставь в **PowerShell** (Win+X → Windows PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\drgr-bot\start.ps1"
```

Или просто дважды кликни по ярлыку **«Code VM»** на Рабочем столе.

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

**«Python not found»** → установи Python с https://www.python.org/downloads/ (галочка «Add Python to PATH»)

**«Git не является командой»** → установи Git с https://git-scm.com/download/win

**«running scripts is disabled»** → выполни в PowerShell:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**«fatal: destination path already exists»** → папка уже есть, нужно обновить:
```powershell
cd "$env:USERPROFILE\drgr-bot"; git pull; powershell -ExecutionPolicy Bypass -File install.ps1
```

**Страница не открывается (ERR_CONNECTION_REFUSED)** → сервер не запущен. Запусти снова:
```powershell
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\drgr-bot\start.ps1"
```

**Обновить до последней версии:**
```powershell
cd "$env:USERPROFILE\drgr-bot"; git pull; powershell -ExecutionPolicy Bypass -File install.ps1
```

---

## 🗂 Структура проекта

```
drgr-bot/
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
