from __future__ import annotations

from execution.db import get_connection


CONTENT_IDEA_COLUMNS = {
    "content_lane": "TEXT",
    "angle_type": "TEXT",
    "freshness_hook": "TEXT",
    "source_hint": "TEXT",
}

TRENDY_TOPIC_COLUMNS = {
    "content_lane": "TEXT",
    "angle_type": "TEXT",
    "freshness_hook": "TEXT",
}


def ensure_editorial_schema() -> None:
    """Add editorial metadata columns to existing SQLite databases."""

    with get_connection() as conn:
        cursor = conn.cursor()
        _ensure_columns(cursor, "content_ideas", CONTENT_IDEA_COLUMNS)
        _ensure_columns(cursor, "trendy_topics", TRENDY_TOPIC_COLUMNS)
        conn.commit()


def _ensure_columns(cursor, table: str, columns: dict[str, str]) -> None:
    cursor.execute(f"PRAGMA table_info({table})")
    existing = {row["name"] for row in cursor.fetchall()}
    for name, column_type in columns.items():
        if name not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {column_type}")
