from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import json
import subprocess
import signal
import sys
from datetime import datetime

app = Flask(__name__, static_folder='static', template_folder='static')

# Directories
_BASE = os.path.dirname(__file__)
PROJECTS_DIR = os.path.join(_BASE, 'projects')
os.makedirs(PROJECTS_DIR, exist_ok=True)

SETTINGS_FILE = os.path.join(_BASE, 'settings.json')

# ── Default settings ──────────────────────────────────────────────────────────
_DEFAULTS = {
    "bot_token": "",
    "bot_mode": "polling",          # "polling" | "webhook"
    "webhook_url": "",
    "ai_backend": "huggingface",    # "ollama" | "lmstudio" | "qwen" | "huggingface"
    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3",
    "lmstudio_url": "http://localhost:1234",
    "lmstudio_model": "",
    "qwen_api_key": "",
    "qwen_model": "qwen-plus",
    "huggingface_api_key": "",
    "huggingface_model": "HuggingFaceH4/zephyr-7b-beta",
}

def _load_settings() -> dict:
    """Load settings.json, fill missing keys from .env, then from defaults."""
    s = dict(_DEFAULTS)
    # Layer 1: .env file (only for secret keys so we don't break existing installs)
    env_file = os.path.join(os.path.dirname(_BASE), '.env')
    if os.path.exists(env_file):
        with open(env_file, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, _, v = line.partition('=')
                    k = k.strip().lower()
                    if k == 'bot_token':
                        s['bot_token'] = v.strip().strip('"\'')
                    elif k == 'huggingface_api_key':
                        s['huggingface_api_key'] = v.strip().strip('"\'')
    # Layer 2: settings.json overrides everything
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, encoding='utf-8') as f:
                saved = json.load(f)
            s.update({k: v for k, v in saved.items() if k in _DEFAULTS})
        except Exception:
            pass
    return s

def _save_settings(data: dict) -> None:
    """Persist only recognised keys to settings.json."""
    current = _load_settings()
    current.update({k: v for k, v in data.items() if k in _DEFAULTS})
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(current, f, ensure_ascii=False, indent=2)

# ── Bot process management ─────────────────────────────────────────────────────
_bot_proc: subprocess.Popen | None = None

def _bot_pid_file() -> str:
    return os.path.join(_BASE, 'bot.pid')

def _bot_is_running() -> bool:
    pid_file = _bot_pid_file()
    if not os.path.exists(pid_file):
        return False
    try:
        pid = int(open(pid_file).read().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, OSError):
        return False

def _bot_stop() -> None:
    pid_file = _bot_pid_file()
    if os.path.exists(pid_file):
        try:
            pid = int(open(pid_file).read().strip())
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
        try:
            os.remove(pid_file)
        except Exception:
            pass

def _bot_start() -> bool:
    """Start bot.py as a detached subprocess. Returns True on success."""
    _bot_stop()
    bot_py = os.path.join(os.path.dirname(_BASE), 'bot.py')
    if not os.path.exists(bot_py):
        return False
    try:
        proc = subprocess.Popen(
            [sys.executable, bot_py],
            cwd=os.path.dirname(_BASE),
            stdout=open(os.path.join(_BASE, 'bot.log'), 'a'),
            stderr=subprocess.STDOUT,
        )
        with open(_bot_pid_file(), 'w') as f:
            f.write(str(proc.pid))
        return True
    except Exception:
        return False

@app.route('/')
def index():
    return render_template('index.html')

# ── Settings ───────────────────────────────────────────────────────────────────
@app.route('/api/settings', methods=['GET'])
def settings_get():
    s = _load_settings()
    # Mask secret tokens for display (show last 4 chars)
    def _mask(v):
        return ('*' * (len(v) - 4) + v[-4:]) if v and len(v) > 4 else v
    safe = dict(s)
    for key in ('bot_token', 'qwen_api_key', 'huggingface_api_key'):
        if safe.get(key):
            safe[key + '_masked'] = _mask(safe[key])
    return jsonify(safe)

@app.route('/api/settings', methods=['POST'])
def settings_post():
    data = request.json or {}
    # Strip masked placeholders — don't overwrite with '***xxxx'
    cleaned = {}
    for k, v in data.items():
        if k in _DEFAULTS and isinstance(v, str) and '*' not in v:
            cleaned[k] = v
        elif k in _DEFAULTS and not isinstance(v, str):
            cleaned[k] = v
    _save_settings(cleaned)
    return jsonify({'ok': True})

# ── VM list ─────────────────────────────────────────────────────────────────────
@app.route('/api/vm/list', methods=['GET'])
def vm_list():
    s = _load_settings()
    vms = [
        {
            'id': 'ollama',
            'name': 'Ollama (локальный)',
            'description': f"URL: {s['ollama_url']}  Модель: {s['ollama_model'] or 'auto'}",
            'active': s['ai_backend'] == 'ollama',
        },
        {
            'id': 'lmstudio',
            'name': 'LM Studio (локальный)',
            'description': f"URL: {s['lmstudio_url']}  Модель: {s['lmstudio_model'] or 'auto'}",
            'active': s['ai_backend'] == 'lmstudio',
        },
        {
            'id': 'qwen',
            'name': 'Qwen Cloud (Alibaba)',
            'description': f"Модель: {s['qwen_model']}",
            'active': s['ai_backend'] == 'qwen',
        },
        {
            'id': 'huggingface',
            'name': 'HuggingFace Inference',
            'description': f"Модель: {s['huggingface_model']}",
            'active': s['ai_backend'] == 'huggingface',
        },
    ]
    return jsonify({'vms': vms})

# ── Bot status & control ──────────────────────────────────────────────────────
@app.route('/api/bot/status', methods=['GET'])
def bot_status():
    s = _load_settings()
    running = _bot_is_running()
    return jsonify({
        'running': running,
        'mode': s.get('bot_mode', 'polling'),
        'backend': s.get('ai_backend', 'huggingface'),
        'has_token': bool(s.get('bot_token')),
    })

@app.route('/api/bot/start', methods=['POST'])
def bot_start():
    if _bot_is_running():
        return jsonify({'ok': True, 'message': 'Бот уже запущен'})
    ok = _bot_start()
    return jsonify({'ok': ok, 'message': 'Запущен' if ok else 'Ошибка запуска — проверьте bot.py'})

@app.route('/api/bot/stop', methods=['POST'])
def bot_stop():
    _bot_stop()
    return jsonify({'ok': True, 'message': 'Бот остановлен'})

@app.route('/api/bot/restart', methods=['POST'])
def bot_restart():
    _bot_stop()
    ok = _bot_start()
    return jsonify({'ok': ok, 'message': 'Перезапущен' if ok else 'Ошибка запуска'})

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

@app.route('/api/project', methods=['POST'])
def save_project():
    """Save a project"""
    data = request.json
    filename = data.get('filename')
    content = data.get('content')
    
    if not filename or not content:
        return jsonify({'error': 'Missing filename or content'}), 400
    
    filepath = os.path.join(PROJECTS_DIR, filename)
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
    
    filepath = os.path.join(PROJECTS_DIR, file.filename)
    file.save(filepath)
    
    return jsonify({'success': True, 'filename': file.filename})

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
    app.run(host='0.0.0.0', port=5001, debug=True)
