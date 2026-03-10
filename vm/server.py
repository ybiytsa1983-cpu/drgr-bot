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
  GET  /selftest       — run built-in web-scraper self-test, return HTML report
  GET  /launch         — HTML page with emergency launch instructions for all platforms
  POST /retrain        — manually trigger a self-improvement cycle
  POST /agent/log      — receive action record from the Telegram bot for self-learning
  GET  /agent/stats    — return agent action statistics and current training instructions
  POST /agent/describe_image — describe an image using Ollama vision model
  GET  /convert/formats     — list available file conversion formats
  POST /convert/image       — convert image between formats (PNG/JPEG/WEBP/BMP) via Pillow
  POST /convert/text        — convert text between formats (JSON↔CSV, HTML→text, MD→HTML)
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

# Ollama service base URL (override via OLLAMA_HOST env var).
# Default is the standard Ollama port 11434; auto-discovery scans 11434-11444
# as a fallback, so non-standard ports still work automatically.
OLLAMA_BASE = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# Heartbeat configuration
_OLLAMA_HEARTBEAT_INTERVAL = 60   # seconds between liveness pings
_OLLAMA_HEARTBEAT_TIMEOUT  = 2    # seconds to wait for each Ollama response

# ---------------------------------------------------------------------------
# Ollama port auto-discovery
# ---------------------------------------------------------------------------
# Runs once in a background thread at startup.  First tries the configured
# OLLAMA_BASE URL; if unreachable, scans localhost ports 11434-11444 to
# find where Ollama is actually listening.  This handles users who run
# Ollama on a non-default port (e.g. 11435) even when the standard default
# port 11434 is used.
_OLLAMA_SCANNED = False
_OLLAMA_SCAN_LOCK = threading.Lock()


def _autodiscover_ollama() -> None:
    """Verify OLLAMA_BASE is reachable; if not, scan ports 11434-11444.

    Scans both 127.0.0.1 and localhost because on Windows, 'localhost' may
    resolve to ::1 (IPv6) while Ollama listens on 127.0.0.1 only.
    Checks HTTP 200 status to confirm it is actually Ollama (not some other
    service that happens to accept connections on the same port).
    """
    global OLLAMA_BASE, _OLLAMA_SCANNED
    with _OLLAMA_SCAN_LOCK:
        if _OLLAMA_SCANNED:
            return
        _OLLAMA_SCANNED = True
        # 1. Try the already-configured base URL first.
        try:
            r = _http.get(f"{OLLAMA_BASE}/api/tags", timeout=1)
            if r.status_code == 200:
                return  # configured URL is reachable — done
        except Exception:  # pylint: disable=broad-except
            pass
        # 2. Fall back: scan 127.0.0.1 first (avoids IPv6 issues on Windows),
        #    then localhost, on ports 11434-11444.
        for host in ("127.0.0.1", "localhost"):
            for port in range(11434, 11445):
                url = f"http://{host}:{port}"
                try:
                    r = _http.get(f"{url}/api/tags", timeout=1)
                    if r.status_code == 200:
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
            r = _http.get(f"{OLLAMA_BASE}/api/tags", timeout=_OLLAMA_HEARTBEAT_TIMEOUT)
            if r.status_code != 200:
                raise ValueError(f"Ollama returned HTTP {r.status_code}")
        except Exception:  # pylint: disable=broad-except
            # Ollama appears to be gone — allow a fresh scan
            with _OLLAMA_SCAN_LOCK:
                if _OLLAMA_SCANNED:
                    _OLLAMA_SCANNED = False
            _autodiscover_ollama()


threading.Thread(target=_ollama_heartbeat, daemon=True).start()

# Maximum number of prior chat turns to include in the /chat/stream context.
_MAX_CHAT_HISTORY_TURNS = 20

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


@app.route("/ping", methods=["GET"])
def ping():
    """Instant liveness probe — returns immediately without any external calls."""
    return jsonify({"ok": True})


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


# ---------------------------------------------------------------------------
# Self-test / demo endpoints
# ---------------------------------------------------------------------------

_SELFTEST_CODE = r'''
import threading, http.server, sqlite3, time, random, urllib.robotparser
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import requests as _req

# ── 1. Build a 3-page mock e-commerce catalogue in memory ──────────────────
PAGES = {}
PAGES["/robots.txt"] = b"User-agent: *\nDisallow: /private/\nAllow: /\n"

_STARS = ["One", "Two", "Three", "Four", "Five"]

def _book_card(bid, title, price_int, stars):
    return (
        f'<div class="product_pod">'
        f'<h3><a href="/product/{bid}" title="{title}">{title}</a></h3>'
        f'<p class="price_color">GBP{price_int:.2f}</p>'
        f'<p class="star-rating {stars}"></p>'
        f'</div>'
    )

p1_books = "".join(
    _book_card(i, f"Classic Novel {i} The Complete Edition", 10 + i,
               _STARS[i % 5])
    for i in range(1, 21)
)
p2_books = "".join(
    _book_card(i, f"Mystery Thriller {i} Detective Chronicles", 5 + i * 0.5,
               _STARS[(i + 2) % 5])
    for i in range(21, 36)
)

PAGES["/"] = (
    "<html><head><meta charset='utf-8'></head><body>"
    "<ul class='breadcrumb'><li>Home</li><li class='active'>Fiction</li></ul>"
    "<h1>Books Catalogue - Page 1</h1>"
    + p1_books +
    "<ul><li class='next'><a href='/catalogue/page-2.html'>next</a></li></ul>"
    "</body></html>"
).encode("utf-8")

PAGES["/catalogue/page-2.html"] = (
    "<html><head><meta charset='utf-8'></head><body>"
    "<ul class='breadcrumb'><li>Home</li><li class='active'>Mystery</li></ul>"
    "<h1>Books Catalogue - Page 2</h1>"
    + p2_books +
    "</body></html>"
).encode("utf-8")

class _MockHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        path = self.path.split("?")[0]
        body = PAGES.get(path, b"<h1>404</h1>")
        code = 200 if path in PAGES else 404
        self.send_response(code)
        ct = "text/plain" if path.endswith(".txt") else "text/html; charset=utf-8"
        self.send_header("Content-Type", ct)
        self.end_headers()
        self.wfile.write(body)

srv = http.server.HTTPServer(("127.0.0.1", 18081), _MockHandler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(0.2)

BASE = "http://127.0.0.1:18081"

# ── 2. Production-grade scraper ────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122",
    "Mozilla/5.0 (Macintosh) AppleWebKit/605.1.15 Safari/605",
    "Mozilla/5.0 (X11; Linux x86_64) Firefox/124",
]

conn = sqlite3.connect(":memory:")
conn.execute("""CREATE TABLE books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE, title TEXT, price REAL,
    rating TEXT, category TEXT, scraped_at TEXT
)""")
conn.execute("CREATE TABLE scrape_state (key TEXT PRIMARY KEY, value TEXT)")
conn.commit()

def save_book(url, title, price_str, rating, category):
    try:
        price = float(price_str.replace("GBP", "").replace(",", ".").strip())
    except Exception:
        price = 0.0
    conn.execute(
        "INSERT OR IGNORE INTO books(url,title,price,rating,category,scraped_at) VALUES(?,?,?,?,?,datetime('now'))",
        (url, title, price, rating, category))
    conn.commit()

# Check robots.txt
rp = urllib.robotparser.RobotFileParser()
rp.set_url(f"{BASE}/robots.txt")
rp.read()
allowed = rp.can_fetch("*", BASE + "/")

sess = _req.Session()

_MAX_BACKOFF = 8  # seconds — maximum exponential back-off wait for 429 responses

def fetch_with_backoff(url, attempt=0):
    hdr = {"User-Agent": random.choice(USER_AGENTS)}
    try:
        r = sess.get(url, headers=hdr, timeout=5)
        if r.status_code == 429 and attempt < 3:
            time.sleep(min(2 ** attempt + random.random(), _MAX_BACKOFF))
            return fetch_with_backoff(url, attempt + 1)
        r.raise_for_status()
        return r
    except _req.RequestException as exc:
        print(f"  [ERR] {exc}")
        return None

lines = [f"robots.txt: scraping {'ALLOWED' if allowed else 'DISALLOWED'}"]
to_visit = [BASE + "/"]
visited = set()
page_no = 0
MAX_PAGES = 3

while to_visit and page_no < MAX_PAGES:
    url = to_visit.pop(0)
    if url in visited:
        continue
    visited.add(url)
    # Resume support
    if conn.execute("SELECT 1 FROM scrape_state WHERE key=?", (url,)).fetchone():
        lines.append(f"[PAGE] {url} — SKIPPED (already scraped)")
        continue
    conn.execute("INSERT OR IGNORE INTO scrape_state VALUES(?,?)", (url, "done"))
    conn.commit()

    page_no += 1
    lines.append(f"\n[PAGE {page_no}] {url}")
    resp = fetch_with_backoff(url)
    if not resp:
        continue

    soup = BeautifulSoup(resp.content, "html.parser", from_encoding="utf-8")
    cat_el = soup.select_one(".breadcrumb .active")
    category = cat_el.get_text(strip=True) if cat_el else "Books"

    count = 0
    for article in soup.select("div.product_pod"):
        try:
            a     = article.select_one("h3 a")
            title = a["title"]
            href  = urljoin(url, a["href"])
            price = article.select_one(".price_color").get_text(strip=True)
            stars_el = article.select_one(".star-rating")
            rating   = stars_el["class"][1] if stars_el else "?"
            save_book(href, title, price, rating, category)
            count += 1
            lines.append(f"  BOOK  {title[:44]:<44} {price:>10}  *{rating}")
        except Exception as exc:
            lines.append(f"  SKIP  {exc}")

    lines.append(f"  -> {count} books saved from this page")
    nxt = soup.select_one("li.next a")
    if nxt:
        to_visit.append(urljoin(url, nxt["href"]))
    time.sleep(0.05)

# ── 3. Final statistics ───────────────────────────────────────────────────
total  = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
cats   = [r[0] for r in conn.execute("SELECT DISTINCT category FROM books")]
lines.append("\n=== SCRAPE RESULTS ===")
lines.append(f"Total books : {total}  (deduplicated via INSERT OR IGNORE)")
lines.append(f"Categories  : {', '.join(cats)}")

lines.append("\nCheapest 5:")
for r in conn.execute("SELECT title, price, rating FROM books ORDER BY price ASC LIMIT 5"):
    lines.append(f"  {r[0][:44]:<44} GBP{r[1]:<7.2f}  *{r[2]}")

lines.append("\nRating distribution:")
for r in conn.execute("SELECT rating, COUNT(*) n FROM books GROUP BY rating ORDER BY n DESC"):
    bar = "#" * r[1]
    lines.append(f"  {r[0]:<8} {bar} ({r[1]})")

lines.append("\nPrice stats:")
for r in conn.execute("SELECT MIN(price),MAX(price),AVG(price),SUM(price) FROM books"):
    lines.append(f"  Min=GBP{r[0]:.2f}  Max=GBP{r[1]:.2f}  Avg=GBP{r[2]:.2f}  Total=GBP{r[3]:.2f}")

srv.shutdown()
lines.append("\nSELFTEST PASSED")
print("\n".join(lines))
'''


@app.route("/selftest", methods=["GET"])
def selftest():
    """Run a built-in web-scraper self-test and return an HTML report.

    Spins up a local mock HTTP server with a 2-page book catalogue,
    scrapes it with all production features (robots.txt, User-Agent rotation,
    exponential backoff, SQLite dedup, pagination, resume support),
    and renders a nicely formatted HTML result page.

    No external network access is required.
    """
    import html as _html_mod

    result = _run_code(_SELFTEST_CODE, "python")
    success = result["success"]
    raw_out = result.get("output", "") or ""
    raw_err = result.get("error", "") or ""

    # Parse the plain-text output into an HTML report
    rows = []
    for line in (raw_out + ("\n" + raw_err if raw_err.strip() else "")).splitlines():
        stripped = line.strip()
        if stripped.startswith("BOOK"):
            css = "book"
        elif stripped.startswith("SKIP"):
            css = "skip"
        elif stripped.startswith("[PAGE"):
            css = "page"
        elif stripped.startswith("===") or stripped.startswith("SELFTEST"):
            css = "heading"
        elif stripped.startswith("->"):
            css = "summary"
        elif stripped.startswith("[ERR]"):
            css = "error"
        else:
            css = "info"
        rows.append(f'<div class="row {css}">{_html_mod.escape(line)}</div>')

    status_cls = "ok" if success else "fail"
    status_txt = "✅ SELFTEST PASSED" if success else "❌ SELFTEST FAILED"

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Code VM — Self-Test</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #1e1e1e; color: #d4d4d4; font-family: 'Consolas', monospace;
         font-size: 13px; padding: 20px; }}
  h1 {{ font-size: 22px; margin-bottom: 16px; color: #569cd6; }}
  .badge {{ display: inline-block; padding: 6px 18px; border-radius: 4px;
            font-size: 16px; font-weight: bold; margin-bottom: 20px; }}
  .badge.ok   {{ background: #1e4d2b; color: #4ec94e; border: 1px solid #4ec94e; }}
  .badge.fail {{ background: #4d1e1e; color: #f44747; border: 1px solid #f44747; }}
  .log {{ background: #252526; border: 1px solid #3c3c3c; border-radius: 4px;
          padding: 14px; overflow-x: auto; white-space: pre; line-height: 1.6; }}
  .row       {{ padding: 1px 0; }}
  .row.book  {{ color: #9cdcfe; }}
  .row.page  {{ color: #dcdcaa; font-weight: bold; margin-top: 8px; }}
  .row.skip  {{ color: #808080; }}
  .row.error {{ color: #f44747; }}
  .row.heading {{ color: #c586c0; font-weight: bold; margin-top: 10px; }}
  .row.summary {{ color: #4ec94e; }}
  .row.info  {{ color: #d4d4d4; }}
  .meta {{ color: #6a9955; font-size: 11px; margin-top: 16px; }}
  a {{ color: #569cd6; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<h1>⚡ Code VM — Self-Test: Web Scraper</h1>
<div class="badge {status_cls}">{status_txt}</div>
<p style="margin-bottom:14px;color:#858585">
  Спинит локальный mock HTTP-сервер с книжным каталогом из 2 страниц,
  скрапит его с проверкой robots.txt, ротацией User-Agent, SQLite dedup,
  пагинацией и поддержкой возобновления.
  Внешний интернет не нужен.
</p>
<div class="log">{"".join(rows)}</div>
<p class="meta">
  Endpoint: <code>GET /selftest</code> &nbsp;|&nbsp;
  <a href="/">← Вернуться в редактор</a> &nbsp;|&nbsp;
  <a href="/health">Статус системы</a>
</p>
</body>
</html>"""
    return Response(page, status=200 if success else 500,
                    mimetype="text/html; charset=utf-8")


@app.route("/launch", methods=["GET"])
def launch_help():
    """Return an HTML page with emergency launch instructions for all platforms."""
    page = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Code VM — Как запустить</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #1e1e1e; color: #d4d4d4; font-family: system-ui, sans-serif;
         font-size: 14px; padding: 20px; max-width: 820px; line-height: 1.7; }
  h1 { font-size: 24px; color: #569cd6; margin-bottom: 4px; }
  h2 { font-size: 16px; color: #dcdcaa; margin: 24px 0 8px; }
  .card { background: #252526; border: 1px solid #3c3c3c; border-radius: 6px;
          padding: 14px 18px; margin-bottom: 14px; }
  code, pre { background: #0d0d0d; color: #9cdcfe; padding: 3px 7px;
              border-radius: 3px; font-family: Consolas, monospace; font-size: 13px; }
  pre { display: block; padding: 12px; overflow-x: auto; white-space: pre; }
  .tag { display: inline-block; padding: 2px 8px; border-radius: 10px;
         font-size: 11px; font-weight: bold; margin-right: 6px; }
  .win  { background: #004d7a; color: #9cdcfe; }
  .lin  { background: #1e4d2b; color: #4ec94e; }
  .any  { background: #4d3800; color: #dcdcaa; }
  a { color: #569cd6; }
  .ok { color: #4ec94e; font-weight: bold; }
  .note { color: #858585; font-size: 12px; }
</style>
</head>
<body>
<h1>⚡ Code VM — Как запустить</h1>
<p style="color:#858585;margin-bottom:16px">Ты видишь эту страницу — значит сервер уже запущен! <span class="ok">✅</span></p>

<h2>🪟 Windows — один раз (установка + ярлык)</h2>
<div class="card">
<span class="tag win">Windows PowerShell</span>
<pre>$d="$env:USERPROFILE\\drgr-bot"; if(Test-Path $d){Set-Location $d; git pull}else{Set-Location "$env:USERPROFILE"; git clone https://github.com/ybiytsa1983-cpu/drgr-bot; Set-Location drgr-bot}; .\\install.ps1</pre>
<p class="note">Открой Win+X → Windows PowerShell, вставь всё сразу. Создаст ярлык «Code VM» на рабочем столе.</p>
</div>

<h2>🪟 Windows — повторный запуск (без ярлыка)</h2>
<div class="card">
<span class="tag win">PowerShell</span>
<pre>powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\\drgr-bot\\start.ps1"</pre>
<p class="note">Работает всегда, даже без ярлыка.</p>
</div>

<h2>🐧 Linux / macOS</h2>
<div class="card">
<span class="tag lin">bash</span>
<pre>cd ~/drgr-bot && ./start.sh</pre>
<p class="note">Первый раз установит зависимости автоматически (~1 минута).</p>
</div>

<h2>🌐 Любая платформа — прямой запуск Python</h2>
<div class="card">
<span class="tag any">любой терминал</span>
<pre>cd путь/к/drgr-bot/vm
pip install flask requests beautifulsoup4 python-dotenv
python server.py</pre>
<p class="note">Откройте браузер на <a href="http://localhost:5000/">http://localhost:5000/</a></p>
</div>

<h2>🧪 Проверить что VM работает</h2>
<div class="card">
  Открой в браузере: <a href="/selftest"><code>/selftest</code></a> — запустит встроенный тест веб-скрапера<br>
  Или: <a href="/health"><code>/health</code></a> — статус всех компонентов (VM, Ollama, Bot)<br>
  Или: <a href="/challenges"><code>/challenges</code></a> — список заданий для VM
</div>

<h2>❓ Нет файлов вообще</h2>
<div class="card">
<span class="tag win">PowerShell</span>
<pre>Set-Location "$env:USERPROFILE"
git clone https://github.com/ybiytsa1983-cpu/drgr-bot
Set-Location drgr-bot
.\\install.ps1</pre>
<p class="note">После клонирования и install.ps1 на рабочем столе появятся: «Code VM» (ярлык) и «ЗАПУСТИТЬ.bat»</p>
</div>

<p style="margin-top:24px"><a href="/">← Вернуться в редактор</a></p>
</body>
</html>"""
    return Response(page, status=200, mimetype="text/html; charset=utf-8")


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
    if "system_prompt" in body:
        data["system_prompt"] = body["system_prompt"]
    save_instructions(data)
    return jsonify({"success": True, "data": data})


# ---------------------------------------------------------------------------
# Settings (bot token, Ollama URL, etc.)
# ---------------------------------------------------------------------------
@app.route("/settings", methods=["GET"])
def get_settings():
    """Return current runtime settings so the UI can pre-fill fields.

    Triggers Ollama auto-discovery synchronously so the returned URL
    reflects the actual detected port (e.g. 11435) rather than the
    initial default value.
    """
    _autodiscover_ollama()  # ensure OLLAMA_BASE is up-to-date before responding

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
        if not bot_token_set and os.environ.get("BOT_TOKEN"):
            bot_token_set = True
    except Exception:  # pylint: disable=broad-except
        pass

    return jsonify({"ollama_url": OLLAMA_BASE, "bot_token_set": bot_token_set})


@app.route("/settings", methods=["POST"])
def save_settings():
    """Save settings (Telegram bot token, Ollama URL) to .env."""
    global OLLAMA_BASE, _OLLAMA_SCANNED  # noqa: PLW0603
    body = request.get_json(silent=True) or {}
    bot_token  = body.get("bot_token",  "").strip()
    ollama_url = body.get("ollama_url", "").strip()

    if not bot_token and not ollama_url:
        return jsonify({"ok": False, "error": "Nothing to save"})

    env_path = os.path.join(os.path.dirname(_DIR), ".env")

    # Read existing lines or start fresh
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    if bot_token:
        # Update or append BOT_TOKEN line
        token_found = False
        for i, line in enumerate(lines):
            if line.startswith("BOT_TOKEN="):
                lines[i] = f"BOT_TOKEN={bot_token}\n"
                token_found = True
                break
        if not token_found:
            lines.append(f"BOT_TOKEN={bot_token}\n")
        # Apply to current process so /health reflects the change immediately
        os.environ["BOT_TOKEN"] = bot_token

    if ollama_url:
        # Update or append OLLAMA_HOST line
        ollama_found = False
        for i, line in enumerate(lines):
            if line.startswith("OLLAMA_HOST="):
                lines[i] = f"OLLAMA_HOST={ollama_url}\n"
                ollama_found = True
                break
        if not ollama_found:
            lines.append(f"OLLAMA_HOST={ollama_url}\n")
        # Apply to current process immediately
        os.environ["OLLAMA_HOST"] = ollama_url
        OLLAMA_BASE = ollama_url
        # Allow auto-discovery to re-check with the new URL
        with _OLLAMA_SCAN_LOCK:
            _OLLAMA_SCANNED = False
        threading.Thread(target=_autodiscover_ollama, daemon=True).start()

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    return jsonify({"ok": True})



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


# Default Qwen-optimised system prompt used when instructions.json has none.
_DEFAULT_HTML_SYSTEM_PROMPT = (
    "Ты DRGR HTML Generator — экспертный веб-разработчик на базе Qwen.\n"
    "Генерируй красивые, полные, отзывчивые HTML страницы.\n"
    "ВСЕГДА возвращай один полный HTML файл (<!DOCTYPE html>...) "
    "со встроенным CSS и JavaScript.\n"
    "Используй современный CSS (flexbox/grid), красивые цвета, плавные анимации.\n"
    "НЕ подключай внешние зависимости без необходимости.\n"
    "Выводи ТОЛЬКО HTML код без пояснений и комментариев вне кода."
)


@app.route("/generate/html/stream", methods=["POST"])
def generate_html_stream():
    """Stream a complete HTML page from a natural-language description using Qwen/Ollama.

    Body: {"prompt": "...", "model": "..."}
    Streams SSE tokens ending with data: [DONE]
    The accumulated text is the raw Qwen output; the client strips the code fence.
    """
    body  = request.get_json(silent=True) or {}
    model = body.get("model", "").strip()
    prompt = body.get("prompt", "").strip()

    if not model:
        def _no_model():
            yield 'data: {"error":"Модель не выбрана — выберите модель в настройках (☰)"}\n\n'
        return Response(stream_with_context(_no_model()), mimetype="text/event-stream")

    if not prompt:
        def _no_prompt():
            yield 'data: {"error":"Введите описание страницы"}\n\n'
        return Response(stream_with_context(_no_prompt()), mimetype="text/event-stream")

    # Load custom system prompt; fall back to Qwen default
    data = load_instructions()
    sys_prompt = data.get("system_prompt", "").strip() or _DEFAULT_HTML_SYSTEM_PROMPT

    full_prompt = f"{sys_prompt}\n\nЗадание: {prompt}"

    def _stream():
        try:
            resp = _http.post(
                f"{OLLAMA_BASE}/api/generate",
                json={"model": model, "prompt": full_prompt, "stream": True},
                stream=True,
                timeout=int(os.environ.get("OLLAMA_TIMEOUT", 240)),
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
                    _record_generation("html", model, prompt)
                    yield "data: [DONE]\n\n"
                    return
        except _http.exceptions.ConnectionError:
            yield 'data: {"error":"Нет соединения с Ollama — запустите \'ollama serve\'"}\n\n'
        except Exception as exc:  # pylint: disable=broad-except
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return Response(
        stream_with_context(_stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Simple chat endpoint — plain text conversation with Ollama (no HTML wrapping)
# ---------------------------------------------------------------------------
@app.route("/chat/stream", methods=["POST"])
def chat_stream():
    """Stream a plain chat response from Ollama.

    Body: {"message": "...", "model": "...", "history": [...optional chat history...]}
    Streams SSE tokens ending with data: [DONE]
    Unlike /generate/html/stream this returns raw model text without any
    HTML-generation system prompt so it works for any question.
    """
    body    = request.get_json(silent=True) or {}
    model   = body.get("model", "").strip()
    message = body.get("message", "").strip()
    history = body.get("history", [])  # list of {"role": "user"|"assistant", "text": "..."}

    if not model:
        def _no_model():
            yield 'data: {"error":"Модель не выбрана — выберите модель в настройках (☰)"}\n\n'
        return Response(stream_with_context(_no_model()), mimetype="text/event-stream")

    if not message:
        def _no_msg():
            yield 'data: {"error":"Введите сообщение"}\n\n'
        return Response(stream_with_context(_no_msg()), mimetype="text/event-stream")

    # Build a prompt with chat history context
    lines = []
    for entry in history[-_MAX_CHAT_HISTORY_TURNS:]:  # keep last N turns to avoid context overflow
        role = entry.get("role", "user")
        text = entry.get("text", "").strip()
        if text:
            lines.append(f"{'Пользователь' if role == 'user' else 'Ассистент'}: {text}")
    lines.append(f"Пользователь: {message}")
    lines.append("Ассистент:")
    full_prompt = "\n".join(lines)

    def _stream():
        try:
            resp = _http.post(
                f"{OLLAMA_BASE}/api/generate",
                json={"model": model, "prompt": full_prompt, "stream": True},
                stream=True,
                timeout=int(os.environ.get("OLLAMA_TIMEOUT", 240)),
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
            yield 'data: {"error":"Нет соединения с Ollama — запустите \'ollama serve\'"}\n\n'
        except Exception as exc:  # pylint: disable=broad-except
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return Response(
        stream_with_context(_stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
# File Converter — image and text format conversions
# ---------------------------------------------------------------------------

_IMAGE_FORMATS = ("png", "jpeg", "bmp", "webp")
_IMAGE_FMT_ALIAS = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "bmp": "bmp", "webp": "webp"}
_TEXT_CONVERSIONS = [
    {"from": "json", "to": "csv",  "description": "JSON array of objects → CSV"},
    {"from": "csv",  "to": "json", "description": "CSV → JSON array of objects"},
    {"from": "html", "to": "text", "description": "HTML → plain text (strips tags)"},
    {"from": "markdown", "to": "html", "description": "Markdown → HTML"},
]


def _md_inline(text: str) -> str:
    """Convert inline Markdown (bold, italic, code, links) to HTML."""
    import html as _html_mod
    text = _html_mod.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__(.+?)__",     r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*",     r"<em>\1</em>",         text)
    text = re.sub(r"_(.+?)_",       r"<em>\1</em>",         text)
    text = re.sub(r"`(.+?)`",       r"<code>\1</code>",     text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


@app.route("/convert/formats", methods=["GET"])
def convert_formats():
    """List available conversion formats and supported conversions."""
    return jsonify({
        "image": {
            "from": list(_IMAGE_FMT_ALIAS.keys()),
            "to":   list(_IMAGE_FORMATS),
            "note": "Uses Pillow. JPEG/BMP do not support transparency — white background used.",
        },
        "text": {
            "conversions": _TEXT_CONVERSIONS,
        },
    })


@app.route("/convert/image", methods=["POST"])
def convert_image():
    """Convert an image between formats using Pillow.

    Body (one of):
      {"image_base64": "<base64>", "to_format": "jpeg", "quality": 85}
      {"image_path":  "/abs/path/img.png", "to_format": "webp", "quality": 90}

    Returns:
      {"result_base64": "...", "format": "jpeg", "size_bytes": N,
       "dimensions": "1920x1080", "success": true}
    """
    import base64 as _b64
    import io as _io

    body        = request.get_json(silent=True) or {}
    to_format   = _IMAGE_FMT_ALIAS.get(body.get("to_format", "jpeg").lower().lstrip("."), "")
    quality     = min(max(int(body.get("quality", 85)), 1), 100)

    if not to_format:
        return jsonify({
            "error": f"Unsupported target format. Supported: {', '.join(_IMAGE_FORMATS)}",
            "success": False,
        }), 400

    image_base64 = body.get("image_base64", "").strip()
    image_path   = body.get("image_path",   "").strip()

    if image_base64:
        try:
            img_bytes = _b64.b64decode(image_base64)
        except Exception:
            return jsonify({"error": "Invalid base64 data", "success": False}), 400
    elif image_path:
        if not os.path.isabs(image_path):
            return jsonify({"error": "image_path must be absolute", "success": False}), 400
        if not os.path.exists(image_path):
            return jsonify({"error": f"File not found: {image_path}", "success": False}), 404
        with open(image_path, "rb") as fh:
            img_bytes = fh.read()
    else:
        return jsonify({"error": "Provide image_base64 or image_path", "success": False}), 400

    try:
        from PIL import Image  # pillow is in requirements.txt

        buf_in = _io.BytesIO(img_bytes)
        img    = Image.open(buf_in)
        img.load()  # eagerly decode so errors surface here

        # JPEG and BMP don't support alpha — composite onto white background
        if to_format in ("jpeg", "bmp") and img.mode in ("RGBA", "LA", "P"):
            if img.mode == "P":
                img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode in ("RGBA", "LA"):
                bg.paste(img, mask=img.split()[-1])
            else:
                bg.paste(img)
            img = bg
        elif img.mode not in ("RGB", "RGBA", "L") and to_format != "png":
            img = img.convert("RGB")

        buf_out     = _io.BytesIO()
        save_kwargs = {}
        if to_format == "jpeg":
            save_kwargs = {"quality": quality, "optimize": True}
        elif to_format == "webp":
            save_kwargs = {"quality": quality}

        img.save(buf_out, format=to_format.upper(), **save_kwargs)
        result_b64 = _b64.b64encode(buf_out.getvalue()).decode()

        return jsonify({
            "result_base64": result_b64,
            "format":        to_format,
            "size_bytes":    len(buf_out.getvalue()),
            "dimensions":    f"{img.width}x{img.height}",
            "success":       True,
        })

    except ImportError:
        return jsonify({"error": "Pillow not installed. Run: pip install pillow", "success": False}), 500
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"error": str(exc), "success": False}), 500


@app.route("/convert/text", methods=["POST"])
def convert_text():
    """Convert text content between formats.

    Supported conversions:
      json     → csv   (expects JSON array of objects)
      csv      → json  (returns JSON array of objects)
      html/htm → text  (strips tags, returns plain text)
      md/markdown → html (basic Markdown → HTML)

    Body: {"content": "...", "from_format": "json", "to_format": "csv"}
    Returns: {"result": "...", "success": true}
    """
    import csv as _csv
    import html as _html_mod
    import io as _io

    body     = request.get_json(silent=True) or {}
    content  = body.get("content", "")
    from_fmt = body.get("from_format", "").lower().strip()
    to_fmt   = body.get("to_format",   "").lower().strip()

    if not content:
        return jsonify({"error": "No content provided", "success": False}), 400
    if not from_fmt or not to_fmt:
        return jsonify({"error": "Provide from_format and to_format", "success": False}), 400

    try:
        result = ""

        # ── JSON → CSV ────────────────────────────────────────────────────────
        if from_fmt == "json" and to_fmt == "csv":
            data = json.loads(content)
            if not isinstance(data, list):
                data = [data]
            if not data:
                return jsonify({"result": "", "success": True})
            keys = list(data[0].keys()) if isinstance(data[0], dict) else ["value"]
            buf  = _io.StringIO()
            writer = _csv.DictWriter(buf, fieldnames=keys, extrasaction="ignore")
            writer.writeheader()
            for row in data:
                writer.writerow(row if isinstance(row, dict) else {"value": str(row)})
            result = buf.getvalue()

        # ── CSV → JSON ────────────────────────────────────────────────────────
        elif from_fmt == "csv" and to_fmt == "json":
            buf    = _io.StringIO(content)
            reader = _csv.DictReader(buf)
            result = json.dumps(list(reader), ensure_ascii=False, indent=2)

        # ── HTML → plain text ─────────────────────────────────────────────────
        elif from_fmt in ("html", "htm") and to_fmt == "text":
            try:
                from bs4 import BeautifulSoup
                result = BeautifulSoup(content, "html.parser").get_text(separator="\n", strip=True)
            except ImportError:
                result = _html_mod.unescape(re.sub(r"<[^>]+>", "", content))

        # ── Markdown → HTML ───────────────────────────────────────────────────
        elif from_fmt in ("md", "markdown") and to_fmt in ("html", "htm"):
            lines, html_lines, in_code = content.splitlines(), [], False
            for line in lines:
                if line.startswith("```"):
                    if in_code:
                        html_lines.append("</code></pre>")
                        in_code = False
                    else:
                        lang_hint = line[3:].strip()
                        # Whitelist: only allow safe language identifier characters
                        lang_hint = re.sub(r"[^a-zA-Z0-9_+\-]", "", lang_hint)[:32]
                        html_lines.append(f'<pre><code class="language-{lang_hint}">')
                        in_code = True
                    continue
                if in_code:
                    html_lines.append(_html_mod.escape(line))
                    continue
                m = re.match(r"^(#{1,6})\s+(.*)", line)
                if m:
                    lvl = len(m.group(1))
                    html_lines.append(f"<h{lvl}>{_md_inline(m.group(2))}</h{lvl}>")
                    continue
                if re.match(r"^[-*_]{3,}$", line.strip()):
                    html_lines.append("<hr>")
                    continue
                if not line.strip():
                    html_lines.append("")
                    continue
                m = re.match(r"^[\-*]\s+(.*)", line)
                if m:
                    html_lines.append(f"<li>{_md_inline(m.group(1))}</li>")
                    continue
                html_lines.append(f"<p>{_md_inline(line)}</p>")
            result = "\n".join(html_lines)

        else:
            return jsonify({
                "error": f"Unsupported conversion: {from_fmt} → {to_fmt}",
                "supported": [f"{c['from']} → {c['to']}" for c in _TEXT_CONVERSIONS],
                "success": False,
            }), 400

        return jsonify({"result": result, "success": True})

    except (json.JSONDecodeError, _csv.Error) as exc:
        return jsonify({"error": f"Parse error: {exc}", "success": False}), 400
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"error": str(exc), "success": False}), 500


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
