"""
DRGR VM — Flask-based local server.

Provides:
  - Web UI (Monaco Editor, file upload, VM dropdown)
  - /api/search  — multi-source web search (DuckDuckGo + Wikipedia)
  - /api/upload  — file upload (paperclip icon)
  - /api/vm/list — VM preset list for dropdown
  - /api/goose   — Goose LLM integration stub
  - /api/3d      — 3-D object generator stub
  - /api/video   — video generator stub
"""

import os
import re
import json
import time
import asyncio
import logging
import mimetypes
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import (
    Flask,
    abort,
    jsonify,
    render_template,
    request,
    send_from_directory,
)
from werkzeug.utils import secure_filename

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {
    "txt", "md", "py", "js", "ts", "html", "css", "json", "yaml", "yml",
    "png", "jpg", "jpeg", "gif", "webp", "svg",
    "mp4", "webm", "ogg", "mov",
    "pdf", "zip", "tar", "gz",
}

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("drgr-vm")

app = Flask(__name__, static_folder=str(STATIC_DIR), template_folder=str(STATIC_DIR))
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _allowed_file(filename: str) -> bool:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in ALLOWED_EXTENSIONS


def _ddg_search(query: str, max_results: int = 8) -> List[Dict[str, Any]]:
    """Search DuckDuckGo via duckduckgo_search library (sync)."""
    try:
        from duckduckgo_search import DDGS
        raw = list(DDGS().text(query, max_results=max_results * 3))
        # Score and filter
        tokens = set(re.findall(r"\w+", query.lower()))
        for r in raw:
            txt_tokens = set(re.findall(r"\w+", (r.get("title", "") + " " + r.get("body", "")).lower()))
            r["_score"] = len(tokens & txt_tokens) / max(len(tokens), 1)
        raw.sort(key=lambda x: x["_score"], reverse=True)
        return raw[:max_results]
    except Exception as e:
        logger.warning(f"DDG search error: {e}")
        return []


_WIKI_ALLOWED_LANGS = frozenset([
    "ru", "en", "de", "fr", "es", "it", "pt", "ja", "zh", "pl",
    "nl", "sv", "uk", "vi", "ar", "ko", "fi", "no", "da", "cs",
])


def _wiki_search(query: str, lang: str = "en", limit: int = 5) -> List[Dict[str, Any]]:
    """Search Wikipedia API (sync)."""
    # Validate lang against an allowlist to prevent SSRF via host injection
    if lang not in _WIKI_ALLOWED_LANGS:
        lang = "en"
    # Build URL with fixed host; only query params come from user input
    wiki_api_base = f"https://{lang}.wikipedia.org/w/api.php"
    params = urllib.parse.urlencode({
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": str(limit),
        "format": "json",
        "utf8": "1",
    })
    api_url = f"{wiki_api_base}?{params}"
    try:
        data = json.loads(urllib.request.urlopen(api_url, timeout=8).read().decode())
        hits = data.get("query", {}).get("search", [])
        results = []
        for h in hits:
            title = h.get("title", "")
            snippet = re.sub(r"<[^>]+>", "", h.get("snippet", ""))
            wiki_url = f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
            results.append({"title": title, "href": wiki_url, "body": snippet, "source": "wikipedia"})
        return results
    except Exception as e:
        logger.warning(f"Wikipedia search error: {e}")
        return []


# ---------------------------------------------------------------------------
# VM presets
# ---------------------------------------------------------------------------

VM_PRESETS: List[Dict[str, str]] = [
    {"id": "default",   "name": "DRGR VM (default)",      "description": "Стандартная среда"},
    {"id": "python",    "name": "Python 3 Sandbox",        "description": "Python 3.11, pip"},
    {"id": "node",      "name": "Node.js Sandbox",         "description": "Node.js 20, npm"},
    {"id": "rust",      "name": "Rust Sandbox",            "description": "Rust + Cargo"},
    {"id": "web",       "name": "Web Preview",             "description": "HTML/CSS/JS live preview"},
    {"id": "ml",        "name": "ML Workspace",            "description": "PyTorch + Transformers"},
]


# ---------------------------------------------------------------------------
# Routes — UI
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(str(STATIC_DIR), "index.html")


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(str(STATIC_DIR), filename)


# ---------------------------------------------------------------------------
# Routes — API
# ---------------------------------------------------------------------------

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "timestamp": time.time()})


@app.route("/api/vm/list")
def vm_list():
    """Return list of VM presets for dropdown."""
    return jsonify({"vms": VM_PRESETS})


@app.route("/api/search", methods=["GET", "POST"])
def api_search():
    """Multi-source search: DuckDuckGo + Wikipedia."""
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        query = body.get("query", "").strip()
        sources = body.get("sources", ["ddg", "wikipedia"])
        lang = body.get("lang", "ru")
    else:
        query = request.args.get("q", "").strip()
        sources_str = request.args.get("sources", "ddg,wikipedia")
        sources = [s.strip() for s in sources_str.split(",")]
        lang = request.args.get("lang", "ru")

    if not query:
        return jsonify({"error": "query is required"}), 400

    results: List[Dict[str, Any]] = []

    if "ddg" in sources or "duckduckgo" in sources:
        ddg = _ddg_search(query)
        for r in ddg:
            results.append({
                "title": r.get("title", ""),
                "url": r.get("href", "#"),
                "snippet": r.get("body", "")[:200],
                "score": round(r.get("_score", 0.0), 3),
                "source": "duckduckgo",
            })

    if "wikipedia" in sources or "wiki" in sources:
        wiki = _wiki_search(query, lang=lang)
        for r in wiki:
            results.append({
                "title": r["title"],
                "url": r["href"],
                "snippet": r["body"][:200],
                "score": 0.8,
                "source": "wikipedia",
            })

    return jsonify({"query": query, "count": len(results), "results": results})


@app.route("/api/upload", methods=["POST"])
def api_upload():
    """Handle file uploads (paperclip icon)."""
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    filename = secure_filename(file.filename)
    if not _allowed_file(filename):
        return jsonify({"error": f"File type not allowed: {filename}"}), 400

    # Unique filename to avoid collision
    base, ext = os.path.splitext(filename)
    unique_name = f"{base}_{int(time.time())}{ext}"
    save_path = UPLOAD_DIR / unique_name
    file.save(str(save_path))
    logger.info(f"File uploaded: {unique_name} ({save_path.stat().st_size} bytes)")

    mime = mimetypes.guess_type(unique_name)[0] or "application/octet-stream"
    return jsonify({
        "success": True,
        "filename": unique_name,
        "original_name": filename,
        "size": save_path.stat().st_size,
        "mime": mime,
        "url": f"/api/uploads/{unique_name}",
    })


@app.route("/api/uploads/<filename>")
def serve_upload(filename):
    """Serve an uploaded file."""
    safe_name = secure_filename(filename)
    return send_from_directory(str(UPLOAD_DIR), safe_name)


@app.route("/api/goose", methods=["POST"])
def api_goose():
    """
    Goose LLM integration endpoint.
    Forwards prompt to local Ollama / LM Studio if available.
    Falls back to a placeholder when no backend is reachable.
    """
    body = request.get_json(silent=True) or {}
    prompt = body.get("prompt", "").strip()
    model = body.get("model", "llama3")
    max_tokens = int(body.get("max_tokens", 512))

    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    # Try Ollama
    ollama_url = os.getenv("OLLAMA_BASE", "http://localhost:11434")
    ollama_error: Optional[str] = None
    try:
        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }).encode()
        req = urllib.request.Request(
            f"{ollama_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
        return jsonify({"response": resp.get("response", ""), "backend": "ollama", "model": model})
    except Exception as e:
        ollama_error = str(e)
        logger.warning(f"Ollama unavailable: {e}")

    # Try LM Studio
    lms_url = os.getenv("LMS_BASE", "http://localhost:1234")
    lms_error: Optional[str] = None
    try:
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        }).encode()
        req = urllib.request.Request(
            f"{lms_url}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
        text = resp["choices"][0]["message"]["content"]
        return jsonify({"response": text, "backend": "lmstudio", "model": model})
    except Exception as e:
        lms_error = str(e)
        logger.warning(f"LM Studio unavailable: {e}")

    # Fallback placeholder
    return jsonify({
        "response": (
            f"[Goose stub] Нет доступного LLM-бэкенда.\n"
            f"• Ollama ({ollama_url}): {ollama_error}\n"
            f"• LM Studio ({lms_url}): {lms_error}\n\n"
            f"Запустите Ollama (`ollama serve`) или LM Studio и повторите попытку."
        ),
        "backend": "stub",
        "model": model,
    })


@app.route("/api/3d", methods=["POST"])
def api_3d():
    """
    3-D object generator.
    Returns a simple Three.js-compatible JSON scene description.
    """
    body = request.get_json(silent=True) or {}
    description = body.get("description", "cube").strip()
    scene_type = body.get("type", "auto")  # cube | sphere | torus | auto

    if scene_type == "auto":
        desc_lower = description.lower()
        if any(w in desc_lower for w in ["sphere", "ball", "шар", "сфера"]):
            scene_type = "sphere"
        elif any(w in desc_lower for w in ["torus", "ring", "кольцо", "бублик", "тор"]):
            scene_type = "torus"
        elif any(w in desc_lower for w in ["cylinder", "цилиндр"]):
            scene_type = "cylinder"
        else:
            scene_type = "cube"

    geometry_map = {
        "cube":     {"type": "BoxGeometry",      "args": [1, 1, 1]},
        "sphere":   {"type": "SphereGeometry",   "args": [0.7, 32, 32]},
        "torus":    {"type": "TorusGeometry",    "args": [0.6, 0.2, 16, 100]},
        "cylinder": {"type": "CylinderGeometry", "args": [0.5, 0.5, 1.2, 32]},
    }

    scene = {
        "version": "1.0",
        "description": description,
        "geometry": geometry_map.get(scene_type, geometry_map["cube"]),
        "material": {
            "type": "MeshStandardMaterial",
            "color": "#4fc3f7",
            "metalness": 0.3,
            "roughness": 0.5,
            "wireframe": False,
        },
        "lights": [
            {"type": "AmbientLight",     "color": "#ffffff", "intensity": 0.6},
            {"type": "DirectionalLight", "color": "#ffffff", "intensity": 1.0,
             "position": [5, 5, 5]},
        ],
        "camera": {"fov": 60, "position": [2, 2, 3]},
        "animate": {"rotate_y": 0.005},
    }
    return jsonify(scene)


@app.route("/api/video", methods=["POST"])
def api_video():
    """
    Video generator / processor.
    Accepts a file upload or a URL and returns metadata + processing status.
    """
    # Handle file upload
    if "file" in request.files:
        file = request.files["file"]
        filename = secure_filename(file.filename or "video.mp4")
        if not _allowed_file(filename):
            return jsonify({"error": "File type not allowed"}), 400
        base, ext = os.path.splitext(filename)
        unique_name = f"{base}_{int(time.time())}{ext}"
        save_path = UPLOAD_DIR / unique_name
        file.save(str(save_path))

        # Try to get duration with moviepy if available
        duration: Optional[float] = None
        try:
            from moviepy.editor import VideoFileClip
            clip = VideoFileClip(str(save_path))
            duration = clip.duration
            clip.close()
        except Exception:
            pass

        return jsonify({
            "success": True,
            "filename": unique_name,
            "url": f"/api/uploads/{unique_name}",
            "size": save_path.stat().st_size,
            "duration": duration,
            "status": "ready",
            "operations": ["trim", "resize", "extract_frames", "add_subtitles"],
        })

    # Handle JSON body (URL or generation params)
    body = request.get_json(silent=True) or {}
    prompt = body.get("prompt", "").strip()
    if prompt:
        return jsonify({
            "success": True,
            "status": "queued",
            "prompt": prompt,
            "message": (
                "Генерация видео поставлена в очередь. "
                "Подключите Stable Video Diffusion или аналогичный бэкенд для реальной генерации."
            ),
            "backend": "stub",
        })

    return jsonify({"error": "Provide 'file' upload or JSON with 'prompt'"}), 400


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(413)
def too_large(_e):
    return jsonify({"error": f"File too large (max {MAX_UPLOAD_MB} MB)"}), 413


@app.errorhandler(404)
def not_found(_e):
    return jsonify({"error": "Not found"}), 404


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    host = os.getenv("VM_HOST", "0.0.0.0")
    port = int(os.getenv("VM_PORT", "5000"))
    debug = os.getenv("VM_DEBUG", "0") == "1"
    logger.info(f"DRGR VM starting on {host}:{port}")
    app.run(host=host, port=port, debug=debug)
