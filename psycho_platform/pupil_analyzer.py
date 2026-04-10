"""
DRGR Psycho-Platform — Pupil Analyzer.

Анализ зрачков для определения психоэмоционального состояния пациента.

Научная основа:
  • Расширение зрачков (мидриаз) — стресс, страх, когнитивная нагрузка,
    возбуждение, боль, некоторые вещества.
  • Сужение зрачков (миоз) — расслабление, сонливость,
    опиоиды, яркий свет.
  • Асимметрия зрачков (анизокория) — неврологические проблемы,
    травмы, медикаменты.
  • Pupillary Light Reflex (PLR) — скорость реакции на свет
    указывает на состояние автономной нервной системы.

Pipeline:
  1. Детекция лица (из FER-pipeline или MediaPipe).
  2. Выделение области глаз (eye landmarks).
  3. Сегментация зрачка (threshold + contour на ROI глаза).
  4. Измерение диаметра зрачка (в px) и ratio к iris.
  5. Интерпретация: dilation_ratio → состояние.

ВАЖНО: это НЕ медицинская диагностика. Результаты носят
рекомендательный характер.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("drgr-psycho.pupil")


# ═══════════════════════════════════════════════════════════════════════════
#  Конфигурация
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class PupilAnalysisConfig:
    """Параметры анализа зрачков."""

    # --- Детекция глаз ---
    eye_detector: str = "mediapipe"           # mediapipe | haarcascade | dlib
    min_eye_confidence: float = 0.7           # мин. уверенность детектора глаз

    # --- Сегментация зрачка ---
    pupil_threshold: int = 40                 # порог бинаризации для зрачка (0-255)
    pupil_blur_kernel: int = 7                # размер GaussianBlur kernel
    min_pupil_radius_px: int = 3              # мин. радиус зрачка (px)
    max_pupil_radius_px: int = 80             # макс. радиус зрачка (px)

    # --- Нормализация ---
    # Отношение зрачка к радужке (pupil/iris ratio)
    # Нормальный диапазон: 0.2 - 0.8
    baseline_ratio: float = 0.4               # нормальное соотношение в покое
    dilation_high_threshold: float = 0.65     # > = значительное расширение
    dilation_moderate_threshold: float = 0.5  # > = умеренное расширение
    constriction_threshold: float = 0.25      # < = значительное сужение

    # --- Анизокория ---
    anisocoria_threshold: float = 0.15        # разница ratio L/R > порога → анизокория

    # --- Временное сглаживание ---
    smoothing_window: int = 5                 # кадров для скользящего среднего
    min_frames_for_assessment: int = 10       # мин. кадров для надёжной оценки

    # --- Маппинг состояний ---
    dilation_states: Dict[str, str] = field(default_factory=lambda: {
        "high_dilation": "stress_or_arousal",
        "moderate_dilation": "cognitive_load",
        "normal": "calm",
        "constriction": "relaxation_or_fatigue",
    })


DEFAULT_PUPIL_CONFIG = PupilAnalysisConfig()


# ═══════════════════════════════════════════════════════════════════════════
#  Результат анализа
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class PupilMeasurement:
    """Результат измерения одного глаза."""

    eye_side: str                  # "left" | "right"
    pupil_diameter_px: float       # диаметр зрачка в пикселях
    iris_diameter_px: float        # диаметр радужки в пикселях
    pupil_iris_ratio: float        # pupil / iris (0.0 - 1.0)
    center_x: float                # центр зрачка (x)
    center_y: float                # центр зрачка (y)
    confidence: float              # уверенность измерения (0-1)


@dataclass
class PupilAnalysisResult:
    """Совокупный результат анализа зрачков."""

    left_eye: Optional[PupilMeasurement] = None
    right_eye: Optional[PupilMeasurement] = None

    # Агрегированные метрики
    avg_pupil_iris_ratio: float = 0.0     # среднее pupil/iris обоих глаз
    anisocoria_detected: bool = False      # разница зрачков L/R > порога
    anisocoria_diff: float = 0.0           # |left_ratio - right_ratio|

    # Интерпретация
    dilation_level: str = "normal"         # high_dilation | moderate_dilation | normal | constriction
    inferred_state: str = "calm"           # stress_or_arousal | cognitive_load | calm | relaxation_or_fatigue
    state_confidence: float = 0.0          # 0-1

    # Предупреждения
    warnings: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
#  Анализатор зрачков
# ═══════════════════════════════════════════════════════════════════════════

class PupilAnalyzer:
    """
    Анализ зрачков для определения психоэмоционального состояния.

    Использование:
        analyzer = PupilAnalyzer()
        result = analyzer.analyze_frame(frame_numpy)
        print(result.inferred_state)  # "stress_or_arousal"
    """

    def __init__(self, config: Optional[PupilAnalysisConfig] = None):
        self.config = config or DEFAULT_PUPIL_CONFIG
        self._cv2 = None
        self._history: List[float] = []  # история ratio для сглаживания

    def _ensure_cv2(self) -> bool:
        """Lazy-импорт OpenCV."""
        if self._cv2 is not None:
            return True
        try:
            import cv2
            self._cv2 = cv2
            return True
        except ImportError:
            logger.warning("OpenCV not installed for pupil analysis")
            return False

    # ──────────────────────────────────────────────────────────────────
    #  Основной метод: анализ кадра
    # ──────────────────────────────────────────────────────────────────
    def analyze_frame(self, frame) -> PupilAnalysisResult:
        """
        Анализ зрачков на одном кадре.

        Parameters
        ----------
        frame : numpy.ndarray
            BGR-кадр с камеры (OpenCV формат).

        Returns
        -------
        PupilAnalysisResult
        """
        if not self._ensure_cv2():
            return PupilAnalysisResult(
                warnings=["OpenCV not available"]
            )

        cv2 = self._cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Детекция глаз
        left_roi, right_roi = self._detect_eye_regions(frame, gray)

        left_measurement = None
        right_measurement = None

        if left_roi is not None:
            left_measurement = self._measure_pupil(left_roi, "left")
        if right_roi is not None:
            right_measurement = self._measure_pupil(right_roi, "right")

        return self._build_result(left_measurement, right_measurement)

    # ──────────────────────────────────────────────────────────────────
    #  Анализ из base64 изображения
    # ──────────────────────────────────────────────────────────────────
    def analyze_image_bytes(self, image_bytes: bytes) -> PupilAnalysisResult:
        """Анализ из байтов изображения."""
        if not self._ensure_cv2():
            return PupilAnalysisResult(warnings=["OpenCV not available"])

        import numpy as np
        cv2 = self._cv2
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            return PupilAnalysisResult(warnings=["Failed to decode image"])
        return self.analyze_frame(frame)

    # ──────────────────────────────────────────────────────────────────
    #  Детекция областей глаз
    # ──────────────────────────────────────────────────────────────────
    def _detect_eye_regions(self, frame, gray) -> Tuple[Optional[Any], Optional[Any]]:
        """
        Выделение ROI левого и правого глаза.
        Использует Haar cascade (встроен в OpenCV).
        """
        cv2 = self._cv2

        # Haar cascade для глаз (встроен в OpenCV)
        eye_cascade_path = cv2.data.haarcascades + "haarcascade_eye.xml"
        eye_cascade = cv2.CascadeClassifier(eye_cascade_path)

        eyes = eye_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(30, 30),
        )

        if len(eyes) < 1:
            return None, None

        # Сортируем по x: левый глаз (меньший x) и правый (больший x)
        sorted_eyes = sorted(eyes, key=lambda e: e[0])

        left_roi = None
        right_roi = None

        if len(sorted_eyes) >= 1:
            x, y, w, h = sorted_eyes[0]
            left_roi = gray[y:y + h, x:x + w]

        if len(sorted_eyes) >= 2:
            x, y, w, h = sorted_eyes[1]
            right_roi = gray[y:y + h, x:x + w]

        return left_roi, right_roi

    # ──────────────────────────────────────────────────────────────────
    #  Измерение зрачка в ROI глаза
    # ──────────────────────────────────────────────────────────────────
    def _measure_pupil(self, eye_roi, side: str) -> Optional[PupilMeasurement]:
        """
        Сегментация и измерение зрачка в ROI глаза.

        Метод:
        1. GaussianBlur для шумоподавления.
        2. Threshold → бинарная маска зрачка (тёмная область).
        3. findContours → самый крупный контур = зрачок.
        4. minEnclosingCircle → диаметр зрачка.
        5. Отношение к размеру ROI ≈ iris.
        """
        cv2 = self._cv2

        h, w = eye_roi.shape[:2]
        if h < 10 or w < 10:
            return None

        # Iris diameter ≈ ROI width (грубая оценка)
        iris_diameter_px = float(w)

        # Preprocessing
        blurred = cv2.GaussianBlur(
            eye_roi,
            (self.config.pupil_blur_kernel, self.config.pupil_blur_kernel),
            0,
        )

        # Threshold — зрачок = самая тёмная область
        _, thresh = cv2.threshold(
            blurred,
            self.config.pupil_threshold,
            255,
            cv2.THRESH_BINARY_INV,
        )

        # Morphological cleanup
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=1)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=1)

        # Find contours
        contours, _ = cv2.findContours(
            thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        if not contours:
            return None

        # Самый крупный контур = зрачок
        largest = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest)

        # Проверка размера
        radius = math.sqrt(area / math.pi) if area > 0 else 0
        if radius < self.config.min_pupil_radius_px:
            return None
        if radius > self.config.max_pupil_radius_px:
            return None

        # Центр и радиус
        (cx, cy), enc_radius = cv2.minEnclosingCircle(largest)
        pupil_diameter_px = enc_radius * 2.0

        ratio = pupil_diameter_px / iris_diameter_px if iris_diameter_px > 0 else 0.0
        ratio = max(0.0, min(1.0, ratio))  # clamp

        # Confidence на основе circularity контура
        perimeter = cv2.arcLength(largest, True)
        circularity = (4 * math.pi * area) / (perimeter * perimeter) if perimeter > 0 else 0
        confidence = min(1.0, circularity)

        return PupilMeasurement(
            eye_side=side,
            pupil_diameter_px=pupil_diameter_px,
            iris_diameter_px=iris_diameter_px,
            pupil_iris_ratio=ratio,
            center_x=float(cx),
            center_y=float(cy),
            confidence=confidence,
        )

    # ──────────────────────────────────────────────────────────────────
    #  Построение результата
    # ──────────────────────────────────────────────────────────────────
    def _build_result(
        self,
        left: Optional[PupilMeasurement],
        right: Optional[PupilMeasurement],
    ) -> PupilAnalysisResult:
        """Агрегация измерений обоих глаз в итоговый результат."""
        warnings: List[str] = []
        ratios = []

        if left is not None:
            ratios.append(left.pupil_iris_ratio)
        else:
            warnings.append("Left eye not detected")

        if right is not None:
            ratios.append(right.pupil_iris_ratio)
        else:
            warnings.append("Right eye not detected")

        if not ratios:
            return PupilAnalysisResult(
                left_eye=left,
                right_eye=right,
                warnings=warnings + ["No pupil measurements available"],
            )

        avg_ratio = sum(ratios) / len(ratios)

        # Сглаживание по истории
        self._history.append(avg_ratio)
        if len(self._history) > self.config.smoothing_window:
            self._history = self._history[-self.config.smoothing_window:]

        smoothed_ratio = sum(self._history) / len(self._history)

        # Анизокория
        anisocoria = False
        anisocoria_diff = 0.0
        if left is not None and right is not None:
            anisocoria_diff = abs(left.pupil_iris_ratio - right.pupil_iris_ratio)
            anisocoria = anisocoria_diff > self.config.anisocoria_threshold
            if anisocoria:
                warnings.append(
                    f"Anisocoria detected (difference: {anisocoria_diff:.2f}). "
                    "This may indicate neurological issues — consult a specialist."
                )

        # Определение уровня дилатации
        cfg = self.config
        if smoothed_ratio >= cfg.dilation_high_threshold:
            dilation_level = "high_dilation"
        elif smoothed_ratio >= cfg.dilation_moderate_threshold:
            dilation_level = "moderate_dilation"
        elif smoothed_ratio <= cfg.constriction_threshold:
            dilation_level = "constriction"
        else:
            dilation_level = "normal"

        inferred_state = cfg.dilation_states.get(dilation_level, "unknown")

        # Confidence на основе количества кадров в истории
        frames_confidence = min(
            1.0,
            len(self._history) / self.config.min_frames_for_assessment,
        )
        measurement_confidence = (
            sum(m.confidence for m in [left, right] if m is not None) /
            max(1, len(ratios))
        )
        state_confidence = frames_confidence * measurement_confidence

        return PupilAnalysisResult(
            left_eye=left,
            right_eye=right,
            avg_pupil_iris_ratio=smoothed_ratio,
            anisocoria_detected=anisocoria,
            anisocoria_diff=anisocoria_diff,
            dilation_level=dilation_level,
            inferred_state=inferred_state,
            state_confidence=state_confidence,
            warnings=warnings,
        )

    # ──────────────────────────────────────────────────────────────────
    #  Сброс истории (для новой сессии)
    # ──────────────────────────────────────────────────────────────────
    def reset(self) -> None:
        """Сброс истории сглаживания."""
        self._history.clear()

    # ──────────────────────────────────────────────────────────────────
    #  Сериализация результата
    # ──────────────────────────────────────────────────────────────────
    @staticmethod
    def result_to_dict(result: PupilAnalysisResult) -> Dict[str, Any]:
        """Конвертация результата в JSON-совместимый dict."""
        def _eye_dict(m: Optional[PupilMeasurement]) -> Optional[Dict]:
            if m is None:
                return None
            return {
                "eye_side": m.eye_side,
                "pupil_diameter_px": round(m.pupil_diameter_px, 1),
                "iris_diameter_px": round(m.iris_diameter_px, 1),
                "pupil_iris_ratio": round(m.pupil_iris_ratio, 3),
                "center": [round(m.center_x, 1), round(m.center_y, 1)],
                "confidence": round(m.confidence, 2),
            }

        return {
            "left_eye": _eye_dict(result.left_eye),
            "right_eye": _eye_dict(result.right_eye),
            "avg_pupil_iris_ratio": round(result.avg_pupil_iris_ratio, 3),
            "anisocoria_detected": result.anisocoria_detected,
            "anisocoria_diff": round(result.anisocoria_diff, 3),
            "dilation_level": result.dilation_level,
            "inferred_state": result.inferred_state,
            "state_confidence": round(result.state_confidence, 2),
            "warnings": result.warnings,
        }
