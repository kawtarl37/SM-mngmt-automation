from __future__ import annotations

from execution.db import get_connection


def ensure_research_schema() -> None:
    """Create research/source tables used by modular content workflows."""

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS source_registry (
                source_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                source_type TEXT NOT NULL,
                base_url TEXT NOT NULL,
                lane TEXT NOT NULL,
                credibility_score REAL DEFAULT 0.0,
                monitor_frequency TEXT,
                notes TEXT,
                enabled BOOLEAN DEFAULT TRUE,
                approval_status TEXT DEFAULT 'pending_approval',
                added_by TEXT DEFAULT 'system',
                approved_at TIMESTAMP,
                approved_by TEXT,
                content_angle TEXT,
                best_home TEXT,
                fact_check_required BOOLEAN DEFAULT TRUE,
                priority_tier TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        _ensure_columns(
            cursor,
            "source_registry",
            {
                "approval_status": "TEXT DEFAULT 'pending_approval'",
                "added_by": "TEXT DEFAULT 'system'",
                "approved_at": "TIMESTAMP",
                "approved_by": "TEXT",
                "content_angle": "TEXT",
                "best_home": "TEXT",
                "fact_check_required": "BOOLEAN DEFAULT TRUE",
                "priority_tier": "TEXT",
            },
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS source_notifications (
                notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER,
                notification_type TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT DEFAULT 'unread',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                resolved_at TIMESTAMP,
                FOREIGN KEY(source_id) REFERENCES source_registry(source_id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS research_queries (
                query_id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_title TEXT NOT NULL,
                lane TEXT NOT NULL,
                angle_type TEXT,
                platform TEXT NOT NULL,
                source_type TEXT NOT NULL,
                query_text TEXT NOT NULL,
                priority INTEGER DEFAULT 1,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS research_sources (
                research_source_id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_title TEXT NOT NULL,
                lane TEXT NOT NULL,
                source_type TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT,
                credibility_score REAL DEFAULT 0.0,
                fetched_at TIMESTAMP,
                status TEXT DEFAULT 'planned',
                notes TEXT,
                snippet TEXT,
                published_at TIMESTAMP,
                external_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS research_facts (
                fact_id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_title TEXT NOT NULL,
                source_url TEXT NOT NULL,
                claim TEXT NOT NULL,
                evidence_text TEXT,
                confidence_score REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS content_briefs (
                brief_id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_title TEXT NOT NULL,
                lane TEXT NOT NULL,
                angle_type TEXT,
                platform TEXT NOT NULL,
                reader_problem TEXT,
                thesis TEXT,
                source_plan_json TEXT NOT NULL,
                source_candidates_json TEXT NOT NULL,
                platform_sections_json TEXT NOT NULL,
                status TEXT DEFAULT 'planned',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS content_drafts (
                draft_id INTEGER PRIMARY KEY AUTOINCREMENT,
                brief_id INTEGER,
                topic_title TEXT NOT NULL,
                lane TEXT NOT NULL,
                angle_type TEXT,
                platform TEXT NOT NULL,
                title TEXT NOT NULL,
                dek TEXT,
                content_json TEXT NOT NULL,
                source_urls_json TEXT NOT NULL,
                status TEXT DEFAULT 'pending_review',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                approved_at TIMESTAMP,
                approved_by TEXT,
                rejection_reason TEXT,
                FOREIGN KEY(brief_id) REFERENCES content_briefs(brief_id)
            )
            """
        )
        _ensure_columns(
            cursor,
            "research_sources",
            {
                "snippet": "TEXT",
                "published_at": "TIMESTAMP",
                "external_id": "TEXT",
            },
        )
        _ensure_columns(
            cursor,
            "content_drafts",
            {
                "approved_at": "TIMESTAMP",
                "approved_by": "TEXT",
                "rejection_reason": "TEXT",
            },
        )
        conn.commit()


def _ensure_columns(cursor, table: str, columns: dict[str, str]) -> None:
    cursor.execute(f"PRAGMA table_info({table})")
    existing = {row["name"] for row in cursor.fetchall()}
    for name, column_type in columns.items():
        if name not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {column_type}")
