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
    try:
        req = urllib.request.Request(base.rstrip('/') + '/api/tags')
        with urllib.request.urlopen(req, timeout=_HEALTH_TIMEOUT) as resp:
            data = json.loads(resp.read())
            models = [m['name'] for m in data.get('models', [])]
            return {'status': 'ok', 'models': models, 'count': len(models)}
    except Exception:
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

def _ollama_model(base_url: str) -> str:
    try:
        req = urllib.request.Request(f"{base_url}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            models = data.get('models', [])
            if models:
                return models[0]['name']
    except Exception:
        pass
    return 'llama3'

def _ai_generate(prompt: str) -> tuple:
    """Returns (text, source_label). Tries Ollama then LM Studio."""
    # Ollama
    for base in [_ENV['OLLAMA_URL'], 'http://127.0.0.1:11434']:
        try:
            model = _ollama_model(base)
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
    # LM Studio
    for base in [_ENV['LMS_URL'], 'http://127.0.0.1:1234']:
        try:
            payload = json.dumps({
                'model': 'local-model',
                'messages': [{'role': 'user', 'content': prompt}],
                'max_tokens': 4096, 'temperature': 0.2,
            }).encode()
            req = urllib.request.Request(
                f"{base}/v1/chat/completions", data=payload,
                headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(req, timeout=_AI_TIMEOUT) as resp:
                text = json.loads(resp.read())['choices'][0]['message']['content'].strip()
                if text:
                    return text, 'LM Studio'
        except Exception:
            pass
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

    ts        = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_name = _safe_name(description.splitlines()[0][:80])

    prompt       = _build_code_prompt(description)
    ai_text, src = _ai_generate(prompt)

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


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False)
