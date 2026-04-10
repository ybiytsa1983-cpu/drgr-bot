"""
DRGR Psycho-Platform — Eye-Based Age Estimator.

Оценка возраста по периорбитальным признакам глаз:
  • Морщины вокруг глаз (гусиные лапки) — crow's feet
  • Мешки / отёчность под глазами — under-eye bags
  • Цвет и чистота склеры — sclera yellowness / redness
  • Чёткость радужки — iris clarity / limbal ring
  • Птоз верхнего века — eyelid drooping

Научная основа:
  • Periorbital aging — один из самых надёжных маркеров возраста.
  • Limbal ring visibility падает с возрастом (Peshek et al., 2011).
  • Sclera color меняется от белого (юность) к желтоватому (старость).
  • Crow's feet — первые морщины, появляющиеся с 25-30 лет.

Pipeline:
  1. Детекция лица + извлечение области глаз.
  2. Анализ 5 параметров (wrinkles, bags, sclera, iris, ptosis).
  3. Каждый параметр → score 0.0-1.0 (0=молодой, 1=старый).
  4. Взвешенная сумма → estimated_age.
  5. Доверительный интервал ± margin.

ВАЖНО: это НЕ медицинская и НЕ юридическая оценка.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("drgr-psycho.eye_age")


# ═══════════════════════════════════════════════════════════════════════════
#  Конфигурация
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class EyeAgeConfig:
    """Параметры оценки возраста по глазам."""

    # --- Веса параметров (сумма = 1.0) ---
    wrinkle_weight: float = 0.30          # морщины (гусиные лапки)
    bags_weight: float = 0.20             # мешки под глазами
    sclera_weight: float = 0.15           # цвет склеры
    iris_weight: float = 0.20             # чёткость радужки / лимбальное кольцо
    ptosis_weight: float = 0.15           # опущение верхнего века

    # --- Маппинг score → возраст ---
    age_min: float = 15.0                 # score=0 → этот возраст
    age_max: float = 80.0                 # score=1 → этот возраст

    # --- Доверительный интервал ---
    confidence_margin: float = 5.0        # ± лет

    # --- Пороги для текстурного анализа ---
    wrinkle_edge_threshold: int = 50      # Canny edge lower threshold
    wrinkle_edge_upper: int = 150         # Canny edge upper threshold
    bag_darkness_threshold: int = 60      # средняя яркость < порога → мешки

    # --- Детектор глаз ---
    eye_detector: str = "haarcascade"     # haarcascade | mediapipe


DEFAULT_EYE_AGE_CONFIG = EyeAgeConfig()


# ═══════════════════════════════════════════════════════════════════════════
#  Результат
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class EyeAgeResult:
    """Результат оценки возраста по глазам."""

    estimated_age: float              # предсказанный возраст (лет)
    confidence_margin: float          # ± лет
    lower_bound: float                # estimated_age - margin
    upper_bound: float                # estimated_age + margin

    # Отдельные скоры (0.0 = молодой, 1.0 = старый)
    wrinkle_score: float = 0.0       # морщины
    bags_score: float = 0.0          # мешки
    sclera_score: float = 0.0        # склера
    iris_score: float = 0.0          # радужка
    ptosis_score: float = 0.0        # птоз

    composite_score: float = 0.0     # взвешенная сумма (0-1)
    confidence: float = 0.0          # общая уверенность (0-1)

    warnings: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
#  Анализатор
# ═══════════════════════════════════════════════════════════════════════════

class EyeAgeEstimator:
    """
    Оценка возраста по периорбитальным признакам.

    Использование:
        estimator = EyeAgeEstimator()
        result = estimator.estimate_from_frame(frame_numpy)
        print(f"Estimated age: {result.estimated_age:.0f} ± {result.confidence_margin:.0f}")
    """

    def __init__(self, config: Optional[EyeAgeConfig] = None):
        self.config = config or DEFAULT_EYE_AGE_CONFIG
        self._cv2 = None

    def _ensure_cv2(self) -> bool:
        if self._cv2 is not None:
            return True
        try:
            import cv2
            self._cv2 = cv2
            return True
        except ImportError:
            logger.warning("OpenCV not installed for eye age estimation")
            return False

    # ──────────────────────────────────────────────────────────────────
    #  Основной метод
    # ──────────────────────────────────────────────────────────────────
    def estimate_from_frame(self, frame) -> EyeAgeResult:
        """
        Оценка возраста из BGR-кадра.

        Parameters
        ----------
        frame : numpy.ndarray (BGR)

        Returns
        -------
        EyeAgeResult
        """
        if not self._ensure_cv2():
            return EyeAgeResult(
                estimated_age=0, confidence_margin=self.config.confidence_margin,
                lower_bound=0, upper_bound=0,
                warnings=["OpenCV not available"],
            )

        cv2 = self._cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Детекция глаз
        eye_regions = self._detect_eye_regions(gray)
        if not eye_regions:
            return EyeAgeResult(
                estimated_age=0, confidence_margin=self.config.confidence_margin,
                lower_bound=0, upper_bound=0,
                warnings=["No eyes detected in frame"],
            )

        # Расширенные ROI (для анализа периорбитальной области)
        periorbital_rois = self._extract_periorbital_rois(frame, gray, eye_regions)

        # Анализ каждого параметра
        wrinkle_score = self._analyze_wrinkles(periorbital_rois, gray)
        bags_score = self._analyze_bags(periorbital_rois, gray)
        sclera_score = self._analyze_sclera(periorbital_rois, frame)
        iris_score = self._analyze_iris(periorbital_rois, gray)
        ptosis_score = self._analyze_ptosis(periorbital_rois, gray)

        # Взвешенная сумма
        cfg = self.config
        composite = (
            wrinkle_score * cfg.wrinkle_weight +
            bags_score * cfg.bags_weight +
            sclera_score * cfg.sclera_weight +
            iris_score * cfg.iris_weight +
            ptosis_score * cfg.ptosis_weight
        )
        composite = max(0.0, min(1.0, composite))

        # Маппинг в возраст
        estimated_age = cfg.age_min + composite * (cfg.age_max - cfg.age_min)
        lower = estimated_age - cfg.confidence_margin
        upper = estimated_age + cfg.confidence_margin

        # Confidence (среднее по скорам — чем больше разброс, тем ниже)
        scores = [wrinkle_score, bags_score, sclera_score, iris_score, ptosis_score]
        variance = sum((s - composite) ** 2 for s in scores) / len(scores)
        confidence = max(0.0, min(1.0, 1.0 - math.sqrt(variance)))

        return EyeAgeResult(
            estimated_age=round(estimated_age, 1),
            confidence_margin=cfg.confidence_margin,
            lower_bound=round(lower, 1),
            upper_bound=round(upper, 1),
            wrinkle_score=round(wrinkle_score, 3),
            bags_score=round(bags_score, 3),
            sclera_score=round(sclera_score, 3),
            iris_score=round(iris_score, 3),
            ptosis_score=round(ptosis_score, 3),
            composite_score=round(composite, 3),
            confidence=round(confidence, 2),
        )

    # ──────────────────────────────────────────────────────────────────
    #  Анализ из байтов
    # ──────────────────────────────────────────────────────────────────
    def estimate_from_bytes(self, image_bytes: bytes) -> EyeAgeResult:
        """Оценка возраста из байтов изображения."""
        if not self._ensure_cv2():
            return EyeAgeResult(
                estimated_age=0, confidence_margin=self.config.confidence_margin,
                lower_bound=0, upper_bound=0,
                warnings=["OpenCV not available"],
            )

        import numpy as np
        cv2 = self._cv2
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            return EyeAgeResult(
                estimated_age=0, confidence_margin=self.config.confidence_margin,
                lower_bound=0, upper_bound=0,
                warnings=["Failed to decode image"],
            )
        return self.estimate_from_frame(frame)

    # ──────────────────────────────────────────────────────────────────
    #  Детекция глаз
    # ──────────────────────────────────────────────────────────────────
    def _detect_eye_regions(self, gray) -> List[tuple]:
        """Haar cascade для детекции областей глаз."""
        cv2 = self._cv2
        cascade_path = cv2.data.haarcascades + "haarcascade_eye.xml"
        cascade = cv2.CascadeClassifier(cascade_path)
        eyes = cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30),
        )
        return list(eyes) if len(eyes) > 0 else []

    def _extract_periorbital_rois(self, frame, gray, eye_regions) -> List[Dict]:
        """
        Извлечение расширенных ROI для периорбитального анализа.
        Каждый ROI включает область над и под глазом.
        """
        h, w = gray.shape[:2]
        rois = []
        for (ex, ey, ew, eh) in eye_regions[:2]:  # макс. 2 глаза
            # Расширяем ROI на 50% вверх и 60% вниз для захвата морщин/мешков
            pad_up = int(eh * 0.5)
            pad_down = int(eh * 0.6)
            pad_side = int(ew * 0.3)

            y1 = max(0, ey - pad_up)
            y2 = min(h, ey + eh + pad_down)
            x1 = max(0, ex - pad_side)
            x2 = min(w, ex + ew + pad_side)

            rois.append({
                "eye_rect": (ex, ey, ew, eh),
                "peri_rect": (x1, y1, x2 - x1, y2 - y1),
                "eye_gray": gray[ey:ey + eh, ex:ex + ew],
                "peri_gray": gray[y1:y2, x1:x2],
                "eye_color": frame[ey:ey + eh, ex:ex + ew],
                "peri_color": frame[y1:y2, x1:x2],
                # Отдельно под глазом (для мешков)
                "under_gray": gray[ey + eh:min(h, ey + eh + pad_down), ex:ex + ew],
                # Сбоку от глаза (для гусиных лапок)
                "side_gray": gray[ey:ey + eh, min(w, ex + ew):min(w, ex + ew + pad_side)],
            })
        return rois

    # ──────────────────────────────────────────────────────────────────
    #  Анализ морщин (crow's feet)
    # ──────────────────────────────────────────────────────────────────
    def _analyze_wrinkles(self, rois: List[Dict], gray) -> float:
        """
        Оценка морщин через edge density в периорбитальной зоне.
        Больше edges = больше морщин = старше.
        """
        if not rois:
            return 0.0

        cv2 = self._cv2
        cfg = self.config
        densities = []

        for roi in rois:
            side = roi["side_gray"]
            if side.size < 100:
                continue
            edges = cv2.Canny(side, cfg.wrinkle_edge_threshold, cfg.wrinkle_edge_upper)
            density = edges.sum() / (edges.size * 255.0) if edges.size > 0 else 0.0
            densities.append(density)

        if not densities:
            return 0.0

        avg_density = sum(densities) / len(densities)
        # Normalize: 0.0 = no wrinkles, 0.15+ = severe wrinkles
        return min(1.0, avg_density / 0.15)

    # ──────────────────────────────────────────────────────────────────
    #  Анализ мешков под глазами
    # ──────────────────────────────────────────────────────────────────
    def _analyze_bags(self, rois: List[Dict], gray) -> float:
        """
        Оценка мешков: тёмные области под глазами.
        Ниже средняя яркость → больше мешков → старше.
        """
        if not rois:
            return 0.0

        brightnesses = []
        for roi in rois:
            under = roi["under_gray"]
            if under.size < 50:
                continue
            mean_val = float(under.mean())
            brightnesses.append(mean_val)

        if not brightnesses:
            return 0.0

        avg_brightness = sum(brightnesses) / len(brightnesses)
        # Инверсия: чем темнее (ниже яркость) → выше score
        # Normalize: 120+ = bright/young, 40- = very dark/old
        score = 1.0 - max(0.0, min(1.0, (avg_brightness - 40.0) / 80.0))
        return score

    # ──────────────────────────────────────────────────────────────────
    #  Анализ склеры
    # ──────────────────────────────────────────────────────────────────
    def _analyze_sclera(self, rois: List[Dict], frame) -> float:
        """
        Оценка цвета склеры: желтоватая / красноватая = старше.
        Чистая белая = моложе.
        """
        if not rois:
            return 0.0

        cv2 = self._cv2
        yellowness_scores = []

        for roi in rois:
            eye_color = roi["eye_color"]
            if eye_color.size < 100:
                continue

            # Конвертируем в HSV
            hsv = cv2.cvtColor(eye_color, cv2.COLOR_BGR2HSV)

            # Маска белых/светлых пикселей (склера)
            # High Value + Low Saturation → белый
            mask = cv2.inRange(hsv, (0, 0, 150), (180, 60, 255))

            if mask.sum() < 100:
                continue

            # Средний Hue склеры (жёлтый ≈ 20-30, белый ≈ 0)
            sclera_hue = hsv[:, :, 0][mask > 0]
            if len(sclera_hue) == 0:
                continue

            mean_hue = float(sclera_hue.mean())
            # Hue 0=red, 15-30=yellow → score
            yellowness = min(1.0, mean_hue / 30.0)
            yellowness_scores.append(yellowness)

        if not yellowness_scores:
            return 0.0

        return sum(yellowness_scores) / len(yellowness_scores)

    # ──────────────────────────────────────────────────────────────────
    #  Анализ радужки (iris clarity / limbal ring)
    # ──────────────────────────────────────────────────────────────────
    def _analyze_iris(self, rois: List[Dict], gray) -> float:
        """
        Оценка чёткости радужки: размытие лимбального кольца = старше.
        Чёткое лимбальное кольцо = моложе.
        """
        if not rois:
            return 0.0

        cv2 = self._cv2
        sharpness_scores = []

        for roi in rois:
            eye_gray = roi["eye_gray"]
            if eye_gray.size < 100:
                continue

            # Laplacian variance = мера резкости
            laplacian = cv2.Laplacian(eye_gray, cv2.CV_64F)
            variance = float(laplacian.var())

            # Normalize: высокая variance = чёткий = молодой
            # Typical: 50-500 sharp, <50 blurry
            sharpness = min(1.0, variance / 300.0)
            sharpness_scores.append(sharpness)

        if not sharpness_scores:
            return 0.0

        avg_sharpness = sum(sharpness_scores) / len(sharpness_scores)
        # Инвертируем: чёткий = молодой = low score
        return 1.0 - avg_sharpness

    # ──────────────────────────────────────────────────────────────────
    #  Анализ птоза (drooping eyelid)
    # ──────────────────────────────────────────────────────────────────
    def _analyze_ptosis(self, rois: List[Dict], gray) -> float:
        """
        Оценка птоза: отношение видимой части глаза к общей ширине.
        Меньше видимая часть → больше птоз → старше.
        """
        if not rois:
            return 0.0

        aspect_ratios = []
        for roi in rois:
            _, _, ew, eh = roi["eye_rect"]
            if ew < 10:
                continue
            # Eye aspect ratio: height/width
            # Нормальный ≈ 0.3-0.5, птоз < 0.25
            ear = float(eh) / float(ew)
            aspect_ratios.append(ear)

        if not aspect_ratios:
            return 0.0

        avg_ear = sum(aspect_ratios) / len(aspect_ratios)
        # Маппинг: EAR 0.5 = wide open = young → 0.0
        # EAR 0.15 = very droopy = old → 1.0
        score = 1.0 - max(0.0, min(1.0, (avg_ear - 0.15) / 0.35))
        return score

    # ──────────────────────────────────────────────────────────────────
    #  Сериализация
    # ──────────────────────────────────────────────────────────────────
    @staticmethod
    def result_to_dict(result: EyeAgeResult) -> Dict[str, Any]:
        """Конвертация результата в dict."""
        return {
            "estimated_age": result.estimated_age,
            "confidence_margin": result.confidence_margin,
            "lower_bound": result.lower_bound,
            "upper_bound": result.upper_bound,
            "scores": {
                "wrinkle": result.wrinkle_score,
                "bags": result.bags_score,
                "sclera": result.sclera_score,
                "iris": result.iris_score,
                "ptosis": result.ptosis_score,
            },
            "composite_score": result.composite_score,
            "confidence": result.confidence,
            "warnings": result.warnings,
        }
