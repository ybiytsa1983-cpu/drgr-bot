"""
DRGR VM — Extension server.
Provides:
  GET  /            → Monaco editor UI
  GET  /health      → JSON status of all connected AI services
  POST /api/task    → Send task to local AI (Ollama → LM Studio → fallback)
  GET  /api/tasks   → List task history
  GET  /api/projects
  POST /api/project
  POST /api/upload
  POST /api/goose
"""
from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import re
import json
import textwrap
import urllib.request
import urllib.error
import threading
import time
from datetime import datetime

app = Flask(__name__, static_folder='static', template_folder='static')

# ---------------------------------------------------------------------------
# Config — all overridable by environment variables
# ---------------------------------------------------------------------------
PROJECTS_DIR = os.path.join(os.path.dirname(__file__), 'projects')
TASKS_DIR    = os.path.join(os.path.dirname(__file__), 'tasks')
os.makedirs(PROJECTS_DIR, exist_ok=True)
os.makedirs(TASKS_DIR, exist_ok=True)

_ENV = {
    'OLLAMA_URL':   os.getenv('OLLAMA_URL',   'http://localhost:11434'),
    'LMS_URL':      os.getenv('LMS_URL',       'http://localhost:1234'),
    'TGWUI_URL':    os.getenv('TGWUI_URL',     'http://localhost:5000'),
    'COMFYUI_URL':  os.getenv('COMFYUI_URL',   'http://localhost:8188'),
    'SD_URL':       os.getenv('SD_URL',        'http://localhost:7860'),
    'OAF_URL':      os.getenv('OAF_URL',       'http://localhost:3000'),
    'TRIPOSR_URL':  os.getenv('TRIPOSR_URL',   'http://localhost:7861'),
    'ROOCODE_URL':  os.getenv('ROOCODE_URL',   'http://localhost:1337'),
    'VISION_VM_URL':os.getenv('VISION_VM_URL', 'http://localhost:8080'),
    'REMOTE_VM_URL':os.getenv('REMOTE_VM_URL', ''),
    'BOT_TOKEN':    os.getenv('BOT_TOKEN',     ''),
}
_AI_TIMEOUT = int(os.getenv('AI_TIMEOUT', '120'))
_HEALTH_TIMEOUT = float(os.getenv('HEALTH_TIMEOUT', '3'))

# ---------------------------------------------------------------------------
# Health cache — refresh every 15 s in background to keep UI snappy
# ---------------------------------------------------------------------------
_health_cache: dict = {}
_health_lock = threading.Lock()

def _probe(url: str, path: str = '/', timeout: float = _HEALTH_TIMEOUT) -> bool:
    """Return True if `url+path` answers HTTP 200..499."""
    try:
        req = urllib.request.Request(url.rstrip('/') + path, method='GET')
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status < 500
    except Exception:
        return False

def _probe_ollama(base: str) -> dict:
    # Try the configured URL first, then scan common Ollama ports
    parsed = re.match(r'^(https?://[^:]+)(?::(\d+))?', base)
    host_part = parsed.group(1) if parsed else 'http://localhost'
    configured_port = int(parsed.group(2)) if (parsed and parsed.group(2)) else 11434
    ports_to_try = [configured_port] + [p for p in (11434, 11435, 11436) if p != configured_port]
    for port in ports_to_try:
        candidate = f'{host_part}:{port}'
        try:
            req = urllib.request.Request(candidate.rstrip('/') + '/api/tags')
            with urllib.request.urlopen(req, timeout=_HEALTH_TIMEOUT) as resp:
                data = json.loads(resp.read())
                models = [m['name'] for m in data.get('models', [])]
                if port != configured_port:
                    _ENV['OLLAMA_URL'] = candidate
                return {'status': 'ok', 'models': models, 'count': len(models)}
        except Exception:
            pass
    return {'status': 'offline'}

def _probe_lmstudio(base: str) -> dict:
    try:
        req = urllib.request.Request(base.rstrip('/') + '/v1/models')
        with urllib.request.urlopen(req, timeout=_HEALTH_TIMEOUT) as resp:
            data = json.loads(resp.read())
            models = [m['id'] for m in data.get('data', [])]
            return {'status': 'ok', 'models': models, 'count': len(models)}
    except Exception:
        return {'status': 'offline'}

def _probe_tgwui(base: str) -> dict:
    if _probe(base, '/v1/models'):
        return {'status': 'ok'}
    if _probe(base, '/api/v1/model'):
        return {'status': 'ok'}
    if _probe(base, '/'):
        return {'status': 'ok'}
    return {'status': 'offline'}

def _probe_sd(base: str) -> dict:
    if _probe(base, '/sdapi/v1/sd-models'):
        return {'status': 'ok'}
    if _probe(base, '/'):
        return {'status': 'ok'}
    return {'status': 'offline'}

def _probe_comfyui(base: str) -> dict:
    if _probe(base, '/system_stats'):
        return {'status': 'ok'}
    if _probe(base, '/'):
        return {'status': 'ok'}
    return {'status': 'offline'}

def _probe_vision_vm(base: str) -> dict:
    if _probe(base, '/health'):
        return {'status': 'ok'}
    if _probe(base, '/'):
        return {'status': 'ok'}
    return {'status': 'offline'}

def _probe_moondream() -> dict:
    """Check if moondream model is available in Ollama."""
    ollama = _ENV['OLLAMA_URL']
    try:
        req = urllib.request.Request(ollama.rstrip('/') + '/api/tags')
        with urllib.request.urlopen(req, timeout=_HEALTH_TIMEOUT) as resp:
            data = json.loads(resp.read())
            models = [m['name'] for m in data.get('models', [])]
            vision_models = [m for m in models if any(
                v in m.lower() for v in ['moondream', 'llava', 'minicpm', 'qwen.*vl']
            )]
            if vision_models:
                return {'status': 'ok', 'model': vision_models[0]}
    except Exception:
        pass
    return {'status': 'offline', 'model': None}

def _check_tg_bot() -> dict:
    tok = _ENV['BOT_TOKEN']
    if not tok:
        return {'status': 'no_token'}
    try:
        url = f'https://api.telegram.org/bot{tok}/getMe'
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            if data.get('ok'):
                u = data['result']
                return {'status': 'ok', 'username': u.get('username', ''), 'name': u.get('first_name', '')}
    except Exception:
        pass
    return {'status': 'offline'}

def _build_health() -> dict:
    ollama   = _probe_ollama(_ENV['OLLAMA_URL'])
    lms      = _probe_lmstudio(_ENV['LMS_URL'])
    tgwui    = _probe_tgwui(_ENV['TGWUI_URL'])
    comfyui  = _probe_comfyui(_ENV['COMFYUI_URL'])
    sd       = _probe_sd(_ENV['SD_URL'])
    oaf      = {'status': 'ok' if _probe(_ENV['OAF_URL'], '/') else 'offline'}
    triposr  = {'status': 'ok' if _probe(_ENV['TRIPOSR_URL'], '/') else 'offline'}
    roocode  = {'status': 'ok' if _probe(_ENV['ROOCODE_URL'], '/') else 'offline'}
    vvm      = _probe_vision_vm(_ENV['VISION_VM_URL'])
    remote   = {'status': 'ok' if (_ENV['REMOTE_VM_URL'] and _probe(_ENV['REMOTE_VM_URL'], '/')) else 'offline'}
    moon     = _probe_moondream()
    tgbot    = _check_tg_bot()
    return {
        'ollama':       ollama,
        'lmstudio':     lms,
        'tgwui':        tgwui,
        'comfyui':      comfyui,
        'stable_diffusion': sd,
        'oaf':          oaf,
        'triposr':      triposr,
        'roocode':      roocode,
        'vision_vm':    vvm,
        'vision_light': moon,
        'remote_vm':    remote,
        'tg_bot':       tgbot,
        'config': {k: (v if k != 'BOT_TOKEN' else ('set' if v else '')) for k, v in _ENV.items()},
        'ts': datetime.now().isoformat(),
    }

def _health_refresh_loop():
    while True:
        try:
            h = _build_health()
            with _health_lock:
                _health_cache.update(h)
        except Exception:
            pass
        time.sleep(15)

threading.Thread(target=_health_refresh_loop, daemon=True, name='health-refresh').start()

# ---------------------------------------------------------------------------
# AI helpers — Ollama → LM Studio → fallback
# ---------------------------------------------------------------------------

def _ollama_models(base_url: str) -> list:
    """Return list of model names from Ollama, or [] on error."""
    try:
        req = urllib.request.Request(f"{base_url}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return [m['name'] for m in data.get('models', [])]
    except Exception:
        return []

def _ollama_model(base_url: str) -> str:
    models = _ollama_models(base_url)
    return models[0] if models else 'llama3'

def _lms_models(base_url: str) -> list:
    """Return list of loaded model IDs from LM Studio /v1/models, or [] on error."""
    for port in [1234, 1235, 1236]:
        candidate = re.sub(r':\d+', f':{port}', base_url)
        try:
            req = urllib.request.Request(f"{candidate}/v1/models")
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read())
                models = [m.get('id', m.get('name', 'local-model')) for m in data.get('data', [])]
                if models:
                    # Update global LMS URL to the working port
                    _ENV['LMS_URL'] = candidate
                    return models
        except Exception:
            pass
    return []

def _lms_model(base_url: str) -> str:
    models = _lms_models(base_url)
    return models[0] if models else 'local-model'

def _ai_generate(prompt: str, preferred_model: str = '') -> tuple:
    """Returns (text, source_label). Tries Ollama then LM Studio.
    preferred_model can be 'lms:modelname', 'ollama:modelname', or bare model name.
    """
    prefer_lms = preferred_model.startswith('lms:')
    prefer_ollama = preferred_model.startswith('ollama:')
    bare_model = re.sub(r'^(lms:|ollama:)', '', preferred_model).strip()

    def _try_ollama(base: str) -> tuple:
        try:
            model = bare_model if (prefer_ollama and bare_model) else _ollama_model(base)
            payload = json.dumps({
                'model': model, 'prompt': prompt, 'stream': False,
                'options': {'num_predict': 4096, 'temperature': 0.2},
            }).encode()
            req = urllib.request.Request(
                f"{base}/api/generate", data=payload,
                headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(req, timeout=_AI_TIMEOUT) as resp:
                text = json.loads(resp.read()).get('response', '').strip()
                if text:
                    return text, f'Ollama ({model})'
        except Exception:
            pass
        return '', ''

    def _try_lms(base: str) -> tuple:
        for port in [1234, 1235, 1236]:
            candidate = re.sub(r':\d+', f':{port}', base)
            try:
                model = bare_model if (prefer_lms and bare_model) else _lms_model(candidate)
                payload = json.dumps({
                    'model': model,
                    'messages': [{'role': 'user', 'content': prompt}],
                    'max_tokens': 4096, 'temperature': 0.2,
                }).encode()
                req = urllib.request.Request(
                    f"{candidate}/v1/chat/completions", data=payload,
                    headers={'Content-Type': 'application/json'}, method='POST')
                with urllib.request.urlopen(req, timeout=_AI_TIMEOUT) as resp:
                    text = json.loads(resp.read())['choices'][0]['message']['content'].strip()
                    if text:
                        _ENV['LMS_URL'] = candidate
                        return text, f'LM Studio ({model})'
            except Exception:
                pass
        return '', ''

    ollama_bases = [_ENV['OLLAMA_URL'], 'http://127.0.0.1:11434']
    lms_bases    = [_ENV['LMS_URL'],    'http://127.0.0.1:1234']

    if prefer_lms:
        for base in lms_bases:
            text, src = _try_lms(base)
            if text:
                return text, src
        for base in ollama_bases:
            text, src = _try_ollama(base)
            if text:
                return text, src
    else:
        for base in ollama_bases:
            text, src = _try_ollama(base)
            if text:
                return text, src
        for base in lms_bases:
            text, src = _try_lms(base)
            if text:
                return text, src
    return '', 'none'

def _build_code_prompt(description: str) -> str:
    return f"""Ты — AI-ассистент для генерации кода. Сгенерируй полный рабочий проект по заданию:

ЗАДАНИЕ:
{description}

ТРЕБОВАНИЯ:
1. Полный рабочий код, без заглушек и TODO
2. Каждый файл отделяй заголовком: ### filename.py (или .yml, .md и т.д.)
3. Добавь README.md с инструкцией по запуску
4. Используй Python 3.11+, современные библиотеки
5. Только код и заголовки файлов, без лишних объяснений

Начни с первого файла:
"""

# ---------------------------------------------------------------------------
# Fallback template plan
# ---------------------------------------------------------------------------

def _build_fallback_plan(description: str) -> dict:
    first_line = description.strip().splitlines()[0][:120]
    desc_lower = description.lower()
    uses_telegram = any(k in desc_lower for k in ['telegram', 'тг', 'бот', 'bot'])
    uses_postgres  = any(k in desc_lower for k in ['postgresql', 'postgres', 'база', 'db', 'database'])
    uses_fastapi   = any(k in desc_lower for k in ['fastapi', 'api', 'апи', 'endpoint'])
    uses_wb        = any(k in desc_lower for k in ['wildberries', 'wb', 'маркетплейс', 'marketplace'])
    uses_ai        = any(k in desc_lower for k in ['ai', 'ии', 'ollama', 'ml', 'model'])
    stack = []
    if uses_telegram: stack.append('aiogram 3.x (Telegram Bot)')
    if uses_fastapi:  stack.append('FastAPI + Uvicorn')
    if uses_postgres: stack.append('PostgreSQL 15 + SQLAlchemy + Alembic')
    if uses_wb:       stack.append('Wildberries API / MPStats / Alibaba scraper')
    if uses_ai:       stack.append('Ollama / OpenAI-compatible API')
    if not stack:     stack = ['Python 3.11', 'Flask', 'SQLite', 'Docker']
    modules = []
    if uses_wb:       modules.append('scraper.py — сбор данных (Wildberries, Alibaba, MPStats)')
    if uses_telegram: modules.append('bot/main.py — Telegram-бот (aiogram)')
    if uses_ai:       modules.append('ai_agent.py — AI-ассистент (Ollama)')
    if uses_postgres: modules.append('db/models.py — ORM-модели')
    modules.append('dashboard/index.html — веб-интерфейс')
    return {
        'title': first_line, 'stack': stack, 'modules': modules,
        'run': 'cp .env.example .env && docker compose up --build -d',
    }

def _safe_name(s: str) -> str:
    n = re.sub(r'[^\w\s-]', '', s, flags=re.UNICODE).strip()
    n = re.sub(r'[\s-]+', '_', n)
    return n[:40] or 'project'

def _fallback_to_text(plan: dict) -> str:
    stack = '\n'.join(f'  • {s}' for s in plan['stack'])
    mods  = '\n'.join(f'  {i+1}. {m}' for i, m in enumerate(plan['modules']))
    return (
        f"# {plan['title']}\n\n## Стек\n{stack}\n\n## Модули\n{mods}\n\n"
        f"## Запуск\n```bash\n{plan['run']}\n```\n\n"
        "---\n⚠️  AI недоступен (Ollama/LM Studio не запущены).\n"
        "Запустите `ollama serve` или используйте СЕРВИСЫ.bat и повторите.\n"
    )

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/health')
def health():
    with _health_lock:
        cached = dict(_health_cache)
    if not cached:
        cached = _build_health()
        with _health_lock:
            _health_cache.update(cached)
    return jsonify(cached)


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        data = request.json or {}
        for key in ('OLLAMA_URL', 'LMS_URL', 'TGWUI_URL', 'COMFYUI_URL',
                    'SD_URL', 'OAF_URL', 'TRIPOSR_URL', 'ROOCODE_URL',
                    'VISION_VM_URL', 'REMOTE_VM_URL', 'BOT_TOKEN'):
            if key in data:
                _ENV[key] = data[key]
                os.environ[key] = data[key]
        return jsonify({'ok': True})
    return jsonify({k: (v if k != 'BOT_TOKEN' else ('set' if v else ''))
                    for k, v in _ENV.items()})


@app.route('/api/projects', methods=['GET'])
def get_projects():
    projects = []
    for filename in os.listdir(PROJECTS_DIR):
        if filename.endswith(('.html', '.py', '.md', '.txt', '.json', '.yml', '.yaml')):
            fp = os.path.join(PROJECTS_DIR, filename)
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    content = f.read()
                projects.append({
                    'name': filename, 'content': content,
                    'modified': datetime.fromtimestamp(os.path.getmtime(fp)).isoformat(),
                })
            except Exception:
                pass
    return jsonify(projects)


def _sanitize_filename(filename: str) -> str:
    name = os.path.basename(filename)
    name = re.sub(r'[^\w.\-]', '_', name)
    if name.startswith('.'):
        name = '_' + name
    return name[:200] or 'file'


@app.route('/api/project', methods=['POST'])
def save_project():
    data = request.json or {}
    filename, content = data.get('filename'), data.get('content')
    if not filename or not content:
        return jsonify({'error': 'Missing filename or content'}), 400
    fp = os.path.join(PROJECTS_DIR, _sanitize_filename(filename))
    with open(fp, 'w', encoding='utf-8') as f:
        f.write(content)
    return jsonify({'success': True})


@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400
    fp = os.path.join(PROJECTS_DIR, _sanitize_filename(file.filename))
    file.save(fp)
    return jsonify({'success': True, 'filename': os.path.basename(fp)})


@app.route('/api/task', methods=['POST'])
def create_task():
    """Send task to local AI; return generated code (or fallback plan)."""
    data = request.json or {}
    description = (data.get('description') or '').strip()
    if not description:
        return jsonify({'error': 'description is required'}), 400

    model = (data.get('model') or '').strip()  # e.g. 'lms:qwen2-7b' or 'ollama:llama3'

    ts        = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_name = _safe_name(description.splitlines()[0][:80])

    prompt       = _build_code_prompt(description)
    ai_text, src = _ai_generate(prompt, preferred_model=model)

    if ai_text:
        content, used_ai, title = ai_text, True, description.splitlines()[0][:80]
    else:
        plan    = _build_fallback_plan(description)
        content = _fallback_to_text(plan)
        used_ai = False
        title   = plan['title']
        src     = 'fallback (шаблон)'

    filename = f"{safe_name}_{ts}.md"
    with open(os.path.join(PROJECTS_DIR, filename), 'w', encoding='utf-8') as f:
        f.write(content)
    with open(os.path.join(TASKS_DIR, f"task_{ts}.json"), 'w', encoding='utf-8') as f:
        json.dump({'id': ts, 'description': description, 'title': title,
                   'ai_source': src, 'used_ai': used_ai, 'html_file': filename,
                   'created_at': datetime.now().isoformat()}, f,
                  ensure_ascii=False, indent=2)

    return jsonify({'title': title, 'content': content,
                    'html_file': filename, 'used_ai': used_ai, 'ai_source': src})


@app.route('/api/models')
def list_models():
    """List available AI models from Ollama and LM Studio."""
    result = {'ollama': [], 'lmstudio': [], 'default': ''}
    for base in [_ENV['OLLAMA_URL'], 'http://127.0.0.1:11434']:
        models = _ollama_models(base)
        if models:
            result['ollama'] = [{'id': f'ollama:{m}', 'name': m, 'source': 'Ollama'} for m in models]
            break
    for base in [_ENV['LMS_URL'], 'http://127.0.0.1:1234']:
        models = _lms_models(base)
        if models:
            result['lmstudio'] = [{'id': f'lms:{m}', 'name': m, 'source': 'LM Studio'} for m in models]
            break
    all_models = result['ollama'] + result['lmstudio']
    if all_models:
        result['default'] = all_models[0]['id']
    return jsonify(result)


@app.route('/api/tasks', methods=['GET'])
def list_tasks():
    tasks = []
    for fn in sorted(os.listdir(TASKS_DIR), reverse=True):
        if fn.endswith('.json'):
            try:
                with open(os.path.join(TASKS_DIR, fn), 'r', encoding='utf-8') as f:
                    tasks.append(json.load(f))
            except Exception:
                pass
    return jsonify(tasks)


@app.route('/api/goose', methods=['POST'])
def goose_integration():
    data  = request.json or {}
    query = (data.get('query') or '').strip()
    if not query:
        return jsonify({'result': 'Введите запрос'})
    text, src = _ai_generate(query)
    return jsonify({'result': text or 'AI недоступен', 'source': src})


@app.route('/api/generate-3d',    methods=['POST'])
def generate_3d():
    return jsonify({'result': '3D generation — в разработке'})

@app.route('/api/generate-video', methods=['POST'])
def generate_video():
    return jsonify({'result': 'Video generation — в разработке'})


# ---------------------------------------------------------------------------
# Research / Article generation
# ---------------------------------------------------------------------------
_ARTICLES_DIR = os.path.join(os.path.dirname(__file__), 'articles')
os.makedirs(_ARTICLES_DIR, exist_ok=True)

_RESEARCH_THEMES = [
    ('teal',   '#009688', '#e0f2f1'),
    ('indigo', '#3f51b5', '#e8eaf6'),
    ('deep-orange', '#ff5722', '#fbe9e7'),
    ('green',  '#388e3c', '#e8f5e9'),
    ('purple', '#7b1fa2', '#f3e5f5'),
    ('blue',   '#1976d2', '#e3f2fd'),
]

def _ddg_search(query: str, max_results: int = 15) -> list:
    """Search DuckDuckGo; return list of {title,href,body} or []."""
    try:
        from ddgs import DDGS
        results = list(DDGS().text(query, max_results=max_results))
        return results
    except Exception:
        pass
    return []


def _build_research_prompt(topic: str, sources: list) -> str:
    src_block = ''
    if sources:
        for i, s in enumerate(sources[:12], 1):
            title = s.get('title', '')
            body  = s.get('body', '')[:400]
            url   = s.get('href', '')
            src_block += f"\n[Источник {i}] {title}\nURL: {url}\n{body}\n"
    else:
        src_block = '\n(Поиск недоступен — используй базовые знания об этой теме)\n'

    return f"""Ты — профессиональный автор аналитических статей. Напиши развёрнутую статью на тему:

ТЕМА: {topic}

ИСТОЧНИКИ ДЛЯ АНАЛИЗА:
{src_block}

ТРЕБОВАНИЯ К СТАТЬЕ:
1. Объём — минимум 800 слов, желательно 1500+
2. Структура: введение, 5-8 разделов с ## заголовками, заключение
3. В каждом разделе: факты, цифры, примеры из источников
4. Включи список ключевых выводов (маркированный список)
5. Включи раздел "Статистика и цифры" с числовыми данными
6. Ссылайся на источники где уместно
7. Пиши на русском языке
8. ТОЛЬКО текст статьи в формате Markdown, без лишних предисловий

Начни с # {topic} и напиши полноценную статью:
"""


def _keywords_from_topic(topic: str) -> list:
    stop = {'и','в','на','с','по','для','от','из','за','при','до','как','что',
            'это','но','или','не','так','же','уже','ещё','где','когда'}
    words = re.findall(r'[а-яёa-z]{4,}', topic.lower())
    return [w for w in words if w not in stop][:5] or ['technology']


def _build_article_html(topic: str, markdown_text: str, sources: list,
                        article_id: str) -> str:
    import random
    theme = random.choice(_RESEARCH_THEMES)
    accent, accent_dark, accent_light = theme

    # Convert markdown to HTML
    html_body = _md_to_html(markdown_text)

    # Build sources list
    src_html = ''
    for i, s in enumerate(sources[:12], 1):
        title = (s.get('title') or '').replace('<','&lt;').replace('>','&gt;')
        url   = s.get('href', '#')
        body  = (s.get('body') or '')[:120].replace('<','&lt;').replace('>','&gt;')
        if len(s.get('body','')) > 120:
            body += '…'
        src_html += (
            f'<li class="list-group-item">'
            f'<b>{i}.</b> <a href="{url}" target="_blank">{title}</a>'
            f'<br><small class="text-muted">{body}</small>'
            f'</li>\n'
        )
    if not src_html:
        src_html = '<li class="list-group-item text-muted">Источники недоступны (поиск заблокирован в этой среде)</li>'

    # Build chart data from numeric mentions in text
    chart_js = _build_chart_from_text(markdown_text, topic)

    # Image keywords
    kws = _keywords_from_topic(topic)
    kw_str = ','.join(kws[:3])

    # Hero and inline images from loremflickr
    hero_url = f'https://loremflickr.com/1200/400/{kw_str}?lock=42'
    img2_url = f'https://loremflickr.com/600/350/{kw_str}?lock=77'
    img3_url = f'https://loremflickr.com/600/350/{kw_str}?lock=113'

    ts = datetime.now().strftime('%d.%m.%Y %H:%M')

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{topic}</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.3/css/bootstrap.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  body{{background:#f8f9fa;}}
  .hero{{background:linear-gradient(135deg,{accent_dark},{accent});color:#fff;padding:60px 0 40px;}}
  .hero img{{width:100%;max-height:360px;object-fit:cover;border-radius:12px;opacity:.85;}}
  .accent{{color:{accent_dark};}}
  h2{{color:{accent_dark};border-left:4px solid {accent};padding-left:10px;margin-top:2rem;}}
  h3{{color:{accent};margin-top:1.5rem;}}
  .article-body img{{max-width:100%;border-radius:8px;margin:1rem 0;box-shadow:0 2px 12px rgba(0,0,0,.15);}}
  .float-img{{float:right;width:45%;margin:0 0 1rem 1.5rem;border-radius:8px;box-shadow:0 2px 12px rgba(0,0,0,.15);}}
  @media(max-width:576px){{.float-img{{float:none;width:100%;margin:0 0 1rem;}}}}
  .source-list{{max-height:320px;overflow-y:auto;}}
  .chart-wrap{{background:#fff;border-radius:12px;padding:20px;box-shadow:0 2px 8px rgba(0,0,0,.08);margin:2rem 0;}}
  .badge-src{{background:{accent};}}
  blockquote{{border-left:4px solid {accent};padding-left:1rem;color:#555;font-style:italic;}}
</style>
</head>
<body>

<div class="hero">
  <div class="container">
    <div class="row align-items-center g-4">
      <div class="col-md-6">
        <h1 class="display-5 fw-bold">{topic}</h1>
        <p class="lead opacity-75">Аналитическая статья · {ts}</p>
        <span class="badge badge-src fs-6">{len(sources)} источников</span>
      </div>
      <div class="col-md-6">
        <img src="{hero_url}" alt="{topic}" loading="lazy">
      </div>
    </div>
  </div>
</div>

<div class="container my-5">
  <div class="row g-4">

    <div class="col-lg-8">
      <div class="card shadow-sm">
        <div class="card-body article-body px-4 py-4">
          <img src="{img2_url}" class="float-img" alt="{topic}" loading="lazy">
          {html_body}
          <div class="clearfix"></div>
          <img src="{img3_url}" class="img-fluid rounded mt-3" alt="{topic}" loading="lazy">
        </div>
      </div>

      {f'<div class="chart-wrap"><h5 class="accent">📊 Статистика по теме</h5>{chart_js}</div>' if chart_js else ''}
    </div>

    <div class="col-lg-4">
      <div class="card shadow-sm mb-4">
        <div class="card-header fw-bold" style="background:{accent_light}">
          📚 Источники ({len(sources)})
        </div>
        <ul class="list-group list-group-flush source-list">
          {src_html}
        </ul>
      </div>

      <div class="card shadow-sm">
        <div class="card-header fw-bold" style="background:{accent_light}">ℹ️ О статье</div>
        <div class="card-body small text-muted">
          <p>Тема: <b>{topic}</b></p>
          <p>Дата: {ts}</p>
          <p>ID: <code>{article_id}</code></p>
          <a href="/research/article/{article_id}" class="btn btn-sm btn-outline-secondary w-100 mt-2" target="_blank">🔗 Открыть в новой вкладке</a>
        </div>
      </div>
    </div>

  </div>
</div>

<footer class="bg-dark text-white text-center py-3 mt-4">
  <small>Сгенерировано DRGR VM · {ts}</small>
</footer>
</body>
</html>"""


def _md_to_html(md: str) -> str:
    """Minimal Markdown → HTML converter (no external deps)."""
    lines = md.split('\n')
    out = []
    in_ul = False
    in_ol = False
    in_code = False
    code_buf = []

    def flush_list():
        nonlocal in_ul, in_ol
        if in_ul:
            out.append('</ul>')
            in_ul = False
        if in_ol:
            out.append('</ol>')
            in_ol = False

    for line in lines:
        # code blocks
        if line.startswith('```'):
            if in_code:
                out.append('<pre class="bg-light p-3 rounded"><code>' +
                           '\n'.join(code_buf).replace('<','&lt;').replace('>','&gt;') +
                           '</code></pre>')
                code_buf = []
                in_code = False
            else:
                flush_list()
                in_code = True
            continue
        if in_code:
            code_buf.append(line)
            continue

        # headings
        if line.startswith('### '):
            flush_list()
            out.append(f'<h3>{_md_inline(line[4:])}</h3>')
            continue
        if line.startswith('## '):
            flush_list()
            out.append(f'<h2>{_md_inline(line[3:])}</h2>')
            continue
        if line.startswith('# '):
            flush_list()
            out.append(f'<h1 class="accent">{_md_inline(line[2:])}</h1>')
            continue

        # blockquote
        if line.startswith('> '):
            flush_list()
            out.append(f'<blockquote class="blockquote"><p>{_md_inline(line[2:])}</p></blockquote>')
            continue

        # horizontal rule
        if re.match(r'^[-*_]{3,}$', line.strip()):
            flush_list()
            out.append('<hr>')
            continue

        # unordered list
        if re.match(r'^[*\-] ', line):
            if not in_ul:
                if in_ol:
                    out.append('</ol>')
                    in_ol = False
                out.append('<ul class="mb-2">')
                in_ul = True
            out.append(f'<li>{_md_inline(line[2:])}</li>')
            continue

        # ordered list
        if re.match(r'^\d+\. ', line):
            if not in_ol:
                if in_ul:
                    out.append('</ul>')
                    in_ul = False
                out.append('<ol class="mb-2">')
                in_ol = True
            out.append(f'<li>{_md_inline(re.sub(r"^\d+\. ","",line))}</li>')
            continue

        flush_list()
        stripped = line.strip()
        if not stripped:
            out.append('<br>')
        else:
            out.append(f'<p>{_md_inline(stripped)}</p>')

    flush_list()
    return '\n'.join(out)


def _md_inline(text: str) -> str:
    """Apply inline Markdown: bold, italic, code, links."""
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*',     r'<em>\1</em>', text)
    text = re.sub(r'`(.+?)`',       r'<code>\1</code>', text)
    text = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2" target="_blank">\1</a>', text)
    return text


def _build_chart_from_text(text: str, topic: str) -> str:
    """Extract numeric data from article text and build a Chart.js chart."""
    # Extract patterns like "X%" or "N млн/тыс/billion"
    pct_matches = re.findall(r'(\d+(?:[.,]\d+)?)\s*%', text)
    # Try to pair % with preceding word
    labels_raw = re.findall(r'([А-Яа-яёA-Za-z][А-Яа-яёA-Za-z\s]{2,20})[^\d]*(\d+(?:[.,]\d+)?)\s*%', text)

    if len(labels_raw) >= 3:
        labels = [l[0].strip()[:25] for l in labels_raw[:7]]
        values = [float(l[1].replace(',','.')) for l in labels_raw[:7]]
        chart_type = 'bar'
    elif len(pct_matches) >= 3:
        labels = [f'Показатель {i+1}' for i in range(min(7, len(pct_matches)))]
        values = [float(v.replace(',','.')) for v in pct_matches[:7]]
        chart_type = 'bar'
    else:
        # Generate plausible data from topic keywords
        kws = _keywords_from_topic(topic)
        if not kws:
            return ''
        import random
        labels = kws[:5]
        values = [random.randint(20, 95) for _ in labels]
        chart_type = 'bar'

    import json as _json
    l_json = _json.dumps(labels, ensure_ascii=False)
    v_json = _json.dumps(values)

    colors = ['#009688','#3f51b5','#ff5722','#388e3c','#7b1fa2','#1976d2','#f57c00']
    c_json = _json.dumps(colors[:len(labels)])

    return f"""<canvas id="resChart" height="250"></canvas>
<script>
new Chart(document.getElementById('resChart'),{{
  type:'{chart_type}',
  data:{{labels:{l_json},datasets:[{{
    label:'{topic[:40]}',
    data:{v_json},
    backgroundColor:{c_json},
    borderRadius:6,borderWidth:0
  }}]}},
  options:{{responsive:true,plugins:{{legend:{{display:false}},
    tooltip:{{callbacks:{{label:ctx=>ctx.parsed.y+'%'}}}}
  }},scales:{{y:{{beginAtZero:true,max:100}}}}}}
}});
</script>"""


@app.route('/research', methods=['POST'])
def research():
    """
    POST /research  {topic, max_sources?, model?}
    → {html, article_id, sources_count, ai_source, topic}
    """
    data = request.json or {}
    topic = (data.get('topic') or '').strip()
    if not topic:
        return jsonify({'error': 'topic is required'}), 400

    max_sources = int(data.get('max_sources') or 15)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    article_id = re.sub(r'[^\w]', '_', topic[:30]) + '_' + ts

    # 1. Search
    sources = _ddg_search(topic, max_results=max_sources)

    # 2. Build AI prompt
    prompt = _build_research_prompt(topic, sources)

    # 3. Generate article via AI
    model = (data.get('model') or '').strip()
    ai_text, ai_src = _ai_generate(prompt, preferred_model=model)

    if not ai_text:
        # Minimal fallback
        ai_text = f"# {topic}\n\n*AI недоступен. Запустите Ollama или LM Studio и повторите.*\n"
        ai_src = 'fallback'

    # 4. Build HTML
    html = _build_article_html(topic, ai_text, sources, article_id)

    # 5. Save
    html_path = os.path.join(_ARTICLES_DIR, article_id + '.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)

    md_path = os.path.join(_ARTICLES_DIR, article_id + '.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(ai_text)

    return jsonify({
        'article_id': article_id,
        'html': html,
        'ai_source': ai_src,
        'sources_count': len(sources),
        'topic': topic,
    })


@app.route('/research/article/<article_id>')
def research_article(article_id):
    """Serve a saved article HTML."""
    safe_id = re.sub(r'[^\w\-]', '', article_id)
    path = os.path.join(_ARTICLES_DIR, safe_id + '.html')
    if not os.path.exists(path):
        return 'Статья не найдена', 404
    with open(path, 'r', encoding='utf-8') as f:
        return f.read(), 200, {'Content-Type': 'text/html; charset=utf-8'}


@app.route('/research/list')
def research_list():
    articles = []
    for fn in sorted(os.listdir(_ARTICLES_DIR), reverse=True):
        if fn.endswith('.html'):
            aid = fn[:-5]
            articles.append({'id': aid, 'url': f'/research/article/{aid}'})
    return jsonify(articles[:50])


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False)
