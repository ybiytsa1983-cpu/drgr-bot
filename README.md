# Психокоррекция

Платформа для психоэмоциональной оценки и коррекции на основе методов Пизека.

## Возможности

- **🧠 FER-анализ** -- анализ лицевой экспрессии (валентность, возбуждение, стресс)
- **👁️ Анализ зрачков** -- дилатация, анизокория → стресс / когнитивная нагрузка / расслабление
- **👀 Возраст по глазам** -- 5 параметров (морщины, мешки, склера, радужка, птоз) → оценка возраста
- **📊 Совокупная оценка** -- FER (40%) + зрачки (30%) + baseline (30%) → стресс-балл + рекомендации
- **📚 База знаний** -- научные источники, методики, принципы ВМ
- **21+ Gate** -- проверка возраста по лицу (вероятностная оценка)
- **Этика** -- обязательное информированное согласие, без диагнозов, только рекомендации

---

## 📥 Как скачать и установить

### Вариант 1 -- Быстрая установка (Windows, PowerShell)

Откройте PowerShell и выполните:

```powershell
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
irm https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/start_vm.ps1 | iex
```

Скрипт автоматически:
1. Скачает проект на рабочий стол
2. Установит зависимости Python
3. Запустит сервер
4. Создаст ярлык на рабочем столе

### Вариант 2 -- Скачать через Git

```bash
git clone https://github.com/ybiytsa1983-cpu/drgr-bot.git
cd drgr-bot
pip install -r requirements.txt
python vm/server.py
```

### Вариант 3 -- Скачать ZIP

1. Откройте https://github.com/ybiytsa1983-cpu/drgr-bot
2. Нажмите зелёную кнопку **Code** → **Download ZIP**
3. Распакуйте архив
4. Откройте папку и запустите:

```bash
pip install -r requirements.txt
python vm/server.py
```

### Требования

| Программа | Ссылка |
|-----------|--------|
| **Python 3.10+** | https://www.python.org/downloads/ |
| **Git** (для варианта 2) | https://git-scm.com/download/win |
| **Ollama** (для AI) | https://ollama.com |

> ⚠️ При установке Python отметьте **"Add Python to PATH"**.

---

## 🚀 Запуск

### PowerShell (рекомендуется)

```powershell
powershell -ExecutionPolicy Bypass -File start.ps1
```

### BAT файл

```
ЗАПУСТИТЬ_БОТА.bat
```

### Ручной запуск

```bash
pip install -r requirements.txt
python vm/server.py
```

После запуска откройте: **http://localhost:5002**

---

## 🧠 Веб-интерфейс

| Модуль | Функция |
|--------|---------|
| 📊 Статус модулей | Состояние Ollama, камеры, анализаторов, базы знаний |
| 📚 База знаний | Источники, методики, принципы ВМ, рекомендации |
| 🔬 Совокупная оценка | FER + зрачки + baseline → стресс-балл |
| 👁️ Анализ зрачков | Дилатация, анизокория, когнитивная нагрузка |
| 👀 Возраст по глазам | Оценка биологического возраста |
| 📄 Научные источники | Статьи, книги, исследования |

---

## 📁 Структура проекта

```
drgr-bot/
├── bot.py                 # Telegram-бот (aiogram 3.x)
├── vm/
│   ├── server.py          # Сервер (Flask, порт 5002)
│   └── static/
│       └── index.html     # Веб-интерфейс психокоррекции
├── psycho_platform/       # 🧠 Модуль психодиагностики
│   ├── schema.sql         #   Схема БД (8 таблиц)
│   ├── fer_config.py      #   Конфигурация FER-pipeline
│   ├── age_gate.py        #   Проверка возраста 21+
│   ├── consent.py         #   Информированное согласие
│   ├── camera.py          #   Управление камерой (OpenCV)
│   ├── knowledge_base.py  #   База знаний (источники + методики)
│   ├── pupil_analyzer.py  #   Анализ зрачков
│   ├── eye_age_estimator.py #  Возраст по глазам
│   ├── comprehensive_assessment.py # Совокупная оценка
│   └── README.md          #   Документация модуля
├── setup_training_archive.ps1  # Скрипт создания архива для обучения ВМ
├── start.ps1              # Лаунчер (Ollama, порты, зависимости)
├── start_vm.ps1           # Быстрый запуск + установка
├── requirements.txt       # Зависимости Python
├── УСТАНОВИТЬ.bat         # Первичная установка
├── ЗАПУСТИТЬ_БОТА.bat     # Запуск сервера
└── ОБНОВИТЬ.bat           # Обновление
```

---

## 🔄 Обновление

```
ОБНОВИТЬ.bat
```

---

## ❓ Решение проблем

**Порт 5002 занят**
→ Запустите с другим портом:
```powershell
# Windows PowerShell
$env:DRGR_PORT=5003; python vm/server.py

# Linux / macOS
DRGR_PORT=5003 python vm/server.py
```

**"Python не найден"**
→ Установите Python с https://www.python.org/downloads/ (отметьте "Add Python to PATH").

**Нет AI (анализ не работает)**
→ Установите Ollama: https://ollama.com → `ollama pull llama3`

---

## 📖 Архив для обучения ВМ

```powershell
.\setup_training_archive.ps1
```

Создаёт структуру каталогов и скачивает открытые ресурсы (статьи, описания моделей).

Подробнее: [psycho_platform/README.md](psycho_platform/README.md)