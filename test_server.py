#!/usr/bin/env python3
"""Comprehensive functional test suite for vm/server.py endpoints.

Run with:  python3 test_server.py
All tests use the Flask test client (no real network required).
"""
import base64
import json
import struct
import sys
import zlib

sys.path.insert(0, "vm")
import server  # noqa: E402  (must come after path insert)


# ── helpers ──────────────────────────────────────────────────────────────────

def make_1x1_png() -> bytes:
    """Return a minimal valid 1×1 RGB PNG."""
    header    = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr_crc  = zlib.crc32(b"IHDR" + ihdr_data)
    ihdr      = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
    idat_data = zlib.compress(b"\x00\xff\xff\xff")
    idat_crc  = zlib.crc32(b"IDAT" + idat_data)
    idat      = struct.pack(">I", len(idat_data)) + b"IDAT" + idat_data + struct.pack(">I", idat_crc)
    iend_crc  = zlib.crc32(b"IEND")
    iend      = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
    return header + ihdr + idat + iend


TEST_PNG_B64 = base64.b64encode(make_1x1_png()).decode()

_PASS = 0
_FAIL = 0
_ERRORS: list[str] = []


def ok(name: str, cond: bool, extra: str = "") -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  PASS  {name}")
    else:
        _FAIL += 1
        msg = f"  FAIL  {name}" + (f" — {extra}" if extra else "")
        print(msg)
        _ERRORS.append(msg)


# ── tests ────────────────────────────────────────────────────────────────────

def run_all() -> None:
    client = server.app.test_client()

    # ── Basic GET endpoints ───────────────────────────────────────────────────
    print("\n[GET endpoints]")
    r = client.get("/health");            ok("GET /health",             r.status_code == 200)
    r = client.get("/settings");          ok("GET /settings",           r.status_code == 200)
    r = client.get("/ollama/models");     ok("GET /ollama/models",      r.status_code == 200)
    r = client.get("/lmstudio/models");   ok("GET /lmstudio/models",    r.status_code == 200)
    r = client.get("/project/list");      ok("GET /project/list",       r.status_code == 200)
    r = client.get("/project/path");      ok("GET /project/path",       r.status_code == 200)
    r = client.get("/generate/gltf/shapes"); ok("GET /generate/gltf/shapes", r.status_code == 200)
    r = client.get("/instructions");      ok("GET /instructions",       r.status_code == 200)
    r = client.get("/agent/stats");       ok("GET /agent/stats",        r.status_code == 200)
    r = client.get("/convert/formats");   ok("GET /convert/formats",    r.status_code == 200)
    r = client.get("/bot/status");        ok("GET /bot/status",         r.status_code == 200)
    r = client.get("/agent/training_data"); ok("GET /agent/training_data", r.status_code == 200)
    r = client.get("/remote/status");     ok("GET /remote/status",      r.status_code == 200)
    r = client.get("/ping");              ok("GET /ping",               r.status_code == 200)

    # ── /settings POST ───────────────────────────────────────────────────────
    print("\n[POST /settings]")
    r = client.post("/settings", json={"ollama_url": "http://localhost:11434"})
    ok("POST /settings (save ollama_url)", r.status_code == 200)

    # ── /execute ─────────────────────────────────────────────────────────────
    print("\n[POST /execute]")
    r = client.post("/execute", json={"code": "print(2 + 2)", "language": "python"})
    d = r.get_json()
    ok("POST /execute python",    r.status_code == 200 and d.get("success"))
    ok("POST /execute python out", (d or {}).get("output", "").strip() == "4")

    r = client.post("/execute", json={"code": "console.log(6 * 7)", "language": "javascript"})
    d = r.get_json()
    ok("POST /execute js",         r.status_code == 200 and d.get("success"))
    ok("POST /execute js out",     (d or {}).get("output", "").strip() == "42")

    # ── /generate/gltf ───────────────────────────────────────────────────────
    print("\n[POST /generate/gltf]")
    for shape in ["cube", "sphere", "cylinder", "cone", "torus", "plane"]:
        r = client.post("/generate/gltf", json={"shape": shape})
        d = r.get_json()
        ok(f"POST /generate/gltf shape={shape}", r.status_code == 200 and "meshes" in (d or {}))

    # ── /agent/log (full format) ──────────────────────────────────────────────
    print("\n[POST /agent/log — full format]")
    record = {
        "timestamp":   "2026-01-01T00:00:00Z",
        "action_type": "test_action",
        "input":       {"query": "hello"},
        "output":      {"result": "world"},
        "success":     True,
        "duration_ms": 42,
        "metadata":    {},
    }
    r = client.post("/agent/log", json=record)
    ok("POST /agent/log (full format)", r.status_code == 200 and r.get_json().get("ok"))

    # ── /agent/log_action alias ───────────────────────────────────────────────
    print("\n[POST /agent/log_action — short format alias]")
    r = client.post("/agent/log_action", json={"action": "gltf_generated", "details": '{"shape":"cube"}'})
    ok("POST /agent/log_action alias",  r.status_code == 200)
    ok("POST /agent/log_action ok=True", r.get_json().get("ok") is True)

    # Also verify short-form via /agent/log route
    r = client.post("/agent/log", json={"action": "short_form_test", "details": "{}"})
    ok("POST /agent/log short form", r.status_code == 200 and r.get_json().get("ok"))

    # ── /convert/image ───────────────────────────────────────────────────────
    print("\n[POST /convert/image]")
    for fmt in ("jpeg", "webp", "png"):
        r = client.post("/convert/image", json={"image_base64": TEST_PNG_B64, "to_format": fmt})
        d = r.get_json() or {}
        ok(f"POST /convert/image → {fmt}",
           r.status_code == 200 and d.get("success") and "result_base64" in d)

    # Bad format
    r = client.post("/convert/image", json={"image_base64": TEST_PNG_B64, "to_format": "xyz"})
    ok("POST /convert/image bad format → 400", r.status_code == 400)

    # Missing body
    r = client.post("/convert/image", json={})
    ok("POST /convert/image no image → 400", r.status_code == 400)

    # ── /project/save and /project/zip ───────────────────────────────────────
    print("\n[POST /project/save & zip]")
    r = client.post("/project/save", json={
        "content":  "<h1>Test</h1>",
        "filename": "index.html",
        "name":     "test_project",
    })
    d = r.get_json()
    ok("POST /project/save",         r.status_code == 200 and d.get("success"))
    pid = (d or {}).get("project_id")
    ok("POST /project/save has project_id", bool(pid))

    if pid:
        r2 = client.get(f"/project/zip/{pid}")
        ok("GET /project/zip/<id>", r2.status_code == 200 and "zip" in r2.content_type)
        r3 = client.delete(f"/project/delete/{pid}")
        ok("DELETE /project/delete/<id>", r3.status_code == 200)

    # ── /instructions POST ────────────────────────────────────────────────────
    print("\n[POST /instructions]")
    r = client.post("/instructions", json={"system_prompt": "Ты умный ИИ-ассистент."})
    ok("POST /instructions (save system_prompt)", r.status_code == 200)

    # ── /check ────────────────────────────────────────────────────────────────
    print("\n[POST /check]")
    r = client.post("/check", json={"code": "x = 1\nprint(x)", "language": "python", "model": ""})
    ok("POST /check python", r.status_code == 200)

    # ── /bot/test ─────────────────────────────────────────────────────────────
    print("\n[POST /bot/test]")
    r = client.post("/bot/test", json={})
    ok("POST /bot/test (no token → ok=False)", r.status_code == 200 and not r.get_json().get("ok"))

    # ── _is_chrome_extension_request (internal helper) ────────────────────────
    print("\n[_is_chrome_extension_request helper]")
    ok("ext detect — chrome extension",  server._is_chrome_extension_request("create a chrome extension"))
    ok("ext detect — расширение chrome", server._is_chrome_extension_request("расширение chrome для поиска"))
    ok("ext detect — manifest.json",     server._is_chrome_extension_request("создай manifest.json"))
    ok("ext detect — false positive",    not server._is_chrome_extension_request("create a website about weather"))

    # ── Chat slash command routing (offline) ──────────────────────────────────
    print("\n[GET / — serves index.html]")
    r = client.get("/")
    ok("GET / returns HTML", r.status_code == 200 and b"<!DOCTYPE" in r.data)

    # ── Navigator PWA ─────────────────────────────────────────────────────────
    print("\n[GET /navigator/]")
    r = client.get("/navigator/")
    ok("GET /navigator/ serves navigator HTML", r.status_code == 200)

    # ── Ollama graceful failure (no Ollama running) ───────────────────────────
    print("\n[Ollama graceful failures]")
    r = client.post("/ollama/ask", json={"model": "test", "prompt": "hello"})
    d = r.get_json() or {}
    ok("POST /ollama/ask offline → success=False", not d.get("success"))

    # SSE endpoints — just check they stream an error event, not crash
    r = client.post("/chat/stream", json={"message": "hello"})
    ok("POST /chat/stream (no model) → 200", r.status_code == 200)

    r = client.post("/generate/auto/stream", json={"prompt": "hello", "language": "python"})
    ok("POST /generate/auto/stream (no model) → 200", r.status_code == 200)


# ── main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  DRGR VM — Server endpoint test suite")
    print("=" * 60)
    run_all()
    print("\n" + "=" * 60)
    total = _PASS + _FAIL
    print(f"  Results: {_PASS}/{total} passed, {_FAIL} failed")
    if _ERRORS:
        print("\n  Failed tests:")
        for e in _ERRORS:
            print(" ", e)
    print("=" * 60)
    sys.exit(0 if _FAIL == 0 else 1)
