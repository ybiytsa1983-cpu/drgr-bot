"""
DRGR Psycho-Platform — Camera Module.

Управление камерой (index 0 по умолчанию) для FER-анализа и age gate.
Предоставляет:
  • Проверку доступности камеры
  • Захват одиночного кадра
  • Конфигурацию (индекс, разрешение, fps)

ВАЖНО: OpenCV используется в headless-режиме (cv2.VideoCapture).
На сервере без физической камеры методы возвращают заглушки.
"""
from __future__ import annotations

import base64
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("drgr-psycho.camera")


# ═══════════════════════════════════════════════════════════════════════════
#  Конфигурация камеры
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class CameraConfig:
    """Параметры камеры."""
    index: int = 0                  # Индекс камеры (0 = основная)
    width: int = 640                # Ширина кадра
    height: int = 480               # Высота кадра
    fps: int = 30                   # Частота кадров
    warmup_frames: int = 5          # Кадров для «прогрева» камеры
    jpeg_quality: int = 85          # Качество JPEG при экспорте (0-100)


DEFAULT_CAMERA_CONFIG = CameraConfig()


# ═══════════════════════════════════════════════════════════════════════════
#  Менеджер камеры
# ═══════════════════════════════════════════════════════════════════════════
class CameraManager:
    """
    Управление камерой через OpenCV.

    Использование:
        cam = CameraManager()
        status = cam.get_status()
        if status["available"]:
            frame_b64 = cam.capture_frame_b64()
    """

    def __init__(self, config: Optional[CameraConfig] = None):
        self.config = config or DEFAULT_CAMERA_CONFIG
        self._lock = threading.Lock()
        self._cv2 = None  # lazy import

    def _ensure_cv2(self):
        """Lazy-импорт OpenCV."""
        if self._cv2 is not None:
            return True
        try:
            import cv2
            self._cv2 = cv2
            return True
        except ImportError:
            logger.warning(
                "OpenCV not installed. "
                "Run: pip install opencv-python-headless"
            )
            return False

    # ──────────────────────────────────────────────────────────────────
    #  Статус камеры
    # ──────────────────────────────────────────────────────────────────
    def get_status(self) -> Dict[str, Any]:
        """Проверить доступность камеры и вернуть статус."""
        if not self._ensure_cv2():
            return {
                "available": False,
                "error": "opencv-python-headless not installed",
                "index": self.config.index,
                "resolution": f"{self.config.width}x{self.config.height}",
            }

        cv2 = self._cv2
        cap = None
        try:
            cap = cv2.VideoCapture(self.config.index)
            if not cap.isOpened():
                return {
                    "available": False,
                    "error": f"Camera index {self.config.index} not accessible",
                    "index": self.config.index,
                    "resolution": f"{self.config.width}x{self.config.height}",
                }
            actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            actual_fps = cap.get(cv2.CAP_PROP_FPS)
            return {
                "available": True,
                "index": self.config.index,
                "resolution": f"{actual_w}x{actual_h}",
                "fps": actual_fps,
                "configured_resolution": f"{self.config.width}x{self.config.height}",
            }
        except Exception as exc:
            return {
                "available": False,
                "error": str(exc),
                "index": self.config.index,
                "resolution": f"{self.config.width}x{self.config.height}",
            }
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass

    # ──────────────────────────────────────────────────────────────────
    #  Захват кадра
    # ──────────────────────────────────────────────────────────────────
    def capture_frame(self) -> Tuple[bool, Optional[Any]]:
        """
        Захватить один кадр с камеры.

        Returns:
            (success, frame_numpy_array_or_None)
        """
        if not self._ensure_cv2():
            return False, None

        cv2 = self._cv2
        cap = None
        try:
            with self._lock:
                cap = cv2.VideoCapture(self.config.index)
                if not cap.isOpened():
                    return False, None

                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)

                # Пропуск «прогревочных» кадров
                for _ in range(self.config.warmup_frames):
                    cap.read()

                ret, frame = cap.read()
                if not ret or frame is None:
                    return False, None
                return True, frame
        except Exception as exc:
            logger.error("Camera capture error: %s", exc)
            return False, None
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass

    def capture_frame_b64(self) -> Optional[str]:
        """
        Захватить кадр и вернуть как base64-encoded JPEG.

        Returns:
            base64 строка или None при ошибке.
        """
        ok, frame = self.capture_frame()
        if not ok or frame is None:
            return None

        cv2 = self._cv2
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, self.config.jpeg_quality]
        ret, buf = cv2.imencode(".jpg", frame, encode_params)
        if not ret:
            return None
        return base64.b64encode(buf).decode("ascii")

    # ──────────────────────────────────────────────────────────────────
    #  Обновление конфигурации
    # ──────────────────────────────────────────────────────────────────
    def update_config(
        self,
        index: Optional[int] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        fps: Optional[int] = None,
    ) -> CameraConfig:
        """Обновить конфигурацию камеры."""
        if index is not None:
            self.config.index = index
        if width is not None:
            self.config.width = width
        if height is not None:
            self.config.height = height
        if fps is not None:
            self.config.fps = fps
        logger.info(
            "Camera config updated: index=%d, %dx%d @ %d fps",
            self.config.index,
            self.config.width,
            self.config.height,
            self.config.fps,
        )
        return self.config
