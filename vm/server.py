from flask import Flask, render_template, request, jsonify, send_from_directory, Response, stream_with_context
import os
import re
import json
import textwrap
import urllib.request
import urllib.error
from datetime import datetime

app = Flask(__name__, static_folder='static', template_folder='static')

# Runtime directories (created at startup, excluded from git)
PROJECTS_DIR = os.path.join(os.path.dirname(__file__), 'projects')
TASKS_DIR = os.path.join(os.path.dirname(__file__), 'tasks')
os.makedirs(PROJECTS_DIR, exist_ok=True)
os.makedirs(TASKS_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# AI helpers — try Ollama, then LM Studio, then return ""
# ---------------------------------------------------------------------------

_OLLAMA_URLS = [
    os.getenv('OLLAMA_URL', 'http://localhost:11434'),
    'http://127.0.0.1:11434',
]
_LMS_URLS = [
    os.getenv('LMS_URL', 'http://localhost:1234'),
    'http://127.0.0.1:1234',
]
_AI_TIMEOUT = int(os.getenv('AI_TIMEOUT', 120))


def _ollama_model(base_url: str) -> str:
    """Return the first available Ollama model name, or 'llama3'."""
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


def _ai_generate(prompt: str) -> tuple[str, str]:
    """
    Send *prompt* to the local AI and return (response_text, source_label).
    Tries: Ollama → LM Studio → returns ("", "none")
    """
    # --- Ollama ---
    for base in _OLLAMA_URLS:
        try:
            model = _ollama_model(base)
            payload = json.dumps({
                'model': model,
                'prompt': prompt,
                'stream': False,
                'options': {'num_predict': 4096, 'temperature': 0.2},
            }).encode()
            req = urllib.request.Request(
                f"{base}/api/generate",
                data=payload,
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=_AI_TIMEOUT) as resp:
                data = json.loads(resp.read())
                text = data.get('response', '').strip()
                if text:
                    return text, f'Ollama ({model})'
        except Exception:
            pass

    # --- LM Studio ---
    for base in _LMS_URLS:
        try:
            payload = json.dumps({
                'model': 'local-model',
                'messages': [{'role': 'user', 'content': prompt}],
                'max_tokens': 4096,
                'temperature': 0.2,
            }).encode()
            req = urllib.request.Request(
                f"{base}/v1/chat/completions",
                data=payload,
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=_AI_TIMEOUT) as resp:
                data = json.loads(resp.read())
                text = data['choices'][0]['message']['content'].strip()
                if text:
                    return text, 'LM Studio'
        except Exception:
            pass

    return '', 'none'


def _build_code_prompt(description: str) -> str:
    """Build a prompt that asks the AI to generate full project code."""
    return f"""Ты — AI-ассистент для генерации кода. Сгенерируй полный рабочий проект по следующему заданию:

ЗАДАНИЕ:
{description}

ТРЕБОВАНИЯ:
1. Создай все необходимые файлы с полным рабочим кодом (не заглушки, не TODO)
2. Каждый файл должен быть разделён заголовком в формате:
   ### filename.py
   (или ### docker-compose.yml, ### requirements.txt и т.д.)
3. Добавь README.md с инструкцией по запуску
4. Используй Python 3.11+, современные библиотеки
5. Отвечай ТОЛЬКО кодом и заголовками файлов, без лишних пояснений

Начни сразу с первого файла:
"""


# ---------------------------------------------------------------------------
# Fallback: template-based plan (used when AI is unavailable)
# ---------------------------------------------------------------------------

def _build_fallback_plan(description: str) -> dict:
    """Keyword-based project plan when AI is offline."""
    first_line = description.strip().splitlines()[0][:120]
    title = first_line
    desc_lower = description.lower()

    uses_telegram = any(k in desc_lower for k in ['telegram', 'тг', 'бот', 'bot'])
    uses_postgres = any(k in desc_lower for k in ['postgresql', 'postgres', 'база', 'db', 'database'])
    uses_docker = any(k in desc_lower for k in ['docker', 'compose', 'контейн'])
    uses_fastapi = any(k in desc_lower for k in ['fastapi', 'api', 'апи', 'endpoint'])
    uses_wb = any(k in desc_lower for k in ['wildberries', 'wb', 'маркетплейс', 'marketplace'])
    uses_ai = any(k in desc_lower for k in ['ai', 'ии', 'ollama', 'ml', 'model', 'openclaw'])

    stack = []
    if uses_telegram:
        stack.append('aiogram 3.x (Telegram Bot)')
    if uses_fastapi:
        stack.append('FastAPI + Uvicorn')
    if uses_postgres:
        stack.append('PostgreSQL 15 + SQLAlchemy + Alembic')
    if uses_docker:
        stack.append('Docker Compose')
    if uses_wb:
        stack.append('Wildberries API / MPStats / Alibaba scraper')
    if uses_ai:
        stack.append('Ollama / OpenAI-compatible API')
    if not stack:
        stack = ['Python 3.11', 'Flask', 'SQLite', 'Docker']

    structure = textwrap.dedent(f"""\
        {_safe_name(title)}/
        ├── docker-compose.yml
        ├── .env.example
        ├── README.md
        {'├── bot/' if uses_telegram else ''}
        {'│   └── main.py           # Telegram-бот (aiogram)' if uses_telegram else ''}
        {'├── api/' if uses_fastapi else '├── app/'}
        │   └── main.py           # {'FastAPI' if uses_fastapi else 'Flask'} сервер
        {'├── workers/' if uses_wb else ''}
        {'│   ├── scraper.py        # Wildberries / Alibaba / MPStats' if uses_wb else ''}
        {'│   └── analytics.py      # Юнит-экономика, скоринг товаров' if uses_wb else ''}
        {'├── db/' if uses_postgres else ''}
        {'│   ├── models.py' if uses_postgres else ''}
        {'│   └── migrations/       # Alembic' if uses_postgres else ''}
        └── dashboard/
            └── index.html        # Web-интерфейс / дашборд
    """).strip()
    structure = '\n'.join(line for line in structure.splitlines() if line.strip())

    modules = []
    if uses_wb:
        modules.append('scraper.py — асинхронный сбор данных (Wildberries, Alibaba, MPStats)')
        modules.append('analytics.py — скоринг товаров: маржа, конкуренция, динамика спроса')
    if uses_telegram:
        modules.append('bot/main.py — приём текстовых и голосовых команд через Telegram')
    if uses_ai:
        modules.append('ai_agent.py — AI-ассистент (Ollama) для рекомендаций')
    if uses_postgres:
        modules.append('db/models.py — ORM-модели: Product, Category, Supplier, Analysis')
    modules.append('dashboard/index.html — дашборд: графики, фильтры, карточки товаров')

    run_instructions = textwrap.dedent("""\
        # 1. Настроить окружение
        cp .env.example .env

        # 2. Запустить через Docker Compose
        docker compose up --build -d

        # 3. Применить миграции БД
        docker compose exec api alembic upgrade head

        # 4. Открыть дашборд
        # http://localhost:8080
    """).strip()

    return {
        'title': title,
        'stack': stack,
        'structure': structure,
        'modules': modules,
        'run_instructions': run_instructions,
    }


def _safe_name(title: str) -> str:
    name = re.sub(r'[^\w\s-]', '', title, flags=re.UNICODE).strip()
    name = re.sub(r'[\s-]+', '_', name)
    return name[:40] or 'project'


def _fallback_to_text(plan: dict) -> str:
    """Convert a fallback plan dict to plain text for Monaco display."""
    stack_lines = '\n'.join(f'  • {s}' for s in plan['stack'])
    module_lines = '\n'.join(f'  {i+1}. {m}' for i, m in enumerate(plan['modules']))
    return (
        f"# {plan['title']}\n\n"
        f"## Стек\n{stack_lines}\n\n"
        f"## Структура\n```\n{plan['structure']}\n```\n\n"
        f"## Модули\n{module_lines}\n\n"
        f"## Запуск\n```bash\n{plan['run_instructions']}\n```\n\n"
        f"---\n⚠️  AI-агент недоступен (Ollama/LM Studio не запущены).\n"
        f"Запустите `ollama serve` и повторите задание для получения реального кода.\n"
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/projects', methods=['GET'])
def get_projects():
    """Get all saved projects."""
    projects = []
    for filename in os.listdir(PROJECTS_DIR):
        if filename.endswith(('.html', '.py', '.md', '.txt', '.json', '.yaml', '.yml')):
            filepath = os.path.join(PROJECTS_DIR, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                projects.append({
                    'name': filename,
                    'content': content,
                    'modified': datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat(),
                })
            except Exception:
                pass
    return jsonify(projects)


def _sanitize_filename(filename: str) -> str:
    """Return a safe filename: basename only, alphanumeric + dot/dash/underscore."""
    name = os.path.basename(filename)
    name = re.sub(r'[^\w.\-]', '_', name)
    if name.startswith('.'):
        name = '_' + name
    return name[:200] or 'file'


@app.route('/api/project', methods=['POST'])
def save_project():
    """Save a project."""
    data = request.json or {}
    filename = data.get('filename')
    content = data.get('content')
    if not filename or not content:
        return jsonify({'error': 'Missing filename or content'}), 400
    safe_filename = _sanitize_filename(filename)
    filepath = os.path.join(PROJECTS_DIR, safe_filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    return jsonify({'success': True})


@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Handle file upload."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    safe_filename = _sanitize_filename(file.filename)
    filepath = os.path.join(PROJECTS_DIR, safe_filename)
    file.save(filepath)
    return jsonify({'success': True, 'filename': safe_filename})


@app.route('/api/task', methods=['POST'])
def create_task():
    """
    Accept a task description, send it to the local AI (Ollama / LM Studio)
    for real code generation, save the result, and return it for Monaco display.

    Falls back to a keyword-based template plan when no AI is available.
    """
    data = request.json or {}
    description = (data.get('description') or '').strip()
    if not description:
        return jsonify({'error': 'description is required'}), 400

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_name = _safe_name(description.splitlines()[0][:80])

    # --- Try AI first ---
    prompt = _build_code_prompt(description)
    ai_text, ai_source = _ai_generate(prompt)

    if ai_text:
        content = ai_text
        filename = f"{safe_name}_{ts}.md"
        used_ai = True
        title = description.splitlines()[0][:80]
    else:
        # Fallback: template plan
        plan = _build_fallback_plan(description)
        content = _fallback_to_text(plan)
        filename = f"{safe_name}_{ts}.md"
        used_ai = False
        title = plan['title']
        ai_source = 'fallback (шаблон)'

    # Save content as a project file for Monaco
    filepath = os.path.join(PROJECTS_DIR, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

    # Save task record
    task_record = {
        'id': ts,
        'description': description,
        'title': title,
        'ai_source': ai_source,
        'used_ai': used_ai,
        'html_file': filename,
        'created_at': datetime.now().isoformat(),
    }
    task_path = os.path.join(TASKS_DIR, f"task_{ts}.json")
    with open(task_path, 'w', encoding='utf-8') as f:
        json.dump(task_record, f, ensure_ascii=False, indent=2)

    return jsonify({
        'title': title,
        'content': content,
        'html_file': filename,
        'used_ai': used_ai,
        'ai_source': ai_source,
    })


@app.route('/api/tasks', methods=['GET'])
def list_tasks():
    """List all submitted tasks."""
    tasks = []
    for filename in sorted(os.listdir(TASKS_DIR), reverse=True):
        if filename.endswith('.json'):
            try:
                with open(os.path.join(TASKS_DIR, filename), 'r', encoding='utf-8') as f:
                    tasks.append(json.load(f))
            except Exception:
                pass
    return jsonify(tasks)


@app.route('/api/goose', methods=['POST'])
def goose_integration():
    """Goose AI integration — proxies to local AI."""
    data = request.json or {}
    query = (data.get('query') or '').strip()
    if not query:
        return jsonify({'result': 'Введите запрос для Goose AI'})
    text, source = _ai_generate(query)
    return jsonify({'result': text or 'AI недоступен', 'source': source})


@app.route('/api/generate-3d', methods=['POST'])
def generate_3d():
    """3D generation placeholder."""
    return jsonify({'result': '3D generation — в разработке'})


@app.route('/api/generate-video', methods=['POST'])
def generate_video():
    """Video generation placeholder."""
    return jsonify({'result': 'Video generation — в разработке'})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False)
