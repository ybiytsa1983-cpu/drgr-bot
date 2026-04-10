"""
DRGR Psycho-Platform — Knowledge Base Module.

SQLite-хранилище для научных источников (sources) и методик (methods).
Предоставляет CRUD-операции и поиск по тегам / типам.

Используется для:
  • Хранения научных публикаций по FER, невербике, психокоррекции
  • Хранения методик (дыхательные, когнитивные, телесные упражнения)
  • Связки состояние → рекомендованные методики
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("drgr-psycho.kb")

_BASE_DIR = Path(__file__).resolve().parent
_SCHEMA_PATH = _BASE_DIR / "schema.sql"
_DEFAULT_DB_PATH = _BASE_DIR / "knowledge_base.db"


class KnowledgeBase:
    """
    SQLite-based knowledge base for sources and methods.

    Использование:
        kb = KnowledgeBase()
        kb.add_source(type="article", authors="Ekman P.", ...)
        sources = kb.search_sources(tags=["emotion_recognition"])
    """

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or str(_DEFAULT_DB_PATH)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        """Инициализация БД из schema.sql."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                if _SCHEMA_PATH.exists():
                    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
                conn.commit()
            finally:
                conn.close()
        logger.info("Knowledge base initialized: %s", self._db_path)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ═══════════════════════════════════════════════════════════════════
    #  SOURCES — CRUD
    # ═══════════════════════════════════════════════════════════════════

    def add_source(
        self,
        type: str,
        authors: str,
        title: str,
        year: Optional[int] = None,
        url: Optional[str] = None,
        doi: Optional[str] = None,
        tags: Optional[List[str]] = None,
        notes: Optional[str] = None,
    ) -> int:
        """Добавить источник, вернуть id."""
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        with self._lock:
            conn = self._conn()
            try:
                cur = conn.execute(
                    """INSERT INTO sources (type, year, authors, title, url, doi, tags, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (type, year, authors, title, url, doi, tags_json, notes),
                )
                conn.commit()
                return cur.lastrowid
            finally:
                conn.close()

    def get_sources(
        self,
        type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Получить источники с фильтрацией."""
        conn = self._conn()
        try:
            query = "SELECT * FROM sources WHERE 1=1"
            params: list = []
            if type:
                query += " AND type = ?"
                params.append(type)
            if tags:
                for tag in tags:
                    # Sanitize: only allow alphanumeric, underscore, hyphen
                    safe_tag = "".join(c for c in tag if c.isalnum() or c in ("_", "-"))
                    if safe_tag:
                        query += " AND tags LIKE ?"
                        params.append(f"%{safe_tag}%")
            query += " ORDER BY year DESC, id DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def get_source_by_id(self, source_id: int) -> Optional[Dict[str, Any]]:
        """Получить источник по id."""
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM sources WHERE id = ?", (source_id,)
            ).fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════════
    #  METHODS — CRUD
    # ═══════════════════════════════════════════════════════════════════

    def add_method(
        self,
        title: str,
        description: Optional[str] = None,
        evidence_level: str = "medium",
        applicable_in_app: bool = False,
        target_states: Optional[List[str]] = None,
        instructions: Optional[str] = None,
        duration_min: Optional[int] = None,
        source_ids: Optional[List[int]] = None,
    ) -> int:
        """Добавить методику, вернуть id."""
        target_json = json.dumps(target_states or [], ensure_ascii=False)
        source_json = json.dumps(source_ids or [])
        with self._lock:
            conn = self._conn()
            try:
                cur = conn.execute(
                    """INSERT INTO methods
                       (title, description, evidence_level, applicable_in_app,
                        target_states, instructions, duration_min, source_ids)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        title, description, evidence_level, int(applicable_in_app),
                        target_json, instructions, duration_min, source_json,
                    ),
                )
                conn.commit()
                return cur.lastrowid
            finally:
                conn.close()

    def get_methods(
        self,
        evidence_level: Optional[str] = None,
        target_state: Optional[str] = None,
        applicable_only: bool = False,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Получить методики с фильтрацией."""
        conn = self._conn()
        try:
            query = "SELECT * FROM methods WHERE 1=1"
            params: list = []
            if evidence_level:
                query += " AND evidence_level = ?"
                params.append(evidence_level)
            if target_state:
                # Sanitize: only allow alphanumeric, underscore, hyphen
                safe_state = "".join(c for c in target_state if c.isalnum() or c in ("_", "-"))
                if safe_state:
                    query += " AND target_states LIKE ?"
                    params.append(f"%{safe_state}%")
            if applicable_only:
                query += " AND applicable_in_app = 1"
            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def get_method_by_id(self, method_id: int) -> Optional[Dict[str, Any]]:
        """Получить методику по id."""
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM methods WHERE id = ?", (method_id,)
            ).fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════════
    #  Рекомендации: состояние → методики
    # ═══════════════════════════════════════════════════════════════════

    def recommend_methods(
        self,
        state: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Получить рекомендованные методики для данного состояния.
        Только applicable_in_app = true.
        """
        return self.get_methods(
            target_state=state,
            applicable_only=True,
            limit=limit,
        )

    # ═══════════════════════════════════════════════════════════════════
    #  Статистика
    # ═══════════════════════════════════════════════════════════════════

    def get_stats(self) -> Dict[str, Any]:
        """Статистика базы знаний."""
        conn = self._conn()
        try:
            sources_count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            methods_count = conn.execute("SELECT COUNT(*) FROM methods").fetchone()[0]
            types = conn.execute(
                "SELECT type, COUNT(*) as cnt FROM sources GROUP BY type"
            ).fetchall()
            levels = conn.execute(
                "SELECT evidence_level, COUNT(*) as cnt FROM methods GROUP BY evidence_level"
            ).fetchall()
            return {
                "sources_total": sources_count,
                "methods_total": methods_count,
                "sources_by_type": {r["type"]: r["cnt"] for r in types},
                "methods_by_level": {r["evidence_level"]: r["cnt"] for r in levels},
            }
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════════
    #  Helpers
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        # Parse JSON fields
        for key in ("tags", "target_states", "source_ids"):
            if key in d and isinstance(d[key], str):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d
