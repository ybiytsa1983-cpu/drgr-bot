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
  POST /ollama/create-visor-vm — create drgr-visor (retrained qwen3-vl:8b for ВИЗОР+Monaco)
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
  POST /agent/describe_image   — describe an image using Ollama vision model
  POST /agent/generate_image   — generate an image via local SD (port 7860) or ComfyUI (port 8188); handler for GENERATE_IMAGE agent command
  POST /visor/watch    — SSE: continuously screenshot a URL and report AI-detected changes
  GET  /convert/formats     — list available file conversion formats
  POST /convert/image       — convert image between formats (PNG/JPEG/WEBP/BMP) via Pillow
  POST /convert/text        — convert text between formats (JSON↔CSV, HTML→text, MD→HTML)
  POST /browse/screenshot   — screenshot a URL and analyse with qwen3-vl / drgr-visor
  POST /browse/agent/run    — SSE: run autonomous DRGRBrowserAgent loop for a task
  POST /patch/stream        — stream edited code (patch existing code based on user request)
  POST /project/generate    — generate a full web project from a task description and save to disk
  GET  /project/list        — list all saved projects (metadata, most recent first)
  GET  /project/<id>/<file> — serve a file from a saved project directory
  POST /project/save        — save current editor content as a named project file on disk
  DELETE /project/<id>      — delete a saved project directory
"""

import ast
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import queue
import threading
import time
import urllib.parse
import uuid
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
from flask import Flask, Response, jsonify, redirect, request, send_from_directory, stream_with_context

app = Flask(__name__, static_folder="static")
_log = logging.getLogger("CodeVM")


@app.errorhandler(Exception)
def _handle_unhandled_exception(exc):
    """Return a JSON error response for any unhandled exception so the frontend
    never receives an HTML 500 page that would cause JSON.parse to fail."""
    _log.exception("Unhandled exception in request: %s", exc)
    return jsonify({"ok": False, "error": str(exc)}), 500

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
_OLLAMA_DEFAULT_BASE = "http://localhost:11434"
_ollama_host_raw = os.environ.get("OLLAMA_HOST", "").rstrip("/")
if _ollama_host_raw and not _ollama_host_raw.startswith(("http://", "https://")):
    _ollama_host_raw = "http://" + _ollama_host_raw
OLLAMA_BASE = _ollama_host_raw or _OLLAMA_DEFAULT_BASE

# LM Studio service base URL (OpenAI-compatible API).
# Override via LM_STUDIO_URL env var or the settings panel.
# LM Studio typically runs on port 1234 and exposes /v1/models, /v1/chat/completions etc.
LM_STUDIO_BASE = os.environ.get("LM_STUDIO_URL", "").rstrip("/")
# Prefix used in model selector to distinguish LM Studio models from Ollama ones.
_LM_STUDIO_PREFIX = "lmstudio:"

# text-generation-webui (oobabooga) base URL — OpenAI-compatible API.
# Override via TGWUI_URL env var or the settings panel.
# Typically runs on port 5000 with --api flag and exposes /v1/models, /v1/chat/completions.
TGWUI_BASE = os.environ.get("TGWUI_URL", "").rstrip("/")
_TGWUI_PREFIX = "tgwui:"

# Roo Code (https://github.com/RooCodeInc/Roo-Code) base URL — OpenAI-compatible API.
# Roo Code is a VS Code AI coding assistant that forwards requests to any OpenAI-compatible
# backend (Ollama, LM Studio, OpenRouter, etc.).  Point this URL at the same server Roo Code
# is configured to use (e.g. http://127.0.0.1:1234 for LM Studio, http://127.0.0.1:11434 for
# Ollama via its OpenAI-compat layer).  Models are shown with the prefix "roo:".
ROO_CODE_BASE = os.environ.get("ROO_CODE_URL", "").rstrip("/")
_ROO_CODE_PREFIX = "roo:"

# Open Agentic Framework base URL — multi-agent orchestrator.
# Override via OAF_URL env var or the settings panel.
OAF_BASE = os.environ.get("OAF_URL", "").rstrip("/")

# TripoSR / Hunyuan3D / local 3D generation service base URL.
# The service should expose POST /generate accepting {"prompt": "...", "image_base64": "..."}
# and returning {"ok": True, "model_url": "<url or base64>"}.
# Override via TRIPOSR_URL env var or the settings panel.
TRIPOSR_BASE = os.environ.get("TRIPOSR_URL", "").rstrip("/")

# AI website builder service base URL (build-a-site / AI-Website-Builder style).
# Should expose POST /generate accepting {"prompt": "..."} and returning {"ok": True, "html": "..."}.
# Override via WEBBUILDER_URL env var or the settings panel.
WEBBUILDER_BASE = os.environ.get("WEBBUILDER_URL", "").rstrip("/")

# Video editor project service base URL (omniclip / twick style).
# Should expose POST /project accepting {"script": "...", "files": [...]} and returning {"ok": True, ...}.
# Override via VIDEDITOR_URL env var or the settings panel.
VIDEDITOR_BASE = os.environ.get("VIDEDITOR_URL", "").rstrip("/")

# Remote VM URL — URL of an externally hosted VM (e.g. Google Colab via ngrok).
# When set, the /remote/proxy endpoint forwards requests there.
REMOTE_VM_URL = os.environ.get("REMOTE_VM_URL", "").rstrip("/")
# Timestamp (time.time()) of the last successful POST /api/colab/register call.
# 0.0 means never seen.
REMOTE_VM_LAST_SEEN: float = 0.0

# Vision VM URL — URL of a dedicated vision-capable Ollama instance (e.g. a
# second Ollama with llava or minicpm-v loaded).  When set and online, all
# vision requests are routed here automatically, effectively "disconnecting"
# the primary VM's vision capability in favour of the dedicated one.
VISION_VM_URL = os.environ.get("VISION_VM_URL", "").rstrip("/")
# Prefix used in model names to indicate the model lives on the Vision VM.
_VISION_VM_PREFIX = "visionvm:"

# Stable Diffusion (AUTOMATIC1111 / SD.Next) and ComfyUI base URLs.
# These are module-level so they can be updated live via /settings.
# Defaults read from environment; can be changed without restart through the UI.
SD_BASE = os.environ.get("SD_API_URL", "http://127.0.0.1:7860").rstrip("/")
COMFYUI_BASE = os.environ.get("COMFYUI_API_URL", "http://127.0.0.1:8188").rstrip("/")

# BOT_VM — which AI backend the Telegram bot should prefer for chat requests.
# Values: "auto" (default — use whatever is available), "ollama", "lmstudio", "tgwui", "remote"
# Can be changed live via /settings without restarting the bot.
BOT_VM: str = os.environ.get("BOT_VM", "auto").strip().lower() or "auto"

# BOT_MODEL — pin a specific model for the Telegram bot (e.g. "llama3:8b", "lmstudio:mistral").
# Empty string means "auto" — use whatever get_best_model() returns.
BOT_MODEL: str = os.environ.get("BOT_MODEL", "").strip()

# Sources that produce poor screenshots (JS-heavy, login walls, etc.)
_EXCLUDED_SCREENSHOT_SOURCES = frozenset({"reddit", "hackernews"})

# Regex to extract a YouTube video ID from a URL (watch?v=, youtu.be/, embed/)
_YT_VIDEO_ID_RE = re.compile(
    r'(?:youtube\.com/watch\?[^"\'>\s]*v=|youtu\.be/|youtube\.com/embed/)([A-Za-z0-9_-]{11})'
)

# LM Studio streaming timeout — long-running generations can exceed 4 minutes.
# Override via LMS_TIMEOUT env var (seconds).  Falls back to OLLAMA_TIMEOUT if
# that is set, otherwise defaults to 600 (10 minutes).
try:
    _LMS_TIMEOUT = int(
        os.environ.get(
            "LMS_TIMEOUT",
            os.environ.get("OLLAMA_TIMEOUT", 600),
        )
    )
except ValueError as _e:
    raise ValueError(
        f"Invalid LMS_TIMEOUT or OLLAMA_TIMEOUT environment variable: {_e}"
    ) from _e

# CORS relay port — a lightweight HTTP server on this port proxies /api/*
# requests to OLLAMA_BASE with permissive CORS headers so Chrome extensions
# (sidepanel, content scripts) can call Ollama directly from the browser
# without running into CORS restrictions.
# Default: 11435  (Ollama default is 11434; +1 keeps it easy to remember).
# Override via env var: OLLAMA_RELAY_PORT=0 to disable.
_OLLAMA_RELAY_PORT = int(os.environ.get("OLLAMA_RELAY_PORT", 11435))

# ---------------------------------------------------------------------------
# Remote VM polling job queue
# ---------------------------------------------------------------------------
# Jobs are stored here so a Colab notebook can poll /remote/jobs/pending
# and POST results back — no ngrok tunnel required on the local side.
_remote_jobs: "dict[str, dict]" = {}   # job_id -> job dict
_remote_jobs_lock = threading.Lock()

# Lock protecting LM_STUDIO_BASE auto-discovery updates.
_LMS_DISCOVER_LOCK = threading.Lock()

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

# Track liveness transitions so we can auto-restart Ollama when it crashes.
_OLLAMA_ALIVE = False          # True once Ollama responded at least once
_OLLAMA_ALIVE_LOCK = threading.Lock()
_OLLAMA_PROC: "subprocess.Popen | None" = None   # handle for auto-restarted Ollama

# Seconds to wait after restarting Ollama before re-probing ports
_OLLAMA_RESTART_WAIT = 5

# One-liner update command shown in crash warnings
_UPDATE_CMD_URL = (
    "try { irm https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/update.ps1 | iex }"
    " catch { irm https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/copilot/create-monaco-code-generator/update.ps1 | iex }"
)


def _resolve_lms_url() -> str:
    """Return a working LM Studio base URL.

    First tries the configured LM_STUDIO_BASE.  If it is unreachable or not
    set, scans common local/LAN addresses and updates the global so subsequent
    calls use the discovered address automatically.  Thread-safe: URL update
    is protected by _LMS_DISCOVER_LOCK.
    """
    global LM_STUDIO_BASE  # noqa: PLW0603
    # Quick probe of the current base (if set) — read without lock
    _current = LM_STUDIO_BASE
    if _current:
        try:
            r = _http.get(f"{_current}/v1/models", timeout=3)
            if r.status_code == 200:
                return _current
        except Exception:  # pylint: disable=broad-except
            pass
    # Configured URL unreachable — scan well-known addresses under lock so only
    # one thread performs discovery at a time.
    with _LMS_DISCOVER_LOCK:
        # Re-check after acquiring the lock: another thread may have updated it.
        _current = LM_STUDIO_BASE
        if _current:
            try:
                r = _http.get(f"{_current}/v1/models", timeout=3)
                if r.status_code == 200:
                    return _current
            except Exception:  # pylint: disable=broad-except
                pass
        for _host in ("127.0.0.1", "localhost", "172.22.208.1", "172.22.0.1"):
            for _port in (1234, 1235, 8080, 11434, 8000):
                _url = f"http://{_host}:{_port}"
                if _url == _current:
                    continue  # already failed above
                try:
                    _r = _http.get(f"{_url}/v1/models", timeout=1)
                    if _r.status_code == 200:
                        LM_STUDIO_BASE = _url
                        return _url
                except Exception:  # pylint: disable=broad-except
                    continue
    return LM_STUDIO_BASE  # return original even if unreachable


def _find_ollama_exe() -> "str | None":
    """Return the path to ollama.exe (Windows) or 'ollama' (Unix) if installed."""
    import shutil as _shutil
    if _shutil.which("ollama"):
        return "ollama"
    # Windows common install paths
    candidates = []
    local_app = os.environ.get("LOCALAPPDATA", "")
    user_profile = os.environ.get("USERPROFILE", "")
    if local_app:
        candidates.append(os.path.join(local_app, "Programs", "Ollama", "ollama.exe"))
    if user_profile:
        candidates.append(os.path.join(user_profile, "AppData", "Local", "Programs", "Ollama", "ollama.exe"))
    candidates += [
        r"C:\Program Files\Ollama\ollama.exe",
        r"C:\Program Files (x86)\Ollama\ollama.exe",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _restart_ollama() -> bool:
    """Try to restart Ollama via 'ollama serve'.  Returns True if started."""
    global _OLLAMA_PROC  # noqa: PLW0603
    # If a previously restarted Ollama is still running, don't spawn another.
    if _OLLAMA_PROC is not None and _OLLAMA_PROC.poll() is None:
        return True  # already restarting
    exe = _find_ollama_exe()
    if not exe:
        return False
    try:
        _OLLAMA_PROC = subprocess.Popen(
            [exe, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        print(
            f"[Code VM] Ollama crashed — restarted via 'ollama serve'. "
            f"To update: {_UPDATE_CMD_URL}",
            flush=True,
        )
        return True
    except Exception as exc:  # pylint: disable=broad-except
        print(f"[Code VM] Could not restart Ollama: {exc}", flush=True)
        return False


def _autodiscover_ollama() -> None:
    """Verify OLLAMA_BASE is reachable; if not, scan ports 11434-11444.

    Scans both 127.0.0.1 and localhost because on Windows, 'localhost' may
    resolve to ::1 (IPv6) while Ollama listens on 127.0.0.1 only.
    Checks HTTP 200 status to confirm it is actually Ollama (not some other
    service that happens to accept connections on the same port).
    """
    global OLLAMA_BASE, _OLLAMA_SCANNED, _OLLAMA_ALIVE  # noqa: PLW0603
    with _OLLAMA_SCAN_LOCK:
        if _OLLAMA_SCANNED:
            return
        _OLLAMA_SCANNED = True
        _default_base = _OLLAMA_DEFAULT_BASE

        def _accept(url: str) -> None:
            """Mark url as the live Ollama endpoint."""
            global OLLAMA_BASE, _OLLAMA_ALIVE  # noqa: PLW0603
            prev = OLLAMA_BASE
            OLLAMA_BASE = url
            with _OLLAMA_ALIVE_LOCK:
                _OLLAMA_ALIVE = True  # type: ignore[assignment]
            if url != prev:
                print(f"[Code VM] Ollama обнаружена на {url} (было: {prev})", flush=True)
            elif url != _default_base:
                print(
                    f"[Code VM] Ollama найдена по адресу {url} "
                    f"(нестандартный порт — сохраните в настройках: OLLAMA_HOST={url})",
                    flush=True,
                )

        # 1. Try the already-configured base URL first.
        try:
            r = _http.get(f"{OLLAMA_BASE}/api/tags", timeout=1)
            if r.status_code == 200:
                _accept(OLLAMA_BASE)
                return  # configured URL is reachable — done
        except Exception:  # pylint: disable=broad-except
            pass

        # 1b. On Windows, 'localhost' may resolve to ::1 (IPv6) while Ollama
        #     listens on 127.0.0.1 only — or vice versa.  Try the IPv4/name
        #     equivalent of the configured URL immediately so the very first
        #     /health call after startup already sees Ollama as available.
        if "localhost" in OLLAMA_BASE:
            _alt = OLLAMA_BASE.replace("localhost", "127.0.0.1")
            try:
                r = _http.get(f"{_alt}/api/tags", timeout=1)
                if r.status_code == 200:
                    _accept(_alt)
                    return
            except Exception:  # pylint: disable=broad-except
                pass
        elif "127.0.0.1" in OLLAMA_BASE:
            _alt = OLLAMA_BASE.replace("127.0.0.1", "localhost")
            try:
                r = _http.get(f"{_alt}/api/tags", timeout=1)
                if r.status_code == 200:
                    _accept(_alt)
                    return
            except Exception:  # pylint: disable=broad-except
                pass

        # 2. Fall back: scan 127.0.0.1 first (avoids IPv6 issues on Windows),
        #    then localhost, on ports 11434-11444.
        #    Skip _OLLAMA_RELAY_PORT to avoid mistaking our own CORS relay for
        #    an Ollama instance (which would cause infinite proxy loops).
        for host in ("127.0.0.1", "localhost"):
            for port in range(11434, 11445):
                if port == _OLLAMA_RELAY_PORT:
                    continue  # never treat our own CORS relay as Ollama
                url = f"http://{host}:{port}"
                try:
                    r = _http.get(f"{url}/api/tags", timeout=1)
                    if r.status_code == 200:
                        _accept(url)
                        return
                except Exception:  # pylint: disable=broad-except
                    continue


# Kick off discovery immediately so it's done before the first browser request
threading.Thread(target=_autodiscover_ollama, daemon=True).start()


def _ollama_heartbeat() -> None:
    """Background thread: re-check Ollama every 60 s and re-discover if lost.

    This ensures the VM always picks up Ollama even when it starts or restarts
    after the VM is already running — without requiring the browser to be open.
    When a crash is detected (was alive → now unreachable), Ollama is restarted
    automatically via 'ollama serve'.
    """
    global _OLLAMA_ALIVE  # noqa: PLW0603
    while True:
        time.sleep(_OLLAMA_HEARTBEAT_INTERVAL)
        alive_now = False
        try:
            r = _http.get(f"{OLLAMA_BASE}/api/tags", timeout=_OLLAMA_HEARTBEAT_TIMEOUT)
            if r.status_code != 200:
                raise ValueError(f"Ollama returned HTTP {r.status_code}")
            alive_now = True
        except Exception:  # pylint: disable=broad-except
            pass

        with _OLLAMA_ALIVE_LOCK:
            was_alive = _OLLAMA_ALIVE
            _OLLAMA_ALIVE = alive_now

        if alive_now:
            # Ollama is healthy — nothing to do
            pass
        else:
            if was_alive:
                # Transition alive → dead: Ollama likely crashed
                print(
                    "[Code VM] WARNING: Ollama stopped responding — attempting auto-restart.\n"
                    f"  If the problem persists, update drgr-bot:\n"
                    f"    {_UPDATE_CMD_URL}\n"
                    "  Or use /update in the Telegram bot.",
                    flush=True,
                )
                restarted = _restart_ollama()
                if restarted:
                    # Give Ollama a moment to initialise before re-scanning
                    time.sleep(_OLLAMA_RESTART_WAIT)
            # Allow a fresh port scan regardless of restart success
            with _OLLAMA_SCAN_LOCK:
                if _OLLAMA_SCANNED:
                    _OLLAMA_SCANNED = False
            _autodiscover_ollama()
            # Update alive flag if Ollama came back
            try:
                r = _http.get(f"{OLLAMA_BASE}/api/tags", timeout=_OLLAMA_HEARTBEAT_TIMEOUT)
                if r.status_code == 200:
                    with _OLLAMA_ALIVE_LOCK:
                        _OLLAMA_ALIVE = True
            except Exception:  # pylint: disable=broad-except
                pass


threading.Thread(target=_ollama_heartbeat, daemon=True).start()


# ---------------------------------------------------------------------------
# LM Studio auto-discovery and heartbeat
# ---------------------------------------------------------------------------
_LMS_HEARTBEAT_INTERVAL = 60      # seconds between LM Studio liveness probes
_LMS_HEALTH_CHECK_TIMEOUT = 3     # seconds for heartbeat /v1/models probe


def _autodiscover_lms() -> None:
    """Run once at startup in a background thread to discover LM Studio.

    Calls _resolve_lms_url() which scans common local/LAN addresses and
    updates LM_STUDIO_BASE so it is available before the first browser request.
    """
    _resolve_lms_url()


def _lms_heartbeat() -> None:
    """Background thread: re-check LM Studio every 60 s and re-discover if lost.

    This ensures LM_STUDIO_BASE stays up-to-date when LM Studio restarts,
    moves to a different port, or becomes temporarily unreachable.
    """
    while True:
        if not LM_STUDIO_BASE:
            # Not configured yet — try to discover
            _resolve_lms_url()
        else:
            try:
                r = _http.get(f"{LM_STUDIO_BASE}/v1/models", timeout=_LMS_HEALTH_CHECK_TIMEOUT)
                if r.status_code != 200:
                    raise ValueError(f"LM Studio returned HTTP {r.status_code}")
            except Exception:  # pylint: disable=broad-except
                # Lost connection — attempt re-discovery silently
                _resolve_lms_url()
        time.sleep(_LMS_HEARTBEAT_INTERVAL)


# Kick off LM Studio discovery at startup and keep it alive in background
threading.Thread(target=_autodiscover_lms, daemon=True).start()
threading.Thread(target=_lms_heartbeat, daemon=True).start()


# ---------------------------------------------------------------------------
# Ollama CORS relay  (port 11435 by default)
# ---------------------------------------------------------------------------
# A minimal HTTP proxy that runs on _OLLAMA_RELAY_PORT.
# It forwards /api/chat, /api/generate, /api/tags … to OLLAMA_BASE
# and adds Access-Control-Allow-Origin: * to every response.
#
# Chrome extensions (sidepanel, content scripts) cannot call Ollama at
# localhost:11434 directly because Chrome blocks mixed-content / CORS for
# extension pages that have no declared host_permissions for that origin.
# The relay lives at http://127.0.0.1:11435 and the extension declares
# host_permissions for THAT origin — so the request succeeds.
# ---------------------------------------------------------------------------
def _start_ollama_cors_relay() -> None:
    """Start a CORS-aware HTTP proxy for Ollama on _OLLAMA_RELAY_PORT."""
    if _OLLAMA_RELAY_PORT == 0:
        return  # disabled by user
    # If OLLAMA_BASE itself uses the relay port (e.g. user set OLLAMA_HOST=...:11435
    # and Ollama really is there), starting the relay on that port would either
    # fail (port taken) or create an infinite forwarding loop.  Skip the relay.
    try:
        from urllib.parse import urlparse as _urlparse_relay
        _relay_base_port = _urlparse_relay(OLLAMA_BASE).port
        if _relay_base_port == _OLLAMA_RELAY_PORT:
            print(
                f"[Code VM] Ollama CORS relay disabled: OLLAMA_BASE ({OLLAMA_BASE}) "
                f"already uses port {_OLLAMA_RELAY_PORT} — relay would loop.",
                flush=True,
            )
            return
    except Exception:  # pylint: disable=broad-except
        pass
    import http.server as _hs
    import socketserver as _ss
    import urllib.request as _ur
    import urllib.error as _ue

    _ollama_relay_timeout = int(os.environ.get("OLLAMA_TIMEOUT", 240))

    class _RelayHandler(_hs.BaseHTTPRequestHandler):
        def log_message(self, _fmt, *_args):  # suppress access log
            pass

        def _send_cors_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers",
                "Content-Type, Authorization, Accept",
            )

        def do_OPTIONS(self) -> None:          # pre-flight
            self.send_response(204)
            self._send_cors_headers()
            self.end_headers()

        def do_GET(self) -> None:
            target = f"{OLLAMA_BASE}{self.path}"
            try:
                req = _ur.Request(target, headers={"Accept": "application/json"})
                with _ur.urlopen(req, timeout=5) as resp:
                    data = resp.read()
                    ct = resp.headers.get("Content-Type", "application/json")
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(data)
            except _ue.URLError as exc:
                err = json.dumps({"error": str(exc)}).encode()
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(err)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length > 0 else b""
            target = f"{OLLAMA_BASE}{self.path}"
            try:
                req = _ur.Request(
                    target,
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with _ur.urlopen(req, timeout=_ollama_relay_timeout) as resp:
                    ct = resp.headers.get("Content-Type", "application/json")
                    self.send_response(200)
                    self.send_header("Content-Type", ct)
                    self._send_cors_headers()
                    self.end_headers()
                    # Stream chunks as they arrive so /api/chat stream works
                    while True:
                        chunk = resp.read(4096)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
            except _ue.URLError as exc:
                err = json.dumps({"error": str(exc)}).encode()
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(err)
            except Exception as exc:  # pylint: disable=broad-except
                err = json.dumps({"error": str(exc)}).encode()
                try:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self._send_cors_headers()
                    self.end_headers()
                    self.wfile.write(err)
                except Exception:  # pylint: disable=broad-except
                    pass

    class _ThreadingServer(_ss.ThreadingMixIn, _ss.TCPServer):
        allow_reuse_address = True
        daemon_threads = True

    try:
        relay_server = _ThreadingServer(("0.0.0.0", _OLLAMA_RELAY_PORT), _RelayHandler)
        print(
            f"[Code VM] Ollama CORS relay started on 0.0.0.0:{_OLLAMA_RELAY_PORT}"
            " — Chrome extensions and LAN devices can call Ollama through this address.",
            flush=True,
        )
        relay_server.serve_forever()
    except OSError as exc:
        print(
            f"[Code VM] Could not start Ollama CORS relay on port {_OLLAMA_RELAY_PORT}: {exc}"
            " — Chrome extensions may encounter CORS errors when calling Ollama.",
            flush=True,
        )


threading.Thread(target=_start_ollama_cors_relay, daemon=True).start()


# ---------------------------------------------------------------------------
# Remote Colab VM heartbeat poller
# ---------------------------------------------------------------------------
_COLAB_POLL_INTERVAL = 30  # seconds between remote VM /api/status probes


def _colab_vm_poller() -> None:
    """Background thread: every 30 s ping the registered Colab VM /api/status.

    This keeps the server aware of the remote VM's liveness even between
    explicit /api/colab/register heartbeats from the Colab side.
    """
    while True:
        time.sleep(_COLAB_POLL_INTERVAL)
        if REMOTE_VM_URL:
            try:
                _http.get(f"{REMOTE_VM_URL}/api/status", timeout=5)
            except Exception:  # pylint: disable=broad-except
                pass


threading.Thread(target=_colab_vm_poller, daemon=True).start()


# server.py manages the lifecycle of bot.py so that saving a new token via
# POST /settings immediately restarts the bot with the updated credential.

_bot_proc: "subprocess.Popen | None" = None
_bot_proc_lock = threading.Lock()

_BOT_PY = os.path.join(os.path.dirname(_DIR), "bot.py")
_BOT_TOKEN_PLACEHOLDER = "your_telegram_bot_token_here"


def _get_saved_token() -> str:
    """Return BOT_TOKEN from .env in repo root, or '' if not set."""
    env_path = os.path.join(os.path.dirname(_DIR), ".env")
    try:
        with open(env_path, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("BOT_TOKEN="):
                    val = line[len("BOT_TOKEN="):].strip()
                    if val and val != _BOT_TOKEN_PLACEHOLDER:
                        return val
    except OSError:
        pass
    return os.environ.get("BOT_TOKEN", "")


def _stop_bot() -> None:
    """Kill the managed bot subprocess (if running)."""
    global _bot_proc  # noqa: PLW0603
    with _bot_proc_lock:
        if _bot_proc is not None:
            try:
                _bot_proc.terminate()
                try:
                    _bot_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    _bot_proc.kill()
            except OSError:
                pass
            _bot_proc = None


def _start_bot(token: str = "") -> bool:
    """Start (or restart) bot.py with the given token.

    If *token* is empty, reads from .env.  Returns True if the process
    was launched successfully, False otherwise.
    """
    global _bot_proc  # noqa: PLW0603

    if not os.path.isfile(_BOT_PY):
        _log.warning("bot.py not found at %s — skipping bot start", _BOT_PY)
        return False

    if not token:
        token = _get_saved_token()
    if not token:
        _log.info("BOT_TOKEN not set — bot will not start")
        return False

    _stop_bot()

    env = os.environ.copy()
    env["BOT_TOKEN"] = token

    # Determine log file path for bot output (repo root / bot.log)
    bot_log_path = os.path.join(os.path.dirname(_DIR), "bot.log")
    try:
        bot_log_fh = open(bot_log_path, "a", encoding="utf-8")  # noqa: SIM115, WPS515
    except OSError:
        bot_log_fh = subprocess.DEVNULL  # type: ignore[assignment]

    try:
        with _bot_proc_lock:
            _bot_proc = subprocess.Popen(  # noqa: S603
                [sys.executable, _BOT_PY],
                env=env,
                cwd=os.path.dirname(_DIR),
                stdout=bot_log_fh,
                stderr=bot_log_fh,
            )
        _log.info("Bot started (PID %s)", _bot_proc.pid)
        return True
    except OSError as exc:
        _log.error("Failed to start bot.py: %s", exc)
        return False


def _bot_monitor() -> None:
    """Background thread: restart the bot if it exits unexpectedly."""
    while True:
        time.sleep(10)
        with _bot_proc_lock:
            proc = _bot_proc
        if proc is not None and proc.poll() is not None:
            # Process exited — restart only if we still have a valid token
            token = _get_saved_token()
            if token:
                _log.warning("Bot exited (rc=%s) — restarting", proc.returncode)
                _start_bot(token)


threading.Thread(target=_bot_monitor, daemon=True).start()

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
        "total_projects_saved": 0,
        "failed_actions": 0,
        "retrain_cycles": 0,
        "popular_queries": {},          # query -> count
        "screenshot_failed_domains": {},  # domain -> fail_count
        "avg_sources_per_query": 0.0,
        "screenshot_success_rate": 1.0,
        "image_descriptions": [],       # last 50 AI descriptions (for training)
        "article_topics": [],           # last 50 article titles
        "saved_projects": [],           # last 100 saved project names
        "actions_since_last_retrain": 0,
    },
    # ── Browser-agent specification ───────────────────────────────────────────
    # Autonomous browser-control protocol used by the DRGR visor agent.
    # Stored here so the model can learn the command schema and improve
    # its browser-automation suggestions over time.
    "browser_agent_instructions": {
        "agent": {
            "name": "DRGRBrowserAgent",
            "version": "1.0",
            "description": (
                "Autonomous agent controlling the browser through the DRGR visor "
                "in multiple steps: observe → plan → act → verify → log."
            ),
            "capabilities": [
                "Multi-tab management via visor",
                "URL navigation",
                "Element search and click",
                "Text input into fields",
                "Page scroll",
                "Wait for DOM/URL changes",
                "Basic captcha and modal detection",
                "React to page errors and unexpected behaviour",
                "Image generation via local Stable Diffusion or ComfyUI (GENERATE_IMAGE command)",
            ],
            "constraints": [
                "Do not execute arbitrary system code outside the browser",
                "Do not attempt to bypass captchas — only report them",
                "Respect the cycle step limit",
                "All actions only through formalised commands",
                "For image generation tasks always use GENERATE_IMAGE — never return NOOP",
            ],
        },
        "cycle": {
            "max_steps": 80,
            "default_wait_timeout_ms": 8000,
            "commands": [
                "NAVIGATE", "CLICK", "TYPE", "WAIT", "SWITCH_TAB",
                "SCROLL", "SCREENSHOT", "GENERATE_IMAGE", "NOOP",
            ],
            "termination_conditions": [
                "Goal achieved",
                "Captcha detected (status=blocked_captcha)",
                "Critical HTTP error or ban",
                "Step limit exceeded (current_step >= max_steps)",
                "User explicitly stopped execution",
            ],
        },
        "command_schemas": {
            "GENERATE_IMAGE": {
                "description": (
                    "Generate an image via the local Stable Diffusion or ComfyUI API "
                    "(POST /agent/generate_image on the DRGR VM server). "
                    "Always use this command for any image-generation request — "
                    "NEVER respond with NOOP for image tasks."
                ),
                "fields": {
                    "prompt":          "Text description of the image to generate (required).",
                    "negative_prompt": "What to exclude from the image (optional, default empty).",
                    "width":           "Image width in pixels (optional, default 512).",
                    "height":          "Image height in pixels (optional, default 512).",
                    "steps":           "Diffusion steps (optional, default 20).",
                    "cfg_scale":       "CFG guidance scale (optional, default 7).",
                    "save_as":         "Filename to save result as (optional).",
                },
                "example": {
                    "type":            "GENERATE_IMAGE",
                    "prompt":          "A futuristic city at night with neon lights",
                    "negative_prompt": "blurry, low quality",
                    "width":           512,
                    "height":          512,
                    "steps":           25,
                },
            },
        },
        "output_schema": {
            "cycle_state": {
                "status": "running | finished_success | finished_error | blocked_captcha | user_input_required",
                "current_step": "number",
                "max_steps": "number",
            },
            "thoughts": {
                "observation": "Brief description of what the agent sees now.",
                "state_analysis": "What is happening: login, redirect, error, form, captcha, modal.",
                "plan_short": "Next step or short sequence of actions (1-3 steps).",
                "risks": "Possible problems: captcha, ban, wrong input, infinite redirect.",
            },
        },
        "special_states": {
            "captcha": "Set status=blocked_captcha, take SCREENSHOT, do not attempt to solve.",
            "modal_cookies": "Try CLICK on Accept/OK to close.",
            "error_page": "Log in state_analysis; stop or correct plan; set finished_error if critical.",
            "image_generation": (
                "Use GENERATE_IMAGE command with prompt, negative_prompt, width, height, steps. "
                "The server calls the local Stable Diffusion / ComfyUI API and returns the result. "
                "Do NOT navigate to external image sites — always prefer the local GENERATE_IMAGE command."
            ),
        },
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
                    data = json.load(fh)
                # Back-fill any keys added after the file was first created
                # (e.g. browser_agent_instructions added in a later version).
                for key, default_val in _DEFAULT_INSTRUCTIONS.items():
                    if key not in data:
                        data[key] = _deep_copy(default_val) if isinstance(default_val, (dict, list)) else default_val
                return data
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
# Number of characters to inspect when detecting HTML content masquerading as
# another language.  120 chars is enough for "<!DOCTYPE html>" plus whitespace.
_HTML_DETECT_PREFIX = 120


def _is_html_content(code: str) -> bool:
    """Return True if code looks like an HTML document (not JS or Python)."""
    prefix = code.strip()[:_HTML_DETECT_PREFIX].lower()
    return prefix.startswith("<") or "<!doctype" in prefix


# Patterns that indicate code uses Chrome-extension or browser-extension APIs
# that cannot run in plain Node.js
_BROWSER_EXT_PATTERNS = re.compile(
    r"""
    # chrome.<any-identifier> (dot notation) — catches ALL Chrome Extension APIs,
    # including sidePanel, offscreen, declarativeNetRequest, webNavigation, etc.
    \bchrome\s*\.\s*[a-zA-Z_][a-zA-Z0-9_]*\b
    |
    # chrome['property'] or chrome["property"] (bracket notation)
    \bchrome\s*\[\s*['"][a-zA-Z_][a-zA-Z0-9_]*['"]\s*\]
    |
    # typeof chrome (existence check in browser extension code)
    \btypeof\s+chrome\b
    |
    # if (chrome) / if (!chrome) bare standalone reference
    \bif\s*\(\s*!?\s*chrome\s*[).\[&|!]
    |
    # browser.* WebExtensions API (Firefox extensions)
    \bbrowser\s*\.\s*(?:storage|runtime|tabs|windows|bookmarks|history|
        cookies|permissions|management|extension|alarms|notifications|
        sidebarAction|menus|commands|webNavigation|webRequest|
        declarativeNetRequest|scripting|action|browserAction)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _is_browser_extension_code(code: str) -> bool:
    """Return True if code uses Chrome/browser extension APIs not available in Node.js."""
    return bool(_BROWSER_EXT_PATTERNS.search(code))


# Regex that matches a *closed* JavaScript regex literal on a single line:
#   /pattern/flags   (flags are optional; only valid flag chars allowed)
# Used to distinguish a real regex from a bare URL-path like /site or /api/v1.
_JS_CLOSED_REGEX_RE = re.compile(
    r"^/[^/\n]+/[gimsuy]{0,6}\s*(?:[;,\)\]}\n]|$)"
)


def _js_code_starts_with_bare_slash(code: str) -> str:
    """Return the offending first line if *code* starts with an unterminated
    regex literal (e.g. '/site', '/api/v1'), or an empty string if the code
    is fine.  A valid '/pattern/flags' regex or a '//' / '/*' comment is
    considered fine.
    """
    stripped = code.lstrip()
    if not stripped.startswith("/"):
        return ""
    if stripped.startswith(("//", "/*")):
        return ""
    first_line = stripped.split("\n")[0].strip()
    if _JS_CLOSED_REGEX_RE.match(first_line):
        return ""
    return first_line


# Words that strongly suggest the content is a human-readable prose description
# rather than JavaScript / TypeScript source code.
_PROSE_START_WORDS = frozenset({
    "the", "this", "a", "an", "it", "its", "is", "are", "was", "were",
    "i", "we", "you", "he", "she", "they",
    "note", "description", "overview", "summary", "introduction",
    "here", "below", "above",
    # Russian
    "это", "этот", "данный", "данная", "модель", "система",
    "программа", "приложение", "файл", "скрипт", "код",
    "добавьте", "создайте", "напишите", "реализуйте",
})

_PROSE_SENTENCE_RE = re.compile(
    r"^[A-ZА-ЯЁ][a-zA-Zа-яА-ЯёЁ\s,\.\!\?\-\–\—\«\»\"\']{40,}$",
    re.MULTILINE,
)


def _is_prose_text(code: str) -> bool:
    """Return True when *code* looks like plain prose text rather than
    executable JavaScript / TypeScript.

    Heuristics (all must pass — we want low false-positive rate):
    1. First non-empty word (lowercased) is in the known prose-starter list, OR
       the first non-empty line looks like a natural-language sentence.
    2. The snippet has no common JS keywords / punctuation at all.
    3. The snippet has at least 3 prose-like sentences.
    """
    stripped = code.strip()
    if not stripped:
        return False

    # Quick-exit: if there's any obvious JS syntax, it's probably code
    _js_signals = (
        "function ", "const ", "let ", "var ", "=>", "require(", "import ",
        "export ", "class ", "return ", "console.", "module.", "async ",
        "await ", "new ", "if (", "for (", "while (", "try {", "catch (",
        "===", "!==", "&&", "||", "null", "undefined", "true", "false",
        "0x", ".js", ".ts",
    )
    for sig in _js_signals:
        if sig in stripped:
            return False

    first_line = stripped.split("\n")[0].strip()
    first_word = first_line.split()[0].lower().rstrip(",:;.") if first_line.split() else ""

    # Condition 1 — first word is a known prose starter
    starts_like_prose = first_word in _PROSE_START_WORDS

    # Condition 2 — first line looks like a natural-language sentence
    # (starts with uppercase, contains spaces, no code punctuation)
    sentence_like = bool(
        first_line
        and first_line[0].isupper()
        and " " in first_line
        and not any(c in first_line for c in ("{", "}", "(", ")", "[", "]", ";", "=", ":"))
    )

    if not (starts_like_prose or sentence_like):
        return False

    # Condition 3 — multiple prose-like lines / sentences
    prose_lines = sum(1 for ln in stripped.splitlines() if _PROSE_SENTENCE_RE.match(ln.strip()))
    return prose_lines >= 2


def _sanitize_exec_output(text: str, tmp_path: str) -> str:
    """Replace the temporary file path in execution output with '<code>'.

    This makes error tracebacks user-friendly by hiding internal temp file
    names like /tmp/tmpXXX.py or C:\\Users\\...\\AppData\\Local\\Temp\\tmpXXX.py.
    The full path, its forward-slash normalised variant, and the bare basename
    are all replaced so no internal path leaks through in any error format.
    """
    if not tmp_path or not text:
        return text
    # Replace the exact path as returned by the OS
    cleaned = text.replace(tmp_path, "<code>")
    # Also replace the forward-slash normalised version (Python on Windows
    # sometimes emits paths with '/' even when the OS uses '\')
    normalised = tmp_path.replace("\\", "/")
    if normalised != tmp_path:
        cleaned = cleaned.replace(normalised, "<code>")
    # Also replace the bare filename (basename) in case only the filename
    # appears in an error message without the directory prefix.
    # Use a cross-platform split that recognises both '/' and '\'.
    basename = normalised.rsplit("/", 1)[-1]
    if basename:
        cleaned = cleaned.replace(basename, "<code>")
    return cleaned


_RUNNERS = {
    # Use sys.executable so user code runs in the same venv as the server and
    # has access to all installed packages (flask, requests, aiogram, etc.).
    "python": [sys.executable],
    "javascript": ["node", "--no-warnings"],
    "shell": ["bash"],
    "bash": ["bash"],
    # Prefer node --experimental-strip-types (Node 22+); fallback to npx ts-node
    "typescript": ["node", "--no-warnings", "--experimental-strip-types"],
}

# Fallback runtimes tried when the primary runner is not found.
# Key = primary executable name (runner[0]); value = fallback command list.
_RUNNER_FALLBACKS = {
    "bash": ["sh"],
}

# Languages handled entirely in-process (no subprocess needed).
_INPROCESS_RUNNERS = {"json", "xml", "html", "markdown", "css", "sql",
                      "plaintext", "text"}


def _run_typescript(code: str) -> dict:
    """Execute TypeScript code using the best available runtime.

    Tries runtimes in order:
    1. node --experimental-strip-types  (Node 22+, built-in TS support)
    2. npx ts-node --transpile-only --skip-project  (requires ts-node install)
    3. Regex type-stripping + plain node  (last resort for simple TS files)
    """
    # Guard: bare slash at start (e.g. /site) would cause a Node.js regex error
    _bad_line = _js_code_starts_with_bare_slash(code)
    if _bad_line:
        return {
            "output": "",
            "error": (
                f"SyntaxError: Строка 1 «{_bad_line[:80]}» начинается с «/» — "
                "это URL-путь, а не TypeScript-код."
            ),
            "success": False,
        }

    tmp_ts = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".ts", mode="w", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(code)
            tmp_ts = tmp.name

        def _run(cmd: list) -> dict:
            proc = subprocess.run(
                cmd + [tmp_ts],
                capture_output=True, text=True, timeout=10,
                cwd=tempfile.gettempdir(),
            )
            stdout = _sanitize_exec_output(proc.stdout, tmp_ts)
            stderr = _sanitize_exec_output(proc.stderr, tmp_ts)
            return {
                "output": stdout[:4096],
                "stdout": stdout[:4096],
                "error": stderr[:2048],
                "stderr": stderr[:2048],
                "success": proc.returncode == 0,
            }

        # 1. Try node --experimental-strip-types (Node 22+)
        try:
            result = _run(["node", "--no-warnings", "--experimental-strip-types"])
            if result["success"] or (
                result["error"] and
                "--experimental-strip-types" not in result["error"] and
                "unknown" not in result["error"].lower() and
                "unrecognized" not in result["error"].lower()
            ):
                return result
        except FileNotFoundError:
            pass

        # 2. Try npx ts-node --transpile-only --skip-project
        try:
            result = _run(["npx", "--yes", "ts-node",
                           "--transpile-only", "--skip-project"])
            if result["success"] or (
                result["error"] and
                "Cannot find module" not in result["error"] and
                "ts-node" not in result["error"].lower().split("\n")[0]
            ):
                return result
        except FileNotFoundError:
            pass

        # 3. Regex type-stripping + plain node (last resort)
        ts_stripped = re.sub(
            r'\binterface\s+\w+[^{]*\{[^}]*\}', '', code, flags=re.DOTALL)
        ts_stripped = re.sub(
            r'\btype\s+\w+\s*=\s*[^\n;]+[;\n]', '', ts_stripped)
        # Remove return type annotations: ): ReturnType => / ): ReturnType {
        ts_stripped = re.sub(
            r'\)\s*:\s*(?:string|number|boolean|void|any|never|unknown|object'
            r'|undefined|bigint|symbol|Promise|[A-Z]\w*)(?:\[\])?'
            r'(?:\s*\|[^{=,;\n]+)?(?=\s*[\{=])',
            ')', ts_stripped)
        # Remove parameter/variable type annotations: name: TypeName
        ts_stripped = re.sub(
            r':\s*(?:string|number|boolean|void|any|never|unknown|object'
            r'|undefined|bigint|symbol|null|[A-Z]\w*)(?:\[\])?'
            r'(?:\s*(?:\||\&)\s*(?:string|number|boolean|null|undefined|[A-Z]\w*)(?:\[\])?)*'
            r'(?=\s*[,)=;\n])',
            '', ts_stripped)
        # Remove generic type params from function calls: fn<Type>(...)
        ts_stripped = re.sub(r'<[A-Z]\w*(?:,\s*\w+)*>', '', ts_stripped)

        js_path = tmp_ts.replace('.ts', '_stripped.js')
        try:
            with open(js_path, 'w', encoding='utf-8') as jf:
                jf.write(ts_stripped)
            try:
                proc = subprocess.run(
                    ['node', '--no-warnings', js_path],
                    capture_output=True, text=True, timeout=10,
                    cwd=tempfile.gettempdir())
                stdout = _sanitize_exec_output(proc.stdout, js_path)
                stdout = _sanitize_exec_output(stdout, tmp_ts)
                stderr = _sanitize_exec_output(proc.stderr, js_path)
                stderr = _sanitize_exec_output(stderr, tmp_ts)
                return {
                    "output": stdout[:4096],
                    "stdout": stdout[:4096],
                    "error": stderr[:2048],
                    "stderr": stderr[:2048],
                    "success": proc.returncode == 0,
                }
            except FileNotFoundError:
                pass
        finally:
            if os.path.exists(js_path):
                os.unlink(js_path)

        return {
            "output": "",
            "error": (
                "TypeScript runtime not found. "
                "Установите Node.js 22+ или ts-node: npm install -g ts-node typescript"
            ),
            "success": False,
        }
    except subprocess.TimeoutExpired:
        return {"output": "", "error": "Execution timed out (10 s limit)", "success": False}
    except Exception as exc:  # pylint: disable=broad-except
        return {"output": "", "error": str(exc), "success": False}
    finally:
        if tmp_ts and os.path.exists(tmp_ts):
            os.unlink(tmp_ts)


def _run_code(code: str, language: str) -> dict:
    # Handle languages that don't require execution
    if language in _INPROCESS_RUNNERS:
        if language == "json":
            try:
                parsed = json.loads(code)
                formatted = json.dumps(parsed, ensure_ascii=False, indent=2)
                return {"output": formatted, "error": "", "success": True,
                        "stdout": formatted, "stderr": ""}
            except json.JSONDecodeError as exc:
                return {"output": "", "error": f"JSON error: {exc}", "success": False,
                        "stdout": "", "stderr": f"JSON error: {exc}"}
        # For html/css/markdown/sql/plaintext — just echo the content
        return {"output": code, "error": "", "success": True, "stdout": code, "stderr": ""}

    runner = _RUNNERS.get(language)
    if runner is None:
        return {"output": "", "error": f"Unsupported language: {language}", "success": False}

    # TypeScript has its own multi-step runner
    if language == "typescript":
        return _run_typescript(code)

    # Guard: if JavaScript code is actually HTML, refuse execution with a clear message
    if language == "javascript" and _is_html_content(code):
        return {
            "output": "",
            "error": (
                "Обнаружен HTML вместо JavaScript. "
                "Выберите язык 'html' или используйте ```html блок."
            ),
            "success": False,
        }

    # Guard: code whose first non-blank line starts with a bare '/' (not '//' or
    # '/*') is almost certainly a URL path accidentally extracted as JavaScript
    # (e.g. '/site', '/api/endpoint').  Node.js tries to parse it as a regex
    # literal and immediately throws:
    #   SyntaxError: Invalid regular expression: missing /
    # Detect this early and return a clear, actionable error instead of the
    # cryptic Node.js message.
    if language == "javascript":
        _bad_first = _js_code_starts_with_bare_slash(code)
        if _bad_first:
            return {
                "output": "",
                "error": (
                    f"SyntaxError: Строка 1 «{_bad_first[:80]}» начинается с «/» — "
                    "это похоже на URL-путь, а не на JavaScript-код.\n"
                    "Node.js интерпретирует «/...» как незакрытое регулярное выражение "
                    "и выбрасывает «Invalid regular expression: missing /».\n\n"
                    "Что делать:\n"
                    "  • Убедитесь, что в редакторе JavaScript-код, а не URL-адрес.\n"
                    "  • Если вы хотели сгенерировать JS, нажмите «▶ Сгенерировать» "
                    "с описанием задачи."
                ),
                "success": False,
            }

    # Guard: manifest.json content should not be executed as JavaScript
    if language in ("javascript", "typescript") and re.search(r'"manifest_version"\s*:', code):
        return {
            "output": "",
            "error": (
                "⛔ Это файл manifest.json Chrome Extension — его нельзя запускать как JavaScript.\n"
                "manifest.json — это конфигурационный JSON-файл для расширения браузера.\n\n"
                "Что делать:\n"
                "  1. Скачайте расширение как ZIP: нажмите '📦 ZIP' в менеджере проектов\n"
                "  2. Установите через chrome://extensions/ → Режим разработчика → "
                "Загрузить распакованное расширение\n"
                "  3. Смените язык на JSON кнопкой ⟨/⟩ или выпадающим списком языка"
            ),
            "success": False,
        }

    # Guard: browser/Chrome-extension APIs don't exist in Node.js
    if language in ("javascript", "typescript") and _is_browser_extension_code(code):
        return {
            "output": "",
            "error": (
                "⛔ Код использует Chrome Extension API (chrome.storage, chrome.runtime и т.д.), "
                "которые недоступны в Node.js.\n"
                "Этот код является расширением для браузера — его нельзя запустить через Node.js.\n\n"
                "Решения:\n"
                "  1. Нажмите '▶ Сгенерировать' и попросите:\n"
                "     «Перепиши без chrome.* API — только Node.js (fs, path, os, crypto)»\n"
                "  2. Если это Chrome Extension — упакуйте как расширение:\n"
                "     создайте manifest.json + popup.html и загрузите через chrome://extensions/\n"
                "  3. Для визуализации в браузере — попросите сгенерировать HTML-файл\n"
                "  4. Используйте кнопку '🌐 Открыть' для просмотра HTML-версии в браузере"
            ),
            "success": False,
        }

    # Guard: plain prose text (e.g. a model description or README) is not JS
    if language in ("javascript", "typescript") and _is_prose_text(code):
        first_line = code.strip().splitlines()[0][:80] if code.strip() else ""
        return {
            "output": "",
            "error": (
                f"⛔ Содержимое редактора выглядит как текст, а не как JavaScript-код.\n"
                f"Первая строка: «{first_line}»\n\n"
                "Node.js не может выполнить обычный текст — он ожидает JavaScript-код.\n\n"
                "Что делать:\n"
                "  1. Нажмите '▶ Сгенерировать' и опишите задачу на русском или английском —\n"
                "     ИИ напишет готовый JavaScript-код.\n"
                "  2. Если хотите запустить Python — выберите язык 'Python' в выпадающем списке.\n"
                "  3. Если хотите отобразить текст — выберите язык 'plaintext' или 'markdown'."
            ),
            "success": False,
        }

    _suffix_map = {
        "python": ".py",
        "javascript": ".js",
        "typescript": ".ts",
        "shell": ".sh",
        "bash": ".sh",
    }
    suffix = _suffix_map.get(language, ".txt")
    tmp_path = None

    def _exec(cmd: list) -> dict:
        proc = subprocess.run(
            cmd + [tmp_path],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=tempfile.gettempdir(),
        )
        stdout = _sanitize_exec_output(proc.stdout, tmp_path)
        stderr = _sanitize_exec_output(proc.stderr, tmp_path)
        return {
            "output": stdout[:4096],
            "stdout": stdout[:4096],
            "error": stderr[:2048],
            "stderr": stderr[:2048],
            "success": proc.returncode == 0,
        }

    try:
        with tempfile.NamedTemporaryFile(
            suffix=suffix, mode="w", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(code)
            tmp_path = tmp.name

        try:
            return _exec(runner)
        except FileNotFoundError:
            # Try fallback runtime (e.g. "python" when "python3" is missing)
            fallback = _RUNNER_FALLBACKS.get(runner[0])
            if fallback:
                try:
                    return _exec(fallback)
                except FileNotFoundError:
                    pass
            # Ultimate fallback for Python: use the same interpreter that runs
            # this server (guaranteed to be available regardless of PATH).
            if language == "python":
                try:
                    return _exec([sys.executable])
                except FileNotFoundError:
                    pass
            return {
                "output": "",
                "error": f"Runtime not found: {runner[0]}",
                "success": False,
            }
    except subprocess.TimeoutExpired:
        return {"output": "", "error": "Execution timed out (10 s limit)", "success": False}
    except Exception as exc:  # pylint: disable=broad-except
        return {"output": "", "error": str(exc), "success": False}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Code checking
# ---------------------------------------------------------------------------

def _fix_aiogram_decorators(code: str) -> str:
    """Auto-fix aiogram 3.x decorator argument ordering.

    Python requires positional arguments before keyword arguments.
    In aiogram 3.x decorators like @router.message() and
    @router.callback_query(), filter objects (F.text, Command(...) etc.)
    are positional args, while state= is a keyword arg.

    This function reorders them so positional filters come first.
    Example fix:
      @router.message(state=S.foo, F.text.startswith('/x'))
      → @router.message(F.text.startswith('/x'), state=S.foo)
    """
    import tokenize as _tok
    import io as _io

    _DECO_NAME_RE = re.compile(r"^(?:router|dp)\.\w+$")

    try:
        tokens = list(_tok.generate_tokens(_io.StringIO(code).readline))
    except _tok.TokenError:
        return code  # unparseable — leave unchanged

    src_lines = code.splitlines(keepends=True)

    def _offset(line: int, col: int) -> int:
        return sum(len(src_lines[ln]) for ln in range(line - 1)) + col

    replacements: list[tuple[int, int, str]] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        # Look for '@' that starts a decorator
        if tok.type != _tok.OP or tok.string != "@":
            i += 1
            continue

        # Collect name tokens up to '('
        j = i + 1
        name_parts: list[str] = []
        while j < len(tokens):
            t = tokens[j]
            if t.type == _tok.NAME:
                name_parts.append(t.string)
                j += 1
            elif t.type == _tok.OP and t.string == ".":
                name_parts.append(".")
                j += 1
            elif t.type == _tok.OP and t.string == "(":
                break
            else:
                break

        name_str = "".join(name_parts)
        if not _DECO_NAME_RE.match(name_str) or j >= len(tokens) or tokens[j].string != "(":
            i += 1
            continue

        open_paren_tok = tokens[j]
        depth = 1
        k = j + 1
        arg_toks: list = []
        close_paren_tok = None
        while k < len(tokens) and depth > 0:
            t = tokens[k]
            if t.type == _tok.OP:
                if t.string in ("(", "[", "{"):
                    depth += 1
                elif t.string in (")", "]", "}"):
                    depth -= 1
                    if depth == 0:
                        close_paren_tok = t
                        break
            arg_toks.append(t)
            k += 1

        if not close_paren_tok:
            i = k
            continue

        # Split by top-level commas
        parts_toks: list[list] = []
        cur: list = []
        d2 = 0
        for t in arg_toks:
            if t.type == _tok.OP:
                if t.string in ("(", "[", "{"):
                    d2 += 1
                elif t.string in (")", "]", "}"):
                    d2 -= 1
                elif t.string == "," and d2 == 0:
                    parts_toks.append(cur)
                    cur = []
                    continue
            cur.append(t)
        if cur:
            parts_toks.append(cur)

        part_texts = ["".join(t.string for t in pt).strip() for pt in parts_toks]
        positional: list[str] = []
        keyword: list[str] = []
        for txt in part_texts:
            if re.match(r"^[A-Za-z_]\w*\s*=", txt):
                keyword.append(txt)
            else:
                positional.append(txt)

        if not keyword or not positional:
            i = k + 1
            continue

        # Already correct?
        saw_kw = False
        already_ok = True
        for txt in part_texts:
            if re.match(r"^[A-Za-z_]\w*\s*=", txt):
                saw_kw = True
            elif saw_kw:
                already_ok = False
                break

        if not already_ok:
            new_args = ", ".join(positional + keyword)
            s = _offset(open_paren_tok.start[0], open_paren_tok.start[1]) + 1
            e = _offset(close_paren_tok.start[0], close_paren_tok.start[1])
            replacements.append((s, e, new_args))

        i = k + 1

    for s, e, txt in sorted(replacements, reverse=True):
        code = code[:s] + txt + code[e:]

    return code


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
        # qwen3-vl preferred — the retrained multimodal model
        "qwen3-vl:8b",
        "qwen2.5vl:7b",
        "llava:latest",
        "llava:7b",
        "bakllava:latest",
        "moondream:latest",
        "llava-phi3:latest",
        # GPT-OSS / GLM variants that may have vision capability
        "gpt-oss:latest",
        "glm-4v:latest",
    ] if m
]

# LM Studio model name patterns known to support vision (image_url content type).
# Used to prefer these over plain text models when selecting from LM Studio.
_LM_STUDIO_VISION_PATTERNS = (
    "vision", "vl", "llava", "bakllava", "glm-4v", "glm-4.6v",
    "moondream", "phi3-vision", "minicpm-v", "gpt-oss",
)


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

    elif action_type in ("project_save", "project_generate"):
        aa["total_projects_saved"] = aa.get("total_projects_saved", 0) + 1
        name = record.get("input", {}).get("name", "")
        if name:
            projects = aa.setdefault("saved_projects", [])
            projects.append({
                "name": name,
                "action": action_type,
                "ts": record.get("timestamp", ""),
            })
            if len(projects) > 100:
                aa["saved_projects"] = projects[-100:]

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

    if aa.get("total_projects_saved", 0) > 0:
        instructions.append(
            f"Projects saved to VM memory: {aa['total_projects_saved']} "
            "(generated code/HTML projects stored in vm/projects/ directory)"
        )
        recent_proj = [p["name"] for p in aa.get("saved_projects", [])[-5:]]
        if recent_proj:
            instructions.append(
                "Recent saved project names: " + "; ".join(recent_proj)
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


@app.route("/chat", methods=["GET"])
def chat_page():
    """Serve the main UI with the AI chat view active.

    Fixes 'chat online page not found' — navigating to /chat now returns the
    index page (the chat panel is accessible via the 💬 Чат button inside it).
    """
    return send_from_directory(app.static_folder, "index.html")


@app.route("/chatroom", methods=["GET"])
def chatroom_redirect():
    """Convenience alias for /chatroom/page — the standalone multi-user chat room."""
    return redirect("/chatroom/page")


@app.route("/bundle_monaco", methods=["POST"])
def bundle_monaco():
    """Download Monaco Editor files for offline use by running the bundling script."""
    import platform as _platform
    import subprocess as _sp

    vendor_dir = os.path.join(_DIR, "static", "vendor", "monaco", "vs")
    loader_path = os.path.join(vendor_dir, "loader.js")

    # Already bundled?
    if os.path.isfile(loader_path):
        return jsonify({"ok": True, "message": "Monaco уже скачан"})

    try:
        if _platform.system() == "Windows":
            script = os.path.join(_DIR, "bundle_monaco.ps1")
            cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script]
        else:
            script = os.path.join(_DIR, "bundle_monaco.sh")
            cmd = ["bash", script]

        result = _sp.run(cmd, capture_output=True, text=True, timeout=120)
        ok = result.returncode == 0 and os.path.isfile(loader_path)
        return jsonify({
            "ok": ok,
            "message": "Monaco успешно скачан — перезагрузите страницу" if ok else "Не удалось скачать Monaco",
            "stdout": result.stdout[-1000:] if result.stdout else "",
            "stderr": result.stderr[-500:] if result.stderr else "",
        })
    except _sp.TimeoutExpired:
        return jsonify({"ok": False, "message": "Время вышло при скачивании Monaco (>120 с) — попробуйте позже"})
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"ok": False, "message": str(exc)})


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
                        bot_token_set = bool(val and val != _BOT_TOKEN_PLACEHOLDER)
                        break
        # Also honour env var set at runtime (e.g. when running on a server)
        if not bot_token_set and os.environ.get("BOT_TOKEN"):
            bot_token_set = True
    except Exception:  # pylint: disable=broad-except
        pass

    # --- Bot process running status ---
    with _bot_proc_lock:
        _proc = _bot_proc
    bot_running = _proc is not None and _proc.poll() is None

    # --- LM Studio (OpenAI-compatible) ---
    lms_ok     = False
    lms_models: list = []
    if LM_STUDIO_BASE:
        try:
            lms_resp = _http.get(f"{LM_STUDIO_BASE}/v1/models", timeout=10)
            if lms_resp.status_code == 200:
                lms_ok = True
                lms_data = lms_resp.json()
                lms_models = [
                    f"{_LM_STUDIO_PREFIX}{m['id']}"
                    for m in lms_data.get("data", [])
                ]
        except Exception:  # pylint: disable=broad-except
            pass

    # --- text-generation-webui (oobabooga) ---
    tgwui_ok     = False
    tgwui_models: list = []
    if TGWUI_BASE:
        try:
            tgwui_resp = _http.get(f"{TGWUI_BASE}/v1/models", timeout=3)
            if tgwui_resp.status_code == 200:
                tgwui_ok = True
                tgwui_data = tgwui_resp.json()
                tgwui_models = [
                    f"{_TGWUI_PREFIX}{m['id']}"
                    for m in tgwui_data.get("data", [])
                ]
        except Exception:  # pylint: disable=broad-except
            pass

    # --- Roo Code (OpenAI-compatible coding assistant) ---
    roo_code_ok     = False
    roo_code_models: list = []
    if ROO_CODE_BASE:
        try:
            roo_resp = _http.get(f"{ROO_CODE_BASE}/v1/models", timeout=3)
            if roo_resp.status_code == 200:
                roo_code_ok = True
                roo_code_models = [
                    f"{_ROO_CODE_PREFIX}{m['id']}"
                    for m in roo_resp.json().get("data", [])
                ]
        except Exception:  # pylint: disable=broad-except
            pass

    # --- Open Agentic Framework ---
    oaf_ok = False
    if OAF_BASE:
        try:
            oaf_resp = _http.get(f"{OAF_BASE}/health", timeout=3)
            oaf_ok = oaf_resp.status_code < 400
        except Exception:  # pylint: disable=broad-except
            pass

    # --- TripoSR / local 3D generation service ---
    triposr_ok = False
    if TRIPOSR_BASE:
        try:
            triposr_resp = _http.get(f"{TRIPOSR_BASE}/health", timeout=3)
            triposr_ok = triposr_resp.status_code < 400
        except Exception:  # pylint: disable=broad-except
            pass

    # --- AI website builder service ---
    webbuilder_ok = False
    if WEBBUILDER_BASE:
        try:
            wb_resp = _http.get(f"{WEBBUILDER_BASE}/health", timeout=3)
            webbuilder_ok = wb_resp.status_code < 400
        except Exception:  # pylint: disable=broad-except
            pass

    # --- Video editor backend service ---
    videditor_ok = False
    if VIDEDITOR_BASE:
        try:
            ve_resp = _http.get(f"{VIDEDITOR_BASE}/health", timeout=3)
            videditor_ok = ve_resp.status_code < 400
        except Exception:  # pylint: disable=broad-except
            pass

    # --- Stable Diffusion (AUTOMATIC1111 / SD.Next) ---
    sd_ok = False
    if SD_BASE:
        try:
            sd_ok = _sd_available(SD_BASE)
        except Exception:  # pylint: disable=broad-except
            pass

    # --- ComfyUI ---
    comfyui_ok = False
    if COMFYUI_BASE:
        try:
            comfyui_ok = _comfyui_available(COMFYUI_BASE)
        except Exception:  # pylint: disable=broad-except
            pass

    # --- Remote VM (Google Colab / ngrok) ---
    rvm_ok = False
    if REMOTE_VM_URL:
        try:
            rvm_resp = _http.get(f"{REMOTE_VM_URL}/health", timeout=3)
            rvm_ok = rvm_resp.status_code < 400
        except Exception:  # pylint: disable=broad-except
            pass

    # --- Vision VM (dedicated Ollama with vision models) ---
    vvm_ok     = False
    vvm_models: list = []
    if VISION_VM_URL:
        try:
            vvm_resp = _http.get(f"{VISION_VM_URL}/api/tags", timeout=3)
            if vvm_resp.status_code == 200:
                vvm_ok = True
                vvm_models = [
                    f"{_VISION_VM_PREFIX}{m.get('name', '')}"
                    for m in vvm_resp.json().get("models", [])
                ]
        except Exception:  # pylint: disable=broad-except
            pass

    # --- Light vision model (moondream / minicpm-v in local Ollama) ---
    # Priority order: moondream:latest > moondream:1.8b > moondream (any tag) > minicpm-v variants
    _light_vision_candidates = ["moondream:latest", "moondream:1.8b", "moondream", "minicpm-v:latest", "minicpm-v"]
    light_vision_model = ""
    if ollama_ok:
        _ollama_set = set(ollama_models)
        for _lv in _light_vision_candidates:
            if _lv in _ollama_set:
                light_vision_model = _lv
                break
        if not light_vision_model:
            # Fuzzy match: find any installed model whose name starts with a candidate prefix
            for _lv in _light_vision_candidates:
                _prefix = _lv.split(":")[0]
                _match = next((_m for _m in ollama_models if _m.startswith(_prefix)), "")
                if _match:
                    light_vision_model = _match
                    break

    # --- Ollama CORS relay ---
    relay_ok = False
    if _OLLAMA_RELAY_PORT > 0:
        try:
            import urllib.request as _ur
            with _ur.urlopen(
                f"http://127.0.0.1:{_OLLAMA_RELAY_PORT}/api/tags", timeout=2
            ) as _rr:
                relay_ok = _rr.status == 200
        except Exception:  # pylint: disable=broad-except
            pass

    return jsonify({
        "vm":     {"status": "ok"},
        "ollama": {
            "status": "ok" if ollama_ok else "unreachable",
            "url":    OLLAMA_BASE,
            "models": ollama_models,
        },
        "ollama_relay": {
            "status": "ok" if relay_ok else ("disabled" if _OLLAMA_RELAY_PORT == 0 else "starting"),
            "port":   _OLLAMA_RELAY_PORT,
            "url":    f"http://127.0.0.1:{_OLLAMA_RELAY_PORT}" if _OLLAMA_RELAY_PORT > 0 else "",
        },
        "lm_studio": {
            "status":  "ok" if lms_ok else ("unreachable" if LM_STUDIO_BASE else "not_configured"),
            "url":     LM_STUDIO_BASE,
            "models":  lms_models,
        },
        "tgwui": {
            "status":  "ok" if tgwui_ok else ("unreachable" if TGWUI_BASE else "not_configured"),
            "url":     TGWUI_BASE,
            "models":  tgwui_models,
        },
        "roo_code": {
            "status":  "ok" if roo_code_ok else ("unreachable" if ROO_CODE_BASE else "not_configured"),
            "url":     ROO_CODE_BASE,
            "models":  roo_code_models,
        },
        "oaf": {
            "status": "ok" if oaf_ok else ("unreachable" if OAF_BASE else "not_configured"),
            "url":    OAF_BASE,
        },
        "triposr": {
            "status": "ok" if triposr_ok else ("unreachable" if TRIPOSR_BASE else "not_configured"),
            "url":    TRIPOSR_BASE,
        },
        "webbuilder": {
            "status": "ok" if webbuilder_ok else ("unreachable" if WEBBUILDER_BASE else "not_configured"),
            "url":    WEBBUILDER_BASE,
        },
        "videditor": {
            "status": "ok" if videditor_ok else ("unreachable" if VIDEDITOR_BASE else "not_configured"),
            "url":    VIDEDITOR_BASE,
        },
        "remote_vm": {
            "status": "ok" if rvm_ok else ("unreachable" if REMOTE_VM_URL else "not_configured"),
            "url":    REMOTE_VM_URL,
        },
        "vision_vm": {
            "status": "ok" if vvm_ok else ("unreachable" if VISION_VM_URL else "not_configured"),
            "url":    VISION_VM_URL,
            "models": vvm_models,
        },
        "vision_light": {
            "status": "ok" if light_vision_model else ("inactive" if vvm_ok else "none"),
            "model":  light_vision_model,
            "note":   "auto-disabled" if vvm_ok else ("active" if light_vision_model else "not_installed"),
        },
        "stable_diffusion": {
            "status": "ok" if sd_ok else ("unreachable" if SD_BASE else "not_configured"),
            "url":    SD_BASE,
        },
        "comfyui": {
            "status": "ok" if comfyui_ok else ("unreachable" if COMFYUI_BASE else "not_configured"),
            "url":    COMFYUI_BASE,
        },
        "bot": {
            "token_set": bot_token_set,
            "running":   bot_running,
            "status":    "running" if bot_running else ("configured" if bot_token_set else "missing"),
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
    {
        "id": "android_navigator_apk",
        "title": "📱 Android Навигатор — структура APK (Kotlin)",
        "difficulty": "⭐⭐⭐⭐⭐",
        "language": "kotlin",
        "prompt": (
            "Generate complete Android Navigator app source code in Kotlin with Gradle build files. "
            "Requirements:\n\n"
            "1. GPS — use FusedLocationProviderClient for multi-satellite positioning "
            "(GPS, GLONASS, Galileo, BeiDou). Show accuracy, speed, satellites count.\n\n"
            "2. MAP — use OSMDroid library (no Google Maps API key required) with OpenStreetMap tiles, "
            "show current position, route polyline, destination marker.\n\n"
            "3. ROUTING — use OSRM public API (https://router.project-osrm.org) for turn-by-turn "
            "navigation. Show distance, ETA, next manoeuvre instruction.\n\n"
            "4. ALTERNATIVE ROUTES — request and display 3 alternative routes, let user pick.\n\n"
            "5. SAVED ROUTES — store routes in Room database (SQLite). Load on app start.\n\n"
            "6. TRAFFIC — fetch GIBDD (traffic police) RSS feed "
            "(https://www.gibdd.ru/rss/news/) and show alerts on map as markers.\n\n"
            "7. AI ASSISTANT — voice/text assistant using Android SpeechRecognizer + TextToSpeech; "
            "sends queries to Ollama REST API (configurable base URL).\n\n"
            "8. 3D / ANIMATION — tilt map to 45° for 3D perspective, animate car icon along route, "
            "smooth camera follow with bearing rotation.\n\n"
            "9. UI — Material Design 3, dark theme, bottom sheet with route info, "
            "floating action buttons for GPS re-centre and route start/stop.\n\n"
            "Output files:\n"
            "- app/src/main/AndroidManifest.xml (with all permissions)\n"
            "- app/src/main/kotlin/com/drgr/navigator/MainActivity.kt\n"
            "- app/src/main/kotlin/com/drgr/navigator/NavigationService.kt\n"
            "- app/src/main/kotlin/com/drgr/navigator/RouteRepository.kt\n"
            "- app/src/main/res/layout/activity_main.xml\n"
            "- app/build.gradle\n"
            "- build.gradle (project-level)\n"
            "- settings.gradle\n"
            "Wrap each file in a ```kotlin or ```xml code block with a comment showing its path."
        ),
        "description": (
            "Полный Android навигатор на Kotlin: мультиспутниковый GPS (FusedLocation), "
            "карта OSMDroid, маршрутизация OSRM, альтернативные маршруты, база данных Room, "
            "мониторинг пробок ГИБДД, ИИ-ассистент (Ollama), 3D анимация машины. "
            "APK собирается командой: ./gradlew assembleDebug"
        ),
        "demo_url": "/navigator/",
    },
    {
        "id": "android_emulator_setup",
        "title": "🖥 Настройка Android-эмулятора",
        "difficulty": "⭐⭐⭐",
        "language": "python",
        "prompt": (
            "Write a Python script that automates Android emulator (AVD) setup and launch. "
            "The script should:\n"
            "1. Check if ANDROID_HOME / ANDROID_SDK_ROOT is set, guide user if not.\n"
            "2. List available AVDs via 'emulator -list-avds'.\n"
            "3. If no AVDs exist, create one using 'avdmanager create avd' with a Pixel 6 profile.\n"
            "4. Start the emulator: 'emulator -avd <name> -no-snapshot-save'.\n"
            "5. Wait for boot: poll 'adb shell getprop sys.boot_completed' until '1'.\n"
            "6. Install an APK if provided via command-line argument: 'adb install -r <apk>'.\n"
            "7. Print coloured status messages at each step.\n"
            "Use subprocess, argparse, sys. No external dependencies."
        ),
        "description": (
            "Python-скрипт автоматической настройки Android-эмулятора: "
            "проверка SDK, создание AVD (Pixel 6), запуск эмулятора, ожидание загрузки, "
            "установка APK. Работает на Windows/macOS/Linux."
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

<h2>🪟 Windows — пересоздать ярлык на рабочем столе</h2>
<div class="card">
<span class="tag win">PowerShell</span>
<pre>powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\\drgr-bot\\vm\\create_shortcut.ps1"</pre>
<p class="note">Запусти если ярлык «Code VM» пропал с рабочего стола. Также поместит «ЗАПУСТИТЬ_ВМ.bat» и «ПЕРЕУЧИТЬ_ВМ.bat» на рабочий стол.</p>
</div>

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

    # Pre-validate Python syntax before writing to a temp file, so the error
    # message references the actual line number in the submitted code rather
    # than a confusing /tmp/tmpXXX.py path that the user never sees.
    if language == "python":
        # Auto-fix common aiogram 3.x decorator mistake: positional filter after keyword arg.
        # e.g. @router.message(state=S.foo, F.text) → @router.message(F.text, state=S.foo)
        code = _fix_aiogram_decorators(code)
        try:
            compile(code, "<code>", "exec")
        except SyntaxError as exc:
            lineno = exc.lineno if exc.lineno is not None else "?"
            snippet = (exc.text or "").splitlines()[0].rstrip() if exc.text else ""
            friendly = f"Синтаксическая ошибка на строке {lineno}: {exc.msg}"
            if snippet:
                friendly += f"\n  {snippet}"
            # Add hint for the common aiogram ordering mistake
            if "positional argument follows keyword argument" in str(exc.msg):
                friendly += (
                    "\n\n💡 Подсказка: В aiogram 3.x позиционные фильтры (F.text, Command('start') и т.д.) "
                    "должны стоять ПЕРЕД именованными аргументами (state=...).\n"
                    "  ПРАВИЛЬНО:   @router.message(F.text.startswith('/cmd'), state=States.value)\n"
                    "  НЕПРАВИЛЬНО: @router.message(state=States.value, F.text.startswith('/cmd'))"
                )
            return jsonify({"output": "", "error": friendly, "success": False})

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
                        bot_token_set = bool(val and val != _BOT_TOKEN_PLACEHOLDER)
                        break
        if not bot_token_set and os.environ.get("BOT_TOKEN"):
            bot_token_set = True
    except Exception:  # pylint: disable=broad-except
        pass

    return jsonify({
        "ollama_url": OLLAMA_BASE,
        "lm_studio_url": LM_STUDIO_BASE,
        "tgwui_url": TGWUI_BASE,
        "roo_code_url": ROO_CODE_BASE,
        "oaf_url": OAF_BASE,
        "triposr_url": TRIPOSR_BASE,
        "webbuilder_url": WEBBUILDER_BASE,
        "videditor_url": VIDEDITOR_BASE,
        "remote_vm_url": REMOTE_VM_URL,
        "vision_vm_url": VISION_VM_URL,
        "sd_url": SD_BASE,
        "comfyui_url": COMFYUI_BASE,
        "bot_token_set": bot_token_set,
        "ollama_relay_port": _OLLAMA_RELAY_PORT,
        "bot_vm": BOT_VM,
        "bot_model": BOT_MODEL,
    })


@app.route("/settings", methods=["POST"])
def save_settings():
    """Save settings (Telegram bot token, chat ID, Ollama URL, LM Studio URL, Remote VM URL) to .env."""
    global OLLAMA_BASE, _OLLAMA_SCANNED, LM_STUDIO_BASE, TGWUI_BASE, ROO_CODE_BASE  # noqa: PLW0603
    global OAF_BASE, TRIPOSR_BASE, WEBBUILDER_BASE, VIDEDITOR_BASE  # noqa: PLW0603
    global REMOTE_VM_URL, VISION_VM_URL, SD_BASE, COMFYUI_BASE, BOT_VM, BOT_MODEL  # noqa: PLW0603
    body = request.get_json(silent=True) or {}
    bot_token      = body.get("bot_token",      "").strip()
    chat_id        = body.get("chat_id",         "").strip()
    ollama_url     = body.get("ollama_url",      "").strip()
    lm_studio_url  = body.get("lm_studio_url",   "").strip().rstrip("/")
    tgwui_url      = body.get("tgwui_url",        "").strip().rstrip("/")
    roo_code_url   = body.get("roo_code_url",     "").strip().rstrip("/")
    oaf_url        = body.get("oaf_url",          "").strip().rstrip("/")
    triposr_url    = body.get("triposr_url",      "").strip().rstrip("/")
    webbuilder_url = body.get("webbuilder_url",   "").strip().rstrip("/")
    videditor_url  = body.get("videditor_url",    "").strip().rstrip("/")
    remote_vm_url  = body.get("remote_vm_url",   "").strip().rstrip("/")
    vision_vm_url  = body.get("vision_vm_url",   "").strip().rstrip("/")
    sd_url         = body.get("sd_url",           "").strip().rstrip("/")
    comfyui_url    = body.get("comfyui_url",      "").strip().rstrip("/")
    bot_vm_val     = body.get("bot_vm",           "").strip().lower()
    bot_model_val  = body.get("bot_model",        "").strip()

    if not any([bot_token, chat_id, ollama_url, lm_studio_url, tgwui_url, roo_code_url, oaf_url,
                triposr_url, webbuilder_url, videditor_url, remote_vm_url, vision_vm_url,
                sd_url, comfyui_url, bot_vm_val, bot_model_val]):
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

    if chat_id:
        # Update or append TELEGRAM_CHAT_ID line
        cid_found = False
        for i, line in enumerate(lines):
            if line.startswith("TELEGRAM_CHAT_ID="):
                lines[i] = f"TELEGRAM_CHAT_ID={chat_id}\n"
                cid_found = True
                break
        if not cid_found:
            lines.append(f"TELEGRAM_CHAT_ID={chat_id}\n")
        os.environ["TELEGRAM_CHAT_ID"] = chat_id

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

    if lm_studio_url:
        # Update or append LM_STUDIO_URL line
        lms_found = False
        for i, line in enumerate(lines):
            if line.startswith("LM_STUDIO_URL="):
                lines[i] = f"LM_STUDIO_URL={lm_studio_url}\n"
                lms_found = True
                break
        if not lms_found:
            lines.append(f"LM_STUDIO_URL={lm_studio_url}\n")
        os.environ["LM_STUDIO_URL"] = lm_studio_url
        LM_STUDIO_BASE = lm_studio_url

    if tgwui_url:
        tgwui_found = False
        for i, line in enumerate(lines):
            if line.startswith("TGWUI_URL="):
                lines[i] = f"TGWUI_URL={tgwui_url}\n"
                tgwui_found = True
                break
        if not tgwui_found:
            lines.append(f"TGWUI_URL={tgwui_url}\n")
        os.environ["TGWUI_URL"] = tgwui_url
        TGWUI_BASE = tgwui_url

    if roo_code_url:
        roo_found = False
        for i, line in enumerate(lines):
            if line.startswith("ROO_CODE_URL="):
                lines[i] = f"ROO_CODE_URL={roo_code_url}\n"
                roo_found = True
                break
        if not roo_found:
            lines.append(f"ROO_CODE_URL={roo_code_url}\n")
        os.environ["ROO_CODE_URL"] = roo_code_url
        ROO_CODE_BASE = roo_code_url

    if oaf_url:
        oaf_found = False
        for i, line in enumerate(lines):
            if line.startswith("OAF_URL="):
                lines[i] = f"OAF_URL={oaf_url}\n"
                oaf_found = True
                break
        if not oaf_found:
            lines.append(f"OAF_URL={oaf_url}\n")
        os.environ["OAF_URL"] = oaf_url
        OAF_BASE = oaf_url

    if triposr_url:
        triposr_found = False
        for i, line in enumerate(lines):
            if line.startswith("TRIPOSR_URL="):
                lines[i] = f"TRIPOSR_URL={triposr_url}\n"
                triposr_found = True
                break
        if not triposr_found:
            lines.append(f"TRIPOSR_URL={triposr_url}\n")
        os.environ["TRIPOSR_URL"] = triposr_url
        TRIPOSR_BASE = triposr_url

    if webbuilder_url:
        wb_found = False
        for i, line in enumerate(lines):
            if line.startswith("WEBBUILDER_URL="):
                lines[i] = f"WEBBUILDER_URL={webbuilder_url}\n"
                wb_found = True
                break
        if not wb_found:
            lines.append(f"WEBBUILDER_URL={webbuilder_url}\n")
        os.environ["WEBBUILDER_URL"] = webbuilder_url
        WEBBUILDER_BASE = webbuilder_url

    if videditor_url:
        ve_found = False
        for i, line in enumerate(lines):
            if line.startswith("VIDEDITOR_URL="):
                lines[i] = f"VIDEDITOR_URL={videditor_url}\n"
                ve_found = True
                break
        if not ve_found:
            lines.append(f"VIDEDITOR_URL={videditor_url}\n")
        os.environ["VIDEDITOR_URL"] = videditor_url
        VIDEDITOR_BASE = videditor_url

    if remote_vm_url:
        # Update or append REMOTE_VM_URL line
        rvm_found = False
        for i, line in enumerate(lines):
            if line.startswith("REMOTE_VM_URL="):
                lines[i] = f"REMOTE_VM_URL={remote_vm_url}\n"
                rvm_found = True
                break
        if not rvm_found:
            lines.append(f"REMOTE_VM_URL={remote_vm_url}\n")
        os.environ["REMOTE_VM_URL"] = remote_vm_url
        REMOTE_VM_URL = remote_vm_url

    if vision_vm_url:
        # Update or append VISION_VM_URL line
        vvm_found = False
        for i, line in enumerate(lines):
            if line.startswith("VISION_VM_URL="):
                lines[i] = f"VISION_VM_URL={vision_vm_url}\n"
                vvm_found = True
                break
        if not vvm_found:
            lines.append(f"VISION_VM_URL={vision_vm_url}\n")
        os.environ["VISION_VM_URL"] = vision_vm_url
        VISION_VM_URL = vision_vm_url

    if sd_url:
        sd_found = False
        for i, line in enumerate(lines):
            if line.startswith("SD_API_URL="):
                lines[i] = f"SD_API_URL={sd_url}\n"
                sd_found = True
                break
        if not sd_found:
            lines.append(f"SD_API_URL={sd_url}\n")
        os.environ["SD_API_URL"] = sd_url
        SD_BASE = sd_url

    if comfyui_url:
        cfu_found = False
        for i, line in enumerate(lines):
            if line.startswith("COMFYUI_API_URL="):
                lines[i] = f"COMFYUI_API_URL={comfyui_url}\n"
                cfu_found = True
                break
        if not cfu_found:
            lines.append(f"COMFYUI_API_URL={comfyui_url}\n")
        os.environ["COMFYUI_API_URL"] = comfyui_url
        COMFYUI_BASE = comfyui_url

    if bot_vm_val and bot_vm_val in ("auto", "ollama", "lmstudio", "tgwui", "remote"):
        bvm_found = False
        for i, line in enumerate(lines):
            if line.startswith("BOT_VM="):
                lines[i] = f"BOT_VM={bot_vm_val}\n"
                bvm_found = True
                break
        if not bvm_found:
            lines.append(f"BOT_VM={bot_vm_val}\n")
        os.environ["BOT_VM"] = bot_vm_val
        BOT_VM = bot_vm_val

    if bot_model_val is not None and "bot_model" in body:
        bm_found = False
        for i, line in enumerate(lines):
            if line.startswith("BOT_MODEL="):
                lines[i] = f"BOT_MODEL={bot_model_val}\n"
                bm_found = True
                break
        if not bm_found:
            lines.append(f"BOT_MODEL={bot_model_val}\n")
        os.environ["BOT_MODEL"] = bot_model_val
        BOT_MODEL = bot_model_val

    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except OSError as exc:
        return jsonify({"ok": False, "error": f"Не удалось записать .env: {exc}"})

    # If the bot token changed, restart the bot process so it uses the new token.
    bot_restarted = False
    if bot_token:
        bot_restarted = _start_bot(bot_token)

    return jsonify({"ok": True, "bot_restarted": bot_restarted})


@app.route("/bot/status", methods=["GET"])
def bot_status():
    """Return the status of the managed bot subprocess."""
    with _bot_proc_lock:
        proc = _bot_proc
    if proc is None:
        running = False
        pid = None
    else:
        running = proc.poll() is None
        pid = proc.pid
    token = _get_saved_token()
    return jsonify({
        "running": running,
        "pid": pid,
        "token_set": bool(token),
    })


@app.route("/bot/restart", methods=["POST"])
def bot_restart():
    """(Re)start the bot subprocess using the token stored in .env."""
    if not os.path.isfile(_BOT_PY):
        return jsonify({"ok": False, "error": "bot.py не найден — убедитесь что репозиторий клонирован полностью"})
    if not _get_saved_token():
        return jsonify({"ok": False, "error": "BOT_TOKEN не задан — сначала сохрани токен в настройках"})
    ok = _start_bot()
    if ok:
        with _bot_proc_lock:
            pid = _bot_proc.pid if _bot_proc else None
        return jsonify({"ok": True, "pid": pid})
    return jsonify({"ok": False, "error": "Не удалось запустить бота"})


@app.route("/bot/test", methods=["POST"])
def bot_test():
    """Test a Telegram bot token by calling the Telegram getMe API.

    Body: {"bot_token": "..."}
    Returns: {"ok": true, "username": "...", "first_name": "..."} or {"ok": false, "error": "..."}
    """
    body = request.get_json(silent=True) or {}
    token = body.get("bot_token", "").strip()
    if not token:
        return jsonify({"ok": False, "error": "Токен не указан"})
    try:
        resp = _http.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=10,
        )
        data = resp.json()
        if data.get("ok"):
            result = data.get("result", {})
            return jsonify({
                "ok": True,
                "username": result.get("username", ""),
                "first_name": result.get("first_name", ""),
                "id": result.get("id"),
            })
        description = data.get("description", "Неверный токен или Telegram API недоступен")
        return jsonify({"ok": False, "error": description})
    except _http.exceptions.ConnectionError:
        return jsonify({"ok": False, "error": "Нет доступа к api.telegram.org — проверьте интернет-соединение"})
    except _http.exceptions.Timeout:
        return jsonify({"ok": False, "error": "Таймаут запроса к Telegram API (>10 сек)"})
    except Exception:  # pylint: disable=broad-except
        return jsonify({"ok": False, "error": "Ошибка при проверке токена — попробуйте позже"})


@app.route("/autostart/register", methods=["POST"])
def autostart_register():
    """Register the VM server as a Windows Task Scheduler task so it starts on login.

    Works only on Windows. On other platforms returns {"ok": false, "error": "..."}
    """
    import sys as _sys
    import shutil as _shutil
    if _sys.platform != "win32":
        return jsonify({"ok": False, "error": "Автозапуск поддерживается только на Windows"})
    try:
        repo_dir = os.path.abspath(os.path.join(_DIR, ".."))
        python_exe = _sys.executable
        server_py  = os.path.join(repo_dir, "vm", "server.py")
        task_name  = "DrgrBotVM"
        # Build a minimal schtasks command — runs at logon, hidden window, highest privileges
        cmd = (
            f'schtasks /create /tn "{task_name}" /tr "\\"{python_exe}\\" \\"{server_py}\\"" '
            f'/sc ONLOGON /rl HIGHEST /f /it'
        )
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            return jsonify({"ok": True, "message": f"Задача '{task_name}' создана — VM будет запускаться при входе в Windows"})
        return jsonify({"ok": False, "error": result.stderr.strip() or result.stdout.strip() or "schtasks вернул ошибку"})
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"ok": False, "error": str(exc)})


@app.route("/autostart/remove", methods=["POST"])
def autostart_remove():
    """Remove the Windows Task Scheduler autostart task."""
    import sys as _sys
    if _sys.platform != "win32":
        return jsonify({"ok": False, "error": "Автозапуск поддерживается только на Windows"})
    try:
        task_name = "DrgrBotVM"
        cmd = f'schtasks /delete /tn "{task_name}" /f'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            return jsonify({"ok": True, "message": f"Задача '{task_name}' удалена"})
        return jsonify({"ok": False, "error": result.stderr.strip() or "Задача не найдена или ошибка удаления"})
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"ok": False, "error": str(exc)})


@app.route("/ollama/models", methods=["GET"])
def ollama_models():
    """Return the list of models available in Ollama and (if configured) LM Studio."""
    models = []
    preferred = ""

    # --- Ollama models ---
    try:
        resp = _http.get(f"{OLLAMA_BASE}/api/tags", timeout=3)
        resp.raise_for_status()
        ol_models = [m["name"] for m in resp.json().get("models", [])]
        models.extend(ol_models)
        if not preferred:
            preferred = next((m for m in _PREFERRED_MODELS if m in ol_models), ol_models[0] if ol_models else "")
    except Exception:  # pylint: disable=broad-except
        pass

    # --- LM Studio models (OpenAI-compatible /v1/models) ---
    if LM_STUDIO_BASE:
        try:
            lms_resp = _http.get(f"{LM_STUDIO_BASE}/v1/models", timeout=10)
            lms_resp.raise_for_status()
            lms_models = [
                f"{_LM_STUDIO_PREFIX}{m['id']}"
                for m in lms_resp.json().get("data", [])
            ]
            models.extend(lms_models)
            # Set LM Studio model as preferred if no Ollama model was found
            if not preferred and lms_models:
                preferred = lms_models[0]
        except Exception:  # pylint: disable=broad-except
            pass

    # --- text-generation-webui models (OpenAI-compatible /v1/models) ---
    if TGWUI_BASE:
        try:
            tgwui_resp = _http.get(f"{TGWUI_BASE}/v1/models", timeout=3)
            tgwui_resp.raise_for_status()
            tw_models = [
                f"{_TGWUI_PREFIX}{m['id']}"
                for m in tgwui_resp.json().get("data", [])
            ]
            models.extend(tw_models)
            if not preferred and tw_models:
                preferred = tw_models[0]
        except Exception:  # pylint: disable=broad-except
            pass

    # --- Roo Code models (OpenAI-compatible /v1/models) ---
    if ROO_CODE_BASE:
        try:
            roo_resp = _http.get(f"{ROO_CODE_BASE}/v1/models", timeout=3)
            roo_resp.raise_for_status()
            roo_models = [
                f"{_ROO_CODE_PREFIX}{m['id']}"
                for m in roo_resp.json().get("data", [])
            ]
            models.extend(roo_models)
            if not preferred and roo_models:
                preferred = roo_models[0]
        except Exception:  # pylint: disable=broad-except
            pass

    available = bool(models)
    if not preferred and models:
        preferred = models[0]
    return jsonify({"models": models, "available": available, "preferred": preferred})


@app.route("/lmstudio/models", methods=["GET"])
def lmstudio_models():
    """Return the list of models available in LM Studio (OpenAI-compatible /v1/models).

    If the configured URL is unreachable, the endpoint automatically falls back to
    scanning common LM Studio addresses so the UI can reconnect without user action.
    """
    global LM_STUDIO_BASE  # noqa: PLW0603
    if not LM_STUDIO_BASE:
        return jsonify({"models": [], "available": False, "url": "", "error": "LM Studio URL not configured"})
    try:
        resp = _http.get(f"{LM_STUDIO_BASE}/v1/models", timeout=5)
        resp.raise_for_status()
        models = [m["id"] for m in resp.json().get("data", [])]
        return jsonify({"models": models, "available": bool(models), "url": LM_STUDIO_BASE})
    except Exception:  # pylint: disable=broad-except
        pass
    # Configured URL unreachable — try common local/LAN addresses automatically
    _fallback_candidates = []
    for _host in ("127.0.0.1", "localhost", "172.22.208.1", "172.22.0.1", "192.168.1.1"):
        for _port in (1234, 1235, 8080, 11434, 8000):
            _url = f"http://{_host}:{_port}"
            if _url != LM_STUDIO_BASE:
                _fallback_candidates.append(_url)
    for _url in _fallback_candidates:
        try:
            _r = _http.get(f"{_url}/v1/models", timeout=1)
            if _r.status_code == 200:
                _models = [m["id"] for m in _r.json().get("data", [])]
                LM_STUDIO_BASE = _url  # auto-update for subsequent requests
                return jsonify({"models": _models, "available": bool(_models), "url": _url,
                                "auto_detected": True})
        except Exception:  # pylint: disable=broad-except
            continue
    return jsonify({"models": [], "available": False, "url": LM_STUDIO_BASE,
                    "error": "LM Studio недоступен по сохранённому адресу"})


@app.route("/lmstudio/detect", methods=["GET"])
def lmstudio_detect():
    """Scan common LM Studio ports/addresses and return the first reachable one.

    Scans 127.0.0.1 and localhost on ports 1234, 1235, 11434, 8080, 8000.
    If an extra host hint is provided via ?hint=<host>, that is probed first
    (useful for LAN addresses like 172.22.208.1).
    Returns {"url": "<base_url>", "models": [...]} or {"url": null}.
    """
    from urllib.parse import urlparse as _urlparse_detect
    hint = request.args.get("hint", "").strip().rstrip("/")
    candidates = []
    if hint:
        # Normalise: add scheme if missing so urlparse works correctly
        hint_url = hint if hint.startswith(("http://", "https://")) else f"http://{hint}"
        parsed_hint = _urlparse_detect(hint_url)
        if parsed_hint.port:
            # Hint already contains a port — probe exactly that URL
            candidates.append(hint_url)
        else:
            # No port in hint — scan common LM Studio ports on the hint host
            for port in (1234, 1235, 11434, 8080, 8000):
                candidates.append(f"http://{parsed_hint.hostname}:{port}")
    # Common local addresses + default LAN VM host (e.g. Windows-host WSL bridge 172.22.208.1)
    for host in ("127.0.0.1", "localhost", "172.22.208.1"):
        for port in (1234, 1235, 11434, 8080, 8000):
            candidates.append(f"http://{host}:{port}")
    seen: set = set()
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        if url == LM_STUDIO_BASE:
            # Already configured — return current config without extra probe
            try:
                resp = _http.get(f"{url}/v1/models", timeout=2)
                if resp.status_code == 200:
                    models = [m["id"] for m in resp.json().get("data", [])]
                    return jsonify({"url": url, "models": models})
            except Exception:  # pylint: disable=broad-except
                pass
            continue
        try:
            resp = _http.get(f"{url}/v1/models", timeout=1)
            if resp.status_code == 200:
                models = [m["id"] for m in resp.json().get("data", [])]
                return jsonify({"url": url, "models": models})
        except Exception:  # pylint: disable=broad-except
            continue
    return jsonify({"url": None, "models": []})


# ---------------------------------------------------------------------------
# VM diagnostic report — lists all generators/editors and tests LLM backends
# ---------------------------------------------------------------------------

@app.route("/vm/report", methods=["GET"])
def vm_report():
    """Return a diagnostic report listing all generators, editors and LLM backend statuses.

    Optional query params:
      ?model=<model_id>  — if provided, fires a quick test generation request
    """
    import time as _time

    generators = [
        {"id": "code",       "name": "💻 Генератор кода",          "endpoint": "/generate/auto/stream",    "method": "POST"},
        {"id": "patch",      "name": "✏ Патчер кода",              "endpoint": "/patch/stream",             "method": "POST"},
        {"id": "project",    "name": "📦 Генератор проектов",       "endpoint": "/project/generate",         "method": "POST"},
        {"id": "extension",  "name": "🧩 Генератор расширений",     "endpoint": "/extension/generate",       "method": "POST"},
        {"id": "imagegen",   "name": "🎨 Генератор изображений",    "endpoint": "/imagegen/generate",        "method": "POST"},
        {"id": "triposr",    "name": "🧊 Генератор 3D-моделей",     "endpoint": "/triposr/generate",         "method": "POST"},
        {"id": "webbuilder", "name": "🌐 Генератор сайтов",         "endpoint": "/webbuilder/generate",      "method": "POST"},
        {"id": "videditor",  "name": "🎬 Генератор видеопроектов",  "endpoint": "/videditor/project",        "method": "POST"},
        {"id": "research",   "name": "🔬 Исследователь (Research)", "endpoint": "/research",                 "method": "POST"},
    ]

    editors = [
        {"id": "monaco",       "name": "📝 Monaco (редактор кода)",   "status": "built-in",   "note": "Встроен в VM"},
        {"id": "gltf",         "name": "🧊 GLTF 3D-редактор",         "status": "built-in",   "note": "JSON + 3D preview"},
        {"id": "webbuilder",   "name": "🌐 Редактор сайтов",          "status": "built-in",   "note": "WebBuilder pane"},
        {"id": "videditor",    "name": "🎬 Видеоредактор (EDL)",       "status": "built-in",   "note": "VidEditor pane"},
        {"id": "imagegen",     "name": "🎨 Арт-студия",               "status": "built-in",   "note": "SD/ComfyUI pane"},
    ]

    # --- Check LLM backends ---
    backends: list = []

    # Ollama
    ollama_status = "not_configured"
    ollama_models: list = []
    if OLLAMA_BASE:
        try:
            r = _http.get(f"{OLLAMA_BASE}/api/tags", timeout=3)
            if r.status_code == 200:
                ollama_models = [m["name"] for m in r.json().get("models", [])]
                ollama_status = "ok"
            else:
                ollama_status = "unreachable"
        except Exception:
            ollama_status = "unreachable"
    backends.append({"id": "ollama", "name": "🦙 Ollama", "url": OLLAMA_BASE, "status": ollama_status, "models": ollama_models})

    # LM Studio
    lms_status = "not_configured"
    lms_models: list = []
    if LM_STUDIO_BASE:
        try:
            r = _http.get(f"{LM_STUDIO_BASE}/v1/models", timeout=10)
            if r.status_code == 200:
                lms_models = [m["id"] for m in r.json().get("data", [])]
                lms_status = "ok"
            else:
                lms_status = "unreachable"
        except Exception:
            lms_status = "unreachable"
    backends.append({"id": "lmstudio", "name": "🎬 LM Studio", "url": LM_STUDIO_BASE, "status": lms_status, "models": lms_models})

    # TGWUI
    tgwui_status = "not_configured"
    tgwui_models: list = []
    if TGWUI_BASE:
        try:
            r = _http.get(f"{TGWUI_BASE}/v1/models", timeout=3)
            if r.status_code == 200:
                tgwui_models = [m["id"] for m in r.json().get("data", [])]
                tgwui_status = "ok"
            else:
                tgwui_status = "unreachable"
        except Exception:
            tgwui_status = "unreachable"
    backends.append({"id": "tgwui", "name": "⚙ TGWUI", "url": TGWUI_BASE, "status": tgwui_status, "models": tgwui_models})

    # Roo Code
    roo_code_status = "not_configured"
    roo_code_models_vs: list = []
    if ROO_CODE_BASE:
        try:
            r = _http.get(f"{ROO_CODE_BASE}/v1/models", timeout=3)
            if r.status_code == 200:
                roo_code_models_vs = [m["id"] for m in r.json().get("data", [])]
                roo_code_status = "ok"
            else:
                roo_code_status = "unreachable"
        except Exception:
            roo_code_status = "unreachable"
    backends.append({"id": "roocode", "name": "🦘 Roo Code", "url": ROO_CODE_BASE, "status": roo_code_status, "models": roo_code_models_vs})

    # Vision VM
    vvm_status = "not_configured"
    if VISION_VM_URL:
        try:
            r = _http.get(f"{VISION_VM_URL}/health", timeout=3)
            vvm_status = "ok" if r.status_code == 200 else "unreachable"
        except Exception:
            vvm_status = "unreachable"
    backends.append({"id": "visionvm", "name": "👁 Vision VM", "url": VISION_VM_URL, "status": vvm_status, "models": []})

    # Remote VM (Colab / ngrok)
    remote_status = "not_configured"
    if REMOTE_VM_URL:
        try:
            r = _http.get(f"{REMOTE_VM_URL}/health", timeout=4)
            remote_status = "ok" if r.status_code == 200 else "unreachable"
        except Exception:
            remote_status = "unreachable"
    backends.append({"id": "remotevm", "name": "☁ Remote VM (Colab)", "url": REMOTE_VM_URL, "status": remote_status, "models": []})

    # --- Optional quick test code generation ---
    test_model = request.args.get("model", "").strip()
    test_result: dict = {}
    if test_model:
        test_prompt = (
            "Напиши на Python функцию `fibonacci(n)` которая возвращает список из первых n "
            "чисел Фибоначчи. Только код, без объяснений."
        )
        t0 = _time.time()
        try:
            if test_model.startswith("lmstudio:") and LM_STUDIO_BASE:
                real_model = test_model[len("lmstudio:"):]
                payload = {
                    "model": real_model,
                    "messages": [{"role": "user", "content": test_prompt}],
                    "max_tokens": 512, "temperature": 0.2, "stream": False,
                }
                r = _http.post(f"{LM_STUDIO_BASE}/v1/chat/completions", json=payload, timeout=30)
                if r.status_code == 200:
                    content = r.json()["choices"][0]["message"]["content"]
                    test_result = {"ok": True, "model": test_model, "elapsed_s": round(_time.time() - t0, 2), "output": content[:1000]}
                else:
                    test_result = {"ok": False, "model": test_model, "error": f"HTTP {r.status_code}"}
            elif test_model.startswith("tgwui:") and TGWUI_BASE:
                real_model = test_model[len("tgwui:"):]
                payload = {
                    "model": real_model,
                    "messages": [{"role": "user", "content": test_prompt}],
                    "max_tokens": 512, "temperature": 0.2, "stream": False,
                }
                r = _http.post(f"{TGWUI_BASE}/v1/chat/completions", json=payload, timeout=30)
                if r.status_code == 200:
                    content = r.json()["choices"][0]["message"]["content"]
                    test_result = {"ok": True, "model": test_model, "elapsed_s": round(_time.time() - t0, 2), "output": content[:1000]}
                else:
                    test_result = {"ok": False, "model": test_model, "error": f"HTTP {r.status_code}"}
            elif test_model.startswith("roo:") and ROO_CODE_BASE:
                real_model = test_model[len("roo:"):]
                payload = {
                    "model": real_model,
                    "messages": [{"role": "user", "content": test_prompt}],
                    "max_tokens": 512, "temperature": 0.2, "stream": False,
                }
                r = _http.post(f"{ROO_CODE_BASE}/v1/chat/completions", json=payload, timeout=30)
                if r.status_code == 200:
                    content = r.json()["choices"][0]["message"]["content"]
                    test_result = {"ok": True, "model": test_model, "elapsed_s": round(_time.time() - t0, 2), "output": content[:1000]}
                else:
                    test_result = {"ok": False, "model": test_model, "error": f"HTTP {r.status_code}"}
            elif OLLAMA_BASE:
                payload = {
                    "model": test_model,
                    "messages": [{"role": "user", "content": test_prompt}],
                    "stream": False,
                }
                r = _http.post(f"{OLLAMA_BASE}/api/chat", json=payload, timeout=30)
                if r.status_code == 200:
                    content = r.json().get("message", {}).get("content", "")
                    test_result = {"ok": True, "model": test_model, "elapsed_s": round(_time.time() - t0, 2), "output": content[:1000]}
                else:
                    test_result = {"ok": False, "model": test_model, "error": f"HTTP {r.status_code}"}
            else:
                test_result = {"ok": False, "model": test_model, "error": "No matching backend configured"}
        except Exception as exc:  # pylint: disable=broad-except
            test_result = {"ok": False, "model": test_model, "error": str(exc), "elapsed_s": round(_time.time() - t0, 2)}

    return jsonify({
        "generators": generators,
        "editors": editors,
        "backends": backends,
        "test": test_result,
        "summary": {
            "total_generators": len(generators),
            "total_editors": len(editors),
            "backends_ok": sum(1 for b in backends if b["status"] == "ok"),
            "backends_total": len(backends),
        },
    })


# ---------------------------------------------------------------------------
# Colab VM auto-start — receives URL from batch file / URL param
# ---------------------------------------------------------------------------

@app.route("/colab/autostart", methods=["POST"])
def colab_autostart():
    """Auto-configure the Remote VM URL (called from a batch file or startup script).

    Expects JSON: {"url": "https://xxxx.ngrok-free.app"}
    Saves the URL to .env and returns the VM UI URL with ?view=colab.
    """
    global REMOTE_VM_URL  # noqa: PLW0603
    body = request.get_json(silent=True) or {}
    url = body.get("url", "").strip().rstrip("/")
    if not url:
        return jsonify({"ok": False, "error": "url is required"}), 400
    if not url.startswith(("http://", "https://")):
        return jsonify({"ok": False, "error": "url must start with http:// or https://"}), 400

    # Persist to .env
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    try:
        lines: list = []
        if os.path.exists(env_path):
            with open(env_path, encoding="utf-8") as f:
                lines = f.readlines()
        found = False
        for i, line in enumerate(lines):
            if line.startswith("REMOTE_VM_URL="):
                lines[i] = f"REMOTE_VM_URL={url}\n"
                found = True
                break
        if not found:
            lines.append(f"REMOTE_VM_URL={url}\n")
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception:  # pylint: disable=broad-except
        pass

    os.environ["REMOTE_VM_URL"] = url
    REMOTE_VM_URL = url

    # Test connectivity
    try:
        r = _http.get(f"{url}/health", timeout=5)
        connected = r.status_code == 200
    except Exception:  # pylint: disable=broad-except
        connected = False

    vm_port = int(os.environ.get("VM_PORT", 8080))
    ui_url = f"http://localhost:{vm_port}/?view=colab"
    return jsonify({"ok": True, "url": url, "connected": connected, "ui_url": ui_url})


@app.route("/colab/notebook_url", methods=["GET"])
def colab_notebook_url():
    """Return the Google Colab notebook URL for drgr_vm_colab.ipynb.

    The notebook is looked up in the repository root.  If found it returns a
    colab.research.google.com/github/... deep-link.  Falls back to the raw
    GitHub URL if the repo remote is available.
    """
    # Try to resolve the GitHub repo remote URL from git config
    repo_root = os.path.join(os.path.dirname(__file__), "..")
    notebook_rel = "drgr_vm_colab.ipynb"
    notebook_path = os.path.join(repo_root, notebook_rel)

    colab_url = ""
    github_url = ""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, cwd=repo_root, timeout=5,
        )
        remote = result.stdout.strip()
        # Convert SSH → HTTPS and strip .git
        remote = remote.replace("git@github.com:", "https://github.com/")
        if remote.endswith(".git"):
            remote = remote[:-4]
        # Parse the URL to validate the host is exactly github.com
        from urllib.parse import urlparse  # noqa: PLC0415
        parsed = urlparse(remote)
        if parsed.scheme in ("http", "https") and parsed.netloc in ("github.com", "www.github.com"):
            repo_path = parsed.path.lstrip("/")
            if repo_path:
                github_url = f"https://raw.githubusercontent.com/{repo_path}/HEAD/{notebook_rel}"
                colab_url = (
                    f"https://colab.research.google.com/github/{repo_path}/blob/HEAD/{notebook_rel}"
                )
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        app.logger.debug("colab_notebook_url: could not resolve git remote: %s", exc)

    exists = os.path.isfile(notebook_path)
    return jsonify({
        "ok": True,
        "exists": exists,
        "colab_url": colab_url,
        "github_url": github_url,
        "notebook_file": notebook_rel,
    })


# ---------------------------------------------------------------------------
# Colab VM registration and status — /api/colab/register + /api/colab/status
# ---------------------------------------------------------------------------

@app.route("/api/colab/register", methods=["POST"])
def colab_register():
    """Register (or refresh) the Colab VM URL.

    Expects JSON: {"url": "https://xxxx.ngrok-free.app"}
    Updates the global REMOTE_VM_URL and REMOTE_VM_LAST_SEEN, and persists
    the URL to .env so it survives a server restart.
    """
    global REMOTE_VM_URL, REMOTE_VM_LAST_SEEN  # noqa: PLW0603
    body = request.get_json(silent=True) or {}
    url = body.get("url", "").strip().rstrip("/")
    if not url:
        return jsonify({"ok": False, "error": "url is required"}), 400
    if not url.startswith(("http://", "https://")):
        return jsonify({"ok": False, "error": "url must start with http:// or https://"}), 400

    REMOTE_VM_URL = url
    REMOTE_VM_LAST_SEEN = time.time()

    # Persist to .env
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    try:
        lines: list = []
        if os.path.exists(env_path):
            with open(env_path, encoding="utf-8") as f:
                lines = f.readlines()
        found = False
        for i, line in enumerate(lines):
            if line.startswith("REMOTE_VM_URL="):
                lines[i] = f"REMOTE_VM_URL={url}\n"
                found = True
                break
        if not found:
            lines.append(f"REMOTE_VM_URL={url}\n")
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception:  # pylint: disable=broad-except
        pass

    os.environ["REMOTE_VM_URL"] = url
    return jsonify({"ok": True, "url": url, "last_seen": REMOTE_VM_LAST_SEEN})


@app.route("/api/colab/status", methods=["GET"])
def colab_status():
    """Return the registration status of the Colab VM.

    Response: {"url": "...", "online": bool, "last_seen": float}
    "online" is True when a heartbeat was received within the last 90 seconds.
    """
    online = bool(REMOTE_VM_URL) and (time.time() - REMOTE_VM_LAST_SEEN) < 90
    return jsonify({
        "url": REMOTE_VM_URL,
        "online": online,
        "last_seen": REMOTE_VM_LAST_SEEN,
    })


@app.route("/tgwui/models", methods=["GET"])
def tgwui_models():
    """Return the list of models available in text-generation-webui (OpenAI-compatible /v1/models)."""
    if not TGWUI_BASE:
        return jsonify({"models": [], "available": False, "url": "", "error": "text-generation-webui URL not configured"})
    try:
        resp = _http.get(f"{TGWUI_BASE}/v1/models", timeout=5)
        resp.raise_for_status()
        models = [m["id"] for m in resp.json().get("data", [])]
        return jsonify({"models": models, "available": bool(models), "url": TGWUI_BASE})
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"models": [], "available": False, "url": TGWUI_BASE, "error": str(exc)})


@app.route("/roocode/models", methods=["GET"])
def roocode_models():
    """Return the list of models available via the Roo Code backend (OpenAI-compatible /v1/models).

    Point ROO_CODE_URL at whatever LLM server Roo Code is configured to use
    (e.g. http://127.0.0.1:1234 for LM Studio, http://127.0.0.1:11434 for Ollama).
    """
    if not ROO_CODE_BASE:
        return jsonify({"models": [], "available": False, "url": "", "error": "Roo Code URL not configured"})
    try:
        resp = _http.get(f"{ROO_CODE_BASE}/v1/models", timeout=5)
        resp.raise_for_status()
        models = [m["id"] for m in resp.json().get("data", [])]
        return jsonify({"models": models, "available": bool(models), "url": ROO_CODE_BASE})
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"models": [], "available": False, "url": ROO_CODE_BASE, "error": str(exc)})


# ---------------------------------------------------------------------------
# Remote VM (Google Colab / ngrok) — status probe and transparent proxy
# ---------------------------------------------------------------------------

@app.route("/remote/status", methods=["GET"])
def remote_vm_status():
    """Check connectivity to the configured Remote VM URL (e.g. Google Colab via ngrok)."""
    if not REMOTE_VM_URL:
        return jsonify({"ok": False, "url": "", "error": "Remote VM URL not configured"})
    try:
        resp = _http.get(f"{REMOTE_VM_URL}/health", timeout=5)
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        return jsonify({"ok": resp.status_code < 400, "url": REMOTE_VM_URL, "status_code": resp.status_code, "data": data})
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"ok": False, "url": REMOTE_VM_URL, "error": str(exc)})


@app.route("/remote/proxy/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def remote_vm_proxy(subpath):
    """Transparent proxy — forward requests to the configured Remote VM URL.

    Usage:  POST /remote/proxy/chat/stream  →  forwarded to <REMOTE_VM_URL>/chat/stream
    This lets the browser UI call the Google Colab VM without CORS issues.
    Only a safe allowlist of request headers is forwarded to avoid leaking
    sensitive client headers (cookies, auth tokens, etc.).
    """
    if not REMOTE_VM_URL:
        return jsonify({"error": "Remote VM URL not configured"}), 503

    target = f"{REMOTE_VM_URL}/{subpath}"
    params = request.args.to_dict(flat=False)

    # Forward only safe, non-sensitive headers
    _ALLOWED_REQUEST_HEADERS = frozenset({
        "content-type", "accept", "accept-language", "accept-encoding",
        "user-agent", "cache-control", "x-requested-with",
    })
    headers = {
        k: v for k, v in request.headers
        if k.lower() in _ALLOWED_REQUEST_HEADERS
    }

    # Response headers to strip (hop-by-hop + encoding that would confuse clients)
    _STRIP_RESPONSE_HEADERS = frozenset({
        "transfer-encoding", "content-encoding",
        "connection", "keep-alive", "proxy-authenticate",
        "proxy-authorization", "te", "trailers", "upgrade",
    })

    try:
        proxied = _http.request(
            method=request.method,
            url=target,
            params=params,
            headers=headers,
            data=request.get_data(),
            stream=True,
            timeout=120,
        )
        # Stream the response back (supports SSE endpoints)
        def _generate():
            for chunk in proxied.iter_content(chunk_size=None):
                if chunk:
                    yield chunk

        return app.response_class(
            response=_generate(),
            status=proxied.status_code,
            headers={
                k: v for k, v in proxied.headers.items()
                if k.lower() not in _STRIP_RESPONSE_HEADERS
            },
        )
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"error": str(exc)}), 502


@app.route("/remote/models", methods=["GET"])
def remote_vm_models():
    """Fetch the list of Ollama models available on the configured Remote VM."""
    if not REMOTE_VM_URL:
        return jsonify({"models": [], "error": "Remote VM URL not configured"})
    try:
        resp = _http.get(f"{REMOTE_VM_URL}/ollama/models", timeout=8)
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        models = data.get("models", [])
        # Prefix each model name so the UI can distinguish remote from local
        prefixed = [f"remote:{m}" for m in models]
        return jsonify({"models": prefixed, "raw_models": models, "url": REMOTE_VM_URL})
    except _http.exceptions.Timeout:
        return jsonify({"models": [], "error": f"Таймаут при подключении к Remote VM ({REMOTE_VM_URL})"})
    except _http.exceptions.ConnectionError:
        return jsonify({"models": [], "error": f"Нет соединения с Remote VM ({REMOTE_VM_URL})"})
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"models": [], "error": str(exc)})


# ---------------------------------------------------------------------------
# Remote VM polling job queue — no-ngrok alternative
# ---------------------------------------------------------------------------
# Workflow:
#   1. Local UI  → POST /remote/jobs           (push a new job)
#   2. Colab     → GET  /remote/jobs/pending   (poll for new work)
#   3. Colab     → POST /remote/jobs/<id>/result (post result)
#   4. Local UI  → GET  /remote/jobs/<id>       (poll for result)
# ---------------------------------------------------------------------------

@app.route("/remote/jobs", methods=["POST"])
def remote_jobs_push():
    """Push a new job onto the queue.  Returns {job_id, ok}."""
    body = request.get_json(silent=True) or {}
    if not body:
        return jsonify({"ok": False, "error": "Empty body"}), 400
    job_id = str(uuid.uuid4())
    job = {
        "id": job_id,
        "status": "pending",
        "payload": body,
        "result": None,
        "created_at": time.time(),
    }
    with _remote_jobs_lock:
        _remote_jobs[job_id] = job
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/remote/jobs/pending", methods=["GET"])
def remote_jobs_pending():
    """Return all pending jobs (for Colab to poll).  Marks returned jobs as 'running'."""
    with _remote_jobs_lock:
        pending = [j for j in _remote_jobs.values() if j["status"] == "pending"]
        for j in pending:
            _remote_jobs[j["id"]]["status"] = "running"
    return jsonify({"jobs": pending})


@app.route("/remote/jobs/<job_id>/result", methods=["POST"])
def remote_job_result(job_id):
    """Colab posts the result for a completed job."""
    body = request.get_json(silent=True) or {}
    with _remote_jobs_lock:
        if job_id not in _remote_jobs:
            return jsonify({"ok": False, "error": "Unknown job"}), 404
        _remote_jobs[job_id]["status"] = "done"
        _remote_jobs[job_id]["result"] = body.get("result")
    return jsonify({"ok": True})


@app.route("/remote/jobs/<job_id>", methods=["GET", "DELETE"])
def remote_job_get(job_id):
    """GET: return the status and result of a job (local UI polls this).
    DELETE: remove the job from the queue.
    """
    if request.method == "DELETE":
        with _remote_jobs_lock:
            removed = _remote_jobs.pop(job_id, None)
        return jsonify({"ok": removed is not None})
    with _remote_jobs_lock:
        job = _remote_jobs.get(job_id)
    if not job:
        return jsonify({"ok": False, "error": "Unknown job"}), 404
    return jsonify({"ok": True, "job": job})


@app.route("/remote/jobs", methods=["GET"])
def remote_jobs_list():
    """Return all jobs sorted by creation time (for the dashboard)."""
    with _remote_jobs_lock:
        jobs = list(_remote_jobs.values())
    return jsonify({"jobs": sorted(jobs, key=lambda j: j.get("created_at", 0), reverse=True)})


# ---------------------------------------------------------------------------
# Goose agent — on-machine AI coding agent (github.com/block/goose)
# ---------------------------------------------------------------------------

@app.route("/goose/run", methods=["POST"])
def goose_run():
    """Run goose CLI in a project directory with a given instruction.

    Body: {"instruction": "...", "project_dir": "...", "model": "..."}
    Returns: {"ok": True/False, "output": "...", "error": "..."}

    Goose must be installed: curl -fsSL .../download_cli.sh | bash
    Configure LLM provider in goose config (~/.config/goose/config.yaml)
    pointing to Ollama: provider: openai, base_url: http://127.0.0.1:11434/v1
    """
    import shutil
    body        = request.get_json(silent=True) or {}
    instruction = body.get("instruction", "").strip()
    project_dir = body.get("project_dir", "").strip()
    timeout_s   = int(body.get("timeout", 120))

    if not instruction:
        return jsonify({"ok": False, "error": "instruction required"})

    goose_bin = shutil.which("goose") or shutil.which("goose.exe")
    if not goose_bin:
        return jsonify({"ok": False, "error_code": "GOOSE_NOT_FOUND", "error": "goose CLI not found in PATH. Install: curl -fsSL https://github.com/block/goose/releases/download/stable/download_cli.sh | bash"})

    # Validate project_dir: must be an existing absolute path to prevent traversal.
    # If not provided or invalid, fall back to the server's working directory.
    safe_cwd = os.getcwd()
    if project_dir:
        abs_dir = os.path.realpath(project_dir)
        if os.path.isdir(abs_dir):
            safe_cwd = abs_dir
        else:
            return jsonify({"ok": False, "error": f"project_dir не найден или не является директорией: {project_dir}"})

    try:
        result = subprocess.run(  # noqa: S603
            [goose_bin, "run", "--text", instruction],
            cwd=safe_cwd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        output = (result.stdout or "") + (result.stderr or "")
        return jsonify({"ok": result.returncode == 0, "output": output, "return_code": result.returncode})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": f"goose timeout after {timeout_s}s"})
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"ok": False, "error": str(exc)})


@app.route("/goose/check", methods=["GET"])
def goose_check():
    """Return whether the goose CLI is installed and reachable in PATH.

    Returns: {"installed": true/false, "path": "...", "version": "..."}
    """
    import shutil
    goose_bin = shutil.which("goose") or shutil.which("goose.exe")
    if not goose_bin:
        return jsonify({"installed": False, "path": None, "version": None})
    version = ""
    try:
        result = subprocess.run(  # noqa: S603
            [goose_bin, "--version"],
            capture_output=True, text=True, timeout=5,
        )
        output = (result.stdout or result.stderr or "").strip()
        version = output.splitlines()[0] if output else ""
    except (subprocess.SubprocessError, OSError):
        version = ""
    return jsonify({"installed": True, "path": goose_bin, "version": version})


# ---------------------------------------------------------------------------
# Open Agentic Framework — multi-agent orchestrator
# ---------------------------------------------------------------------------

@app.route("/oaf/task", methods=["POST"])
def oaf_task():
    """Submit a task to the Open Agentic Framework.

    Body: {"task": "...", "agent": "...", "context": {...}}
    Returns the framework's JSON response.
    Configure OAF_URL in settings pointing to your docker-compose instance.
    """
    if not OAF_BASE:
        return jsonify({"ok": False, "error": "Open Agentic Framework URL не настроен — укажите OAF URL в настройках (☰)"})
    body = request.get_json(silent=True) or {}
    try:
        resp = _http.post(
            f"{OAF_BASE}/api/task",
            json=body,
            timeout=int(os.environ.get("OLLAMA_TIMEOUT", 120)),
        )
        resp.raise_for_status()
        return jsonify({"ok": True, "data": resp.json()})
    except _http.exceptions.ConnectionError:
        return jsonify({"ok": False, "error": f"Нет соединения с OAF по адресу {OAF_BASE}"})
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"ok": False, "error": str(exc)})


@app.route("/oaf/status", methods=["GET"])
def oaf_status():
    """Probe the Open Agentic Framework health endpoint."""
    if not OAF_BASE:
        return jsonify({"ok": False, "url": "", "error": "OAF URL not configured"})
    try:
        resp = _http.get(f"{OAF_BASE}/health", timeout=5)
        return jsonify({"ok": resp.status_code < 400, "url": OAF_BASE, "status_code": resp.status_code})
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"ok": False, "url": OAF_BASE, "error": str(exc)})


# ---------------------------------------------------------------------------
# 3D model generation service (TripoSR / Hunyuan3D / NVIDIA 3d-object-generation)
# ---------------------------------------------------------------------------

@app.route("/triposr/generate", methods=["POST"])
def triposr_generate():
    """Generate a 3D model from a text prompt or image.

    Body: {"prompt": "...", "image_base64": "<optional base64 PNG/JPEG>",
           "format": "glb|obj|stl", "steps": 50}
    Forwards the request to the local TripoSR-compatible HTTP service (TRIPOSR_URL).
    The service returns {"ok": True, "model_url": "...", "format": "glb"} or
    {"ok": True, "model_b64": "<base64 encoded 3D file>"}.

    Local service setup options:
    - TripoSR: https://github.com/VAST-AI-Research/TripoSR (with a thin Flask wrapper)
    - Hunyuan3D-2: https://github.com/Tencent-Hunyuan/Hunyuan3D-2
    - NVIDIA 3D Blueprint: https://github.com/NVIDIA-AI-Blueprints/3d-object-generation
    """
    if not TRIPOSR_BASE:
        return jsonify({"ok": False, "error": "3D generation service URL не настроен — укажите TripoSR URL в настройках (☰)"})
    body = request.get_json(silent=True) or {}
    if not body.get("prompt") and not body.get("image_base64"):
        return jsonify({"ok": False, "error": "Необходим prompt или image_base64"})
    try:
        timeout = int(os.environ.get("OLLAMA_TIMEOUT", 300))
        resp = _http.post(
            f"{TRIPOSR_BASE}/generate",
            json=body,
            timeout=timeout,
        )
        resp.raise_for_status()
        return jsonify({"ok": True, "data": resp.json()})
    except _http.exceptions.ConnectionError:
        return jsonify({"ok": False, "error": f"Нет соединения с 3D-сервисом по адресу {TRIPOSR_BASE}"})
    except _http.exceptions.Timeout:
        return jsonify({"ok": False, "error": "Таймаут 3D-генерации — модель ещё загружается или слишком сложный запрос"})
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"ok": False, "error": str(exc)})


# ---------------------------------------------------------------------------
# AI website builder (build-a-site / AI-Website-Builder style)
# ---------------------------------------------------------------------------

@app.route("/webbuilder/generate", methods=["POST"])
def webbuilder_generate():
    """Build a website from a text prompt via a local AI website builder service.

    Body: {"prompt": "...", "style": "tailwind|bootstrap|plain",
           "pages": ["index", "about"], "model": "<optional override>"}
    Alternatively, if no WEBBUILDER_URL is set, generates HTML directly
    using the local Ollama/LM Studio model specified in "model".

    Local service setup options:
    - build-a-site: https://github.com/i-dream-of-ai/build-a-site
    - AI-Website-Builder: https://github.com/Ratna-Babu/Ai-Website-Builder
    """
    body = request.get_json(silent=True) or {}
    prompt = body.get("prompt", "").strip()
    if not prompt:
        return jsonify({"ok": False, "error": "prompt обязателен"})

    # If external website builder service is configured, forward to it.
    # On connection failure fall through to the local LLM fallback below.
    if WEBBUILDER_BASE:
        try:
            timeout = int(os.environ.get("OLLAMA_TIMEOUT", 300))
            resp = _http.post(
                f"{WEBBUILDER_BASE}/generate",
                json=body,
                timeout=timeout,
            )
            resp.raise_for_status()
            return jsonify({"ok": True, "data": resp.json()})
        except (_http.exceptions.ConnectionError, _http.exceptions.Timeout):
            pass  # External service unavailable — fall through to local LLM below
        except Exception as exc:  # pylint: disable=broad-except
            return jsonify({"ok": False, "error": str(exc)})

    # Fallback: generate HTML directly using local Ollama / LM Studio / TGWUI.
    model = body.get("model", "").strip()
    style = body.get("style", "tailwind").strip()

    # Choose CDN for the selected style framework
    _style_cdn = {
        "tailwind": '<script src="https://cdn.tailwindcss.com"></script>',
        "bootstrap": '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"><script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>',
        "plain": "",
    }.get(style, "")

    system_prompt = (
        "You are an expert full-stack web developer. Generate a COMPLETE, STANDALONE, "
        "production-ready single-page website as a single HTML file.\n\n"
        f"CSS framework: {style}. Include CDN links as needed.\n\n"
        "STRICT REQUIREMENTS — every generated page MUST have ALL of these:\n"
        "1. Valid HTML5 with <!DOCTYPE html>, <html lang>, <head> with charset+viewport+title.\n"
        "2. A sticky navigation bar with working SCROLL links (href='#section-id') to all sections.\n"
        "3. At least 4 distinct, uniquely-styled full-width sections with id attributes.\n"
        "4. Hero section with headline, sub-headline, and a prominent CTA button.\n"
        "5. Features/services section with cards or icon grid (minimum 3 items).\n"
        "6. A contact form with name, email, message fields and a submit button "
        "   (use JS alert on submit — no actual server required).\n"
        "7. A footer with copyright, social links, and back-to-top button.\n"
        "8. Smooth scroll behaviour: <script>document.querySelectorAll('a[href^=\"#\"]').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();document.querySelector(a.getAttribute('href'))?.scrollIntoView({behavior:'smooth'})}));</script>\n"
        "9. Responsive design: desktop + mobile (min-width breakpoints or flexbox/grid).\n"
        "10. Visually rich: gradients, box-shadows, hover transitions, colour palette.\n"
        "11. ALL buttons and nav links must be CLICKABLE and FUNCTIONAL (scroll or JS action).\n\n"
        "OUTPUT RULES:\n"
        "- Output ONLY raw HTML. Do NOT wrap in ``` code fences.\n"
        "- Do NOT include any explanation text before or after the HTML.\n"
        "- The first character of your response must be '<' (start of <!DOCTYPE html>).\n"
    )
    user_prompt = (
        f"Create a complete, richly-styled, fully-functional single-page website for:\n\n{prompt}\n\n"
        "Remember: all sections must be unique, all links must work, the design must be beautiful "
        "and modern. Start your response with <!DOCTYPE html>."
    )

    def _strip_html_fences(raw: str) -> str:
        """Remove markdown code fences that some models add around HTML output."""
        raw = raw.strip()
        # Strip optional language tag and leading newline(s) after opening fence
        raw = re.sub(r'^```[a-zA-Z]*\s*\n', '', raw)
        # Strip trailing closing fence
        raw = re.sub(r'\n```\s*$', '', raw)
        return raw.strip()

    try:
        if model.startswith("lmstudio:") and LM_STUDIO_BASE:
            real_model = model[len("lmstudio:"):]
            r = _http.post(
                f"{LM_STUDIO_BASE}/v1/chat/completions",
                json={"model": real_model, "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ], "stream": False},
                timeout=int(os.environ.get("OLLAMA_TIMEOUT", 300)),
            )
            r.raise_for_status()
            html = _strip_html_fences(r.json()["choices"][0]["message"]["content"])
        elif model.startswith("tgwui:") and TGWUI_BASE:
            real_model = model[len("tgwui:"):]
            r = _http.post(
                f"{TGWUI_BASE}/v1/chat/completions",
                json={"model": real_model, "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ], "stream": False},
                timeout=int(os.environ.get("OLLAMA_TIMEOUT", 300)),
            )
            r.raise_for_status()
            html = _strip_html_fences(r.json()["choices"][0]["message"]["content"])
        else:
            # Default: Ollama — auto-pick first available model if none specified
            if not model:
                try:
                    _mr = _http.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
                    _mr.raise_for_status()
                    _ml = _mr.json().get("models", [])
                    if _ml:
                        model = _ml[0].get("name", "")
                except Exception:
                    pass
            r = _http.post(
                f"{OLLAMA_BASE}/api/chat",
                json={"model": model, "stream": False, "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ]},
                timeout=int(os.environ.get("OLLAMA_TIMEOUT", 300)),
            )
            r.raise_for_status()
            html = _strip_html_fences(r.json().get("message", {}).get("content", ""))
        return jsonify({"ok": True, "data": {"html": html}})
    except _http.exceptions.Timeout:
        return jsonify({"ok": False, "error": "Таймаут — модель не отвечает"})
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"ok": False, "error": str(exc)})


# ---------------------------------------------------------------------------
# Video editor backend (omniclip / twick style)
# ---------------------------------------------------------------------------

@app.route("/videditor/project", methods=["POST"])
def videditor_project():
    """Send a video editing script/EDL to the video editor backend.

    Body: {"script": "...", "files": ["path1", "path2"], "format": "mp4",
           "model": "<optional LLM model to first generate the EDL script>"}
    If VIDEDITOR_URL is set, forwards the assembled EDL to the backend.
    Otherwise generates an EDL/JSON script using the local LLM.

    Local service setup options:
    - omniclip: https://github.com/omni-media/omniclip (add thin HTTP API layer)
    - twick: https://github.com/ncounterspecialist/twick
    """
    body = request.get_json(silent=True) or {}
    description = body.get("description", body.get("script", "")).strip()
    if not description:
        return jsonify({"ok": False, "error": "description или script обязателен"})

    # If external video editor service is configured, forward to it.
    # On connection failure fall through to the local LLM fallback below.
    if VIDEDITOR_BASE:
        try:
            timeout = int(os.environ.get("OLLAMA_TIMEOUT", 300))
            resp = _http.post(
                f"{VIDEDITOR_BASE}/project",
                json=body,
                timeout=timeout,
            )
            resp.raise_for_status()
            return jsonify({"ok": True, "data": resp.json()})
        except (_http.exceptions.ConnectionError, _http.exceptions.Timeout):
            pass  # External service unavailable — fall through to local LLM below
        except Exception as exc:  # pylint: disable=broad-except
            return jsonify({"ok": False, "error": str(exc)})

    # Fallback: use local LLM to generate an EDL/JSON editing script.
    model = body.get("model", "").strip()
    files = body.get("files", [])
    system_prompt = (
        "You are an expert video editor. "
        "Generate a JSON editing script (EDL) describing the video project. "
        "The JSON must have: {\"clips\": [{\"file\": str, \"start\": float, \"end\": float, \"text_overlay\": str}], "
        "\"transitions\": [{\"type\": str, \"at\": float}], \"audio\": {\"music\": str, \"volume\": float}}. "
        "Output only valid JSON — no explanations, no markdown fences."
    )
    file_list = ", ".join(files) if files else "(no files specified)"
    user_prompt = f"Create a video editing script for: {description}\nAvailable files: {file_list}"
    try:
        if model.startswith("lmstudio:") and LM_STUDIO_BASE:
            real_model = model[len("lmstudio:"):]
            r = _http.post(
                f"{LM_STUDIO_BASE}/v1/chat/completions",
                json={"model": real_model, "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ], "stream": False},
                timeout=int(os.environ.get("OLLAMA_TIMEOUT", 300)),
            )
            r.raise_for_status()
            edl = r.json()["choices"][0]["message"]["content"]
        elif model.startswith("tgwui:") and TGWUI_BASE:
            real_model = model[len("tgwui:"):]
            r = _http.post(
                f"{TGWUI_BASE}/v1/chat/completions",
                json={"model": real_model, "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ], "stream": False},
                timeout=int(os.environ.get("OLLAMA_TIMEOUT", 300)),
            )
            r.raise_for_status()
            edl = r.json()["choices"][0]["message"]["content"]
        else:
            if not model:
                try:
                    _mr = _http.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
                    _mr.raise_for_status()
                    _ml = _mr.json().get("models", [])
                    if _ml:
                        model = _ml[0].get("name", "")
                except Exception:
                    pass
            r = _http.post(
                f"{OLLAMA_BASE}/api/chat",
                json={"model": model, "stream": False, "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ]},
                timeout=int(os.environ.get("OLLAMA_TIMEOUT", 300)),
            )
            r.raise_for_status()
            edl = r.json().get("message", {}).get("content", "")
        return jsonify({"ok": True, "data": {"edl": edl}})
    except _http.exceptions.Timeout:
        return jsonify({"ok": False, "error": "Таймаут — модель не отвечает"})
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"ok": False, "error": str(exc)})


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
        except _http.exceptions.Timeout:
            _oto = int(os.environ.get("OLLAMA_TIMEOUT", 120))
            yield f'data: {{"error":"Ollama не ответил за {_oto} с — модель слишком медленная. Попробуйте увеличить OLLAMA_TIMEOUT или выбрать меньшую модель."}}\n\n'
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
        except _http.exceptions.Timeout:
            _oto = int(os.environ.get("OLLAMA_TIMEOUT", 120))
            yield f'data: {{"error":"Ollama не ответил за {_oto} с — модель слишком медленная. Попробуйте увеличить OLLAMA_TIMEOUT или выбрать меньшую модель."}}\n\n'
        except _http.exceptions.ConnectionError:
            yield "data: {\"error\":\"Cannot connect to Ollama\"}\n\n"
        except Exception as exc:  # pylint: disable=broad-except
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return Response(
        stream_with_context(_stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _parse_modelfile(content: str) -> dict:
    """Parse a Modelfile into a dict for Ollama's structured /api/create API.

    Supports FROM, SYSTEM (triple-quoted or single-quoted), and PARAMETER
    directives.  Returns::

        {
            "from": "base-model-name",   # required by new Ollama API
            "system": "system prompt",   # optional
            "parameters": {"temperature": 0.3, ...},  # optional
        }

    The new-style API (Ollama ≥ 0.6) uses these fields instead of the
    deprecated ``modelfile`` string parameter.
    """
    result: dict = {"from": None, "system": None, "parameters": {}}
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith("#"):
            i += 1
            continue
        upper = line.upper()
        if upper.startswith("FROM "):
            result["from"] = line[5:].strip()
        elif upper.startswith("SYSTEM"):
            rest = line[6:].strip()
            if rest.startswith('"""'):
                # Triple-quoted block — may span multiple lines
                rest = rest[3:]
                parts = []
                if '"""' in rest:
                    result["system"] = rest[:rest.index('"""')]
                    i += 1
                    continue
                parts.append(rest)
                while i + 1 < len(lines):
                    i += 1
                    chunk = lines[i]
                    if '"""' in chunk:
                        parts.append(chunk[:chunk.index('"""')])
                        break
                    parts.append(chunk)
                result["system"] = "\n".join(parts)
            elif rest.startswith('"'):
                result["system"] = rest.strip('"')
            else:
                result["system"] = rest
        elif upper.startswith("PARAMETER "):
            parts = line.split(None, 2)
            if len(parts) >= 3:
                param_name = parts[1].lower()
                param_val  = parts[2]
                try:
                    result["parameters"][param_name] = int(param_val)
                except ValueError:
                    try:
                        result["parameters"][param_name] = float(param_val)
                    except ValueError:
                        result["parameters"][param_name] = param_val
        i += 1
    return result


def _ollama_create_payload(model_name: str, modelfile: str) -> dict:
    """Build the best Ollama /api/create payload for the given Modelfile.

    Sends both the new structured fields (``from``, ``system``, ``parameters``)
    AND the legacy ``modelfile`` string so the request works regardless of which
    Ollama version is installed:

    * Ollama < 0.6  — uses ``name`` + ``modelfile`` (ignores ``from``/``system``)
    * Ollama ≥ 0.6  — uses ``model`` + ``from`` + ``system`` + ``parameters``
                       (ignores ``modelfile``)

    If the Modelfile has no FROM directive we only send the legacy format.
    """
    parsed = _parse_modelfile(modelfile)
    if not parsed.get("from"):
        # No FROM directive — only legacy format is possible.
        return {"name": model_name, "modelfile": modelfile, "stream": True}
    # Include BOTH formats so any Ollama version handles the request.
    payload: dict = {
        # New-style API (Ollama ≥ 0.6)
        "model": model_name,
        "from": parsed["from"],
        # Legacy API (Ollama < 0.6)
        "name": model_name,
        "modelfile": modelfile,
        "stream": True,
    }
    if parsed.get("system"):
        payload["system"] = parsed["system"]
    if parsed.get("parameters"):
        payload["parameters"] = parsed["parameters"]
    return payload


@app.route("/ollama/create", methods=["POST"])
def ollama_create():
    """Create a custom Ollama model from a Modelfile string.

    Body: {"name": "my-coder", "modelfile": "FROM qwen:latest\\nSYSTEM ..."}
    Returns a streaming text/event-stream response with progress lines.
    Supports both the new Ollama ≥ 0.6 structured API and the legacy
    ``modelfile`` string parameter.
    """
    body = request.get_json(silent=True) or {}
    name      = body.get("name", "").strip()
    modelfile = body.get("modelfile", "").strip()
    if not name:
        return jsonify({"error": "model name required"}), 400
    if not modelfile:
        return jsonify({"error": "modelfile content required"}), 400

    payload = _ollama_create_payload(name, modelfile)

    def _stream():
        try:
            with _http.post(
                f"{OLLAMA_BASE}/api/create",
                json=payload,
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
                    yield f"data: {json.dumps({'status': obj.get('status', ''), 'error': obj.get('error', '')})}\n\n"
            _done_msg = f"Model '{name}' created successfully!"
            yield f"data: {json.dumps({'status': _done_msg, 'done': True})}\n\n"
        except _http.exceptions.Timeout:
            _oto = int(os.environ.get("OLLAMA_TIMEOUT", 120))
            yield f'data: {{"error":"Ollama не ответил за {_oto} с — модель слишком медленная. Попробуйте увеличить OLLAMA_TIMEOUT или выбрать меньшую модель."}}\n\n'
        except _http.exceptions.ConnectionError:
            yield "data: {\"error\":\"Cannot connect to Ollama\"}\n\n"
        except Exception as exc:  # pylint: disable=broad-except
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

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

    # Use the same strong auto-generation prompt but fixed to the requested language
    sys_prompt = (
        f"Ты DRGR Code Generator — эксперт-программист ({language}) на базе Qwen.\n"
        f"Генерируй ПОЛНЫЙ, РАБОЧИЙ, ГОТОВЫЙ К ЗАПУСКУ {language}-код.\n"
        "КРИТИЧЕСКИ ВАЖНО — КАЧЕСТВО КОДА:\n"
        "  - СТРОГО ЗАПРЕЩЕНО генерировать demo-версии, заглушки, placeholder-код.\n"
        "  - ЗАПРЕЩЕНЫ любые комментарии: '# TODO', '# implement later', '# ваш код', "
        "'// TODO', 'pass', 'raise NotImplementedError', '// add code here', "
        "'В реальном приложении здесь...', 'This is a demo', 'placeholder'.\n"
        "  - КАЖДАЯ функция должна иметь ПОЛНУЮ, РАБОЧУЮ реализацию — никаких пустых тел.\n"
        "  - Генерируй ПОЛНЫЙ, РАБОЧИЙ, ГОТОВЫЙ К ЗАПУСКУ код с первой попытки.\n"
        f"Возвращай ТОЛЬКО код в блоке ```{language} ... ``` без пояснений вне блока.\n"
        "НЕ спрашивай уточнений — сразу генерируй полный рабочий код.\n\n"
        f"Задание: {prompt}"
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
        "Ты DRGR HTML Generator — экспертный веб-разработчик на базе Qwen.\n"
        "Генерируй красивые, ПОЛНЫЕ, РАБОЧИЕ, отзывчивые HTML страницы.\n"
        "ВСЕГДА возвращай один полный HTML файл (<!DOCTYPE html>...) "
        "со встроенным CSS и JavaScript.\n"
        "Используй современный CSS (flexbox/grid), красивые цвета, плавные анимации.\n"
        "Выводи ТОЛЬКО HTML код без пояснений и комментариев вне кода.\n"
        "СТРОГО ЗАПРЕЩЕНО: заглушки, demo-версии, placeholder-код, "
        "незаполненные функции, комментарии вида '// TODO', '// добавить логику', "
        "'/* реализация */', 'console.log(\"not implemented\")', 'В реальном приложении здесь...'.\n"
        "Если задание содержит 3D-объекты — ОБЯЗАТЕЛЬНО подключи Three.js через CDN "
        "и создавай реальную 3D-сцену с WebGLRenderer.\n"
        "Генерируй ПОЛНЫЙ, РАБОЧИЙ, ГОТОВЫЙ К ЗАПУСКУ код с первой попытки.\n\n"
        f"Задание: {prompt}"
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


# Free public APIs usable without any API key — referenced in system prompts.
_FREE_PUBLIC_APIS_HINT = (
    "используй реальные БЕСПЛАТНЫЕ публичные API без ключей: "
    "https://api.open-meteo.com/v1/forecast?latitude=55.75&longitude=37.62&current_weather=true (погода), "
    "https://api.exchangerate-api.com/v4/latest/USD (курсы валют), "
    "https://api.coindesk.com/v1/bpi/currentprice.json (Bitcoin), "
    "https://worldtimeapi.org/api/ip (текущее время), "
    "https://randomuser.me/api/ (случайный пользователь), "
    "https://jsonplaceholder.typicode.com/posts (тест-данные). "
    "ЗАПРЕЩЕНО: 'YOUR_API_KEY', 'вставьте ключ', 'API ключ здесь' — только рабочий код без ключей"
)

# Default Qwen-optimised system prompt used when instructions.json has none.
_DEFAULT_HTML_SYSTEM_PROMPT = (
    "Ты DRGR HTML Generator — экспертный веб-разработчик на базе Qwen.\n"
    "Генерируй красивые, ПОЛНЫЕ, РАБОЧИЕ, отзывчивые HTML страницы.\n"
    "ВСЕГДА возвращай один полный HTML файл (<!DOCTYPE html>...) "
    "со встроенным CSS и JavaScript.\n"
    "Используй современный CSS (flexbox/grid), красивые цвета, плавные анимации.\n"
    "Выводи ТОЛЬКО HTML код без пояснений и комментариев вне кода.\n"
    "СТРОГО ЗАПРЕЩЕНО: заглушки, demo-версии, placeholder-код, "
    "незаполненные функции, комментарии вида '// TODO', '// добавить логику', "
    "'/* реализация */', 'console.log(\"not implemented\")', 'В реальном приложении здесь...'.\n"
    "Если задание содержит 3D-объекты, объёмные фигуры, кубы, сферы, анимации — "
    "ОБЯЗАТЕЛЬНО подключи Three.js через CDN: "
    "<script src=\"https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.min.js\"></script>. "
    "Создавай реальную 3D-сцену с WebGLRenderer, PerspectiveCamera, настоящей геометрией "
    "(BoxGeometry, SphereGeometry и т.д.), материалами (MeshStandardMaterial или MeshPhongMaterial), "
    "AmbientLight/DirectionalLight и анимационным циклом requestAnimationFrame. "
    "Добавь вращение объекта в animate(). "
    "НЕ используй canvas 2D для имитации 3D — используй настоящий Three.js.\n"
    "Если задание содержит расширение браузера (extension) — пиши ПОЛНЫЙ "
    "рабочий код всех файлов: manifest.json, background.js, content.js, popup.html. "
    "Код должен немедленно работать после установки без доработки. "
    "НЕ пиши 'В реальном расширении...' или 'здесь будет логика' — только реальный код.\n"
    "Если задание требует данных из интернета (погода, курсы валют, новости и т.д.) — "
    f"{_FREE_PUBLIC_APIS_HINT}.\n\n"
    "Ты также знаешь протокол DRGRBrowserAgent v1.0 — автономного агента для управления "
    "браузером через DRGR-визор. Агент работает в цикле: наблюдение → планирование → действие "
    "→ проверка → логирование. Команды агента: NAVIGATE, CLICK, TYPE, WAIT, SWITCH_TAB, "
    "SCROLL, SCREENSHOT, GENERATE_IMAGE, NOOP. "
    "GENERATE_IMAGE — команда для генерации изображений через локальный Stable Diffusion или ComfyUI. "
    "Поля: prompt (обязательно), negative_prompt, width, height, steps, cfg_scale, save_as. "
    "ВАЖНО: при задаче генерации изображения ВСЕГДА используй GENERATE_IMAGE — "
    "никогда не возвращай NOOP для задач генерации изображений. "
    "Вывод агента содержит cycle_state (status, current_step, "
    "max_steps), thoughts (observation, state_analysis, plan_short, risks) и commands. "
    "Особые состояния: blocked_captcha (обнаружена капча), finished_success/finished_error. "
    "При генерации HTML-визора для браузерного агента учитывай эту схему."
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

    # LM Studio model support (OpenAI-compatible /v1/chat/completions)
    is_lms_gen = model.startswith(_LM_STUDIO_PREFIX)

    if is_lms_gen:
        real_model = model[len(_LM_STUDIO_PREFIX):]
        lms_url    = _resolve_lms_url()

        def _stream_lms_gen():
            if not lms_url:
                yield 'data: {"error":"LM Studio URL не настроен — укажите URL в настройках (☰)"}\n\n'
                return
            try:
                resp = _http.post(
                    f"{lms_url}/v1/chat/completions",
                    json={
                        "model": real_model,
                        "messages": [
                            {"role": "system", "content": sys_prompt},
                            {"role": "user",   "content": f"Задание: {prompt}"},
                        ],
                        "stream": True,
                    },
                    stream=True,
                    timeout=_LMS_TIMEOUT,
                )
                resp.raise_for_status()
                for raw_line in resp.iter_lines():
                    if not raw_line:
                        continue
                    line_str = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                    if line_str.startswith("data: "):
                        line_str = line_str[6:]
                    if line_str.strip() in ("[DONE]", ""):
                        _record_generation("html", model, prompt)
                        yield "data: [DONE]\n\n"
                        return
                    try:
                        chunk = json.loads(line_str)
                    except ValueError:
                        continue
                    delta  = chunk.get("choices", [{}])[0].get("delta", {})
                    token  = delta.get("content", "")
                    finish = chunk.get("choices", [{}])[0].get("finish_reason")
                    if token:
                        yield f"data: {json.dumps({'token': token})}\n\n"
                    if finish:
                        _record_generation("html", model, prompt)
                        yield "data: [DONE]\n\n"
                        return
            except _http.exceptions.Timeout:
                yield f'data: {{"error":"Нет ответа от LM Studio за {_LMS_TIMEOUT} с — модель слишком медленная."}}\n\n'
            except _http.exceptions.ConnectionError:
                _resolve_lms_url()  # re-discover for next request
                yield f'data: {json.dumps({"error": f"Нет соединения с LM Studio по адресу {lms_url} — проверьте, что LM Studio запущен"})}\n\n'
            except Exception as exc:  # pylint: disable=broad-except
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"

        return Response(
            stream_with_context(_stream_lms_gen()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    def _stream():
        try:
            resp = _http.post(
                f"{OLLAMA_BASE}/api/generate",
                json={"model": model, "prompt": full_prompt, "stream": True},
                stream=True,
                timeout=int(os.environ.get("OLLAMA_TIMEOUT", 240)),
            )
            if resp.status_code == 500:
                err_body = ""
                try:
                    err_body = resp.json().get("error", resp.text[:200])
                except Exception:  # pylint: disable=broad-except
                    err_body = resp.text[:200]
                _err_msg = f'Ollama ошибка 500: {err_body}. Проверьте, что модель "{model}" загружена (ollama pull {model}).'
                yield f"data: {json.dumps({'error': _err_msg})}\n\n"
                return
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
        except _http.exceptions.Timeout:
            _oto = int(os.environ.get("OLLAMA_TIMEOUT", 120))
            yield f'data: {{"error":"Ollama не ответил за {_oto} с — модель слишком медленная. Попробуйте увеличить OLLAMA_TIMEOUT или выбрать меньшую модель."}}\n\n'
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
# Auto-language code generator — model decides what language to use
# ---------------------------------------------------------------------------
_DEFAULT_AUTO_SYSTEM_PROMPT = (
    "Ты DRGR Code Generator — эксперт-программист на базе Qwen.\n"
    "Проанализируй задание и АВТОМАТИЧЕСКИ выбери наиболее подходящий язык программирования.\n"
    "Для веб-страниц, лендингов, игр в браузере, дашбордов — генерируй самодостаточный HTML "
    "со встроенным CSS и JavaScript (```html блок, полный <!DOCTYPE html> документ).\n"
    "Для алгоритмов, скриптов, утилит, обработки данных — Python (```python блок).\n"
    "Для front-end без сервера — JavaScript (```javascript блок).\n"
    "Для Android приложений — Kotlin/Java (```kotlin или ```java блок). "
    "APK — это Android Package Kit, исполняемый файл Android-приложения. "
    "Для создания APK используй Android Studio или Gradle (./gradlew assembleDebug). "
    "Укажи структуру проекта: app/src/main/AndroidManifest.xml, MainActivity.kt, build.gradle. "
    "Разрешения GPS: ACCESS_FINE_LOCATION, ACCESS_COARSE_LOCATION в AndroidManifest.xml. "
    "Android-эмулятор (AVD) запускается через Android Studio или командой: "
    "emulator -avd <имя_эмулятора>.\n"
    "Для iOS приложений — Swift/SwiftUI (```swift блок). "
    "IPA — это iOS App Archive. Для установки на устройство нужен Apple Developer аккаунт.\n"
    "Для Telegram ботов, Discord ботов — Python (```python блок) с aiogram 3.x или python-telegram-bot.\n"
    "КРИТИЧЕСКИ ВАЖНО — КАЧЕСТВО КОДА:\n"
    "  - СТРОГО ЗАПРЕЩЕНО генерировать demo-версии, заглушки, placeholder-код.\n"
    "  - ЗАПРЕЩЕНЫ любые комментарии: '# TODO', '# implement later', '# ваш код', "
    "'// TODO', 'pass', 'raise NotImplementedError', '// add code here', "
    "'В реальном приложении здесь...', 'This is a demo', 'placeholder'.\n"
    "  - КАЖДАЯ функция должна иметь ПОЛНУЮ, РАБОЧУЮ реализацию — никаких пустых тел.\n"
    "  - Генерируй ПОЛНЫЙ, РАБОЧИЙ, ГОТОВЫЙ К ЗАПУСКУ код с первой попытки.\n"
    "  - Для игр: полная игровая механика, управление, счёт, анимации, конец игры.\n"
    "  - Для расширений браузера: все файлы manifest.json, background.js, content.js, popup.html "
    "с полной рабочей логикой, обработкой событий, хранением данных.\n"
    "КРИТИЧЕСКИ ВАЖНО для Python-кода:\n"
    "  - Используй ТОЛЬКО стандартную библиотеку Python (os, sys, json, math, random, datetime, "
    "re, pathlib, collections, itertools, functools, string, io, time, hashlib и т.д.).\n"
    "  - НЕ импортируй сторонние пакеты (requests, numpy, pandas, flask, django и т.д.) "
    "если задание явно не требует этого. Сторонние пакеты могут быть не установлены.\n"
    "  - Если нужна работа с HTTP — используй urllib.request из стандартной библиотеки.\n"
    "  - Код должен выполняться без ошибок в чистом окружении Python.\n"
    "КРИТИЧЕСКИ ВАЖНО для aiogram 3.x:\n"
    "  - В декораторах @router.message() и @router.callback_query() ВСЕГДА ставь "
    "позиционные фильтры (F.text, Command('start'), F.text.startswith('/cmd') и т.д.) "
    "ПЕРЕД именованными аргументами (state=States.value).\n"
    "  - ПРАВИЛЬНО: @router.message(F.text.startswith('/generate'), "
    "state=MediaStates.waiting)\n"
    "  - НЕПРАВИЛЬНО: @router.message(state=MediaStates.waiting, "
    "F.text.startswith('/generate'))  # SyntaxError!\n"
    "  - Это Python-правило: позиционные аргументы не могут идти после именованных.\n"
    "КРИТИЧЕСКИ ВАЖНО для JavaScript-кода (Node.js):\n"
    "  - Код выполняется в Node.js — НИКАКИХ browser/Chrome Extension API.\n"
    "  - ЗАПРЕЩЕНО использовать: chrome.storage, chrome.runtime, chrome.tabs, browser.*, "
    "window, document, localStorage, sessionStorage, fetch (используй https модуль вместо), "
    "XMLHttpRequest — эти API доступны ТОЛЬКО в браузере или Chrome Extension.\n"
    "  - НЕ подключай внешние npm пакеты — используй только встроенные Node.js модули "
    "(fs, path, os, crypto, http, https, url, util, events, stream и т.д.).\n"
    "  - Если задание требует Chrome Extension — генерируй HTML-файл с инструкцией по упаковке, "
    "НЕ JavaScript для Node.js.\n"
    "  - Если нужна работа в браузере с DOM — генерируй HTML (```html блок), а не JavaScript.\n"
    "ВСЕГДА возвращай ТОЛЬКО код в соответствующем ``` блоке без пояснений вне кода.\n"
    "НЕ спрашивай уточнений — сразу генерируй полный рабочий код.\n"
    "КРИТИЧЕСКИ ВАЖНО для HTML — работа с интернетом:\n"
    f"  - Если задание требует данных из интернета — {_FREE_PUBLIC_APIS_HINT}.\n"
    "  - fetch() в HTML работает напрямую из браузера — используй его без проблем.\n"
    "СТРОГО ЗАПРЕЩЕНО: возвращать любые мета-данные, данные обучения или структурированные данные "
    "вместо кода (например: episode/actions/training_view, perception/observation или похожие схемы) — "
    "только готовый исполняемый код."
)


@app.route("/generate/auto/stream", methods=["POST"])
def generate_auto_stream():
    """Stream code generation with automatic language detection by the model.

    Body: {"prompt": "...", "model": "..."}
    Streams SSE tokens ending with data: [DONE]
    The model decides what language to use based on the task description.
    Supports Ollama models and LM Studio models (prefix "lmstudio:").
    """
    body   = request.get_json(silent=True) or {}
    model  = body.get("model", "").strip()
    prompt = body.get("prompt", "").strip()

    if not model:
        def _no_model():
            yield 'data: {"error":"Модель не выбрана — выберите модель в настройках (☰)"}\n\n'
        return Response(stream_with_context(_no_model()), mimetype="text/event-stream")

    if not prompt:
        def _no_prompt():
            yield 'data: {"error":"Введите задание"}\n\n'
        return Response(stream_with_context(_no_prompt()), mimetype="text/event-stream")

    data       = load_instructions()
    sys_prompt = data.get("system_prompt", "").strip() or _DEFAULT_AUTO_SYSTEM_PROMPT

    # Route to LM Studio when model has the "lmstudio:" prefix
    is_lms = model.startswith(_LM_STUDIO_PREFIX)
    if is_lms:
        real_model = model[len(_LM_STUDIO_PREFIX):]
        lms_url    = _resolve_lms_url()

        def _stream_lms_auto():
            if not lms_url:
                yield 'data: {"error":"LM Studio URL не настроен — укажите URL в настройках (☰)"}\n\n'
                return
            try:
                resp = _http.post(
                    f"{lms_url}/v1/chat/completions",
                    json={
                        "model": real_model,
                        "messages": [
                            {"role": "system", "content": sys_prompt},
                            {"role": "user",   "content": f"Задание: {prompt}"},
                        ],
                        "stream": True,
                    },
                    stream=True,
                    timeout=_LMS_TIMEOUT,
                )
                resp.raise_for_status()
                for raw_line in resp.iter_lines():
                    if not raw_line:
                        continue
                    line_str = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                    if line_str.startswith("data: "):
                        line_str = line_str[6:]
                    if line_str.strip() in ("[DONE]", ""):
                        _record_generation("auto", model, prompt)
                        yield "data: [DONE]\n\n"
                        return
                    try:
                        chunk = json.loads(line_str)
                    except ValueError:
                        continue
                    delta  = chunk.get("choices", [{}])[0].get("delta", {})
                    token  = delta.get("content", "")
                    finish = chunk.get("choices", [{}])[0].get("finish_reason")
                    if token:
                        yield f"data: {json.dumps({'token': token})}\n\n"
                    if finish:
                        _record_generation("auto", model, prompt)
                        yield "data: [DONE]\n\n"
                        return
            except _http.exceptions.Timeout:
                yield f'data: {{"error":"Нет ответа от LM Studio за {_LMS_TIMEOUT} с — модель слишком медленная."}}\n\n'
            except _http.exceptions.ConnectionError:
                _resolve_lms_url()  # re-discover for next request
                yield f'data: {json.dumps({"error": f"Нет соединения с LM Studio по адресу {lms_url} — проверьте, что LM Studio запущен"})}\n\n'
            except Exception as exc:  # pylint: disable=broad-except
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"

        return Response(
            stream_with_context(_stream_lms_auto()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    is_tgwui = model.startswith(_TGWUI_PREFIX)
    if is_tgwui:
        real_model = model[len(_TGWUI_PREFIX):]
        tw_url     = TGWUI_BASE

        def _stream_tgwui_auto():
            if not tw_url:
                yield 'data: {"error":"text-generation-webui URL не настроен — укажите URL в настройках (☰)"}\n\n'
                return
            try:
                resp = _http.post(
                    f"{tw_url}/v1/chat/completions",
                    json={
                        "model": real_model,
                        "messages": [
                            {"role": "system", "content": sys_prompt},
                            {"role": "user",   "content": f"Задание: {prompt}"},
                        ],
                        "stream": True,
                    },
                    stream=True,
                    timeout=_LMS_TIMEOUT,
                )
                resp.raise_for_status()
                for raw_line in resp.iter_lines():
                    if not raw_line:
                        continue
                    line_str = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                    if line_str.startswith("data: "):
                        line_str = line_str[6:]
                    if line_str.strip() in ("[DONE]", ""):
                        _record_generation("auto", model, prompt)
                        yield "data: [DONE]\n\n"
                        return
                    try:
                        chunk = json.loads(line_str)
                    except ValueError:
                        continue
                    delta  = chunk.get("choices", [{}])[0].get("delta", {})
                    token  = delta.get("content", "")
                    finish = chunk.get("choices", [{}])[0].get("finish_reason")
                    if token:
                        yield f"data: {json.dumps({'token': token})}\n\n"
                    if finish:
                        _record_generation("auto", model, prompt)
                        yield "data: [DONE]\n\n"
                        return
            except _http.exceptions.Timeout:
                _oto = int(os.environ.get("OLLAMA_TIMEOUT", 120))
                yield f'data: {{"error":"Нет ответа от text-generation-webui за {_oto} с."}}\n\n'
            except _http.exceptions.ConnectionError:
                yield f'data: {json.dumps({"error": f"Нет соединения с text-generation-webui по адресу {tw_url}"})}\n\n'
            except Exception as exc:  # pylint: disable=broad-except
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"

        return Response(
            stream_with_context(_stream_tgwui_auto()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    is_roo = model.startswith(_ROO_CODE_PREFIX)
    if is_roo:
        real_model = model[len(_ROO_CODE_PREFIX):]
        roo_url    = ROO_CODE_BASE

        def _stream_roo_auto():
            if not roo_url:
                yield 'data: {"error":"Roo Code URL не настроен — укажите URL в настройках (☰)"}\n\n'
                return
            try:
                resp = _http.post(
                    f"{roo_url}/v1/chat/completions",
                    json={
                        "model": real_model,
                        "messages": [
                            {"role": "system", "content": sys_prompt},
                            {"role": "user",   "content": f"Задание: {prompt}"},
                        ],
                        "stream": True,
                    },
                    stream=True,
                    timeout=_LMS_TIMEOUT,
                )
                resp.raise_for_status()
                for raw_line in resp.iter_lines():
                    if not raw_line:
                        continue
                    line_str = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                    if line_str.startswith("data: "):
                        line_str = line_str[6:]
                    if line_str.strip() in ("[DONE]", ""):
                        _record_generation("auto", model, prompt)
                        yield "data: [DONE]\n\n"
                        return
                    try:
                        chunk = json.loads(line_str)
                    except ValueError:
                        continue
                    delta  = chunk.get("choices", [{}])[0].get("delta", {})
                    token  = delta.get("content", "")
                    finish = chunk.get("choices", [{}])[0].get("finish_reason")
                    if token:
                        yield f"data: {json.dumps({'token': token})}\n\n"
                    if finish:
                        _record_generation("auto", model, prompt)
                        yield "data: [DONE]\n\n"
                        return
            except _http.exceptions.Timeout:
                yield f'data: {{"error":"Нет ответа от Roo Code за {_LMS_TIMEOUT} с — модель слишком медленная."}}\n\n'
            except _http.exceptions.ConnectionError:
                yield f'data: {json.dumps({"error": f"Нет соединения с Roo Code по адресу {roo_url} — проверьте настройки"})}\n\n'
            except Exception as exc:  # pylint: disable=broad-except
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"

        return Response(
            stream_with_context(_stream_roo_auto()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    full_prompt = f"{sys_prompt}\n\nЗадание: {prompt}"

    def _stream():
        try:
            resp = _http.post(
                f"{OLLAMA_BASE}/api/generate",
                json={"model": model, "prompt": full_prompt, "stream": True},
                stream=True,
                timeout=int(os.environ.get("OLLAMA_TIMEOUT", 240)),
            )
            if resp.status_code == 500:
                err_body = ""
                try:
                    err_body = resp.json().get("error", resp.text[:200])
                except Exception:
                    err_body = resp.text[:200]
                _err_msg = f'Ollama ошибка 500: {err_body}. Проверьте, что модель "{model}" загружена (ollama pull {model}).'
                yield f"data: {json.dumps({'error': _err_msg})}\n\n"
                return
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
                    _record_generation("auto", model, prompt)
                    yield "data: [DONE]\n\n"
                    return
        except _http.exceptions.Timeout:
            _oto = int(os.environ.get("OLLAMA_TIMEOUT", 120))
            yield f'data: {{"error":"Ollama не ответил за {_oto} с — модель слишком медленная. Попробуйте увеличить OLLAMA_TIMEOUT или выбрать меньшую модель."}}\n\n'
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
    """Stream a plain chat response from Ollama or LM Studio.

    Body: {"message": "...", "model": "...", "history": [...optional chat history...]}
    Streams SSE tokens ending with data: [DONE]
    Unlike /generate/html/stream this returns raw model text without any
    HTML-generation system prompt so it works for any question.

    If the model name starts with "lmstudio:" the request is routed to the
    LM Studio OpenAI-compatible /v1/chat/completions endpoint.
    """
    body         = request.get_json(silent=True) or {}
    model        = body.get("model", "").strip()
    message      = body.get("message", "").strip()
    history      = body.get("history", [])  # list of {"role": "user"|"assistant", "text": "..."}
    system       = body.get("system", "").strip()  # optional system context prefix
    image_base64 = body.get("image_base64", "").strip()  # optional base64 image for vision models

    if not model:
        def _no_model():
            yield 'data: {"error":"Модель не выбрана — выберите модель в настройках (☰)"}\n\n'
        return Response(stream_with_context(_no_model()), mimetype="text/event-stream")

    if not message:
        def _no_msg():
            yield 'data: {"error":"Введите сообщение"}\n\n'
        return Response(stream_with_context(_no_msg()), mimetype="text/event-stream")

    # Build messages list for chat API
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    for entry in history[-_MAX_CHAT_HISTORY_TURNS:]:
        role = entry.get("role", "user")
        text = entry.get("text", "").strip()
        if text:
            messages.append({"role": role, "content": text})
    # Build the user message — attach image if provided
    user_msg: dict = {"role": "user", "content": message}
    if image_base64:
        user_msg["images"] = [image_base64]
    messages.append(user_msg)

    # Route to LM Studio when the model has the lmstudio: prefix
    is_lms = model.startswith(_LM_STUDIO_PREFIX)

    # Route to Remote VM when the model has the remote: prefix
    _REMOTE_PREFIX = "remote:"
    is_remote = model.startswith(_REMOTE_PREFIX)

    if is_remote:
        real_model = model[len(_REMOTE_PREFIX):]
        rvm_url    = REMOTE_VM_URL

        def _stream_remote():
            if not rvm_url:
                yield 'data: {"error":"Remote VM URL не настроен — укажите URL в настройках (☰)"}\n\n'
                return
            try:
                resp = _http.post(
                    f"{rvm_url}/chat/stream",
                    json={"model": real_model, "messages": messages,
                          "message": message, "history": history,
                          "system": system, "image_base64": image_base64},
                    stream=True,
                    timeout=_LMS_TIMEOUT,
                )
                resp.raise_for_status()
                for raw_line in resp.iter_lines():
                    if not raw_line:
                        continue
                    line_str = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else raw_line
                    yield f"{line_str}\n\n"
                    if "[DONE]" in line_str:
                        return
            except _http.exceptions.Timeout:
                _oto = int(os.environ.get("OLLAMA_TIMEOUT", 120))
                yield f'data: {{"error":"Нет ответа от Remote VM за {_oto} с — модель слишком медленная."}}\n\n'
            except _http.exceptions.ConnectionError:
                yield f'data: {json.dumps({"error": f"Нет соединения с Remote VM по адресу {rvm_url}"})}\n\n'
            except Exception as exc:  # pylint: disable=broad-except
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"

        return Response(
            stream_with_context(_stream_remote()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    if is_lms:
        # LM Studio uses OpenAI-compatible /v1/chat/completions
        real_model = model[len(_LM_STUDIO_PREFIX):]
        lms_url    = _resolve_lms_url()

        # For OpenAI-compatible API, image must be in content array format
        if image_base64:
            user_msg["content"] = [
                {"type": "text",       "text": message},
                {"type": "image_url",  "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
            ]
            # Remove the Ollama-style 'images' key
            user_msg.pop("images", None)

        def _stream_lms():
            if not lms_url:
                yield 'data: {"error":"LM Studio URL не настроен — укажите URL в настройках (☰)"}\n\n'
                return
            try:
                resp = _http.post(
                    f"{lms_url}/v1/chat/completions",
                    json={"model": real_model, "messages": messages, "stream": True},
                    stream=True,
                    timeout=_LMS_TIMEOUT,
                )
                resp.raise_for_status()
                for raw_line in resp.iter_lines():
                    if not raw_line:
                        continue
                    line_str = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                    if line_str.startswith("data: "):
                        line_str = line_str[6:]
                    if line_str.strip() in ("[DONE]", ""):
                        yield "data: [DONE]\n\n"
                        return
                    try:
                        chunk = json.loads(line_str)
                    except ValueError:
                        continue
                    # OpenAI-style delta token
                    delta   = chunk.get("choices", [{}])[0].get("delta", {})
                    token   = delta.get("content", "")
                    finish  = chunk.get("choices", [{}])[0].get("finish_reason")
                    if token:
                        yield f"data: {json.dumps({'token': token})}\n\n"
                    if finish:
                        yield "data: [DONE]\n\n"
                        return
            except _http.exceptions.Timeout:
                yield f'data: {{"error":"Нет ответа от LM Studio за {_LMS_TIMEOUT} с — модель слишком медленная."}}\n\n'
            except _http.exceptions.ConnectionError:
                _resolve_lms_url()  # re-discover for next request
                yield f'data: {json.dumps({"error": f"Нет соединения с LM Studio по адресу {lms_url} — проверьте, что LM Studio запущен"})}\n\n'
            except Exception as exc:  # pylint: disable=broad-except
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"

        return Response(
            stream_with_context(_stream_lms()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    is_tgwui = model.startswith(_TGWUI_PREFIX)
    if is_tgwui:
        real_model = model[len(_TGWUI_PREFIX):]
        tw_url     = TGWUI_BASE

        def _stream_tgwui():
            if not tw_url:
                yield 'data: {"error":"text-generation-webui URL не настроен — укажите URL в настройках (☰)"}\n\n'
                return
            try:
                resp = _http.post(
                    f"{tw_url}/v1/chat/completions",
                    json={"model": real_model, "messages": messages, "stream": True},
                    stream=True,
                    timeout=_LMS_TIMEOUT,
                )
                resp.raise_for_status()
                for raw_line in resp.iter_lines():
                    if not raw_line:
                        continue
                    line_str = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                    if line_str.startswith("data: "):
                        line_str = line_str[6:]
                    if line_str.strip() in ("[DONE]", ""):
                        yield "data: [DONE]\n\n"
                        return
                    try:
                        chunk = json.loads(line_str)
                    except ValueError:
                        continue
                    delta  = chunk.get("choices", [{}])[0].get("delta", {})
                    token  = delta.get("content", "")
                    finish = chunk.get("choices", [{}])[0].get("finish_reason")
                    if token:
                        yield f"data: {json.dumps({'token': token})}\n\n"
                    if finish:
                        yield "data: [DONE]\n\n"
                        return
            except _http.exceptions.Timeout:
                _oto = int(os.environ.get("OLLAMA_TIMEOUT", 120))
                yield f'data: {{"error":"Нет ответа от text-generation-webui за {_oto} с."}}\n\n'
            except _http.exceptions.ConnectionError:
                yield f'data: {json.dumps({"error": f"Нет соединения с text-generation-webui по адресу {tw_url}"})}\n\n'
            except Exception as exc:  # pylint: disable=broad-except
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"

        return Response(
            stream_with_context(_stream_tgwui()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # --- Default: Ollama ---
    def _stream():
        try:
            resp = _http.post(
                f"{OLLAMA_BASE}/api/chat",
                json={"model": model, "messages": messages, "stream": True},
                stream=True,
                timeout=int(os.environ.get("OLLAMA_TIMEOUT", 240)),
            )
            if resp.status_code == 500:
                err_body = ""
                try:
                    err_body = resp.json().get("error", resp.text[:200])
                except Exception:
                    err_body = resp.text[:200]
                _err_msg = f'Ollama вернул ошибку 500: {err_body}. Проверьте, что модель "{model}" загружена (ollama pull {model}).'
                yield f"data: {json.dumps({'error': _err_msg})}\n\n"
                return
            resp.raise_for_status()
            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue
                try:
                    chunk = json.loads(raw_line)
                except ValueError:
                    continue
                token = chunk.get("message", {}).get("content", "") or chunk.get("response", "")
                if token:
                    yield f"data: {json.dumps({'token': token})}\n\n"
                if chunk.get("done"):
                    yield "data: [DONE]\n\n"
                    return
        except _http.exceptions.Timeout:
            _oto = int(os.environ.get("OLLAMA_TIMEOUT", 120))
            yield f'data: {{"error":"Ollama не ответил за {_oto} с — модель слишком медленная. Попробуйте увеличить OLLAMA_TIMEOUT или выбрать меньшую модель."}}\n\n'
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
# Online multi-user Chat Room — for extension users
# Each message is broadcast to all connected SSE subscribers.
# ---------------------------------------------------------------------------
_CHATROOM_HISTORY_MAX      = 100   # keep last N messages in memory
_CHATROOM_MAX_NICK_LEN     = 32    # max nickname length
_CHATROOM_MAX_MSG_LEN      = 2000  # max message text length
_CHATROOM_QUEUE_MAXSIZE    = 64    # max queued events per SSE subscriber
_CHATROOM_HEARTBEAT_SEC    = 20    # seconds between heartbeat pings
_chatroom_history: list = []  # list of {id, nick, text, ts}
_chatroom_subs: list = []     # list of queue.Queue — one per SSE subscriber
_chatroom_lock = threading.Lock()
_chatroom_msg_counter = 0


def _chatroom_broadcast(msg: dict) -> None:
    """Push a message dict to every active SSE subscriber queue."""
    with _chatroom_lock:
        dead = []
        for q in _chatroom_subs:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            try:
                _chatroom_subs.remove(q)
            except ValueError:
                pass


@app.route("/chatroom/page")
def chatroom_page():
    """Serve the standalone chat room HTML page."""
    return send_from_directory(
        os.path.join(_DIR, "static"), "chat_room.html"
    )


@app.route("/chatroom/history", methods=["GET"])
def chatroom_history():
    """Return recent chat room messages as JSON."""
    with _chatroom_lock:
        history = list(_chatroom_history)
    return jsonify({"messages": history})


_CHATROOM_VALID_COLORS = {
    "#e74c3c", "#e67e22", "#f1c40f", "#2ecc71", "#1abc9c",
    "#3498db", "#9b59b6", "#e91e63", "#00bcd4", "#ff5722",
    "#8bc34a", "#607d8b", "#ff9800", "#795548", "#673ab7",
}
# Registered users: nick -> {color, registered_at}
_chatroom_users: dict = {}


@app.route("/chatroom/register", methods=["POST"])
def chatroom_register():
    """Register or update a chat user.

    Body: {"nick": "...", "color": "#rrggbb"}
    Returns: {"ok": true, "nick": "...", "color": "#rrggbb"}
    """
    body = request.get_json(silent=True) or {}
    nick = (body.get("nick") or "").strip()[:_CHATROOM_MAX_NICK_LEN]
    if not nick:
        return jsonify({"ok": False, "error": "nick required"}), 400
    color = (body.get("color") or "").strip().lower()
    if color not in _CHATROOM_VALID_COLORS:
        h = int(hashlib.md5(nick.encode()).hexdigest(), 16)
        color = sorted(_CHATROOM_VALID_COLORS)[h % len(_CHATROOM_VALID_COLORS)]
    with _chatroom_lock:
        _chatroom_users[nick] = {
            "color": color,
            "registered_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    return jsonify({"ok": True, "nick": nick, "color": color})


@app.route("/chatroom/send", methods=["POST"])
def chatroom_send():
    """Post a message to the chat room.

    Body: {"nick": "...", "text": "...", "color": "#rrggbb", "reply_to": N}
    Returns: {"ok": true, "id": N}
    """
    global _chatroom_msg_counter
    body = request.get_json(silent=True) or {}
    nick     = (body.get("nick") or "Аноним").strip()[:_CHATROOM_MAX_NICK_LEN]
    text     = (body.get("text") or "").strip()[:_CHATROOM_MAX_MSG_LEN]
    reply_to = body.get("reply_to")  # optional msg id being replied to
    if not text:
        return jsonify({"ok": False, "error": "empty message"}), 400

    # Determine avatar color: use registered color or the one sent with message
    with _chatroom_lock:
        user_info = _chatroom_users.get(nick, {})
    color = user_info.get("color") or (body.get("color") or "").strip().lower()
    if color not in _CHATROOM_VALID_COLORS:
        h = int(hashlib.md5(nick.encode()).hexdigest(), 16)
        color = sorted(_CHATROOM_VALID_COLORS)[h % len(_CHATROOM_VALID_COLORS)]

    # Resolve reply-to snippet
    reply_snippet = None
    if reply_to:
        try:
            reply_to = int(reply_to)
            with _chatroom_lock:
                for m in _chatroom_history:
                    if m.get("id") == reply_to:
                        reply_snippet = {
                            "id": reply_to,
                            "nick": m.get("nick", ""),
                            "text": (m.get("text") or "")[:80],
                        }
                        break
        except (TypeError, ValueError):
            reply_to = None

    with _chatroom_lock:
        _chatroom_msg_counter += 1
        msg_id = _chatroom_msg_counter
        msg = {
            "id": msg_id,
            "nick": nick,
            "color": color,
            "text": text,
            "ts": datetime.now(timezone.utc).strftime("%H:%M"),
        }
        if reply_to and reply_snippet:
            msg["reply_to"] = reply_snippet
        _chatroom_history.append(msg)
        if len(_chatroom_history) > _CHATROOM_HISTORY_MAX:
            _chatroom_history.pop(0)

    _chatroom_broadcast(msg)
    return jsonify({"ok": True, "id": msg_id})


@app.route("/chatroom/events")
def chatroom_events():
    """SSE stream — pushes new chat messages to the client as they arrive."""
    q: queue.Queue = queue.Queue(maxsize=_CHATROOM_QUEUE_MAXSIZE)
    with _chatroom_lock:
        _chatroom_subs.append(q)

    def _gen():
        # Send heartbeat first so the connection is established immediately
        yield "data: {\"type\":\"connected\"}\n\n"
        try:
            while True:
                try:
                    msg = q.get(timeout=_CHATROOM_HEARTBEAT_SEC)
                    yield f"data: {json.dumps(msg)}\n\n"
                except queue.Empty:
                    # Heartbeat to keep connection alive
                    yield "data: {\"type\":\"ping\"}\n\n"
        except GeneratorExit:
            pass
        finally:
            with _chatroom_lock:
                try:
                    _chatroom_subs.remove(q)
                except ValueError:
                    pass

    return Response(
        stream_with_context(_gen()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Chatroom — online users list
# ---------------------------------------------------------------------------
@app.route("/chatroom/users", methods=["GET"])
def chatroom_users_list():
    """Return list of currently registered chat users."""
    with _chatroom_lock:
        users = [
            {"nick": k, "color": v.get("color", "#888")}
            for k, v in _chatroom_users.items()
        ]
    return jsonify({"users": users})


# ---------------------------------------------------------------------------
# Chatroom — private DM (direct messages)
# ---------------------------------------------------------------------------
_chatroom_dm_history: dict = {}   # key: frozenset({nick_a, nick_b}) → list of msgs
_chatroom_dm_subs: dict = {}      # key: nick → list of queue.Queue
_chatroom_dm_counter = 0
_chatroom_dm_lock = threading.Lock()
_CHATROOM_DM_HISTORY_MAX = 200


def _chatroom_dm_key(a: str, b: str):
    return frozenset({a, b})


def _chatroom_dm_notify(to_nick: str, msg: dict) -> None:
    """Push a DM notification to subscriber queues of the recipient."""
    with _chatroom_dm_lock:
        for q in _chatroom_dm_subs.get(to_nick, []):
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass


@app.route("/chatroom/dm/send", methods=["POST"])
def chatroom_dm_send():
    """Send a private DM from one user to another.

    Body: {"from": "alice", "to": "bob", "text": "...", "color": "#rrggbb"}
    Returns: {"ok": true, "id": N}
    """
    global _chatroom_dm_counter
    body = request.get_json(silent=True) or {}
    from_nick = (body.get("from") or "").strip()[:_CHATROOM_MAX_NICK_LEN]
    to_nick   = (body.get("to") or "").strip()[:_CHATROOM_MAX_NICK_LEN]
    text      = (body.get("text") or "").strip()[:_CHATROOM_MAX_MSG_LEN]
    if not from_nick or not to_nick or not text:
        return jsonify({"ok": False, "error": "from/to/text required"}), 400

    with _chatroom_lock:
        user_info = _chatroom_users.get(from_nick, {})
    color = user_info.get("color") or (body.get("color") or "").strip().lower()
    if color not in _CHATROOM_VALID_COLORS:
        h = int(hashlib.md5(from_nick.encode()).hexdigest(), 16)
        color = sorted(_CHATROOM_VALID_COLORS)[h % len(_CHATROOM_VALID_COLORS)]

    with _chatroom_dm_lock:
        _chatroom_dm_counter += 1
        msg_id = _chatroom_dm_counter
        msg = {
            "id": msg_id,
            "type": "dm",
            "from": from_nick,
            "to": to_nick,
            "color": color,
            "text": text,
            "ts": datetime.now(timezone.utc).strftime("%H:%M"),
        }
        key = _chatroom_dm_key(from_nick, to_nick)
        if key not in _chatroom_dm_history:
            _chatroom_dm_history[key] = []
        _chatroom_dm_history[key].append(msg)
        if len(_chatroom_dm_history[key]) > _CHATROOM_DM_HISTORY_MAX:
            _chatroom_dm_history[key].pop(0)

    # Notify both parties
    _chatroom_dm_notify(to_nick, msg)
    _chatroom_dm_notify(from_nick, msg)
    return jsonify({"ok": True, "id": msg_id})


@app.route("/chatroom/dm/history", methods=["GET"])
def chatroom_dm_history_get():
    """Return DM history between two users.

    Query params: ?from=alice&to=bob
    """
    from_nick = (request.args.get("from") or "").strip()
    to_nick   = (request.args.get("to") or "").strip()
    if not from_nick or not to_nick:
        return jsonify({"messages": []})
    key = _chatroom_dm_key(from_nick, to_nick)
    with _chatroom_dm_lock:
        msgs = list(_chatroom_dm_history.get(key, []))
    return jsonify({"messages": msgs})


@app.route("/chatroom/dm/events")
def chatroom_dm_events():
    """SSE stream delivering incoming DMs for a specific user.

    Query param: ?nick=alice
    """
    nick = (request.args.get("nick") or "").strip()
    if not nick:
        return jsonify({"error": "nick required"}), 400

    q: queue.Queue = queue.Queue(maxsize=_CHATROOM_QUEUE_MAXSIZE)
    with _chatroom_dm_lock:
        _chatroom_dm_subs.setdefault(nick, []).append(q)

    def _gen():
        yield "data: {\"type\":\"connected\"}\n\n"
        try:
            while True:
                try:
                    msg = q.get(timeout=_CHATROOM_HEARTBEAT_SEC)
                    yield f"data: {json.dumps(msg)}\n\n"
                except queue.Empty:
                    yield "data: {\"type\":\"ping\"}\n\n"
        except GeneratorExit:
            pass
        finally:
            with _chatroom_dm_lock:
                subs = _chatroom_dm_subs.get(nick, [])
                try:
                    subs.remove(q)
                except ValueError:
                    pass

    return Response(
        stream_with_context(_gen()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Chatroom — reactions, edit, delete, pin (Telegram-like features)
# ---------------------------------------------------------------------------
_CHATROOM_ALLOWED_REACTIONS = {"👍", "👎", "❤", "😂", "😮", "😢", "🔥", "🎉"}
_chatroom_pins: list = []       # list of message ids that are pinned
_CHATROOM_PINS_MAX = 5


def _chatroom_find_msg(msg_id: int):
    """Return (msg, index) from _chatroom_history or (None, -1)."""
    with _chatroom_lock:
        for i, m in enumerate(_chatroom_history):
            if m.get("id") == msg_id:
                return m, i
    return None, -1


@app.route("/chatroom/react", methods=["POST"])
def chatroom_react():
    """Toggle an emoji reaction on a message.

    Body: {"nick": "...", "msg_id": N, "emoji": "👍"}
    Broadcasts a 'reaction' event with full reactions state.
    """
    body = request.get_json(silent=True) or {}
    nick    = (body.get("nick") or "").strip()[:_CHATROOM_MAX_NICK_LEN]
    try:
        msg_id = int(body.get("msg_id") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid msg_id"}), 400
    emoji   = (body.get("emoji") or "").strip()
    if not nick or not msg_id or emoji not in _CHATROOM_ALLOWED_REACTIONS:
        return jsonify({"ok": False, "error": "invalid params"}), 400

    msg, _ = _chatroom_find_msg(msg_id)
    if msg is None:
        return jsonify({"ok": False, "error": "message not found"}), 404

    with _chatroom_lock:
        if "reactions" not in msg:
            msg["reactions"] = {}
        r = msg["reactions"].setdefault(emoji, [])
        if nick in r:
            r.remove(nick)   # toggle off
        else:
            r.append(nick)   # toggle on
        if not r:
            del msg["reactions"][emoji]
        reactions_snap = dict(msg.get("reactions", {}))

    _chatroom_broadcast({
        "type": "reaction",
        "msg_id": msg_id,
        "reactions": reactions_snap,
    })
    return jsonify({"ok": True, "reactions": reactions_snap})


@app.route("/chatroom/edit", methods=["POST"])
def chatroom_edit():
    """Edit the text of an existing message (own messages only).

    Body: {"nick": "...", "msg_id": N, "text": "..."}
    """
    body = request.get_json(silent=True) or {}
    nick   = (body.get("nick") or "").strip()[:_CHATROOM_MAX_NICK_LEN]
    try:
        msg_id = int(body.get("msg_id") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid msg_id"}), 400
    text   = (body.get("text") or "").strip()[:_CHATROOM_MAX_MSG_LEN]
    if not nick or not msg_id or not text:
        return jsonify({"ok": False, "error": "invalid params"}), 400

    msg, _ = _chatroom_find_msg(msg_id)
    if msg is None:
        return jsonify({"ok": False, "error": "message not found"}), 404
    if msg.get("nick") != nick:
        return jsonify({"ok": False, "error": "not your message"}), 403

    with _chatroom_lock:
        msg["text"] = text
        msg["edited"] = True

    _chatroom_broadcast({"type": "edit", "msg_id": msg_id, "text": text, "edited": True})
    return jsonify({"ok": True})


@app.route("/chatroom/delete", methods=["POST"])
def chatroom_delete():
    """Soft-delete a message (mark as deleted, keep in history).

    Body: {"nick": "...", "msg_id": N}
    """
    body = request.get_json(silent=True) or {}
    nick   = (body.get("nick") or "").strip()[:_CHATROOM_MAX_NICK_LEN]
    try:
        msg_id = int(body.get("msg_id") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid msg_id"}), 400
    if not nick or not msg_id:
        return jsonify({"ok": False, "error": "invalid params"}), 400

    msg, _ = _chatroom_find_msg(msg_id)
    if msg is None:
        return jsonify({"ok": False, "error": "message not found"}), 404
    if msg.get("nick") != nick:
        return jsonify({"ok": False, "error": "not your message"}), 403

    with _chatroom_lock:
        msg["deleted"] = True
        msg["text"]    = ""

    _chatroom_broadcast({"type": "delete", "msg_id": msg_id})
    return jsonify({"ok": True})


@app.route("/chatroom/pin", methods=["POST"])
def chatroom_pin():
    """Pin or unpin a message.

    Body: {"nick": "...", "msg_id": N}
    Toggles: if already pinned — unpins; otherwise pins (max _CHATROOM_PINS_MAX).
    """
    global _chatroom_pins
    body   = request.get_json(silent=True) or {}
    nick   = (body.get("nick") or "").strip()[:_CHATROOM_MAX_NICK_LEN]
    try:
        msg_id = int(body.get("msg_id") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid msg_id"}), 400
    if not nick or not msg_id:
        return jsonify({"ok": False, "error": "invalid params"}), 400

    msg, _ = _chatroom_find_msg(msg_id)
    if msg is None:
        return jsonify({"ok": False, "error": "message not found"}), 404

    with _chatroom_lock:
        if msg_id in _chatroom_pins:
            _chatroom_pins.remove(msg_id)
            pinned = False
        else:
            _chatroom_pins.append(msg_id)
            if len(_chatroom_pins) > _CHATROOM_PINS_MAX:
                _chatroom_pins.pop(0)
            pinned = True
        pins_snap = list(_chatroom_pins)

    _chatroom_broadcast({"type": "pin_update", "pins": pins_snap})
    return jsonify({"ok": True, "pinned": pinned, "pins": pins_snap})


@app.route("/chatroom/pins", methods=["GET"])
def chatroom_pins_get():
    """Return pinned message ids and their content."""
    with _chatroom_lock:
        pins = list(_chatroom_pins)
        result = []
        for pid in pins:
            for m in _chatroom_history:
                if m.get("id") == pid and not m.get("deleted"):
                    result.append(m)
                    break
    return jsonify({"pins": result})


# ---------------------------------------------------------------------------
# Chatroom extra: typing indicators, search, polls, image upload, bookmarks
# ---------------------------------------------------------------------------

# ── Typing indicator ─────────────────────────────────────────────────────────
@app.route("/chatroom/typing", methods=["POST"])
def chatroom_typing():
    """Broadcast a typing indicator to all SSE subscribers.

    Body: {"nick": "...", "typing": true|false}
    """
    body = request.get_json(silent=True) or {}
    nick = (body.get("nick") or "").strip()[:32]
    typing = bool(body.get("typing", True))
    if not nick:
        return jsonify({"ok": False, "error": "nick required"}), 400
    _chatroom_broadcast({"type": "typing", "nick": nick, "typing": typing})
    return jsonify({"ok": True})


# ── Message search ────────────────────────────────────────────────────────────
@app.route("/chatroom/search", methods=["GET"])
def chatroom_search():
    """Search messages by keyword (case-insensitive).

    Query: ?q=keyword
    Returns: {"results": [msg, ...]}
    """
    q = (request.args.get("q") or "").strip().lower()
    if not q:
        return jsonify({"results": []})
    with _chatroom_lock:
        results = [
            m for m in _chatroom_history
            if not m.get("deleted") and q in (m.get("text") or "").lower()
        ]
    return jsonify({"results": results})


# ── Polls ─────────────────────────────────────────────────────────────────────
_chatroom_polls: dict = {}   # poll_id → {id, creator, question, options, votes, closed, ts}
_chatroom_poll_counter = 0
_CHATROOM_POLLS_MAX = 20

@app.route("/chatroom/poll", methods=["POST"])
def chatroom_poll_create():
    """Create a new poll.

    Body: {"nick": "...", "question": "...", "options": ["opt1", "opt2", ...]}
    Returns: {"ok": true, "poll_id": <int>}
    """
    global _chatroom_poll_counter
    body = request.get_json(silent=True) or {}
    nick = (body.get("nick") or "").strip()[:32]
    question = (body.get("question") or "").strip()[:200]
    options  = [str(o)[:100] for o in (body.get("options") or []) if str(o).strip()]
    if not nick:
        return jsonify({"ok": False, "error": "nick required"}), 400
    if not question:
        return jsonify({"ok": False, "error": "question required"}), 400
    if len(options) < 2 or len(options) > 10:
        return jsonify({"ok": False, "error": "2–10 options required"}), 400
    with _chatroom_lock:
        user_info = _chatroom_users.get(nick, {})
        color = user_info.get("color", "#888")
        _chatroom_poll_counter += 1
        poll_id = _chatroom_poll_counter
        ts = datetime.now(timezone.utc).strftime("%H:%M")
        poll = {
            "id": poll_id,
            "creator": nick,
            "color": color,
            "question": question,
            "options": options,
            "votes": {o: [] for o in options},   # option → list of nicks
            "closed": False,
            "ts": ts,
        }
        _chatroom_polls[poll_id] = poll
        # Evict oldest polls if too many
        if len(_chatroom_polls) > _CHATROOM_POLLS_MAX:
            oldest = min(_chatroom_polls.keys())
            del _chatroom_polls[oldest]
    _chatroom_broadcast({"type": "poll_new", "poll": poll})
    return jsonify({"ok": True, "poll_id": poll_id})


@app.route("/chatroom/poll/vote", methods=["POST"])
def chatroom_poll_vote():
    """Vote on a poll option.

    Body: {"nick": "...", "poll_id": <int>, "option": "..."}
    Returns: {"ok": true, "poll": {...}}
    """
    body = request.get_json(silent=True) or {}
    nick    = (body.get("nick") or "").strip()[:32]
    poll_id = int(body.get("poll_id") or 0)
    option  = str(body.get("option") or "").strip()[:100]
    if not nick:
        return jsonify({"ok": False, "error": "nick required"}), 400
    with _chatroom_lock:
        poll = _chatroom_polls.get(poll_id)
        if not poll:
            return jsonify({"ok": False, "error": "poll not found"}), 404
        if poll.get("closed"):
            return jsonify({"ok": False, "error": "poll closed"}), 400
        if option not in poll["options"]:
            return jsonify({"ok": False, "error": "invalid option"}), 400
        # Remove previous vote by this nick
        for opt_votes in poll["votes"].values():
            if nick in opt_votes:
                opt_votes.remove(nick)
        poll["votes"][option].append(nick)
        poll_snap = dict(poll)
    _chatroom_broadcast({"type": "poll_update", "poll": poll_snap})
    return jsonify({"ok": True, "poll": poll_snap})


@app.route("/chatroom/polls", methods=["GET"])
def chatroom_polls_list():
    """Return all active (non-closed) polls, newest first."""
    with _chatroom_lock:
        polls = sorted(
            [p for p in _chatroom_polls.values() if not p.get("closed")],
            key=lambda p: p["id"],
            reverse=True,
        )
    return jsonify({"polls": polls})


@app.route("/chatroom/poll/close", methods=["POST"])
def chatroom_poll_close():
    """Close a poll (creator only).

    Body: {"nick": "...", "poll_id": <int>}
    """
    body = request.get_json(silent=True) or {}
    nick    = (body.get("nick") or "").strip()[:32]
    poll_id = int(body.get("poll_id") or 0)
    if not nick:
        return jsonify({"ok": False, "error": "nick required"}), 400
    with _chatroom_lock:
        poll = _chatroom_polls.get(poll_id)
        if not poll:
            return jsonify({"ok": False, "error": "poll not found"}), 404
        if poll["creator"] != nick:
            return jsonify({"ok": False, "error": "only creator can close"}), 403
        poll["closed"] = True
        poll_snap = dict(poll)
    _chatroom_broadcast({"type": "poll_update", "poll": poll_snap})
    return jsonify({"ok": True})


# ── Image / file upload ───────────────────────────────────────────────────────
import mimetypes as _mimetypes
import pathlib as _pathlib
_CHATROOM_UPLOAD_DIR = _pathlib.Path(__file__).parent / "static" / "chatroom_uploads"
_CHATROOM_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
_CHATROOM_UPLOAD_MAX_MB = 10
_CHATROOM_ALLOWED_EXT = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
    ".mp3", ".ogg", ".wav", ".webm", ".m4a",
    ".pdf", ".txt", ".md",
    ".mp4",
}

@app.route("/chatroom/upload", methods=["POST"])
def chatroom_upload():
    """Upload a file (image / audio / document) to the chatroom.

    multipart/form-data fields: file, nick, color
    Returns: {"ok": true, "url": "/chatroom/uploads/<filename>", "name": "...", "mime": "..."}
    """
    nick  = (request.form.get("nick")  or "").strip()[:32]
    color = (request.form.get("color") or "#888").strip()[:20]
    if not nick:
        return jsonify({"ok": False, "error": "nick required"}), 400
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error": "no file"}), 400
    from werkzeug.utils import secure_filename as _secure_filename
    orig_name = _secure_filename(f.filename) if f.filename else "file"
    ext = _pathlib.Path(orig_name).suffix.lower()
    if ext not in _CHATROOM_ALLOWED_EXT:
        return jsonify({"ok": False, "error": f"file type {ext!r} not allowed"}), 400
    # Size check
    f.seek(0, 2)
    size = f.tell()
    f.seek(0)
    if size > _CHATROOM_UPLOAD_MAX_MB * 1024 * 1024:
        return jsonify({"ok": False, "error": f"max {_CHATROOM_UPLOAD_MAX_MB} MB"}), 400
    unique_name = f"{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}_{orig_name}"
    dest = _CHATROOM_UPLOAD_DIR / unique_name
    f.save(dest)
    url = f"/chatroom/uploads/{unique_name}"
    mime = _mimetypes.guess_type(orig_name)[0] or "application/octet-stream"
    # Broadcast a message with the file attachment
    global _chatroom_msg_counter
    with _chatroom_lock:
        _chatroom_msg_counter += 1
        msg_id = _chatroom_msg_counter
        ts = datetime.now(timezone.utc).strftime("%H:%M")
        msg = {
            "id": msg_id,
            "nick": nick,
            "color": color,
            "text": orig_name,
            "ts": ts,
            "attachment": {"url": url, "name": orig_name, "mime": mime},
        }
        _chatroom_history.append(msg)
        if len(_chatroom_history) > _CHATROOM_HISTORY_MAX:
            _chatroom_history.pop(0)
    _chatroom_broadcast(msg)
    return jsonify({"ok": True, "url": url, "name": orig_name, "mime": mime})


@app.route("/chatroom/uploads/<path:filename>")
def chatroom_upload_serve(filename):
    """Serve uploaded chatroom files."""
    return send_from_directory(str(_CHATROOM_UPLOAD_DIR), filename)


# ── Bookmarks (per-session, stored client-side; backend not required)
# ── Forward message (re-send as own message with forward attribution)
@app.route("/chatroom/forward", methods=["POST"])
def chatroom_forward():
    """Forward a message to the group chat.

    Body: {"nick": "...", "msg_id": <int>, "color": "..."}
    Returns: {"ok": true}
    """
    body = request.get_json(silent=True) or {}
    nick   = (body.get("nick")  or "").strip()[:32]
    color  = (body.get("color") or "#888").strip()[:20]
    msg_id = int(body.get("msg_id") or 0)
    if not nick:
        return jsonify({"ok": False, "error": "nick required"}), 400
    orig, _ = _chatroom_find_msg(msg_id)
    if not orig or orig.get("deleted"):
        return jsonify({"ok": False, "error": "message not found"}), 404
    global _chatroom_msg_counter
    with _chatroom_lock:
        _chatroom_msg_counter += 1
        new_id = _chatroom_msg_counter
        ts = datetime.now(timezone.utc).strftime("%H:%M")
        msg = {
            "id": new_id,
            "nick": nick,
            "color": color,
            "text": orig.get("text", ""),
            "ts": ts,
            "forward_from": orig.get("nick", ""),
        }
        _chatroom_history.append(msg)
        if len(_chatroom_history) > _CHATROOM_HISTORY_MAX:
            _chatroom_history.pop(0)
    _chatroom_broadcast(msg)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# TG → VM chat: Telegram messages forwarded to the VM AI chat panel
# ---------------------------------------------------------------------------
_TG_CHAT_MAX = 200          # keep last N TG messages in memory
_tg_chat_history: list = []  # [{id, from_name, text, ts}]
_tg_chat_lock = threading.Lock()
_tg_chat_counter = 0


@app.route("/chat/push", methods=["POST"])
def chat_push():
    """Receive a Telegram message and store it for the VM chat UI to poll.

    Body: {"from_name": "...", "text": "...", "chat_title": "...",
           "has_photo": bool, "has_document": bool, "file_name": "..."}
    Returns: {"ok": true, "id": <int>}
    """
    global _tg_chat_counter
    body = request.get_json(silent=True) or {}
    from_name = (body.get("from_name") or "TG")[:64]
    text = (body.get("text") or "").strip()[:4000]
    if not text and not body.get("has_photo") and not body.get("has_document"):
        return jsonify({"ok": False, "error": "empty message"})
    with _tg_chat_lock:
        _tg_chat_counter += 1
        msg_id = _tg_chat_counter
        entry = {
            "id": msg_id,
            "from_name": from_name,
            "text": text,
            "ts": time.strftime("%H:%M"),
        }
        if body.get("chat_title"):
            entry["chat_title"] = str(body["chat_title"])[:64]
        if body.get("has_photo"):
            entry["has_photo"] = True
        if body.get("has_document"):
            entry["has_document"] = True
            entry["file_name"] = str(body.get("file_name") or "")[:128]
        _tg_chat_history.append(entry)
        if len(_tg_chat_history) > _TG_CHAT_MAX:
            _tg_chat_history.pop(0)
    return jsonify({"ok": True, "id": msg_id})


@app.route("/chat/tg_messages", methods=["GET"])
def chat_tg_messages():
    """Return TG messages with id > after parameter for polling.

    Query param: after=<int>  (default 0)
    Returns: {"messages": [...]}
    """
    try:
        after = int(request.args.get("after", 0))
    except (ValueError, TypeError):
        after = 0
    with _tg_chat_lock:
        msgs = [m for m in _tg_chat_history if m["id"] > after]
    return jsonify({"messages": msgs})


_DEFAULT_PATCH_SYSTEM_PROMPT = (
    "Ты DRGR Code Patcher — эксперт-программист на базе Qwen.\n"
    "Тебе дадут СУЩЕСТВУЮЩИЙ код и ЗАПРОС на изменение.\n"
    "ЗАДАЧА: внести минимально необходимые правки в код согласно запросу.\n"
    "ПРАВИЛА:\n"
    "- НЕ переписывай весь код заново — только вноси необходимые изменения\n"
    "- Сохраняй структуру, стиль и логику исходного кода\n"
    "- Верни ТОЛЬКО полный итоговый код в ``` блоке (того же языка)\n"
    "- НЕ давай пояснений вне кода\n"
    "- Если код HTML — верни полный <!DOCTYPE html> документ с внесёнными правками"
)


@app.route("/patch/stream", methods=["POST"])
def patch_stream():
    """Stream patched/edited code based on existing code + user change request.

    Body: {"prompt": "...", "code": "...", "model": "..."}
    Streams SSE tokens ending with data: [DONE]
    The model edits the existing code minimally rather than regenerating from scratch.
    """
    body   = request.get_json(silent=True) or {}
    model  = body.get("model", "").strip()
    prompt = body.get("prompt", "").strip()
    code   = body.get("code", "").strip()

    if not model:
        def _no_model():
            yield 'data: {"error":"Модель не выбрана — выберите модель в настройках (☰)"}\n\n'
        return Response(stream_with_context(_no_model()), mimetype="text/event-stream")

    if not prompt:
        def _no_prompt():
            yield 'data: {"error":"Введите запрос на правки"}\n\n'
        return Response(stream_with_context(_no_prompt()), mimetype="text/event-stream")

    if not code:
        def _no_code():
            yield 'data: {"error":"Редактор пуст — нечего редактировать"}\n\n'
        return Response(stream_with_context(_no_code()), mimetype="text/event-stream")

    data       = load_instructions()
    sys_prompt = data.get("patch_system_prompt", "").strip() or _DEFAULT_PATCH_SYSTEM_PROMPT
    full_prompt = (
        f"{sys_prompt}\n\n"
        f"СУЩЕСТВУЮЩИЙ КОД:\n```\n{code}\n```\n\n"
        f"ЗАПРОС НА ИЗМЕНЕНИЕ: {prompt}"
    )

    _to = int(os.environ.get("OLLAMA_TIMEOUT", 300))
    _real_model = model

    def _stream():
        try:
            # Route lmstudio: / tgwui: models through their OpenAI-compatible APIs
            if _real_model.startswith(_LM_STUDIO_PREFIX):
                _m = _real_model[len(_LM_STUDIO_PREFIX):]
                _base = _resolve_lms_url()  # auto-discover if not yet configured
                if not _base:
                    yield 'data: {"error":"LM Studio URL не настроен — укажите URL в настройках (☰)"}\n\n'
                    return
                _use_chat = True
                _timeout = _LMS_TIMEOUT
            elif _real_model.startswith(_TGWUI_PREFIX) and TGWUI_BASE:
                _m = _real_model[len(_TGWUI_PREFIX):]
                _base = TGWUI_BASE
                _use_chat = True
                _timeout = _LMS_TIMEOUT
            elif _real_model.startswith(_TGWUI_PREFIX):
                # tgwui: prefix but no base URL configured
                yield 'data: {"error":"text-generation-webui URL не настроен — укажите URL в настройках (☰)"}\n\n'
                return
            else:
                _m = _real_model
                _base = None
                _use_chat = False
                _timeout = _to

            if _use_chat and _base:
                resp = _http.post(
                    f"{_base}/v1/chat/completions",
                    json={
                        "model": _m,
                        "messages": [{"role": "user", "content": full_prompt}],
                        "stream": True,
                    },
                    stream=True,
                    timeout=_timeout,
                )
                resp.raise_for_status()
                for raw_line in resp.iter_lines():
                    if not raw_line:
                        continue
                    line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if line in ("", "[DONE]"):
                        continue
                    try:
                        chunk = json.loads(line)
                    except ValueError:
                        continue
                    delta = (chunk.get("choices") or [{}])[0].get("delta", {})
                    token = delta.get("content", "")
                    if token:
                        yield f"data: {json.dumps({'token': token})}\n\n"
                _record_generation("patch", _m, full_prompt)
                yield "data: [DONE]\n\n"
                return

            # Default: Ollama /api/generate
            resp = _http.post(
                f"{OLLAMA_BASE}/api/generate",
                json={"model": _m, "prompt": full_prompt, "stream": True},
                stream=True,
                timeout=_to,
            )
            if resp.status_code == 500:
                err_body = ""
                try:
                    err_body = resp.json().get("error", resp.text[:200])
                except Exception:  # pylint: disable=broad-except
                    err_body = resp.text[:200]
                _err_msg = f'Ollama ошибка 500: {err_body}. Проверьте, что модель "{_m}" загружена (ollama pull {_m}).'
                yield f"data: {json.dumps({'error': _err_msg})}\n\n"
                return
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
                    _record_generation("patch", _m, full_prompt)
                    yield "data: [DONE]\n\n"
                    return
        except _http.exceptions.Timeout:
            _oto = int(os.environ.get("OLLAMA_TIMEOUT", 120))
            yield f'data: {{"error":"Таймаут {_oto} с — модель слишком медленная. Попробуйте увеличить OLLAMA_TIMEOUT или выбрать меньшую модель."}}\n\n'
        except _http.exceptions.ConnectionError:
            yield 'data: {"error":"Нет соединения с ИИ-сервером — запустите Ollama/LM Studio"}\n\n'
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
@app.route("/agent/log_action", methods=["POST"])
def agent_log():
    """Receive one action record from the Telegram bot or UI and persist it.

    Body (full format):
      {
        "timestamp":   "2026-...",
        "action_type": "search|screenshot|article|describe_image|generate_html|gltf_generated|...",
        "input":       {...},
        "output":      {...},
        "success":     true|false,
        "duration_ms": 1234,
        "metadata":    {...}
      }

    Body (short format, accepted by /agent/log_action alias):
      {"action": "gltf_generated", "details": "{...}"}

    The record is:
      1. Appended to vm/training_data/actions.jsonl (one JSON object per line)
      2. Summarised into instructions.json for the self-improvement engine
      3. Auto-triggers _regenerate_instructions every RETRAIN_AFTER_ACTIONS actions
    """
    record = request.get_json(silent=True)
    if not record or not isinstance(record, dict):
        return jsonify({"error": "Invalid JSON body"}), 400
    # Normalise short-form {"action": "...", "details": "..."} sent by gltfAddTraining()
    if "action" in record and "action_type" not in record:
        details_raw = record.get("details", "{}")
        try:
            details = json.loads(details_raw) if isinstance(details_raw, str) else details_raw
        except (ValueError, TypeError):
            details = {"raw": str(details_raw)}
        record = {
            "timestamp":   record.get("timestamp", _now()),
            "action_type": record["action"],
            "input":       details,
            "output":      {},
            "success":     True,
            "duration_ms": 0,
            "metadata":    {},
        }
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
    # Sanitize custom prompt: strip control characters and limit length
    _raw_prompt    = body.get("prompt", "").strip()
    custom_prompt  = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', ' ', _raw_prompt)[:1000] if _raw_prompt else ""

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

    # Select the best available vision model (Ollama or LM Studio)
    selected_model = _best_vision_model()
    if not selected_model:
        # No vision model available — trigger moondream pull and report
        def _pull_moon_desc():
            try:
                _http.post(f"{OLLAMA_BASE}/api/pull", json={"name": "moondream:latest"}, timeout=600)
            except Exception:  # pylint: disable=broad-except
                pass
        threading.Thread(target=_pull_moon_desc, daemon=True).start()
        return jsonify({
            "description": "",
            "model": None,
            "success": False,
            "error": (
                "No vision model available. "
                "Auto-installing moondream:latest (lightweight, ~1 GB). "
                "Try again in a minute, or run: ollama pull moondream"
            ),
            "pulling": "moondream:latest",
        })

    _prompt_describe = custom_prompt if custom_prompt else (
        "Describe this image in detail in Russian. "
        "Include all visible text, objects, layout, and context. "
        "Be specific and informative."
    )

    try:
        is_vvm = selected_model.startswith(_VISION_VM_PREFIX)
        is_lms = selected_model.startswith(_LM_STUDIO_PREFIX)
        if is_vvm:
            real_model = selected_model[len(_VISION_VM_PREFIX):]
            resp = _http.post(
                f"{VISION_VM_URL}/api/generate",
                json={
                    "model":  real_model,
                    "prompt": _prompt_describe,
                    "images": [img_b64],
                    "stream": False,
                },
                timeout=int(os.environ.get("OLLAMA_TIMEOUT", 120)),
            )
            description = ""
            if resp.status_code == 200:
                description = resp.json().get("response", "")
        elif is_lms:
            real_model = selected_model[len(_LM_STUDIO_PREFIX):]
            resp = _http.post(
                f"{LM_STUDIO_BASE}/v1/chat/completions",
                json={
                    "model": real_model,
                    "messages": [{"role": "user", "content": [
                        {"type": "text", "text": _prompt_describe},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                    ]}],
                    "stream": False,
                    "max_tokens": 1024,
                },
                timeout=int(os.environ.get("OLLAMA_TIMEOUT", 120)),
            )
            description = ""
            if resp.status_code == 200:
                choices = resp.json().get("choices", [])
                if choices:
                    description = choices[0].get("message", {}).get("content", "")
        else:
            resp = _http.post(
                f"{OLLAMA_BASE}/api/generate",
                json={
                    "model":  selected_model,
                    "prompt": _prompt_describe,
                    "images": [img_b64],
                    "stream": False,
                },
                timeout=int(os.environ.get("OLLAMA_TIMEOUT", 120)),
            )
            description = ""
            if resp.status_code == 200:
                description = resp.json().get("response", "")

        if description:
            # Log to training data
            _record_agent_action({
                "timestamp":   _now(),
                "action_type": "describe_image",
                "input":       {"image_path": image_path},
                "output":      {"description": description[:400]},
                "success":     True,
                "duration_ms": 0,
                "metadata":    {"model": selected_model},
            })
            return jsonify({
                "description": description,
                "model":       selected_model,
                "success":     True,
            })
        return jsonify({"description": "", "model": selected_model, "success": False,
                        "error": resp.text[:200]}), resp.status_code
    except _http.exceptions.ConnectionError:
        return jsonify({"error": "Cannot connect to Ollama"}), 503
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Image generation via local Stable Diffusion / ComfyUI
# ---------------------------------------------------------------------------

# Note: The canonical URL globals are SD_BASE and COMFYUI_BASE defined at
# module top-level so they can be patched live via /settings.  The aliases
# below are kept for legacy references inside the helper functions.
_COMFYUI_CHECKPOINT  = os.environ.get("COMFYUI_CHECKPOINT",  "v1-5-pruned-emaonly.ckpt")  # default SD 1.5 checkpoint


def _sd_available(base_url: str) -> bool:
    """Return True when a Stable Diffusion (A1111/SD.Next) API responds at *base_url*."""
    try:
        r = _http.get(f"{base_url}/sdapi/v1/samplers", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _comfyui_available(base_url: str) -> bool:
    """Return True when a ComfyUI server responds at *base_url*."""
    try:
        r = _http.get(f"{base_url}/system_stats", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _generate_via_sd(base_url: str, params: dict) -> dict:
    """Call the Automatic1111 / SD.Next txt2img API and return base64 image + metadata."""
    import base64 as _b64

    payload = {
        "prompt":          params.get("prompt", ""),
        "negative_prompt": params.get("negative_prompt", ""),
        "width":           int(params.get("width",     512)),
        "height":          int(params.get("height",    512)),
        "steps":           int(params.get("steps",      20)),
        "cfg_scale":       float(params.get("cfg_scale", 7)),
        "sampler_name":    params.get("sampler_name", "DPM++ 2M Karras"),
        "batch_size":      1,
        "n_iter":          1,
        "save_images":     False,
        "send_images":     True,
    }
    r = _http.post(f"{base_url}/sdapi/v1/txt2img", json=payload, timeout=300)
    r.raise_for_status()
    body = r.json()
    images = body.get("images", [])
    if not images:
        raise ValueError("Stable Diffusion returned no images")
    return {
        "image_base64": images[0],
        "backend":      "stable-diffusion",
        "params":       payload,
        "info":         body.get("info", ""),
    }


def _generate_via_comfyui(base_url: str, params: dict) -> dict:
    """Submit a minimal txt2img workflow to ComfyUI and poll for the result."""
    import base64 as _b64
    import time as _time
    import uuid as _uuid

    prompt_text = params.get("prompt", "")
    negative    = params.get("negative_prompt", "")
    width       = int(params.get("width",  512))
    height      = int(params.get("height", 512))
    steps       = int(params.get("steps",  20))
    cfg         = float(params.get("cfg_scale", 7))
    client_id   = str(_uuid.uuid4())

    # Minimal ComfyUI workflow (SDXL-compatible; adapt model name as needed)
    workflow = {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "model":    ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
                "seed":     42,
                "steps":    steps,
                "cfg":      cfg,
                "sampler_name": "dpmpp_2m",
                "scheduler": "karras",
                "denoise":  1.0,
            },
        },
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": _COMFYUI_CHECKPOINT}},
        "5": {"class_type": "EmptyLatentImage",       "inputs": {"width": width, "height": height, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode",         "inputs": {"text": prompt_text, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode",         "inputs": {"text": negative,    "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode",              "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage",              "inputs": {"images": ["8", 0], "filename_prefix": "drgr_agent"}},
    }

    r = _http.post(f"{base_url}/prompt", json={"prompt": workflow, "client_id": client_id}, timeout=30)
    r.raise_for_status()
    prompt_id = r.json().get("prompt_id")
    if not prompt_id:
        raise ValueError("ComfyUI did not return a prompt_id")

    # Poll /history until done (up to 5 min)
    deadline = _time.time() + 300
    while _time.time() < deadline:
        hist_r = _http.get(f"{base_url}/history/{prompt_id}", timeout=10)
        if hist_r.status_code == 200:
            hist = hist_r.json()
            if prompt_id in hist:
                outputs = hist[prompt_id].get("outputs", {})
                for node_out in outputs.values():
                    for img_meta in node_out.get("images", []):
                        filename  = img_meta["filename"]
                        subfolder = img_meta.get("subfolder", "")
                        img_r = _http.get(
                            f"{base_url}/view",
                            params={"filename": filename, "subfolder": subfolder, "type": "output"},
                            timeout=30,
                        )
                        img_r.raise_for_status()
                        b64 = _b64.b64encode(img_r.content).decode()
                        return {"image_base64": b64, "backend": "comfyui", "params": params}
        _time.sleep(2)
    raise TimeoutError("ComfyUI job timed out after 5 minutes")


@app.route("/imagegen/generate", methods=["POST"])
@app.route("/agent/generate_image", methods=["POST"])
def agent_generate_image():
    """Generate an image via the local Stable Diffusion or ComfyUI API.

    This is the server-side handler for the DRGRBrowserAgent ``GENERATE_IMAGE``
    command.  The agent must call this endpoint — never return NOOP for image
    generation tasks.

    Body (JSON):
      {
        "prompt":          "A futuristic city at night",   // required
        "negative_prompt": "blurry, low quality",          // optional
        "width":           512,                            // optional, default 512
        "height":          512,                            // optional, default 512
        "steps":           20,                             // optional, default 20
        "cfg_scale":       7,                              // optional, default 7
        "save_as":         "output.png"                    // optional filename hint
      }

    Returns:
      {
        "success":      true,
        "image_base64": "<base64 PNG>",
        "backend":      "stable-diffusion" | "comfyui",
        "prompt":       "...",
        "width":        512,
        "height":       512
      }

    Backend priority: Stable Diffusion (localhost:7860) → ComfyUI (localhost:8188).
    Override defaults via SD_API_URL / COMFYUI_API_URL environment variables.
    """
    import base64 as _b64
    import time as _time_mod

    body = request.get_json(silent=True) or {}
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    params = {
        "prompt":          prompt,
        "negative_prompt": body.get("negative_prompt", ""),
        "width":           int(body.get("width",     512)),
        "height":          int(body.get("height",    512)),
        "steps":           int(body.get("steps",      20)),
        "cfg_scale":       float(body.get("cfg_scale", 7)),
        "save_as":         body.get("save_as", ""),
    }

    t_start = _time_mod.time()
    result  = None
    error   = None

    # ── Try Stable Diffusion first ───────────────────────────────────────────
    if _sd_available(SD_BASE):
        try:
            result = _generate_via_sd(SD_BASE, params)
        except Exception as exc:  # pylint: disable=broad-except
            error = f"SD error: {exc}"

    # ── Fall back to ComfyUI ─────────────────────────────────────────────────
    if result is None and _comfyui_available(COMFYUI_BASE):
        try:
            result = _generate_via_comfyui(COMFYUI_BASE, params)
        except Exception as exc:  # pylint: disable=broad-except
            error = f"ComfyUI error: {exc}"

    # ── No backend available ─────────────────────────────────────────────────
    if result is None:
        msg = (
            "No local image generation backend found. "
            "Install one of:\n"
            "  • Stable Diffusion WebUI (AUTOMATIC1111) — starts on port 7860. "
            "Run: webui.bat --api\n"
            "  • ComfyUI — starts on port 8188. "
            "Run: python main.py\n"
            "Or set SD_API_URL / COMFYUI_API_URL environment variables to point "
            "to a running instance."
        )
        return jsonify({"success": False, "error": msg, "hint": error}), 503

    duration_ms = int((_time_mod.time() - t_start) * 1000)

    # Optional: save file to projects directory
    saved_path = ""
    save_as = params["save_as"]
    if save_as:
        projects_dir = os.path.join(_DIR, "projects")
        os.makedirs(projects_dir, exist_ok=True)
        save_as = os.path.basename(save_as)  # strip any path traversal
        # Strip any existing extension then always save as .png to avoid confusion
        root, _ext = os.path.splitext(save_as)
        if not root:
            root = "generated"
        save_as = root + ".png"
        saved_path = os.path.join(projects_dir, save_as)
        try:
            with open(saved_path, "wb") as fh:
                fh.write(_b64.b64decode(result["image_base64"]))
        except Exception:  # pylint: disable=broad-except
            saved_path = ""

    # Log action for self-learning
    _record_agent_action({
        "timestamp":   _now(),
        "action_type": "generate_image",
        "input":       {"prompt": prompt[:200], "width": params["width"], "height": params["height"]},
        "output":      {"backend": result["backend"], "saved_path": saved_path},
        "success":     True,
        "duration_ms": duration_ms,
        "metadata":    {"steps": params["steps"], "cfg_scale": params["cfg_scale"]},
    })

    return jsonify({
        "success":      True,
        "image_base64": result["image_base64"],
        "backend":      result["backend"],
        "prompt":       prompt,
        "width":        params["width"],
        "height":       params["height"],
        "steps":        params["steps"],
        "duration_ms":  duration_ms,
        "saved_path":   saved_path,
    })


# ---------------------------------------------------------------------------
# Android emulator / mobile code generation endpoints
# ---------------------------------------------------------------------------

_ANDROID_APK_DIR = os.path.join(os.path.dirname(__file__), "static", "android_apks")
os.makedirs(_ANDROID_APK_DIR, exist_ok=True)


@app.route("/android/generate", methods=["POST"])
def android_generate():
    """Generate mobile app code (Kotlin/React Native/Flutter) using the local LLM.

    Body (JSON):
      {
        "prompt":   "Навигатор с GPS и картой OSM",   // required
        "platform": "kotlin" | "react-native" | "flutter",  // optional, default "kotlin"
        "model":    "...",   // optional, overrides default model
      }

    Returns:
      { "code": "...", "files": {...}, "platform": "kotlin" }
    """
    body     = request.get_json(silent=True) or {}
    prompt   = (body.get("prompt") or "").strip()
    platform = (body.get("platform") or "kotlin").strip().lower()
    model    = (body.get("model") or "").strip()

    if not prompt:
        return jsonify({"error": "prompt is required"}), 400
    if not model:
        return jsonify({"error": "model is required — select a model first"}), 400

    platform_hints = {
        "kotlin": (
            "Generate complete Android app source code in Kotlin with Gradle build files. "
            "Include: AndroidManifest.xml, MainActivity.kt, layout XML, build.gradle. "
            "Wrap each file in a ```kotlin or ```xml code block with a comment on the first line "
            "showing the file path, e.g.: // app/src/main/kotlin/com/example/MainActivity.kt"
        ),
        "react-native": (
            "Generate a complete React Native (Expo) mobile app. "
            "Include: App.tsx (or App.js), package.json, app.json. "
            "Wrap each file in a ```javascript or ```typescript code block with a comment "
            "on the first line showing the file path, e.g.: // App.tsx"
        ),
        "flutter": (
            "Generate a complete Flutter mobile app in Dart. "
            "Include: lib/main.dart, pubspec.yaml. "
            "Wrap each file in a ```dart or ```yaml code block with a comment "
            "on the first line showing the file path, e.g.: // lib/main.dart"
        ),
    }
    system_hint = platform_hints.get(platform, platform_hints["kotlin"])

    full_prompt = (
        f"You are an expert mobile developer.\n{system_hint}\n\n"
        f"Task: {prompt}\n\n"
        "Requirements:\n"
        "- Fully working, compilable code — no placeholders or TODOs\n"
        "- Russian-language UI (text labels, strings, comments)\n"
        "- Dark theme\n"
        "- Mobile-first design\n"
        "- Offline-capable where possible\n\n"
        "Return ONLY the code blocks. No explanations outside the code blocks."
    )

    try:
        if model.startswith("lmstudio:"):
            lm_model = model[len("lmstudio:"):]
            resp = _http.post(
                f"{LM_STUDIO_BASE}/v1/chat/completions",
                json={"model": lm_model, "messages": [{"role": "user", "content": full_prompt}],
                      "max_tokens": 4096, "temperature": 0.2},
                timeout=int(os.environ.get("OLLAMA_TIMEOUT", 300)),
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
        elif model.startswith("tgwui:"):
            tg_model = model[len("tgwui:"):]
            resp = _http.post(
                f"{TGWUI_BASE}/v1/chat/completions",
                json={"model": tg_model, "messages": [{"role": "user", "content": full_prompt}],
                      "max_tokens": 4096, "temperature": 0.2},
                timeout=int(os.environ.get("OLLAMA_TIMEOUT", 300)),
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
        else:
            resp = _http.post(
                f"{OLLAMA_BASE}/api/generate",
                json={"model": model, "prompt": full_prompt, "stream": False},
                timeout=int(os.environ.get("OLLAMA_TIMEOUT", 300)),
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "")
    except _http.exceptions.ConnectionError:
        return jsonify({"error": "Cannot connect to AI — is Ollama/LM Studio running?"}), 503
    except _http.exceptions.Timeout:
        return jsonify({"error": "AI request timed out"}), 504
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"error": str(exc)}), 500

    # Parse named file blocks from the response.
    # Uses a split-based approach rather than a regex with [^`]*? to correctly
    # handle code blocks that contain backtick characters (e.g. template literals).
    files = {}
    _FENCE_RE = re.compile(
        r"```(?:kotlin|java|xml|dart|yaml|javascript|typescript|json|groovy)\s*\n"
        r"(?:(?://|#)\s*(?P<path>[^\n]+)\n)?",
    )
    pos = 0
    for m in _FENCE_RE.finditer(raw):
        end_of_fence = m.end()
        close_idx = raw.find("\n```", end_of_fence)
        if close_idx == -1:
            continue
        block_code = raw[end_of_fence:close_idx].strip()
        path_hint  = (m.group("path") or "").strip()
        if block_code:
            key = path_hint if path_hint else f"file_{len(files)+1}"
            files[key] = block_code
        pos = close_idx + 4

    return jsonify({
        "code":     raw,
        "files":    files,
        "platform": platform,
    })


@app.route("/android/apk/upload", methods=["POST"])
def android_apk_upload():
    """Accept an APK file upload and return a download URL.

    Multipart form data:
      file: the APK file
    """
    from werkzeug.utils import secure_filename as _sf
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "no file"}), 400
    name = _sf(f.filename or "app.apk")
    if not name.endswith(".apk"):
        name += ".apk"
    dest = os.path.join(_ANDROID_APK_DIR, name)
    f.save(dest)
    return jsonify({"url": f"/android/apk/{name}", "name": name})


@app.route("/android/apk/<path:filename>")
def android_apk_serve(filename):
    """Serve an APK file for download."""
    from werkzeug.utils import secure_filename as _sf
    safe = _sf(filename)
    return send_from_directory(_ANDROID_APK_DIR, safe, as_attachment=True)


@app.route("/android/apk/list", methods=["GET"])
def android_apk_list():
    """Return a list of uploaded APK files."""
    try:
        files = [
            {"name": f, "url": f"/android/apk/{f}",
             "size": os.path.getsize(os.path.join(_ANDROID_APK_DIR, f))}
            for f in os.listdir(_ANDROID_APK_DIR)
            if f.endswith(".apk")
        ]
    except Exception:
        files = []
    return jsonify({"apks": files})


@app.route("/android/apk/send", methods=["POST"])
def android_apk_send():
    """Send an APK file to the configured Telegram chat via the Bot API.

    Body (JSON):
      { "name": "app-debug.apk", "chat_id": "<optional override>" }
    """
    body = request.get_json(silent=True) or {}
    from werkzeug.utils import secure_filename as _sf
    name = _sf((body.get("name") or "").strip())
    if not name:
        return jsonify({"ok": False, "error": "APK name required"}), 400

    apk_path = os.path.join(_ANDROID_APK_DIR, name)
    if not os.path.isfile(apk_path):
        return jsonify({"ok": False, "error": f"APK not found: {name}"}), 404

    token   = os.environ.get("BOT_TOKEN", "").strip()
    chat_id = body.get("chat_id") or os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token:
        return jsonify({"ok": False, "error": "BOT_TOKEN not configured"}), 503
    if not chat_id:
        return jsonify({"ok": False, "error": "TELEGRAM_CHAT_ID not configured"}), 503

    try:
        import io as _io
        with open(apk_path, "rb") as fh:
            resp = _http.post(
                f"https://api.telegram.org/bot{token}/sendDocument",
                data={"chat_id": chat_id,
                      "caption": f"📦 {name}\n⚙ Установи: Настройки → Безопасность → Неизвестные источники"},
                files={"document": (name, fh, "application/vnd.android.package-archive")},
                timeout=60,
            )
        resp.raise_for_status()
        return jsonify({"ok": True, "name": name})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/android/emulator/status", methods=["GET"])
def android_emulator_status():
    """Check if an Android emulator (ADB) is reachable on localhost."""
    import subprocess as _sp
    try:
        r = _sp.run(
            ["adb", "devices"],
            capture_output=True, text=True, timeout=5
        )
        lines = [ln.strip() for ln in r.stdout.splitlines()
                 if ln.strip() and "List of devices" not in ln]
        devices = [ln for ln in lines if "\t" in ln]
        return jsonify({
            "adb_available": r.returncode == 0,
            "devices": devices,
            "raw": r.stdout.strip(),
        })
    except FileNotFoundError:
        return jsonify({"adb_available": False, "devices": [],
                        "error": "adb not found — install Android SDK"})
    except Exception as exc:
        return jsonify({"adb_available": False, "devices": [], "error": str(exc)})


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
# GLTF Figure Generator — pure-Python, no extra dependencies
# Generates valid GLTF 2.0 (JSON) for primitive 3D shapes.
# ---------------------------------------------------------------------------

import struct as _struct
import math as _math
import base64 as _b64


def _pack_buffer(positions: list, normals: list, indices: list) -> tuple:
    """Pack vertex positions, normals and indices into a binary buffer.

    Returns (buffer_bytes, pos_count, idx_count) where
      - positions/normals are flat lists of floats (3 components each vertex)
      - indices are a flat list of unsigned shorts (must be < 65535 vertices)
    """
    vertex_count = len(positions) // 3
    idx_count    = len(indices)

    # Positions buffer (FLOAT 32)
    pos_bytes = _struct.pack(f"{len(positions)}f", *positions)
    # Normals buffer (FLOAT 32)
    nrm_bytes = _struct.pack(f"{len(normals)}f", *normals)
    # Indices buffer (UNSIGNED SHORT, padded to 4-byte boundary)
    idx_bytes = _struct.pack(f"{idx_count}H", *indices)
    pad_len   = (4 - len(idx_bytes) % 4) % 4
    idx_bytes += b"\x00" * pad_len

    buf = idx_bytes + pos_bytes + nrm_bytes
    return buf, vertex_count, idx_count, len(idx_bytes), len(pos_bytes)


def _gltf_json(shape: str, params: dict) -> dict:
    """Build a GLTF 2.0 dict for the requested shape.

    Supported shapes: cube, sphere, cylinder, cone, torus, plane.
    Returns the GLTF dict (caller embeds the buffer as a data URI).
    """
    if shape == "cube":
        w = float(params.get("width",  1.0))
        h = float(params.get("height", 1.0))
        d = float(params.get("depth",  1.0))
        hw, hh, hd = w / 2, h / 2, d / 2
        # 6 faces × 4 verts each = 24 verts
        faces = [
            # pos_x, pos_y, pos_z, normal_x, normal_y, normal_z
            # +Z face
            (-hw, -hh,  hd,  0, 0,  1), ( hw, -hh,  hd,  0, 0,  1),
            ( hw,  hh,  hd,  0, 0,  1), (-hw,  hh,  hd,  0, 0,  1),
            # -Z face
            ( hw, -hh, -hd,  0, 0, -1), (-hw, -hh, -hd,  0, 0, -1),
            (-hw,  hh, -hd,  0, 0, -1), ( hw,  hh, -hd,  0, 0, -1),
            # +X face
            ( hw, -hh,  hd,  1, 0,  0), ( hw, -hh, -hd,  1, 0,  0),
            ( hw,  hh, -hd,  1, 0,  0), ( hw,  hh,  hd,  1, 0,  0),
            # -X face
            (-hw, -hh, -hd, -1, 0,  0), (-hw, -hh,  hd, -1, 0,  0),
            (-hw,  hh,  hd, -1, 0,  0), (-hw,  hh, -hd, -1, 0,  0),
            # +Y face
            (-hw,  hh,  hd,  0, 1,  0), ( hw,  hh,  hd,  0, 1,  0),
            ( hw,  hh, -hd,  0, 1,  0), (-hw,  hh, -hd,  0, 1,  0),
            # -Y face
            (-hw, -hh, -hd,  0,-1,  0), ( hw, -hh, -hd,  0,-1,  0),
            ( hw, -hh,  hd,  0,-1,  0), (-hw, -hh,  hd,  0,-1,  0),
        ]
        positions = []
        normals   = []
        for f in faces:
            positions += [f[0], f[1], f[2]]
            normals   += [f[3], f[4], f[5]]
        indices = []
        for fi in range(6):
            base = fi * 4
            indices += [base, base+1, base+2, base, base+2, base+3]

    elif shape == "plane":
        w = float(params.get("width",  2.0))
        d = float(params.get("depth",  2.0))
        hw, hd = w / 2, d / 2
        positions = [-hw,0,-hd,  hw,0,-hd,  hw,0,hd,  -hw,0,hd]
        normals   = [0,1,0,  0,1,0,  0,1,0,  0,1,0]
        indices   = [0,1,2,  0,2,3]

    elif shape == "sphere":
        segs_w = max(8, int(params.get("segments_w", 16)))
        segs_h = max(6, int(params.get("segments_h", 12)))
        r = float(params.get("radius", 0.5))
        positions, normals, indices = [], [], []
        for lat in range(segs_h + 1):
            theta = _math.pi * lat / segs_h
            for lon in range(segs_w + 1):
                phi = 2 * _math.pi * lon / segs_w
                x = _math.sin(theta) * _math.cos(phi)
                y = _math.cos(theta)
                z = _math.sin(theta) * _math.sin(phi)
                positions += [x * r, y * r, z * r]
                normals   += [x, y, z]
        for lat in range(segs_h):
            for lon in range(segs_w):
                a = lat * (segs_w + 1) + lon
                b = a + segs_w + 1
                indices += [a, b, a+1, b, b+1, a+1]

    elif shape == "cylinder":
        segs = max(8, int(params.get("segments", 16)))
        r    = float(params.get("radius", 0.5))
        h    = float(params.get("height", 1.0))
        positions, normals, indices = [], [], []
        # Side surface
        for s in range(segs + 1):
            phi = 2 * _math.pi * s / segs
            cx = _math.cos(phi)
            cz = _math.sin(phi)
            positions += [cx*r, -h/2, cz*r,  cx*r, h/2, cz*r]
            normals   += [cx, 0, cz,  cx, 0, cz]
        for s in range(segs):
            base = s * 2
            indices += [base, base+1, base+2, base+1, base+3, base+2]
        # Bottom cap
        bot_center = len(positions) // 3
        positions += [0, -h/2, 0];  normals += [0, -1, 0]
        first_rim = len(positions) // 3
        for s in range(segs):
            phi = 2 * _math.pi * s / segs
            positions += [_math.cos(phi)*r, -h/2, _math.sin(phi)*r]
            normals   += [0, -1, 0]
        for s in range(segs):
            indices += [bot_center, first_rim + (s+1) % segs, first_rim + s]
        # Top cap
        top_center = len(positions) // 3
        positions += [0, h/2, 0];  normals += [0, 1, 0]
        top_rim = len(positions) // 3
        for s in range(segs):
            phi = 2 * _math.pi * s / segs
            positions += [_math.cos(phi)*r, h/2, _math.sin(phi)*r]
            normals   += [0, 1, 0]
        for s in range(segs):
            indices += [top_center, top_rim + s, top_rim + (s+1) % segs]

    elif shape == "cone":
        segs = max(8, int(params.get("segments", 16)))
        r    = float(params.get("radius", 0.5))
        h    = float(params.get("height", 1.0))
        positions, normals, indices = [], [], []
        slope = r / h
        # Side surface
        apex = len(positions) // 3
        positions += [0, h/2, 0];  normals += [0, 1, 0]
        rim_start = len(positions) // 3
        for s in range(segs):
            phi = 2 * _math.pi * s / segs
            cx = _math.cos(phi)
            cz = _math.sin(phi)
            positions += [cx*r, -h/2, cz*r]
            nlen = _math.sqrt(1 + slope*slope)
            normals   += [cx/nlen, slope/nlen, cz/nlen]
        for s in range(segs):
            indices += [apex, rim_start + s, rim_start + (s+1) % segs]
        # Bottom cap
        bot_center = len(positions) // 3
        positions += [0, -h/2, 0];  normals += [0, -1, 0]
        bot_rim = len(positions) // 3
        for s in range(segs):
            phi = 2 * _math.pi * s / segs
            positions += [_math.cos(phi)*r, -h/2, _math.sin(phi)*r]
            normals   += [0, -1, 0]
        for s in range(segs):
            indices += [bot_center, bot_rim + (s+1) % segs, bot_rim + s]

    elif shape == "torus":
        segs_tube  = max(8,  int(params.get("segments_tube",  16)))
        segs_ring  = max(8,  int(params.get("segments_ring",  32)))
        r_major    = float(params.get("radius_major", 0.4))
        r_minor    = float(params.get("radius_minor", 0.15))
        positions, normals, indices = [], [], []
        for i in range(segs_ring + 1):
            phi = 2 * _math.pi * i / segs_ring
            cx = _math.cos(phi)
            cz = _math.sin(phi)
            for j in range(segs_tube + 1):
                theta = 2 * _math.pi * j / segs_tube
                nx = cx * _math.cos(theta)
                ny = _math.sin(theta)
                nz = cz * _math.cos(theta)
                x  = (r_major + r_minor * _math.cos(theta)) * cx
                y  = r_minor * _math.sin(theta)
                z  = (r_major + r_minor * _math.cos(theta)) * cz
                positions += [x, y, z]
                normals   += [nx, ny, nz]
        for i in range(segs_ring):
            for j in range(segs_tube):
                a = i * (segs_tube + 1) + j
                b = a + segs_tube + 1
                indices += [a, b, a+1, b, b+1, a+1]
    else:
        raise ValueError(f"Unknown shape: {shape!r}")

    return positions, normals, indices


def _build_gltf(shape: str, params: dict, color: list | None = None) -> dict:
    """Build a complete GLTF 2.0 dict with an embedded base64 buffer."""
    positions, normals, raw_indices = _gltf_json(shape, params)

    # Clamp indices to unsigned short range (max 65535)
    indices = [int(i) for i in raw_indices]
    buf, vertex_count, idx_count, idx_bytes_len, attr_bytes_len = _pack_buffer(
        positions, normals, indices
    )

    # Compute min/max for position accessor (GLTF validator requires them)
    px = positions[0::3];  py = positions[1::3];  pz = positions[2::3]
    pos_min = [min(px), min(py), min(pz)]
    pos_max = [max(px), max(py), max(pz)]

    buf_b64 = "data:application/octet-stream;base64," + _b64.b64encode(buf).decode()

    r, g, b = (color or [0.4, 0.7, 1.0])[:3]
    a = (color[3] if color and len(color) > 3 else 1.0)

    gltf = {
        "asset": {"version": "2.0", "generator": "drgr-bot GLTF Generator"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": shape}],
        "meshes": [{
            "name": shape,
            "primitives": [{
                "attributes": {"POSITION": 1, "NORMAL": 2},
                "indices": 0,
                "material": 0,
            }]
        }],
        "accessors": [
            # Indices
            {
                "bufferView": 0, "componentType": 5123, "count": idx_count,
                "type": "SCALAR",
            },
            # Positions
            {
                "bufferView": 1, "componentType": 5126, "count": vertex_count,
                "type": "VEC3", "min": pos_min, "max": pos_max,
            },
            # Normals
            {
                "bufferView": 2, "componentType": 5126, "count": vertex_count,
                "type": "VEC3",
            },
        ],
        "bufferViews": [
            # Indices view
            {"buffer": 0, "byteOffset": 0, "byteLength": idx_bytes_len, "target": 34963},
            # Positions view
            {"buffer": 0, "byteOffset": idx_bytes_len,
             "byteLength": attr_bytes_len, "target": 34962},
            # Normals view
            {"buffer": 0, "byteOffset": idx_bytes_len + attr_bytes_len,
             "byteLength": attr_bytes_len, "target": 34962},
        ],
        "buffers": [{"uri": buf_b64, "byteLength": len(buf)}],
        "materials": [{
            "name": "default",
            "pbrMetallicRoughness": {
                "baseColorFactor": [r, g, b, a],
                "metallicFactor": 0.0,
                "roughnessFactor": 0.5,
            },
            "doubleSided": True,
        }],
    }
    return gltf


@app.route("/generate/gltf", methods=["POST"])
def generate_gltf():
    """Generate a GLTF 2.0 figure and return it as JSON or a downloadable file.

    Body (JSON):
      shape    — "cube" | "sphere" | "cylinder" | "cone" | "torus" | "plane"
      params   — dict of shape-specific parameters (optional)
      color    — [r, g, b, a] 0-1 floats (optional, default blue-ish)
      download — bool, if true respond with application/json + Content-Disposition

    Shape params:
      cube:     width, height, depth  (default 1)
      plane:    width, depth          (default 2)
      sphere:   radius (0.5), segments_w (16), segments_h (12)
      cylinder: radius (0.5), height (1), segments (16)
      cone:     radius (0.5), height (1), segments (16)
      torus:    radius_major (0.4), radius_minor (0.15),
                segments_ring (32), segments_tube (16)
    """
    body     = request.get_json(silent=True) or {}
    shape    = str(body.get("shape", "cube")).lower()
    params   = body.get("params", {}) or {}
    color    = body.get("color", None)
    download = bool(body.get("download", False))

    _VALID_SHAPES = {"cube", "sphere", "cylinder", "cone", "torus", "plane"}
    if shape not in _VALID_SHAPES:
        return jsonify({"error": f"Unknown shape '{shape}'. Choose from: {sorted(_VALID_SHAPES)}"}), 400

    try:
        gltf = _build_gltf(shape, params, color)
    except (ValueError, TypeError, OverflowError, _struct.error) as exc:
        return jsonify({"error": str(exc)}), 400

    gltf_json_bytes = json.dumps(gltf, ensure_ascii=False, indent=2).encode("utf-8")

    if download:
        from flask import Response as _FResponse
        return _FResponse(
            gltf_json_bytes,
            mimetype="model/gltf+json",
            headers={"Content-Disposition": f"attachment; filename={shape}.gltf"},
        )

    return app.response_class(
        gltf_json_bytes,
        mimetype="application/json",
    )


@app.route("/generate/gltf/shapes", methods=["GET"])
def generate_gltf_shapes():
    """Return the list of supported shapes and their default parameters."""
    return jsonify({
        "shapes": [
            {"name": "cube",     "params": {"width": 1, "height": 1, "depth": 1}},
            {"name": "plane",    "params": {"width": 2, "depth": 2}},
            {"name": "sphere",   "params": {"radius": 0.5, "segments_w": 16, "segments_h": 12}},
            {"name": "cylinder", "params": {"radius": 0.5, "height": 1, "segments": 16}},
            {"name": "cone",     "params": {"radius": 0.5, "height": 1, "segments": 16}},
            {"name": "torus",    "params": {"radius_major": 0.4, "radius_minor": 0.15,
                                            "segments_ring": 32, "segments_tube": 16}},
        ]
    })


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
# Browser screenshot + AI page analysis
# ---------------------------------------------------------------------------

@app.route("/browse/screenshot", methods=["POST"])
def browse_screenshot():
    """Take a screenshot of a URL and analyse it with the best available vision model.

    Body: {"url": "https://example.com", "model": "gpt-oss:latest"}
      - model (optional): Ollama model name or "lmstudio:<id>" to use a specific
        model for analysis.  Defaults to the best available vision model.
    Returns:
      {"screenshot_base64": "<base64 png>", "description": "...", "url": "...",
       "model": "qwen3-vl:8b", "success": true}

    Falls back gracefully:
      - If Playwright is not installed → fetch page text via requests
      - If no vision model → return screenshot only (no description)
    """
    import base64 as _b64

    body = request.get_json(silent=True) or {}
    url  = body.get("url", "").strip()
    # Optional explicit model override (e.g. "gpt-oss:latest" or "lmstudio:zai-org/glm-4.6v-flash")
    model_override = body.get("model", "").strip()
    if not url:
        return jsonify({"error": "Provide url", "success": False}), 400
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # ── SSRF guard — block requests to private / loopback addresses ───────────
    # Also reconstructs URL from parsed parts to break the taint chain.
    safe_url = ""
    try:
        import ipaddress as _ipaddress
        import urllib.parse as _urlparse
        parsed = _urlparse.urlparse(url)
        hostname = parsed.hostname or ""
        # Block loopback and reserved addresses by name
        _BLOCKED_HOSTS = {
            "localhost", "ip6-localhost", "ip6-loopback",
            "0.0.0.0", "::1", "::ffff:127.0.0.1",
        }
        if hostname in _BLOCKED_HOSTS:
            return jsonify({"error": "Requests to internal addresses are not allowed", "success": False}), 400
        # Block by IP range (handles 10.x, 172.16-31.x, 192.168.x, 127.x etc.)
        try:
            addr = _ipaddress.ip_address(hostname)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                return jsonify({"error": "Requests to private/reserved IP addresses are not allowed", "success": False}), 400
        except ValueError:
            pass  # hostname is a domain name, not an IP — that's fine
        # Reconstruct from parsed parts to produce a clean, sanitised URL string
        safe_url = _urlparse.urlunparse((
            parsed.scheme, parsed.netloc, parsed.path,
            "", parsed.query, "",
        ))
    except Exception as ssrf_exc:
        _log.warning("browse_screenshot: SSRF guard error for request, rejecting: %s", ssrf_exc)
        return jsonify({"error": "Could not validate URL for safety", "success": False}), 400
    if not safe_url:
        return jsonify({"error": "Could not construct safe URL", "success": False}), 400

    screenshot_b64 = ""

    # ── Attempt Playwright screenshot ────────────────────────────────────────
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
        from playwright.sync_api import TimeoutError as _PWTimeout  # type: ignore

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 800})
                page.goto(safe_url, wait_until="domcontentloaded", timeout=20_000)
                page.wait_for_timeout(1500)
                buf = page.screenshot(type="png", full_page=False)
                screenshot_b64 = _b64.b64encode(buf).decode()
            except _PWTimeout:
                _log.warning("browse_screenshot: timeout loading %s", safe_url)
            finally:
                browser.close()
    except ImportError:
        _log.debug("browse_screenshot: Playwright not installed, using text fallback")
    except Exception as exc:
        _log.debug("browse_screenshot: Playwright error: %s", exc)

    # ── Text fallback when screenshot unavailable ─────────────────────────────
    if not screenshot_b64:
        try:
            r = _http.get(
                safe_url, timeout=10,
                headers={"User-Agent": "Mozilla/5.0 (compatible; DRGRBot/1.0)"},
            )
            text = re.sub(r"<[^>]+>", " ", r.text)
            text = re.sub(r"\s+", " ", text).strip()[:1200]
            return jsonify({
                "screenshot_base64": "",
                "description": (
                    "Скриншот недоступен (Playwright не установлен или страница заблокирована).\n"
                    f"Текст страницы:\n{text}"
                ),
                "url": url,
                "model": None,
                "success": False,
                "text_fallback": True,
            })
        except Exception as exc2:
            return jsonify({"error": str(exc2), "url": url, "success": False}), 500

    # ── Pick vision model ─────────────────────────────────────────────────────
    selected_model = model_override or None
    # Highest priority: dedicated Vision VM
    if not selected_model and VISION_VM_URL:
        try:
            r = _http.get(f"{VISION_VM_URL}/api/tags", timeout=3)
            if r.status_code == 200:
                available = {m["name"] for m in r.json().get("models", [])}
                for candidate in _VISION_MODELS:
                    if candidate in available:
                        selected_model = f"{_VISION_VM_PREFIX}{candidate}"
                        break
                if not selected_model and available:
                    selected_model = f"{_VISION_VM_PREFIX}{next(iter(available))}"
        except Exception:
            pass
    if not selected_model:
        try:
            r = _http.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
            if r.status_code == 200:
                available = {m["name"] for m in r.json().get("models", [])}
                for candidate in _VISION_MODELS:
                    if candidate in available:
                        selected_model = candidate
                        break
        except Exception:
            pass

    # Fallback to LM Studio when no Ollama vision model is available
    if not selected_model and LM_STUDIO_BASE:
        try:
            r = _http.get(f"{LM_STUDIO_BASE}/v1/models", timeout=10)
            if r.status_code == 200:
                lms_models = r.json().get("data", [])
                if lms_models:
                    # Prefer models with known vision patterns
                    for lm in lms_models:
                        mid = (lm.get("id") or "").lower()
                        if any(pat in mid for pat in _LM_STUDIO_VISION_PATTERNS):
                            selected_model = f"{_LM_STUDIO_PREFIX}{lm['id']}"
                            break
                    if not selected_model:
                        selected_model = f"{_LM_STUDIO_PREFIX}{lms_models[0]['id']}"
        except Exception:
            pass

    description = ""
    if selected_model:
        _prompt_page = (
            "Опиши эту веб-страницу подробно на русском языке. "
            "Укажи: заголовок страницы, основной контент, навигацию, "
            "ключевые элементы интерфейса и кнопки управления, "
            "что происходит на странице и какие действия можно выполнить."
        )
        try:
            is_vvm = selected_model.startswith(_VISION_VM_PREFIX)
            is_lms = selected_model.startswith(_LM_STUDIO_PREFIX)
            if is_vvm:
                real_model = selected_model[len(_VISION_VM_PREFIX):]
                r = _http.post(
                    f"{VISION_VM_URL}/api/generate",
                    json={
                        "model":  real_model,
                        "prompt": _prompt_page,
                        "images": [screenshot_b64],
                        "stream": False,
                    },
                    timeout=int(os.environ.get("OLLAMA_TIMEOUT", 120)),
                )
                if r.status_code == 200:
                    description = r.json().get("response", "")
            elif is_lms:
                real_model = selected_model[len(_LM_STUDIO_PREFIX):]
                r = _http.post(
                    f"{LM_STUDIO_BASE}/v1/chat/completions",
                    json={
                        "model": real_model,
                        "messages": [{"role": "user", "content": [
                            {"type": "text", "text": _prompt_page},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}},
                        ]}],
                        "stream": False,
                        "max_tokens": 1024,
                    },
                    timeout=int(os.environ.get("OLLAMA_TIMEOUT", 120)),
                )
                if r.status_code == 200:
                    choices = r.json().get("choices", [])
                    if choices:
                        description = choices[0].get("message", {}).get("content", "")
            else:
                r = _http.post(
                    f"{OLLAMA_BASE}/api/generate",
                    json={
                        "model":  selected_model,
                        "prompt": _prompt_page,
                        "images": [screenshot_b64],
                        "stream": False,
                    },
                    timeout=int(os.environ.get("OLLAMA_TIMEOUT", 120)),
                )
                if r.status_code == 200:
                    description = r.json().get("response", "")
        except Exception as exc:
            _log.debug("browse_screenshot vision analysis failed: %s", exc)

    # Log to training data
    _record_agent_action({
        "timestamp":   _now(),
        "action_type": "browse_screenshot",
        "input":       {"url": url},
        "output":      {"description": description[:300], "has_screenshot": True},
        "success":     True,
        "duration_ms": 0,
        "metadata":    {"model": selected_model},
    })

    return jsonify({
        "screenshot_base64": screenshot_b64,
        "description":       description,
        "url":               url,
        "model":             selected_model,
        "success":           True,
    })


# ---------------------------------------------------------------------------
# Lightweight vision fallback — moondream auto-pull / status endpoint
# ---------------------------------------------------------------------------

@app.route("/vision/light/check", methods=["GET"])
def vision_light_check():
    """Check lightweight vision model availability; trigger auto-pull if absent.

    Returns: {available: bool, model: "moondream:latest"|"", pulling: bool, status: "ok"|"pulling"|"none"}
    A GET request checks if a lightweight vision model (moondream) is present in Ollama.
    If missing and pull_if_absent=1 query param is set, starts an async pull.
    Used by the Chrome extension on startup to ensure basic image description works
    even when no heavy vision model (qwen3-vl / llava) is installed.
    When a full vision VM (VISION_VM_URL) is configured and reachable, the light VM is
    considered unnecessary and the response marks it as not needed.
    """
    pull_if_absent = request.args.get("pull_if_absent", "0") == "1"

    # If a dedicated Vision VM is already online, no light VM needed
    if VISION_VM_URL:
        try:
            r = _http.get(f"{VISION_VM_URL}/api/tags", timeout=3)
            if r.status_code == 200 and r.json().get("models"):
                return jsonify({
                    "available": True,
                    "model": "",
                    "pulling": False,
                    "status": "vision_vm_active",
                    "message": "Vision VM already active — light fallback not needed",
                })
        except Exception:  # pylint: disable=broad-except
            pass

    _light_candidates = ["moondream:latest", "moondream:1.8b", "moondream", "minicpm-v:latest", "minicpm-v"]
    found_model = ""
    try:
        r = _http.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
        if r.status_code == 200:
            available = {m.get("name", "") for m in r.json().get("models", [])}
            for c in _light_candidates:
                if c in available:
                    found_model = c
                    break
    except Exception:  # pylint: disable=broad-except
        return jsonify({"available": False, "model": "", "pulling": False, "status": "ollama_unreachable"})

    if found_model:
        return jsonify({"available": True, "model": found_model, "pulling": False, "status": "ok"})

    if pull_if_absent:
        # Start async pull of moondream (lightweight ~1 GB vision model)
        def _do_pull():
            try:
                _http.post(f"{OLLAMA_BASE}/api/pull", json={"name": "moondream:latest"}, timeout=600)
            except Exception:  # pylint: disable=broad-except
                pass
        threading.Thread(target=_do_pull, daemon=True).start()
        return jsonify({"available": False, "model": "moondream:latest", "pulling": True,
                        "status": "pulling",
                        "message": "moondream:latest pull started — light vision will be available soon"})

    return jsonify({"available": False, "model": "", "pulling": False, "status": "none",
                    "message": "No lightweight vision model found. Request with ?pull_if_absent=1 to auto-install moondream."})


# ---------------------------------------------------------------------------
# Visor VM — create retrained qwen3-vl model + live page-watch endpoint
# ---------------------------------------------------------------------------

@app.route("/ollama/create-visor-vm", methods=["POST"])
def create_visor_vm():
    """Create (or recreate) the drgr-visor custom model from qwen3-vl:8b.

    Reads vm/Modelfile.qwen3-visor and submits it to Ollama's /api/create
    endpoint as a streaming SSE response so the UI can show download progress.

    Body: {} — no parameters needed, everything is read from the Modelfile.
    Returns: text/event-stream with {"status": "...", "done": true|false}
    """
    modelfile_path = os.path.join(_DIR, "Modelfile.qwen3-visor")
    try:
        with open(modelfile_path, "r", encoding="utf-8") as fh:
            modelfile_content = fh.read()
    except FileNotFoundError:
        return jsonify({"error": f"Modelfile not found: {modelfile_path}"}), 500

    model_name = "drgr-visor"
    payload    = _ollama_create_payload(model_name, modelfile_content)

    def _stream():
        _creating_msg = f"Creating model '{model_name}' from qwen3-vl:8b..."
        yield f"data: {json.dumps({'status': _creating_msg})}\n\n"
        try:
            with _http.post(
                f"{OLLAMA_BASE}/api/create",
                json=payload,
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
                    status = obj.get("status", "")
                    error  = obj.get("error", "")
                    yield f"data: {json.dumps({'status': status, 'error': error})}\n\n"
            _done_status = f"✅ Модель '{model_name}' создана! Используй её в настройках как '{model_name}'"
            yield f"data: {json.dumps({'status': _done_status, 'done': True})}\n\n"
        except _http.exceptions.Timeout:
            _oto = int(os.environ.get("OLLAMA_TIMEOUT", 120))
            yield f'data: {{"error":"Ollama не ответил за {_oto} с — модель слишком медленная. Попробуйте увеличить OLLAMA_TIMEOUT или выбрать меньшую модель."}}\n\n'
        except _http.exceptions.ConnectionError:
            yield "data: {\"error\":\"Cannot connect to Ollama — убедись что Ollama запущена\"}\n\n"
        except Exception as exc:  # pylint: disable=broad-except
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return Response(
        stream_with_context(_stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Autonomous Browser Agent — DRGRBrowserAgent execution loop
# ---------------------------------------------------------------------------

@app.route("/browse/agent/run", methods=["POST"])
def browse_agent_run():
    """Execute a multi-step autonomous browser task via DRGRBrowserAgent protocol.

    Body: {"task": "...", "model": "...", "max_steps": 20, "start_url": "https://..."}
    Returns: text/event-stream with per-cycle JSON objects:
      {"cycle": N, "thoughts": {...}, "commands": [...], "results": [...], "done": bool}

    The endpoint asks the model for the next cycle of commands, executes each
    command (NAVIGATE / CLICK / TYPE / SCREENSHOT / WAIT / SCROLL / NOOP) using
    Playwright, feeds the screenshot back to the vision model and repeats until
    the model sets cycle_state.status to "finished_*" or max_steps is reached.
    """
    import base64 as _b64

    body      = request.get_json(silent=True) or {}
    task      = body.get("task", "").strip()
    model     = body.get("model", "").strip()
    max_steps = max(1, min(int(body.get("max_steps", 20)), 80))
    start_url = body.get("start_url", "").strip()

    if not task:
        return jsonify({"error": "Provide task"}), 400
    if not model:
        return jsonify({"error": "Provide model"}), 400

    vis_model = _best_vision_model() or model

    def _ssrf_ok(url: str) -> bool:
        """Return True if the URL is not a private/loopback address."""
        try:
            import ipaddress as _ipa
            import urllib.parse as _up
            parsed = _up.urlparse(url)
            host = parsed.hostname or ""
            if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
                return False
            try:
                addr = _ipa.ip_address(host)
                if addr.is_private or addr.is_loopback or addr.is_link_local:
                    return False
            except ValueError:
                pass
            return True
        except Exception:
            return False

    def _stream():
        # Try to import Playwright; stream an error if not available
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
            from playwright.sync_api import TimeoutError as _PWTimeout  # type: ignore
        except ImportError:
            yield (
                'data: {"error":"Playwright не установлен. '
                'Запустите: playwright install chromium"}\n\n'
            )
            return

        context_history: list = []
        current_url = start_url or ""
        last_screenshot_b64 = ""

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = browser.new_page(viewport={"width": 1280, "height": 800})

            # Navigate to start URL if provided
            if current_url:
                if not current_url.startswith(("http://", "https://")):
                    current_url = "https://" + current_url
                if _ssrf_ok(current_url):
                    try:
                        page.goto(current_url, wait_until="domcontentloaded", timeout=20_000)
                        page.wait_for_timeout(1000)
                        buf = page.screenshot(type="png", full_page=False)
                        last_screenshot_b64 = _b64.b64encode(buf).decode()
                    except Exception as e:
                        yield f"data: {json.dumps({'error': f'Не удалось открыть стартовый URL: {e}'})}\n\n"

            for cycle in range(1, max_steps + 1):
                # Build prompt for the model including current page screenshot
                agent_prompt = (
                    f"Задание: {task}\n\n"
                    f"Шаг {cycle} из {max_steps}.\n"
                    f"Текущий URL: {page.url or 'не определён'}\n"
                    "Опиши, что видишь на странице, и верни JSON с полями:\n"
                    '{"cycle_state":{"status":"running|finished_success|finished_error",'
                    '"current_step":' + str(cycle) + ',"max_steps":' + str(max_steps) + '},'
                    '"thoughts":{"observation":"...","plan_short":"..."},'
                    '"commands":[...]}'
                )

                # Ask model for next commands
                model_response = ""
                try:
                    _vvm_agent = vis_model.startswith(_VISION_VM_PREFIX)
                    _lms_agent = vis_model.startswith(_LM_STUDIO_PREFIX)
                    if _vvm_agent:
                        _real_vis = vis_model[len(_VISION_VM_PREFIX):]
                        _vvm_body: dict = {
                            "model": _real_vis,
                            "prompt": agent_prompt,
                            "stream": False,
                        }
                        if last_screenshot_b64:
                            _vvm_body["images"] = [last_screenshot_b64]
                        r = _http.post(
                            f"{VISION_VM_URL}/api/generate",
                            json=_vvm_body,
                            timeout=int(os.environ.get("OLLAMA_TIMEOUT", 120)),
                        )
                        if r.status_code == 200:
                            model_response = r.json().get("response", "")
                    elif _lms_agent:
                        _real_vis = vis_model[len(_LM_STUDIO_PREFIX):]
                        _content: list = [{"type": "text", "text": agent_prompt}]
                        if last_screenshot_b64:
                            _content.append({"type": "image_url", "image_url": {
                                "url": f"data:image/png;base64,{last_screenshot_b64}"}})
                        r = _http.post(
                            f"{LM_STUDIO_BASE}/v1/chat/completions",
                            json={
                                "model": _real_vis,
                                "messages": [{"role": "user", "content": _content}],
                                "stream": False,
                                "max_tokens": 1024,
                            },
                            timeout=int(os.environ.get("OLLAMA_TIMEOUT", 120)),
                        )
                        if r.status_code == 200:
                            choices = r.json().get("choices", [])
                            if choices:
                                model_response = choices[0].get("message", {}).get("content", "")
                    else:
                        api_body: dict = {
                            "model": vis_model,
                            "prompt": agent_prompt,
                            "stream": False,
                        }
                        if last_screenshot_b64:
                            api_body["images"] = [last_screenshot_b64]
                        r = _http.post(
                            f"{OLLAMA_BASE}/api/generate",
                            json=api_body,
                            timeout=int(os.environ.get("OLLAMA_TIMEOUT", 120)),
                        )
                        if r.status_code == 200:
                            model_response = r.json().get("response", "")
                except Exception as exc:
                    yield f"data: {json.dumps({'error': f'Vision model error: {exc}', 'cycle': cycle})}\n\n"
                    break

                # Try to parse JSON from model response
                cycle_json = {}
                try:
                    # Extract JSON block from response
                    m_json = re.search(r"\{.*\}", model_response, re.DOTALL)
                    if m_json:
                        cycle_json = json.loads(m_json.group(0))
                except (ValueError, AttributeError):
                    cycle_json = {"thoughts": {"observation": model_response[:300]}, "commands": []}

                commands  = cycle_json.get("commands", [])
                thoughts  = cycle_json.get("thoughts", {})
                cs        = cycle_json.get("cycle_state", {})
                status    = cs.get("status", "running")
                cmd_results: list = []

                # Execute each command
                for cmd in commands[:5]:  # limit to 5 commands per cycle
                    cmd_type = (cmd.get("type") or "").upper()
                    result   = {"type": cmd_type, "ok": False, "info": ""}
                    try:
                        if cmd_type == "NAVIGATE":
                            nav_url = cmd.get("url", "")
                            if nav_url and _ssrf_ok(nav_url):
                                page.goto(nav_url, wait_until="domcontentloaded", timeout=20_000)
                                page.wait_for_timeout(500)
                                result.update({"ok": True, "info": f"Navigated to {nav_url}"})
                            else:
                                result["info"] = "URL blocked or empty"
                        elif cmd_type == "CLICK":
                            sel = cmd.get("selector", "")
                            if sel:
                                page.click(sel, timeout=5000)
                                page.wait_for_timeout(300)
                                result.update({"ok": True, "info": f"Clicked {sel}"})
                        elif cmd_type == "TYPE":
                            sel  = cmd.get("selector", "")
                            text = cmd.get("text", "")
                            if sel and text:
                                page.fill(sel, text)
                                if cmd.get("submit"):
                                    page.press(sel, "Enter")
                                result.update({"ok": True, "info": f"Typed into {sel}"})
                        elif cmd_type == "WAIT":
                            ms = max(100, min(int(cmd.get("timeout_ms", 1000)), 10000))
                            page.wait_for_timeout(ms)
                            result.update({"ok": True, "info": f"Waited {ms}ms"})
                        elif cmd_type == "SCROLL":
                            direction = cmd.get("direction", "down")
                            amount    = int(cmd.get("amount", 300))
                            delta_y   = amount if direction == "down" else -amount
                            page.evaluate(f"window.scrollBy(0, {delta_y})")
                            result.update({"ok": True, "info": f"Scrolled {direction}"})
                        elif cmd_type in ("SCREENSHOT", "NOOP"):
                            result.update({"ok": True, "info": cmd_type})
                        else:
                            result["info"] = f"Unknown command: {cmd_type}"
                    except Exception as e:
                        result["info"] = str(e)[:200]
                    cmd_results.append(result)

                # Take screenshot after commands
                try:
                    buf = page.screenshot(type="png", full_page=False)
                    last_screenshot_b64 = _b64.b64encode(buf).decode()
                except Exception:
                    last_screenshot_b64 = ""

                # Log agent action
                _record_agent_action({
                    "timestamp":   _now(),
                    "action_type": "browser_agent_cycle",
                    "input":       {"task": task[:120], "cycle": cycle},
                    "output":      {"status": status, "commands": len(commands)},
                    "success":     status.startswith("finished_success"),
                    "duration_ms": 0,
                    "metadata":    {"url": page.url},
                })

                yield f"data: {json.dumps({'cycle': cycle, 'url': page.url, 'thoughts': thoughts, 'commands': commands, 'results': cmd_results, 'screenshot': last_screenshot_b64[:200] + '...' if last_screenshot_b64 else '', 'status': status})}\n\n"

                if status.startswith("finished_"):
                    break

            browser.close()
            yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(_stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )



@app.route("/visor/watch", methods=["POST"])
def visor_watch():
    """Continuously screenshot a URL and report AI-detected changes (SSE).

    Body: {"url": "https://...", "interval": 10, "max_snapshots": 5}
    Returns: text/event-stream with per-snapshot JSON objects:
      {"snapshot": 1, "description": "...", "change": "...", "url": "..."}

    Uses the best available vision model to describe each snapshot and compute
    a diff summary compared to the previous snapshot.  Stops after max_snapshots.
    """
    import base64 as _b64

    body         = request.get_json(silent=True) or {}
    url          = body.get("url", "").strip()
    interval_sec = max(3, min(int(body.get("interval", 10)), 60))
    max_snaps    = max(1, min(int(body.get("max_snapshots", 5)), 20))

    if not url:
        return jsonify({"error": "Provide url"}), 400
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # SSRF guard (same logic as /browse/screenshot)
    try:
        import ipaddress as _ipaddress
        import urllib.parse as _urlparse2
        _parsed2 = _urlparse2.urlparse(url)
        _hostname2 = _parsed2.hostname or ""
        _BLOCKED2 = {"localhost", "ip6-localhost", "0.0.0.0", "::1"}
        if _hostname2 in _BLOCKED2:
            return jsonify({"error": "Requests to internal addresses not allowed"}), 400
        try:
            _addr2 = _ipaddress.ip_address(_hostname2)
            if _addr2.is_private or _addr2.is_loopback or _addr2.is_link_local:
                return jsonify({"error": "Requests to private IP addresses not allowed"}), 400
        except ValueError:
            pass
        url = _urlparse2.urlunparse((
            _parsed2.scheme, _parsed2.netloc, _parsed2.path, "", _parsed2.query, ""
        ))
    except Exception:
        return jsonify({"error": "Could not validate URL"}), 400

    # Select vision model: prefer drgr-visor (our retrained model), then qwen3-vl:8b
    vis_model = _best_vision_model()

    def _stream():
        prev_description = ""
        for snap_n in range(1, max_snaps + 1):
            if snap_n > 1:
                time.sleep(interval_sec)

            # Take screenshot via same code path as /browse/screenshot
            screenshot_b64 = ""
            try:
                from playwright.sync_api import sync_playwright  # type: ignore
                from playwright.sync_api import TimeoutError as _PWTimeout  # type: ignore
                with sync_playwright() as _pw:
                    _brow = _pw.chromium.launch(headless=True, args=["--no-sandbox"])
                    try:
                        _pg = _brow.new_page(viewport={"width": 1280, "height": 800})
                        _pg.goto(url, wait_until="networkidle", timeout=20_000)
                        _img_bytes = _pg.screenshot(full_page=False)
                        screenshot_b64 = _b64.b64encode(_img_bytes).decode()
                    except _PWTimeout:
                        pass
                    finally:
                        _brow.close()
            except Exception:
                pass

            if not screenshot_b64:
                payload = json.dumps({
                    "snapshot": snap_n, "url": url,
                    "error": "Playwright not available — установи: playwright install chromium",
                    "done": snap_n == max_snaps,
                })
                yield f"data: {payload}\n\n"
                break

            # Ask vision model to describe this snapshot
            description = ""
            change_summary = ""
            try:
                vis_body: dict = {
                    "model": vis_model,
                    "prompt": (
                        "Опиши подробно что видишь на этом скриншоте веб-страницы. "
                        "Что изменилось по сравнению с предыдущим снимком?\n"
                        f"Предыдущее описание: {prev_description[:500] or 'нет (первый снимок)'}"
                    ),
                    "images": [screenshot_b64],
                    "stream": False,
                }
                _vis_prompt = vis_body["prompt"]
                _is_vvm_snap = vis_model.startswith(_VISION_VM_PREFIX)
                _is_lms_snap = vis_model.startswith(_LM_STUDIO_PREFIX)
                if _is_vvm_snap:
                    _real_vis_snap = vis_model[len(_VISION_VM_PREFIX):]
                    _r = _http.post(
                        f"{VISION_VM_URL}/api/generate",
                        json={
                            "model": _real_vis_snap,
                            "prompt": _vis_prompt,
                            "images": [screenshot_b64],
                            "stream": False,
                        },
                        timeout=60,
                    )
                    if _r.status_code == 200:
                        description = _r.json().get("response", "")
                elif _is_lms_snap:
                    _real_vis_snap = vis_model[len(_LM_STUDIO_PREFIX):]
                    _r = _http.post(
                        f"{LM_STUDIO_BASE}/v1/chat/completions",
                        json={
                            "model": _real_vis_snap,
                            "messages": [{"role": "user", "content": [
                                {"type": "text", "text": _vis_prompt},
                                {"type": "image_url", "image_url": {
                                    "url": f"data:image/png;base64,{screenshot_b64}"}},
                            ]}],
                            "stream": False,
                            "max_tokens": 1024,
                        },
                        timeout=60,
                    )
                    if _r.status_code == 200:
                        _choices = _r.json().get("choices", [])
                        if _choices:
                            description = _choices[0].get("message", {}).get("content", "")
                else:
                    _r = _http.post(
                        f"{OLLAMA_BASE}/api/generate",
                        json=vis_body,
                        timeout=60,
                    )
                    if _r.status_code == 200:
                        description = _r.json().get("response", "")
                if prev_description and description:
                    # Compute word-level overlap as a similarity proxy
                    prev_words = set(prev_description.lower().split())
                    curr_words = set(description.lower().split())
                    overlap = len(prev_words & curr_words)
                    total   = max(len(prev_words | curr_words), 1)
                    similarity = overlap / total
                    change_summary = (
                        "Нет значимых изменений" if similarity > 0.85
                        else f"Обнаружены изменения на странице (сходство: {similarity:.0%})"
                    )
            except Exception as exc:
                description = f"Ошибка AI анализа: {exc}"

            prev_description = description

            payload = json.dumps({
                "snapshot":    snap_n,
                "url":         url,
                "model":       vis_model,
                "description": description[:1000],
                "change":      change_summary,
                "done":        snap_n == max_snaps,
            })
            yield f"data: {payload}\n\n"

    return Response(
        stream_with_context(_stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _best_vision_model() -> str:
    """Return the best available vision model name.

    Priority: Vision VM (visionvm:) → Ollama (OLLAMA_BASE) → LM Studio (lmstudio:)
              → lightweight fallback (moondream).
    When VISION_VM_URL is configured and online, all vision requests are routed
    to the dedicated vision instance, effectively bypassing the primary Ollama.
    """
    # Only genuine vision/multimodal models belong here (text-only models excluded)
    preferred = ["qwen3-vl:8b", "qwen3-vl:235b-cloud", "llava", "llava:13b", "llava:7b",
                 "llava:34b", "bakllava", "minicpm-v:latest", "minicpm-v", "moondream",
                 "moondream:latest", "moondream:1.8b", "glm-4v", "cogvlm"]
    # Lightweight fallback models (fast, ~1 GB, suitable when no heavy vision model)
    _light_vision = ["moondream:latest", "moondream:1.8b", "moondream", "minicpm-v:latest", "minicpm-v"]
    # Vision capability name patterns
    _vision_patterns = ("vl", "vision", "llava", "bakllava", "moondream", "minicpm-v", "glm-4v", "cogvlm")

    # 1. Dedicated Vision VM (another Ollama instance) — highest priority
    if VISION_VM_URL:
        try:
            r = _http.get(f"{VISION_VM_URL}/api/tags", timeout=3)
            if r.status_code == 200:
                available = {m.get("name", "") for m in r.json().get("models", [])}
                for p in preferred:
                    if p in available:
                        return f"{_VISION_VM_PREFIX}{p}"
                # Only return a model from Vision VM if it looks like a vision model
                for m_name in available:
                    if any(pat in m_name.lower() for pat in _vision_patterns):
                        return f"{_VISION_VM_PREFIX}{m_name}"
        except Exception:  # pylint: disable=broad-except
            pass
    # 2. Primary Ollama instance
    try:
        r = _http.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
        if r.status_code == 200:
            available = {m.get("name", "") for m in r.json().get("models", [])}
            for p in preferred:
                if p in available:
                    return p
            # Check lightweight vision models in Ollama
            for lv in _light_vision:
                if lv in available:
                    return lv
            # Check any model with vision-related name pattern
            for m_name in available:
                m_lower = m_name.lower()
                if any(pat in m_lower for pat in ("vl", "vision", "llava", "bakllava", "moondream", "minicpm-v", "glm-4v")):
                    return m_name
    except Exception:
        pass
    # 3. Fallback: try LM Studio — only models with known vision capability patterns
    if LM_STUDIO_BASE:
        try:
            r = _http.get(f"{LM_STUDIO_BASE}/v1/models", timeout=10)
            if r.status_code == 200:
                lms_models = r.json().get("data", [])
                if lms_models:
                    # Only return models whose name matches a known vision pattern
                    for lm in lms_models:
                        mid = (lm.get("id") or "").lower()
                        if any(pat in mid for pat in _LM_STUDIO_VISION_PATTERNS):
                            return f"{_LM_STUDIO_PREFIX}{lm['id']}"
                    # Do NOT fall back to first model — it may not support vision
        except Exception:
            pass
    # 4. Lightweight auto-fallback: try to pull moondream (fast ~1 GB model)
    #    and return its name so the caller can use it once pull completes
    try:
        r = _http.get(f"{OLLAMA_BASE}/api/tags", timeout=3)
        if r.status_code == 200:
            available = {m.get("name", "") for m in r.json().get("models", [])}
            if not any(
                any(pat in m.lower() for pat in ("vl", "vision", "llava", "bakllava", "moondream", "minicpm-v"))
                for m in available
            ):
                # No vision model at all — trigger async pull of moondream (lightweight)
                def _pull_moondream():
                    try:
                        _http.post(
                            f"{OLLAMA_BASE}/api/pull",
                            json={"name": "moondream:latest"},
                            timeout=600,
                        )
                    except Exception:  # pylint: disable=broad-except
                        pass
                threading.Thread(target=_pull_moondream, daemon=True).start()
    except Exception:  # pylint: disable=broad-except
        pass
    return ""


# ---------------------------------------------------------------------------
# Auto-complete code generator — iterative write → run → fix loop
# ---------------------------------------------------------------------------
# The endpoint generates code, executes it, and if it fails automatically
# re-prompts the model with the error context.  It repeats up to max_attempts
# times, so the final result is always verified-working code.

@app.route("/generate/auto/complete", methods=["POST"])
def generate_auto_complete():
    """Generate code, execute it, and auto-fix until it works.

    Body: {"prompt": "...", "model": "...", "max_attempts": 3}
    Returns:
      {"code": "...", "output": "...", "language": "python",
       "success": true, "attempts": 1}

    Supports Python and JavaScript execution; HTML is returned as-is after
    generation (no execution needed).  Unknown languages are also returned
    after the first generation attempt.
    Supports Ollama, LM Studio (prefix "lmstudio:"), and TGWUI (prefix "tgwui:").
    """
    body         = request.get_json(silent=True) or {}
    model        = body.get("model", "").strip()
    prompt       = body.get("prompt", "").strip()
    max_attempts = min(int(body.get("max_attempts", 3)), 5)

    if not model:
        # Auto-detect best available model
        try:
            mr = _http.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
            if mr.status_code == 200:
                models_list = mr.json().get("models", [])
                if models_list:
                    model = models_list[0].get("name", "")
        except Exception:  # pylint: disable=broad-except
            pass
        if not model and LM_STUDIO_BASE and LM_STUDIO_BASE.strip():
            try:
                lms_mr = _http.get(f"{LM_STUDIO_BASE}/v1/models", timeout=5)
                if lms_mr.status_code == 200:
                    lms_list = lms_mr.json().get("data", [])
                    if lms_list:
                        model = f"{_LM_STUDIO_PREFIX}{lms_list[0]['id']}"
            except Exception:  # pylint: disable=broad-except
                pass
        if not model and TGWUI_BASE and TGWUI_BASE.strip():
            try:
                tw_mr = _http.get(f"{TGWUI_BASE}/v1/models", timeout=5)
                if tw_mr.status_code == 200:
                    tw_list = tw_mr.json().get("data", [])
                    if tw_list:
                        model = f"{_TGWUI_PREFIX}{tw_list[0]['id']}"
            except Exception:  # pylint: disable=broad-except
                pass
        if not model and ROO_CODE_BASE and ROO_CODE_BASE.strip():
            try:
                roo_mr = _http.get(f"{ROO_CODE_BASE}/v1/models", timeout=5)
                if roo_mr.status_code == 200:
                    roo_list = roo_mr.json().get("data", [])
                    if roo_list:
                        model = f"{_ROO_CODE_PREFIX}{roo_list[0]['id']}"
            except Exception:  # pylint: disable=broad-except
                pass
    if not model:
        return jsonify({"error": "No model selected", "success": False}), 400
    if not prompt:
        return jsonify({"error": "No prompt provided", "success": False}), 400

    data       = load_instructions()
    sys_prompt = data.get("system_prompt", "").strip() or _DEFAULT_AUTO_SYSTEM_PROMPT

    # Determine backend
    _is_lms_ac     = model.startswith(_LM_STUDIO_PREFIX)
    _is_tgwui_ac   = model.startswith(_TGWUI_PREFIX)
    _is_roo_ac     = model.startswith(_ROO_CODE_PREFIX)
    _real_model_ac = (
        model[len(_LM_STUDIO_PREFIX):] if _is_lms_ac
        else model[len(_TGWUI_PREFIX):] if _is_tgwui_ac
        else model[len(_ROO_CODE_PREFIX):] if _is_roo_ac
        else model
    )

    def _call_llm_ac(user_content: str) -> str:
        """Call the appropriate LLM backend and return the raw text response."""
        if _is_lms_ac:
            r = _http.post(
                f"{LM_STUDIO_BASE}/v1/chat/completions",
                json={"model": _real_model_ac,
                      "messages": [{"role": "system", "content": sys_prompt},
                                   {"role": "user", "content": user_content}],
                      "stream": False},
                timeout=int(os.environ.get("OLLAMA_TIMEOUT", 180)),
            )
            r.raise_for_status()
            return r.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        if _is_tgwui_ac:
            if not TGWUI_BASE:
                raise ValueError("text-generation-webui URL не настроен — укажите URL в настройках (☰)")
            r = _http.post(
                f"{TGWUI_BASE}/v1/chat/completions",
                json={"model": _real_model_ac,
                      "messages": [{"role": "system", "content": sys_prompt},
                                   {"role": "user", "content": user_content}],
                      "stream": False},
                timeout=int(os.environ.get("OLLAMA_TIMEOUT", 180)),
            )
            r.raise_for_status()
            return r.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        if _is_roo_ac:
            if not ROO_CODE_BASE:
                raise ValueError("Roo Code URL не настроен — укажите URL в настройках (☰)")
            r = _http.post(
                f"{ROO_CODE_BASE}/v1/chat/completions",
                json={"model": _real_model_ac,
                      "messages": [{"role": "system", "content": sys_prompt},
                                   {"role": "user", "content": user_content}],
                      "stream": False},
                timeout=int(os.environ.get("OLLAMA_TIMEOUT", 180)),
            )
            r.raise_for_status()
            return r.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        # Ollama
        r = _http.post(
            f"{OLLAMA_BASE}/api/generate",
            json={"model": _real_model_ac,
                  "prompt": f"{sys_prompt}\n\n{user_content}",
                  "stream": False},
            timeout=int(os.environ.get("OLLAMA_TIMEOUT", 180)),
        )
        r.raise_for_status()
        return r.json().get("response", "")

    current_user_content = f"Задание: {prompt}"
    code = output = err_text = ""
    language = "python"

    for attempt in range(1, max_attempts + 1):
        # 1. Generate code
        try:
            raw = _call_llm_ac(current_user_content)
        except _http.exceptions.ConnectionError:
            backend_name = "LM Studio" if _is_lms_ac else "TGWUI" if _is_tgwui_ac else ("Roo Code" if _is_roo_ac else "Ollama")
            return jsonify({
                "error": f"Нет соединения с {backend_name}",
                "success": False, "attempts": attempt,
            }), 503
        except Exception as exc:
            return jsonify({"error": str(exc), "success": False, "attempts": attempt}), 500

        # Detect language from fenced block marker
        raw_lower = raw.lower()
        if "```html" in raw_lower or (
            "```" not in raw_lower and ("<html" in raw_lower or "<!doctype" in raw_lower)
        ):
            language = "html"
        elif "```python" in raw_lower or "```py" in raw_lower:
            language = "python"
        elif "```javascript" in raw_lower or "```js" in raw_lower:
            language = "javascript"
        else:
            language = "python"  # safe default — Python can be executed and tested

        code = _extract_code_block(raw, language)

        # Re-check: if extracted code is actually HTML but was labeled as JS/Python, fix it
        if language in ("javascript", "python") and _is_html_content(code):
            language = "html"

        # 2. HTML: no execution needed — return immediately
        if language == "html":
            _record_generation("html", model, prompt)
            return jsonify({
                "code": code, "output": "", "language": "html",
                "success": True, "attempts": attempt,
            })

        # 3. Execute for Python / JavaScript — verify it actually works
        result   = _run_code(code, language)
        output   = result.get("output", "")
        err_text = result.get("error", "")
        success  = result.get("success", False)

        if success:
            _record_generation(language, model, prompt)
            return jsonify({
                "code": code, "output": output, "language": language,
                "success": True, "attempts": attempt,
            })

        # 4. Re-prompt with error context for next attempt
        if attempt < max_attempts:
            current_user_content = (
                f"Задание: {prompt}\n\n"
                f"Попытка {attempt}: твой код вызвал ошибку при выполнении:\n"
                f"```\n{err_text[:600]}\n```\n"
                f"Вывод программы (если есть):\n```\n{output[:300]}\n```\n\n"
                f"Исправь ВСЕ ошибки и верни полностью исправленный рабочий код. "
                f"ТОЛЬКО код в ``` блоке без объяснений вне блока."
            )

    # All attempts exhausted
    return jsonify({
        "code": code, "output": output, "error": err_text,
        "language": language, "success": False, "attempts": max_attempts,
        "message": (
            f"Не удалось написать рабочий код за {max_attempts} попытки. "
            "Последняя ошибка в поле 'error'."
        ),
    })


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


def _is_chrome_extension_request(prompt: str) -> bool:
    """Return True if the prompt is asking for a Chrome/browser extension."""
    keywords = [
        "chrome extension", "browser extension", "расширение chrome",
        "расширение для chrome", "расширение браузера", "manifest.json",
        "chrome addon", "firefox extension", "sidebar extension", "sidepanel",
        "side panel extension", "content script", "background script",
        "ai blaze", "ai расширение", "расширение ai", "боковая панель расширение",
        "расширение с боковой", "extension sidepanel", "extension sidebar",
    ]
    pl = prompt.lower()
    return any(kw in pl for kw in keywords)


def _generate_chrome_extension_files(model: str, prompt: str, name: str) -> dict:
    """Use the LLM to generate a complete Chrome extension (Manifest V3) as multiple files.

    Generates fully functional extension code with real browser API usage,
    page analysis, image description (via Ollama vision), and Ollama AI chat.
    Returns a dict of {filename: content} for all extension files.
    Supports Ollama models and LM Studio models (prefix "lmstudio:").
    """
    ext_name = name or "AI Assistant"
    sys_prompt = (
        "You are an expert Chrome Extension developer (Manifest V3).\n"
        "Generate a COMPLETE, FULLY FUNCTIONAL Chrome Extension for the task below.\n"
        "\n"
        "ABSOLUTE RULES — VIOLATIONS ARE UNACCEPTABLE:\n"
        "1. NEVER write 'В реальном расширении здесь будет...', 'This is a demo', "
        "'// TODO', '// your code here', 'placeholder', 'stub', or ANY placeholder text.\n"
        "2. Every file must be 100% complete, working code — no ellipsis (...), "
        "no incomplete blocks, no comments saying 'add code here'.\n"
        "3. ALL functions must have REAL implementations — not just console.log or empty bodies.\n"
        "\n"
        "ARCHITECTURE — MV3 background relay for streaming (CORS bypass):\n"
        "   Sidepanel cannot call Ollama directly due to CORS. Use background.js as relay:\n"
        "   sidepanel.js opens a long-lived port: chrome.runtime.connect({name:'ollama_stream'})\n"
        "   then posts {type:'OLLAMA_CHAT', model, messages, images?} to the port.\n"
        "   background.js listens on that port, fetches from\n"
        f"   http://127.0.0.1:{_OLLAMA_RELAY_PORT}/api/chat with stream:true,\n"
        "   reads via response.body.getReader(), splits on '\\n', parses JSON,\n"
        "   extracts token = json.message?.content || json.response || ''\n"
        "   and relays each token back via port.postMessage({token}).\n"
        "   On finish (json.done === true) sends port.postMessage({done:true}).\n"
        "   On error sends port.postMessage({error: e.message}).\n"
        "\n"
        "REQUIRED FEATURES — IMPLEMENT ALL:\n"
        "A. sidepanel.html — complete dark-themed UI with:\n"
        "   - Header with extension name, model selector (gemma3:4b, qwen2.5:3b, llava:7b), status dot\n"
        "   - Chat messages container with user/bot bubbles\n"
        "   - Toolbar: [📸 Скриншот], [🔍 Текст страницы], [🖼 Описать], [📋 HTML]\n"
        "   - Textarea input + Send button (Enter sends, Shift+Enter = newline)\n"
        "   - Emoji picker button with a grid of common emojis\n"
        "   - File/image attach button (input type=file)\n"
        "   - Mobile-responsive CSS with @media queries\n"
        "   - Uses sidepanel.js (separate file referenced with <script src='sidepanel.js'>)\n"
        "\n"
        "B. sidepanel.js — COMPLETE JavaScript implementing ALL of the following:\n"
        "   - sendMessage(text, model, images?): open port via chrome.runtime.connect({name:'ollama_stream'}),\n"
        "     post {type:'OLLAMA_CHAT', model, messages:[{role:'user',content:text}], images},\n"
        "     port.onMessage: append token, on done hideTyping, on error show error\n"
        "   - capturePageScreenshot(): chrome.runtime.sendMessage({type:'CAPTURE_SCREENSHOT'}),\n"
        "     receive dataUrl, display preview, send to Ollama llava/gemma3 for description\n"
        "   - getPageText(): chrome.tabs.query({active:true,currentWindow:true}), then\n"
        "     chrome.scripting.executeScript to get document.body.innerText\n"
        "   - getPageHTML(): executeScript to get document.documentElement.outerHTML\n"
        "   - describeImage(base64): POST via port to background.js with images array for vision description\n"
        "   - handleFileAttach(file): FileReader to read as DataURL if image, as text otherwise\n"
        "   - appendMessage(role, content): creates styled bubble in #messages div\n"
        "   - showTyping() / hideTyping(): typing indicator in chat\n"
        "   - saveHistory() / loadHistory(): chrome.storage.local for persistence\n"
        "   - All event listeners via addEventListener, no inline handlers\n"
        "\n"
        "C. background.js — COMPLETE service worker:\n"
        "   - chrome.sidePanel.setPanelBehavior({openPanelOnActionClick: true}) on install\n"
        "   - chrome.action.onClicked: opens side panel for the tab\n"
        "   - chrome.runtime.onMessage for 'CAPTURE_SCREENSHOT': chrome.tabs.captureVisibleTab\n"
        "   - chrome.runtime.onMessage for 'GET_PAGE_TEXT': chrome.scripting.executeScript\n"
        "   - chrome.runtime.onConnect for port name 'ollama_stream': handle OLLAMA_CHAT messages,\n"
        f"     fetch http://127.0.0.1:{_OLLAMA_RELAY_PORT}/api/chat POST stream:true,\n"
        "     read via response.body.getReader(), split lines, parse JSON,\n"
        "     relay tokens via port.postMessage({token}) and port.postMessage({done:true})\n"
        f"   - On extension install/startup: fetch http://127.0.0.1:{int(os.environ.get('VM_PORT', 5000))}/vision/light/check?pull_if_absent=1\n"
        "     to auto-install lightweight moondream vision model if no vision model is present;\n"
        "     if response.status=='vision_vm_active' or response.available==true, skip pull.\n"
        "     Store {lightVisionReady: bool, lightVisionModel: str} in chrome.storage.local.\n"
        "   - When a vision VM URL is detected (sidepanel sends 'VISION_VM_CONNECTED' message),\n"
        "     store {useVisionVM: true} in chrome.storage.local to suppress light VM usage.\n"
        "\n"
        "D. content.js — COMPLETE content script:\n"
        "   - chrome.runtime.onMessage for 'GET_TEXT': returns document.body.innerText\n"
        "   - chrome.runtime.onMessage for 'GET_HTML': returns outerHTML\n"
        "   - chrome.runtime.onMessage for 'GET_IMAGES': returns [{src,alt}] for img tags\n"
        "   - chrome.runtime.onMessage for 'HIGHLIGHT_TEXT': window.find() highlight\n"
        "   - chrome.runtime.onMessage for 'SCROLL_TO': scrollIntoView on matching element\n"
        "   - chrome.runtime.onMessage for 'CLICK_ELEMENT': click on matching element\n"
        "\n"
        "E. manifest.json — Manifest V3 with permissions: sidePanel, activeTab, scripting,\n"
        f"   tabs, storage; host_permissions: [\"<all_urls>\", \"http://127.0.0.1:{_OLLAMA_RELAY_PORT}/*\", \"http://*:{_OLLAMA_RELAY_PORT}/*\"]\n"
        "\n"
        "LAN SUPPORT: background.js must read the relay URL from chrome.storage.local key\n"
        f"'ollamaRelayUrl' (default 'http://127.0.0.1:{_OLLAMA_RELAY_PORT}/api/chat') so users\n"
        "on other LAN devices can point the extension to a remote relay.\n"
        "Add handler for chrome.runtime.onMessage type='SET_RELAY_URL' that saves msg.url to storage.\n"
        "\n"
        "Output EXACTLY these 5 files. Each file preceded by === filename === on its own line,\n"
        "then immediately a fenced code block (```json / ```html / ```javascript).\n"
        "\n"
        f"Extension name: {ext_name}\n"
        f"Task: {prompt}"
    )

    is_lms = model.startswith(_LM_STUDIO_PREFIX)
    if is_lms:
        real_model = model[len(_LM_STUDIO_PREFIX):]
        lms_url    = _resolve_lms_url()
        resp = _http.post(
            f"{lms_url}/v1/chat/completions",
            json={
                "model": real_model,
                "messages": [
                    {"role": "system", "content": "You are an expert Chrome Extension developer (Manifest V3). Generate only complete, fully functional code."},
                    {"role": "user",   "content": sys_prompt},
                ],
                "stream": False,
            },
            timeout=int(os.environ.get("OLLAMA_TIMEOUT", 300)),
        )
        resp.raise_for_status()
        raw = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
    elif model.startswith(_TGWUI_PREFIX):
        real_model = model[len(_TGWUI_PREFIX):]
        resp = _http.post(
            f"{TGWUI_BASE}/v1/chat/completions",
            json={
                "model": real_model,
                "messages": [
                    {"role": "system", "content": "You are an expert Chrome Extension developer (Manifest V3). Generate only complete, fully functional code."},
                    {"role": "user",   "content": sys_prompt},
                ],
                "stream": False,
            },
            timeout=int(os.environ.get("OLLAMA_TIMEOUT", 300)),
        )
        resp.raise_for_status()
        raw = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
    else:
        resp = _http.post(
            f"{OLLAMA_BASE}/api/generate",
            json={"model": model, "prompt": sys_prompt, "stream": False},
            timeout=int(os.environ.get("OLLAMA_TIMEOUT", 300)),
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "")

    # Parse the response: look for === filename === markers followed by code blocks
    # Pattern allows word chars, dots and hyphens — no slashes to prevent path traversal.
    file_re = re.compile(
        r"===\s*([\w.\-]+)\s*===\s*\n```\w*\n([\s\S]*?)```",
        re.MULTILINE,
    )
    files: dict[str, str] = {}
    for m in file_re.finditer(raw):
        fname = m.group(1).strip()
        content = m.group(2)
        # Sanitize: reject any path traversal attempts
        fname = os.path.basename(fname)
        if fname and content.strip() and not fname.startswith("."):
            files[fname] = content

    # Fallback: if the model didn't follow the format, extract individual code blocks
    if not files:
        manifest = _extract_code_block(raw, "json")
        sidepanel_html = _extract_code_block(raw, "html")
        sidepanel_js = _extract_code_block(raw, "javascript")
        if manifest:
            files["manifest.json"] = manifest
        if sidepanel_html:
            files["sidepanel.html"] = sidepanel_html
        if sidepanel_js:
            files["sidepanel.js"] = sidepanel_js
        bg_match = re.search(r'background\.js.*?```(?:javascript|js)\n([\s\S]*?)```', raw, re.IGNORECASE)
        if bg_match:
            files["background.js"] = bg_match.group(1)
        ct_match = re.search(r'content\.js.*?```(?:javascript|js)\n([\s\S]*?)```', raw, re.IGNORECASE)
        if ct_match:
            files["content.js"] = ct_match.group(1)

    # Ensure a manifest exists even if generation failed partially
    if "manifest.json" not in files:
        files["manifest.json"] = json.dumps({
            "manifest_version": 3,
            "name": ext_name,
            "version": "1.0",
            "description": prompt[:120],
            "permissions": ["sidePanel", "activeTab", "scripting", "tabs", "storage"],
            "host_permissions": [
                "<all_urls>",
                f"http://127.0.0.1:{_OLLAMA_RELAY_PORT}/*",
                f"http://*:{_OLLAMA_RELAY_PORT}/*",
            ],
            "background": {"service_worker": "background.js"},
            "content_scripts": [{"matches": ["<all_urls>"], "js": ["content.js"]}],
            "side_panel": {"default_path": "sidepanel.html"},
            "action": {"default_title": ext_name},
        }, ensure_ascii=False, indent=2)

    # Ensure background.js with correct sidePanel registration and Ollama streaming relay
    if "background.js" not in files:
        files["background.js"] = (
            "// Service Worker — Chrome Extension Manifest V3\n"
            "// Relays streaming Ollama requests from sidepanel via long-lived port\n"
            "// to avoid CORS restrictions in the extension side panel.\n\n"
            "chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });\n\n"
            "chrome.action.onClicked.addListener(function(tab) {\n"
            "  chrome.sidePanel.open({ tabId: tab.id });\n"
            "});\n\n"
            "// Default relay URL (localhost). Override via chrome.storage.local {ollamaRelayUrl}\n"
            f"var _DEFAULT_RELAY = 'http://127.0.0.1:{_OLLAMA_RELAY_PORT}/api/chat';\n\n"
            "async function _getRelayUrl() {\n"
            "  return new Promise(function(resolve) {\n"
            "    try {\n"
            "      chrome.storage.local.get('ollamaRelayUrl', function(d) {\n"
            "        if (chrome.runtime.lastError) {\n"
            "          resolve(_DEFAULT_RELAY);\n"
            "          return;\n"
            "        }\n"
            "        resolve((d && d.ollamaRelayUrl) || _DEFAULT_RELAY);\n"
            "      });\n"
            "    } catch (e) {\n"
            "      resolve(_DEFAULT_RELAY);\n"
            "    }\n"
            "  });\n"
            "}\n\n"
            "// Long-lived port relay for streaming /api/chat responses\n"
            "chrome.runtime.onConnect.addListener(function(port) {\n"
            "  if (port.name !== 'ollama_stream') return;\n"
            "  port.onMessage.addListener(async function(msg) {\n"
            "    if (msg.type !== 'OLLAMA_CHAT') return;\n"
            "    var ollamaUrl = msg.ollamaUrl || (await _getRelayUrl());\n"
            "    try {\n"
            "      var body = JSON.stringify({\n"
            "        model: msg.model || 'gemma3:4b',\n"
            "        messages: msg.messages || [{role:'user', content: msg.message || ''}],\n"
            "        stream: true\n"
            "      });\n"
            "      if (msg.images && msg.images.length) {\n"
            "        var parsed = JSON.parse(body);\n"
            "        parsed.messages[parsed.messages.length - 1].images = msg.images;\n"
            "        body = JSON.stringify(parsed);\n"
            "      }\n"
            "      var resp = await fetch(ollamaUrl, {\n"
            "        method: 'POST',\n"
            "        headers: { 'Content-Type': 'application/json' },\n"
            "        body: body\n"
            "      });\n"
            "      if (!resp.ok) {\n"
            "        port.postMessage({ error: 'HTTP ' + resp.status });\n"
            "        return;\n"
            "      }\n"
            "      var reader = resp.body.getReader();\n"
            "      var decoder = new TextDecoder();\n"
            "      var buf = '';\n"
            "      while (true) {\n"
            "        var _r = await reader.read();\n"
            "        if (_r.done) break;\n"
            "        buf += decoder.decode(_r.value, { stream: true });\n"
            "        var lines = buf.split('\\n');\n"
            "        buf = lines.pop();\n"
            "        for (var i = 0; i < lines.length; i++) {\n"
            "          var line = lines[i].trim();\n"
            "          if (!line) continue;\n"
            "          try {\n"
            "            var json = JSON.parse(line);\n"
            "            var token = (json.message && json.message.content) ||\n"
            "                        json.response || '';\n"
            "            if (token) port.postMessage({ token: token });\n"
            "            if (json.done) { port.postMessage({ done: true }); return; }\n"
            "          } catch (e) { /* skip malformed line */ }\n"
            "        }\n"
            "      }\n"
            "      port.postMessage({ done: true });\n"
            "    } catch (e) {\n"
            "      port.postMessage({ error: e.message });\n"
            "    }\n"
            "  });\n"
            "});\n\n"
            "// One-shot message handlers (screenshot, page text, etc.)\n"
            "chrome.runtime.onMessage.addListener(function(msg, sender, sendResponse) {\n"
            "  if (msg.type === 'CAPTURE_SCREENSHOT') {\n"
            "    chrome.tabs.captureVisibleTab(null, { format: 'jpeg', quality: 80 },\n"
            "      function(dataUrl) { sendResponse({ dataUrl: dataUrl }); });\n"
            "    return true;\n"
            "  }\n"
            "  if (msg.type === 'GET_PAGE_TEXT') {\n"
            "    chrome.scripting.executeScript({\n"
            "      target: { tabId: msg.tabId },\n"
            "      func: function() {\n"
            "        return document.body ? document.body.innerText.slice(0, 8000) : '';\n"
            "      },\n"
            "    }, function(results) {\n"
            "      sendResponse({ text: (results && results[0]) ? results[0].result : '' });\n"
            "    });\n"
            "    return true;\n"
            "  }\n"
            "  if (msg.type === 'SET_RELAY_URL') {\n"
            "    chrome.storage.local.set({ ollamaRelayUrl: msg.url }, function() {\n"
            "      sendResponse({ ok: true });\n"
            "    });\n"
            "    return true;\n"
            "  }\n"
            "  if (msg.type === 'GET_RELAY_URL') {\n"
            "    chrome.storage.local.get('ollamaRelayUrl', function(d) {\n"
            f"      sendResponse({{ url: d.ollamaRelayUrl || 'http://127.0.0.1:{_OLLAMA_RELAY_PORT}/api/chat' }});\n"
            "    });\n"
            "    return true;\n"
            "  }\n"
            "});\n"
        )

    # Ensure content.js exists
    if "content.js" not in files:
        files["content.js"] = (
            "// Content Script — runs on every page\n"
            "chrome.runtime.onMessage.addListener(function(msg, sender, sendResponse) {\n"
            "  if (msg.type === 'GET_TEXT') {\n"
            "    sendResponse({ text: document.body ? document.body.innerText.slice(0, 8000) : '' });\n"
            "    return true;\n"
            "  }\n"
            "  if (msg.type === 'GET_HTML') {\n"
            "    sendResponse({ html: document.documentElement.outerHTML.slice(0, 20000) });\n"
            "    return true;\n"
            "  }\n"
            "  if (msg.type === 'GET_IMAGES') {\n"
            "    var imgs = Array.from(document.querySelectorAll('img')).slice(0, 20).map(\n"
            "      function(img) { return { src: img.src, alt: img.alt || '' }; });\n"
            "    sendResponse({ images: imgs });\n"
            "    return true;\n"
            "  }\n"
            "  if (msg.type === 'HIGHLIGHT_TEXT') {\n"
            "    if (msg.term) window.find(msg.term, false, false, true, false, true, false);\n"
            "    sendResponse({ ok: true });\n"
            "    return true;\n"
            "  }\n"
            "  if (msg.type === 'SCROLL_TO') {\n"
            "    var el = document.querySelector(msg.selector || 'body');\n"
            "    if (el) el.scrollIntoView({ behavior: 'smooth' });\n"
            "    sendResponse({ ok: !!el });\n"
            "    return true;\n"
            "  }\n"
            "  if (msg.type === 'CLICK_ELEMENT') {\n"
            "    var el = document.querySelector(msg.selector || '');\n"
            "    if (el) el.click();\n"
            "    sendResponse({ ok: !!el });\n"
            "    return true;\n"
            "  }\n"
            "});\n"
        )

    # Add README with installation instructions
    files["README.md"] = (
        f"# {ext_name}\n\n"
        f"**Описание:** {prompt}\n\n"
        f"**Сгенерировано:** {_now()}\n\n"
        "## Установка Chrome Extension\n\n"
        "1. Откройте Chrome → `chrome://extensions/`\n"
        "2. Включите **Режим разработчика** (правый верхний угол)\n"
        "3. Нажмите **«Загрузить распакованное расширение»**\n"
        "4. Выберите папку этого проекта\n"
        "5. Нажмите иконку расширения → откроется боковая панель\n\n"
        "## Возможности\n\n"
        "- 💬 **AI-чат** — потоковые ответы от Ollama\n"
        "- 📸 **Скриншот** — захват + AI описание текущей страницы\n"
        "- 🔍 **Текст страницы** — извлечение и анализ контента\n"
        "- 🖼 **Описание изображений** — vision-анализ через Ollama\n"
        "- 📋 **HTML структура** — полный HTML для анализа\n"
        "- 💾 **История чата** — сохраняется в chrome.storage.local\n\n"
        "## Требования\n\n"
        "Запустите **drgr-bot VM** (он автоматически запускает CORS-релей на порту "
        f"{_OLLAMA_RELAY_PORT}):\n"
        "```\n"
        "python vm/server.py\n"
        "```\n\n"
        "Ollama должна быть запущена: `ollama serve`\n\n"
        "Рекомендуемые модели:\n"
        "- `ollama pull gemma3:4b` — чат\n"
        "- `ollama pull llava:7b` — анализ изображений\n"
        "- `ollama pull qwen2.5:3b` — код\n\n"
        "## Архитектура (CORS relay)\n\n"
        "Расширение общается с Ollama через фоновый скрипт (background.js),\n"
        "который подключается к CORS-релею на `http://127.0.0.1:"
        f"{_OLLAMA_RELAY_PORT}` — он запускается автоматически вместе с VM-сервером.\n"
        "Это позволяет стримить токены прямо в боковой панели без ошибок CORS.\n\n"
        "## Использование с другого устройства (LAN)\n\n"
        "Если вы используете расширение на устройстве, отличном от сервера drgr-bot:\n\n"
        "1. Найдите IP-адрес сервера (например `192.168.1.100`)\n"
        f"2. В расширении откройте настройки и укажите URL релея:\n"
        f"   `http://192.168.1.100:{_OLLAMA_RELAY_PORT}/api/chat`\n"
        "3. Или выполните в консоли расширения (chrome://extensions → Service Worker):\n"
        "   ```js\n"
        f"   chrome.storage.local.set({{ollamaRelayUrl: 'http://192.168.1.100:{_OLLAMA_RELAY_PORT}/api/chat'}})\n"
        "   ```\n\n"
        "CORS-релей drgr-bot VM теперь слушает на `0.0.0.0` — доступен с любого устройства в сети.\n\n"
        "## Файлы\n\n"
        + "\n".join(f"- `{f}`" for f in files.keys() if f != "README.md")
        + "\n"
    )

    return files

@app.route("/project/generate", methods=["POST"])
def project_generate():
    """Generate a complete web project from a task description using Ollama or LM Studio.

    Body: {"model": "...", "prompt": "...", "name": "optional project name"}
    Returns: {"project_id": "...", "files": {"index.html": "...", ...}, "success": true}

    Detects Chrome extension requests and generates a full multi-file extension
    (manifest.json, sidepanel.html, sidepanel.js, background.js, content.js, README.md).
    Supports models with "lmstudio:" prefix routed to LM Studio OpenAI-compatible API.
    """
    body    = request.get_json(silent=True) or {}
    model   = body.get("model", "").strip()
    prompt  = body.get("prompt", "").strip()
    name    = body.get("name", "").strip() or prompt[:60]

    if not model:
        return jsonify({"error": "No model selected", "success": False})
    if not prompt:
        return jsonify({"error": "No prompt provided", "success": False})

    is_lms = model.startswith(_LM_STUDIO_PREFIX)

    try:
        # Chrome extension: generate multi-file project
        if _is_chrome_extension_request(prompt):
            files = _generate_chrome_extension_files(model, prompt, name)
            if not files:
                return jsonify({"error": "Model returned no extension files", "success": False})
        else:
            sys_prompt = (
                "You are an expert full-stack web developer. "
                "Generate a COMPLETE, FULLY FUNCTIONAL, production-ready web application "
                "for the task described below. "
                "ABSOLUTE RULES — VIOLATIONS ARE UNACCEPTABLE:\n"
                "1. NEVER write demo versions, stubs, placeholders, or incomplete code.\n"
                "2. NEVER use '// TODO', '// add code here', '/* implement */', "
                "'В реальном приложении здесь...', 'This is a demo', 'placeholder'.\n"
                "3. Every function must have a REAL, WORKING implementation.\n"
                "The application MUST be a single HTML file with all CSS and JavaScript inline. "
                "Use a dark, modern design with CSS variables, responsive layout (flexbox/grid), "
                "and smooth animations. Include ALL functionality described in the task. "
                "Return ONLY the complete HTML document inside a fenced ```html code block. "
                "Do not write anything outside that block.\n\n"
                f"Task: {prompt}"
            )

            if is_lms:
                # Route to LM Studio OpenAI-compatible API
                real_model = model[len(_LM_STUDIO_PREFIX):]
                lms_url    = _resolve_lms_url()
                if not lms_url:
                    return jsonify({"error": "LM Studio URL не настроен — укажите URL в настройках (☰)", "success": False})
                resp = _http.post(
                    f"{lms_url}/v1/chat/completions",
                    json={
                        "model": real_model,
                        "messages": [
                            {"role": "system", "content": "You are an expert full-stack web developer. Generate only complete, fully functional code."},
                            {"role": "user",   "content": sys_prompt},
                        ],
                        "stream": False,
                    },
                    timeout=_LMS_TIMEOUT,
                )
                resp.raise_for_status()
                raw = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            elif model.startswith(_TGWUI_PREFIX):
                # Route to text-generation-webui OpenAI-compatible API
                real_model = model[len(_TGWUI_PREFIX):]
                tw_url     = TGWUI_BASE
                if not tw_url:
                    return jsonify({"error": "text-generation-webui URL не настроен — укажите URL в настройках (☰)", "success": False})
                resp = _http.post(
                    f"{tw_url}/v1/chat/completions",
                    json={
                        "model": real_model,
                        "messages": [
                            {"role": "system", "content": "You are an expert full-stack web developer. Generate only complete, fully functional code."},
                            {"role": "user",   "content": sys_prompt},
                        ],
                        "stream": False,
                    },
                    timeout=_LMS_TIMEOUT,
                )
                resp.raise_for_status()
                raw = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            else:
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
        # Also log to VM memory/training data
        threading.Thread(
            target=_record_agent_action,
            args=({
                "timestamp":   _now(),
                "action_type": "project_generate",
                "input":       {"name": name, "prompt": prompt, "model": model},
                "output":      {"project_id": project_id, "files": list(files.keys())},
                "success":     True,
                "duration_ms": 0,
                "metadata":    {},
            },),
            daemon=True,
        ).start()

        return jsonify({
            "project_id": project_id,
            "name": name,
            "files": {k: v for k, v in files.items()},
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


@app.route("/project/zip/<project_id>", methods=["GET"])
def project_zip(project_id: str):
    """Return all project files as a ZIP archive for download.

    Useful for downloading Chrome extensions ready for installation.
    """
    import io
    import zipfile

    if not re.match(r'^[a-z0-9_-]+$', project_id):
        return jsonify({"error": "Invalid project ID"}), 400
    project_dir = os.path.join(PROJECTS_DIR, project_id)
    if not os.path.isdir(project_dir):
        return jsonify({"error": "Project not found"}), 404

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in os.scandir(project_dir):
            if entry.is_file() and entry.name != "project.json":
                zf.write(entry.path, entry.name)
    buf.seek(0)

    return Response(
        buf.read(),
        mimetype="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{project_id}.zip"'},
    )


@app.route("/project/<project_id>/<path:filename>", methods=["GET"])
def project_file(project_id: str, filename: str):
    """Serve a file from a saved project directory."""
    # Sanitise: only allow lowercase alphanumeric characters, underscores and hyphens
    if not re.match(r'^[a-z0-9_-]+$', project_id):
        return jsonify({"error": "Invalid project ID. Only lowercase letters, digits, underscores and hyphens are allowed."}), 400
    project_dir = os.path.join(PROJECTS_DIR, project_id)
    if not os.path.isdir(project_dir):
        return jsonify({"error": "Project not found"}), 404
    # send_from_directory handles path traversal protection
    return send_from_directory(project_dir, filename)


@app.route("/project/save", methods=["POST"])
def project_save():
    """Save the current editor content as a named project file on disk.

    Body: {"content": "...", "filename": "index.html", "name": "My Project",
           "description": "optional description"}
    Returns: {"project_id": "...", "path": "...", "success": true}
    """
    body        = request.get_json(silent=True) or {}
    content     = body.get("content", "")
    filename    = body.get("filename", "index.html").strip()
    name        = body.get("name", "").strip() or filename
    description = body.get("description", "").strip()

    if not content:
        return jsonify({"error": "No content provided", "success": False}), 400

    # Sanitise filename — strip any path separators, keep only safe characters
    filename = os.path.basename(filename)
    # Allow word chars, hyphens, spaces, single dots; reject anything else
    filename = re.sub(r'[^\w\-. ]', '_', filename)
    # Collapse multiple dots to prevent issues like 'foo..html'
    filename = re.sub(r'\.{2,}', '.', filename).strip() or "project.html"

    slug = _slugify(name) or "project"
    project_id = f"{slug}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    files = {filename: content}
    _save_project(project_id, name, description or name, files)

    # Log to VM training data / memory so the VM "remembers" this project
    threading.Thread(
        target=_record_agent_action,
        args=({
            "timestamp":   _now(),
            "action_type": "project_save",
            "input":       {"name": name, "filename": filename, "description": description or name},
            "output":      {"project_id": project_id, "size": len(content)},
            "success":     True,
            "duration_ms": 0,
            "metadata":    {"content_preview": content[:200]},
        },),
        daemon=True,
    ).start()

    return jsonify({
        "project_id": project_id,
        "name":       name,
        "filename":   filename,
        "path":       os.path.join(PROJECTS_DIR, project_id, filename),
        "success":    True,
    })


@app.route("/project/delete/<project_id>", methods=["DELETE"])
def project_delete(project_id: str):
    """Delete a saved project directory."""
    if not re.match(r'^[a-z0-9_-]+$', project_id):
        return jsonify({"error": "Invalid project ID"}), 400
    project_dir = os.path.join(PROJECTS_DIR, project_id)
    if not os.path.isdir(project_dir):
        return jsonify({"error": "Project not found"}), 404
    shutil.rmtree(project_dir, ignore_errors=True)
    return jsonify({"success": True})


@app.route("/project/path", methods=["GET"])
def project_path():
    """Return the absolute path of the projects directory on disk.

    Ensures the directory exists (creates it if missing) before returning its path.
    """
    _ensure_projects_dir()
    return jsonify({"path": os.path.abspath(PROJECTS_DIR), "success": True})


# ---------------------------------------------------------------------------
# File upload — upload a file from the user's PC into the editor
# ---------------------------------------------------------------------------

# Allowed text file extensions for upload
_UPLOAD_ALLOWED_EXT = {
    ".py", ".js", ".ts", ".html", ".css", ".json", ".xml", ".yaml", ".yml",
    ".md", ".markdown", ".txt", ".csv", ".sql", ".sh", ".bash", ".ps1",
    ".java", ".kt", ".go", ".rs", ".cpp", ".c", ".h", ".cs", ".php",
    ".rb", ".r", ".swift", ".dockerfile", ".toml", ".ini", ".env",
}

# Image/binary extensions — stored in projects/uploads/, returned as data URL
_UPLOAD_IMAGE_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico",
    ".tiff", ".tif", ".avif",
}

# All other binary file types accepted (PDF, Office, archives, etc.)
_UPLOAD_BINARY_EXT = {
    ".pdf", ".zip", ".tar", ".gz", ".7z", ".rar",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".mp3", ".mp4", ".wav", ".ogg", ".webm", ".avi",
}

_UPLOAD_MEDIA_DIR = os.path.join(_DIR, "projects", "uploads")


def _ensure_upload_dir() -> None:
    os.makedirs(_UPLOAD_MEDIA_DIR, exist_ok=True)


def _html_escape(s: str) -> str:
    """Minimal HTML escaping to prevent XSS when inserting filenames into HTML tags."""
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;")
             .replace("'", "&#x27;"))


def _save_upload_file(data: bytes, safe_name: str) -> tuple:
    """Save binary data to the uploads directory; return (stored_name, file_url)."""
    _ensure_upload_dir()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    # Use secure_filename again to ensure no path separators in safe_name
    from werkzeug.utils import secure_filename as _sf
    safe_base = _sf(safe_name) or "file.bin"
    stored_name = f"{ts}_{safe_base}"
    # Final safety check — ensure no directory traversal
    stored_name = os.path.basename(stored_name)
    stored_path = os.path.join(_UPLOAD_MEDIA_DIR, stored_name)
    with open(stored_path, "wb") as fh:
        fh.write(data)
    return stored_name, f"/files/media/{stored_name}"


@app.route("/files/upload", methods=["POST"])
def files_upload():
    """Accept a file uploaded from the user's PC.

    Text files: returns their text content so the editor can show them.
    Image files: saves to projects/uploads/, returns base64 data URL + HTML img tag.
    Binary files: saves to projects/uploads/, returns file URL.

    Accepts multipart/form-data with a 'file' field.
    Returns: {content, filename, language, size, success, is_image, data_url, file_url}
    """
    import base64 as _base64
    from werkzeug.utils import secure_filename as _secure_filename

    uploaded = request.files.get("file")
    if not uploaded:
        return jsonify({"error": "No file provided", "success": False}), 400

    original_name = uploaded.filename or "file.bin"
    safe_name = _secure_filename(original_name) or "file.bin"
    _, ext = os.path.splitext(safe_name.lower())
    escaped_name = _html_escape(safe_name)

    # ── Image file ──────────────────────────────────────────────────────────
    if ext in _UPLOAD_IMAGE_EXT:
        data = uploaded.read(10 * 1024 * 1024)  # 10 MB limit for images
        stored_name, file_url = _save_upload_file(data, safe_name)

        mime_map = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
            ".svg": "image/svg+xml", ".ico": "image/x-icon",
            ".tiff": "image/tiff", ".tif": "image/tiff", ".avif": "image/avif",
        }
        mime = mime_map.get(ext, "image/png")
        b64 = _base64.b64encode(data).decode("ascii")
        data_url = f"data:{mime};base64,{b64}"
        html_tag = f'<img src="{file_url}" alt="{escaped_name}" style="max-width:100%">'
        return jsonify({
            "content":   html_tag,
            "filename":  safe_name,
            "language":  "html",
            "size":      len(data),
            "success":   True,
            "is_image":  True,
            "data_url":  data_url,
            "file_url":  file_url,
        })

    # ── Binary (non-image) file ─────────────────────────────────────────────
    if ext in _UPLOAD_BINARY_EXT:
        data = uploaded.read(50 * 1024 * 1024)  # 50 MB limit
        stored_name, file_url = _save_upload_file(data, safe_name)
        html_tag = f'<a href="{file_url}" target="_blank">{escaped_name}</a>'
        return jsonify({
            "content":  html_tag,
            "filename": safe_name,
            "language": "html",
            "size":     len(data),
            "success":  True,
            "is_image": False,
            "file_url": file_url,
        })

    # ── Text file ───────────────────────────────────────────────────────────
    # Read content (limit to 1 MB for text)
    data = uploaded.read(1024 * 1024)
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            content = data.decode("cp1251")
        except UnicodeDecodeError:
            # Treat undecodable content as binary — save to uploads
            stored_name, file_url = _save_upload_file(data, safe_name)
            return jsonify({
                "content":  f'<a href="{file_url}" target="_blank">{escaped_name}</a>',
                "filename": safe_name,
                "language": "html",
                "size":     len(data),
                "success":  True,
                "is_image": False,
                "file_url": file_url,
            })

    # Guess language from extension
    _ext_to_lang = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".html": "html", ".htm": "html", ".css": "css",
        ".json": "json", ".xml": "xml", ".yaml": "yaml", ".yml": "yaml",
        ".md": "markdown", ".markdown": "markdown",
        ".txt": "plaintext", ".csv": "plaintext", ".sql": "sql",
        ".sh": "shell", ".bash": "bash", ".ps1": "powershell",
        ".java": "java", ".kt": "kotlin", ".go": "go", ".rs": "rust",
        ".cpp": "cpp", ".c": "c", ".h": "c", ".cs": "csharp",
        ".php": "php", ".rb": "ruby", ".r": "r", ".swift": "swift",
        ".dockerfile": "dockerfile", ".toml": "plaintext", ".ini": "plaintext",
    }
    lang = _ext_to_lang.get(ext, "plaintext")

    return jsonify({
        "content":  content,
        "filename": safe_name,
        "language": lang,
        "size":     len(data),
        "success":  True,
        "is_image": False,
    })


@app.route("/files/media/<path:filename>", methods=["GET"])
def files_media(filename: str):
    """Serve a previously uploaded media/binary file from projects/uploads/."""
    from werkzeug.utils import secure_filename as _secure_filename
    # Sanitise — use secure_filename + os.path.basename to prevent path traversal
    safe = os.path.basename(_secure_filename(filename))
    if not safe or safe.startswith('.'):
        return jsonify({"error": "Invalid filename"}), 400
    _ensure_upload_dir()
    return send_from_directory(_UPLOAD_MEDIA_DIR, safe)


# ---------------------------------------------------------------------------
# Web search — search the web via DuckDuckGo Lite HTML (no API key needed)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Web search — search the web via DuckDuckGo Lite HTML (no API key needed)
# ---------------------------------------------------------------------------

@app.route("/browse/page", methods=["POST"])
def browse_page():
    """Fetch the text content of a web page (no screenshot, no vision AI).

    Useful for the autonomous agent to read page text quickly.

    Body: {"url": "https://example.com", "max_chars": 3000}
    Returns: {text: "...", title: "...", url: "...", success: true}
    """
    body     = request.get_json(silent=True) or {}
    url      = body.get("url", "").strip()
    max_chars = int(body.get("max_chars", 3000))

    if not url:
        return jsonify({"error": "Provide url", "success": False}), 400
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # SSRF guard
    safe_url = ""
    try:
        import ipaddress as _ipaddress_bp
        parsed   = urllib.parse.urlparse(url)
        hostname = parsed.hostname or ""
        _BLOCKED = {"localhost", "0.0.0.0", "::1", "ip6-localhost", "ip6-loopback"}
        if hostname in _BLOCKED:
            return jsonify({"error": "Requests to internal addresses are not allowed", "success": False}), 400
        try:
            addr = _ipaddress_bp.ip_address(hostname)
            if addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local:
                return jsonify({"error": "Requests to private/reserved IPs are not allowed", "success": False}), 400
        except ValueError:
            pass
        safe_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query, ""))
    except Exception as ssrf_exc:
        return jsonify({"error": f"URL validation failed: {ssrf_exc}", "success": False}), 400
    if not safe_url:
        return jsonify({"error": "Could not construct safe URL", "success": False}), 400

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0 Safari/537.36",
            "Accept-Language": "ru,en;q=0.9",
        }
        # Read at most ~300 KB to avoid memory issues with large pages
        _MAX_HTML = 300_000
        r = _http.get(safe_url, headers=headers, timeout=15, stream=True)
        r.raise_for_status()
        content_type = r.headers.get("Content-Type", "")
        if "text" not in content_type and "html" not in content_type:
            return jsonify({"error": f"Not a text page: {content_type}", "success": False}), 400

        chunks = []
        total  = 0
        for chunk in r.iter_content(chunk_size=8192, decode_unicode=True):
            if isinstance(chunk, bytes):
                chunk = chunk.decode("utf-8", errors="replace")
            chunks.append(chunk)
            total += len(chunk)
            if total >= _MAX_HTML:
                break
        raw_html = "".join(chunks)[:_MAX_HTML]

        # Extract title
        title = ""
        title_match = re.search(r"<title[^>]*>([^<]{1,200})</title>", raw_html, re.IGNORECASE)
        if title_match:
            title = re.sub(r"\s+", " ", title_match.group(1)).strip()

        # Strip HTML tags to get text
        text = re.sub(r"<style[^>]*>.*?</style[^>]*>", " ", raw_html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<script[^>]*>.*?</script[^>]*>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"&lt;", "<", text)
        text = re.sub(r"&gt;", ">", text)
        text = re.sub(r"&quot;", '"', text)
        text = re.sub(r"&#\d+;", "", text)
        text = re.sub(r"\s{2,}", " ", text).strip()

        _record_agent_action({
            "timestamp":   _now(),
            "action_type": "browse_page",
            "input":       {"url": safe_url},
            "output":      {"text_length": len(text), "title": title},
            "success":     True,
            "duration_ms": 0,
            "metadata":    {},
        })

        return jsonify({
            "text":    text[:max_chars],
            "title":   title,
            "url":     safe_url,
            "success": True,
        })

    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"error": str(exc), "success": False}), 500


@app.route("/browse/proxy", methods=["GET"])
def browse_proxy():
    """Proxy web pages for interactive browsing inside the ВИЗОР iframe.

    Fetches the target URL server-side, rewrites all anchor/form URLs to route
    back through this proxy, and returns the page HTML without X-Frame-Options
    or Content-Security-Policy restrictions so modern sites render in the iframe.

    Query string: ?url=https://example.com
    Returns: text/html (the proxied, URL-rewritten page)
    """
    raw_url = request.args.get("url", "").strip()
    if not raw_url:
        return "<html><body style='font-family:sans-serif;color:#fff;background:#1a1a1a;padding:20px'><h3>⚠ Не указан URL</h3><p>Передайте параметр ?url=https://example.com</p></body></html>", 400
    if not raw_url.startswith(("http://", "https://")):
        raw_url = "https://" + raw_url

    # ── SSRF guard — block internal/private addresses ─────────────────────────
    safe_url = ""
    try:
        import ipaddress as _ipa_prx
        parsed = urllib.parse.urlparse(raw_url)
        hostname = parsed.hostname or ""
        _BLOCKED = {"localhost", "0.0.0.0", "::1", "ip6-localhost", "ip6-loopback"}
        if hostname in _BLOCKED:
            return "<html><body style='font-family:sans-serif;color:#fff;background:#1a1a1a;padding:20px'><h3>⛔ Запрещено</h3><p>Запросы на внутренние адреса не разрешены.</p></body></html>", 403
        try:
            addr = _ipa_prx.ip_address(hostname)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                return "<html><body style='font-family:sans-serif;color:#fff;background:#1a1a1a;padding:20px'><h3>⛔ Запрещено</h3><p>Запросы на приватные/зарезервированные IP не разрешены.</p></body></html>", 403
        except ValueError:
            pass
        safe_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query, ""))
    except Exception as ssrf_exc:
        return f"<html><body><p>URL error: {ssrf_exc}</p></body></html>", 400
    if not safe_url:
        return "<html><body><p>Could not construct safe URL</p></body></html>", 400

    try:
        hdrs = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru,en;q=0.9",
        }
        r = _http.get(safe_url, headers=hdrs, timeout=15, allow_redirects=True, stream=True)

        # After redirects the final URL is used as the base for relative links
        base_url = r.url or safe_url
        content_type = r.headers.get("Content-Type", "text/html")

        # Non-HTML resources (images, fonts, CSS, JS, etc.) — pass through transparently
        if "text/html" not in content_type:
            content = r.content
            resp_headers = {"Content-Type": content_type}
            # Strip framing-restriction headers for everything that flows through us
            return content, r.status_code, resp_headers

        # Read HTML (cap at 500 KB to stay responsive)
        _MAX_HTML_PRX = 500_000
        chunks = []
        total = 0
        for chunk in r.iter_content(chunk_size=8192, decode_unicode=True):
            if isinstance(chunk, bytes):
                chunk = chunk.decode("utf-8", errors="replace")
            chunks.append(chunk)
            total += len(chunk)
            if total >= _MAX_HTML_PRX:
                break
        html = "".join(chunks)

        # ── Rewrite links so all navigation stays inside the proxy ─────────────
        def _proxy_href(href: str) -> str:
            """Return a /browse/proxy?url=... link for the given href."""
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
                return href
            try:
                abs_url = urllib.parse.urljoin(base_url, href)
                parts = urllib.parse.urlparse(abs_url)
                if parts.scheme not in ("http", "https"):
                    return href
                return "/browse/proxy?url=" + urllib.parse.quote(abs_url, safe="")
            except Exception:
                return href

        def _rewrite_href(m: "re.Match") -> str:
            q, val = m.group(1), m.group(2)
            return f'href={q}{_proxy_href(val)}{q}'

        def _rewrite_action(m: "re.Match") -> str:
            q, val = m.group(1), m.group(2)
            return f'action={q}{_proxy_href(val)}{q}'

        def _resolve_src(m: "re.Match") -> str:
            attr, q, val = m.group(1), m.group(2), m.group(3)
            if val.startswith(("data:", "blob:")):
                return m.group(0)
            try:
                abs_url = urllib.parse.urljoin(base_url, val)
                parts = urllib.parse.urlparse(abs_url)
                if parts.scheme not in ("http", "https"):
                    return m.group(0)
                # Route external scripts and stylesheets through the proxy to avoid
                # CORS issues caused by the null-origin sandbox on the iframe
                return f'{attr}={q}/browse/proxy?url={urllib.parse.quote(abs_url, safe="")}{q}'
            except Exception:
                return m.group(0)

        # Rewrite <a href> and <form action> to go through proxy
        html = re.sub(
            r'''href\s*=\s*(["'])((?!#|javascript:|mailto:|tel:|data:)[^"']+)\1''',
            _rewrite_href,
            html,
            flags=re.IGNORECASE,
        )
        html = re.sub(
            r'''action\s*=\s*(["'])([^"']+)\1''',
            _rewrite_action,
            html,
            flags=re.IGNORECASE,
        )
        # Route all src= resources (scripts, images, iframes) through the proxy.
        # This avoids CORS failures that occur because the sandboxed iframe has a
        # null origin — external servers reject null-origin fetch/XHR requests.
        html = re.sub(
            r'''(src)\s*=\s*(["'])([^"']+)\2''',
            _resolve_src,
            html,
            flags=re.IGNORECASE,
        )

        # Inject <base> + tiny script that updates the VM URL bar on the parent
        js_url = json.dumps(base_url)  # properly escapes all JS-special chars incl. \n, \r, U+2028
        inject = (
            f'<base href="{base_url}">'
            f"<script>"
            f"try{{window.top.document.getElementById('vurl-input').value={js_url}}}catch(e){{}}"
            f"</script>"
        )
        # Insert right after <head> (or prepend if no head tag)
        html_patched = re.sub(r"(<head[^>]*>)", r"\1\n" + inject, html, count=1, flags=re.IGNORECASE)
        if html_patched == html:
            html_patched = inject + html

        return html_patched, 200, {"Content-Type": "text/html; charset=utf-8"}

    except Exception as exc:  # pylint: disable=broad-except
        _log.warning("browse_proxy error for %s: %s", safe_url, exc)
        return (
            f"<html><body style='font-family:sans-serif;color:#fff;background:#1a1a1a;padding:20px'>"
            f"<h3>⚠ Ошибка загрузки страницы</h3>"
            f"<p>{safe_url}</p><pre style='color:#f88'>{exc}</pre>"
            f"<p><a href='/browse/proxy?url={urllib.parse.quote(safe_url, safe='')}' "
            f"style='color:#4af'>Повторить</a></p>"
            f"</body></html>",
            500,
            {"Content-Type": "text/html; charset=utf-8"},
        )


# ---------------------------------------------------------------------------
# Research endpoint — multi-source search + screenshots + HTML article
# ---------------------------------------------------------------------------

def _research_html_escape(text: str) -> str:
    """Minimal HTML escaper (avoids importing html at module level)."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _research_build_html(title: str, body_text: str, sources: list, screenshot_uris: list, yt_video_id: str = "") -> str:
    """Build a self-contained professional HTML research article with Bootstrap 5 CDN, gallery, Chart.js, video, and action buttons."""
    import random as _rnd_html
    esc = _research_html_escape

    # ── Bootstrap 5 CDN (no install required) ────────────────────────────
    _BS_CDN = (
        '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" '
        'integrity="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH" crossorigin="anonymous"/>\n'
        '<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js" '
        'integrity="sha384-YvpcrYf0tY3lHB60NNkmXc4s9bIOgUxi8T/jzmCl6jc9LXJGU/d2h+lrEMGMIjY" crossorigin="anonymous"></script>\n'
    )
    # Randomise accent theme so each article looks unique
    _THEMES = [
        # (accent_hex, accent2_hex, bg_class, header_bg_class)
        ("#0d6efd", "#198754", "bg-light", "bg-primary"),      # Bootstrap blue
        ("#6610f2", "#0dcaf0", "bg-light", "bg-purple"),       # purple+cyan
        ("#dc3545", "#fd7e14", "bg-light", "bg-danger"),       # red+orange
        ("#20c997", "#0d6efd", "bg-white", "bg-success"),      # teal+blue
        ("#ffc107", "#6610f2", "bg-light", "bg-warning"),      # yellow+purple
        ("#0dcaf0", "#198754", "bg-light", "bg-info"),         # cyan+green
    ]
    _theme = _rnd_html.choice(_THEMES)
    _accent, _accent2 = _theme[0], _theme[1]

    # ── Layout variant (diversifies article structure each generation) ────
    _LAYOUT_STYLES = ["hero", "magazine", "timeline", "cards", "default"]
    _layout_style = _rnd_html.choice(_LAYOUT_STYLES)

    # Inline images use lock values above this offset to ensure they differ from gallery images
    _INLINE_IMG_LOCK_OFFSET = 100000

    # ── Topic-relevant fallback images – ensure 5–7 visuals per article ──
    # Extract Latin keywords from title for loremflickr topic-image search
    _img_kws_raw = re.sub(r'[^a-zA-Z0-9 ]', ' ', title).split()
    _img_latin = [k.lower() for k in _img_kws_raw if re.match(r'^[a-zA-Z]{3,}$', k)][:4]
    if not _img_latin:
        _img_latin = ["technology", "science"]
    _img_kw_joined = ','.join(_img_latin[:3])
    _img_kw_enc = urllib.parse.quote_plus(_img_kw_joined)
    _all_img_uris = list(screenshot_uris)
    _target_img_count = _rnd_html.randint(5, 7)
    for _fi in range(max(0, _target_img_count - len(_all_img_uris))):
        _lock_val = (abs(hash(title + str(_fi))) % 99997) + 1
        _all_img_uris.append(
            f"https://loremflickr.com/800/500/{_img_kw_enc}?lock={_lock_val}"
        )

    # ── Reading-time / stats ──────────────────────────────────────────────
    word_count = len(body_text.split())
    reading_min = max(1, word_count // 200)
    h2_headings = [line[3:].strip() for line in body_text.splitlines() if line.startswith("## ")]
    stats_html = (
        '<div class="article-stats">\n'
        f'<span>⏱ Время чтения: <strong>~{reading_min} мин</strong></span>\n'
        f'<span>📝 Слов: <strong>{word_count}</strong></span>\n'
        f'<span>📚 Источников: <strong>{len(sources)}</strong></span>\n'
        f'<span>📸 Иллюстраций: <strong>{len(_all_img_uris)}</strong></span>\n'
        '</div>\n'
    )

    # ── Table of contents ─────────────────────────────────────────────────
    toc_html = ""
    if h2_headings:
        toc_items = "".join(
            f'<li><a href="#section-{i}">{esc(h)}</a></li>\n'
            for i, h in enumerate(h2_headings)
        )
        toc_html = (
            '<nav class="toc">\n'
            '<h3>📋 Содержание</h3>\n'
            f'<ol>{toc_items}</ol>\n'
            '</nav>\n'
        )

    # ── Hero / featured image (first image, layout-dependent) ────────────
    _hero_uri = _all_img_uris[0] if _all_img_uris else ""
    _hero_alt = esc(title)
    hero_html = ""
    if _hero_uri and _layout_style in ("hero", "magazine"):
        hero_html = (
            f'<div class="hero-img-wrap">\n'
            f'  <img src="{_hero_uri}" alt="{_hero_alt}" class="hero-img" loading="eager"/>\n'
            f'</div>\n'
        )

    # ── Photo gallery (uses all images including loremflickr fallbacks) ───
    gallery_items = ""
    # Skip the hero image (index 0) for hero/magazine layouts to avoid duplicate
    _gallery_start = 1 if (_hero_uri and _layout_style in ("hero", "magazine")) else 0
    for i, uri in enumerate(_all_img_uris[_gallery_start:], start=_gallery_start):
        src = sources[i] if i < len(sources) else {}
        src_title = esc(src.get("title", f"Иллюстрация {i + 1}"))
        _src_real_url = src.get("url", "")
        src_url = esc(_src_real_url)
        # Fallback images link to source if available, or just the image
        link_href = src_url if _src_real_url else uri
        gallery_items += (
            f'<figure class="gallery-item">'
            f'<a href="{link_href}" target="_blank" rel="noopener">'
            f'<img src="{uri}" alt="{src_title}" loading="lazy"/>'
            f'</a>'
            f'<figcaption>'
            + (f'<a href="{src_url}" target="_blank" rel="noopener">🔗 {src_title}</a>'
               if _src_real_url else f'📷 {src_title}')
            + f'</figcaption>'
            f'</figure>\n'
        )
    gallery_html = ""
    if gallery_items:
        gallery_html = (
            '<section class="gallery">\n'
            "<h2>📸 Галерея материалов</h2>\n"
            '<div class="gallery-grid">\n'
            f"{gallery_items}"
            "</div></section>\n"
        )
    elif sources:
        # No images at all (very rare) — show source cards with snippet preview
        _card_icons = ["🌐", "📖", "💬", "📰", "🔗", "📡", "🗞️", "📝"]
        _cards = ""
        for _ci, _src in enumerate(sources[:6]):
            _ci_icon = _card_icons[_ci % len(_card_icons)]
            _ct = esc(_src.get("title", "Источник"))
            _cu = esc(_src.get("url", "#"))
            _cs = esc(_src.get("snippet", "")[:200])
            _cards += (
                f'<figure class="gallery-item src-card">'
                f'<div class="src-card-head">{_ci_icon}</div>'
                f'<figcaption>'
                f'<a href="{_cu}" target="_blank" rel="noopener"><strong>{_ct}</strong></a>'
                f'{"<p>" + _cs + "…</p>" if _cs else ""}'
                f'</figcaption>'
                f'</figure>\n'
            )
        gallery_html = (
            '<section class="gallery">\n'
            "<h2>🔗 Материалы по теме</h2>\n"
            '<div class="gallery-grid">\n'
            f"{_cards}"
            "</div></section>\n"
        )

    # ── Article sections (Markdown → HTML) ───────────────────────────────
    def _inline_md(raw: str) -> str:
        """Convert inline Markdown (bold, italic, inline code, links) to HTML.

        Escapes HTML entities first, then applies safe pattern substitutions.
        """
        # Escape HTML special chars
        s = raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        # Bold: **text** or __text__
        s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
        s = re.sub(r'__(.+?)__', r'<strong>\1</strong>', s)
        # Italic: *text* or _text_ (only single * or _, not touching already-processed **)
        s = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<em>\1</em>', s)
        s = re.sub(r'(?<!_)_(?!_)(.+?)(?<!_)_(?!_)', r'<em>\1</em>', s)
        # Inline code: `code`
        s = re.sub(r'`([^`]+)`', r'<code>\1</code>', s)
        # Markdown links: [text](url)
        s = re.sub(r'\[([^\]]+)\]\((https?://[^\)]+)\)',
                   r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
        return s

    sections_html = ""
    lines = body_text.strip().splitlines()
    # Section icons for h2 headings
    _section_icons = ["📌", "🔍", "💡", "📊", "🏆", "⚙️", "🌐", "📝", "🔬", "✅"]
    _sec_idx = 0
    current_para: list = []
    _in_code_block = False

    def _flush_para(paras: list) -> str:
        if not paras:
            return ""
        text = " ".join(paras).strip()
        if not text:
            return ""
        return "<p>" + _inline_md(text) + "</p>\n"

    for line in (lines[1:] if len(lines) > 1 else lines):
        # Fenced code blocks (``` or ~~~)
        if line.strip().startswith("```") or line.strip().startswith("~~~"):
            sections_html += _flush_para(current_para)
            current_para = []
            _in_code_block = not _in_code_block
            continue
        if _in_code_block:
            # Render code block lines as-is (escaped)
            sections_html += f'<code class="code-line">{esc(line)}</code><br>\n'
            continue
        if line.startswith("#### "):
            sections_html += _flush_para(current_para)
            current_para = []
            sections_html += f'<h4>{_inline_md(line[5:].strip())}</h4>\n'
        elif line.startswith("### "):
            sections_html += _flush_para(current_para)
            current_para = []
            sections_html += f'<h3>{_inline_md(line[4:].strip())}</h3>\n'
        elif line.startswith("## "):
            sections_html += _flush_para(current_para)
            current_para = []
            icon = _section_icons[_sec_idx % len(_section_icons)]
            anchor_id = f"section-{_sec_idx}"
            # Interleave images: inject an inline image every 2nd h2 heading
            # Use unique lock values (offset by 100000) so inline images differ from gallery
            if _all_img_uris and _sec_idx > 0 and _sec_idx % 2 == 0:
                _lock_inline = (abs(hash(title + "inline" + str(_sec_idx))) % 99997) + _INLINE_IMG_LOCK_OFFSET + 1
                _iuri = f"https://loremflickr.com/800/500/{_img_kw_enc}?lock={_lock_inline}"
                _ifloat = "inline-img-right" if _sec_idx % 4 == 0 else "inline-img-left"
                sections_html += (
                    f'<figure class="inline-img {_ifloat}">'
                    f'<img src="{_iuri}" alt="{icon} {esc(line[3:60].strip())}" loading="lazy"/>'
                    f'</figure>\n'
                )
            _sec_idx += 1
            sections_html += f'<h2 id="{anchor_id}">{icon} {_inline_md(line[3:].strip())}</h2>\n'
        elif line.startswith("# "):
            sections_html += _flush_para(current_para)
            current_para = []
            sections_html += f"<h2>{_inline_md(line[2:].strip())}</h2>\n"
        elif line.strip().startswith("- ") or line.strip().startswith("* "):
            sections_html += _flush_para(current_para)
            current_para = []
            sections_html += f'<li>{_inline_md(line.strip()[2:].strip())}</li>\n'
        elif re.match(r'^\d+\.\s+', line.strip()):
            # Numbered list item: "1. text" (requires at least one space after period)
            sections_html += _flush_para(current_para)
            current_para = []
            item_text = re.sub(r'^\d+\.\s+', '', line.strip())
            sections_html += f'<li class="ol-item">{_inline_md(item_text)}</li>\n'
        elif line.strip():
            current_para.append(line.strip())
        else:
            sections_html += _flush_para(current_para)
            current_para = []
    sections_html += _flush_para(current_para)

    # Wrap consecutive <li> / <li class="ol-item"> items into <ul>/<ol> blocks.
    # Use a simple line-by-line pass to avoid catastrophic backtracking in regex.
    _wrapped_lines: list = []
    _ul_buf: list = []
    _ol_buf: list = []

    def _flush_ul(buf: list) -> str:
        if not buf:
            return ""
        return '<ul class="art-list">' + "".join(buf) + "</ul>\n"

    def _flush_ol(buf: list) -> str:
        if not buf:
            return ""
        return '<ol class="art-list">' + "".join(buf) + "</ol>\n"

    for _sl in sections_html.splitlines(keepends=True):
        if _sl.startswith('<li class="ol-item">'):
            _wrapped_lines.append(_flush_ul(_ul_buf)); _ul_buf = []
            _ol_buf.append(_sl)
        elif _sl.startswith('<li>'):
            _wrapped_lines.append(_flush_ol(_ol_buf)); _ol_buf = []
            _ul_buf.append(_sl)
        else:
            _wrapped_lines.append(_flush_ul(_ul_buf)); _ul_buf = []
            _wrapped_lines.append(_flush_ol(_ol_buf)); _ol_buf = []
            _wrapped_lines.append(_sl)
    _wrapped_lines.append(_flush_ul(_ul_buf))
    _wrapped_lines.append(_flush_ol(_ol_buf))
    sections_html = "".join(l for l in _wrapped_lines if l)

    # ── Video section (auto-embed if ID found, else interactive widget) ──────
    yt_query = urllib.parse.quote_plus(title[:80])
    yt_search_url = f"https://www.youtube.com/results?search_query={yt_query}"
    if yt_video_id:
        # Auto-embed the found video
        yt_embed_src = f"https://www.youtube.com/embed/{yt_video_id}"
        video_html = (
            '<section class="video-section">\n'
            '<h2>🎬 Видео по теме</h2>\n'
            '<div class="video-embed-wrap">\n'
            f'  <iframe src="{yt_embed_src}" title="YouTube Video" frameborder="0"\n'
            '          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"\n'
            '          allowfullscreen></iframe>\n'
            '</div>\n'
            '<div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">\n'
            f'  <a class="btn-video-search" href="{yt_search_url}" target="_blank" rel="noopener">🔍 Ещё видео на YouTube</a>\n'
            '  <button class="btn-action" onclick="document.getElementById(\'yt-manual\').style.display='
            'document.getElementById(\'yt-manual\').style.display===\'none\'?\'\':\'none\'">✏ Другое видео</button>\n'
            '</div>\n'
            '<div id="yt-manual" style="display:none;margin-top:10px">\n'
            '  <div class="yt-input-row">\n'
            '    <input id="yt-url-input" type="text" placeholder="https://www.youtube.com/watch?v=... или ID видео"\n'
            '           style="flex:1;padding:9px 12px;border:1px solid #ccc;border-radius:8px;font-size:14px"\n'
            '           onkeydown="if(event.key===\'Enter\'){embedYTVideo();}" />\n'
            '    <button class="btn-video" onclick="embedYTVideo()">▶ Смотреть</button>\n'
            '  </div>\n'
            '</div>\n'
            '<script>\n'
            'function embedYTVideo() {\n'
            '  var raw = (document.getElementById("yt-url-input") || {}).value || "";\n'
            '  var val = raw.trim();\n'
            '  if (!val) { alert("Введите ссылку или ID видео YouTube"); return; }\n'
            '  var m = val.match(/(?:[?&]v=|youtu\\.be\\/|embed\\/)([A-Za-z0-9_-]{11})/);\n'
            '  var vid = m ? m[1] : (val.length === 11 && /^[A-Za-z0-9_-]+$/.test(val) ? val : null);\n'
            '  if (!vid) { alert("Не удалось распознать ID видео. Вставьте полную ссылку YouTube."); return; }\n'
            '  var iframe = document.querySelector(".video-embed-wrap iframe");\n'
            '  if (iframe) iframe.src = "https://www.youtube.com/embed/" + vid + "?autoplay=1";\n'
            '  document.getElementById("yt-manual").style.display = "none";\n'
            '}\n'
            '</script>\n'
            '</section>\n'
        )
    else:
        # No video found — show manual paste widget
        # NOTE: YouTube removed the listType=search embed parameter in 2019.
        # We use an interactive widget: user can paste a YouTube URL/ID to embed it,
        # or click the search button to open YouTube in a new tab.
        video_html = (
            '<section class="video-section">\n'
            '<h2>🎬 Видео по теме</h2>\n'
            '<div id="yt-widget">\n'
            '  <div class="yt-placeholder" id="yt-placeholder">\n'
            f'    <p>Вставьте ссылку или ID видео YouTube по теме <strong>{esc(title)}</strong>:</p>\n'
            '    <div class="yt-input-row">\n'
            '      <input id="yt-url-input" type="text" placeholder="https://www.youtube.com/watch?v=... или ID видео"\n'
            '             style="flex:1;padding:9px 12px;border:1px solid #ccc;border-radius:8px;font-size:14px"\n'
            '             onkeydown="if(event.key===\'Enter\'){embedYTVideo();}" />\n'
            '      <button class="btn-video" onclick="embedYTVideo()">▶ Смотреть</button>\n'
            f'      <a class="btn-video-search" href="{yt_search_url}" target="_blank" rel="noopener">🔍 Найти на YouTube</a>\n'
            '    </div>\n'
            '  </div>\n'
            '  <div id="yt-embed-wrap" style="display:none">\n'
            '    <div class="video-embed-wrap">\n'
            '      <iframe id="yt-iframe" src="" title="YouTube Video" frameborder="0" allowfullscreen\n'
            '              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share">\n'
            '      </iframe>\n'
            '    </div>\n'
            '    <div style="margin-top:8px;display:flex;gap:8px">\n'
            '      <button class="btn-action" onclick="document.getElementById(\'yt-embed-wrap\').style.display=\'none\';'
            'document.getElementById(\'yt-placeholder\').style.display=\'\'">⬅ Другое видео</button>\n'
            f'      <a class="btn-video-search" href="{yt_search_url}" target="_blank" rel="noopener">🔍 Поиск на YouTube</a>\n'
            '    </div>\n'
            '  </div>\n'
            '</div>\n'
            '<script>\n'
            'function embedYTVideo() {\n'
            '  var raw = (document.getElementById("yt-url-input") || {}).value || "";\n'
            '  var val = raw.trim();\n'
            '  if (!val) { alert("Введите ссылку или ID видео YouTube"); return; }\n'
            '  // Extract video ID from full URL (watch?v=, youtu.be/, embed/)\n'
            '  var m = val.match(/(?:[?&]v=|youtu\\.be\\/|embed\\/)([A-Za-z0-9_-]{11})/);\n'
            '  var vid = m ? m[1] : (val.length === 11 && /^[A-Za-z0-9_-]+$/.test(val) ? val : null);\n'
            '  if (!vid) { alert("Не удалось распознать ID видео. Вставьте полную ссылку YouTube."); return; }\n'
            '  var iframe = document.getElementById("yt-iframe");\n'
            '  if (iframe) iframe.src = "https://www.youtube.com/embed/" + vid + "?autoplay=1";\n'
            '  document.getElementById("yt-placeholder").style.display = "none";\n'
            '  document.getElementById("yt-embed-wrap").style.display = "";\n'
            '}\n'
            '</script>\n'
            '</section>\n'
        )

    # ── Sources list ──────────────────────────────────────────────────────
    src_items = "".join(
        f'<li><a href="{esc(s.get("url","#"))}" target="_blank" rel="noopener">'
        f'🔗 {esc(s.get("title","Источник"))}</a></li>\n'
        for s in sources[:10]
    )
    sources_html = (
        '<section class="sources">\n'
        '<h2>📚 Источники и ссылки</h2>\n'
        f'<ol>\n{src_items}</ol>\n'
        '</section>\n'
    )

    # ── Inline SVG bar chart (no external CDN required) ──────────────────
    _chart_src = sources[:8]
    _chart_palette = [
        "#0e84d4", "#1aad5a", "#e8a020", "#a020e8",
        "#d94040", "#40a0d9", "#d9a040", "#40d9a0",
    ]
    _bar_vals = [max(1, len(s.get("snippet", "").split())) for s in _chart_src]
    _bar_max = max(_bar_vals) if _bar_vals else 1
    _bar_width = 60
    _bar_gap = 10
    _chart_w = (_bar_width + _bar_gap) * len(_chart_src) + _bar_gap
    _chart_h = 180
    _bar_area_h = 120
    _svg_bars = ""
    for _bi, (_bv, _bs) in enumerate(zip(_bar_vals, _chart_src)):
        _bx = _bar_gap + _bi * (_bar_width + _bar_gap)
        _bh = max(4, int(_bv / _bar_max * _bar_area_h))
        _by = _bar_area_h - _bh + 10
        _bc = _chart_palette[_bi % len(_chart_palette)]
        _label = esc(_bs.get("title", "")[:18])
        _svg_bars += (
            f'<rect x="{_bx}" y="{_by}" width="{_bar_width}" height="{_bh}" fill="{_bc}" rx="4">'
            f'<title>{_label}: {_bv} слов</title></rect>\n'
            f'<text x="{_bx + _bar_width // 2}" y="{_by - 4}" text-anchor="middle" '
            f'font-size="10" fill="#555">{_bv}</text>\n'
            f'<text x="{_bx + _bar_width // 2}" y="{_bar_area_h + 24}" text-anchor="middle" '
            f'font-size="9" fill="#777">{_label[:12]}</text>\n'
        )
    chart_html = (
        '<section class="chart-section">\n'
        '<h2>📊 Охват источников</h2>\n'
        '<div class="chart-wrap">\n'
        f'<svg viewBox="0 0 {_chart_w} {_chart_h}" xmlns="http://www.w3.org/2000/svg"'
        f' style="width:100%;max-width:{_chart_w}px;overflow:visible;font-family:sans-serif">\n'
        f'<line x1="0" y1="{_bar_area_h + 10}" x2="{_chart_w}" y2="{_bar_area_h + 10}"'
        ' stroke="#ccc" stroke-width="1"/>\n'
        + _svg_bars +
        '</svg>\n'
        '</div>\n'
        '</section>\n'
    )

    # ── Action buttons bar ────────────────────────────────────────────────
    buttons_html = (
        '<div class="action-bar">\n'
        '<button class="btn-action" onclick="window.print()">🖨️ Печать</button>\n'
        '<button class="btn-action" onclick="copyArticle()">📋 Копировать текст</button>\n'
        '<button class="btn-action" onclick="shareArticle()">🔗 Поделиться</button>\n'
        '<button class="btn-action btn-scroll" onclick="window.scrollTo({top:0,behavior:\'smooth\'})">⬆️ Наверх</button>\n'
        '</div>\n'
        '<script>\n'
        'function copyArticle(){\n'
        '  var t=document.querySelector(".article-body");'
        '  if(!t){return;}'
        '  navigator.clipboard.writeText(t.innerText).then(function(){'
        '    alert("Текст скопирован!");'
        '  }).catch(function(){alert("Не удалось скопировать.");});\n'
        '}\n'
        'function shareArticle(){\n'
        '  if(navigator.share){\n'
        f'    navigator.share({{title:"{esc(title)}",url:window.location.href}});\n'
        '  } else {\n'
        '    navigator.clipboard.writeText(window.location.href).then(function(){'
        '      alert("Ссылка скопирована!");'
        '    });\n'
        '  }\n'
        '}\n'
        '</script>\n'
    )

    # ── SVG pipeline diagram ───────────────────────────────────────────────
    svg_html = (
        '<section class="svg-section">\n'
        '<h2>🔄 Как создавалась статья</h2>\n'
        '<svg viewBox="0 0 700 90" xmlns="http://www.w3.org/2000/svg"'
        ' style="max-width:100%;font-family:sans-serif">\n'
        '<rect x="0" y="20" width="110" height="50" rx="10" fill="#0e84d4"/>'
        '<text x="55" y="48" text-anchor="middle" fill="#fff" font-size="12">🔍 Запрос</text>\n'
        '<polygon points="115,45 128,35 128,55" fill="#555"/>\n'
        '<rect x="133" y="20" width="110" height="50" rx="10" fill="#1aad5a"/>'
        '<text x="188" y="48" text-anchor="middle" fill="#fff" font-size="12">🌐 Поиск</text>\n'
        '<polygon points="248,45 261,35 261,55" fill="#555"/>\n'
        '<rect x="266" y="20" width="110" height="50" rx="10" fill="#e8a020"/>'
        '<text x="321" y="48" text-anchor="middle" fill="#fff" font-size="12">📸 Данные</text>\n'
        '<polygon points="381,45 394,35 394,55" fill="#555"/>\n'
        '<rect x="399" y="20" width="110" height="50" rx="10" fill="#a020e8"/>'
        '<text x="454" y="48" text-anchor="middle" fill="#fff" font-size="12">🤖 AI</text>\n'
        '<polygon points="514,45 527,35 527,55" fill="#555"/>\n'
        '<rect x="532" y="20" width="160" height="50" rx="10" fill="#d94040"/>'
        '<text x="612" y="48" text-anchor="middle" fill="#fff" font-size="12">📰 Статья</text>\n'
        '</svg></section>\n'
    )

    css = (
        "@keyframes fadeInUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}"
        "@keyframes slideInLeft{from{opacity:0;transform:translateX(-30px)}to{opacity:1;transform:translateX(0)}}"
        "@keyframes pulse{0%,100%{opacity:1}50%{opacity:.6}}"
        "@keyframes barGrow{from{transform:scaleY(0);transform-origin:bottom}to{transform:scaleY(1);transform-origin:bottom}}"
        f":root{{--accent:{_accent};--accent2:{_accent2};--bg:#f0f4f8;--card:#fff;--text:#1a1a2e}}"
        "body{margin:0;padding:20px;font-family:'Segoe UI',system-ui,sans-serif;"
        "background:var(--bg);color:var(--text);line-height:1.7}"
        "article{background:var(--card);padding:36px;border-radius:12px;"
        "box-shadow:0 4px 20px rgba(0,0,0,.10);max-width:960px;margin:0 auto;"
        "animation:fadeInUp .5s ease both}"
        "h1{font-size:2em;margin-bottom:8px;color:var(--accent);border-bottom:3px solid var(--accent2);padding-bottom:10px;"
        "animation:slideInLeft .5s ease both}"
        "h2{font-size:1.25em;margin:28px 0 10px;color:var(--accent2);display:flex;align-items:center;gap:6px;scroll-margin-top:80px}"
        "p{line-height:1.75;margin:0 0 14px;color:#333}"
        "a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}"
        ".art-list{margin:8px 0 14px 0;padding-left:1.5em}"
        ".art-list li{margin:4px 0;line-height:1.6}"
        ".article-stats{display:flex;gap:16px;flex-wrap:wrap;padding:10px 16px;margin:12px 0 20px;"
        "background:linear-gradient(135deg,#e8f4fd,#f0fff4);border-radius:8px;font-size:.9em;color:#444;"
        "border:1px solid #c5ddf0;animation:fadeInUp .6s ease .1s both}"
        ".article-stats span{white-space:nowrap}"
        ".toc{background:#f8f9ff;border:1px solid #dde4f5;border-radius:8px;padding:14px 20px;"
        "margin:16px 0 28px;display:inline-block;min-width:200px;"
        "animation:slideInLeft .5s ease .2s both}"
        ".toc h3{margin:0 0 8px;font-size:1em;color:var(--accent)}"
        ".toc ol{margin:0;padding-left:1.4em}"
        ".toc li{margin:3px 0;font-size:.92em}"
        ".gallery{margin:32px 0}"
        ".gallery-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px}"
        ".gallery-item{background:#f9f9f9;border-radius:10px;overflow:hidden;"
        "transition:transform .25s ease,box-shadow .25s ease;"
        "box-shadow:0 2px 8px rgba(0,0,0,.08);animation:fadeInUp .5s ease both}"
        ".gallery-item:hover{transform:translateY(-5px) scale(1.01);box-shadow:0 8px 24px rgba(0,0,0,.18)}"
        ".gallery-item img{width:100%;display:block;border-bottom:1px solid #ddd;"
        "transition:filter .3s ease}.gallery-item:hover img{filter:brightness(1.05)}"
        ".gallery-item figcaption{padding:8px 10px;font-size:.82em;color:#555;font-style:italic}"
        ".gallery-item a{display:block}"
        ".sources{background:#f0f7ff;border-left:4px solid var(--accent);padding:16px 20px;"
        "border-radius:0 8px 8px 0;margin:24px 0}"
        ".sources ol{padding-left:1.4em}.sources li{margin:5px 0}"
        ".chart-section{margin:28px 0;animation:fadeInUp .5s ease .15s both}"
        ".chart-wrap{background:#f9f9f9;border-radius:8px;padding:16px;border:1px solid #e0e0e0;"
        "overflow-x:auto}"
        ".chart-wrap svg rect{animation:barGrow .6s ease both}"
        ".svg-section{margin:28px 0}"
        ".video-section{margin:32px 0;animation:fadeInUp .5s ease .2s both}"
        ".video-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:start}"
        "@media(max-width:640px){.video-grid{grid-template-columns:1fr}}"
        ".video-embed-wrap{position:relative;padding-bottom:56.25%;height:0;overflow:hidden;"
        "border-radius:10px;box-shadow:0 4px 12px rgba(0,0,0,.15)}"
        ".video-embed-wrap iframe{position:absolute;top:0;left:0;width:100%;height:100%;border:0}"
        ".video-link-box{background:#fff3e0;border-radius:10px;padding:16px;border:1px solid #ffcc80}"
        ".btn-video{display:inline-block;margin-top:10px;padding:10px 20px;background:#ff0000;"
        "color:#fff;border-radius:8px;text-decoration:none;font-weight:600;font-size:.9em;"
        "transition:background .2s,transform .1s}"
        ".btn-video:hover{background:#cc0000;text-decoration:none;transform:scale(1.03)}"
        ".action-bar{display:flex;gap:10px;flex-wrap:wrap;margin:24px 0;padding:16px;"
        "background:#f9f9f9;border-radius:10px;border:1px solid #e0e0e0}"
        ".btn-action{padding:8px 16px;background:var(--accent);color:#fff;border:none;"
        "border-radius:6px;cursor:pointer;font-size:.88em;font-weight:600;"
        "transition:background .2s,transform .1s}"
        ".btn-action:hover{background:#0a6aab;transform:translateY(-1px)}"
        ".btn-scroll{background:#1aad5a}.btn-scroll:hover{background:#148a48}"
        "h3{font-size:1.1em;margin:20px 0 8px;color:#2c5f8a}"
        "h4{font-size:1em;margin:16px 0 6px;color:#444;font-style:italic}"
        "code{background:#f0f0f0;border-radius:4px;padding:1px 5px;font-size:.88em;font-family:monospace}"
        "code.code-line{display:inline-block;font-family:monospace;background:#f5f5f5;"
        "padding:0 6px;width:100%;font-size:.85em}"
        ".yt-placeholder{background:#fff3e0;border:1px solid #ffcc80;border-radius:12px;padding:20px;margin:12px 0}"
        ".yt-placeholder p{margin:0 0 12px;font-size:.95em;color:#555}"
        ".yt-input-row{display:flex;gap:8px;flex-wrap:wrap}"
        ".btn-video{display:inline-block;padding:9px 18px;background:#ff0000;"
        "color:#fff;border-radius:8px;text-decoration:none;font-weight:600;font-size:.9em;"
        "border:none;cursor:pointer;white-space:nowrap;transition:background .2s,transform .1s}"
        ".btn-video:hover{background:#cc0000;text-decoration:none;transform:scale(1.03)}"
        ".btn-video-search{display:inline-block;padding:9px 18px;background:#0e84d4;"
        "color:#fff;border-radius:8px;text-decoration:none;font-weight:600;font-size:.9em;"
        "white-space:nowrap;transition:background .2s,transform .1s}"
        ".btn-video-search:hover{background:#0a6aab;text-decoration:none;transform:scale(1.03)}"
        ".video-embed-wrap{position:relative;padding-bottom:56.25%;height:0;overflow:hidden;"
        "border-radius:10px;box-shadow:0 4px 12px rgba(0,0,0,.15);margin-bottom:12px}"
        ".video-embed-wrap iframe{position:absolute;top:0;left:0;width:100%;height:100%;border:0}"
        ".article-body p{animation:fadeInUp .4s ease both}"
        "@media print{.action-bar,.video-section,.toc{display:none}}"
        "@media(max-width:600px){article{padding:18px}h1{font-size:1.5em}}"
        ".src-card-head{font-size:2.5em;text-align:center;padding:20px 0 10px;background:#f0f7ff}"
        ".src-card p{margin:6px 0 0;font-size:.82em;color:#555;line-height:1.5}"
        # Hero image styles
        ".hero-img-wrap{margin:-36px -36px 32px;border-radius:12px 12px 0 0;overflow:hidden;"
        "max-height:420px;display:flex;align-items:center;justify-content:center;"
        "background:#e8f0fe}"
        ".hero-img{width:100%;height:420px;object-fit:cover;display:block;"
        "animation:fadeInUp .6s ease both}"
        # Inline floating images within article text
        ".inline-img{max-width:340px;border-radius:10px;overflow:hidden;"
        "box-shadow:0 4px 14px rgba(0,0,0,.12);margin:8px 16px 16px;"
        "transition:transform .25s ease}"
        ".inline-img:hover{transform:scale(1.02)}"
        ".inline-img img{width:100%;height:220px;object-fit:cover;display:block}"
        ".inline-img-right{float:right;clear:right}"
        ".inline-img-left{float:left;clear:left}"
        "@media(max-width:640px){.inline-img{float:none;max-width:100%;margin:12px 0}}"
        # Layout-specific overrides for structural diversity
        # Hero layout: darker header gradient, large accent strip
        ".layout-hero h1{font-size:2.2em;margin-bottom:4px}"
        ".layout-hero .article-stats{background:linear-gradient(135deg,#e0f0ff,#f5f0ff)}"
        # Magazine layout: serif-like heading, pull-quote style
        ".layout-magazine article{border-top:6px solid var(--accent)}"
        ".layout-magazine h2{font-style:italic}"
        ".layout-magazine .toc{float:right;width:260px;margin:0 0 20px 24px;"
        "background:#fafafa;border-radius:8px;padding:14px;border:1px solid #e0e0e0}"
        "@media(max-width:640px){.layout-magazine .toc{float:none;width:auto;margin:0 0 16px}}"
        # Timeline layout: numbered steps on h2
        ".layout-timeline h2::before{content:counter(timeline-section) '. ';counter-increment:timeline-section;"
        "font-size:.8em;color:var(--accent2);margin-right:4px}"
        ".layout-timeline .article-body{counter-reset:timeline-section}"
        # Cards layout: each section in a card-style box
        ".layout-cards .article-body h2{background:var(--accent);color:#fff;"
        "padding:10px 16px;border-radius:8px 8px 0 0;margin:28px 0 0}"
        ".layout-cards .article-body p{border:1px solid #e8e8e8;border-top:none;"
        "padding:14px 16px;border-radius:0 0 8px 8px;margin:0 0 4px}"
    )

    return (
        '<!DOCTYPE html>\n<html lang="ru">\n<head>\n'
        '<meta charset="UTF-8"/>\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1"/>\n'
        f"<title>{esc(title)}</title>\n"
        f"{_BS_CDN}"
        f"<style>{css}</style>\n"
        "</head>\n<body class=\"bg-light\">\n"
        "<div class=\"container py-4\">\n"
        f"<article class=\"card shadow-sm p-4 p-md-5 mb-4 layout-{_layout_style}\">\n"
        f"{hero_html}"
        f"<h1 class=\"display-6 fw-bold mb-3\" style=\"color:var(--accent)\">📰 {esc(title)}</h1>\n"
        f"{stats_html}"
        f"{buttons_html}"
        f"{toc_html}"
        f'<section class="article-body">\n{sections_html}</section>\n'
        '<div style="clear:both"></div>\n'
        f"{gallery_html}"
        f"{video_html}"
        f"{chart_html}"
        f"{svg_html}"
        f"{sources_html}"
        "</article>\n</div>\n</body>\n</html>"
    )


@app.route("/research", methods=["POST"])
def web_research():
    """Full research pipeline: search multiple sources, take screenshots, generate HTML article.

    Body: {"query": "topic", "max_results": 5, "screenshots": true, "model": "",
           "existing_article": "...optional existing article text to enrich..."}
    Returns: {"html": "...", "title": "...", "sources": [...], "success": true}
    """
    import base64 as _b64r
    body = request.get_json(silent=True) or {}
    query = body.get("query", "").strip()
    max_results = min(int(body.get("max_results", 5)), 10)
    do_screenshots = bool(body.get("screenshots", True))
    model = body.get("model", "").strip()
    existing_article = body.get("existing_article", "").strip()

    # If query looks like an existing article, extract topic from it
    if not existing_article and len(query) > 400:
        lines = [l.strip() for l in query.splitlines() if l.strip()]
        has_heading = any(l.startswith("##") or l.startswith("# ") for l in lines)
        para_count = sum(1 for l in lines if len(l) > 60)
        if has_heading or para_count >= 3:
            existing_article = query
            # Extract topic from first heading or first line
            topic = ""
            for l in lines:
                if l.startswith("## ") or l.startswith("# "):
                    topic = re.sub(r'^#+\s*', '', l).strip()
                    break
            if not topic and lines:
                topic = re.sub(r'^[\U0001F300-\U0001F9FF\u2000-\u2FFF\s#*]+', '', lines[0]).strip()[:120]
            if topic:
                query = topic

    if not query:
        return jsonify({"error": "Provide query", "success": False}), 400

    sources: list = []

    # Detect if query is primarily in Russian (for locale hints)
    _is_russian_query = bool(re.search(r'[а-яёА-ЯЁ]{3,}', query))

    # ── 1. DuckDuckGo search ───────────────────────────────────────────────
    _DDGS = None
    try:
        try:
            from ddgs import DDGS as _D
        except ImportError:
            from duckduckgo_search import DDGS as _D  # type: ignore[no-redef]
        _DDGS = _D
    except ImportError:
        pass

    if _DDGS is not None:
        try:
            _ddgs_region = "ru-ru" if _is_russian_query else "wt-wt"
            def _do_ddgs() -> list:
                try:
                    with _DDGS() as d:
                        return list(d.text(query, max_results=max_results, region=_ddgs_region))
                except TypeError:
                    # Older ddgs versions don't support `region` keyword; retry without it
                    return list(_DDGS().text(query, max_results=max_results))

            for r in _do_ddgs():
                sources.append({
                    "title":   r.get("title", ""),
                    "url":     r.get("href", "") or r.get("url", ""),
                    "snippet": r.get("body", "") or r.get("snippet", ""),
                    "source":  "ddg",
                })
        except Exception as _exc:  # pylint: disable=broad-except
            _log.warning("research ddg: %s", _exc)

    # ── 2. Wikipedia ───────────────────────────────────────────────────────
    try:
        # Prefer Russian Wikipedia for Russian queries, fall back to English
        _wiki_lang = "ru" if _is_russian_query else "en"
        wiki_url = f"https://{_wiki_lang}.wikipedia.org/w/api.php"
        wr = _http.get(wiki_url, params={
            "action": "query", "list": "search", "srsearch": query,
            "format": "json", "srlimit": 3, "utf8": 1,
        }, timeout=8)
        wr.raise_for_status()
        for ws in wr.json().get("query", {}).get("search", [])[:3]:
            page_title = ws.get("title", "")
            snippet = re.sub(r'<[^>]+>', '', ws.get("snippet", ""))
            sources.append({
                "title":   page_title,
                "url":     f"https://{_wiki_lang}.wikipedia.org/wiki/{urllib.parse.quote(page_title)}",
                "snippet": snippet,
                "source":  "wikipedia",
            })
    except Exception as _exc:  # pylint: disable=broad-except
        _log.warning("research wikipedia: %s", _exc)

    # ── 3. Reddit ──────────────────────────────────────────────────────────
    try:
        rr = _http.get(
            "https://www.reddit.com/search.json",
            params={"q": query, "sort": "relevance", "limit": 3, "type": "link"},
            headers={"User-Agent": "DrgrBot/1.0 research-agent"},
            timeout=8,
        )
        rr.raise_for_status()
        for ch in rr.json().get("data", {}).get("children", [])[:3]:
            d = ch.get("data", {})
            permalink = d.get("permalink", "")
            href = f"https://www.reddit.com{permalink}" if permalink else d.get("url", "")
            if href.startswith("http"):
                sources.append({
                    "title":   d.get("title", "Reddit post"),
                    "url":     href,
                    "snippet": d.get("selftext", "")[:300],
                    "source":  "reddit",
                })
    except Exception as _exc:  # pylint: disable=broad-except
        _log.warning("research reddit: %s", _exc)

    # ── 4. HackerNews (Algolia) ────────────────────────────────────────────
    try:
        hnr = _http.get(
            "https://hn.algolia.com/api/v1/search",
            params={"query": query, "tags": "story", "hitsPerPage": 3},
            timeout=8,
        )
        hnr.raise_for_status()
        for hit in hnr.json().get("hits", [])[:3]:
            story_url = hit.get("url", "")
            hn_url = f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
            href = story_url if story_url.startswith("http") else hn_url
            sources.append({
                "title":   hit.get("title", "HN story"),
                "url":     href,
                "snippet": hit.get("story_text", "")[:300] if hit.get("story_text") else "",
                "source":  "hackernews",
            })
    except Exception as _exc:  # pylint: disable=broad-except
        _log.warning("research hackernews: %s", _exc)

    if not sources:
        # No internet sources found — fall through to Ollama-only article generation
        _log.warning("research: no internet sources found for %r; generating AI-only article", query)

    # ── 4b. Extract YouTube video ID from sources (for auto-embed) ────────
    yt_video_id = ""
    for _src in sources:
        _yt_m = _YT_VIDEO_ID_RE.search(_src.get("url", "") + " " + _src.get("snippet", ""))
        if _yt_m:
            yt_video_id = _yt_m.group(1)
            break
    # Dedicated YouTube search if nothing found yet
    if not yt_video_id and _DDGS is not None:
        try:
            def _do_yt_ddgs() -> list:
                try:
                    with _DDGS() as d:
                        return list(d.text(f"youtube {query}", max_results=5))
                except TypeError:
                    return list(_DDGS().text(f"youtube {query}", max_results=5))

            for _yr in _do_yt_ddgs():
                _yurl = _yr.get("href", "") or _yr.get("url", "")
                _yt_m = _YT_VIDEO_ID_RE.search(_yurl)
                if _yt_m:
                    yt_video_id = _yt_m.group(1)
                    break
        except Exception as _exc:  # pylint: disable=broad-except
            _log.debug("research yt search: %s", _exc)

    # ── 5. Screenshots (base64 data URIs) ─────────────────────────────────
    screenshot_uris: list = []
    if do_screenshots:
        _PLAYWRIGHT_OK = False
        try:
            from playwright.sync_api import sync_playwright as _sync_pw  # type: ignore
            _PLAYWRIGHT_OK = True
        except ImportError:
            pass

        if _PLAYWRIGHT_OK:
            # Only screenshot from reliable sources (not reddit/hackernews which are JS-heavy).
            # Prefer sources whose title/snippet contains query keywords for topic relevance.
            _query_kws = set(re.sub(r'[^\w\s]', '', query.lower()).split())
            def _relevance_score(s: dict) -> int:
                txt = (s.get("title", "") + " " + s.get("snippet", "")).lower()
                return sum(1 for kw in _query_kws if kw in txt)

            _ss_sources = sorted(
                [
                    s for s in sources
                    if s.get("url", "").startswith("http")
                    and s.get("source", "") not in _EXCLUDED_SCREENSHOT_SOURCES
                ],
                key=_relevance_score,
                reverse=True,
            )
            max_ss = min(3, len(_ss_sources))
            for src in _ss_sources[:max_ss]:
                url = src.get("url", "")
                if not url.startswith("http"):
                    continue
                try:
                    import tempfile as _tf
                    with _tf.NamedTemporaryFile(suffix=".png", delete=False) as _tmp:
                        tmp_path = _tmp.name
                    with _sync_pw() as pw:
                        browser = pw.chromium.launch(
                            headless=True,
                            args=["--no-sandbox", "--disable-setuid-sandbox",
                                  "--disable-dev-shm-usage"],
                        )
                        page = browser.new_page(viewport={"width": 1280, "height": 800})
                        page.goto(url, wait_until="domcontentloaded", timeout=12000)
                        page.screenshot(path=tmp_path, full_page=False)
                        browser.close()
                    with open(tmp_path, "rb") as _f:
                        uri = "data:image/png;base64," + _b64r.b64encode(_f.read()).decode()
                    os.unlink(tmp_path)
                    screenshot_uris.append(uri)
                except Exception as _exc:  # pylint: disable=broad-except
                    _log.warning("research screenshot %s: %s", url, _exc)

    # ── 5b. Vision analysis of screenshots ────────────────────────────────
    vis_descriptions: list = []
    if screenshot_uris:
        _vis_model = model or _best_vision_model()
        # Sanitize query for use in prompt (limit length, no control chars)
        _safe_query = re.sub(r'[\x00-\x1f]', ' ', query)[:200]
        for _uri in screenshot_uris:
            try:
                # Validate data URI format; skip if malformed
                if not (_uri.startswith("data:image/") and "," in _uri):
                    _log.debug("research vision: skipping malformed data URI")
                    continue
                _img_b64 = _uri.split(",", 1)[1]
                if not _img_b64:
                    continue
                _vision_prompt = (
                    f"Опиши подробно что ты видишь на этом скриншоте веб-страницы"
                    f" по теме '{_safe_query}'. Извлеки ключевую информацию: заголовки,"
                    " данные, факты, ссылки."
                )
                if _vis_model.startswith(_VISION_VM_PREFIX) and VISION_VM_URL:
                    _real_vis = _vis_model[len(_VISION_VM_PREFIX):]
                    _vr = _http.post(
                        f"{VISION_VM_URL}/api/generate",
                        json={"model": _real_vis, "prompt": _vision_prompt,
                              "images": [_img_b64], "stream": False},
                        timeout=60,
                    )
                    if _vr.status_code == 200:
                        _desc = _vr.json().get("response", "")
                        if _desc:
                            vis_descriptions.append(_desc)
                elif _vis_model.startswith(_LM_STUDIO_PREFIX) and LM_STUDIO_BASE:
                    _real_vis = _vis_model[len(_LM_STUDIO_PREFIX):]
                    _vr = _http.post(
                        f"{LM_STUDIO_BASE}/v1/chat/completions",
                        json={"model": _real_vis, "messages": [{"role": "user", "content": [
                            {"type": "text", "text": _vision_prompt},
                            {"type": "image_url", "image_url": {"url": _uri}},
                        ]}], "stream": False, "max_tokens": 600},
                        timeout=60,
                    )
                    if _vr.status_code == 200:
                        _desc = _vr.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                        if _desc:
                            vis_descriptions.append(_desc)
                elif not _vis_model.startswith(_LM_STUDIO_PREFIX) and not _vis_model.startswith(_VISION_VM_PREFIX):
                    _vr = _http.post(
                        f"{OLLAMA_BASE}/api/generate",
                        json={"model": _vis_model, "prompt": _vision_prompt,
                              "images": [_img_b64], "stream": False},
                        timeout=60,
                    )
                    if _vr.status_code == 200:
                        _desc = _vr.json().get("response", "")
                        if _desc:
                            vis_descriptions.append(_desc)
            except Exception as _vexc:  # pylint: disable=broad-except
                _log.warning("research vision analysis: %s", _vexc)

    # ── 6. Build aggregated text for Ollama ───────────────────────────────
    # Filter: keep only sources with meaningful snippets (>= 50 chars)
    blocks = [
        f"Источник «{s['title']}»: {s.get('snippet','')[:800]}"
        for s in sources[:10]
        if len(s.get("snippet", "")) >= 50
    ]
    if vis_descriptions:
        blocks += [f"Описание скриншота {i+1}: {d[:600]}" for i, d in enumerate(vis_descriptions)]
    aggregated = "\n\n".join(blocks)

    # ── 7. Generate article text via Ollama, LM Studio, TGWUI or Roo Code ──
    article_text = ""
    is_lms_research  = model.startswith(_LM_STUDIO_PREFIX)  if model else False
    is_roo_research  = model.startswith(_ROO_CODE_PREFIX)   if model else False

    if not model:
        # Auto-detect: prefer LM Studio → Roo Code → Ollama
        if LM_STUDIO_BASE:
            try:
                lms_mr = _http.get(f"{LM_STUDIO_BASE}/v1/models", timeout=5)
                if lms_mr.status_code == 200:
                    lms_model_list = lms_mr.json().get("data", [])
                    if lms_model_list:
                        model = f"{_LM_STUDIO_PREFIX}{lms_model_list[0]['id']}"
                        is_lms_research = True
            except Exception:  # pylint: disable=broad-except
                pass
        if not model and ROO_CODE_BASE:
            try:
                roo_mr = _http.get(f"{ROO_CODE_BASE}/v1/models", timeout=5)
                if roo_mr.status_code == 200:
                    roo_model_list = roo_mr.json().get("data", [])
                    if roo_model_list:
                        model = f"{_ROO_CODE_PREFIX}{roo_model_list[0]['id']}"
                        is_roo_research = True
            except Exception:  # pylint: disable=broad-except
                pass
        if not model:
            try:
                mr = _http.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
                mr.raise_for_status()
                models_list = mr.json().get("models", [])
                if models_list:
                    model = models_list[0].get("name", "")
            except Exception:  # pylint: disable=broad-except
                pass

    if model and aggregated:
        try:
            import random as _rand
            import datetime as _dt
            _variation_styles = [
                "глубокий аналитический обзор с историческим контекстом",
                "практическое руководство с конкретными примерами и советами",
                "журналистское расследование с цитатами и статистикой",
                "научно-популярный рассказ с интересными открытиями",
                "репортаж с акцентом на последние события и тренды",
                "сравнительный анализ с разными точками зрения",
                "экспертный разбор с разными уровнями детализации",
                "практический кейс с примерами из реальной жизни",
            ]
            _style = _rand.choice(_variation_styles)
            _year = _dt.date.today().year
            # Use enrichment prompt when existing article is provided
            if existing_article:
                _existing_snippet = existing_article[:1500].strip()
                prompt = (
                    f'Ты — профессиональный AI-журналист и редактор. Тебе предоставлена СУЩЕСТВУЮЩАЯ СТАТЬЯ по теме "{query}".\n\n'
                    f"ТВОЯ ЗАДАЧА — создать УЛУЧШЕННУЮ, ОБОГАЩЁННУЮ версию статьи:\n"
                    f"1. ПРОВЕРЬ факты из исходной статьи по свежим источникам\n"
                    f"2. ДОБАВЬ недостающую актуальную информацию из источников ниже\n"
                    f"3. ОПРОВЕРГНИ устаревшие или ошибочные утверждения (если есть)\n"
                    f"4. РАСШИРИ статью новыми разделами и деталями\n"
                    f"5. Стиль: {_style}\n\n"
                    f"ИСХОДНАЯ СТАТЬЯ (для контекста и обогащения):\n"
                    f"---\n{_existing_snippet}\n---\n\n"
                    f"НОВЫЕ ДАННЫЕ ИЗ АКТУАЛЬНЫХ ИСТОЧНИКОВ {_year} ГОДА:\n{aggregated}\n\n"
                    f"СТРУКТУРА УЛУЧШЕННОЙ СТАТЬИ (не менее 8 разделов):\n"
                    f"Строка 1: Улучшенный заголовок статьи о теме '{query}' (без символа #)\n\n"
                    f"## 🔍 Введение\nЧто такое '{query}', актуальность в {_year} году (с новыми данными).\n\n"
                    f"## 📌 Ключевые факты\nОсновные характеристики — проверенные и обновлённые.\n\n"
                    f"## 💡 Актуальная информация {_year}\nСамые свежие данные, исправления устаревших сведений.\n\n"
                    f"## 📊 Цифры и статистика\nКонкретные данные, цитаты экспертов, исследования.\n\n"
                    f"## 🌍 Применение и примеры\nРеальные кейсы, практическое применение.\n\n"
                    f"## 🌟 Что не было в исходной статье\nНовые факты, открытия, детали по теме '{query}'.\n\n"
                    f"## 📈 Тренды и перспективы\nПоследние тенденции и прогнозы на {_year} год.\n\n"
                    f"## ✅ Итоговые выводы\nОбновлённые заключения, сравнение с исходной статьёй.\n\n"
                    f"Требования:\n"
                    f"- Минимум 800 слов\n"
                    f"- Только русский язык\n"
                    f"- Статья должна быть ЗАМЕТНО БОГАЧЕ исходной\n"
                    f"- Включи конкретные ссылки на источники внутри текста\n"
                    f"- ТОЛЬКО Markdown разметка (## для разделов, ** для выделения) — никаких HTML тегов\n"
                    f"- НЕ ПИШИ вступлений типа 'Конечно, вот статья' — начни СРАЗУ с заголовка\n"
                )
            else:
                prompt = (
                    f'Ты — профессиональный AI-журналист. Напиши УНИКАЛЬНУЮ ПОЛНОЦЕННУЮ статью СТРОГО по теме "{query}".\n\n'
                    f"Стиль статьи: {_style}.\n\n"
                    f"КРИТИЧЕСКИ ВАЖНО:\n"
                    f"- Статья должна быть ТОЛЬКО И ИСКЛЮЧИТЕЛЬНО о теме '{query}'\n"
                    f"- НЕ смешивай разные темы из источников\n"
                    f"- НЕ КОПИРУЙ тексты из источников — используй их ТОЛЬКО как справочный материал\n"
                    f"- Пиши СВОИМИ словами, статья должна быть уникальной\n"
                    f"- Включай конкретные факты, цифры, даты из источников\n\n"
                    f"Справочные данные из источников:\n{aggregated}\n\n"
                    f"СТРУКТУРА СТАТЬИ (обязательная, не менее 7 разделов):\n"
                    f"Строка 1: Оригинальный заголовок ТОЛЬКО о теме '{query}' (без символа #)\n\n"
                    f"## 🔍 Введение\n"
                    f"Что такое '{query}', почему эта тема актуальна в {_year} году.\n\n"
                    f"## 📌 Основные аспекты\n"
                    f"Ключевые характеристики и особенности темы.\n\n"
                    f"## 💡 Важные факты и цифры\n"
                    f"Конкретные данные, статистика, цитаты экспертов по теме '{query}'.\n\n"
                    f"## 🌍 Применение и примеры\n"
                    f"Реальные случаи и практическое применение.\n\n"
                    f"## 🌟 Интересные подробности\n"
                    f"Малоизвестные факты и детали темы '{query}'.\n\n"
                    f"## 📈 Актуальные тренды\n"
                    f"Последние тенденции и развитие темы в {_year} году.\n\n"
                    f"## ✅ Заключение\n"
                    f"Итоговые выводы и перспективы по теме '{query}'.\n\n"
                    f"Требования к тексту:\n"
                    f"- Минимум 700 слов\n"
                    f"- Только русский язык\n"
                    f"- Тема статьи: ТОЛЬКО '{query}'\n"
                    f"- Статья должна быть уникальной и информативной\n"
                    f"- ТОЛЬКО Markdown разметка (## для разделов, ** для выделения) — никаких HTML тегов\n"
                    f"- НЕ ПИШИ вступлений типа 'Конечно, вот статья' — начни СРАЗУ с заголовка\n"
                )
            is_tgwui_research = model.startswith(_TGWUI_PREFIX)
            is_roo_research   = model.startswith(_ROO_CODE_PREFIX)
            if is_lms_research:
                real_model = model[len(_LM_STUDIO_PREFIX):]
                ar = _http.post(
                    f"{LM_STUDIO_BASE}/v1/chat/completions",
                    json={"model": real_model,
                          "messages": [{"role": "user", "content": prompt}],
                          "stream": False, "max_tokens": 4096},
                    timeout=int(os.environ.get("OLLAMA_TIMEOUT", 180)),
                )
                ar.raise_for_status()
                article_text = ar.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            elif is_tgwui_research:
                real_model = model[len(_TGWUI_PREFIX):]
                ar = _http.post(
                    f"{TGWUI_BASE}/v1/chat/completions",
                    json={"model": real_model,
                          "messages": [{"role": "user", "content": prompt}],
                          "stream": False, "max_tokens": 4096},
                    timeout=int(os.environ.get("OLLAMA_TIMEOUT", 180)),
                )
                ar.raise_for_status()
                article_text = ar.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            elif is_roo_research:
                real_model = model[len(_ROO_CODE_PREFIX):]
                ar = _http.post(
                    f"{ROO_CODE_BASE}/v1/chat/completions",
                    json={"model": real_model,
                          "messages": [{"role": "user", "content": prompt}],
                          "stream": False, "max_tokens": 4096},
                    timeout=int(os.environ.get("OLLAMA_TIMEOUT", 180)),
                )
                ar.raise_for_status()
                article_text = ar.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            else:
                ar = _http.post(
                    f"{OLLAMA_BASE}/api/generate",
                    json={"model": model, "prompt": prompt, "stream": False},
                    timeout=int(os.environ.get("OLLAMA_TIMEOUT", 180)),
                )
                ar.raise_for_status()
                article_text = ar.json().get("response", "")
        except Exception as _exc:  # pylint: disable=broad-except
            _log.warning("research ollama: %s", _exc)
    elif model and not sources:
        # No internet sources available — generate article from AI knowledge alone
        try:
            import random as _rand2
            import datetime as _dt2
            _styles2 = [
                "глубокий аналитический обзор",
                "научно-популярный рассказ",
                "практическое руководство с примерами",
                "репортаж с фактами и цифрами",
            ]
            _style2 = _rand2.choice(_styles2)
            _year2 = _dt2.date.today().year
            prompt = (
                f'Ты — профессиональный AI-журналист. Напиши УНИКАЛЬНУЮ ПОЛНОЦЕННУЮ статью СТРОГО по теме: "{query}".\n\n'
                f"Стиль: {_style2}.\n\n"
                f"СТРУКТУРА СТАТЬИ (не менее 7 разделов):\n"
                f"Строка 1: Оригинальный заголовок о теме '{query}' (без символа #)\n\n"
                f"## 🔍 Введение\n"
                f"Что такое '{query}' и почему это важно в {_year2} году.\n\n"
                f"## 📌 Основные аспекты\n"
                f"Ключевые характеристики и особенности.\n\n"
                f"## 💡 Важные факты и цифры\n"
                f"Конкретные данные, статистика.\n\n"
                f"## 🌍 Применение и примеры\n"
                f"Практическое применение, реальные случаи.\n\n"
                f"## 🌟 Интересные подробности\n"
                f"Малоизвестные факты и детали.\n\n"
                f"## 📈 Актуальные тренды\n"
                f"Последние тенденции в {_year2} году.\n\n"
                f"## ✅ Заключение\n"
                f"Итоговые выводы и перспективы.\n\n"
                f"Требования: минимум 700 слов, только русский язык, ТОЛЬКО о теме '{query}', статья уникальная.\n"
                f"ТОЛЬКО Markdown разметка — никаких HTML тегов. Начни СРАЗУ с заголовка, без вступлений.\n"
                "Примечание: статья создана на основе знаний AI (без интернет-поиска)."
            )
            is_tgwui_research = model.startswith(_TGWUI_PREFIX)
            is_roo_research   = model.startswith(_ROO_CODE_PREFIX)
            if is_lms_research:
                real_model = model[len(_LM_STUDIO_PREFIX):]
                ar = _http.post(
                    f"{LM_STUDIO_BASE}/v1/chat/completions",
                    json={"model": real_model,
                          "messages": [{"role": "user", "content": prompt}],
                          "stream": False, "max_tokens": 4096},
                    timeout=int(os.environ.get("OLLAMA_TIMEOUT", 180)),
                )
                ar.raise_for_status()
                article_text = ar.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            elif is_tgwui_research:
                real_model = model[len(_TGWUI_PREFIX):]
                ar = _http.post(
                    f"{TGWUI_BASE}/v1/chat/completions",
                    json={"model": real_model,
                          "messages": [{"role": "user", "content": prompt}],
                          "stream": False, "max_tokens": 4096},
                    timeout=int(os.environ.get("OLLAMA_TIMEOUT", 180)),
                )
                ar.raise_for_status()
                article_text = ar.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            elif is_roo_research:
                real_model = model[len(_ROO_CODE_PREFIX):]
                ar = _http.post(
                    f"{ROO_CODE_BASE}/v1/chat/completions",
                    json={"model": real_model,
                          "messages": [{"role": "user", "content": prompt}],
                          "stream": False, "max_tokens": 4096},
                    timeout=int(os.environ.get("OLLAMA_TIMEOUT", 180)),
                )
                ar.raise_for_status()
                article_text = ar.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            else:
                ar = _http.post(
                    f"{OLLAMA_BASE}/api/generate",
                    json={"model": model, "prompt": prompt, "stream": False},
                    timeout=int(os.environ.get("OLLAMA_TIMEOUT", 180)),
                )
                ar.raise_for_status()
                article_text = ar.json().get("response", "")
        except Exception as _exc:  # pylint: disable=broad-except
            _log.warning("research ollama (no-internet fallback): %s", _exc)

    if not article_text:
        if not sources:
            # Neither internet nor Ollama available
            return jsonify({"error": "No results found and no AI model available", "success": False}), 404
        # Fallback: build a structured article from source snippets
        good_snippets = [
            s for s in sources
            if len(s.get("snippet", "")) >= 50
        ]
        if good_snippets:
            # Build a readable article rather than a raw snippet dump
            intro = (
                f"{query}\n\n"
                f"По данной теме удалось найти следующую информацию из открытых источников.\n"
            )
            body_parts = []
            for s in good_snippets[:5]:
                section_title = s['title'][:80].strip()
                snippet_text = s.get('snippet', '').strip()
                body_parts.append(f"## 📌 {section_title}\n{snippet_text}")
            article_text = (
                intro
                + "\n\n".join(body_parts)
                + "\n\n## ✅ Заключение\nПриведённые данные получены из открытых источников. "
                "Для получения более подробной информации воспользуйтесь ссылками на источники ниже."
            )
        else:
            return jsonify({"error": "Не удалось получить достаточно данных по запросу", "success": False}), 404

    # ── 8. Clean article text from LLM artefacts ─────────────────────────
    # Strip fenced code blocks wrapping the whole output (some models wrap their
    # response in ```html ... ``` or ``` ... ```)
    article_text = article_text.strip()
    article_text = re.sub(r'^```[a-zA-Z]*\s*\n', '', article_text)
    article_text = re.sub(r'\n```\s*$', '', article_text)
    article_text = article_text.strip()

    # If the LLM returned raw HTML (starts with <!DOCTYPE or <html), extract
    # plain text from it so _research_build_html can re-render it properly.
    if re.match(r'^\s*<!DOCTYPE\s+html|^\s*<html', article_text, re.IGNORECASE):
        import html as _html_mod
        article_text = re.sub(r'<style[^>]*>.*?</\s*style[^>]*>', '', article_text, flags=re.DOTALL | re.IGNORECASE)
        article_text = re.sub(r'<script[^>]*>.*?</\s*script[^>]*>', '', article_text, flags=re.DOTALL | re.IGNORECASE)
        article_text = re.sub(r'<[^>]+>', ' ', article_text)
        article_text = _html_mod.unescape(article_text)
        article_text = re.sub(r'\s{3,}', '\n\n', article_text).strip()
    elif re.search(r'<(?:p|h[1-6]|div|ul|li|strong|em|br)\b', article_text, re.IGNORECASE):
        # Partial HTML tags in the body — strip them to get clean text
        import html as _html_mod
        article_text = re.sub(r'<[^>]+>', ' ', article_text)
        article_text = _html_mod.unescape(article_text)
        article_text = re.sub(r'\s{3,}', '\n\n', article_text).strip()

    # Strip leading lines that look like LLM preamble phrases
    # (e.g. "Конечно! Вот ваша статью:", "Here is the article:", "Sure, here's...")
    _preamble_line = re.compile(
        r'^(?:'
        r'конечно[,!].{0,60}$|'
        r'конечно\s*$|'
        r'вот\s+(?:ваша\s+)?(?:статья|текст)[.:!]?\s*$|'
        r'вот\s+(?:готовая\s+)?статья[.:!]?\s*$|'
        r'пожалуйста[,!]\s+вот\s+.{0,60}:\s*$|'
        r'как\s+(?:вы\s+)?просили.{0,80}$|'
        r'разумеется[,!].{0,60}$|'
        r'с\s+удовольствием.{0,60}$|'
        r'ниже\s+(?:представлена\s+|находится\s+)?(?:статья|текст).{0,60}$|'
        r'here\s+is\s+(?:the\s+)?(?:article|text)[.:!]?\s*$|'
        r'sure[,!]\s+here(?:\'s|\s+is).{0,60}$|'
        r'below\s+is\s+(?:a\s+|an\s+|the\s+)?(?:article|text|draft).{0,60}$|'
        r'i\'ve\s+(?:written|prepared|created)\s+.{0,60}$|'
        r'(?:вот|это)\s+(?:готовая\s+)?(?:статья|текст)\s+(?:по|о|про)\s+.{0,80}$|'
        r'\*{1,3}(?:статья|article|текст)\*{0,3}[.:\s]*$'
        r')',
        re.IGNORECASE,
    )
    _art_lines = article_text.splitlines()
    while _art_lines and _preamble_line.match(_art_lines[0].strip()):
        _art_lines.pop(0)
    # Also skip leading blank lines after preamble removal
    while _art_lines and not _art_lines[0].strip():
        _art_lines.pop(0)
    # Skip lines before the first ## heading that look like LLM commentary.
    # A well-formed article has at most 2 lines before the first ## heading
    # (typically the article title and possibly a subtitle/tagline).
    # If more than _MAX_PRE_HEADING_LINES lines precede the first ## it is very
    # likely LLM preamble chatter ("Here is your article…", "Of course! …" etc.)
    # that survived the pattern-based stripping above — trim it aggressively.
    _MAX_PRE_HEADING_LINES = 4
    _first_h2 = next(
        (i for i, ln in enumerate(_art_lines) if ln.strip().startswith("## ") or ln.strip().startswith("# ")),
        None,
    )
    if _first_h2 is not None and _first_h2 > _MAX_PRE_HEADING_LINES:
        # Keep up to 2 non-empty lines before the first heading (title + subtitle)
        _keep_before = min(2, _first_h2)
        _before = [ln for ln in _art_lines[:_first_h2] if ln.strip()]
        _art_lines = _before[-_keep_before:] + _art_lines[_first_h2:]
    article_text = "\n".join(_art_lines).strip()

    # ── 9. Build HTML article ─────────────────────────────────────────────
    lines = article_text.strip().splitlines()
    title = lines[0].lstrip("#* ").strip() if lines else query
    html_article = _research_build_html(title, article_text, sources, screenshot_uris, yt_video_id)

    _record_agent_action({
        "timestamp": _now(),
        "action_type": "research",
        "input": {"query": query},
        "output": {"sources": len(sources), "screenshots": len(screenshot_uris)},
        "success": True,
        "duration_ms": 0,
        "metadata": {"model": model},
    })

    return jsonify({
        "html":    html_article,
        "title":   title,
        "sources": [{"title": s["title"], "url": s["url"], "source": s.get("source", "")}
                    for s in sources[:10]],
        "success": True,
    })


@app.route("/search", methods=["POST"])
def web_search():
    """Search the web using the ddgs library (primary) or DuckDuckGo Lite HTML (fallback).

    Body: {"query": "search terms", "max_results": 5}
    Returns: {results: [{title, url, snippet},...], query, success}
    """
    body = request.get_json(silent=True) or {}
    query = body.get("query", "").strip()
    max_results = min(int(body.get("max_results", 5)), 10)

    if not query:
        return jsonify({"error": "Provide query", "success": False}), 400

    results = []
    last_error = ""

    # ── Primary: try ddgs / duckduckgo_search library ─────────────────────────
    _DDGS = None
    try:
        try:
            from ddgs import DDGS as _D
        except ImportError:
            from duckduckgo_search import DDGS as _D  # type: ignore[no-redef]
        _DDGS = _D
    except ImportError:
        pass

    if _DDGS is not None:
        try:
            def _ddgs_search() -> list:
                try:
                    with _DDGS() as ddgs_inst:
                        return list(ddgs_inst.text(query, max_results=max_results))
                except TypeError:
                    return list(_DDGS().text(query, max_results=max_results))

            raw = _ddgs_search()
            for r in raw:
                results.append({
                    "title":   r.get("title", ""),
                    "url":     r.get("href", "") or r.get("url", ""),
                    "snippet": r.get("body", "") or r.get("snippet", ""),
                })
        except (OSError, RuntimeError, ValueError, ImportError) as exc:
            last_error = str(exc)
            _log.warning("web_search ddgs: %s", exc)
        except Exception as exc:  # pylint: disable=broad-except  # ddgs may raise library-specific errors
            last_error = str(exc)
            _log.warning("web_search ddgs (unexpected): %s", exc)

    # ── Fallback: scrape DuckDuckGo Lite HTML ─────────────────────────────────
    if not results:
        try:
            import urllib.parse as _up
            search_url = "https://lite.duckduckgo.com/lite/"
            params = {"q": query, "kl": "ru-ru"}
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0 Safari/537.36",
                "Accept-Language": "ru,en;q=0.9",
            }
            r = _http.post(search_url, data=params, headers=headers, timeout=10)
            r.raise_for_status()

            html_text = r.text
            # Primary pattern for DuckDuckGo Lite results
            link_pattern = re.compile(
                r'<a[^>]+class="result-link"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>',
                re.IGNORECASE | re.DOTALL,
            )
            snip_pattern = re.compile(
                r'<td[^>]+class="result-snippet"[^>]*>(.*?)</td>',
                re.IGNORECASE | re.DOTALL,
            )
            links = link_pattern.findall(html_text)
            snippets = [re.sub(r'<[^>]+>', '', s).strip()
                        for s in snip_pattern.findall(html_text)]

            for i, (href, title) in enumerate(links[:max_results]):
                snippet = snippets[i] if i < len(snippets) else ""
                # Decode DuckDuckGo redirect URLs if present
                if "duckduckgo.com/l/?" in href:
                    match = re.search(r'uddg=([^&]+)', href)
                    if match:
                        href = _up.unquote(match.group(1))
                elif href.startswith("/"):
                    href = "https://duckduckgo.com" + href
                results.append({
                    "title":   title.strip(),
                    "url":     href,
                    "snippet": snippet[:300],
                })

            # Broader fallback if primary regex matched nothing
            if not results:
                broad = re.findall(
                    r'<a[^>]+href="(https?://[^"]+)"[^>]*>([^<]{5,120})</a>',
                    html_text)
                for href, title in broad[:max_results]:
                    if "duckduckgo.com" not in href:
                        results.append({"title": title.strip(), "url": href, "snippet": ""})

        except (_http.exceptions.RequestException, OSError, ValueError) as exc:
            last_error = str(exc)
            _log.warning("web_search html-scrape: %s", exc)
        except Exception as exc:  # pylint: disable=broad-except  # defensive catch for regex/decode errors
            last_error = str(exc)
            _log.warning("web_search html-scrape (unexpected): %s", exc)

    if not results and last_error:
        return jsonify({"error": last_error, "success": False}), 500

    _record_agent_action({
        "timestamp": _now(),
        "action_type": "web_search",
        "input": {"query": query},
        "output": {"results_count": len(results)},
        "success": bool(results),
        "duration_ms": 0,
        "metadata": {},
    })

    return jsonify({"results": results, "query": query, "success": True})


# ---------------------------------------------------------------------------
# File download — download a file from a URL and return its content/save it
# ---------------------------------------------------------------------------

@app.route("/files/download", methods=["POST"])
def files_download():
    """Download a file from a URL and return its text content (or save it).

    Body: {"url": "https://example.com/file.py", "save": false}
    Returns: {content: "...", filename: "...", language: "...", success: true}
    or if save=true: {path: "/abs/path", filename: "...", success: true}
    """
    import urllib.parse as _up

    body = request.get_json(silent=True) or {}
    url = body.get("url", "").strip()
    save_to_disk = bool(body.get("save", False))

    if not url or not url.startswith(("http://", "https://")):
        return jsonify({"error": "Provide a valid http/https URL", "success": False}), 400

    # SSRF guard — reconstruct URL from parsed parts to break taint chain
    safe_url = ""
    try:
        import ipaddress as _ip
        parsed = _up.urlparse(url)
        hostname = parsed.hostname or ""
        _BLOCKED = {"localhost", "0.0.0.0", "::1", "ip6-localhost", "ip6-loopback"}
        if hostname in _BLOCKED:
            return jsonify({"error": "Requests to internal addresses are not allowed", "success": False}), 400
        try:
            addr = _ip.ip_address(hostname)
            if addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local:
                return jsonify({"error": "Requests to private/reserved IPs are not allowed", "success": False}), 400
        except ValueError:
            pass
        # Reconstruct from parsed parts to produce a sanitised URL
        safe_url = _up.urlunparse((
            parsed.scheme, parsed.netloc, parsed.path,
            "", parsed.query, "",
        ))
    except Exception as ssrf_exc:
        return jsonify({"error": f"URL validation failed: {ssrf_exc}", "success": False}), 400
    if not safe_url:
        return jsonify({"error": "Could not construct safe URL", "success": False}), 400

    try:
        r = _http.get(safe_url, timeout=15,
                      headers={"User-Agent": "Mozilla/5.0 (compatible; DRGRBot/1.0)"},
                      stream=True)
        r.raise_for_status()

        # Limit to 1 MB
        chunks = []
        total = 0
        for chunk in r.iter_content(chunk_size=8192):
            total += len(chunk)
            if total > 1_048_576:
                return jsonify({"error": "File too large (> 1 MB)", "success": False}), 400
            chunks.append(chunk)
        raw = b"".join(chunks)

        # Guess filename from URL
        path_part = _up.urlparse(safe_url).path
        filename = os.path.basename(path_part) or "downloaded_file.txt"
        _, ext = os.path.splitext(filename.lower())

        if save_to_disk:
            save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
            os.makedirs(save_dir, exist_ok=True)
            dest = os.path.join(save_dir, filename)
            with open(dest, "wb") as fh:
                fh.write(raw)
            return jsonify({"path": dest, "filename": filename, "size": len(raw), "success": True})

        # Return as text
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            content = raw.decode("latin-1")

        _ext_to_lang = {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".html": "html", ".htm": "html", ".css": "css",
            ".json": "json", ".xml": "xml", ".yaml": "yaml", ".yml": "yaml",
            ".md": "markdown", ".sql": "sql", ".sh": "shell", ".bash": "bash",
        }
        lang = _ext_to_lang.get(ext, "plaintext")

        return jsonify({
            "content": content[:65536],
            "filename": filename,
            "language": lang,
            "size": len(raw),
            "success": True,
        })

    except _http.exceptions.Timeout:
        return jsonify({"error": "Download timed out", "success": False}), 500
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"error": str(exc), "success": False}), 500


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
        # Auto-start bot.py if BOT_TOKEN is already configured
        _start_bot()
        # Use HTTPS if SSL cert/key env vars are set (generated by vm.ps1)
        _ssl_cert = os.environ.get("VM_SSL_CERT", "")
        _ssl_key  = os.environ.get("VM_SSL_KEY", "")
        if _ssl_cert and _ssl_key and os.path.isfile(_ssl_cert) and os.path.isfile(_ssl_key):
            _ssl_ctx: object = (_ssl_cert, _ssl_key)
            print(f"[Code VM] HTTPS enabled (cert: {_ssl_cert})", flush=True)
            # Start a plain-HTTP redirect server on port+1 so LAN phones can
            # connect via http:// and get forwarded to the HTTPS URL.
            _http_redir_port = port + 1
            try:
                import http.server as _hs
                import threading as _thr

                class _RedirectHandler(_hs.BaseHTTPRequestHandler):
                    _https_port = port

                    def do_GET(self):  # noqa: N802
                        host = self.headers.get("Host", "").split(":")[0] or "localhost"
                        target = f"https://{host}:{self._https_port}{self.path}"
                        self.send_response(301)
                        self.send_header("Location", target)
                        self.end_headers()

                    def do_POST(self):  # noqa: N802
                        self.do_GET()

                    def log_message(self, fmt, *args):  # noqa: D102
                        """Suppress per-request log lines from the redirect server."""

                _redir_srv = _hs.HTTPServer(("0.0.0.0", _http_redir_port), _RedirectHandler)
                _redir_thr = _thr.Thread(target=_redir_srv.serve_forever, daemon=True)
                _redir_thr.start()
                print(
                    f"[Code VM] HTTP→HTTPS redirect running on port {_http_redir_port}",
                    flush=True,
                )
            except Exception as _redir_exc:
                print(f"[Code VM] Could not start HTTP redirect: {_redir_exc}", flush=True)
        else:
            _ssl_ctx = None
        print("[Code VM] Flask app starting.", flush=True)
        app.run(host="0.0.0.0", port=port, debug=False, ssl_context=_ssl_ctx, threaded=True)
    except Exception:
        print(_tb.format_exc(), flush=True)
        raise
