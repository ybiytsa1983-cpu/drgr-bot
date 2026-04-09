"""
DRGR Psycho-Platform — Age Gate (21+).

Модуль вероятностной оценки возраста по лицу.
Используется при входе на платформу: если нижняя граница доверительного
интервала >= 21 — пропускаем; иначе — отказ (или запрос документа).

ВАЖНО: это НЕ юридическая проверка паспорта, а предварительная оценка.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from .fer_config import DEFAULT_AGE_CONFIG, AgeEstimationConfig

logger = logging.getLogger("drgr-psycho.age_gate")


@dataclass
class AgeEstimationResult:
    """Результат оценки возраста."""

    predicted_age: float          # Предсказанный возраст (лет)
    confidence_margin: float      # ± погрешность (лет)
    lower_bound: float            # predicted_age - margin
    upper_bound: float            # predicted_age + margin
    is_allowed: bool              # lower_bound >= min_age
    denial_reason: Optional[str]  # Причина отказа (если есть)


class AgeGate:
    """
    Проверка возраста 21+ по изображению лица.

    Использование:
        gate = AgeGate()
        result = gate.evaluate(image_bytes)
        if result.is_allowed:
            # пропускаем
        else:
            # показываем отказ
    """

    def __init__(self, config: Optional[AgeEstimationConfig] = None):
        self.config = config or DEFAULT_AGE_CONFIG
        self._model = None

    # ──────────────────────────────────────────────────────────────────
    #  Загрузка модели (lazy)
    # ──────────────────────────────────────────────────────────────────
    def _ensure_model(self) -> None:
        """Lazy-загрузка модели при первом вызове."""
        if self._model is not None:
            return

        try:
            from transformers import pipeline as hf_pipeline

            self._model = hf_pipeline(
                "image-classification",
                model=self.config.model,
                device=-1,  # CPU; для GPU поставьте 0
            )
            logger.info("Age-estimation model loaded: %s", self.config.model)
        except ImportError:
            logger.error(
                "transformers not installed. "
                "Run: pip install transformers torch pillow"
            )
            raise
        except Exception:
            logger.exception("Failed to load age-estimation model")
            raise

    # ──────────────────────────────────────────────────────────────────
    #  Основной метод
    # ──────────────────────────────────────────────────────────────────
    def evaluate(self, image) -> AgeEstimationResult:
        """
        Оценка возраста по изображению.

        Parameters
        ----------
        image : PIL.Image.Image | bytes | str
            Изображение лица (PIL Image, байты или путь к файлу).

        Returns
        -------
        AgeEstimationResult
        """
        self._ensure_model()

        # Если передали bytes — конвертируем в PIL
        if isinstance(image, bytes):
            from io import BytesIO

            from PIL import Image as PILImage

            image = PILImage.open(BytesIO(image)).convert("RGB")
        elif isinstance(image, str):
            from PIL import Image as PILImage

            image = PILImage.open(image).convert("RGB")

        # Получаем предсказания (список {label: "20-25", score: 0.43}, ...)
        predictions = self._model(image)

        # Парсим среднее из топ-предсказания (label = "25-30" → 27.5)
        predicted_age = self._parse_age_label(predictions[0]["label"])

        lower = predicted_age - self.config.confidence_margin
        upper = predicted_age + self.config.confidence_margin

        is_allowed = lower >= self.config.min_age

        denial_reason = None
        if not is_allowed:
            denial_reason = (
                f"Оценка возраста: {predicted_age:.0f} лет "
                f"(интервал {lower:.0f}–{upper:.0f}). "
                f"Минимальный возраст: {self.config.min_age}+. "
                "Это автоматическая оценка и может содержать ошибки."
            )

        return AgeEstimationResult(
            predicted_age=predicted_age,
            confidence_margin=self.config.confidence_margin,
            lower_bound=lower,
            upper_bound=upper,
            is_allowed=is_allowed,
            denial_reason=denial_reason,
        )

    # ──────────────────────────────────────────────────────────────────
    #  Вспомогательные методы
    # ──────────────────────────────────────────────────────────────────
    @staticmethod
    def _parse_age_label(label: str) -> float:
        """
        Парсит метку вида "25-30" или "25" в числовой возраст.
        Для диапазона возвращает среднее.
        """
        label = label.strip()
        if "-" in label:
            parts = label.split("-")
            try:
                low = float(parts[0])
                high = float(parts[1])
                return (low + high) / 2.0
            except (ValueError, IndexError):
                pass
        try:
            return float(label)
        except ValueError:
            logger.warning("Cannot parse age label: %s, defaulting to 0", label)
            return 0.0

    # ──────────────────────────────────────────────────────────────────
    #  Текст для UI
    # ──────────────────────────────────────────────────────────────────
    @staticmethod
    def get_consent_text() -> str:
        """Текст информированного согласия для экрана проверки возраста."""
        return (
            "Для доступа к сервису (21+) мы оценим ваш возраст по "
            "изображению лица. Это необязательная предварительная проверка "
            "и не заменяет юридическую идентификацию.\n\n"
            "• Изображение анализируется в реальном времени и НЕ сохраняется.\n"
            "• Возможны ошибки оценки; результат является приблизительным.\n"
            "• Продолжая, вы подтверждаете, что вам исполнился 21 год."
        )
