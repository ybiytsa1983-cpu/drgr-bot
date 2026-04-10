-- ═══════════════════════════════════════════════════════════════════════
--  DRGR Psycho-Platform — Database Schema
--  Совместимо с SQLite (dev) и PostgreSQL (prod).
-- ═══════════════════════════════════════════════════════════════════════

-- ───────────────────────────────────────────────────────────────────────
--  Научные источники (статьи, книги, методички)
-- ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sources (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    type          TEXT    NOT NULL CHECK (type IN (
                      'article', 'book', 'pop_psychology', 'method', 'dataset'
                  )),
    year          INTEGER,
    authors       TEXT    NOT NULL,                 -- Фамилии через запятую
    title         TEXT    NOT NULL,
    url           TEXT,                             -- URL или DOI
    doi           TEXT,
    tags          TEXT    DEFAULT '[]',             -- JSON-массив тегов:
                                                   --   emotion_recognition, nonverbal,
                                                   --   psychocorrection, clinical, app_based
    notes         TEXT,
    created_at    TEXT    DEFAULT (datetime('now','utc'))
);

-- ───────────────────────────────────────────────────────────────────────
--  Методики (дыхательные, когнитивные, телесные и др.)
-- ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS methods (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT    NOT NULL,
    description     TEXT,                          -- Краткое описание своими словами
    evidence_level  TEXT    NOT NULL CHECK (evidence_level IN (
                        'high', 'medium', 'low', 'popular'
                    )),
    applicable_in_app BOOLEAN DEFAULT 0,           -- Можно ли встроить в платформу
    target_states   TEXT    DEFAULT '[]',           -- JSON: ["stress","anxiety","low_mood"]
    instructions    TEXT,                           -- Пошаговая инструкция для пользователя
    duration_min    INTEGER,                        -- Примерная длительность, мин
    source_ids      TEXT    DEFAULT '[]',           -- JSON: [1, 5, 12]
    created_at      TEXT    DEFAULT (datetime('now','utc'))
);

-- ───────────────────────────────────────────────────────────────────────
--  Пользователи (минимальный набор — без персональных данных)
-- ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uid             TEXT    NOT NULL UNIQUE,         -- UUID, никаких ФИО
    age_verified    BOOLEAN DEFAULT 0,               -- Прошёл 21+ проверку
    consent_given   BOOLEAN DEFAULT 0,               -- Дал информированное согласие
    consent_ts      TEXT,                             -- Когда дал согласие
    created_at      TEXT    DEFAULT (datetime('now','utc'))
);

-- ───────────────────────────────────────────────────────────────────────
--  Сессии тестирования
-- ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS test_sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    started_at      TEXT    DEFAULT (datetime('now')),
    ended_at        TEXT,
    video_consent   BOOLEAN DEFAULT 0,               -- Согласие на видеоанализ
    status          TEXT    DEFAULT 'in_progress'
                            CHECK (status IN ('in_progress','completed','cancelled')),
    created_at      TEXT    DEFAULT (datetime('now','utc'))
);

-- ───────────────────────────────────────────────────────────────────────
--  Результаты FER-анализа (анонимизированные метрики, НЕ видео)
-- ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fer_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES test_sessions(id),
    question_id     TEXT,                            -- К какому вопросу относится
    start_time      REAL,                            -- секунды от начала сессии
    end_time        REAL,
    -- Агрегированные метрики (не сырые кадры)
    avg_valence     REAL,                            -- -1..+1  негатив..позитив
    avg_arousal     REAL,                            --  0..1   спокойствие..возбуждение
    stress_score    REAL,                            --  0..1   уровень стресса
    dominant_emotion TEXT,                           -- joy/sadness/anger/fear/surprise/neutral
    confidence      REAL,                            --  0..1
    raw_metrics     TEXT,                            -- JSON (расширенные метрики)
    created_at      TEXT    DEFAULT (datetime('now','utc'))
);

-- ───────────────────────────────────────────────────────────────────────
--  Результаты анализа зрачков
-- ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pupil_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES test_sessions(id),
    question_id     TEXT,
    timestamp       REAL,                            -- секунды от начала сессии
    -- Метрики зрачков
    avg_pupil_iris_ratio  REAL,                      -- среднее pupil/iris (0-1)
    left_ratio      REAL,                            -- левый глаз ratio
    right_ratio     REAL,                            -- правый глаз ratio
    dilation_level  TEXT,                            -- high_dilation/moderate_dilation/normal/constriction
    inferred_state  TEXT,                            -- stress_or_arousal/cognitive_load/calm/relaxation_or_fatigue
    anisocoria      BOOLEAN DEFAULT 0,               -- обнаружена ли разница зрачков
    anisocoria_diff REAL,                            -- |left - right|
    state_confidence REAL,                           -- 0-1
    raw_metrics     TEXT,                            -- JSON (расширенные метрики)
    created_at      TEXT DEFAULT (datetime('now','utc'))
);

-- ───────────────────────────────────────────────────────────────────────
--  Результаты оценки возраста по глазам
-- ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS eye_age_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES test_sessions(id),
    timestamp       REAL,
    -- Возраст
    estimated_age   REAL,
    lower_bound     REAL,
    upper_bound     REAL,
    -- Отдельные скоры (0=young, 1=old)
    wrinkle_score   REAL,
    bags_score      REAL,
    sclera_score    REAL,
    iris_score      REAL,
    ptosis_score    REAL,
    composite_score REAL,
    confidence      REAL,
    created_at      TEXT DEFAULT (datetime('now','utc'))
);

-- ───────────────────────────────────────────────────────────────────────
--  Совокупные оценки (comprehensive assessment)
-- ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS comprehensive_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES test_sessions(id),
    timestamp       REAL,
    -- Совокупные метрики
    estimated_age   REAL,
    age_source      TEXT,                            -- face/eye/combined
    dominant_emotion TEXT,
    overall_stress  REAL,                            -- 0-1
    stress_level    TEXT,                            -- high/moderate/low
    pupil_state     TEXT,
    detected_states TEXT,                            -- JSON ["stress","anxiety"]
    recommended_ids TEXT,                            -- JSON [1,3,5]
    warnings        TEXT,                            -- JSON
    full_report     TEXT,                            -- JSON (полный отчёт)
    created_at      TEXT DEFAULT (datetime('now','utc'))
);

-- ───────────────────────────────────────────────────────────────────────
--  Рекомендации, выданные пользователю
-- ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS recommendations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES test_sessions(id),
    method_id       INTEGER NOT NULL REFERENCES methods(id),
    reason          TEXT,                            -- Почему рекомендовали
    shown_at        TEXT    DEFAULT (datetime('now','utc')),
    user_feedback   TEXT    CHECK (user_feedback IN (
                        'helpful', 'not_helpful', 'skipped', NULL
                    ))
);

-- ───────────────────────────────────────────────────────────────────────
--  Индексы
-- ───────────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_sources_type    ON sources(type);
CREATE INDEX IF NOT EXISTS idx_sources_year    ON sources(year);
CREATE INDEX IF NOT EXISTS idx_methods_level   ON methods(evidence_level);
CREATE INDEX IF NOT EXISTS idx_fer_session     ON fer_results(session_id);
CREATE INDEX IF NOT EXISTS idx_pupil_session   ON pupil_results(session_id);
CREATE INDEX IF NOT EXISTS idx_eye_age_session ON eye_age_results(session_id);
CREATE INDEX IF NOT EXISTS idx_comp_session    ON comprehensive_results(session_id);
CREATE INDEX IF NOT EXISTS idx_recs_session    ON recommendations(session_id);
