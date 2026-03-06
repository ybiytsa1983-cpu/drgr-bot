"""
Code VM Server — Flask backend for the Monaco-based self-improving code environment.

Endpoints:
  GET  /               — serve the Monaco editor UI
  POST /execute        — run code (Python or JavaScript) in a sandboxed subprocess
  POST /check          — static-check / lint code
  GET  /instructions   — return the current self-improvement JSON
  POST /instructions   — update training / internet-work instructions
"""

import ast
import json
import os
import re
import subprocess
import tempfile
import threading
from datetime import datetime, timezone

from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder="static")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_DIR = os.path.dirname(os.path.abspath(__file__))
INSTRUCTIONS_FILE = os.path.join(_DIR, "instructions.json")
_lock = threading.Lock()

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
def _regenerate_instructions(data: dict) -> None:
    """Analyse accumulated statistics and rewrite training_instructions."""
    stats = data["statistics"]
    patterns = data["learned_patterns"]
    total = stats["total_runs"]

    instructions: list = [
        "Write clean, readable code with meaningful variable names",
        "Always handle exceptions — never use bare except",
    ]

    # Success-rate advice
    if total > 0:
        rate = stats["successful_runs"] / total
        if rate < 0.40:
            instructions.append(
                "High failure rate detected — focus on debugging and error handling"
            )
        elif rate < 0.70:
            instructions.append(
                f"Moderate success rate ({rate:.0%}) — review error patterns and improve error handling"
            )
        else:
            instructions.append(
                f"Good success rate ({rate:.0%}) — maintain current coding practices"
            )

    # Advice from common errors (top 3)
    common = patterns.get("common_errors", {})
    for error_key, count in sorted(common.items(), key=lambda x: -x[1])[:3]:
        instructions.append(f"Recurring error ({count}×): {error_key[:80]}")

    # Note frequently-used imports (top 5)
    freq = patterns.get("frequently_used_imports", {})
    top_libs = sorted(freq.items(), key=lambda x: -x[1])[:5]
    if top_libs:
        lib_names = ", ".join(name for name, _ in top_libs)
        instructions.append(f"Frequently used libraries: {lib_names}")

    data["training_instructions"] = instructions

    # Append to improvement_history (keep last 20 entries)
    entry = {
        "timestamp": _now(),
        "total_runs": total,
        "success_rate": round(stats["successful_runs"] / total, 2) if total > 0 else 0,
        "instructions_count": len(instructions),
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
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("VM_PORT", 5000))
    # Ensure instructions file is initialised before accepting requests
    load_instructions()
    app.run(host="0.0.0.0", port=port, debug=False)
