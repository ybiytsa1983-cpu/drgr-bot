"""
DRGR Psycho-Platform — FER (Facial Emotion Recognition) Pipeline Config.

Конфигурация моделей, порогов и параметров для модуля видеоанализа.
Используется как backend-конфиг (Python + PyTorch/TF) и как справочник
для фронтенда (WebRTC-параметры).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

# ═══════════════════════════════════════════════════════════════════════════
#  Список эмоций (соответствует стандартным FER-датасетам)
# ═══════════════════════════════════════════════════════════════════════════
EMOTIONS: List[str] = [
    "neutral",
    "joy",
    "sadness",
    "anger",
    "fear",
    "surprise",
    "disgust",
    "contempt",
]

# Маппинг эмоций → психоэмоциональные метрики
EMOTION_TO_VALENCE: Dict[str, float] = {
    "joy":      +0.8,
    "surprise": +0.2,
    "neutral":   0.0,
    "contempt": -0.3,
    "sadness":  -0.6,
    "fear":     -0.7,
    "anger":    -0.5,
    "disgust":  -0.6,
}

EMOTION_TO_AROUSAL: Dict[str, float] = {
    "neutral":   0.1,
    "sadness":   0.2,
    "contempt":  0.3,
    "disgust":   0.4,
    "joy":       0.6,
    "anger":     0.8,
    "fear":      0.8,
    "surprise":  0.9,
}


# ═══════════════════════════════════════════════════════════════════════════
#  Конфигурация FER-pipeline
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class FERConfig:
    """Параметры FER-pipeline."""

    # --- Детектор лиц ---
    face_detector: str = "retinaface"          # retinaface | mtcnn | mediapipe
    face_min_confidence: float = 0.85          # мин. уверенность детектора

    # --- FER-модель ---
    fer_model: str = "vit-face-expression"     # HF model id или локальный путь
    fer_backend: str = "pytorch"               # pytorch | tensorflow | onnx
    fer_input_size: int = 224                  # размер входа модели (px)

    # --- Временное сглаживание ---
    smoothing_window: int = 5                  # кадров для скользящего среднего
    spike_threshold: float = 0.6               # порог «всплеска» эмоции (0-1)

    # --- WebRTC / Frontend ---
    capture_fps: int = 5                       # кадров/сек отправляемых на backend
    max_frame_queue: int = 30                  # макс. очередь кадров

    # --- Интерпретация ---
    stress_emotions: List[str] = field(
        default_factory=lambda: ["anger", "fear", "sadness", "disgust"]
    )
    stress_weight_map: Dict[str, float] = field(
        default_factory=lambda: {
            "anger": 0.9,
            "fear": 0.85,
            "sadness": 0.7,
            "disgust": 0.5,
        }
    )
    stress_high_threshold: float = 0.65        # > — «повышенный стресс»
    stress_moderate_threshold: float = 0.35    # > — «умеренный»
    # ниже — «низкий»


# ═══════════════════════════════════════════════════════════════════════════
#  Конфигурация Age-estimation
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class AgeEstimationConfig:
    """Параметры модуля оценки возраста (21+ gate)."""

    model: str = "nateraw/vit-age-classifier"  # HF model id или локальный путь
    backend: str = "pytorch"
    input_size: int = 224

    # Минимальный возраст для доступа
    min_age: int = 21

    # Доверительный интервал (±years)
    confidence_margin: float = 3.0

    # Если нижняя граница (predicted - margin) >= min_age → пропускаем
    # Иначе → отказ / запрос документа
    fallback_action: str = "deny"              # deny | request_document


# ═══════════════════════════════════════════════════════════════════════════
#  Дефолтные конфиги (singleton)
# ═══════════════════════════════════════════════════════════════════════════
DEFAULT_FER_CONFIG = FERConfig()
DEFAULT_AGE_CONFIG = AgeEstimationConfig()
