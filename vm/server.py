from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import re
import json
import textwrap
from datetime import datetime

app = Flask(__name__, static_folder='static', template_folder='static')

# Create directories
PROJECTS_DIR = os.path.join(os.path.dirname(__file__), 'projects')
TASKS_DIR = os.path.join(os.path.dirname(__file__), 'tasks')
os.makedirs(PROJECTS_DIR, exist_ok=True)
os.makedirs(TASKS_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Helper: project plan generator
# ---------------------------------------------------------------------------

def _build_project_plan(description: str) -> dict:
    """
    Build a structured project plan from a free-text description.
    Returns a dict with keys: title, stack, structure, modules, run_instructions.
    """
    first_line = description.strip().splitlines()[0][:120]
    title = first_line

    # Detect common keywords to tailor the plan
    desc_lower = description.lower()
    uses_telegram = any(k in desc_lower for k in ["telegram", "тг", "бот", "bot"])
    uses_postgres = any(k in desc_lower for k in ["postgresql", "postgres", "база", "db", "database"])
    uses_docker = any(k in desc_lower for k in ["docker", "compose", "контейн"])
    uses_fastapi = any(k in desc_lower for k in ["fastapi", "api", "апи", "endpoint"])
    uses_wb = any(k in desc_lower for k in ["wildberries", "wb", "маркетплейс", "marketplace"])
    uses_ai = any(k in desc_lower for k in ["ai", "ии", "openclaw", "ollama", "ml", "model"])

    stack = []
    if uses_telegram:
        stack.append("aiogram 3.x (Telegram Bot)")
    if uses_fastapi:
        stack.append("FastAPI + Uvicorn")
    if uses_postgres:
        stack.append("PostgreSQL 15 + SQLAlchemy + Alembic")
    if uses_docker:
        stack.append("Docker Compose")
    if uses_wb:
        stack.append("Wildberries API / MPStats / Alibaba scraper")
    if uses_ai:
        stack.append("OpenClaw / Ollama / HuggingFace Inference API")
    if not stack:
        stack = ["Python 3.11", "Flask", "SQLite", "Docker"]

    structure = textwrap.dedent(f"""\
        {_safe_name(title)}/
        ├── docker-compose.yml
        ├── .env.example
        ├── README.md
        {"├── bot/" if uses_telegram else ""}
        {"│   ├── Dockerfile" if uses_telegram else ""}
        {"│   ├── requirements.txt" if uses_telegram else ""}
        {"│   └── main.py           # Telegram-бот (aiogram)" if uses_telegram else ""}
        {"├── api/" if uses_fastapi else "├── app/"}
        {"│   ├── Dockerfile" }
        {"│   ├── requirements.txt" }
        {"│   └── main.py           # FastAPI / Flask сервер" }
        {"├── workers/" if uses_wb else ""}
        {"│   ├── scraper.py        # Wildberries / Alibaba / MPStats" if uses_wb else ""}
        {"│   ├── analytics.py      # Юнит-экономика, скоринг товаров" if uses_wb else ""}
        {"│   └── scheduler.py      # APScheduler: фоновые задачи" if uses_wb else ""}
        {"├── db/" if uses_postgres else ""}
        {"│   ├── models.py" if uses_postgres else ""}
        {"│   └── migrations/       # Alembic" if uses_postgres else ""}
        └── dashboard/
            └── index.html        # Web-интерфейс / дашборд
    """).strip()
    # Remove blank lines that result from unused sections
    structure = "\n".join(line for line in structure.splitlines() if line.strip())

    modules = []
    if uses_wb:
        modules.append("scraper.py — асинхронный сбор данных (Wildberries, Alibaba, MPStats)")
        modules.append("analytics.py — скоринг товаров: маржа, конкуренция, динамика спроса")
    if uses_telegram:
        modules.append("bot/main.py — приём текстовых и голосовых команд через Telegram")
    if uses_ai:
        modules.append("ai_agent.py — AI-ассистент (OpenClaw / Ollama) для рекомендаций")
    if uses_postgres:
        modules.append("db/models.py — ORM-модели: Product, Category, Supplier, Analysis")
    modules.append("dashboard/index.html — дашборд: графики, фильтры, карточки товаров")

    run_instructions = textwrap.dedent("""\
        # 1. Клонировать и настроить окружение
        cp .env.example .env
        # Заполните .env: BOT_TOKEN, DATABASE_URL, WB_API_KEY и т.д.

        # 2. Запустить через Docker Compose
        docker compose up --build -d

        # 3. Применить миграции БД
        docker compose exec api alembic upgrade head

        # 4. Открыть дашборд
        # http://localhost:8080
    """).strip()

    return {
        "title": title,
        "stack": stack,
        "structure": structure,
        "modules": modules,
        "run_instructions": run_instructions,
    }


def _safe_name(title: str) -> str:
    """Convert a title to a safe directory name."""
    name = re.sub(r"[^\w\s-]", "", title, flags=re.UNICODE).strip()
    name = re.sub(r"[\s-]+", "_", name)
    return name[:40] or "project"


def _plan_to_html(plan: dict, description: str) -> str:
    """Render the plan as an HTML file for the Monaco editor."""
    stack_items = "\n".join(f"        <li>{s}</li>" for s in plan["stack"])
    module_items = "\n".join(f"        <li><code>{m}</code></li>" for m in plan["modules"])
    structure_escaped = plan["structure"].replace("<", "&lt;").replace(">", "&gt;")
    run_escaped = plan["run_instructions"].replace("<", "&lt;").replace(">", "&gt;")
    desc_escaped = description[:500].replace("<", "&lt;").replace(">", "&gt;")

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Проект: {plan['title']}</title>
<style>
  body {{ font-family: 'Segoe UI', sans-serif; background: #1e1e1e; color: #d4d4d4; padding: 2rem; }}
  h1 {{ color: #4ec9b0; }} h2 {{ color: #ce9178; margin-top: 1.5rem; }}
  pre {{ background: #252526; padding: 1rem; border-radius: 6px; overflow-x: auto; }}
  ul {{ padding-left: 1.5rem; line-height: 1.8; }}
  code {{ color: #9cdcfe; }}
  .desc {{ color: #888; font-style: italic; margin-bottom: 1rem; }}
</style>
</head>
<body>
<h1>📋 {plan['title']}</h1>
<p class="desc">{desc_escaped}</p>

<h2>🛠 Технологический стек</h2>
<ul>
{stack_items}
</ul>

<h2>📁 Структура проекта</h2>
<pre>{structure_escaped}</pre>

<h2>⚙️ Ключевые модули</h2>
<ul>
{module_items}
</ul>

<h2>🚀 Запуск</h2>
<pre>{run_escaped}</pre>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/projects', methods=['GET'])
def get_projects():
    """Get all saved projects"""
    projects = []
    for filename in os.listdir(PROJECTS_DIR):
        if filename.endswith('.html') or filename.endswith('.py'):
            filepath = os.path.join(PROJECTS_DIR, filename)
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            projects.append({
                'name': filename,
                'content': content,
                'modified': datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat()
            })
    return jsonify(projects)


def _sanitize_filename(filename: str) -> str:
    """Return a safe filename: basename only, alphanumeric + dot/dash/underscore."""
    name = os.path.basename(filename)
    name = re.sub(r"[^\w.\-]", "_", name)
    # Reject names starting with a dot (hidden files)
    if name.startswith("."):
        name = "_" + name
    return name[:200] or "file"


@app.route('/api/project', methods=['POST'])
def save_project():
    """Save a project"""
    data = request.json
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
    """Handle file upload"""
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
    Accept a project task description and return a structured project plan.
    Also saves an HTML blueprint to the projects directory.
    """
    data = request.json or {}
    description = (data.get('description') or '').strip()
    if not description:
        return jsonify({'error': 'description is required'}), 400

    plan = _build_project_plan(description)

    # Save HTML blueprint
    safe_name = _safe_name(plan['title'])
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    html_filename = f"{safe_name}_{ts}.html"
    html_content = _plan_to_html(plan, description)
    html_path = os.path.join(PROJECTS_DIR, html_filename)
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    # Save task record
    task_record = {
        'id': ts,
        'description': description,
        'plan': plan,
        'html_file': html_filename,
        'created_at': datetime.now().isoformat(),
    }
    task_path = os.path.join(TASKS_DIR, f"task_{ts}.json")
    with open(task_path, 'w', encoding='utf-8') as f:
        json.dump(task_record, f, ensure_ascii=False, indent=2)

    # Build human-readable result for Telegram
    stack_lines = "\n".join(f"  • {s}" for s in plan['stack'])
    module_lines = "\n".join(f"  {i+1}. {m}" for i, m in enumerate(plan['modules']))
    result_text = (
        f"📋 <b>Проект: {plan['title']}</b>\n\n"
        f"<b>Стек:</b>\n{stack_lines}\n\n"
        f"<b>Структура:</b>\n<pre>{plan['structure']}</pre>\n\n"
        f"<b>Модули:</b>\n{module_lines}\n\n"
        f"<b>Запуск:</b>\n<pre>{plan['run_instructions']}</pre>\n\n"
        f"💾 Blueprint сохранён: <code>{html_filename}</code>\n"
        f"Откройте <code>http://localhost:5001</code> для просмотра в редакторе."
    )

    return jsonify({
        'result': result_text,
        'plan': plan,
        'html_file': html_filename,
    })


@app.route('/api/tasks', methods=['GET'])
def list_tasks():
    """List all submitted tasks."""
    tasks = []
    for filename in sorted(os.listdir(TASKS_DIR), reverse=True):
        if filename.endswith('.json'):
            with open(os.path.join(TASKS_DIR, filename), 'r', encoding='utf-8') as f:
                tasks.append(json.load(f))
    return jsonify(tasks)


@app.route('/api/goose', methods=['POST'])
def goose_integration():
    """Goose AI integration endpoint"""
    data = request.json
    # TODO: Implement Goose AI integration
    return jsonify({'result': 'Goose integration placeholder'})


@app.route('/api/generate-3d', methods=['POST'])
def generate_3d():
    """3D generation endpoint"""
    data = request.json
    # TODO: Implement 3D generation
    return jsonify({'result': '3D generation placeholder'})


@app.route('/api/generate-video', methods=['POST'])
def generate_video():
    """Video generation endpoint"""
    data = request.json
    # TODO: Implement video generation
    return jsonify({'result': 'Video generation placeholder'})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False) 
