"""
DRGR VM Server — полнофункциональный бэкенд.

Функции:
  • Управление ТГ-ботом (start / stop / status) как subprocess
  • Генератор статей (/research) — DDG + scrape + Ollama / LM Studio LLM
  • Чат с AI (/chat) — Ollama / LM Studio
  • Генерация текста (/generate) — промпт → LLM
  • Настройки (/settings GET/POST → .env)
  • Здоровье (/health, /extension/report)
  • CORS для chrome-extension://
  • Проекты (CRUD) + загрузка файлов
  • Интеграция TG сообщений (/chat/tg_messages)
"""
from __future__ import annotations

import html as _html
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from flask import Flask, jsonify, render_template, request, send_from_directory

# ---------------------------------------------------------------------------
#  Пути / директории
# ---------------------------------------------------------------------------
_BASE_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _BASE_DIR.parent
_PROJECTS_DIR = _BASE_DIR / "projects"
_PROJECTS_DIR.mkdir(exist_ok=True)

_ENV_PATH = _ROOT_DIR / ".env"
_BOT_SCRIPT = _ROOT_DIR / "bot.py"
_BOT_LOG = _ROOT_DIR / "bot_output.log"

# ---------------------------------------------------------------------------
#  Логирование
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("drgr-vm")

# ---------------------------------------------------------------------------
#  Flask
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder="static", template_folder="static")

# ---------------------------------------------------------------------------
#  CORS (для chrome-extension:// и localhost фронтенда)
# ---------------------------------------------------------------------------
def _add_cors(resp):
    origin = request.headers.get("Origin", "")
    if origin.startswith("chrome-extension://") or "localhost" in origin or "127.0.0.1" in origin:
        resp.headers["Access-Control-Allow-Origin"] = origin
    else:
        resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return resp

app.after_request(_add_cors)

@app.route("/", defaults={"path": ""}, methods=["OPTIONS"])
@app.route("/<path:path>", methods=["OPTIONS"])
def cors_preflight(path):
    return "", 204

# ---------------------------------------------------------------------------
#  .env чтение / запись
# ---------------------------------------------------------------------------
def _env_read() -> Dict[str, str]:
    """Прочитать .env файл в dict."""
    result: Dict[str, str] = {}
    if not _ENV_PATH.exists():
        return result
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        result[key] = val
    return result

def _env_save(data: Dict[str, str]) -> None:
    """Записать dict в .env файл."""
    lines: List[str] = []
    for k, v in data.items():
        k = re.sub(r"[^A-Za-z0-9_]", "", k)
        if not k:
            continue
        v = str(v).replace('"', '\\"')
        lines.append(f'{k}="{v}"')
    _ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

# ---------------------------------------------------------------------------
#  Управление ТГ-ботом
# ---------------------------------------------------------------------------
_bot_proc: Optional[subprocess.Popen] = None
_bot_lock = threading.Lock()

def _bot_start() -> Tuple[bool, str]:
    global _bot_proc
    with _bot_lock:
        if _bot_proc and _bot_proc.poll() is None:
            return False, "Бот уже запущен"
        if not _BOT_SCRIPT.exists():
            return False, f"bot.py не найден: {_BOT_SCRIPT}"
        env = os.environ.copy()
        env_data = _env_read()
        env.update(env_data)
        if not env.get("BOT_TOKEN"):
            return False, "BOT_TOKEN не задан в .env"
        try:
            log_fh = open(_BOT_LOG, "a", encoding="utf-8")  # noqa: SIM115
            _bot_proc = subprocess.Popen(
                [sys.executable, str(_BOT_SCRIPT)],
                cwd=str(_ROOT_DIR),
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                env=env,
            )
        except Exception as exc:
            try:
                log_fh.close()
            except Exception:
                pass
            return False, f"Ошибка запуска: {exc}"
        logger.info("Bot started, PID=%s", _bot_proc.pid)
        return True, f"Бот запущен (PID {_bot_proc.pid})"

def _bot_stop() -> Tuple[bool, str]:
    global _bot_proc
    with _bot_lock:
        if not _bot_proc or _bot_proc.poll() is not None:
            _bot_proc = None
            return False, "Бот не запущен"
        pid = _bot_proc.pid
        try:
            _bot_proc.terminate()
            _bot_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _bot_proc.kill()
        _bot_proc = None
        logger.info("Bot stopped, PID=%s", pid)
        return True, f"Бот остановлен (PID {pid})"

def _bot_get_status() -> Dict[str, Any]:
    with _bot_lock:
        if _bot_proc and _bot_proc.poll() is None:
            return {"running": True, "pid": _bot_proc.pid}
        return {"running": False, "pid": None}

# ---------------------------------------------------------------------------
#  Ollama / LM Studio — обнаружение и вызов
# ---------------------------------------------------------------------------
_OLLAMA_PROBE_PORTS = (11434, 11435, 11436, 11437)
_LMSTUDIO_PROBE_PORTS = (1234, 1235)

def _probe_service(host: str, port: int, path: str = "/", timeout: float = 2.0) -> bool:
    try:
        r = requests.get(f"http://{host}:{port}{path}", timeout=timeout)
        return r.status_code < 500
    except Exception:
        return False

def _find_ollama() -> Optional[str]:
    for p in _OLLAMA_PROBE_PORTS:
        if _probe_service("127.0.0.1", p, "/api/tags"):
            return f"http://127.0.0.1:{p}"
    return None

def _find_lmstudio() -> Optional[str]:
    for p in _LMSTUDIO_PROBE_PORTS:
        if _probe_service("127.0.0.1", p, "/v1/models"):
            return f"http://127.0.0.1:{p}"
    return None

def _llm_models() -> Dict[str, List[str]]:
    """Получить список доступных моделей из Ollama и LM Studio."""
    result: Dict[str, List[str]] = {"ollama": [], "lmstudio": []}
    base = _find_ollama()
    if base:
        try:
            r = requests.get(f"{base}/api/tags", timeout=3)
            for m in r.json().get("models", []):
                result["ollama"].append(m.get("name", "unknown"))
        except Exception:
            pass
    base = _find_lmstudio()
    if base:
        try:
            r = requests.get(f"{base}/v1/models", timeout=3)
            for m in r.json().get("data", []):
                result["lmstudio"].append(m.get("id", "unknown"))
        except Exception:
            pass
    return result

def _llm_chat(messages: List[Dict], model: Optional[str] = None) -> str:
    """Отправить запрос к локальному LLM (Ollama или LM Studio)."""
    base = _find_ollama()
    if base:
        payload: Dict[str, Any] = {"messages": messages, "stream": False}
        if model:
            payload["model"] = model
        else:
            models = _llm_models()
            if models["ollama"]:
                payload["model"] = models["ollama"][0]
            else:
                payload["model"] = "llama3"
        try:
            r = requests.post(f"{base}/api/chat", json=payload, timeout=120)
            data = r.json()
            return data.get("message", {}).get("content", str(data))
        except Exception as exc:
            logger.warning("Ollama chat error: %s", exc)

    base = _find_lmstudio()
    if base:
        payload = {"messages": messages, "stream": False}
        if model:
            payload["model"] = model
        try:
            r = requests.post(f"{base}/v1/chat/completions", json=payload, timeout=120)
            data = r.json()
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return str(data)
        except Exception as exc:
            logger.warning("LMStudio chat error: %s", exc)

    return "❌ Нет доступного LLM (Ollama / LM Studio). Запустите один из них."

# ---------------------------------------------------------------------------
#  Генератор статей (/research)
# ---------------------------------------------------------------------------
_DDG_BLACKLIST = {"mk.ru", "aif.ru", "kp.ru", "life.ru", "tvzvezda.ru", "ren.tv"}

def _research_ddg_search(query: str, max_results: int = 12) -> List[Dict]:
    try:
        from ddgs import DDGS
        results = list(DDGS().text(query, max_results=max_results))
    except Exception as exc:
        logger.warning("DDG search error: %s", exc)
        return []
    filtered = []
    for r in results:
        domain = urlparse(r.get("href", "")).netloc.lower().replace("www.", "")
        if domain not in _DDG_BLACKLIST:
            filtered.append(r)
    return filtered

def _research_scrape_url(url: str, timeout: float = 8.0) -> str:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        text = re.sub(r"<[^>]+>", " ", r.text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:3000]
    except Exception:
        return ""

def _research_build_article(query: str, sources: List[Dict], scraped: Dict[str, str]) -> str:
    """Собрать промпт и вызвать LLM для генерации статьи."""
    context_parts = []
    for i, s in enumerate(sources[:5], 1):
        url = s.get("href", "")
        title = s.get("title", "")
        body = s.get("body", "")
        extra = scraped.get(url, "")
        context_parts.append(f"[{i}] {title}\n{body}\n{extra[:500]}")
    context = "\n---\n".join(context_parts)

    prompt = (
        f"Напиши подробную аналитическую статью на тему: «{query}».\n"
        f"Используй следующие источники:\n{context}\n\n"
        "Требования:\n"
        "- Используй HTML с Bootstrap 5 классами.\n"
        "- Добавь оглавление (TOC) со ссылками.\n"
        "- Добавь таблицу данных если уместно.\n"
        "- В конце — список источников с кликабельными ссылками.\n"
        "- Пиши на русском языке.\n"
    )
    messages = [
        {"role": "system", "content": "Ты — аналитик-исследователь. Пишешь качественные HTML-статьи."},
        {"role": "user", "content": prompt},
    ]
    return _llm_chat(messages)

# ---------------------------------------------------------------------------
#  Health / Diagnostics
# ---------------------------------------------------------------------------
def _health() -> Dict[str, Any]:
    ollama_url = _find_ollama()
    lmstudio_url = _find_lmstudio()
    bot_st = _bot_get_status()
    models = _llm_models()
    return {
        "ollama": {"available": bool(ollama_url), "url": ollama_url, "models": models["ollama"]},
        "lmstudio": {"available": bool(lmstudio_url), "url": lmstudio_url, "models": models["lmstudio"]},
        "bot": bot_st,
        "env_exists": _ENV_PATH.exists(),
        "bot_script_exists": _BOT_SCRIPT.exists(),
    }

# ===========================================================================
#  ROUTES
# ===========================================================================

@app.route("/")
def index():
    return render_template("index.html")

# --- Проекты ---
@app.route("/api/projects", methods=["GET"])
def get_projects():
    projects = []
    for fn in _PROJECTS_DIR.iterdir():
        if fn.suffix in (".html", ".py", ".txt", ".json"):
            projects.append({
                "name": fn.name,
                "content": fn.read_text(encoding="utf-8", errors="replace"),
                "modified": datetime.fromtimestamp(fn.stat().st_mtime).isoformat(),
            })
    return jsonify(projects)

@app.route("/api/project", methods=["POST"])
def save_project():
    data = request.json or {}
    filename = data.get("filename", "").strip()
    content = data.get("content", "")
    if not filename:
        return jsonify({"error": "Missing filename"}), 400
    # Sanitize filename: strip path components, reject traversal
    filename = os.path.basename(filename)
    filename = re.sub(r"[^\w.\-]", "_", filename)
    if not filename or ".." in filename:
        return jsonify({"error": "Invalid filename"}), 400
    target = (_PROJECTS_DIR / filename).resolve()
    if not str(target).startswith(str(_PROJECTS_DIR.resolve())):
        return jsonify({"error": "Invalid filename"}), 400
    target.write_text(content, encoding="utf-8")
    return jsonify({"success": True})

@app.route("/api/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400
    safe_name = os.path.basename(f.filename)
    safe_name = re.sub(r"[^\w.\-]", "_", safe_name)
    if not safe_name or ".." in safe_name:
        return jsonify({"error": "Invalid filename"}), 400
    target = (_PROJECTS_DIR / safe_name).resolve()
    if not str(target).startswith(str(_PROJECTS_DIR.resolve())):
        return jsonify({"error": "Invalid filename"}), 400
    f.save(str(target))
    return jsonify({"success": True, "filename": safe_name})

# --- Бот ---
@app.route("/bot/start", methods=["POST"])
def bot_start():
    ok, msg = _bot_start()
    return jsonify({"ok": ok, "message": str(msg)})

@app.route("/bot/stop", methods=["POST"])
def bot_stop():
    ok, msg = _bot_stop()
    return jsonify({"ok": ok, "message": str(msg)})

@app.route("/bot/status", methods=["GET"])
def bot_status():
    return jsonify(_bot_get_status())

@app.route("/bot/log", methods=["GET"])
def bot_log():
    if _BOT_LOG.exists():
        text = _BOT_LOG.read_text(encoding="utf-8", errors="replace")
        lines = text.strip().split("\n")
        return jsonify({"lines": lines[-100:]})
    return jsonify({"lines": []})

# --- Настройки ---
@app.route("/settings", methods=["GET"])
def settings_get():
    data = _env_read()
    # Маскируем токены при выдаче
    masked = {}
    for k, v in data.items():
        if "TOKEN" in k.upper() or "KEY" in k.upper() or "SECRET" in k.upper():
            masked[k] = "****"
        else:
            masked[k] = v
    return jsonify(masked)

@app.route("/settings", methods=["POST"])
def settings_post():
    data = request.json or {}
    existing = _env_read()
    for k, v in data.items():
        k = re.sub(r"[^A-Za-z0-9_]", "", str(k))
        if not k:
            continue
        v = str(v).strip()
        # Не перезаписываем токен маской
        if v == "****" and k in existing:
            continue
        existing[k] = v
    _env_save(existing)
    return jsonify({"ok": True})

# --- Чат с AI ---
@app.route("/chat", methods=["POST"])
def chat():
    data = request.json or {}
    user_msg = data.get("message", "").strip()
    model = data.get("model")
    if not user_msg:
        return jsonify({"error": "Empty message"}), 400
    history = data.get("history", [])
    messages = [{"role": "system", "content": "Ты — умный ассистент DRGR. Отвечай полезно и кратко."}]
    for h in history[-10:]:
        messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
    messages.append({"role": "user", "content": user_msg})
    reply = _llm_chat(messages, model=model)
    return jsonify({"reply": reply})

# --- Генератор статей ---
@app.route("/research", methods=["POST"])
def research():
    data = request.json or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "Пустой запрос"}), 400

    # 1. Поиск DDG
    ddg_results = _research_ddg_search(query)
    if not ddg_results:
        return jsonify({"error": "Ничего не найдено в DDG"}), 404

    # 2. Параллельный скрейпинг (до 5 URL)
    urls = [r.get("href", "") for r in ddg_results[:5] if r.get("href")]
    scraped: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_research_scrape_url, u): u for u in urls}
        for fut in as_completed(futures):
            url = futures[fut]
            try:
                scraped[url] = fut.result()
            except Exception:
                scraped[url] = ""

    # 3. Генерация статьи через LLM
    article_html = _research_build_article(query, ddg_results, scraped)

    return jsonify({
        "query": query,
        "sources": [{"title": r.get("title", ""), "url": r.get("href", "")} for r in ddg_results[:5]],
        "article": article_html,
    })

# --- Health ---
@app.route("/health", methods=["GET"])
def health():
    return jsonify(_health())

@app.route("/extension/report", methods=["GET"])
def extension_report():
    h = _health()
    lines = [
        "=== DRGR VM Health Report ===",
        f"Ollama: {'✅ ' + (h['ollama']['url'] or '') if h['ollama']['available'] else '❌ Недоступен'}",
        f"  Модели: {', '.join(h['ollama']['models']) or 'нет'}",
        f"LM Studio: {'✅ ' + (h['lmstudio']['url'] or '') if h['lmstudio']['available'] else '❌ Недоступен'}",
        f"  Модели: {', '.join(h['lmstudio']['models']) or 'нет'}",
        f"TG Bot: {'✅ PID=' + str(h['bot']['pid']) if h['bot']['running'] else '❌ Остановлен'}",
        f".env: {'✅' if h['env_exists'] else '❌ Нет файла'}",
        f"bot.py: {'✅' if h['bot_script_exists'] else '❌ Нет файла'}",
    ]
    return jsonify({"report": "\n".join(lines), "data": h})

# --- Модели ---
@app.route("/models", methods=["GET"])
def models():
    return jsonify(_llm_models())

# --- Goose AI (через LLM) ---
@app.route("/api/goose", methods=["POST"])
def goose_integration():
    data = request.json or {}
    query = data.get("query", "")
    if not query:
        return jsonify({"error": "Пустой запрос"}), 400
    reply = _llm_chat([
        {"role": "system", "content": "Ты — эксперт по коду. Анализируй и помогай."},
        {"role": "user", "content": query},
    ])
    return jsonify({"result": reply})

# --- Генерация текста (универсальный промпт → LLM) ---
@app.route("/generate", methods=["POST"])
def generate_text():
    """Генерация текста по произвольному промпту через LLM."""
    data = request.json or {}
    prompt = data.get("prompt", "").strip()
    system = data.get("system", "Ты — полезный AI-ассистент. Отвечай подробно.")
    model = data.get("model")
    if not prompt:
        return jsonify({"error": "Пустой промпт"}), 400
    reply = _llm_chat([
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ], model=model)
    return jsonify({"result": reply})

# --- 3D генерация (через LLM — генерация Three.js кода) ---
@app.route("/api/generate-3d", methods=["POST"])
def generate_3d():
    data = request.json or {}
    prompt = data.get("prompt", "3D куб")
    reply = _llm_chat([
        {"role": "system", "content": (
            "Ты — 3D-разработчик. Генерируй готовый HTML+Three.js код для 3D-сцены. "
            "Код должен быть полностью рабочим — один HTML файл с CDN для Three.js. "
            "Включи OrbitControls для вращения. Подключай Three.js через CDN: "
            "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js"
        )},
        {"role": "user", "content": f"Создай 3D сцену: {prompt}"},
    ])
    return jsonify({"result": reply})

# --- Видео генерация (скрипт через LLM) ---
@app.route("/api/generate-video", methods=["POST"])
def generate_video():
    data = request.json or {}
    prompt = data.get("prompt", "анимация")
    reply = _llm_chat([
        {"role": "system", "content": (
            "Ты — эксперт по видео. Создай Python-скрипт для генерации видео/анимации "
            "с помощью moviepy или PIL. Скрипт должен быть полностью рабочим."
        )},
        {"role": "user", "content": f"Создай видео/анимацию: {prompt}"},
    ])
    return jsonify({"result": reply})

# --- TG сообщения (polling для веб-интерфейса) ---
_tg_messages: List[Dict] = []
_tg_msg_lock = threading.Lock()
_tg_msg_counter = 0

@app.route("/chat/tg_messages", methods=["GET"])
def chat_tg_messages():
    """Получить TG сообщения (для отображения в веб-чате)."""
    after = request.args.get("after", "0")
    try:
        after_id = int(after)
    except (ValueError, TypeError):
        after_id = 0
    with _tg_msg_lock:
        filtered = [m for m in _tg_messages if m.get("id", 0) > after_id]
    return jsonify(filtered)

@app.route("/chat/tg_messages", methods=["POST"])
def chat_tg_messages_post():
    """Добавить TG сообщение (вызывается ботом или webhook)."""
    global _tg_msg_counter
    data = request.json or {}
    with _tg_msg_lock:
        _tg_msg_counter += 1
        msg = {
            "id": _tg_msg_counter,
            "text": data.get("text", ""),
            "from": data.get("from", "unknown"),
            "date": datetime.now().isoformat(),
        }
        _tg_messages.append(msg)
        # Держим не более 500 сообщений
        if len(_tg_messages) > 500:
            _tg_messages[:] = _tg_messages[-500:]
    return jsonify({"ok": True, "id": msg["id"]})

# ---------------------------------------------------------------------------
#  Автоматизация: задачи, циклы, CAPTCHA, авторизация
# ---------------------------------------------------------------------------

# --- Хранилище задач ---
_tasks: Dict[str, Dict[str, Any]] = {}
_tasks_lock = threading.Lock()

def _task_create(task_type: str, params: Dict[str, Any], cycles: int = 1) -> Dict[str, Any]:
    """Создать новую задачу."""
    task_id = uuid.uuid4().hex
    task = {
        "id": task_id,
        "type": task_type,
        "params": params,
        "cycles_total": max(1, cycles),
        "cycles_done": 0,
        "status": "queued",  # queued / running / paused / completed / failed / cancelled
        "created": datetime.now().isoformat(),
        "log": [],
        "error": None,
    }
    with _tasks_lock:
        _tasks[task_id] = task
    return task

def _task_cancel(task_id: str) -> Tuple[bool, str]:
    """Снять (отменить) задачу."""
    with _tasks_lock:
        task = _tasks.get(task_id)
        if not task:
            return False, "Задача не найдена"
        if task["status"] in ("completed", "cancelled"):
            return False, f"Задача уже {task['status']}"
        task["status"] = "cancelled"
        task["log"].append(f"[{datetime.now().isoformat()}] Задача снята пользователем")
    return True, "Задача снята"

def _task_list() -> List[Dict[str, Any]]:
    """Получить список всех задач."""
    with _tasks_lock:
        return list(_tasks.values())

def _task_get(task_id: str) -> Optional[Dict[str, Any]]:
    with _tasks_lock:
        return _tasks.get(task_id)

def _task_log(task_id: str, message: str) -> None:
    with _tasks_lock:
        task = _tasks.get(task_id)
        if task:
            task["log"].append(f"[{datetime.now().isoformat()}] {message}")

# --- Selenium / браузерная автоматизация ---
_selenium_available = False
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    _selenium_available = True
except ImportError:
    logger.warning("selenium не установлен — браузерная автоматизация недоступна")

# --- 2captcha ---
_twocaptcha_available = False
try:
    from twocaptcha import TwoCaptcha
    _twocaptcha_available = True
except ImportError:
    logger.warning("2captcha-python не установлен — автоматическое решение капчи недоступно")


def _create_browser(headless: bool = True) -> Any:
    """Создать Selenium WebDriver (Chrome)."""
    if not _selenium_available:
        raise RuntimeError("selenium не установлен. Выполните: pip install selenium")
    opts = ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(options=opts)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    return driver


def _solve_captcha_2captcha(site_key: str, page_url: str) -> Optional[str]:
    """Решить reCAPTCHA через 2captcha."""
    if not _twocaptcha_available:
        logger.error("2captcha-python не установлен")
        return None
    env = _env_read()
    api_key = env.get("TWOCAPTCHA_API_KEY", "")
    if not api_key:
        logger.error("TWOCAPTCHA_API_KEY не задан в .env")
        return None
    try:
        solver = TwoCaptcha(api_key)
        result = solver.recaptcha(sitekey=site_key, url=page_url)
        return result.get("code")
    except Exception as exc:
        logger.error("2captcha error: %s", exc)
        return None


def _solve_captcha_from_page(driver: Any) -> bool:
    """Попытаться найти и решить CAPTCHA на странице через 2captcha."""
    try:
        # Ищем reCAPTCHA iframe
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        site_key = None
        for iframe in iframes:
            src = iframe.get_attribute("src") or ""
            if "recaptcha" in src or "hcaptcha" in src:
                # Ищем sitekey в src
                match = re.search(r"k=([A-Za-z0-9_-]+)", src)
                if match:
                    site_key = match.group(1)
                    break

        # Также ищем div.g-recaptcha
        if not site_key:
            try:
                recaptcha_div = driver.find_element(By.CLASS_NAME, "g-recaptcha")
                site_key = recaptcha_div.get_attribute("data-sitekey")
            except Exception:
                pass

        if not site_key:
            logger.info("CAPTCHA не найдена на странице")
            return True  # Нет капчи — OK

        logger.info("Найден CAPTCHA sitekey: %s", site_key)
        token = _solve_captcha_2captcha(site_key, driver.current_url)
        if not token:
            return False

        # Вставляем решение
        driver.execute_script(
            'document.getElementById("g-recaptcha-response").value = arguments[0];', token
        )
        # Пытаемся вызвать callback
        driver.execute_script(
            """
            if (typeof ___grecaptcha_cfg !== 'undefined') {
                Object.keys(___grecaptcha_cfg.clients).forEach(function(key) {
                    var client = ___grecaptcha_cfg.clients[key];
                    if (client && client.K && client.K.callback) {
                        client.K.callback(arguments[0]);
                    }
                });
            }
            """, token
        )
        logger.info("CAPTCHA решена и вставлена")
        return True
    except Exception as exc:
        logger.error("Ошибка решения CAPTCHA: %s", exc)
        return False


def _browser_login(url: str, username: str, password: str,
                   username_selector: str = 'input[name="username"], input[name="email"], input[type="email"], #username, #email',
                   password_selector: str = 'input[name="password"], input[type="password"], #password',
                   submit_selector: str = 'button[type="submit"], input[type="submit"], .login-btn, #login-btn',
                   headless: bool = True) -> Dict[str, Any]:
    """Войти в аккаунт через браузер."""
    driver = None
    try:
        driver = _create_browser(headless=headless)
        driver.get(url)
        time.sleep(3)

        wait = WebDriverWait(driver, 15)

        # Ввод логина
        user_field = None
        for sel in username_selector.split(", "):
            try:
                user_field = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel.strip())))
                break
            except Exception:
                continue
        if not user_field:
            return {"ok": False, "error": "Поле логина не найдено"}

        user_field.clear()
        user_field.send_keys(username)
        time.sleep(0.5)

        # Ввод пароля
        pass_field = None
        for sel in password_selector.split(", "):
            try:
                pass_field = driver.find_element(By.CSS_SELECTOR, sel.strip())
                break
            except Exception:
                continue
        if not pass_field:
            return {"ok": False, "error": "Поле пароля не найдено"}

        pass_field.clear()
        pass_field.send_keys(password)
        time.sleep(0.5)

        # Решение CAPTCHA если есть
        _solve_captcha_from_page(driver)
        time.sleep(1)

        # Нажатие кнопки входа
        submit_btn = None
        for sel in submit_selector.split(", "):
            try:
                submit_btn = driver.find_element(By.CSS_SELECTOR, sel.strip())
                break
            except Exception:
                continue
        if submit_btn:
            submit_btn.click()
        else:
            # Пробуем Enter
            pass_field.send_keys("\n")

        time.sleep(5)

        # Сохраняем cookies
        cookies = driver.get_cookies()
        current_url = driver.current_url
        page_title = driver.title

        return {
            "ok": True,
            "cookies": cookies,
            "url": current_url,
            "title": page_title,
        }
    except Exception as exc:
        logger.error("Login error: %s", exc)
        return {"ok": False, "error": "Ошибка входа. Проверьте URL и учётные данные."}
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def _run_task_thread(task_id: str) -> None:
    """Выполнить задачу в отдельном потоке с поддержкой циклов."""
    task = _task_get(task_id)
    if not task:
        return

    with _tasks_lock:
        task["status"] = "running"

    task_type = task["type"]
    params = task["params"]
    total_cycles = task["cycles_total"]

    for cycle in range(1, total_cycles + 1):
        # Проверка отмены
        current = _task_get(task_id)
        if not current or current["status"] == "cancelled":
            _task_log(task_id, f"Задача отменена на цикле {cycle}/{total_cycles}")
            return

        _task_log(task_id, f"Цикл {cycle}/{total_cycles} начат")

        try:
            if task_type == "login":
                result = _browser_login(
                    url=params.get("url", ""),
                    username=params.get("username", ""),
                    password=params.get("password", ""),
                    username_selector=params.get("username_selector", 'input[name="username"], input[name="email"], input[type="email"], #username, #email'),
                    password_selector=params.get("password_selector", 'input[name="password"], input[type="password"], #password'),
                    submit_selector=params.get("submit_selector", 'button[type="submit"], input[type="submit"]'),
                )
                _task_log(task_id, f"Логин: {'успешно' if result.get('ok') else result.get('error', 'ошибка')}")

            elif task_type == "captcha_test":
                url = params.get("url", "")
                driver = None
                try:
                    driver = _create_browser(headless=True)
                    driver.get(url)
                    time.sleep(3)
                    solved = _solve_captcha_from_page(driver)
                    _task_log(task_id, f"CAPTCHA: {'решена' if solved else 'не удалось решить'}")
                finally:
                    if driver:
                        try:
                            driver.quit()
                        except Exception:
                            pass

            elif task_type == "browse":
                url = params.get("url", "")
                action_script = params.get("script", "")
                driver = None
                try:
                    driver = _create_browser(headless=True)
                    driver.get(url)
                    time.sleep(3)
                    # Решить CAPTCHA если есть
                    _solve_captcha_from_page(driver)
                    # Выполнить пользовательский JS
                    if action_script:
                        result = driver.execute_script(action_script)
                        _task_log(task_id, f"Скрипт выполнен: {str(result)[:200]}")
                    else:
                        _task_log(task_id, f"Страница загружена: {driver.title}")
                finally:
                    if driver:
                        try:
                            driver.quit()
                        except Exception:
                            pass

            else:
                _task_log(task_id, f"Неизвестный тип задачи: {task_type}")
                with _tasks_lock:
                    task["status"] = "failed"
                    task["error"] = f"Неизвестный тип: {task_type}"
                return

        except Exception as exc:
            _task_log(task_id, f"Ошибка в цикле {cycle}: {exc}")
            with _tasks_lock:
                task["error"] = str(exc)

        with _tasks_lock:
            task["cycles_done"] = cycle

        # Пауза между циклами
        if cycle < total_cycles:
            delay = params.get("cycle_delay", 5)
            _task_log(task_id, f"Пауза {delay}с перед следующим циклом")
            time.sleep(delay)

    # Завершение
    with _tasks_lock:
        if task["status"] == "running":
            task["status"] = "completed"
    _task_log(task_id, "Задача завершена")


# --- API маршруты автоматизации ---

@app.route("/api/tasks", methods=["GET"])
def api_tasks_list():
    """Получить список задач."""
    return jsonify(_task_list())

@app.route("/api/tasks", methods=["POST"])
def api_tasks_create():
    """Создать и запустить новую задачу."""
    data = request.json or {}
    task_type = data.get("type", "").strip()
    params = data.get("params", {})
    cycles = int(data.get("cycles", 1))
    if not task_type:
        return jsonify({"error": "Не указан тип задачи"}), 400
    if task_type not in ("login", "captcha_test", "browse"):
        return jsonify({"error": f"Неизвестный тип: {task_type}. Доступны: login, captcha_test, browse"}), 400

    task = _task_create(task_type, params, cycles)
    # Запустить в фоновом потоке
    thread = threading.Thread(target=_run_task_thread, args=(task["id"],), daemon=True)
    thread.start()
    return jsonify(task)

@app.route("/api/tasks/<task_id>", methods=["GET"])
def api_task_get(task_id):
    """Получить статус задачи."""
    task = _task_get(task_id)
    if not task:
        return jsonify({"error": "Задача не найдена"}), 404
    return jsonify(task)

@app.route("/api/tasks/<task_id>/cancel", methods=["POST"])
def api_task_cancel(task_id):
    """Снять (отменить) задачу."""
    ok, msg = _task_cancel(task_id)
    return jsonify({"ok": ok, "message": msg})

@app.route("/api/captcha/solve", methods=["POST"])
def api_captcha_solve():
    """Решить CAPTCHA через 2captcha API."""
    data = request.json or {}
    site_key = data.get("site_key", "").strip()
    page_url = data.get("page_url", "").strip()
    if not site_key or not page_url:
        return jsonify({"error": "Укажите site_key и page_url"}), 400
    token = _solve_captcha_2captcha(site_key, page_url)
    if token:
        return jsonify({"ok": True, "token": token})
    return jsonify({"ok": False, "error": "Не удалось решить CAPTCHA"}), 500

@app.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    """Войти в аккаунт через браузер (Selenium)."""
    data = request.json or {}
    url = data.get("url", "").strip()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    if not url or not username or not password:
        return jsonify({"error": "Укажите url, username и password"}), 400
    result = _browser_login(
        url=url,
        username=username,
        password=password,
        username_selector=data.get("username_selector", 'input[name="username"], input[name="email"], input[type="email"], #username, #email'),
        password_selector=data.get("password_selector", 'input[name="password"], input[type="password"], #password'),
        submit_selector=data.get("submit_selector", 'button[type="submit"], input[type="submit"], .login-btn, #login-btn'),
    )
    return jsonify(result)

@app.route("/api/automation/status", methods=["GET"])
def api_automation_status():
    """Статус модуля автоматизации."""
    env = _env_read()
    return jsonify({
        "selenium_available": _selenium_available,
        "twocaptcha_available": _twocaptcha_available,
        "twocaptcha_key_set": bool(env.get("TWOCAPTCHA_API_KEY")),
        "tasks_count": len(_tasks),
        "tasks_running": sum(1 for t in _tasks.values() if t["status"] == "running"),
    })

# ---------------------------------------------------------------------------
#  Автозапуск бота при старте сервера (если BOT_TOKEN задан)
# ---------------------------------------------------------------------------
def _autostart_bot():
    time.sleep(3)
    env = _env_read()
    if env.get("BOT_TOKEN"):
        ok, msg = _bot_start()
        logger.info("Autostart bot: ok=%s, msg=%s", ok, msg)
    else:
        logger.info("Autostart bot: skipped (no BOT_TOKEN)")

# ---------------------------------------------------------------------------
#  main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import socket

    _port = int(os.environ.get("DRGR_PORT", 5001))

    # Проверка порта
    def _port_free(p: int) -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("0.0.0.0", p))
            return True
        except OSError:
            return False
        finally:
            s.close()

    if not _port_free(_port):
        logger.error("Порт %d уже занят! Попробуйте: DRGR_PORT=5002 python vm/server.py", _port)
        for alt in range(_port + 1, _port + 10):
            if _port_free(alt):
                logger.info("Используется альтернативный порт: %d", alt)
                _port = alt
                break
        else:
            logger.error("Все порты %d-%d заняты. Завершение.", _port, _port + 9)
            sys.exit(1)

    threading.Thread(target=_autostart_bot, daemon=True).start()
    logger.info("DRGR VM Server запущен на http://localhost:%d", _port)
    app.run(host="0.0.0.0", port=_port, debug=False)
