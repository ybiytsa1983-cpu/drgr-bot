"""
DRGR Psycho-Platform — Informed Consent & Privacy Module.

Управление информированным согласием пользователя перед
видеоанализом и тестированием.

Ключевые принципы:
  • Обязательное информированное согласие ДО записи камеры.
  • Пользователь выбирает, сохранять ли видео (по умолчанию — нет).
  • Без камеры — только текстовые тесты.
  • Никаких «диагнозов» — только мягкая оценка и рекомендации.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("drgr-psycho.consent")


# ═══════════════════════════════════════════════════════════════════════════
#  Тексты согласий
# ═══════════════════════════════════════════════════════════════════════════

CONSENT_VIDEO_ANALYSIS = (
    "Я разрешаю анализ видео с камеры и оценку моего "
    "психоэмоционального состояния в целях подбора упражнений. "
    "Я понимаю, что:\n"
    "  • Это НЕ медицинская диагностика.\n"
    "  • Результаты носят рекомендательный характер.\n"
    "  • Я могу прервать анализ в любой момент.\n"
    "  • Сырое видео по умолчанию НЕ сохраняется."
)

CONSENT_VIDEO_STORAGE = (
    "Я дополнительно разрешаю сохранить исходное видео сессии "
    "для улучшения качества анализа. Видео будет храниться "
    "в зашифрованном виде и удалено через 30 дней."
)

CONSENT_TEXT_ONLY = (
    "Я согласен(на) пройти текстовое тестирование. "
    "Камера не будет использоваться. "
    "Результаты носят рекомендательный характер и "
    "не являются медицинским диагнозом."
)

MINOR_DENIAL_MESSAGE = (
    "Платформа предназначена для пользователей 21+.\n"
    "Если вам меньше 21 года, пожалуйста, обратитесь к "
    "специалисту или родителям.\n\n"
    "Это сообщение создано автоматической системой оценки "
    "возраста, которая может содержать ошибки."
)


# ═══════════════════════════════════════════════════════════════════════════
#  Модель согласия
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ConsentRecord:
    """Запись информированного согласия."""

    consent_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    user_uid: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # Что именно разрешил пользователь
    video_analysis: bool = False      # Разрешил видеоанализ
    video_storage: bool = False       # Разрешил хранение видео
    text_only: bool = False           # Только текстовые тесты

    # IP / User-Agent (для аудита, хранится хешированно)
    ip_hash: str = ""
    ua_hash: str = ""


class ConsentManager:
    """
    Управление информированным согласием.

    Использование:
        mgr = ConsentManager()
        record = mgr.create_consent(user_uid="abc123", video_analysis=True)
        if mgr.is_video_allowed(record):
            # запускаем FER-pipeline
    """

    @staticmethod
    def create_consent(
        user_uid: str,
        video_analysis: bool = False,
        video_storage: bool = False,
        text_only: bool = False,
        ip_hash: str = "",
        ua_hash: str = "",
    ) -> ConsentRecord:
        """Создаёт запись согласия."""
        # Нельзя одновременно text_only и video_analysis
        if text_only and video_analysis:
            video_analysis = False
            video_storage = False

        record = ConsentRecord(
            user_uid=user_uid,
            video_analysis=video_analysis,
            video_storage=video_storage,
            text_only=text_only,
            ip_hash=ip_hash,
            ua_hash=ua_hash,
        )
        logger.info(
            "Consent created: uid=%s video=%s storage=%s text_only=%s",
            user_uid,
            video_analysis,
            video_storage,
            text_only,
        )
        return record

    @staticmethod
    def is_video_allowed(record: ConsentRecord) -> bool:
        """Проверяет, разрешён ли видеоанализ."""
        return record.video_analysis and not record.text_only

    @staticmethod
    def is_storage_allowed(record: ConsentRecord) -> bool:
        """Проверяет, разрешено ли хранение видео."""
        return record.video_storage and record.video_analysis

    @staticmethod
    def get_consent_texts() -> dict:
        """Возвращает все тексты согласий для отображения в UI."""
        return {
            "video_analysis": CONSENT_VIDEO_ANALYSIS,
            "video_storage": CONSENT_VIDEO_STORAGE,
            "text_only": CONSENT_TEXT_ONLY,
            "minor_denial": MINOR_DENIAL_MESSAGE,
        }

    @staticmethod
    def revoke_consent(record: ConsentRecord) -> ConsentRecord:
        """Отзыв согласия — запрещает всё."""
        record.video_analysis = False
        record.video_storage = False
        record.text_only = False
        logger.info("Consent revoked: uid=%s", record.user_uid)
        return record
