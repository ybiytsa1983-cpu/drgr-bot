from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import json
import re
import subprocess
import sys
import threading
import html as _html_mod
from datetime import datetime
from urllib.parse import urlparse, quote_plus

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




# ── ARTICLE / RESEARCH GENERATOR ────────────────────────────────────────────

_SCRAPE_TIMEOUT = 8
_SCRAPE_MAX_URLS = 5
_SEARCH_MAX_RESULTS = 12
_SCRAPE_THREAD_JOIN_TIMEOUT = 12  # seconds to wait for all scraping threads
_OLLAMA_PROBE_PORTS = (11434, 11435, 11436, 11437)  # ports to try when discovering Ollama
_SCRAPE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'ru,en;q=0.9',
}


def _research_ddg_search(query: str, max_results: int = _SEARCH_MAX_RESULTS) -> list:
    """Synchronous DuckDuckGo search via ddgs library."""
    try:
        from ddgs import DDGS
        results = list(DDGS().text(query, max_results=max_results))
        return results
    except Exception:
        return []


def _research_scrape_url(url: str) -> dict:
    """Scrape a URL and return title, paragraphs and tables."""
    try:
        import requests as _req
        r = _req.get(url, timeout=_SCRAPE_TIMEOUT, headers=_SCRAPE_HEADERS)
        r.raise_for_status()
        text = r.text

        # Extract title
        title_m = re.search(r'<title[^>]*>([^<]+)</title>', text, re.IGNORECASE)
        title = _html_mod.unescape(title_m.group(1).strip()) if title_m else url

        # Remove noisy tags
        text = re.sub(
            r'<(script|style|nav|footer|header|aside|noscript)[^>]*>.*?</\1>',
            '', text, flags=re.DOTALL | re.IGNORECASE
        )

        # Extract paragraphs
        paras = re.findall(r'<p[^>]*>(.*?)</p>', text, re.DOTALL | re.IGNORECASE)
        clean_paras = []
        for p in paras:
            clean = re.sub(r'<[^>]+>', ' ', p).strip()
            clean = re.sub(r'\s+', ' ', clean)
            clean = _html_mod.unescape(clean)
            if len(clean) > 80:
                clean_paras.append(clean)

        # Extract tables (rows of cells)
        tables = []
        for tbl_raw in re.findall(r'<table[^>]*>(.*?)</table>', text, re.DOTALL | re.IGNORECASE):
            rows = []
            for row_raw in re.findall(r'<tr[^>]*>(.*?)</tr>', tbl_raw, re.DOTALL | re.IGNORECASE):
                cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row_raw, re.DOTALL | re.IGNORECASE)
                clean_cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
                clean_cells = [_html_mod.unescape(c) for c in clean_cells if c]
                if clean_cells:
                    rows.append(clean_cells)
            if len(rows) >= 2:
                tables.append(rows)

        return {
            'url': url,
            'title': title[:200],
            'paragraphs': clean_paras[:20],
            'tables': tables[:2],
        }
    except Exception:
        return {'url': url, 'title': '', 'paragraphs': [], 'tables': []}


def _research_call_llm(prompt: str) -> str:
    """Try Ollama or LM Studio for article text generation."""
    import requests as _req

    # Ollama — try multiple ports
    for port in _OLLAMA_PROBE_PORTS:
        base = f'http://localhost:{port}'
        try:
            r = _req.get(f'{base}/api/tags', timeout=1)
            if r.status_code != 200:
                continue
            models = [m['name'] for m in r.json().get('models', [])]
            if not models:
                continue
            # Prefer non-vision text models
            model = next(
                (m for m in models if not any(x in m for x in ('vl', 'vision', 'llava', 'moondream'))),
                models[0]
            )
            r2 = _req.post(f'{base}/api/generate', json={
                'model': model,
                'prompt': prompt,
                'stream': False,
                'options': {'temperature': 0.3, 'num_predict': 2500}
            }, timeout=120)
            r2.raise_for_status()
            response_text = r2.json().get('response', '').strip()
            if response_text:
                return response_text
        except Exception:
            continue

    # LM Studio
    try:
        r = _req.post(f'{_LMS_URL}/chat/completions', json={
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': 2500,
            'temperature': 0.3
        }, timeout=120)
        r.raise_for_status()
        choices = r.json().get('choices') or []
        if choices:
            return choices[0]['message']['content'].strip()
    except Exception:
        pass

    return ''


def _research_llm_to_sections_html(llm_text: str) -> str:
    """Convert LLM markdown-style text (## headings) to HTML sections."""
    if not llm_text:
        return ''
    sections_html = ''
    sec_counter = [0]
    blocks = re.split(r'\n(?=##\s)', '\n' + llm_text.strip())
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if block.startswith('## '):
            lines = block.split('\n', 1)
            heading = lines[0][3:].strip()
            body = lines[1].strip() if len(lines) > 1 else ''
        else:
            heading = ''
            body = block

        paras = [p.strip() for p in re.split(r'\n{2,}', body) if p.strip()]
        paras_html = ''.join(f'<p>{_html_mod.escape(p)}</p>\n' for p in paras)

        sec_id = f'sec{sec_counter[0]}'
        sec_counter[0] += 1
        if heading:
            sections_html += (
                f'<h2 class="art-h2" id="{sec_id}">'
                f'{_html_mod.escape(heading)}</h2>\n{paras_html}\n'
            )
        else:
            sections_html += paras_html

    return sections_html


def _research_build_article(query: str, search_results: list, scraped: list) -> str:
    """Build a rich Bootstrap HTML article page."""
    safe_q = _html_mod.escape(query)

    # ---------- aggregate scraped content ----------
    all_paras: list = []
    all_tables: list = []
    for item in scraped:
        all_paras.extend(item.get('paragraphs', [])[:12])
        all_tables.extend(item.get('tables', [])[:2])

    # ---------- build context for LLM ----------
    ctx_parts = []
    for i, r in enumerate(search_results[:10], 1):
        ctx_parts.append(
            f'[{i}] {r.get("title", "")} ({r.get("href", "")}):\n'
            f'{r.get("body", "")[:400]}'
        )
    if scraped:
        for item in scraped[:3]:
            txt = ' '.join(item.get('paragraphs', [])[:5])[:600]
            if txt:
                ctx_parts.append(f'[Страница {item["url"]}]:\n{txt}')
    ctx = '\n\n'.join(ctx_parts)

    # ---------- LLM article ----------
    llm_text = ''
    if ctx:
        prompt = (
            f'Напиши подробную энциклопедическую статью на русском языке на тему: "{query}"\n\n'
            f'Используй следующие данные из интернета:\n{ctx}\n\n'
            f'Требования:\n'
            f'- 5-7 разделов с заголовками в формате ## Название\n'
            f'- Каждый раздел: 3-4 абзаца с реальными фактами из источников выше\n'
            f'- Первый раздел — введение, последний — выводы\n'
            f'- Только текст (без HTML), без вступительных слов типа "Вот статья..."\n\n'
            f'Начни сразу с ## Введение'
        )
        llm_text = _research_call_llm(prompt)

    # ---------- convert to HTML sections ----------
    sections_html = _research_llm_to_sections_html(llm_text)

    # fallback: scraped paragraphs grouped into sections
    if not sections_html and all_paras:
        chunk = max(1, len(all_paras) // 3)
        for i, title in enumerate(['Обзор', 'Подробности', 'Дополнительно']):
            paras = all_paras[i * chunk:(i + 1) * chunk]
            if not paras:
                continue
            paras_html = ''.join(f'<p>{_html_mod.escape(p)}</p>\n' for p in paras)
            sections_html += f'<h2 class="art-h2" id="sec{i}">{title}</h2>\n{paras_html}\n'

    # last fallback: search snippets
    if not sections_html:
        sections_html = '<h2 class="art-h2" id="sec0">Результаты поиска</h2>\n'
        for r in search_results[:6]:
            sections_html += (
                f'<p><strong>{_html_mod.escape(r.get("title", ""))}</strong><br>'
                f'{_html_mod.escape(r.get("body", ""))}</p>\n'
            )

    # ---------- tables HTML ----------
    tables_html = ''
    for tbl in all_tables[:2]:
        if len(tbl) < 2:
            continue
        header = tbl[0]
        body_rows = tbl[1:]
        thead = ''.join(f'<th>{_html_mod.escape(str(c)[:60])}</th>' for c in header)
        tbody = ''
        for row in body_rows[:20]:
            tbody += '<tr>' + ''.join(f'<td>{_html_mod.escape(str(c)[:100])}</td>' for c in row) + '</tr>\n'
        tables_html += (
            '<div class="table-responsive mb-4">'
            '<table class="table table-bordered table-striped table-sm">'
            f'<thead class="table-dark"><tr>{thead}</tr></thead>'
            f'<tbody>{tbody}</tbody>'
            '</table></div>\n'
        )

    # ---------- sources table ----------
    sources_rows = ''
    for i, r in enumerate(search_results, 1):
        url = r.get('href', '#')
        title = _html_mod.escape(r.get('title', url)[:90])
        domain = _html_mod.escape(urlparse(url).netloc.replace('www.', ''))
        snippet = _html_mod.escape(r.get('body', '')[:120])
        sources_rows += (
            f'<tr><td>{i}</td>'
            f'<td><a href="{url}" target="_blank" rel="noopener">{title}</a>'
            f'<br><small class="text-muted">{snippet}</small></td>'
            f'<td><small>{domain}</small></td></tr>\n'
        )

    # ---------- TOC ----------
    toc_items = ''
    h2_matches = re.findall(r'<h2 class="art-h2" id="(sec\d+)">([^<]+)</h2>', sections_html)
    for sec_id, sec_title in h2_matches:
        toc_items += f'<li><a href="#{sec_id}">{sec_title}</a></li>\n'

    # ---------- chart data (source body length as richness proxy) ----------
    chart_labels_js = json.dumps([r.get('title', '')[:35] for r in search_results[:8]])
    chart_data_js = json.dumps([min(100, len(r.get('body', '')) // 3) for r in search_results[:8]])

    # ---------- images ----------
    query_words = query.split()
    img_kw = quote_plus(' '.join(query_words[:2]))
    img_kw_alt = quote_plus(query_words[0] if query_words else query)

    css = """
    body{font-family:'Segoe UI',Arial,sans-serif;background:#f8f9fa;color:#212529}
    .art-header{background:linear-gradient(135deg,#0d6efd,#6610f2);color:#fff;padding:2.5rem 1.5rem}
    .art-header h1{font-size:2rem;font-weight:700}
    .toc{background:#fff;border:1px solid #dee2e6;border-radius:.5rem;padding:1rem 1.5rem}
    .toc a{text-decoration:none;color:#0d6efd}
    .toc a:hover{text-decoration:underline}
    .art-h2{color:#0d6efd;border-bottom:2px solid #dee2e6;padding-bottom:.3rem;margin-top:2rem;margin-bottom:.8rem}
    .hero-img{width:100%;max-height:340px;object-fit:cover;border-radius:.5rem;margin-bottom:1.5rem}
    .chart-box{position:relative;height:280px;background:#fff;border-radius:.5rem;padding:1rem;border:1px solid #dee2e6;margin-bottom:1.5rem}
    p{line-height:1.7;margin-bottom:.9rem}
    """

    js = (
        'new Chart(document.getElementById("resChart"),{'
        'type:"bar",'
        'data:{'
        f'labels:{chart_labels_js},'
        'datasets:[{'
        'label:"Объём данных",'
        f'data:{chart_data_js},'
        'backgroundColor:"rgba(13,110,253,0.6)",'
        'borderColor:"rgba(13,110,253,1)",'
        'borderWidth:1'
        '}]'
        '},'
        'options:{'
        'responsive:true,maintainAspectRatio:false,'
        'plugins:{legend:{display:false}},'
        'scales:{y:{beginAtZero:true}}'
        '}'
        '});'
    )

    return (
        '<!DOCTYPE html>\n'
        '<html lang="ru">\n'
        '<head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{safe_q} — Статья DRGR</title>\n'
        '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">\n'
        '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>\n'
        f'<style>{css}</style>\n'
        '</head>\n<body>\n'
        '<div class="art-header mb-4">'
        '<div class="container">'
        f'<h1>📰 {safe_q}</h1>'
        f'<p class="mb-0 opacity-75">Автоматически сгенерированная статья &middot; '
        f'{len(search_results)} источников &middot; {len(scraped)} страниц проанализировано</p>'
        '</div></div>\n'
        '<div class="container pb-5">\n'
        '<div class="row g-4">\n'
        # Main column
        '<div class="col-lg-8">\n'
        f'<img src="https://picsum.photos/seed/{img_kw}/800/340" '
        f'onerror="this.src=\'https://loremflickr.com/800/340/{img_kw_alt}?lock=7\'" '
        f'class="hero-img" alt="{safe_q}">\n'
        f'{sections_html}\n'
        f'{tables_html}\n'
        '<div class="chart-box"><canvas id="resChart"></canvas></div>\n'
        '<h2 class="art-h2">📚 Источники</h2>\n'
        '<div class="table-responsive">'
        '<table class="table table-bordered table-hover table-sm">'
        '<thead class="table-secondary"><tr><th>#</th><th>Источник</th><th>Домен</th></tr></thead>'
        f'<tbody>{sources_rows}</tbody>'
        '</table></div>\n'
        '</div>\n'
        # Sidebar column
        '<div class="col-lg-4">\n'
        '<div class="toc mb-4 sticky-top" style="top:1rem">'
        '<h6 class="fw-bold mb-2">📋 Содержание</h6>'
        f'<ol class="mb-0 ps-3">{toc_items}</ol>'
        '</div>\n'
        f'<img src="https://picsum.photos/seed/{img_kw_alt}/400/280" '
        f'onerror="this.src=\'https://loremflickr.com/400/280/{img_kw_alt}?lock=8\'" '
        f'class="img-fluid rounded mb-3" alt="{safe_q}">\n'
        '</div>\n'
        '</div>\n'
        '</div>\n'
        f'<script>{js}</script>\n'
        '</body></html>'
    )


@app.route('/research', methods=['POST'])
def research():
    data = request.json or {}
    query = (data.get('query') or '').strip()
    if not query:
        return jsonify({'error': 'query required'}), 400

    try:
        # 1. DuckDuckGo search
        search_results = _research_ddg_search(query)

        # 2. Parallel scraping of top URLs
        urls = [r.get('href', '') for r in search_results[:_SCRAPE_MAX_URLS] if r.get('href')]
        scraped: list = []
        lock = threading.Lock()

        def _scrape_one(url):
            item = _research_scrape_url(url)
            if item.get('paragraphs'):
                with lock:
                    scraped.append(item)

        threads = [threading.Thread(target=_scrape_one, args=(u,), daemon=True) for u in urls]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=_SCRAPE_THREAD_JOIN_TIMEOUT)

        # 3. Build article HTML
        html_content = _research_build_article(query, search_results, scraped)

        return jsonify({
            'html': html_content,
            'sources_count': len(search_results),
            'scraped_count': len(scraped),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── VM CHAT & DUAL CO-RUN ────────────────────────────────────────────────────

_LMS_PORT = 1234          # LM Studio default OpenAI-compat port
_LMS_URL  = f'http://127.0.0.1:{_LMS_PORT}/v1'

_VM_CHAT_TIMEOUT   = 180  # seconds per single LLM call
_DUORUN_MAX_ROUNDS = 3    # maximum back-and-forth rounds


def _ollama_list_models() -> list:
    """Return list of {name, port} dicts for every Ollama model found."""
    import requests as _req
    found = []
    for port in _OLLAMA_PROBE_PORTS:
        try:
            r = _req.get(f'http://localhost:{port}/api/tags', timeout=2)
            if r.status_code == 200:
                for m in r.json().get('models', []):
                    found.append({'name': m['name'], 'port': port})
        except Exception:
            continue
    return found


def _lms_list_models() -> list:
    """Return list of model ids from LM Studio."""
    import requests as _req
    try:
        r = _req.get(f'{_LMS_URL}/models', timeout=2)
        if r.status_code == 200:
            return [m['id'] for m in r.json().get('data', [])]
    except Exception:
        pass
    return []


def _call_ollama(port: int, model: str, prompt: str, system: str = '') -> str:
    """Call Ollama /api/generate and return the text response."""
    import requests as _req
    messages_prompt = f"{system}\n\n{prompt}" if system else prompt
    try:
        r = _req.post(
            f'http://localhost:{port}/api/generate',
            json={
                'model': model,
                'prompt': messages_prompt,
                'stream': False,
                'options': {'temperature': 0.7, 'num_predict': 3000},
            },
            timeout=_VM_CHAT_TIMEOUT,
        )
        r.raise_for_status()
        return r.json().get('response', '').strip()
    except Exception as e:
        return f'[Ollama error] {e}'


def _call_lmstudio(model: str, prompt: str, system: str = '') -> str:
    """Call LM Studio /v1/chat/completions and return the text response."""
    import requests as _req
    messages = []
    if system:
        messages.append({'role': 'system', 'content': system})
    messages.append({'role': 'user', 'content': prompt})
    try:
        payload = {
            'messages': messages,
            'max_tokens': 3000,
            'temperature': 0.7,
        }
        if model:
            payload['model'] = model
        r = _req.post(
            f'{_LMS_URL}/chat/completions',
            json=payload,
            timeout=_VM_CHAT_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        choices = data.get('choices') or []
        if not choices:
            return '[LM Studio error] empty choices in response'
        return choices[0]['message']['content'].strip()
    except Exception as e:
        return f'[LM Studio error] {e}'


def _dispatch_vm(backend: str, model: str, port: int, prompt: str, system: str = '') -> str:
    """Route a prompt to the correct backend and return the text response."""
    if backend == 'lmstudio':
        return _call_lmstudio(model, prompt, system)
    # default: ollama
    if not port:
        # auto-discover
        for p in _OLLAMA_PROBE_PORTS:
            import requests as _req
            try:
                _req.get(f'http://localhost:{p}/api/tags', timeout=1).raise_for_status()
                port = p
                break
            except Exception:
                continue
    return _call_ollama(port or _OLLAMA_PROBE_PORTS[0], model, prompt, system)


@app.route('/vm/models', methods=['GET'])
def vm_models():
    """Return available models for Ollama and LM Studio."""
    return jsonify({
        'ollama':   _ollama_list_models(),
        'lmstudio': _lms_list_models(),
    })


@app.route('/vm/openclaw/status', methods=['GET'])
def vm_openclaw_status():
    """Lightweight OpenClaw availability check (gateway + browser server)."""
    import requests as _req
    gateway_ok = False
    browser_ok = False
    try:
        r = _req.get('http://127.0.0.1:18789', timeout=1)
        gateway_ok = 200 <= r.status_code < 300
    except Exception:
        gateway_ok = False
    try:
        r = _req.get('http://127.0.0.1:18791', timeout=1)
        browser_ok = 200 <= r.status_code < 300
    except Exception:
        browser_ok = False
    return jsonify({
        'ok': gateway_ok or browser_ok,
        'gateway_ok': gateway_ok,
        'browser_ok': browser_ok,
        'gateway_url': 'ws://127.0.0.1:18789',
        'browser_url': 'http://127.0.0.1:18791/',
    })


@app.route('/vm/chat', methods=['POST'])
def vm_chat():
    """Single-VM chat endpoint.

    Body: {backend, model, port, prompt, system?}
    """
    data    = request.json or {}
    backend = data.get('backend', 'ollama')
    model   = data.get('model', '')
    port    = int(data.get('port', 0) or 0)
    prompt  = (data.get('prompt') or '').strip()
    system  = (data.get('system') or '').strip()

    if not prompt:
        return jsonify({'error': 'prompt required'}), 400

    response = _dispatch_vm(backend, model, port, prompt, system)
    return jsonify({'response': response, 'backend': backend, 'model': model})


@app.route('/vm/duorun', methods=['POST'])
def vm_duorun():
    """Dual VM Co-Run: two AI agents collaborate on a task.

    Body:
      task          — the task / question
      agent_a       — {backend, model, port}   first agent (e.g. Ollama)
      agent_b       — {backend, model, port}   second agent (e.g. LM Studio)
      mode          — "plan" | "debate" | "review"  (default "plan")
      rounds        — number of exchange rounds (1-3, default 2)

    Returns:
      {steps: [{agent, role, text}, ...], final: str}
    """
    data  = request.json or {}
    task  = (data.get('task') or '').strip()
    a_cfg = data.get('agent_a') or {}
    b_cfg = data.get('agent_b') or {}
    mode  = data.get('mode', 'plan')
    rounds = min(_DUORUN_MAX_ROUNDS, max(1, int(data.get('rounds', 2) or 2)))

    if not task:
        return jsonify({'error': 'task required'}), 400

    steps = []

    def _say(agent_label: str, role: str, text: str):
        steps.append({'agent': agent_label, 'role': role, 'text': text})

    # ── helper to call an agent config ──────────────────────────────────────
    def _call(cfg: dict, prompt: str, system: str = '') -> str:
        return _dispatch_vm(
            backend=cfg.get('backend', 'ollama'),
            model=cfg.get('model', ''),
            port=int(cfg.get('port', 0) or 0),
            prompt=prompt,
            system=system,
        )

    label_a = f"Агент А ({a_cfg.get('backend','ollama')})"
    label_b = f"Агент Б ({b_cfg.get('backend','lmstudio')})"

    if mode == 'debate':
        # Agent A proposes, Agent B challenges, Agent A concludes
        sys_a = (
            'Ты опытный эксперт-аналитик. Твоя роль — формулировать чёткие обоснованные утверждения '
            'и защищать их логическими аргументами.'
        )
        sys_b = (
            'Ты критический аналитик. Твоя роль — выявлять слабые места в аргументах '
            'и предлагать улучшения или альтернативные точки зрения.'
        )
        # round 1: A proposes
        prop = _call(a_cfg, f'Сформулируй свою позицию по теме: {task}', sys_a)
        _say(label_a, 'предложение', prop)

        for i in range(rounds):
            # B challenges
            challenge = _call(
                b_cfg,
                f'Вот позиция оппонента:\n\n{prop}\n\nВыяви слабые места и предложи контраргументы.',
                sys_b,
            )
            _say(label_b, f'возражение (раунд {i+1})', challenge)

            # A responds
            prop = _call(
                a_cfg,
                f'Твоя позиция:\n{prop}\n\nКонтраргументы оппонента:\n{challenge}\n\n'
                f'Улучши свою позицию с учётом возражений.',
                sys_a,
            )
            _say(label_a, f'ответ (раунд {i+1})', prop)

        final = prop

    elif mode == 'review':
        # Agent A produces draft, Agent B reviews, Agent A finalises
        sys_a = 'Ты квалифицированный специалист. Пиши развёрнуто и структурированно.'
        sys_b = (
            'Ты строгий рецензент. Найди ошибки, неточности и пропуски в тексте, '
            'предложи конкретные улучшения.'
        )
        draft = _call(a_cfg, task, sys_a)
        _say(label_a, 'черновик', draft)

        review = _call(
            b_cfg,
            f'Проверь следующий текст и дай детальные рекомендации по улучшению:\n\n{draft}',
            sys_b,
        )
        _say(label_b, 'рецензия', review)

        final = _call(
            a_cfg,
            f'Твой черновик:\n{draft}\n\nРецензия:\n{review}\n\n'
            f'Перепиши текст, учтя все замечания.',
            sys_a,
        )
        _say(label_a, 'финальный текст', final)

    else:
        # mode == "plan" (default): A plans, B enriches, A synthesises
        sys_a = (
            'Ты стратегический планировщик. Разбивай задачи на чёткие шаги, '
            'распределяй роли и определяй ожидаемые результаты.'
        )
        sys_b = (
            'Ты эксперт по реализации. Детализируй шаги плана, добавляй технические детали, '
            'выявляй риски и предлагай способы их устранения.'
        )
        plan = _call(
            a_cfg,
            f'Составь пошаговый план выполнения задачи:\n\n{task}\n\n'
            f'Распредели роли между двумя агентами (Агент А и Агент Б).',
            sys_a,
        )
        _say(label_a, 'план', plan)

        enriched = _call(
            b_cfg,
            f'Задача: {task}\n\nПлан от Агента А:\n{plan}\n\n'
            f'Детализируй каждый шаг плана, добавь технические подробности и предупреди о рисках.',
            sys_b,
        )
        _say(label_b, 'детализация', enriched)

        for i in range(rounds - 1):
            extra = _call(
                a_cfg,
                f'Исходный план:\n{plan}\n\nДетализация от Агента Б:\n{enriched}\n\n'
                f'Уточни план с учётом деталей. Раунд {i+2}.',
                sys_a,
            )
            _say(label_a, f'уточнение (раунд {i+2})', extra)
            plan = extra

        final = _call(
            a_cfg,
            f'Задача: {task}\n\nИтоговый план (после обсуждения):\n{plan}\n\n'
            f'Напиши краткое итоговое резюме с конкретными шагами и результатами.',
            sys_a,
        )
        _say(label_a, 'итог', final)

    return jsonify({'steps': steps, 'final': final})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
