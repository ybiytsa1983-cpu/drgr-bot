from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import json
import subprocess
import sys
import threading
from datetime import datetime

app = Flask(__name__, static_folder='static', template_folder='static')

# Directories
PROJECTS_DIR = os.path.join(os.path.dirname(__file__), 'projects')
os.makedirs(PROJECTS_DIR, exist_ok=True)

ENV_FILE = os.path.join(os.path.dirname(__file__), '..', '.env')

# Bot process state
_bot_proc = None
_bot_lock = threading.Lock()


# ── CORS ────────────────────────────────────────────────────────────────────

def _add_cors(response):
    origin = request.headers.get('Origin', '')
    if origin.startswith('chrome-extension://') or origin.startswith('http://localhost'):
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


@app.after_request
def after_request(response):
    return _add_cors(response)


@app.route('/', defaults={'path': ''}, methods=['OPTIONS'])
@app.route('/<path:path>', methods=['OPTIONS'])
def cors_preflight(path):
    resp = app.make_default_options_response()
    return _add_cors(resp)


# ── BOT MANAGEMENT ───────────────────────────────────────────────────────────

def _bot_start():
    global _bot_proc
    with _bot_lock:
        if _bot_proc and _bot_proc.poll() is None:
            return {'status': 'already_running', 'pid': _bot_proc.pid}
        bot_path = os.path.join(os.path.dirname(__file__), '..', 'bot.py')
        try:
            bot_log = os.path.join(os.path.dirname(bot_path), 'bot_output.log')
            _bot_proc = subprocess.Popen(
                [sys.executable, bot_path],
                stdout=open(bot_log, 'a', encoding='utf-8'),
                stderr=subprocess.STDOUT,
                cwd=os.path.dirname(bot_path),
            )
            return {'status': 'started', 'pid': _bot_proc.pid}
        except Exception as e:
            return {'status': 'error', 'error': str(e)}


def _bot_stop():
    global _bot_proc
    with _bot_lock:
        if _bot_proc is None or _bot_proc.poll() is not None:
            return {'status': 'not_running'}
        _bot_proc.terminate()
        try:
            _bot_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _bot_proc.kill()
        return {'status': 'stopped'}


def _bot_get_status():
    global _bot_proc
    with _bot_lock:
        if _bot_proc is None:
            return {'status': 'not_started'}
        if _bot_proc.poll() is None:
            return {'status': 'running', 'pid': _bot_proc.pid}
        return {'status': 'stopped', 'returncode': _bot_proc.returncode}


@app.route('/bot/start', methods=['POST'])
def bot_start():
    return jsonify(_bot_start())


@app.route('/bot/stop', methods=['POST'])
def bot_stop():
    return jsonify(_bot_stop())


@app.route('/bot/status', methods=['GET'])
def bot_status():
    return jsonify(_bot_get_status())


# ── SETTINGS ─────────────────────────────────────────────────────────────────

def _env_read():
    env = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, _, v = line.partition('=')
                    env[k.strip()] = v.strip()
    return env


def _env_save(data: dict):
    env = _env_read()
    for k, v in data.items():
        # Sanitize: reject keys/values containing newlines or bare '='  in key
        k = str(k).replace('\n', '').replace('\r', '').replace('=', '')
        v = str(v).replace('\n', '').replace('\r', '')
        if k:
            env[k] = v
    lines = [f'{k}={v}\n' for k, v in env.items()]
    with open(ENV_FILE, 'w', encoding='utf-8') as f:
        f.writelines(lines)


@app.route('/settings', methods=['GET'])
def settings_get():
    env = _env_read()
    safe = {k: v for k, v in env.items() if 'TOKEN' not in k.upper() and 'KEY' not in k.upper() and 'SECRET' not in k.upper()}
    return jsonify(safe)


@app.route('/settings', methods=['POST'])
def settings_post():
    data = request.json or {}
    _env_save(data)
    return jsonify({'ok': True})


# ── HEALTH & EXTENSION REPORT ─────────────────────────────────────────────────

def _health():
    bot_st = _bot_get_status()
    return {
        'vm': 'ok',
        'bot': bot_st.get('status', 'unknown'),
        'bot_pid': bot_st.get('pid'),
        'projects_count': len([f for f in os.listdir(PROJECTS_DIR)]),
    }


@app.route('/health', methods=['GET'])
def health():
    return jsonify(_health())


@app.route('/extension/report', methods=['GET'])
def extension_report():
    data = _health()
    lines = [
        'DRGR VM Status Report',
        '=' * 30,
        f"VM server:      {data['vm']}",
        f"Telegram bot:   {data['bot']}" + (f" (pid {data['bot_pid']})" if data.get('bot_pid') else ''),
        f"Saved projects: {data['projects_count']}",
        '=' * 30,
    ]
    return jsonify({'report': '\n'.join(lines), 'data': data})


# ── MAIN UI ──────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


# ── PROJECTS ─────────────────────────────────────────────────────────────────

@app.route('/api/projects', methods=['GET'])
def get_projects():
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
    data = request.json or {}
    return jsonify({'result': f"Goose received: {data.get('query', '')}"})


@app.route('/api/generate-3d', methods=['POST'])
def generate_3d():
    data = request.json or {}
    return jsonify({'result': f"3D prompt queued: {data.get('prompt', '')}"})


@app.route('/api/generate-video', methods=['POST'])
def generate_video():
    data = request.json or {}
    return jsonify({'result': f"Video prompt queued: {data.get('prompt', '')}"})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)

