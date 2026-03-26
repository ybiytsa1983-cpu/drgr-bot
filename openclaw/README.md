# OpenClaw — AI-система подбора товаров для маркетплейсов

Полноценная AI-система для поиска перспективных товаров на Wildberries с интеграцией Alibaba/1688 и MPStats.

## Возможности

- 🤖 **Telegram-бот** — текстовые и голосовые запросы
- 📊 **Сбор данных** — Wildberries, MPStats, Alibaba/1688
- 💰 **Юнит-экономика** — автоматический расчёт маржи, ROI, точки безубыточности
- 🧠 **AI-рекомендации** — скоринг товаров через OpenClaw/Ollama
- 🗄️ **PostgreSQL** — хранение истории, трендов, аналитики
- 📈 **Dashboard** — веб-интерфейс с графиками и фильтрами

## Стек

| Компонент | Технология |
|---|---|
| Бот | Python 3.11 + aiogram 3.x |
| API | FastAPI + SQLAlchemy (asyncpg) |
| AI-агент | Ollama (llama3) / OpenAI-совместимый |
| БД | PostgreSQL 15 |
| Кэш | Redis 7 |
| Фоновые задачи | APScheduler |
| Парсинг | httpx + BeautifulSoup4 |
| Деплой | Docker Compose |
| Dashboard | HTML5 + Bootstrap 5 + Chart.js |

## Быстрый старт

### 1. Клонировать и настроить

```bash
cd openclaw
cp .env.example .env
# Заполнить .env: BOT_TOKEN, WB_API_KEY и другие ключи
```

### 2. Запустить

```bash
docker compose up --build -d
```

### 3. Применить миграции БД

```bash
docker compose exec api alembic upgrade head
```

### 4. Открыть Dashboard

```
http://localhost:8080
```

### 5. Запустить бота

Напишите боту `/start` в Telegram.

## Команды бота

| Команда | Описание |
|---|---|
| `/start` | Приветствие и меню |
| `/search <товар>` | Найти товар и показать аналитику |
| `/top` | Топ-10 перспективных товаров |
| `/calc <товар> <цена>` | Рассчитать юнит-экономику |
| `/category <категория>` | Аналитика по категории |
| `/report` | Получить дневной отчёт |
| `/settings` | Настройки (комиссии, регион) |

Голосовые сообщения автоматически транскрибируются и обрабатываются как текстовые команды.

## Архитектура

```
openclaw/
├── bot/          # Telegram-бот (aiogram 3.x)
├── api/          # FastAPI REST API
├── workers/      # Парсеры + планировщик
├── db/           # SQLAlchemy модели + Alembic миграции
├── ai_agent/     # OpenClaw AI агент
├── dashboard/    # Web-интерфейс
└── nginx/        # Nginx конфиг (reverse proxy)
```

## Конфигурация

Все настройки находятся в `.env` (скопируйте из `.env.example`).

Основные параметры:
- `BOT_TOKEN` — токен Telegram-бота (от @BotFather)
- `WB_API_KEY` — ключ Wildberries API
- `MPSTATS_API_KEY` — ключ MPStats
- `OLLAMA_URL` — URL локального Ollama (по умолчанию `http://localhost:11434`)
- `AI_MODEL` — модель для AI-рекомендаций (по умолчанию `llama3`)

## Деплой на macOS (iMac)

```bash
# Установить Docker Desktop для Mac
brew install --cask docker

# Запустить проект
cd openclaw
docker compose up -d
```

## Перенос на сервер

```bash
# Скопировать проект на сервер
rsync -avz openclaw/ user@server:/opt/openclaw/

# На сервере
cd /opt/openclaw
cp .env.example .env && nano .env
docker compose up -d
```
