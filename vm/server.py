"""
Психокоррекция -- сервер платформы психоэмоциональной оценки и коррекции.

Функции:
  • FER-анализ (анализ лицевой экспрессии)
  • Анализ зрачков (дилатация, анизокория)
  • Оценка возраста по глазам
  • Совокупная оценка стресса
  • База знаний (источники, методики, рекомендации)
  • Обнаружение Ollama / LM Studio для AI
"""
from __future__ import annotations

import base64 as b64mod
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from flask import Flask, jsonify, render_template, request

# ---------------------------------------------------------------------------
#  Пути / директории
# ---------------------------------------------------------------------------
_BASE_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _BASE_DIR.parent

# Ensure psycho_platform is importable from vm/server.py
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

# ---------------------------------------------------------------------------
#  Psycho-platform modules (lazy-loaded singletons)
# ---------------------------------------------------------------------------
_camera_mgr = None
_knowledge_base = None
_pupil_analyzer = None
_eye_age_estimator = None
_comprehensive_engine = None

def _get_camera():
    global _camera_mgr
    if _camera_mgr is None:
        try:
            from psycho_platform.camera import CameraManager
            _camera_mgr = CameraManager()
        except Exception as exc:
            logger.warning("Camera module not available: %s", exc)
    return _camera_mgr

def _get_kb():
    global _knowledge_base
    if _knowledge_base is None:
        try:
            from psycho_platform.knowledge_base import KnowledgeBase
            _knowledge_base = KnowledgeBase()
        except Exception as exc:
            logger.warning("Knowledge base not available: %s", exc)
    return _knowledge_base

def _get_pupil_analyzer():
    global _pupil_analyzer
    if _pupil_analyzer is None:
        try:
            from psycho_platform.pupil_analyzer import PupilAnalyzer
            _pupil_analyzer = PupilAnalyzer()
        except Exception as exc:
            logger.warning("Pupil analyzer not available: %s", exc)
    return _pupil_analyzer

def _get_eye_age_estimator():
    global _eye_age_estimator
    if _eye_age_estimator is None:
        try:
            from psycho_platform.eye_age_estimator import EyeAgeEstimator
            _eye_age_estimator = EyeAgeEstimator()
        except Exception as exc:
            logger.warning("Eye age estimator not available: %s", exc)
    return _eye_age_estimator

def _get_comprehensive_engine():
    global _comprehensive_engine
    if _comprehensive_engine is None:
        try:
            from psycho_platform.comprehensive_assessment import ComprehensiveAssessment
            _comprehensive_engine = ComprehensiveAssessment()
        except Exception as exc:
            logger.warning("Comprehensive assessment not available: %s", exc)
    return _comprehensive_engine

# ---------------------------------------------------------------------------
#  Логирование
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("psycho-server")

# ---------------------------------------------------------------------------
#  Flask
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder="static", template_folder="static")

# ---------------------------------------------------------------------------
#  CORS (для localhost фронтенда)
# ---------------------------------------------------------------------------
def _add_cors(resp):
    origin = request.headers.get("Origin", "")
    if origin.startswith("chrome-extension://") or "localhost" in origin or "127.0.0.1" in origin:
        resp.headers["Access-Control-Allow-Origin"] = origin
    else:
        resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return resp

app.after_request(_add_cors)

@app.before_request
def _handle_options():
    """Return 204 for any OPTIONS preflight so undefined paths get 404 (not 405)."""
    if request.method == "OPTIONS":
        return "", 204

@app.route("/favicon.ico")
def favicon():
    return "", 204

# ---------------------------------------------------------------------------
#  Ollama / LM Studio -- обнаружение
# ---------------------------------------------------------------------------
# Предпочтительный порт Ollama (из .env OLLAMA_PORT или 11435 по умолчанию)
try:
    _OLLAMA_PREFERRED_PORT = int(os.environ.get("OLLAMA_PORT", "11435"))
except (ValueError, TypeError):
    logger.warning("Invalid OLLAMA_PORT value, using default 11435")
    _OLLAMA_PREFERRED_PORT = 11435
_OLLAMA_PROBE_PORTS = (
    _OLLAMA_PREFERRED_PORT,
    *(p for p in (11434, 11435, 11436, 11437) if p != _OLLAMA_PREFERRED_PORT),
)
_LMSTUDIO_PROBE_PORTS = (1234, 1235)

def _probe_service(host: str, port: int, path: str = "/", timeout: float = 2.0) -> bool:
    try:
        r = requests.get(f"http://{host}:{port}{path}", timeout=timeout)
        return r.status_code < 500
    except Exception:
        return False

def _find_ollama() -> Optional[str]:
    for p in _OLLAMA_PROBE_PORTS:
        if _probe_service("127.0.0.1", p, "/api/tags"):
            return f"http://127.0.0.1:{p}"
    return None

def _find_lmstudio() -> Optional[str]:
    for p in _LMSTUDIO_PROBE_PORTS:
        if _probe_service("127.0.0.1", p, "/v1/models"):
            return f"http://127.0.0.1:{p}"
    return None

def _llm_models() -> Dict[str, List[str]]:
    """Получить список доступных моделей из Ollama и LM Studio."""
    result: Dict[str, List[str]] = {"ollama": [], "lmstudio": []}
    base = _find_ollama()
    if base:
        try:
            r = requests.get(f"{base}/api/tags", timeout=3)
            for m in r.json().get("models", []):
                result["ollama"].append(m.get("name", "unknown"))
        except Exception:
            pass
    base = _find_lmstudio()
    if base:
        try:
            r = requests.get(f"{base}/v1/models", timeout=3)
            for m in r.json().get("data", []):
                result["lmstudio"].append(m.get("id", "unknown"))
        except Exception:
            pass
    return result

# ---------------------------------------------------------------------------
#  Health / Diagnostics
# ---------------------------------------------------------------------------
def _health() -> Dict[str, Any]:
    ollama_url = _find_ollama()
    lmstudio_url = _find_lmstudio()
    models = _llm_models()
    return {
        "ollama": {"available": bool(ollama_url), "url": ollama_url, "models": models["ollama"]},
        "lmstudio": {"available": bool(lmstudio_url), "url": lmstudio_url, "models": models["lmstudio"]},
    }

# ===========================================================================
#  ROUTES
# ===========================================================================

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/health", methods=["GET"])
def health():
    return jsonify(_health())

# ---------------------------------------------------------------------------
#  Ollama status endpoint
# ---------------------------------------------------------------------------
@app.route("/api/ollama/status", methods=["GET"])
def ollama_status():
    """Статус подключения к Ollama (порт 11435 приоритетный)."""
    base = _find_ollama()
    models_data = _llm_models()
    return jsonify({
        "available": bool(base),
        "url": base,
        "preferred_port": _OLLAMA_PREFERRED_PORT,
        "probed_ports": list(_OLLAMA_PROBE_PORTS),
        "models": models_data.get("ollama", []),
    })

# ---------------------------------------------------------------------------
#  Camera API
# ---------------------------------------------------------------------------
@app.route("/api/camera/status", methods=["GET"])
def camera_status():
    """Статус камеры."""
    cam = _get_camera()
    if cam is None:
        return jsonify({"available": False, "error": "Camera module not loaded"})
    return jsonify(cam.get_status())

@app.route("/api/camera/capture", methods=["POST"])
def camera_capture():
    """Захватить кадр с камеры (base64 JPEG)."""
    cam = _get_camera()
    if cam is None:
        return jsonify({"error": "Camera module not loaded"}), 500
    frame_b64 = cam.capture_frame_b64()
    if frame_b64 is None:
        return jsonify({"error": "Failed to capture frame"}), 500
    return jsonify({"image": frame_b64, "format": "jpeg"})

@app.route("/api/camera/config", methods=["GET"])
def camera_config_get():
    """Получить текущую конфигурацию камеры."""
    cam = _get_camera()
    if cam is None:
        return jsonify({"error": "Camera module not loaded"}), 500
    cfg = cam.config
    return jsonify({
        "index": cfg.index,
        "width": cfg.width,
        "height": cfg.height,
        "fps": cfg.fps,
    })

@app.route("/api/camera/config", methods=["POST"])
def camera_config_set():
    """Обновить конфигурацию камеры."""
    cam = _get_camera()
    if cam is None:
        return jsonify({"error": "Camera module not loaded"}), 500
    data = request.json or {}
    cfg = cam.update_config(
        index=data.get("index"),
        width=data.get("width"),
        height=data.get("height"),
        fps=data.get("fps"),
    )
    return jsonify({
        "ok": True,
        "index": cfg.index,
        "width": cfg.width,
        "height": cfg.height,
        "fps": cfg.fps,
    })

# ---------------------------------------------------------------------------
#  Knowledge Base API
# ---------------------------------------------------------------------------
@app.route("/api/kb/stats", methods=["GET"])
def kb_stats():
    """Статистика базы знаний."""
    kb = _get_kb()
    if kb is None:
        return jsonify({"error": "Knowledge base not loaded"}), 500
    return jsonify(kb.get_stats())

@app.route("/api/kb/sources", methods=["GET"])
def kb_sources():
    """Список источников (фильтр: ?type=article&tags=emotion_recognition)."""
    kb = _get_kb()
    if kb is None:
        return jsonify({"error": "Knowledge base not loaded"}), 500
    type_filter = request.args.get("type")
    tags_param = request.args.get("tags")
    tags = tags_param.split(",") if tags_param else None
    limit = min(int(request.args.get("limit", "100")), 500)
    return jsonify(kb.get_sources(type=type_filter, tags=tags, limit=limit))

@app.route("/api/kb/sources", methods=["POST"])
def kb_add_source():
    """Добавить источник."""
    kb = _get_kb()
    if kb is None:
        return jsonify({"error": "Knowledge base not loaded"}), 500
    data = request.json or {}
    required = ("type", "authors", "title")
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"Missing required field: {field}"}), 400
    try:
        source_id = kb.add_source(
            type=data["type"],
            authors=data["authors"],
            title=data["title"],
            year=data.get("year"),
            url=data.get("url"),
            doi=data.get("doi"),
            tags=data.get("tags"),
            notes=data.get("notes"),
        )
        return jsonify({"ok": True, "id": source_id})
    except Exception:
        logger.exception("Failed to add source")
        return jsonify({"error": "Failed to add source"}), 400

@app.route("/api/kb/methods", methods=["GET"])
def kb_methods():
    """Список методик (фильтр: ?state=stress&level=high&applicable=1)."""
    kb = _get_kb()
    if kb is None:
        return jsonify({"error": "Knowledge base not loaded"}), 500
    level = request.args.get("level")
    state = request.args.get("state")
    applicable = request.args.get("applicable") == "1"
    limit = min(int(request.args.get("limit", "100")), 500)
    return jsonify(kb.get_methods(
        evidence_level=level,
        target_state=state,
        applicable_only=applicable,
        limit=limit,
    ))

@app.route("/api/kb/methods", methods=["POST"])
def kb_add_method():
    """Добавить методику."""
    kb = _get_kb()
    if kb is None:
        return jsonify({"error": "Knowledge base not loaded"}), 500
    data = request.json or {}
    if not data.get("title"):
        return jsonify({"error": "Missing required field: title"}), 400
    try:
        method_id = kb.add_method(
            title=data["title"],
            description=data.get("description"),
            evidence_level=data.get("evidence_level", "medium"),
            applicable_in_app=bool(data.get("applicable_in_app", False)),
            target_states=data.get("target_states"),
            instructions=data.get("instructions"),
            duration_min=data.get("duration_min"),
            source_ids=data.get("source_ids"),
        )
        return jsonify({"ok": True, "id": method_id})
    except Exception:
        logger.exception("Failed to add method")
        return jsonify({"error": "Failed to add method"}), 400

@app.route("/api/kb/recommend", methods=["GET"])
def kb_recommend():
    """Рекомендации методик по состоянию: ?state=stress&limit=5."""
    kb = _get_kb()
    if kb is None:
        return jsonify({"error": "Knowledge base not loaded"}), 500
    state = request.args.get("state", "stress")
    limit = min(int(request.args.get("limit", "5")), 20)
    return jsonify(kb.recommend_methods(state=state, limit=limit))

@app.route("/api/kb/seed", methods=["POST"])
def kb_seed():
    """Заполнить базу знаний начальными данными."""
    try:
        from psycho_platform.seed_dataset import seed_all
        result = seed_all()
        return jsonify({"ok": True, **result})
    except Exception:
        logger.exception("Failed to seed knowledge base")
        return jsonify({"error": "Failed to seed knowledge base"}), 500

@app.route("/api/kb/principles", methods=["GET"])
def kb_principles():
    """Принципы работы модулей ВМ (из seed_dataset)."""
    try:
        from psycho_platform.seed_dataset import VM_MODULE_PRINCIPLES
        return jsonify(VM_MODULE_PRINCIPLES)
    except Exception:
        logger.exception("Failed to load VM module principles")
        return jsonify({"error": "Failed to load VM module principles"}), 500

# ---------------------------------------------------------------------------
#  Pupil Analysis API
# ---------------------------------------------------------------------------
@app.route("/api/pupil/status", methods=["GET"])
def pupil_status():
    """Статус модуля анализа зрачков."""
    analyzer = _get_pupil_analyzer()
    if analyzer is None:
        return jsonify({"available": False, "error": "Pupil analyzer not loaded"})
    return jsonify({
        "available": True,
        "config": {
            "eye_detector": analyzer.config.eye_detector,
            "baseline_ratio": analyzer.config.baseline_ratio,
            "dilation_high_threshold": analyzer.config.dilation_high_threshold,
            "anisocoria_threshold": analyzer.config.anisocoria_threshold,
            "smoothing_window": analyzer.config.smoothing_window,
        },
    })

@app.route("/api/pupil/analyze", methods=["POST"])
def pupil_analyze():
    """
    Анализ зрачков из изображения (base64 или камера).

    Body JSON:
      {"source": "camera"} — захват с камеры
      {"image": "<base64>"} — из base64 изображения
    """
    analyzer = _get_pupil_analyzer()
    if analyzer is None:
        return jsonify({"error": "Pupil analyzer not loaded"}), 500

    data = request.json or {}
    source = data.get("source", "")

    if source == "camera":
        cam = _get_camera()
        if cam is None:
            return jsonify({"error": "Camera not available"}), 500
        ok, frame = cam.capture_frame()
        if not ok or frame is None:
            return jsonify({"error": "Failed to capture frame"}), 500
        result = analyzer.analyze_frame(frame)
    elif data.get("image"):
        try:
            img_bytes = b64mod.b64decode(data["image"])
        except Exception:
            return jsonify({"error": "Invalid base64 image"}), 400
        result = analyzer.analyze_image_bytes(img_bytes)
    else:
        return jsonify({"error": "Provide 'source':'camera' or 'image':'<base64>'"}), 400

    from psycho_platform.pupil_analyzer import PupilAnalyzer
    return jsonify(PupilAnalyzer.result_to_dict(result))

@app.route("/api/pupil/reset", methods=["POST"])
def pupil_reset():
    """Сброс истории сглаживания зрачков (для новой сессии)."""
    analyzer = _get_pupil_analyzer()
    if analyzer is None:
        return jsonify({"error": "Pupil analyzer not loaded"}), 500
    analyzer.reset()
    return jsonify({"ok": True, "message": "Pupil history reset"})

# ---------------------------------------------------------------------------
#  Eye-Based Age Estimation API
# ---------------------------------------------------------------------------
@app.route("/api/eye-age/status", methods=["GET"])
def eye_age_status():
    """Статус модуля оценки возраста по глазам."""
    estimator = _get_eye_age_estimator()
    if estimator is None:
        return jsonify({"available": False, "error": "Eye age estimator not loaded"})
    return jsonify({
        "available": True,
        "config": {
            "wrinkle_weight": estimator.config.wrinkle_weight,
            "bags_weight": estimator.config.bags_weight,
            "sclera_weight": estimator.config.sclera_weight,
            "iris_weight": estimator.config.iris_weight,
            "ptosis_weight": estimator.config.ptosis_weight,
            "age_range": f"{estimator.config.age_min}-{estimator.config.age_max}",
            "confidence_margin": estimator.config.confidence_margin,
        },
    })

@app.route("/api/eye-age/estimate", methods=["POST"])
def eye_age_estimate():
    """
    Оценка возраста по глазам из изображения.

    Body JSON:
      {"source": "camera"} — захват с камеры
      {"image": "<base64>"} — из base64 изображения
    """
    estimator = _get_eye_age_estimator()
    if estimator is None:
        return jsonify({"error": "Eye age estimator not loaded"}), 500

    data = request.json or {}
    source = data.get("source", "")

    if source == "camera":
        cam = _get_camera()
        if cam is None:
            return jsonify({"error": "Camera not available"}), 500
        ok, frame = cam.capture_frame()
        if not ok or frame is None:
            return jsonify({"error": "Failed to capture frame"}), 500
        result = estimator.estimate_from_frame(frame)
    elif data.get("image"):
        try:
            img_bytes = b64mod.b64decode(data["image"])
        except Exception:
            return jsonify({"error": "Invalid base64 image"}), 400
        result = estimator.estimate_from_bytes(img_bytes)
    else:
        return jsonify({"error": "Provide 'source':'camera' or 'image':'<base64>'"}), 400

    from psycho_platform.eye_age_estimator import EyeAgeEstimator
    return jsonify(EyeAgeEstimator.result_to_dict(result))

# ---------------------------------------------------------------------------
#  Comprehensive Assessment API
# ---------------------------------------------------------------------------
@app.route("/api/assessment/status", methods=["GET"])
def assessment_status():
    """Статус совокупной оценки."""
    engine = _get_comprehensive_engine()
    if engine is None:
        return jsonify({"available": False, "error": "Assessment engine not loaded"})
    return jsonify({
        "available": True,
        "modules": {
            "fer": True,
            "pupil": _get_pupil_analyzer() is not None,
            "eye_age": _get_eye_age_estimator() is not None,
            "camera": _get_camera() is not None,
            "knowledge_base": _get_kb() is not None,
        },
        "config": {
            "fer_stress_weight": engine.config.fer_stress_weight,
            "pupil_stress_weight": engine.config.pupil_stress_weight,
            "baseline_stress_weight": engine.config.baseline_stress_weight,
            "overall_stress_high": engine.config.overall_stress_high,
            "overall_stress_moderate": engine.config.overall_stress_moderate,
        },
    })

@app.route("/api/assessment/run", methods=["POST"])
def assessment_run():
    """
    Запустить совокупную оценку.

    Body JSON (все поля опциональны):
      {
        "source": "camera" | null,
        "image": "<base64>" | null,
        "fer": {"dominant_emotion": "anger", "stress_score": 0.8, ...},
        "skip_pupil": false,
        "skip_eye_age": false
      }
    """
    engine = _get_comprehensive_engine()
    if engine is None:
        return jsonify({"error": "Assessment engine not loaded"}), 500

    data = request.json or {}

    # Получить кадр (если нужен для pupil/eye_age)
    frame = None
    source = data.get("source", "")

    if source == "camera":
        cam = _get_camera()
        if cam is not None:
            ok, frame = cam.capture_frame()
            if not ok:
                frame = None
    elif data.get("image"):
        try:
            import numpy as np
            cv2_mod = None
            try:
                import cv2
                cv2_mod = cv2
            except ImportError:
                pass
            if cv2_mod is not None:
                img_bytes = b64mod.b64decode(data["image"])
                arr = np.frombuffer(img_bytes, dtype=np.uint8)
                frame = cv2_mod.imdecode(arr, cv2_mod.IMREAD_COLOR)
        except Exception:
            pass

    # --- Собираем данные от каждого модуля ---
    from psycho_platform.comprehensive_assessment import (
        FERInput, PupilInput, EyeAgeInput, FaceAgeInput,
        ComprehensiveAssessment,
    )

    # FER input (из запроса)
    fer_data = data.get("fer")
    fer_input = None
    if fer_data:
        fer_input = FERInput(
            dominant_emotion=fer_data.get("dominant_emotion", "neutral"),
            emotion_scores=fer_data.get("emotion_scores", {}),
            valence=fer_data.get("valence", 0.0),
            arousal=fer_data.get("arousal", 0.0),
            stress_score=fer_data.get("stress_score", 0.0),
            confidence=fer_data.get("confidence", 0.0),
        )

    # Pupil input (из кадра)
    pupil_input = None
    if not data.get("skip_pupil", False) and frame is not None:
        analyzer = _get_pupil_analyzer()
        if analyzer is not None:
            pupil_result = analyzer.analyze_frame(frame)
            pupil_input = PupilInput(
                avg_pupil_iris_ratio=pupil_result.avg_pupil_iris_ratio,
                dilation_level=pupil_result.dilation_level,
                inferred_state=pupil_result.inferred_state,
                anisocoria_detected=pupil_result.anisocoria_detected,
                anisocoria_diff=pupil_result.anisocoria_diff,
                state_confidence=pupil_result.state_confidence,
                warnings=pupil_result.warnings,
            )

    # Eye age input (из кадра)
    eye_age_input = None
    if not data.get("skip_eye_age", False) and frame is not None:
        estimator = _get_eye_age_estimator()
        if estimator is not None:
            eye_result = estimator.estimate_from_frame(frame)
            eye_age_input = EyeAgeInput(
                estimated_age=eye_result.estimated_age,
                composite_score=eye_result.composite_score,
                wrinkle_score=eye_result.wrinkle_score,
                bags_score=eye_result.bags_score,
                sclera_score=eye_result.sclera_score,
                iris_score=eye_result.iris_score,
                ptosis_score=eye_result.ptosis_score,
                confidence=eye_result.confidence,
                warnings=eye_result.warnings,
            )

    # Face age input (из запроса, опционально)
    face_age_data = data.get("face_age")
    face_age_input = None
    if face_age_data:
        face_age_input = FaceAgeInput(
            predicted_age=face_age_data.get("predicted_age", 0.0),
            confidence_margin=face_age_data.get("confidence_margin", 3.0),
            is_allowed=face_age_data.get("is_allowed", True),
        )

    # Запуск совокупной оценки
    result = engine.assess(
        fer=fer_input,
        pupil=pupil_input,
        eye_age=eye_age_input,
        face_age=face_age_input,
    )

    return jsonify(ComprehensiveAssessment.result_to_dict(result))

# ---------------------------------------------------------------------------
#  main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import socket

    _port = int(os.environ.get("DRGR_PORT", 5005))

    # Проверка порта
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("0.0.0.0", _port))
        sock.close()
    except OSError:
        logger.error("Порт %d уже занят! Попробуйте: DRGR_PORT=5006 python vm/server.py", _port)
        # Попробовать следующий порт
        for alt in range(_port + 1, _port + 10):
            try:
                sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock2.bind(("0.0.0.0", alt))
                sock2.close()
                logger.info("Используется альтернативный порт: %d", alt)
                _port = alt
                break
            except OSError:
                continue
        else:
            logger.error("Все порты %d-%d заняты. Завершение.", _port, _port + 9)
            sys.exit(1)

    logger.info("Психокоррекция -- сервер запущен на http://localhost:%d", _port)
    app.run(host="0.0.0.0", port=_port, debug=False)
