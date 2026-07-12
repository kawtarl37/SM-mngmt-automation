from __future__ import annotations

from datetime import datetime, timezone

from execution.db import get_connection
from execution.research.schema import ensure_research_schema
from execution.research.source_registry import DEFAULT_SOURCE_REGISTRY


def seed_source_registry() -> int:
    """Seed default monitored sources. Existing name+lane pairs are left unchanged."""

    ensure_research_schema()
    inserted = 0
    with get_connection() as conn:
        cursor = conn.cursor()
        for source in DEFAULT_SOURCE_REGISTRY:
            cursor.execute(
                "SELECT source_id FROM source_registry WHERE name = ? AND lane = ?",
                (source.name, source.lane),
            )
            existing = cursor.fetchone()
            if existing:
                cursor.execute(
                    """
                    UPDATE source_registry
                    SET approval_status = 'approved',
                        enabled = TRUE,
                        approved_at = COALESCE(approved_at, ?),
                        approved_by = COALESCE(approved_by, 'system')
                    WHERE source_id = ?
                    """,
                    (datetime.now(timezone.utc).isoformat(), existing["source_id"]),
                )
                continue
            cursor.execute(
                """
                INSERT INTO source_registry
                    (name, source_type, base_url, lane, credibility_score,
                     monitor_frequency, notes, enabled, approval_status,
                     added_by, approved_at, approved_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source.name,
                    source.source_type,
                    source.base_url,
                    source.lane,
                    source.credibility_score,
                    source.monitor_frequency,
                    source.notes,
                    source.enabled,
                    source.approval_status,
                    source.added_by,
                    source.approved_at or datetime.now(timezone.utc).isoformat(),
                    source.approved_by or "system",
                ),
            )
            inserted += 1
        conn.commit()
    return inserted


if __name__ == "__main__":
    count = seed_source_registry()
    print(f"Seeded {count} research sources.")
