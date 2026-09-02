from __future__ import annotations

from execution.db import get_connection


def ensure_knowledge_schema() -> None:
    """Create normalized knowledge tables used by the intelligence engine."""

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_entities (
                entity_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                normalized_name TEXT NOT NULL UNIQUE,
                entity_type TEXT NOT NULL,
                primary_lane TEXT,
                aliases_json TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_entries (
                entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id INTEGER,
                entry_type TEXT NOT NULL,
                lane TEXT NOT NULL,
                topic_title TEXT,
                claim TEXT NOT NULL,
                summary TEXT,
                normalized_key TEXT NOT NULL UNIQUE,
                source_type TEXT,
                quality_status TEXT DEFAULT 'needs_more_evidence',
                quality_score REAL DEFAULT 0.0,
                confidence_score REAL DEFAULT 0.0,
                reuse_allowed BOOLEAN DEFAULT FALSE,
                originating_table TEXT,
                originating_id INTEGER,
                last_verified_at TIMESTAMP,
                needs_recheck_after TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(entity_id) REFERENCES knowledge_entities(entity_id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_evidence (
                evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id INTEGER NOT NULL,
                source_url TEXT,
                source_type TEXT,
                title TEXT,
                evidence_text TEXT,
                credibility_score REAL DEFAULT 0.0,
                fetched_at TIMESTAMP,
                research_source_id INTEGER,
                research_fact_id INTEGER,
                content_draft_id INTEGER,
                trend_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(entry_id) REFERENCES knowledge_entries(entry_id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_usage (
                usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id INTEGER NOT NULL,
                asset_type TEXT NOT NULL,
                asset_id INTEGER,
                topic_title TEXT,
                platform TEXT,
                notes TEXT,
                used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(entry_id) REFERENCES knowledge_entries(entry_id)
            )
            """
        )
        _ensure_columns(
            cursor,
            "knowledge_entries",
            {
                "source_type": "TEXT",
                "confidence_score": "REAL DEFAULT 0.0",
                "originating_table": "TEXT",
                "originating_id": "INTEGER",
                "last_verified_at": "TIMESTAMP",
                "needs_recheck_after": "TIMESTAMP",
                "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            },
        )
        _ensure_columns(
            cursor,
            "knowledge_evidence",
            {
                "research_source_id": "INTEGER",
                "research_fact_id": "INTEGER",
                "content_draft_id": "INTEGER",
                "trend_id": "INTEGER",
            },
        )
        conn.commit()


def _ensure_columns(cursor, table: str, columns: dict[str, str]) -> None:
    cursor.execute(f"PRAGMA table_info({table})")
    existing = {row["name"] for row in cursor.fetchall()}
    for name, column_type in columns.items():
        if name not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {column_type}")

