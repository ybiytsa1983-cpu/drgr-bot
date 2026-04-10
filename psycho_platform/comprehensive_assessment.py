"""
DRGR Psycho-Platform — Comprehensive Assessment.

Совокупная оценка состояния пациента по ВСЕМ параметрам:
  1. FER (Facial Emotion Recognition) — эмоции, валентность, стресс.
  2. Зрачки (Pupil Analysis) — дилатация, анизокория, состояние.
  3. Возраст по глазам (Eye Age) — периорбитальные признаки.
  4. Возраст по лицу (Face Age Gate) — ViT age classifier.
  5. Общие метрики — агрегированный stress_score, рекомендации.

Принцип работы:
  • Каждый модуль выдаёт свои метрики.
  • ComprehensiveAssessment объединяет их в единый отчёт.
  • На основе отчёта — рекомендации из базы знаний.
  • НИКАКИХ медицинских диагнозов — только мягкие оценки.

Архитектура:
  ComprehensiveAssessment
    ├── FER-pipeline (emotion, valence, arousal, stress)
    ├── PupilAnalyzer (dilation, anisocoria, inferred_state)
    ├── EyeAgeEstimator (periorbital age scores)
    ├── AgeGate (face-based age)
    └── KnowledgeBase (state → recommended methods)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("drgr-psycho.assessment")


# ═══════════════════════════════════════════════════════════════════════════
#  Конфигурация
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ComprehensiveConfig:
    """Параметры совокупной оценки."""

    # Веса модулей для общего stress_score
    fer_stress_weight: float = 0.40        # вес FER stress_score
    pupil_stress_weight: float = 0.30      # вес pupil dilation
    baseline_stress_weight: float = 0.30   # вес базовых метрик (arousal, valence)

    # Пороги для общей оценки
    overall_stress_high: float = 0.65
    overall_stress_moderate: float = 0.35

    # Маппинг эмоций → состояния (для рекомендаций)
    emotion_state_map: Dict[str, str] = field(default_factory=lambda: {
        "anger": "stress",
        "fear": "anxiety",
        "sadness": "low_mood",
        "disgust": "stress",
        "contempt": "low_mood",
        "surprise": "arousal",
        "joy": "positive",
        "neutral": "calm",
    })

    # Маппинг pupil state → KB state
    pupil_state_map: Dict[str, str] = field(default_factory=lambda: {
        "stress_or_arousal": "stress",
        "cognitive_load": "stress",
        "calm": "calm",
        "relaxation_or_fatigue": "fatigue",
    })

    # Возрастные коррекции (пожилые более склонны к мешкам/птозу)
    age_correction_enabled: bool = True
    elderly_threshold: float = 55.0        # > этого возраста — корректировки

    # Максимум рекомендаций
    max_recommendations: int = 5


DEFAULT_COMPREHENSIVE_CONFIG = ComprehensiveConfig()


# ═══════════════════════════════════════════════════════════════════════════
#  Входные данные от каждого модуля
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class FERInput:
    """Данные от FER-pipeline."""
    dominant_emotion: str = "neutral"
    emotion_scores: Dict[str, float] = field(default_factory=dict)
    valence: float = 0.0          # -1..+1
    arousal: float = 0.0          # 0..1
    stress_score: float = 0.0     # 0..1
    confidence: float = 0.0


@dataclass
class PupilInput:
    """Данные от PupilAnalyzer."""
    avg_pupil_iris_ratio: float = 0.0
    dilation_level: str = "normal"
    inferred_state: str = "calm"
    anisocoria_detected: bool = False
    anisocoria_diff: float = 0.0
    state_confidence: float = 0.0
    warnings: List[str] = field(default_factory=list)


@dataclass
class EyeAgeInput:
    """Данные от EyeAgeEstimator."""
    estimated_age: float = 0.0
    composite_score: float = 0.0
    wrinkle_score: float = 0.0
    bags_score: float = 0.0
    sclera_score: float = 0.0
    iris_score: float = 0.0
    ptosis_score: float = 0.0
    confidence: float = 0.0
    warnings: List[str] = field(default_factory=list)


@dataclass
class FaceAgeInput:
    """Данные от AgeGate (ViT classifier)."""
    predicted_age: float = 0.0
    confidence_margin: float = 3.0
    is_allowed: bool = True
    warnings: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
#  Результат совокупной оценки
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ComprehensiveResult:
    """Единый результат оценки состояния пациента."""

    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # ── Возраст (финальная оценка) ──
    estimated_age: float = 0.0
    age_source: str = "combined"        # "face", "eye", "combined"
    age_confidence: float = 0.0

    # ── Эмоциональное состояние ──
    dominant_emotion: str = "neutral"
    valence: float = 0.0                # -1..+1
    arousal: float = 0.0                # 0..1

    # ── Стресс (совокупный) ──
    overall_stress_score: float = 0.0   # 0..1
    stress_level: str = "low"           # "high", "moderate", "low"
    stress_components: Dict[str, float] = field(default_factory=dict)

    # ── Зрачки ──
    pupil_dilation_level: str = "normal"
    pupil_inferred_state: str = "calm"
    anisocoria_detected: bool = False

    # ── Глазные возрастные признаки ──
    eye_age_scores: Dict[str, float] = field(default_factory=dict)

    # ── Определённые состояния (для рекомендаций) ──
    detected_states: List[str] = field(default_factory=list)

    # ── Рекомендации ──
    recommended_methods: List[Dict[str, Any]] = field(default_factory=list)

    # ── Метаданные ──
    modules_used: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    disclaimer: str = (
        "Это НЕ медицинская диагностика. Результаты носят "
        "рекомендательный характер. При наличии проблем "
        "обратитесь к квалифицированному специалисту."
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Движок совокупной оценки
# ═══════════════════════════════════════════════════════════════════════════

class ComprehensiveAssessment:
    """
    Совокупная оценка состояния по всем параметрам.

    Использование:
        engine = ComprehensiveAssessment()
        result = engine.assess(
            fer=FERInput(dominant_emotion="anger", stress_score=0.8),
            pupil=PupilInput(dilation_level="high_dilation"),
            eye_age=EyeAgeInput(estimated_age=35.0),
            face_age=FaceAgeInput(predicted_age=33.0),
        )
        print(result.stress_level)  # "high"
        print(result.detected_states)  # ["stress"]
        print(result.recommended_methods)
    """

    def __init__(self, config: Optional[ComprehensiveConfig] = None):
        self.config = config or DEFAULT_COMPREHENSIVE_CONFIG
        self._kb = None

    def _get_kb(self):
        """Lazy-загрузка Knowledge Base."""
        if self._kb is None:
            try:
                from .knowledge_base import KnowledgeBase
                self._kb = KnowledgeBase()
            except Exception as exc:
                logger.warning("KB not available: %s", exc)
        return self._kb

    # ──────────────────────────────────────────────────────────────────
    #  Основной метод
    # ──────────────────────────────────────────────────────────────────
    def assess(
        self,
        fer: Optional[FERInput] = None,
        pupil: Optional[PupilInput] = None,
        eye_age: Optional[EyeAgeInput] = None,
        face_age: Optional[FaceAgeInput] = None,
    ) -> ComprehensiveResult:
        """
        Совокупная оценка по всем доступным параметрам.

        Каждый параметр опционален — модуль работает с тем, что есть.
        """
        result = ComprehensiveResult()
        cfg = self.config

        # ── 1. Возраст ──
        self._assess_age(result, eye_age, face_age)

        # ── 2. Эмоции (FER) ──
        if fer is not None:
            result.modules_used.append("fer")
            result.dominant_emotion = fer.dominant_emotion
            result.valence = fer.valence
            result.arousal = fer.arousal

        # ── 3. Зрачки ──
        if pupil is not None:
            result.modules_used.append("pupil")
            result.pupil_dilation_level = pupil.dilation_level
            result.pupil_inferred_state = pupil.inferred_state
            result.anisocoria_detected = pupil.anisocoria_detected
            result.warnings.extend(pupil.warnings)

        # ── 4. Совокупный стресс ──
        self._assess_stress(result, fer, pupil)

        # ── 5. Глазные возрастные признаки ──
        if eye_age is not None:
            result.modules_used.append("eye_age")
            result.eye_age_scores = {
                "wrinkle": eye_age.wrinkle_score,
                "bags": eye_age.bags_score,
                "sclera": eye_age.sclera_score,
                "iris": eye_age.iris_score,
                "ptosis": eye_age.ptosis_score,
            }
            result.warnings.extend(eye_age.warnings)

        # ── 6. Определение состояний ──
        self._detect_states(result, fer, pupil)

        # ── 7. Рекомендации из KB ──
        self._attach_recommendations(result)

        return result

    # ──────────────────────────────────────────────────────────────────
    #  Оценка возраста (комбинированная)
    # ──────────────────────────────────────────────────────────────────
    def _assess_age(
        self,
        result: ComprehensiveResult,
        eye_age: Optional[EyeAgeInput],
        face_age: Optional[FaceAgeInput],
    ) -> None:
        """Комбинированная оценка возраста: face ViT + eye periorbital."""
        ages = []
        confidences = []

        if face_age is not None and face_age.predicted_age > 0:
            result.modules_used.append("face_age")
            ages.append(face_age.predicted_age)
            # ViT обычно точнее → больший вес
            confidences.append(0.7)
            result.warnings.extend(face_age.warnings)

        if eye_age is not None and eye_age.estimated_age > 0:
            ages.append(eye_age.estimated_age)
            confidences.append(0.3 * eye_age.confidence)

        if not ages:
            result.age_source = "none"
            return

        if len(ages) == 1:
            result.estimated_age = ages[0]
            result.age_source = "face" if face_age and face_age.predicted_age > 0 else "eye"
            result.age_confidence = confidences[0]
        else:
            # Взвешенное среднее
            total_weight = sum(confidences)
            if total_weight > 0:
                result.estimated_age = round(
                    sum(a * c for a, c in zip(ages, confidences)) / total_weight,
                    1,
                )
            else:
                result.estimated_age = round(sum(ages) / len(ages), 1)
            result.age_source = "combined"
            result.age_confidence = round(min(1.0, total_weight), 2)

    # ──────────────────────────────────────────────────────────────────
    #  Совокупный стресс
    # ──────────────────────────────────────────────────────────────────
    def _assess_stress(
        self,
        result: ComprehensiveResult,
        fer: Optional[FERInput],
        pupil: Optional[PupilInput],
    ) -> None:
        """Совокупная оценка стресса по FER + зрачкам."""
        cfg = self.config
        components = {}
        weights = {}

        # FER stress
        if fer is not None:
            components["fer_stress"] = fer.stress_score
            weights["fer_stress"] = cfg.fer_stress_weight

            # Arousal/Valence → baseline stress
            # Formula: arousal × (1 - normalized_valence)
            # valence is in [-1,+1]; (valence+1)/2 normalizes to [0,1]
            # High arousal + negative valence → high baseline stress
            baseline = max(0.0, fer.arousal * (1.0 - (fer.valence + 1.0) / 2.0))
            components["baseline"] = min(1.0, baseline)
            weights["baseline"] = cfg.baseline_stress_weight

        # Pupil stress
        if pupil is not None:
            # Dilation → stress mapping
            dilation_stress_map = {
                "high_dilation": 0.9,
                "moderate_dilation": 0.5,
                "normal": 0.2,
                "constriction": 0.1,
            }
            pupil_stress = dilation_stress_map.get(pupil.dilation_level, 0.2)
            components["pupil_stress"] = pupil_stress
            weights["pupil_stress"] = cfg.pupil_stress_weight

        if not components:
            return

        # Взвешенное среднее
        total_weight = sum(weights.values())
        if total_weight > 0:
            overall = sum(
                components[k] * weights[k] for k in components
            ) / total_weight
        else:
            overall = 0.0

        result.overall_stress_score = round(min(1.0, overall), 3)
        result.stress_components = {k: round(v, 3) for k, v in components.items()}

        # Уровень стресса
        if result.overall_stress_score >= cfg.overall_stress_high:
            result.stress_level = "high"
        elif result.overall_stress_score >= cfg.overall_stress_moderate:
            result.stress_level = "moderate"
        else:
            result.stress_level = "low"

    # ──────────────────────────────────────────────────────────────────
    #  Детекция состояний
    # ──────────────────────────────────────────────────────────────────
    def _detect_states(
        self,
        result: ComprehensiveResult,
        fer: Optional[FERInput],
        pupil: Optional[PupilInput],
    ) -> None:
        """Определение состояний для рекомендаций."""
        cfg = self.config
        states = set()

        # Из FER
        if fer is not None:
            emotion_state = cfg.emotion_state_map.get(fer.dominant_emotion)
            if emotion_state and emotion_state != "positive" and emotion_state != "calm":
                states.add(emotion_state)

        # Из зрачков
        if pupil is not None:
            pupil_state = cfg.pupil_state_map.get(pupil.inferred_state)
            if pupil_state and pupil_state != "calm":
                states.add(pupil_state)

        # Из общего стресса
        if result.stress_level == "high":
            states.add("stress")
        elif result.stress_level == "moderate":
            states.add("mild_stress")

        # Анизокория → отдельный warning
        if result.anisocoria_detected:
            states.add("medical_attention")
            result.warnings.append(
                "Обнаружена анизокория (разница зрачков). "
                "Рекомендуется консультация невролога."
            )

        result.detected_states = sorted(states)

    # ──────────────────────────────────────────────────────────────────
    #  Рекомендации
    # ──────────────────────────────────────────────────────────────────
    def _attach_recommendations(self, result: ComprehensiveResult) -> None:
        """Получить рекомендации из KB по обнаруженным состояниям."""
        kb = self._get_kb()
        if kb is None:
            return

        seen_ids = set()
        methods = []

        for state in result.detected_states:
            if state == "medical_attention":
                continue  # Не из KB — только предупреждение

            try:
                recs = kb.recommend_methods(
                    state=state,
                    limit=self.config.max_recommendations,
                )
                for m in recs:
                    mid = m.get("id")
                    if mid not in seen_ids:
                        seen_ids.add(mid)
                        methods.append(m)
            except Exception as exc:
                logger.warning("KB recommendation error for state=%s: %s", state, exc)

        result.recommended_methods = methods[:self.config.max_recommendations]

    # ──────────────────────────────────────────────────────────────────
    #  Сериализация
    # ──────────────────────────────────────────────────────────────────
    @staticmethod
    def result_to_dict(result: ComprehensiveResult) -> Dict[str, Any]:
        """JSON-совместимый dict из результата."""
        return {
            "timestamp": result.timestamp,
            "age": {
                "estimated": result.estimated_age,
                "source": result.age_source,
                "confidence": result.age_confidence,
            },
            "emotion": {
                "dominant": result.dominant_emotion,
                "valence": result.valence,
                "arousal": result.arousal,
            },
            "stress": {
                "overall_score": result.overall_stress_score,
                "level": result.stress_level,
                "components": result.stress_components,
            },
            "pupil": {
                "dilation_level": result.pupil_dilation_level,
                "inferred_state": result.pupil_inferred_state,
                "anisocoria": result.anisocoria_detected,
            },
            "eye_age_scores": result.eye_age_scores,
            "detected_states": result.detected_states,
            "recommended_methods": [
                {
                    "id": m.get("id"),
                    "title": m.get("title"),
                    "description": m.get("description"),
                    "evidence_level": m.get("evidence_level"),
                    "duration_min": m.get("duration_min"),
                    "instructions": m.get("instructions"),
                }
                for m in result.recommended_methods
            ],
            "modules_used": result.modules_used,
            "warnings": result.warnings,
            "disclaimer": result.disclaimer,
        }
