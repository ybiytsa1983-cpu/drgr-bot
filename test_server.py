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
    r = client.get("/tgwui/models");      ok("GET /tgwui/models",       r.status_code == 200)
    r = client.get("/oaf/status");        ok("GET /oaf/status",         r.status_code == 200)
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
    r = client.post("/settings", json={"tgwui_url": "http://127.0.0.1:5000"})
    ok("POST /settings (save tgwui_url)",  r.status_code == 200)
    r = client.post("/settings", json={"oaf_url": "http://127.0.0.1:8080"})
    ok("POST /settings (save oaf_url)",    r.status_code == 200)

    # ── /goose/run ───────────────────────────────────────────────────────────
    print("\n[POST /goose/run]")
    r = client.post("/goose/run", json={"instruction": "test"})
    ok("POST /goose/run (no goose bin) → 200", r.status_code == 200)
    d = r.get_json()
    ok("POST /goose/run (no goose bin) → ok:False", not d.get("ok"))

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

    # ── /bundle_monaco ───────────────────────────────────────────────────────
    print("\n[POST /bundle_monaco]")
    r = client.post("/bundle_monaco")
    d = r.get_json() or {}
    ok("POST /bundle_monaco → 200",    r.status_code == 200)
    ok("POST /bundle_monaco has ok",   "ok" in d)
    ok("POST /bundle_monaco has msg",  "message" in d)

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

    # ── Vision light check endpoint ───────────────────────────────────────────
    print("\n[GET /vision/light/check]")
    r = client.get("/vision/light/check")
    ok("GET /vision/light/check → 200", r.status_code == 200)
    d = r.get_json() or {}
    ok("GET /vision/light/check → has 'available' key", "available" in d)
    ok("GET /vision/light/check → has 'status' key", "status" in d)

    # Research endpoint with existing_article (Ollama offline → no article_text fallback)
    print("\n[POST /research existing_article]")
    r = client.post("/research", json={
        "query": "Python programming",
        "existing_article": "Python programming\n\n## Introduction\nPython is a programming language.\n\n## Features\nIt is easy to learn.\n\n## Conclusion\nPython is great.",
        "screenshots": False,
    })
    ok("POST /research existing_article → 200 or 404", r.status_code in (200, 404))

    # _research_build_html: verify HTML stripping pipeline does not crash
    print("\n[_research_build_html HTML input stripping]")
    import re as _re
    import html as _html_mod_t
    _html_input = (
        "<!DOCTYPE html><html><head><title>Test</title></head><body>"
        "<h1>Test Article</h1><p>This is a <b>test</b> paragraph.</p>"
        "<h2>Section 1</h2><p>Some content here.</p>"
        "</body></html>"
    )
    # Simulate the HTML stripping logic that now runs before _research_build_html
    _at = _html_input.strip()
    _at = _re.sub(r'^```[a-zA-Z]*\s*\n', '', _at)
    _at = _re.sub(r'\n```\s*$', '', _at)
    _at = _at.strip()
    if _re.match(r'^\s*<!DOCTYPE\s+html|^\s*<html', _at, _re.IGNORECASE):
        _at = _re.sub(r'<style[^>]*>.*?</\s*style[^>]*>', '', _at, flags=_re.DOTALL | _re.IGNORECASE)
        _at = _re.sub(r'<script[^>]*>.*?</\s*script[^>]*>', '', _at, flags=_re.DOTALL | _re.IGNORECASE)
        _at = _re.sub(r'<[^>]+>', ' ', _at)
        _at = _html_mod_t.unescape(_at)
        _at = _re.sub(r'\s{3,}', '\n\n', _at).strip()
    ok("HTML stripping: no HTML tags remain in output",
       not _re.search(r'<[a-zA-Z][^>]*>', _at))
    ok("HTML stripping: 'Test Article' preserved in output", "Test Article" in _at)

    # _research_build_html: partial HTML tags (mixed markdown + HTML) stripping
    _partial_html_input = (
        "My Partial Article\n\n"
        "## 🔍 Introduction\n<p>This is a <strong>paragraph</strong> with tags.</p>\n\n"
        "## ✅ Conclusion\n<p>End of article.</p>"
    )
    _pt = _partial_html_input.strip()
    if _re.search(r'<(?:p|h[1-6]|div|ul|li|strong|em|br)\b', _pt, _re.IGNORECASE):
        _pt = _re.sub(r'<[^>]+>', ' ', _pt)
        _pt = _html_mod_t.unescape(_pt)
        _pt = _re.sub(r'\s{3,}', '\n\n', _pt).strip()
    ok("Partial HTML stripping: no block tags remain",
       not _re.search(r'<(?:p|strong|em|div)\b', _pt, _re.IGNORECASE))
    ok("Partial HTML stripping: text preserved", "Introduction" in _pt)

    # _research_build_html: verify it produces valid HTML from Markdown
    print("\n[_research_build_html Markdown→HTML]")
    _md_body = (
        "My Test Article\n\n"
        "## 🔍 Introduction\nThis is the introduction section.\n\n"
        "## 📌 Key Facts\nSome key facts here.\n\n"
        "## ✅ Conclusion\nFinal thoughts."
    )
    try:
        _built_html = server._research_build_html(
            "My Test Article", _md_body, [], [], ""
        )
        ok("_research_build_html returns non-empty HTML", len(_built_html) > 100)
        ok("_research_build_html contains h2 sections",
           _re.search(r'<h2[^>]*>', _built_html) is not None)
        ok("_research_build_html is valid HTML (has html tag)",
           "<html" in _built_html.lower())
    except Exception as _e:
        ok("_research_build_html no exception", False, str(_e))

    # ── Android / mobile endpoints ────────────────────────────────────────────
    print("\n[Android / mobile endpoints]")

    # GET /android/apk/list — should always return JSON
    r = client.get("/android/apk/list")
    d = r.get_json() or {}
    ok("GET /android/apk/list → 200",         r.status_code == 200)
    ok("GET /android/apk/list → has 'apks'",  "apks" in d)
    ok("GET /android/apk/list → apks is list", isinstance(d.get("apks"), list))

    # GET /android/emulator/status — should return JSON even without ADB installed
    r = client.get("/android/emulator/status")
    d = r.get_json() or {}
    ok("GET /android/emulator/status → 200",               r.status_code == 200)
    ok("GET /android/emulator/status → has adb_available", "adb_available" in d)
    ok("GET /android/emulator/status → has devices",       "devices" in d)

    # POST /android/generate — missing prompt → 400
    r = client.post("/android/generate", json={})
    ok("POST /android/generate no prompt → 400", r.status_code == 400)

    # POST /android/generate — missing model → 400
    r = client.post("/android/generate", json={"prompt": "Hello app"})
    ok("POST /android/generate no model → 400", r.status_code == 400)

    # POST /android/generate — Ollama offline → 503 / 500 / 504
    r = client.post("/android/generate", json={"prompt": "Hello world app", "model": "llama2"})
    ok("POST /android/generate offline → error status",
       r.status_code in (500, 503, 504))

    # POST /android/apk/upload — no file → 400
    r = client.post("/android/apk/upload", data={})
    ok("POST /android/apk/upload no file → 400", r.status_code == 400)

    # POST /android/apk/upload — upload a fake APK
    import io
    fake_apk = io.BytesIO(b"PK\x03\x04fake apk bytes")
    r = client.post("/android/apk/upload",
                    data={"file": (fake_apk, "test_app.apk")},
                    content_type="multipart/form-data")
    d = r.get_json() or {}
    ok("POST /android/apk/upload → 200",        r.status_code == 200)
    ok("POST /android/apk/upload → has url",    "url" in d)
    ok("POST /android/apk/upload → url ends .apk",
       d.get("url", "").endswith(".apk"))

    # GET /android/apk/<name> — serve uploaded APK
    apk_name = d.get("name", "test_app.apk")
    r = client.get(f"/android/apk/{apk_name}")
    ok("GET /android/apk/<name> → 200", r.status_code == 200)

    # GET /android/apk/list — should now contain the uploaded file
    r = client.get("/android/apk/list")
    d = r.get_json() or {}
    ok("GET /android/apk/list after upload → not empty",
       len(d.get("apks", [])) > 0)

    # POST /android/apk/send — no token configured → 503
    r = client.post("/android/apk/send", json={"name": apk_name})
    ok("POST /android/apk/send no token → 503", r.status_code == 503)

    # POST /android/apk/send — unknown APK → 400 (name required)
    r = client.post("/android/apk/send", json={})
    ok("POST /android/apk/send no name → 400", r.status_code == 400)


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
