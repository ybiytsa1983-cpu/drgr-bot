"""
DRGR Psycho-Platform — Seed Dataset.

Начальные данные для базы знаний ВМ:
  • Научные источники по FER, невербике, психокоррекции
  • Методики (дыхательные, когнитивные, телесные)
  • Описание принципов работы каждого модуля ВМ

Запуск:
    python -m psycho_platform.seed_dataset

Или из кода:
    from psycho_platform.seed_dataset import seed_all
    seed_all()
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from .knowledge_base import KnowledgeBase

logger = logging.getLogger("drgr-psycho.seed")


# ═══════════════════════════════════════════════════════════════════════════
#  ИСТОЧНИКИ (Sources)
# ═══════════════════════════════════════════════════════════════════════════

SEED_SOURCES: List[Dict[str, Any]] = [
    # --- FER 2021-2026 ---
    {
        "type": "article",
        "year": 2022,
        "authors": "Li S., Deng W.",
        "title": "Deep Facial Expression Recognition: A Survey",
        "url": "https://arxiv.org/abs/2203.13531",
        "doi": "10.1109/TPAMI.2022.3174012",
        "tags": ["emotion_recognition", "deep_learning", "survey"],
        "notes": "Основной обзор FER-методов 2017-2022. Покрывает CNN, ViT, данные.",
    },
    {
        "type": "article",
        "year": 2023,
        "authors": "Savchenko A.V.",
        "title": "Facial Expression Recognition with Adaptive Frame Rate",
        "url": "https://arxiv.org/abs/2307.04420",
        "tags": ["emotion_recognition", "video", "adaptive"],
        "notes": "Адаптивная частота кадров для FER в видеопотоке.",
    },
    {
        "type": "article",
        "year": 2024,
        "authors": "Zhang Y., et al.",
        "title": "FER in Clinical and Therapeutic Applications: A Review",
        "url": "https://arxiv.org/abs/2401.05831",
        "tags": ["emotion_recognition", "clinical", "app_based"],
        "notes": "Обзор применения FER в клинике и терапии.",
    },
    {
        "type": "article",
        "year": 2021,
        "authors": "Mollahosseini A., Hasani B., Mahoor M.H.",
        "title": "AffectNet: A Database for Facial Expression, Valence, and Arousal",
        "url": "https://ieeexplore.ieee.org/document/8013713",
        "doi": "10.1109/TAFFC.2017.2740923",
        "tags": ["emotion_recognition", "dataset", "valence_arousal"],
        "notes": "Датасет AffectNet — 1M+ изображений с разметкой эмоций.",
    },
    {
        "type": "article",
        "year": 2023,
        "authors": "Zheng C., et al.",
        "title": "EmoSet: A Large-Scale Visual Emotion Dataset",
        "url": "https://arxiv.org/abs/2307.07961",
        "tags": ["emotion_recognition", "dataset"],
        "notes": "3.3M изображений, 8 эмоций. Open-access.",
    },
    # --- Невербика / Классика ---
    {
        "type": "book",
        "year": 1872,
        "authors": "Darwin C.",
        "title": "The Expression of the Emotions in Man and Animals",
        "url": "https://en.wikipedia.org/wiki/The_Expression_of_the_Emotions_in_Man_and_Animals",
        "tags": ["nonverbal", "classic", "emotion_recognition"],
        "notes": "Исторический фундамент изучения эмоций по лицу.",
    },
    {
        "type": "pop_psychology",
        "year": 1981,
        "authors": "Pease A.",
        "title": "Body Language: How to Read Others' Thoughts by Their Gestures",
        "url": "https://en.wikipedia.org/wiki/Allan_Pease",
        "tags": ["nonverbal", "body_language", "popular"],
        "notes": "Популяризатор невербики. НЕ клинический инструмент.",
    },
    {
        "type": "pop_psychology",
        "year": 2004,
        "authors": "Pease A., Pease B.",
        "title": "The Definitive Book of Body Language",
        "tags": ["nonverbal", "body_language", "popular"],
        "notes": "Расширенное издание. Позы, жесты, микровыражения (популярно).",
    },
    {
        "type": "article",
        "year": 1971,
        "authors": "Ekman P., Friesen W.V.",
        "title": "Constants Across Cultures in the Face and Emotion",
        "doi": "10.1037/h0030377",
        "tags": ["emotion_recognition", "nonverbal", "classic"],
        "notes": "6 базовых эмоций Экмана — фундамент современного FER.",
    },
    # --- Психокоррекция ---
    {
        "type": "method",
        "year": 2020,
        "authors": "Kabat-Zinn J.",
        "title": "Mindfulness-Based Stress Reduction (MBSR) Protocol",
        "tags": ["psychocorrection", "stress", "mindfulness"],
        "notes": "Клинически валидированная 8-недельная программа снижения стресса.",
    },
    {
        "type": "method",
        "year": 2015,
        "authors": "Ma X., et al.",
        "title": "Effect of Diaphragmatic Breathing on Attention, Negative Affect and Stress",
        "doi": "10.3389/fpsyg.2017.00874",
        "tags": ["psychocorrection", "breathing", "stress"],
        "notes": "Исследование диафрагмального дыхания и его влияния на стресс.",
    },
    {
        "type": "article",
        "year": 2022,
        "authors": "Nategh S., et al.",
        "title": "Age Estimation from Facial Images: A Comprehensive Survey",
        "url": "https://arxiv.org/abs/2206.09039",
        "tags": ["age_estimation", "survey", "deep_learning"],
        "notes": "Обзор методов оценки возраста по лицу.",
    },
]


# ═══════════════════════════════════════════════════════════════════════════
#  МЕТОДИКИ (Methods) — то, что ВМ может рекомендовать пользователю
# ═══════════════════════════════════════════════════════════════════════════

SEED_METHODS: List[Dict[str, Any]] = [
    # --- Дыхательные ---
    {
        "title": "Диафрагмальное дыхание (4-7-8)",
        "description": (
            "Техника дыхания: вдох 4 сек → задержка 7 сек → выдох 8 сек. "
            "Активирует парасимпатическую нервную систему, снижает стресс."
        ),
        "evidence_level": "high",
        "applicable_in_app": True,
        "target_states": ["stress", "anxiety", "high_arousal"],
        "instructions": (
            "1. Сядьте удобно, закройте глаза.\n"
            "2. Вдохните через нос на счёт 4.\n"
            "3. Задержите дыхание на счёт 7.\n"
            "4. Медленно выдохните через рот на счёт 8.\n"
            "5. Повторите 4-8 циклов."
        ),
        "duration_min": 5,
    },
    {
        "title": "Квадратное дыхание (Box Breathing)",
        "description": (
            "Вдох 4 сек → задержка 4 сек → выдох 4 сек → задержка 4 сек. "
            "Используется спецназом и спортсменами для управления стрессом."
        ),
        "evidence_level": "medium",
        "applicable_in_app": True,
        "target_states": ["stress", "anxiety", "focus"],
        "instructions": (
            "1. Вдохните на 4 секунды.\n"
            "2. Задержите дыхание на 4 секунды.\n"
            "3. Выдохните на 4 секунды.\n"
            "4. Задержите дыхание на 4 секунды.\n"
            "5. Повторите 5-10 циклов."
        ),
        "duration_min": 4,
    },
    # --- Когнитивные ---
    {
        "title": "Журнал эмоций (Emotion Diary)",
        "description": (
            "Ежедневная запись эмоций и триггеров. "
            "Помогает осознать паттерны и снизить реактивность."
        ),
        "evidence_level": "medium",
        "applicable_in_app": True,
        "target_states": ["stress", "anxiety", "low_mood", "anger"],
        "instructions": (
            "1. Выберите момент дня (утро или вечер).\n"
            "2. Запишите: какую эмоцию чувствовали сильнее всего?\n"
            "3. Что её вызвало (ситуация, мысль, человек)?\n"
            "4. Как отреагировали?\n"
            "5. Что бы сделали иначе?"
        ),
        "duration_min": 10,
    },
    {
        "title": "Когнитивная переоценка (Reappraisal)",
        "description": (
            "Техника КПТ: переосмысление ситуации для изменения эмоциональной реакции. "
            "Одна из самых исследованных стратегий регуляции эмоций."
        ),
        "evidence_level": "high",
        "applicable_in_app": True,
        "target_states": ["stress", "anxiety", "anger", "low_mood"],
        "instructions": (
            "1. Опишите ситуацию, которая вызывает негатив.\n"
            "2. Какие мысли возникают? Запишите.\n"
            "3. Есть ли другое объяснение ситуации?\n"
            "4. Что бы сказал друг / мудрый наставник?\n"
            "5. Переформулируйте мысль нейтрально."
        ),
        "duration_min": 10,
    },
    # --- Телесные ---
    {
        "title": "Прогрессивная мышечная релаксация (PMR)",
        "description": (
            "Поочерёдное напряжение и расслабление групп мышц. "
            "Снимает физическое напряжение, ассоциированное со стрессом."
        ),
        "evidence_level": "high",
        "applicable_in_app": True,
        "target_states": ["stress", "anxiety", "tension", "high_arousal"],
        "instructions": (
            "1. Лягте или сядьте удобно.\n"
            "2. Начните с ног: напрягите на 5 сек → расслабьте.\n"
            "3. Переходите вверх: икры, бёдра, живот, руки, плечи, лицо.\n"
            "4. Каждую группу — напряжение 5 сек, расслабление 10 сек.\n"
            "5. В конце — просканируйте всё тело."
        ),
        "duration_min": 15,
    },
    {
        "title": "Техника заземления 5-4-3-2-1",
        "description": (
            "Сенсорная техника: назвать 5 вещей, которые видишь, 4 — слышишь, "
            "3 — можешь потрогать, 2 — чувствуешь запах, 1 — на вкус. "
            "Быстрое переключение из тревоги в настоящий момент."
        ),
        "evidence_level": "medium",
        "applicable_in_app": True,
        "target_states": ["anxiety", "panic", "dissociation"],
        "instructions": (
            "1. Назовите 5 вещей, которые ВИДИТЕ прямо сейчас.\n"
            "2. Назовите 4 вещи, которые СЛЫШИТЕ.\n"
            "3. Назовите 3 вещи, которые можете ПОТРОГАТЬ.\n"
            "4. Назовите 2 вещи, которые ЧУВСТВУЕТЕ ЗАПАХ.\n"
            "5. Назовите 1 вещь, которую ощущаете на ВКУС."
        ),
        "duration_min": 3,
    },
    # --- Проективные / Арт-терапия ---
    {
        "title": "Свободное рисование эмоции",
        "description": (
            "Нарисовать текущее эмоциональное состояние абстрактно: "
            "цвет, форма, линии. Помогает экстернализировать чувства."
        ),
        "evidence_level": "low",
        "applicable_in_app": True,
        "target_states": ["stress", "low_mood", "confusion"],
        "instructions": (
            "1. Возьмите лист бумаги и карандаши/маркеры.\n"
            "2. Не думая, нарисуйте то, что чувствуете.\n"
            "3. Используйте любые формы, цвета, линии.\n"
            "4. Посмотрите на рисунок — что он говорит?\n"
            "5. Запишите 1-2 слова рядом."
        ),
        "duration_min": 10,
    },
    # --- Mindfulness ---
    {
        "title": "Сканирование тела (Body Scan)",
        "description": (
            "Внимательное последовательное наблюдение ощущений в каждой части тела. "
            "Ключевая практика MBSR Kabat-Zinn."
        ),
        "evidence_level": "high",
        "applicable_in_app": True,
        "target_states": ["stress", "anxiety", "tension", "insomnia"],
        "instructions": (
            "1. Лягте на спину, закройте глаза.\n"
            "2. Направьте внимание на стопы — что чувствуете?\n"
            "3. Медленно перемещайте внимание вверх: голени → колени → бёдра.\n"
            "4. Живот → грудь → руки → шея → лицо → макушка.\n"
            "5. Просто наблюдайте, не пытаясь менять ощущения.\n"
            "6. 15-20 минут."
        ),
        "duration_min": 20,
    },
]


# ═══════════════════════════════════════════════════════════════════════════
#  ПРИНЦИПЫ РАБОТЫ МОДУЛЕЙ ВМ (dataset-description)
# ═══════════════════════════════════════════════════════════════════════════

VM_MODULE_PRINCIPLES: List[Dict[str, str]] = [
    {
        "module": "fer_pipeline",
        "title": "Модуль распознавания эмоций (FER)",
        "principle": (
            "1. Принимает видеопоток с камеры (WebRTC, 5-10 fps).\n"
            "2. Детектор лиц (RetinaFace/MTCNN) находит лицо в кадре.\n"
            "3. FER-модель (ViT/ResNet) классифицирует эмоцию: "
            "neutral/joy/sadness/anger/fear/surprise/disgust/contempt.\n"
            "4. Временное сглаживание (скользящее среднее по 5 кадрам) "
            "убирает случайные всплески.\n"
            "5. Агрегация по вопросам теста: для каждого question_id "
            "считаем avg_valence, avg_arousal, stress_score.\n"
            "6. Результат — НЕ диагноз, а мягкая оценка "
            "(«повышенный/умеренный/низкий стресс»)."
        ),
    },
    {
        "module": "age_gate",
        "title": "Модуль проверки возраста (21+)",
        "principle": (
            "1. При входе на сайт показываем камеру + текст согласия.\n"
            "2. ViT age-classifier оценивает возраст + доверительный интервал.\n"
            "3. Если lower_bound (predicted_age - margin) >= 21 → пропускаем.\n"
            "4. Если нет → отказ с сообщением.\n"
            "5. Это вероятностная оценка, НЕ юридическая проверка.\n"
            "6. Изображение анализируется в реальном времени и НЕ сохраняется."
        ),
    },
    {
        "module": "consent_manager",
        "title": "Модуль информированного согласия",
        "principle": (
            "1. ДО любого анализа показываем текст согласия.\n"
            "2. Три режима: video_analysis, video_storage, text_only.\n"
            "3. Без согласия → только текстовые тесты.\n"
            "4. Видео по умолчанию НЕ сохраняется (только метрики).\n"
            "5. Пользователь может отозвать согласие в любой момент.\n"
            "6. Для несовершеннолетних — автоматический отказ."
        ),
    },
    {
        "module": "knowledge_base",
        "title": "База знаний (научные источники + методики)",
        "principle": (
            "1. SQLite-хранилище с таблицами: sources, methods.\n"
            "2. Sources — научные статьи, книги, датасеты с тегами.\n"
            "3. Methods — практические методики с уровнем доказательности.\n"
            "4. Каждая методика привязана к target_states "
            "(stress, anxiety, low_mood и т.п.).\n"
            "5. FER-модуль определяет состояние → KB находит подходящие методики.\n"
            "6. Рекомендации ранжируются по evidence_level."
        ),
    },
    {
        "module": "recommendation_engine",
        "title": "Движок рекомендаций",
        "principle": (
            "1. Вход: результаты FER (stress_score, dominant_emotion, valence).\n"
            "2. Маппинг: stress_score > 0.65 → state='stress'; "
            "dominant_emotion='sadness' → state='low_mood'.\n"
            "3. Запрос KB: recommend_methods(state, limit=5).\n"
            "4. Выдача: список упражнений с инструкциями.\n"
            "5. Формулировка мягкая, без медицинских ярлыков.\n"
            "6. Обратная связь: user_feedback (helpful/not_helpful/skipped)."
        ),
    },
    {
        "module": "camera_manager",
        "title": "Модуль камеры",
        "principle": (
            "1. OpenCV VideoCapture с конфигурируемым индексом (default=0).\n"
            "2. Lazy-загрузка: камера открывается только при запросе.\n"
            "3. Захват: одиночный кадр → JPEG base64.\n"
            "4. Прогрев: первые 5 кадров пропускаются (автоэкспозиция).\n"
            "5. На сервере без камеры — возвращает 'not available'.\n"
            "6. Конфигурация через API: index, resolution, fps."
        ),
    },
    {
        "module": "ollama_integration",
        "title": "Интеграция с Ollama LLM",
        "principle": (
            "1. Сервер пробует подключиться к Ollama на портах 11434-11437.\n"
            "2. Предпочтительный порт 11435 задаётся через OLLAMA_PORT в .env.\n"
            "3. При обнаружении — получает список моделей через /api/tags.\n"
            "4. Чат через /api/chat с выбранной моделью.\n"
            "5. Если Ollama недоступна — фоллбэк на LM Studio.\n"
            "6. Используется для: генерации статей, чата, анализа кода."
        ),
    },
]


# ═══════════════════════════════════════════════════════════════════════════
#  Seed Function
# ═══════════════════════════════════════════════════════════════════════════

def seed_all(db_path: str | None = None) -> Dict[str, int]:
    """
    Наполнить базу знаний начальными данными.

    Returns:
        {"sources_added": N, "methods_added": M}
    """
    kb = KnowledgeBase(db_path=db_path)

    # Проверяем, не заполнена ли уже
    stats = kb.get_stats()
    if stats["sources_total"] > 0 or stats["methods_total"] > 0:
        logger.info(
            "KB already seeded (%d sources, %d methods). Skipping.",
            stats["sources_total"],
            stats["methods_total"],
        )
        return {"sources_added": 0, "methods_added": 0}

    sources_added = 0
    for src in SEED_SOURCES:
        try:
            kb.add_source(**src)
            sources_added += 1
        except Exception as exc:
            logger.warning("Failed to add source '%s': %s", src.get("title"), exc)

    methods_added = 0
    for mtd in SEED_METHODS:
        try:
            kb.add_method(**mtd)
            methods_added += 1
        except Exception as exc:
            logger.warning("Failed to add method '%s': %s", mtd.get("title"), exc)

    logger.info("Seed complete: %d sources, %d methods", sources_added, methods_added)
    return {"sources_added": sources_added, "methods_added": methods_added}


# ═══════════════════════════════════════════════════════════════════════════
#  CLI entry point
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = seed_all()
    print(f"✅ Seeded: {result}")
    print("\n📋 VM Module Principles:")
    for m in VM_MODULE_PRINCIPLES:
        print(f"\n{'='*60}")
        print(f"  {m['module']}: {m['title']}")
        print(f"{'='*60}")
        print(m["principle"])
