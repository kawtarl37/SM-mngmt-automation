from __future__ import annotations

from datetime import datetime, timezone

from execution.db import get_connection
from execution.research.models import SourceDefinition
from execution.research.schema import ensure_research_schema


APPROVED = "approved"
PENDING = "pending_approval"
REJECTED = "rejected"


def propose_source(source: SourceDefinition, added_by: str = "system") -> int:
    """Add a new source as pending approval and create a notification."""

    ensure_research_schema()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT source_id, approval_status FROM source_registry WHERE base_url = ? AND lane = ?",
            (source.base_url, source.lane),
        )
        existing = cursor.fetchone()
        if existing:
            source_id = int(existing["source_id"])
            if existing["approval_status"] == PENDING:
                _ensure_notification(cursor, source_id, source.name)
                conn.commit()
            return source_id

        cursor.execute(
            """
            INSERT INTO source_registry
                (name, source_type, base_url, lane, credibility_score, monitor_frequency,
                 notes, enabled, approval_status, added_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source.name,
                source.source_type,
                source.base_url,
                source.lane,
                source.credibility_score,
                source.monitor_frequency,
                source.notes,
                False,
                PENDING,
                added_by,
            ),
        )
        source_id = int(cursor.lastrowid)
        _ensure_notification(cursor, source_id, source.name)
        conn.commit()
        return source_id


def approve_source(source_id: int, approved_by: str = "user") -> bool:
    """Approve a proposed source and mark its notifications resolved."""

    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE source_registry
            SET approval_status = ?, enabled = TRUE, approved_at = ?, approved_by = ?
            WHERE source_id = ?
            """,
            (APPROVED, now, approved_by, source_id),
        )
        changed = cursor.rowcount > 0
        cursor.execute(
            """
            UPDATE source_notifications
            SET status = 'resolved', resolved_at = ?
            WHERE source_id = ? AND status != 'resolved'
            """,
            (now, source_id),
        )
        conn.commit()
        return changed


def reject_source(source_id: int) -> bool:
    """Reject a proposed source and disable it."""

    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE source_registry
            SET approval_status = ?, enabled = FALSE
            WHERE source_id = ?
            """,
            (REJECTED, source_id),
        )
        changed = cursor.rowcount > 0
        cursor.execute(
            """
            UPDATE source_notifications
            SET status = 'resolved', resolved_at = ?
            WHERE source_id = ? AND status != 'resolved'
            """,
            (now, source_id),
        )
        conn.commit()
        return changed


def list_sources(status: str | None = None) -> list[dict]:
    """List registered sources, optionally filtered by approval status."""

    ensure_research_schema()
    with get_connection() as conn:
        cursor = conn.cursor()
        if status:
            cursor.execute(
                "SELECT * FROM source_registry WHERE approval_status = ? ORDER BY created_at DESC",
                (status,),
            )
        else:
            cursor.execute("SELECT * FROM source_registry ORDER BY lane, credibility_score DESC")
        return [dict(row) for row in cursor.fetchall()]


def list_approved_sources(
    lane: str | None = None,
    source_types: tuple[str, ...] | None = None,
    priority_only: bool = False,
) -> list[dict]:
    """List enabled approved sources for collector dispatch."""

    ensure_research_schema()
    clauses = ["approval_status = ?", "enabled = TRUE"]
    params: list[object] = [APPROVED]

    if lane:
        clauses.append("lane = ?")
        params.append(lane)

    if source_types:
        placeholders = ",".join("?" * len(source_types))
        clauses.append(f"source_type IN ({placeholders})")
        params.extend(source_types)

    if priority_only:
        clauses.append("priority_tier = 'priority'")

    query = (
        "SELECT * FROM source_registry WHERE "
        + " AND ".join(clauses)
        + " ORDER BY priority_tier DESC, credibility_score DESC, name ASC"
    )
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, tuple(params))
        return [dict(row) for row in cursor.fetchall()]


def list_notifications(status: str = "unread") -> list[dict]:
    """List source notifications for review surfaces."""

    ensure_research_schema()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT n.*, s.name, s.source_type, s.base_url, s.lane, s.credibility_score
            FROM source_notifications n
            LEFT JOIN source_registry s ON n.source_id = s.source_id
            WHERE n.status = ?
            ORDER BY n.created_at DESC
            """,
            (status,),
        )
        return [dict(row) for row in cursor.fetchall()]


def is_source_approved(base_url: str, lane: str) -> bool:
    """Return True when a source URL or approved source root is approved for automatic use."""

    ensure_research_schema()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT base_url, approval_status, enabled
            FROM source_registry
            WHERE lane = ? AND approval_status = ? AND enabled = TRUE
            """,
            (lane, APPROVED),
        )
        rows = [dict(row) for row in cursor.fetchall()]

    normalized = _normalize_url(base_url)
    for row in rows:
        approved_root = _normalize_url(row["base_url"])
        if normalized == approved_root or normalized.startswith(approved_root.rstrip("/") + "/"):
            return True
    return False


def _normalize_url(url: str) -> str:
    return url.split("?", 1)[0].rstrip("/")


def _ensure_notification(cursor, source_id: int, source_name: str) -> None:
    cursor.execute(
        """
        SELECT 1 FROM source_notifications
        WHERE source_id = ? AND status = 'unread'
        """,
        (source_id,),
    )
    if cursor.fetchone():
        return
    cursor.execute(
        """
        INSERT INTO source_notifications (source_id, notification_type, message)
        VALUES (?, 'source_approval_required', ?)
        """,
        (source_id, f"New research source needs approval: {source_name}"),
    )
