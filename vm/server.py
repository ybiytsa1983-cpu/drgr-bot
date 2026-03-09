"""
Code VM Server — Flask backend for the Monaco-based self-improving code environment.

Endpoints:
  GET  /               — serve the Monaco editor UI
  POST /execute        — run code (Python or JavaScript) in a sandboxed subprocess
  POST /check          — static-check / lint code
  GET  /instructions   — return the current self-improvement JSON
  POST /instructions   — update training / internet-work instructions
  GET  /ollama/models  — list models available in the local Ollama instance
  POST /ollama/ask     — ask a free-form question to a model (AI chat)
  POST /ollama/pull    — pull / download an Ollama model (streaming NDJSON)
  POST /ollama/create  — create a custom model from a Modelfile
  POST /ollama/delete  — delete an Ollama model
  POST /generate/code  — generate code from a prompt (returns extracted code block)
  POST /generate/html  — generate a full HTML page from a prompt (live-preview ready)
  GET  /navigator/     — serve the DRGRNav PWA navigator app
  GET  /challenges     — return pre-defined hard challenge prompts for the VM
  POST /retrain        — manually trigger a self-improvement cycle
  POST /agent/log      — receive action record from the Telegram bot for self-learning
  GET  /agent/stats    — return agent action statistics and current training instructions
  POST /agent/describe_image — describe an image using Ollama vision model
"""

import ast
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
import urllib.parse
from datetime import datetime, timezone

# Load .env from project root (parent of vm/) so OLLAMA_HOST / BOT_TOKEN etc.
# are available even when server.py is started directly with `python server.py`.
try:
    from dotenv import load_dotenv as _load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    _load_dotenv(dotenv_path=_env_path, override=False)
except ImportError:
    pass  # python-dotenv not installed — rely on environment variables

import requests as _http
from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context

app = Flask(__name__, static_folder="static")
_log = logging.getLogger("CodeVM")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_DIR = os.path.dirname(os.path.abspath(__file__))
INSTRUCTIONS_FILE = os.path.join(_DIR, "instructions.json")
NAVIGATOR_DIR     = os.path.join(os.path.dirname(_DIR), "navigator")
PROJECTS_DIR      = os.path.join(_DIR, "projects")

# Training-data directory — stores per-action JSONL logs from the bot
TRAINING_DATA_DIR         = os.path.join(_DIR, "training_data")
ACTIONS_LOG_FILE          = os.path.join(TRAINING_DATA_DIR, "actions.jsonl")
# Dedicated JSON file for image descriptions (for VM self-learning / fine-tuning)
IMAGE_DESCRIPTIONS_FILE   = os.path.join(TRAINING_DATA_DIR, "image_descriptions.jsonl")
os.makedirs(TRAINING_DATA_DIR, exist_ok=True)

_lock             = threading.Lock()
_actions_lock     = threading.Lock()
_img_desc_lock    = threading.Lock()

# Ollama service base URL (override via OLLAMA_HOST env var)
OLLAMA_BASE = os.environ.get("OLLAMA_HOST", "http://localhost:11435")

# Heartbeat configuration
_OLLAMA_HEARTBEAT_INTERVAL = 60   # seconds between liveness pings
_OLLAMA_HEARTBEAT_TIMEOUT  = 2    # seconds to wait for each Ollama response

# ---------------------------------------------------------------------------
# Ollama port auto-discovery
# ---------------------------------------------------------------------------
# Runs once in a background thread at startup.  First tries the configured
# OLLAMA_BASE URL; if unreachable, scans localhost ports 11434-11444 to
# find where Ollama is actually listening.  This handles users who run
# Ollama on a non-default port (e.g. 11435) even when the launcher has
# set OLLAMA_HOST=http://localhost:11434 as a default.
_OLLAMA_SCANNED = False
_OLLAMA_SCAN_LOCK = threading.Lock()


def _autodiscover_ollama() -> None:
    """Verify OLLAMA_BASE is reachable; if not, scan ports 11434-11444."""
    global OLLAMA_BASE, _OLLAMA_SCANNED
    with _OLLAMA_SCAN_LOCK:
        if _OLLAMA_SCANNED:
            return
        _OLLAMA_SCANNED = True
        # 1. Try the already-configured base URL first.
        try:
            _http.get(f"{OLLAMA_BASE}/api/tags", timeout=1)
            return  # configured URL is reachable — done
        except Exception:  # pylint: disable=broad-except
            pass
        # 2. Fall back: scan localhost ports 11434-11444.
        #    Covers cases where the launcher set a default of 11434 but
        #    Ollama is actually listening on a different port (e.g. 11435).
        parsed = urllib.parse.urlparse(OLLAMA_BASE)
        scheme = parsed.scheme or "http"
        host = parsed.hostname or "localhost"
        for port in range(11434, 11445):
            url = f"{scheme}://{host}:{port}"
            try:
                _http.get(f"{url}/api/tags", timeout=1)
                OLLAMA_BASE = url   # update global for all subsequent requests
                return
            except Exception:  # pylint: disable=broad-except
                continue


# Kick off discovery immediately so it's done before the first browser request
threading.Thread(target=_autodiscover_ollama, daemon=True).start()


def _ollama_heartbeat() -> None:
    """Background thread: re-check Ollama every 60 s and re-discover if lost.

    This ensures the VM always picks up Ollama even when it starts or restarts
    after the VM is already running — without requiring the browser to be open.
    """
    while True:
        time.sleep(_OLLAMA_HEARTBEAT_INTERVAL)
        try:
            _http.get(f"{OLLAMA_BASE}/api/tags", timeout=_OLLAMA_HEARTBEAT_TIMEOUT)
        except Exception:  # pylint: disable=broad-except
            # Ollama appears to be gone — allow a fresh scan
            with _OLLAMA_SCAN_LOCK:
                if _OLLAMA_SCANNED:
                    _OLLAMA_SCANNED = False
            _autodiscover_ollama()


threading.Thread(target=_ollama_heartbeat, daemon=True).start()

# Preferred model order for auto-selection (first match wins).
# Override the default with OLLAMA_DEFAULT_MODEL env var.
_PREFERRED_MODELS = [
    m for m in [
        os.environ.get("OLLAMA_DEFAULT_MODEL", ""),
        # Preferred models (newest first)
        "qwen3-vl:8b",
        "qwen3-vl:235b-cloud",
        "qwen2.5-coder:7b",
        "qwen2.5:7b",
        # Common qwen variants already installed by many users
        "qwen2:7b",
        "qwen:latest",
        "qwen:7b",
        "qwen:4b",
        # Other capable models
        "gemma3:12b",
        "gemma3:latest",
        "llama3.2:latest",
        "llama3:8b",
        "mistral:latest",
    ] if m
]

# ---------------------------------------------------------------------------
# Instruction helpers
# ---------------------------------------------------------------------------
_DEFAULT_INSTRUCTIONS: dict = {
    "version": 1,
    "last_updated": "",
    "statistics": {
        "total_runs": 0,
        "successful_runs": 0,
        "failed_runs": 0,
        "total_checks": 0,
    },
    "learned_patterns": {
        "common_errors": {},
        "frequently_used_imports": {},
    },
    "training_instructions": [
        "Write clean, readable code with meaningful variable names",
        "Always handle exceptions — never use bare except",
        "Add docstrings to every function and class",
        "Prefer list comprehensions over explicit for-loops where readable",
    ],
    "internet_work_instructions": [
        "Use the requests library for HTTP calls",
        "Always set timeouts for network requests",
        "Handle HTTP errors and connection errors gracefully",
        "Store API keys in environment variables, never hard-code them",
        "Use aiohttp for async HTTP when performance matters",
    ],
    "improvement_history": [],
    "generation_stats": {
        "total_generations": 0,
        "code_generations": 0,
        "html_generations": 0,
        "successful_prompts": [],
    },
    # ── Agent self-learning section ──────────────────────────────────────────
    # Populated by POST /agent/log calls from the Telegram bot.
    # Used by _regenerate_instructions() to improve prompts & behaviour.
    "agent_actions": {
        "total_searches": 0,
        "total_screenshots": 0,
        "total_articles": 0,
        "total_image_descriptions": 0,
        "total_generate_html": 0,
        "failed_actions": 0,
        "retrain_cycles": 0,
        "popular_queries": {},          # query -> count
        "screenshot_failed_domains": {},  # domain -> fail_count
        "avg_sources_per_query": 0.0,
        "screenshot_success_rate": 1.0,
        "image_descriptions": [],       # last 50 AI descriptions (for training)
        "article_topics": [],           # last 50 article titles
        "actions_since_last_retrain": 0,
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _deep_copy(obj: dict) -> dict:
    return json.loads(json.dumps(obj))


def load_instructions() -> dict:
    with _lock:
        if os.path.exists(INSTRUCTIONS_FILE):
            try:
                with open(INSTRUCTIONS_FILE, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, OSError):
                pass
        data = _deep_copy(_DEFAULT_INSTRUCTIONS)
        data["last_updated"] = _now()
        _write_instructions_unsafe(data)
        return data


def _write_instructions_unsafe(data: dict) -> None:
    """Write without acquiring the lock — caller is responsible."""
    data["last_updated"] = _now()
    with open(INSTRUCTIONS_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def save_instructions(data: dict) -> None:
    with _lock:
        _write_instructions_unsafe(data)


# ---------------------------------------------------------------------------
# Code execution
# ---------------------------------------------------------------------------
_RUNNERS = {
    "python": ["python3"],
    "javascript": ["node"],
}


def _run_code(code: str, language: str) -> dict:
    runner = _RUNNERS.get(language)
    if runner is None:
        return {"output": "", "error": f"Unsupported language: {language}", "success": False}

    suffix = ".py" if language == "python" else ".js"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=suffix, mode="w", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(code)
            tmp_path = tmp.name

        proc = subprocess.run(
            runner + [tmp_path],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=tempfile.gettempdir(),
        )
        return {
            "output": proc.stdout[:4096],
            "error": proc.stderr[:2048],
            "success": proc.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"output": "", "error": "Execution timed out (10 s limit)", "success": False}
    except FileNotFoundError:
        return {
            "output": "",
            "error": f"Runtime not found: {runner[0]}",
            "success": False,
        }
    except Exception as exc:  # pylint: disable=broad-except
        return {"output": "", "error": str(exc), "success": False}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Code checking
# ---------------------------------------------------------------------------
def _check_python(code: str) -> list:
    issues = []

    # 1. Syntax check via ast.parse
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        issues.append(
            {"line": exc.lineno or 1, "message": str(exc.msg), "severity": "error"}
        )
        return issues  # no further checks useful after syntax error

    # 2. AST-based checks (avoids false positives from string literals)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "print":
                issues.append(
                    {
                        "line": node.lineno,
                        "message": "print() found — consider using logging in production",
                        "severity": "info",
                    }
                )

    # 3. Line-level style checks
    for lineno, line in enumerate(code.splitlines(), start=1):
        if len(line) > 120:
            issues.append(
                {
                    "line": lineno,
                    "message": f"Line too long ({len(line)} chars, limit 120)",
                    "severity": "warning",
                }
            )
        if line.strip() == "except:":
            issues.append(
                {
                    "line": lineno,
                    "message": "Bare except clause — catch specific exceptions",
                    "severity": "warning",
                }
            )

    return issues


# ---------------------------------------------------------------------------
# Self-improvement engine
# ---------------------------------------------------------------------------

# Auto-retrain after this many logged agent actions
_RETRAIN_AFTER_ACTIONS = int(os.environ.get("RETRAIN_AFTER_ACTIONS", "10"))

# Vision-capable models (preferred order for image description)
_VISION_MODELS = [
    m for m in [
        os.environ.get("OLLAMA_VISION_MODEL", ""),
        "llava:latest",
        "llava:7b",
        "bakllava:latest",
        "moondream:latest",
        "llava-phi3:latest",
    ] if m
]


def _save_image_description(summary: dict, full_description: str) -> None:
    """Append a full image description to IMAGE_DESCRIPTIONS_FILE (JSON Lines).

    Each line is a self-contained training sample::

        {"image_path": "...", "description": "...", "ts": "..."}

    The file is in JSON Lines format so it can be streamed into a fine-tuning
    pipeline without loading the whole file into memory.
    """
    entry = {
        "image_path":   summary.get("path", ""),
        "description":  full_description,
        "ts":           summary.get("ts", ""),
    }
    with _img_desc_lock:
        try:
            with open(IMAGE_DESCRIPTIONS_FILE, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:
            _log.debug("Failed to write image description: %s", exc)


def _record_agent_action(record: dict) -> None:
    """
    Persist one agent action record:
      - Appends the raw JSON line to ACTIONS_LOG_FILE (JSONL format)
      - Updates summary counters in instructions.json
      - Auto-triggers _regenerate_instructions every _RETRAIN_AFTER_ACTIONS actions
    """
    action_type = record.get("action_type", "unknown")
    success     = bool(record.get("success", False))

    # 1. Append to JSONL log
    with _actions_lock:
        try:
            with open(ACTIONS_LOG_FILE, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            _log.debug("Failed to write action log: %s", exc)

    # 2. Update summary in instructions.json
    data = load_instructions()
    aa = data.setdefault("agent_actions", _deep_copy(
        _DEFAULT_INSTRUCTIONS["agent_actions"]
    ))

    if action_type == "search":
        aa["total_searches"] = aa.get("total_searches", 0) + 1
        query = record.get("input", {}).get("query", "")
        if query:
            # strip "ddg:" / "wiki:" prefix
            clean_q = re.sub(r"^(ddg|wiki):", "", query)
            pop = aa.setdefault("popular_queries", {})
            pop[clean_q] = pop.get(clean_q, 0) + 1
            # keep only top 100
            if len(pop) > 100:
                aa["popular_queries"] = dict(
                    sorted(pop.items(), key=lambda x: -x[1])[:100]
                )
        # update avg sources
        sc = record.get("output", {}).get("source_count", 0)
        prev_total = aa.get("total_searches", 1)
        prev_avg   = aa.get("avg_sources_per_query", 0.0)
        aa["avg_sources_per_query"] = round(
            (prev_avg * (prev_total - 1) + sc) / prev_total, 2
        )

    elif action_type == "screenshot":
        aa["total_screenshots"] = aa.get("total_screenshots", 0) + 1
        if not success:
            aa["failed_actions"] = aa.get("failed_actions", 0) + 1
            url = record.get("input", {}).get("url", "")
            try:
                import urllib.parse as _up
                domain = _up.urlparse(url).netloc
                if domain:
                    fd = aa.setdefault("screenshot_failed_domains", {})
                    fd[domain] = fd.get(domain, 0) + 1
            except Exception:
                pass
        total_ss = aa.get("total_screenshots", 1)
        failed   = sum(aa.get("screenshot_failed_domains", {}).values())
        aa["screenshot_success_rate"] = round(
            max(0.0, (total_ss - failed) / total_ss), 3
        )

    elif action_type == "article":
        aa["total_articles"] = aa.get("total_articles", 0) + 1
        title = record.get("output", {}).get("title", "")
        if title:
            topics = aa.setdefault("article_topics", [])
            topics.append({"title": title, "ts": record.get("timestamp", "")})
            if len(topics) > 50:
                aa["article_topics"] = topics[-50:]

    elif action_type == "describe_image":
        aa["total_image_descriptions"] = aa.get("total_image_descriptions", 0) + 1
        if success:
            desc = record.get("output", {}).get("description", "")
            if desc:
                descs = aa.setdefault("image_descriptions", [])
                img_entry = {
                    "path": record.get("input", {}).get("image_path", ""),
                    "description": desc[:400],
                    "ts": record.get("timestamp", ""),
                }
                descs.append(img_entry)
                if len(descs) > 50:
                    aa["image_descriptions"] = descs[-50:]
                # Also write to dedicated image_descriptions.json for training
                _save_image_description(
                    {"path": img_entry["path"], "ts": img_entry["ts"]},
                    desc,
                )
        else:
            aa["failed_actions"] = aa.get("failed_actions", 0) + 1

    elif action_type == "generate_html":
        aa["total_generate_html"] = aa.get("total_generate_html", 0) + 1
        if not success:
            aa["failed_actions"] = aa.get("failed_actions", 0) + 1

    # 3. Increment actions-since-retrain counter
    aa["actions_since_last_retrain"] = aa.get("actions_since_last_retrain", 0) + 1
    save_instructions(data)

    # 4. Auto-retrain if threshold reached
    if aa["actions_since_last_retrain"] >= _RETRAIN_AFTER_ACTIONS:
        data2 = load_instructions()
        _regenerate_instructions(data2)
        data2["agent_actions"]["actions_since_last_retrain"] = 0
        data2["agent_actions"]["retrain_cycles"] = (
            data2["agent_actions"].get("retrain_cycles", 0) + 1
        )
        save_instructions(data2)


def _regenerate_instructions(data: dict) -> None:
    """
    Analyse accumulated statistics (code runs + agent actions) and rewrite
    training_instructions so the VM constantly improves its behaviour.
    """
    stats    = data["statistics"]
    patterns = data["learned_patterns"]
    total    = stats["total_runs"]
    aa       = data.get("agent_actions", {})

    instructions: list = [
        "Write clean, readable code with meaningful variable names",
        "Always handle exceptions — never use bare except",
    ]

    # ── Code execution success rate ──────────────────────────────────────────
    if total > 0:
        rate = stats["successful_runs"] / total
        if rate < 0.40:
            instructions.append(
                "High failure rate detected — focus on debugging and error handling"
            )
        elif rate < 0.70:
            instructions.append(
                f"Moderate success rate ({rate:.0%}) — review error patterns"
            )
        else:
            instructions.append(
                f"Good success rate ({rate:.0%}) — maintain current coding practices"
            )

    # ── Common errors ────────────────────────────────────────────────────────
    common = patterns.get("common_errors", {})
    for error_key, count in sorted(common.items(), key=lambda x: -x[1])[:3]:
        instructions.append(f"Recurring error ({count}\u00d7): {error_key[:80]}")

    # ── Frequently-used imports ───────────────────────────────────────────────
    freq = patterns.get("frequently_used_imports", {})
    top_libs = sorted(freq.items(), key=lambda x: -x[1])[:5]
    if top_libs:
        lib_names = ", ".join(name for name, _ in top_libs)
        instructions.append(f"Frequently used libraries: {lib_names}")

    # ── Generation activity ───────────────────────────────────────────────────
    gen_stats = data.get("generation_stats", {})
    if gen_stats.get("total_generations", 0) > 0:
        instructions.append(
            f"AI generations so far: {gen_stats['total_generations']} "
            f"({gen_stats.get('code_generations', 0)} code, "
            f"{gen_stats.get('html_generations', 0)} HTML)"
        )

    # ── Agent action insights ─────────────────────────────────────────────────
    if aa.get("total_searches", 0) > 0:
        avg_src = aa.get("avg_sources_per_query", 0)
        instructions.append(
            f"Agent has performed {aa['total_searches']} web searches "
            f"(avg {avg_src:.1f} sources/query)"
        )

    if aa.get("total_screenshots", 0) > 0:
        ss_rate = aa.get("screenshot_success_rate", 1.0)
        instructions.append(
            f"Screenshot success rate: {ss_rate:.0%} "
            f"({aa['total_screenshots']} attempts)"
        )
        # Domains that often fail — avoid or retry with longer timeout
        bad_domains = sorted(
            aa.get("screenshot_failed_domains", {}).items(), key=lambda x: -x[1]
        )[:3]
        if bad_domains:
            dom_str = ", ".join(d for d, _ in bad_domains)
            instructions.append(
                f"Domains with frequent screenshot failures: {dom_str} "
                "— increase timeout or skip"
            )

    if aa.get("total_articles", 0) > 0:
        instructions.append(
            f"Agent has written {aa['total_articles']} research articles"
        )
        recent_topics = [t["title"] for t in aa.get("article_topics", [])[-5:]]
        if recent_topics:
            instructions.append(
                "Recent article topics: " + "; ".join(recent_topics)
            )

    if aa.get("total_image_descriptions", 0) > 0:
        instructions.append(
            f"Agent has described {aa['total_image_descriptions']} images via Ollama vision"
        )
        # Summarise recent descriptions to inform future image understanding
        recent_descs = [d["description"][:60] for d in aa.get("image_descriptions", [])[-3:]]
        if recent_descs:
            instructions.append(
                "Recent image content observed: " + " | ".join(recent_descs)
            )

    if aa.get("total_searches", 0) > 0:
        # Learn about popular topics to improve future search strategies
        pop_q = sorted(aa.get("popular_queries", {}).items(), key=lambda x: -x[1])[:5]
        if pop_q:
            q_str = ", ".join(f'"{q}"' for q, _ in pop_q)
            instructions.append(f"Most searched topics: {q_str}")

    if aa.get("retrain_cycles", 0) > 0:
        instructions.append(
            f"Self-improvement cycles completed: {aa['retrain_cycles']}"
        )

    data["training_instructions"] = instructions

    # Append to improvement_history (keep last 20 entries)
    entry = {
        "timestamp": _now(),
        "total_runs": total,
        "success_rate": round(stats["successful_runs"] / total, 2) if total > 0 else 0,
        "instructions_count": len(instructions),
        "agent_searches": aa.get("total_searches", 0),
        "agent_articles": aa.get("total_articles", 0),
    }
    history = data.setdefault("improvement_history", [])
    history.append(entry)
    if len(history) > 20:
        data["improvement_history"] = history[-20:]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/health", methods=["GET"])
def health():
    """Return overall system status: VM, Ollama, and Telegram bot token.

    Response shape:
    {
      "vm":     {"status": "ok"},
      "ollama": {"status": "ok"|"unreachable", "url": "...", "models": [...]},
      "bot":    {"token_set": true|false, "status": "configured"|"missing"}
    }
    """
    # --- Ollama ---
    ollama_ok     = False
    ollama_models = []
    try:
        resp = _http.get(f"{OLLAMA_BASE}/api/tags", timeout=3)
        if resp.status_code == 200:
            ollama_ok     = True
            ollama_models = [m["name"] for m in resp.json().get("models", [])]
    except Exception:  # pylint: disable=broad-except
        pass

    if not ollama_ok:
        # Ollama is unreachable on the current OLLAMA_BASE — allow the
        # auto-discovery thread to re-scan ports (in case Ollama started
        # after the VM did or moved to a different port).
        # Only reset the flag when no scan is already in flight.
        global _OLLAMA_SCANNED  # noqa: PLW0603 – intentional module-level flag reset
        _should_rescan = False
        with _OLLAMA_SCAN_LOCK:
            if _OLLAMA_SCANNED:   # True = last scan finished; safe to retry
                _OLLAMA_SCANNED = False
                _should_rescan = True
        if _should_rescan:
            threading.Thread(target=_autodiscover_ollama, daemon=True).start()

    # --- Telegram BOT_TOKEN (read from .env in repo root, non-fatal) ---
    bot_token_set = False
    try:
        env_path = os.path.join(os.path.dirname(_DIR), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line.startswith("BOT_TOKEN="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        bot_token_set = bool(val and val != "your_telegram_bot_token_here")
                        break
        # Also honour env var set at runtime (e.g. when running on a server)
        if not bot_token_set and os.environ.get("BOT_TOKEN"):
            bot_token_set = True
    except Exception:  # pylint: disable=broad-except
        pass

    return jsonify({
        "vm":     {"status": "ok"},
        "ollama": {
            "status": "ok" if ollama_ok else "unreachable",
            "url":    OLLAMA_BASE,
            "models": ollama_models,
        },
        "bot": {
            "token_set": bot_token_set,
            "status":    "configured" if bot_token_set else "missing",
        },
    })


# ---------------------------------------------------------------------------
# Navigator PWA
# ---------------------------------------------------------------------------
@app.route("/navigator/")
@app.route("/navigator/index.html")
def navigator_index():
    """Serve the DRGRNav PWA navigator."""
    return send_from_directory(NAVIGATOR_DIR, "index.html")


@app.route("/navigator/<path:filename>")
def navigator_static(filename):
    """Serve navigator static files (manifest, sw.js, …)."""
    return send_from_directory(NAVIGATOR_DIR, filename)


# ---------------------------------------------------------------------------
# Challenges
# ---------------------------------------------------------------------------
_CHALLENGES = [
    {
        "id": "android_navigator",
        "title": "🧭 Android навигатор (онлайн + офлайн)",
        "difficulty": "⭐⭐⭐⭐⭐",
        "language": "html",
        "prompt": (
            "Create a complete, self-contained Android PWA navigator HTML page with: "
            "Leaflet.js map using OpenStreetMap tiles, GPS watchPosition with accuracy circle, "
            "address search with Nominatim autocomplete, OSRM turn-by-turn routing for "
            "car/bike/walk modes, Service Worker for offline tile caching, "
            "IndexedDB for saving/loading routes, dark theme, Russian language UI, "
            "mobile-first design with touch support. All in a single HTML file."
        ),
        "description": (
            "Полнофункциональный навигатор для Android как Progressive Web App. "
            "Работает онлайн (OSM/OSRM) и офлайн (Service Worker + IndexedDB). "
            "GPS, автодополнение адресов, пошаговая навигация, сохранение маршрутов."
        ),
        "demo_url": "/navigator/",
    },
    {
        "id": "python_web_scraper",
        "title": "🕷 Умный веб-скрапер с обходом защит",
        "difficulty": "⭐⭐⭐⭐",
        "language": "python",
        "prompt": (
            "Write a Python web scraper using requests and BeautifulSoup that: "
            "handles JavaScript-rendered pages via Playwright, rotates User-Agent headers, "
            "respects robots.txt, implements exponential backoff on 429 errors, "
            "saves results to SQLite with deduplication, supports resuming interrupted scrapes, "
            "extracts structured data (title, price, images) from e-commerce pages."
        ),
        "description": (
            "Продвинутый скрапер с обходом защит, поддержкой JS-рендеринга, "
            "ротацией заголовков и сохранением в SQLite с возможностью продолжения."
        ),
        "demo_url": None,
    },
    {
        "id": "realtime_chat",
        "title": "💬 Real-time чат с WebSocket",
        "difficulty": "⭐⭐⭐⭐",
        "language": "python",
        "prompt": (
            "Write a Python WebSocket chat server using asyncio and websockets library with: "
            "rooms/channels, nickname registration, message history (last 50 per room) stored in memory, "
            "private messages, online user list, typing indicators, "
            "and a complete single-file HTML client with dark theme. "
            "The server should be a single Python file."
        ),
        "description": (
            "Сервер чата на asyncio WebSocket с комнатами, историей, личными сообщениями "
            "и индикатором набора текста. Клиент — единый HTML файл."
        ),
        "demo_url": None,
    },
    {
        "id": "neural_net",
        "title": "🧠 Нейросеть с нуля (NumPy)",
        "difficulty": "⭐⭐⭐⭐⭐",
        "language": "python",
        "prompt": (
            "Write a complete neural network from scratch using only NumPy (no TensorFlow/PyTorch): "
            "implement forward pass, backpropagation, Adam optimizer, batch normalization, "
            "dropout regularisation, train on MNIST dataset loaded from CSV, "
            "achieve >97% accuracy, plot training curves to PNG, "
            "save/load model weights to npz file. Include full docstrings."
        ),
        "description": (
            "Нейросеть на чистом NumPy: backprop, Adam, BatchNorm, Dropout, обучение на MNIST, "
            "точность >97%, сохранение весов. Без фреймворков."
        ),
        "demo_url": None,
    },
    {
        "id": "blockchain",
        "title": "⛓ Мини-блокчейн с PoW",
        "difficulty": "⭐⭐⭐⭐",
        "language": "python",
        "prompt": (
            "Write a minimal but complete blockchain in Python with: "
            "SHA-256 proof-of-work mining, adjustable difficulty, "
            "transaction pool with UTXO model, digital signatures (ECDSA), "
            "peer-to-peer sync via HTTP (Flask), chain validation, "
            "REST API to submit transactions and mine blocks, "
            "and a simple block explorer HTML page served by Flask."
        ),
        "description": (
            "Блокчейн с PoW майнингом, UTXO-транзакциями, ECDSA подписями, "
            "P2P синхронизацией и веб-обозревателем блоков."
        ),
        "demo_url": None,
    },
    {
        "id": "autonomous_browser_agent",
        "title": "🤖 Автономный агент в браузере",
        "difficulty": "⭐⭐⭐⭐⭐",
        "language": "html",
        "prompt": (
            "Create a complete single-file HTML autonomous browser agent that works entirely offline "
            "(no server, no CDN, zero external requests). Requirements:\n\n"
            "1. TASK QUEUE — user types a task in natural language (e.g. 'summarise this text', "
            "'sort this list', 'calculate fibonacci to N'), agent parses intent and executes it.\n\n"
            "2. CODE GENERATION — agent generates and runs JavaScript code to fulfil the task "
            "using Function() constructor in a try/catch sandbox, captures stdout via console.log override.\n\n"
            "3. SELF-CORRECTION — if execution throws an error, agent rewrites the code and retries "
            "up to 3 times, each attempt shown in the log with diff highlighting.\n\n"
            "4. MEMORY — uses IndexedDB to persist task history and results across page reloads; "
            "shows history panel with timestamps.\n\n"
            "5. FILE I/O — can read dropped files (text, CSV, JSON) and use their content as task input; "
            "can export results as a downloaded file.\n\n"
            "6. OFFLINE AI (optional) — if window.ai (Chrome Built-in AI) or a local WebLLM is "
            "available use it for intent parsing; otherwise use a deterministic rule-based parser.\n\n"
            "7. UI — dark VS Code-like theme, split layout: left = task input + history, "
            "right = live execution log with colour-coded lines (info/warn/error/result), "
            "bottom = generated code viewer with syntax highlighting via a simple tokenizer.\n\n"
            "All JavaScript must be inline. No import/export. No external scripts. "
            "Must work by opening the .html file directly in a browser (file:// protocol)."
        ),
        "description": (
            "Полностью автономный агент в одном HTML файле: принимает задачи на естественном языке, "
            "генерирует и запускает JavaScript, самостоятельно исправляет ошибки (до 3 попыток), "
            "сохраняет историю в IndexedDB, читает файлы drag-and-drop. "
            "Работает без интернета, без сервера — только браузер."
        ),
        "demo_url": None,
    },
]


@app.route("/challenges", methods=["GET"])
def get_challenges():
    """Return the list of pre-defined hard challenge prompts."""
    return jsonify({"challenges": _CHALLENGES})


@app.route("/execute", methods=["POST"])
def execute():
    body = request.get_json(silent=True) or {}
    code = body.get("code", "").strip()
    language = body.get("language", "python")

    if not code:
        return jsonify({"output": "", "error": "No code provided or code is empty", "success": False})

    result = _run_code(code, language)

    data = load_instructions()
    data["statistics"]["total_runs"] += 1

    if result["success"]:
        data["statistics"]["successful_runs"] += 1
        # Track which libraries are imported in successful code
        for match in re.finditer(r"^(?:import|from)\s+(\w+)", code, re.MULTILINE):
            lib = match.group(1)
            freq = data["learned_patterns"].setdefault("frequently_used_imports", {})
            freq[lib] = freq.get(lib, 0) + 1
    else:
        data["statistics"]["failed_runs"] += 1
        if result["error"]:
            lines = [ln for ln in result["error"].splitlines() if ln.strip()]
            error_key = lines[-1][:100] if lines else "Unknown error"
            common = data["learned_patterns"].setdefault("common_errors", {})
            common[error_key] = common.get(error_key, 0) + 1

    _regenerate_instructions(data)
    save_instructions(data)

    return jsonify(result)


@app.route("/check", methods=["POST"])
def check_code():
    body = request.get_json(silent=True) or {}
    code = body.get("code", "")
    language = body.get("language", "python")

    data = load_instructions()
    data["statistics"]["total_checks"] += 1
    save_instructions(data)

    issues: list = []
    if language == "python":
        issues = _check_python(code)

    return jsonify(
        {
            "issues": issues,
            "success": not any(i["severity"] == "error" for i in issues),
        }
    )


@app.route("/instructions", methods=["GET"])
def get_instructions():
    return jsonify(load_instructions())


@app.route("/instructions", methods=["POST"])
def update_instructions():
    body = request.get_json(silent=True) or {}
    data = load_instructions()
    if "training_instructions" in body:
        data["training_instructions"] = body["training_instructions"]
    if "internet_work_instructions" in body:
        data["internet_work_instructions"] = body["internet_work_instructions"]
    save_instructions(data)
    return jsonify({"success": True, "data": data})


# ---------------------------------------------------------------------------
# Ollama integration
# ---------------------------------------------------------------------------
@app.route("/ollama/models", methods=["GET"])
def ollama_models():
    """Return the list of models available in the local Ollama instance."""
    try:
        resp = _http.get(f"{OLLAMA_BASE}/api/tags", timeout=3)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        # Pick the preferred default (first match from _PREFERRED_MODELS list)
        preferred = next((m for m in _PREFERRED_MODELS if m in models), models[0] if models else "")
        return jsonify({"models": models, "available": True, "preferred": preferred})
    except Exception:  # pylint: disable=broad-except
        return jsonify({"models": [], "available": False, "preferred": ""})


@app.route("/ollama/ask", methods=["POST"])
def ollama_ask():
    """Forward a code + prompt to an Ollama model and return the response."""
    body = request.get_json(silent=True) or {}
    model = body.get("model", "").strip()
    prompt = body.get("prompt", "").strip()
    code = body.get("code", "").strip()

    if not model:
        return jsonify({"response": "", "error": "No model selected", "success": False})
    if not prompt and not code:
        return jsonify({"response": "", "error": "No prompt provided", "success": False})

    if code:
        # Include the language name in the code fence for better AI understanding
        lang_hint = body.get("language", "python")
        full_prompt = f"Here is some code:\n```{lang_hint}\n{code}\n```\n\n{prompt}" if prompt else code
    else:
        full_prompt = prompt

    try:
        resp = _http.post(
            f"{OLLAMA_BASE}/api/generate",
            json={"model": model, "prompt": full_prompt, "stream": False},
            # 120 s allows large models (70B+) enough time to generate a response;
            # configurable via OLLAMA_TIMEOUT env var for faster/slower hardware.
            timeout=int(os.environ.get("OLLAMA_TIMEOUT", 120)),
        )
        resp.raise_for_status()
        response_text = resp.json().get("response", "")
        return jsonify({"response": response_text, "success": True})
    except _http.exceptions.Timeout:
        return jsonify({"response": "", "error": "Ollama request timed out (120 s)", "success": False})
    except _http.exceptions.ConnectionError:
        return jsonify({"response": "", "error": "Cannot connect to Ollama — is 'ollama serve' running?", "success": False})
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"response": "", "error": str(exc), "success": False})


@app.route("/ollama/ask/stream", methods=["POST"])
def ollama_ask_stream():
    """Stream tokens from Ollama as SSE events.

    Body: {"prompt": "...", "model": "...", "code": "...", "language": "..."}
    Streams ``data: {"token": "..."}\n\n`` lines; ends with ``data: [DONE]\n\n``.
    On error streams ``data: {"error": "..."}\n\n``.
    """
    body = request.get_json(silent=True) or {}
    model = body.get("model", "").strip()
    prompt = body.get("prompt", "").strip()
    code = body.get("code", "").strip()

    if not model:
        def _err_no_model():
            yield 'data: {"error":"No model selected"}\n\n'
        return Response(stream_with_context(_err_no_model()), mimetype="text/event-stream")

    if code:
        lang_hint = body.get("language", "python")
        full_prompt = f"Here is some code:\n```{lang_hint}\n{code}\n```\n\n{prompt}" if prompt else code
    else:
        full_prompt = prompt or ""

    def _stream():
        try:
            resp = _http.post(
                f"{OLLAMA_BASE}/api/generate",
                json={"model": model, "prompt": full_prompt, "stream": True},
                stream=True,
                timeout=int(os.environ.get("OLLAMA_TIMEOUT", 120)),
            )
            resp.raise_for_status()
            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue
                try:
                    chunk = json.loads(raw_line)
                except ValueError:
                    continue
                token = chunk.get("response", "")
                if token:
                    yield f"data: {json.dumps({'token': token})}\n\n"
                if chunk.get("done"):
                    yield "data: [DONE]\n\n"
                    return
        except _http.exceptions.ConnectionError:
            yield 'data: {"error":"Cannot connect to Ollama — is \'ollama serve\' running?"}\n\n'
        except Exception as exc:  # pylint: disable=broad-except
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return Response(
        stream_with_context(_stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Model Workshop endpoints  (create / pull / delete models in Ollama)
# ---------------------------------------------------------------------------

@app.route("/ollama/pull", methods=["POST"])
def ollama_pull():
    """Pull a model from the Ollama library.

    Body: {"model": "qwen:latest"}
    Returns a streaming text/event-stream response with lines like:
        data: {"status": "...", "percent": 0-100}\n\n
    so the browser can show live download progress.
    """
    body = request.get_json(silent=True) or {}
    model = body.get("model", "").strip()
    if not model:
        return jsonify({"error": "model name required"}), 400

    def _stream():
        try:
            with _http.post(
                f"{OLLAMA_BASE}/api/pull",
                json={"name": model, "stream": True},
                stream=True,
                timeout=3600,
            ) as r:
                for raw_line in r.iter_lines():
                    if not raw_line:
                        continue
                    try:
                        obj = json.loads(raw_line)
                    except ValueError:
                        continue
                    # Calculate progress percentage when total is available
                    total     = obj.get("total", 0)
                    completed = obj.get("completed", 0)
                    percent   = min(100, int(completed * 100 / total)) if total else 0
                    payload = json.dumps({
                        "status":    obj.get("status", ""),
                        "digest":    obj.get("digest", ""),
                        "percent":   percent,
                        "error":     obj.get("error", ""),
                    })
                    yield f"data: {payload}\n\n"
            yield "data: {\"status\":\"done\",\"percent\":100}\n\n"
        except _http.exceptions.ConnectionError:
            yield "data: {\"error\":\"Cannot connect to Ollama\"}\n\n"
        except Exception as exc:  # pylint: disable=broad-except
            yield f"data: {{\"error\":{json.dumps(str(exc))}}}\n\n"

    return Response(
        stream_with_context(_stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/ollama/create", methods=["POST"])
def ollama_create():
    """Create a custom Ollama model from a Modelfile string.

    Body: {"name": "my-coder", "modelfile": "FROM qwen:latest\\nSYSTEM ..."}
    Returns a streaming text/event-stream response with progress lines.
    """
    body = request.get_json(silent=True) or {}
    name      = body.get("name", "").strip()
    modelfile = body.get("modelfile", "").strip()
    if not name:
        return jsonify({"error": "model name required"}), 400
    if not modelfile:
        return jsonify({"error": "modelfile content required"}), 400

    def _stream():
        try:
            with _http.post(
                f"{OLLAMA_BASE}/api/create",
                json={"name": name, "modelfile": modelfile, "stream": True},
                stream=True,
                timeout=3600,
            ) as r:
                for raw_line in r.iter_lines():
                    if not raw_line:
                        continue
                    try:
                        obj = json.loads(raw_line)
                    except ValueError:
                        continue
                    payload = json.dumps({
                        "status": obj.get("status", ""),
                        "error":  obj.get("error", ""),
                    })
                    yield f"data: {payload}\n\n"
            yield f"data: {{\"status\":\"Model '{name}' created successfully!\",\"done\":true}}\n\n"
        except _http.exceptions.ConnectionError:
            yield "data: {\"error\":\"Cannot connect to Ollama\"}\n\n"
        except Exception as exc:  # pylint: disable=broad-except
            yield f"data: {{\"error\":{json.dumps(str(exc))}}}\n\n"

    return Response(
        stream_with_context(_stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/ollama/delete", methods=["POST"])
def ollama_delete():
    """Delete a model from Ollama.

    Body: {"model": "my-coder"}
    """
    body = request.get_json(silent=True) or {}
    model = body.get("model", "").strip()
    if not model:
        return jsonify({"error": "model name required"}), 400
    try:
        resp = _http.delete(
            f"{OLLAMA_BASE}/api/delete",
            json={"name": model},
            timeout=30,
        )
        if resp.status_code in (200, 204):
            return jsonify({"success": True, "message": f"Model '{model}' deleted."})
        return jsonify({"success": False, "error": resp.text}), resp.status_code
    except _http.exceptions.ConnectionError:
        return jsonify({"success": False, "error": "Cannot connect to Ollama"}), 503
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"success": False, "error": str(exc)}), 500


def _extract_code_block(text: str, language: str = "") -> str:
    """Extract the first fenced code block from a Markdown-style LLM response.

    Tries a language-specific fence (```python) first, then any fence, then
    returns the raw stripped text if no fence is found.
    """
    if language:
        m = re.search(rf"```{re.escape(language)}\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1).strip()
    # Any fenced block
    m = re.search(r"```(?:\w+)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text.strip()


def _record_generation(language: str, model: str, prompt: str) -> None:
    """Persist a generation event in the self-learning store."""
    data = load_instructions()
    gen = data.setdefault("generation_stats", {
        "total_generations": 0,
        "code_generations": 0,
        "html_generations": 0,
        "successful_prompts": [],
    })
    gen["total_generations"] = gen.get("total_generations", 0) + 1
    if language == "html":
        gen["html_generations"] = gen.get("html_generations", 0) + 1
    else:
        gen["code_generations"] = gen.get("code_generations", 0) + 1
    prompts = gen.setdefault("successful_prompts", [])
    prompts.append({"prompt": prompt[:120], "language": language, "model": model, "ts": _now()})
    # Keep only the last 50 prompts to limit file size and stay within display constraints
    if len(prompts) > 50:
        gen["successful_prompts"] = prompts[-50:]
    _regenerate_instructions(data)
    save_instructions(data)


# ---------------------------------------------------------------------------
# Generation endpoints (Qwen / any Ollama model)
# ---------------------------------------------------------------------------
@app.route("/generate/code", methods=["POST"])
def generate_code():
    """Generate code from a natural-language prompt using Ollama."""
    body = request.get_json(silent=True) or {}
    model = body.get("model", "").strip()
    prompt = body.get("prompt", "").strip()
    language = body.get("language", "python")

    if not model:
        return jsonify({"code": "", "error": "No model selected", "success": False})
    if not prompt:
        return jsonify({"code": "", "error": "No prompt provided", "success": False})

    sys_prompt = (
        f"You are an expert {language} programmer. "
        f"Generate clean, well-commented {language} code for the following task. "
        "Return ONLY the code inside a fenced code block — no explanations outside it.\n\n"
        f"Task: {prompt}"
    )

    try:
        resp = _http.post(
            f"{OLLAMA_BASE}/api/generate",
            json={"model": model, "prompt": sys_prompt, "stream": False},
            timeout=int(os.environ.get("OLLAMA_TIMEOUT", 120)),
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "")
        code = _extract_code_block(raw, language)
        _record_generation(language, model, prompt)
        return jsonify({"code": code, "success": True})
    except _http.exceptions.Timeout:
        return jsonify({"code": "", "error": "Request timed out", "success": False})
    except _http.exceptions.ConnectionError:
        return jsonify({"code": "", "error": "Cannot connect to Ollama — is 'ollama serve' running?", "success": False})
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"code": "", "error": str(exc), "success": False})


@app.route("/generate/html", methods=["POST"])
def generate_html():
    """Generate a complete HTML page from a natural-language description using Ollama."""
    body = request.get_json(silent=True) or {}
    model = body.get("model", "").strip()
    prompt = body.get("prompt", "").strip()

    if not model:
        return jsonify({"html": "", "error": "No model selected", "success": False})
    if not prompt:
        return jsonify({"html": "", "error": "No prompt provided", "success": False})

    sys_prompt = (
        "You are an expert web developer. "
        "Generate a complete, self-contained, responsive HTML page for the description below. "
        "Use modern CSS (flexbox/grid), semantic HTML5, and inline JavaScript if needed. "
        "Return ONLY the full HTML document inside a fenced ```html code block. "
        "Do not write anything outside that block.\n\n"
        f"Description: {prompt}"
    )

    try:
        resp = _http.post(
            f"{OLLAMA_BASE}/api/generate",
            json={"model": model, "prompt": sys_prompt, "stream": False},
            timeout=int(os.environ.get("OLLAMA_TIMEOUT", 180)),
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "")
        html = _extract_code_block(raw, "html")
        _record_generation("html", model, prompt)
        return jsonify({"html": html, "success": True})
    except _http.exceptions.Timeout:
        return jsonify({"html": "", "error": "Request timed out", "success": False})
    except _http.exceptions.ConnectionError:
        return jsonify({"html": "", "error": "Cannot connect to Ollama — is 'ollama serve' running?", "success": False})
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"html": "", "error": str(exc), "success": False})


# ---------------------------------------------------------------------------
# Retrain / self-improvement trigger
# ---------------------------------------------------------------------------
@app.route("/retrain", methods=["POST"])
def retrain():
    """Manually trigger a self-improvement cycle.

    Analyses accumulated execution statistics and rewrites training_instructions
    based on observed error patterns, success rates, and frequently-used imports.
    Returns the updated instructions document.
    """
    try:
        data = load_instructions()
        _regenerate_instructions(data)
        aa = data.setdefault("agent_actions", {})
        aa["actions_since_last_retrain"] = 0
        aa["retrain_cycles"] = aa.get("retrain_cycles", 0) + 1
        save_instructions(data)
        return jsonify({
            "success": True,
            "message": "Self-improvement cycle completed.",
            "training_instructions": data["training_instructions"],
            "statistics": data["statistics"],
            "agent_actions": data.get("agent_actions", {}),
            "improvement_history_count": len(data.get("improvement_history", [])),
        })
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"success": False, "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Agent self-learning endpoints
# ---------------------------------------------------------------------------

@app.route("/agent/log", methods=["POST"])
def agent_log():
    """Receive one action record from the Telegram bot and persist it.

    Body: {
      "timestamp":   "2026-...",
      "action_type": "search|screenshot|article|describe_image|generate_html|...",
      "input":       {...},
      "output":      {...},
      "success":     true|false,
      "duration_ms": 1234,
      "metadata":    {...}
    }

    The record is:
      1. Appended to vm/training_data/actions.jsonl (one JSON object per line)
      2. Summarised into instructions.json for the self-improvement engine
      3. Auto-triggers _regenerate_instructions every RETRAIN_AFTER_ACTIONS actions
    """
    record = request.get_json(silent=True)
    if not record or not isinstance(record, dict):
        return jsonify({"error": "Invalid JSON body"}), 400
    try:
        threading.Thread(target=_record_agent_action, args=(record,), daemon=True).start()
        return jsonify({"ok": True})
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"error": str(exc)}), 500


@app.route("/agent/stats", methods=["GET"])
def agent_stats():
    """Return agent action statistics and current training instructions."""
    try:
        data = load_instructions()
        return jsonify({
            "agent_actions":         data.get("agent_actions", {}),
            "training_instructions": data.get("training_instructions", []),
            "improvement_history":   data.get("improvement_history", [])[-5:],
            "generation_stats":      data.get("generation_stats", {}),
            "statistics":            data.get("statistics", {}),
        })
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"error": str(exc)}), 500


@app.route("/agent/describe_image", methods=["POST"])
def agent_describe_image():
    """Describe an image using the best available Ollama vision model.

    Body (one of):
      {"image_path": "/absolute/path/to/image.png"}
      {"image_base64": "<base64 string>", "filename": "photo.jpg"}
    Returns: {"description": "...", "model": "llava:latest", "success": true}
    """
    import base64 as _b64

    body           = request.get_json(silent=True) or {}
    image_path     = body.get("image_path", "").strip()
    image_base64   = body.get("image_base64", "").strip()
    filename       = body.get("filename", "image")

    # Resolve image data — accept either a file path OR inline base64
    if image_base64:
        img_b64 = image_base64  # already base64 from browser
    elif image_path:
        if not os.path.isabs(image_path):
            return jsonify({"error": "image_path must be absolute"}), 400
        if not os.path.exists(image_path):
            return jsonify({"error": f"File not found: {image_path}"}), 404
        with open(image_path, "rb") as fh:
            img_b64 = _b64.b64encode(fh.read()).decode()
    else:
        return jsonify({"error": "Provide image_path or image_base64"}), 400

    # Select the first available vision model
    selected_model = None
    try:
        resp = _http.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
        if resp.status_code == 200:
            available = {m["name"] for m in resp.json().get("models", [])}
            for vm_candidate in _VISION_MODELS:
                if vm_candidate in available:
                    selected_model = vm_candidate
                    break
    except Exception:
        pass

    if not selected_model:
        # No vision model available — return empty description gracefully
        return jsonify({"description": "", "model": None, "success": False,
                        "error": "No vision model available. Run: ollama pull llava"})

    try:

        resp = _http.post(
            f"{OLLAMA_BASE}/api/generate",
            json={
                "model":  selected_model,
                "prompt": (
                    "Describe this image in detail in Russian. "
                    "Include all visible text, objects, layout, and context. "
                    "Be specific and informative."
                ),
                "images": [img_b64],
                "stream": False,
            },
            timeout=int(os.environ.get("OLLAMA_TIMEOUT", 120)),
        )
        if resp.status_code == 200:
            description = resp.json().get("response", "")
            # Log to training data
            _record_agent_action({
                "timestamp":   _now(),
                "action_type": "describe_image",
                "input":       {"image_path": image_path},
                "output":      {"description": description[:400]},
                "success":     bool(description),
                "duration_ms": 0,
                "metadata":    {"model": selected_model},
            })
            return jsonify({
                "description": description,
                "model":       selected_model,
                "success":     bool(description),
            })
        return jsonify({"description": "", "model": selected_model, "success": False,
                        "error": resp.text[:200]}), resp.status_code
    except _http.exceptions.ConnectionError:
        return jsonify({"error": "Cannot connect to Ollama"}), 503
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Agent training data endpoint
# ---------------------------------------------------------------------------

@app.route("/agent/training_data", methods=["GET"])
def agent_training_data():
    """Return the image descriptions training dataset (JSON Lines → JSON array).

    Query params:
      ?limit=N   — return only the last N entries (default: all)
      ?format=jsonl — return raw JSONL text instead of JSON array
    """
    limit = request.args.get("limit", "")
    fmt   = request.args.get("format", "json")

    try:
        entries = []
        if os.path.exists(IMAGE_DESCRIPTIONS_FILE):
            with _img_desc_lock:
                with open(IMAGE_DESCRIPTIONS_FILE, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            try:
                                entries.append(json.loads(line))
                            except json.JSONDecodeError:
                                pass

        if limit:
            try:
                entries = entries[-int(limit):]
            except ValueError:
                pass

        if fmt == "jsonl":
            text = "\n".join(json.dumps(e, ensure_ascii=False) for e in entries)
            return app.response_class(text, mimetype="application/x-ndjson")

        return jsonify({
            "total": len(entries),
            "file":  IMAGE_DESCRIPTIONS_FILE,
            "entries": entries,
        })
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Project Generator — autonomous project creation, storage and serving
# ---------------------------------------------------------------------------

def _ensure_projects_dir() -> None:
    os.makedirs(PROJECTS_DIR, exist_ok=True)


def _slugify(text: str) -> str:
    """Convert arbitrary text to a safe directory name."""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_-]+", "_", slug).strip("_")
    return slug[:48] or "project"


def _save_project(project_id: str, name: str, description: str, files: dict) -> str:
    """Persist project files to disk; return the project directory path."""
    _ensure_projects_dir()
    project_dir = os.path.join(PROJECTS_DIR, project_id)
    os.makedirs(project_dir, exist_ok=True)
    for filename, content in files.items():
        file_path = os.path.join(project_dir, filename)
        with open(file_path, "w", encoding="utf-8") as fh:
            fh.write(content)
    # Save project metadata
    meta = {
        "id": project_id,
        "name": name,
        "description": description,
        "files": list(files.keys()),
        "created": _now(),
    }
    with open(os.path.join(project_dir, "project.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    return project_dir


@app.route("/project/generate", methods=["POST"])
def project_generate():
    """Generate a complete web project from a task description using Ollama.

    Body: {"model": "...", "prompt": "...", "name": "optional project name"}
    Returns: {"project_id": "...", "files": {"index.html": "...", ...}, "success": true}
    """
    body    = request.get_json(silent=True) or {}
    model   = body.get("model", "").strip()
    prompt  = body.get("prompt", "").strip()
    name    = body.get("name", "").strip() or prompt[:60]

    if not model:
        return jsonify({"error": "No model selected", "success": False})
    if not prompt:
        return jsonify({"error": "No prompt provided", "success": False})

    sys_prompt = (
        "You are an expert full-stack web developer. "
        "Generate a complete, self-contained, production-ready web application "
        "for the task described below. "
        "The application MUST be a single HTML file with all CSS and JavaScript inline. "
        "Use a dark, modern design with CSS variables, responsive layout (flexbox/grid), "
        "and smooth animations. Include all functionality described in the task. "
        "Return ONLY the complete HTML document inside a fenced ```html code block. "
        "Do not write anything outside that block.\n\n"
        f"Task: {prompt}"
    )

    try:
        resp = _http.post(
            f"{OLLAMA_BASE}/api/generate",
            json={"model": model, "prompt": sys_prompt, "stream": False},
            timeout=int(os.environ.get("OLLAMA_TIMEOUT", 240)),
        )
        resp.raise_for_status()
        raw  = resp.json().get("response", "")
        html = _extract_code_block(raw, "html")
        if not html:
            return jsonify({"error": "Model returned no HTML", "success": False})

        # Build file set
        files = {
            "index.html": html,
            "README.md": (
                f"# {name}\n\n"
                f"**Описание задачи:**\n\n{prompt}\n\n"
                f"**Сгенерировано:** {_now()}\n\n"
                f"**Модель:** {model}\n\n"
                "## Запуск\n\nОткройте `index.html` в браузере.\n"
            ),
        }

        project_id = f"{_slugify(name)}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        _save_project(project_id, name, prompt, files)
        _record_generation("html", model, prompt)

        return jsonify({
            "project_id": project_id,
            "name": name,
            "files": files,
            "success": True,
        })
    except _http.exceptions.Timeout:
        return jsonify({"error": "Request timed out", "success": False})
    except _http.exceptions.ConnectionError:
        return jsonify({"error": "Cannot connect to Ollama — is 'ollama serve' running?", "success": False})
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"error": str(exc), "success": False})


@app.route("/project/list", methods=["GET"])
def project_list():
    """Return metadata for all saved projects (most recent first)."""
    _ensure_projects_dir()
    projects = []
    try:
        for entry in os.scandir(PROJECTS_DIR):
            if not entry.is_dir():
                continue
            meta_path = os.path.join(entry.path, "project.json")
            if not os.path.exists(meta_path):
                continue
            try:
                with open(meta_path, "r", encoding="utf-8") as fh:
                    meta = json.load(fh)
                projects.append(meta)
            except (OSError, json.JSONDecodeError):
                pass
    except OSError:
        pass

    projects.sort(key=lambda p: p.get("created", ""), reverse=True)
    return jsonify({"projects": projects, "total": len(projects)})


@app.route("/project/<project_id>/<path:filename>", methods=["GET"])
def project_file(project_id: str, filename: str):
    """Serve a file from a saved project directory."""
    # Sanitise: only allow lowercase alphanumeric characters, underscores and hyphens
    if not re.match(r'^[a-z0-9_\-]+$', project_id):
        return jsonify({"error": "Invalid project ID. Only lowercase letters, digits, underscores and hyphens are allowed."}), 400
    project_dir = os.path.join(PROJECTS_DIR, project_id)
    if not os.path.isdir(project_dir):
        return jsonify({"error": "Project not found"}), 404
    # send_from_directory handles path traversal protection
    return send_from_directory(project_dir, filename)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys as _sys
    import traceback as _tb

    # When launched via pythonw.exe (no console) redirect all output to a log
    # file in the repo root so startup errors are always visible to the user.
    # The file handle is intentionally left open for the lifetime of the process
    # so Flask's own logging continues to go to the file.
    _repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _log_path = os.path.join(_repo_dir, "server.log")
    try:
        _log_fh = open(_log_path, "w", buffering=1, encoding="utf-8")
        _sys.stdout = _log_fh
        _sys.stderr = _log_fh
    except OSError as _e:
        # Can't open log — warn on original stderr then continue without logging
        print(f"[Code VM] Warning: cannot write server.log: {_e}", file=_sys.__stderr__)

    try:
        port = int(os.environ.get("VM_PORT", 5000))
        print(f"[Code VM] Starting on port {port} ...", flush=True)
        # Ensure instructions file is initialised before accepting requests
        load_instructions()
        print("[Code VM] Flask app starting.", flush=True)
        app.run(host="0.0.0.0", port=port, debug=False)
    except Exception:
        print(_tb.format_exc(), flush=True)
        raise
