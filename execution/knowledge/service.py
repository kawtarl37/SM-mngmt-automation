from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from execution.db import get_connection
from execution.editorial.taxonomy import classify_lane
from execution.knowledge.schema import ensure_knowledge_schema


SENSITIVE_LANES = {"laws_labeling", "science_health", "restaurants_travel"}
AUTHORITATIVE_SOURCE_TYPES = {
    "official_api",
    "official_recall_page",
    "certification_body",
    "gluten_free_organization",
    "medical_research",
    "medical_article",
    "restaurant_allergen_page",
}
COMMUNITY_SOURCE_TYPES = {"community_discussion", "reddit", "subreddit"}

ENTRY_TYPES_BY_SOURCE_TYPE = {
    "brand_product_page": "product_mention",
    "retailer_product_page": "product_mention",
    "restaurant_allergen_page": "restaurant_mention",
    "tool_product_page": "app_or_tool_mention",
    "app_review_page": "app_or_tool_mention",
    "medical_research": "fact",
    "official_api": "fact",
    "official_recall_page": "warning_or_risk",
    "certification_body": "fact",
    "gluten_free_organization": "fact",
    "community_discussion": "community_sentiment",
}


def ingest_current_intelligence() -> dict[str, int]:
    """Copy accumulated research/content intelligence into normalized KB tables."""

    ensure_knowledge_schema()
    counts = {
        "entries_created": 0,
        "entries_existing": 0,
        "evidence_created": 0,
    }
    for item in _research_fact_items():
        _ingest_item(item, counts)
    for item in _research_source_items():
        _ingest_item(item, counts)
    for item in _content_brief_items():
        _ingest_item(item, counts)
    for item in _content_draft_items():
        _ingest_item(item, counts)
    for item in _trend_topic_items():
        _ingest_item(item, counts)
    for item in _trendy_topic_items():
        _ingest_item(item, counts)
    return counts


def list_knowledge_entries(
    search: str | None = None,
    lane: str | None = None,
    entry_type: str | None = None,
    source_type: str | None = None,
    quality_status: str | None = None,
    min_quality: float | None = None,
    limit: int = 100,
) -> list[dict]:
    ensure_knowledge_schema()
    clauses = []
    params: list[Any] = []
    if search:
        like = f"%{search.strip()}%"
        clauses.append("(e.claim LIKE ? OR e.summary LIKE ? OR ent.name LIKE ? OR e.topic_title LIKE ?)")
        params.extend([like, like, like, like])
    if lane:
        clauses.append("e.lane = ?")
        params.append(lane)
    if entry_type:
        clauses.append("e.entry_type = ?")
        params.append(entry_type)
    if source_type:
        clauses.append("e.source_type = ?")
        params.append(source_type)
    if quality_status:
        clauses.append("e.quality_status = ?")
        params.append(quality_status)
    if min_quality is not None:
        clauses.append("e.quality_score >= ?")
        params.append(float(min_quality))

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    safe_limit = max(1, min(int(limit), 250))
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT
                e.*,
                ent.name AS entity_name,
                ent.entity_type,
                COUNT(ev.evidence_id) AS evidence_count
            FROM knowledge_entries e
            LEFT JOIN knowledge_entities ent ON ent.entity_id = e.entity_id
            LEFT JOIN knowledge_evidence ev ON ev.entry_id = e.entry_id
            {where}
            GROUP BY e.entry_id
            ORDER BY e.reuse_allowed DESC, e.quality_score DESC, e.updated_at DESC
            LIMIT ?
            """,
            tuple(params + [safe_limit]),
        )
        return [dict(row) for row in cursor.fetchall()]


def get_knowledge_entry(entry_id: int) -> dict | None:
    ensure_knowledge_schema()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT e.*, ent.name AS entity_name, ent.entity_type
            FROM knowledge_entries e
            LEFT JOIN knowledge_entities ent ON ent.entity_id = e.entity_id
            WHERE e.entry_id = ?
            """,
            (entry_id,),
        )
        entry = cursor.fetchone()
        if not entry:
            return None
        cursor.execute(
            """
            SELECT *
            FROM knowledge_evidence
            WHERE entry_id = ?
            ORDER BY credibility_score DESC, created_at DESC
            """,
            (entry_id,),
        )
        evidence = [dict(row) for row in cursor.fetchall()]
    data = dict(entry)
    data["evidence"] = evidence
    return data


def knowledge_stats() -> dict:
    ensure_knowledge_schema()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM knowledge_entries")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM knowledge_entries WHERE reuse_allowed = TRUE")
        reusable = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM knowledge_entries WHERE quality_status = 'blocked'")
        blocked = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM knowledge_entries WHERE quality_status = 'stale'")
        stale = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM knowledge_entries WHERE quality_status = 'needs_more_evidence'")
        needs_more_evidence = cursor.fetchone()[0]
        cursor.execute(
            """
            SELECT lane, COUNT(*) AS count
            FROM knowledge_entries
            GROUP BY lane
            ORDER BY count DESC
            """
        )
        by_lane = [dict(row) for row in cursor.fetchall()]
        cursor.execute(
            """
            SELECT entry_type, COUNT(*) AS count
            FROM knowledge_entries
            GROUP BY entry_type
            ORDER BY count DESC
            """
        )
        by_type = [dict(row) for row in cursor.fetchall()]
    return {
        "total": total,
        "reusable": reusable,
        "blocked": blocked,
        "stale": stale,
        "needs_more_evidence": needs_more_evidence,
        "by_lane": by_lane,
        "by_type": by_type,
    }


def set_entry_quality_status(entry_id: int, status: str) -> bool:
    ensure_knowledge_schema()
    if status not in {"blocked", "stale", "auto_approved", "needs_more_evidence"}:
        raise ValueError(f"Unsupported knowledge status: {status}")

    if status == "auto_approved":
        entry = get_knowledge_entry(entry_id)
        if not entry:
            return False
        quality = _quality_for_entry(
            lane=entry["lane"],
            entry_type=entry["entry_type"],
            source_type=entry.get("source_type"),
            confidence_score=float(entry.get("confidence_score") or 0.0),
            credibility_score=max((float(e.get("credibility_score") or 0.0) for e in entry["evidence"]), default=0.0),
            has_evidence=bool(entry["evidence"]),
            has_snippet=any(e.get("evidence_text") for e in entry["evidence"]),
            structured_origin=bool(entry.get("originating_table")),
        )
        status = quality["quality_status"]
        reuse_allowed = quality["reuse_allowed"]
        quality_score = quality["quality_score"]
    else:
        reuse_allowed = False
        quality_score = None

    with get_connection() as conn:
        cursor = conn.cursor()
        if quality_score is None:
            cursor.execute(
                """
                UPDATE knowledge_entries
                SET quality_status = ?, reuse_allowed = ?, updated_at = CURRENT_TIMESTAMP
                WHERE entry_id = ?
                """,
                (status, reuse_allowed, entry_id),
            )
        else:
            cursor.execute(
                """
                UPDATE knowledge_entries
                SET quality_status = ?, reuse_allowed = ?, quality_score = ?, updated_at = CURRENT_TIMESTAMP
                WHERE entry_id = ?
                """,
                (status, reuse_allowed, quality_score, entry_id),
            )
        conn.commit()
        return cursor.rowcount > 0


def retrieve_reusable_knowledge(
    topic_title: str,
    lane: str,
    limit: int = 10,
    include_sentiment: bool = True,
) -> list[dict]:
    """Return quality-gated KB entries suitable for generation context."""

    ensure_knowledge_schema()
    tokens = _tokens(f"{topic_title} {lane}")
    clauses = [
        "e.reuse_allowed = TRUE",
        "e.quality_status = 'auto_approved'",
        "e.lane = ?",
    ]
    params: list[Any] = [lane]
    if not include_sentiment:
        clauses.append("e.entry_type NOT IN ('community_sentiment', 'recurring_question')")
    safe_limit = max(1, min(int(limit), 50))
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT e.*, ent.name AS entity_name, ent.entity_type
            FROM knowledge_entries e
            LEFT JOIN knowledge_entities ent ON ent.entity_id = e.entity_id
            WHERE {" AND ".join(clauses)}
            ORDER BY e.quality_score DESC, e.updated_at DESC
            LIMIT 100
            """,
            tuple(params),
        )
        rows = [dict(row) for row in cursor.fetchall()]

    scored = []
    for row in rows:
        haystack = _tokens(f"{row.get('claim')} {row.get('summary')} {row.get('entity_name')}")
        overlap = len(tokens & haystack)
        scored.append((overlap, row["quality_score"], row))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [row for _, _, row in scored[:safe_limit]]


def log_knowledge_usage(
    entry_id: int,
    asset_type: str,
    asset_id: int | None = None,
    topic_title: str | None = None,
    platform: str | None = None,
    notes: str = "",
) -> int:
    ensure_knowledge_schema()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO knowledge_usage
                (entry_id, asset_type, asset_id, topic_title, platform, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (entry_id, asset_type, asset_id, topic_title, platform, notes),
        )
        usage_id = cursor.lastrowid
        conn.commit()
        return int(usage_id)


def _ingest_item(item: dict, counts: dict[str, int]) -> None:
    quality = _quality_for_entry(
        lane=item["lane"],
        entry_type=item["entry_type"],
        source_type=item.get("source_type"),
        confidence_score=float(item.get("confidence_score") or 0.0),
        credibility_score=float(item.get("credibility_score") or 0.0),
        has_evidence=bool(item.get("source_url") or item.get("evidence_text")),
        has_snippet=bool(item.get("evidence_text")),
        structured_origin=bool(item.get("originating_table")),
    )
    normalized_key = _entry_key(item)
    entity_id = _upsert_entity(
        name=item["entity_name"],
        entity_type=item["entity_type"],
        lane=item["lane"],
    )

    with get_connection() as conn:
        cursor = conn.cursor()
        if item.get("originating_table") and item.get("originating_id") is not None:
            cursor.execute(
                """
                SELECT entry_id
                FROM knowledge_entries
                WHERE normalized_key = ?
                   OR (originating_table = ? AND originating_id = ?)
                LIMIT 1
                """,
                (normalized_key, item["originating_table"], item["originating_id"]),
            )
        else:
            cursor.execute("SELECT entry_id FROM knowledge_entries WHERE normalized_key = ?", (normalized_key,))
        existing = cursor.fetchone()
        if existing:
            entry_id = int(existing["entry_id"])
            counts["entries_existing"] += 1
            cursor.execute(
                """
                UPDATE knowledge_entries
                SET entry_type = ?, entity_id = ?, lane = ?, claim = ?, summary = ?,
                    normalized_key = ?, source_type = ?, quality_status = ?,
                    quality_score = ?, confidence_score = ?, reuse_allowed = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE entry_id = ? AND quality_status NOT IN ('blocked', 'stale')
                """,
                (
                    item["entry_type"],
                    entity_id,
                    item["lane"],
                    item["claim"],
                    item.get("summary"),
                    normalized_key,
                    item.get("source_type"),
                    quality["quality_status"],
                    quality["quality_score"],
                    item.get("confidence_score") or item.get("credibility_score") or 0.0,
                    quality["reuse_allowed"],
                    entry_id,
                ),
            )
        else:
            cursor.execute(
                """
                INSERT INTO knowledge_entries
                    (entity_id, entry_type, lane, topic_title, claim, summary,
                     normalized_key, source_type, quality_status, quality_score,
                     confidence_score, reuse_allowed, originating_table, originating_id,
                     last_verified_at, needs_recheck_after)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entity_id,
                    item["entry_type"],
                    item["lane"],
                    item.get("topic_title"),
                    item["claim"],
                    item.get("summary"),
                    normalized_key,
                    item.get("source_type"),
                    quality["quality_status"],
                    quality["quality_score"],
                    item.get("confidence_score") or item.get("credibility_score") or 0.0,
                    quality["reuse_allowed"],
                    item.get("originating_table"),
                    item.get("originating_id"),
                    item.get("fetched_at") or datetime.now(timezone.utc).isoformat(),
                    _recheck_date(item["lane"], item.get("source_type")),
                ),
            )
            entry_id = int(cursor.lastrowid)
            counts["entries_created"] += 1

        if _insert_evidence(cursor, entry_id, item):
            counts["evidence_created"] += 1
        conn.commit()


def _insert_evidence(cursor, entry_id: int, item: dict) -> bool:
    source_url = item.get("source_url") or f"internal://{item.get('originating_table')}/{item.get('originating_id')}"
    cursor.execute(
        """
        SELECT 1
        FROM knowledge_evidence
        WHERE entry_id = ? AND COALESCE(source_url, '') = COALESCE(?, '')
        """,
        (entry_id, source_url),
    )
    if cursor.fetchone():
        return False
    cursor.execute(
        """
        INSERT INTO knowledge_evidence
            (entry_id, source_url, source_type, title, evidence_text, credibility_score,
             fetched_at, research_source_id, research_fact_id, content_draft_id, trend_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry_id,
            source_url,
            item.get("source_type"),
            item.get("title") or item.get("claim"),
            item.get("evidence_text") or item.get("summary"),
            item.get("credibility_score") or item.get("confidence_score") or 0.0,
            item.get("fetched_at"),
            item.get("research_source_id"),
            item.get("research_fact_id"),
            item.get("content_draft_id"),
            item.get("trend_id"),
        ),
    )
    return True


def _quality_for_entry(
    lane: str,
    entry_type: str,
    source_type: str | None,
    confidence_score: float,
    credibility_score: float,
    has_evidence: bool,
    has_snippet: bool,
    structured_origin: bool,
) -> dict:
    source_type = source_type or "internal_structured"
    score = 0.0
    if has_evidence:
        score += 0.25
    if has_snippet:
        score += 0.15
    if structured_origin:
        score += 0.10
    score += min(max(confidence_score, 0.0), 1.0) * 0.25
    score += min(max(credibility_score, 0.0), 1.0) * 0.25
    if _is_authoritative_source(source_type):
        score += 0.10
    if _is_community_source(source_type) or entry_type in {"community_sentiment", "recurring_question"}:
        score = min(score, 0.78)

    score = round(min(score, 1.0), 3)
    threshold = 0.72 if lane in SENSITIVE_LANES else 0.55
    strong_sensitive_source = _is_authoritative_source(source_type)
    is_community = entry_type in {"community_sentiment", "recurring_question"} or _is_community_source(source_type)

    if lane in SENSITIVE_LANES and not is_community and not strong_sensitive_source:
        return {"quality_score": score, "quality_status": "needs_more_evidence", "reuse_allowed": False}
    if score >= threshold and (has_evidence or structured_origin):
        return {"quality_score": score, "quality_status": "auto_approved", "reuse_allowed": True}
    return {"quality_score": score, "quality_status": "needs_more_evidence", "reuse_allowed": False}


def _research_fact_items() -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                f.*,
                rs.lane,
                rs.source_type,
                rs.title AS source_title,
                rs.credibility_score,
                rs.fetched_at
            FROM research_facts f
            LEFT JOIN research_sources rs ON rs.url = f.source_url AND rs.topic_title = f.topic_title
            """
        )
        rows = [dict(row) for row in cursor.fetchall()]
    items = []
    for row in rows:
        source_type = row.get("source_type") or "research_fact"
        lane = row.get("lane") or classify_lane(row["topic_title"])
        items.append(
            {
                "entry_type": "community_sentiment" if _is_community_source(source_type) else "fact",
                "lane": lane,
                "topic_title": row["topic_title"],
                "entity_name": _entity_from_text(row["topic_title"]),
                "entity_type": _entity_type_for_entry("fact", source_type),
                "claim": row["claim"],
                "summary": row.get("evidence_text"),
                "source_type": source_type,
                "source_url": row["source_url"],
                "title": row.get("source_title") or row["claim"],
                "evidence_text": row.get("evidence_text"),
                "confidence_score": row.get("confidence_score") or 0.0,
                "credibility_score": row.get("credibility_score") or row.get("confidence_score") or 0.0,
                "fetched_at": row.get("fetched_at") or row.get("created_at"),
                "originating_table": "research_facts",
                "originating_id": row["fact_id"],
                "research_fact_id": row["fact_id"],
            }
        )
    return items


def _research_source_items() -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM research_sources")
        rows = [dict(row) for row in cursor.fetchall()]
    items = []
    for row in rows:
        entry_type = ENTRY_TYPES_BY_SOURCE_TYPE.get(row["source_type"], "fact")
        items.append(
            {
                "entry_type": entry_type,
                "lane": row["lane"],
                "topic_title": row["topic_title"],
                "entity_name": _entity_from_text(row.get("title") or row["topic_title"]),
                "entity_type": _entity_type_for_entry(entry_type, row["source_type"]),
                "claim": row.get("title") or row["topic_title"],
                "summary": row.get("snippet") or row.get("notes"),
                "source_type": row["source_type"],
                "source_url": row["url"],
                "title": row.get("title"),
                "evidence_text": row.get("snippet") or row.get("notes"),
                "confidence_score": row.get("credibility_score") or 0.0,
                "credibility_score": row.get("credibility_score") or 0.0,
                "fetched_at": row.get("fetched_at") or row.get("created_at"),
                "originating_table": "research_sources",
                "originating_id": row["research_source_id"],
                "research_source_id": row["research_source_id"],
            }
        )
    return items


def _content_brief_items() -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM content_briefs")
        rows = [dict(row) for row in cursor.fetchall()]
    return [
        {
            "entry_type": "tip_or_system",
            "lane": row["lane"],
            "topic_title": row["topic_title"],
            "entity_name": _entity_from_text(row["topic_title"]),
            "entity_type": "community_theme",
            "claim": row.get("thesis") or row["topic_title"],
            "summary": row.get("reader_problem"),
            "source_type": "content_brief",
            "source_url": f"internal://content_briefs/{row['brief_id']}",
            "title": row["topic_title"],
            "evidence_text": row.get("reader_problem") or row.get("thesis"),
            "confidence_score": 0.62,
            "credibility_score": 0.62,
            "fetched_at": row.get("created_at"),
            "originating_table": "content_briefs",
            "originating_id": row["brief_id"],
        }
        for row in rows
    ]


def _content_draft_items() -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM content_drafts")
        rows = [dict(row) for row in cursor.fetchall()]
    items = []
    for row in rows:
        source_urls = _json_list(row.get("source_urls_json"))
        content = _json_dict(row.get("content_json"))
        entry_type = "tip_or_system" if row.get("platform") != "app" else "fact"
        body = _draft_excerpt(content) or row.get("dek")
        items.append(
            {
                "entry_type": entry_type,
                "lane": row["lane"],
                "topic_title": row["topic_title"],
                "entity_name": _entity_from_text(row["topic_title"]),
                "entity_type": "community_theme",
                "claim": row["title"],
                "summary": row.get("dek"),
                "source_type": "content_draft",
                "source_url": source_urls[0] if source_urls else f"internal://content_drafts/{row['draft_id']}",
                "title": row["title"],
                "evidence_text": body,
                "confidence_score": 0.58 if source_urls else 0.45,
                "credibility_score": 0.58 if source_urls else 0.45,
                "fetched_at": row.get("created_at"),
                "originating_table": "content_drafts",
                "originating_id": row["draft_id"],
                "content_draft_id": row["draft_id"],
            }
        )
    return items


def _trend_topic_items() -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trend_topics")
        rows = [dict(row) for row in cursor.fetchall()]
    items = []
    for row in rows:
        text = f"{row.get('title') or ''} {row.get('body') or ''}"
        lane = classify_lane(text)
        source_type = row.get("source") or "community_discussion"
        entry_type = "fact" if _is_medical_source(source_type) else "community_sentiment"
        items.append(
            {
                "entry_type": entry_type,
                "lane": lane,
                "topic_title": row["title"],
                "entity_name": _entity_from_text(row["title"]),
                "entity_type": _entity_type_for_entry(entry_type, source_type),
                "claim": row["title"],
                "summary": row.get("body"),
                "source_type": source_type,
                "source_url": f"internal://trend_topics/{row['topic_id']}",
                "title": row["title"],
                "evidence_text": row.get("body"),
                "confidence_score": min(float(row.get("relevance") or 0.0), 1.0),
                "credibility_score": 0.42,
                "fetched_at": row.get("fetched_at"),
                "originating_table": "trend_topics",
                "originating_id": row["topic_id"],
                "trend_id": row["topic_id"],
            }
        )
    return items


def _trendy_topic_items() -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trendy_topics")
        rows = [dict(row) for row in cursor.fetchall()]
    items = []
    for row in rows:
        source = row.get("source") or "trend_synthesizer"
        lane = row.get("content_lane") or classify_lane(f"{row['title']} {row.get('details') or ''}")
        is_community = "reddit" in source.lower() or "community" in source.lower()
        is_medical = _is_medical_source(source)
        items.append(
            {
                "entry_type": "community_sentiment" if is_community else "fact" if is_medical else "recurring_question",
                "lane": lane,
                "topic_title": row["title"],
                "entity_name": _entity_from_text(row["title"]),
                "entity_type": "community_theme",
                "claim": row["title"],
                "summary": row.get("details"),
                "source_type": source,
                "source_url": f"internal://trendy_topics/{row['topic_id']}",
                "title": row["title"],
                "evidence_text": row.get("details"),
                "confidence_score": min(float(row.get("relevance_score") or 0.0), 1.0),
                "credibility_score": 0.50,
                "fetched_at": row.get("created_at"),
                "originating_table": "trendy_topics",
                "originating_id": row["topic_id"],
                "trend_id": row["topic_id"],
            }
        )
    return items


def _upsert_entity(name: str, entity_type: str, lane: str) -> int:
    normalized = _normalize_text(name)[:160] or "unknown"
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT entity_id FROM knowledge_entities WHERE normalized_name = ?", (normalized,))
        row = cursor.fetchone()
        if row:
            return int(row["entity_id"])
        cursor.execute(
            """
            INSERT INTO knowledge_entities (name, normalized_name, entity_type, primary_lane)
            VALUES (?, ?, ?, ?)
            """,
            (name[:180], normalized, entity_type, lane),
        )
        entity_id = int(cursor.lastrowid)
        conn.commit()
        return entity_id


def _entry_key(item: dict) -> str:
    raw = "|".join(
        [
            item.get("entry_type") or "",
            item.get("lane") or "",
            item.get("entity_name") or "",
            item.get("claim") or "",
            item.get("source_url") or "",
        ]
    )
    return hashlib.sha256(_normalize_text(raw).encode("utf-8")).hexdigest()


def _entity_from_text(text: str | None) -> str:
    if not text:
        return "Unknown"
    cleaned = re.sub(r"\s+", " ", text).strip()
    for sep in (":", " vs ", " versus ", "-", "?", "|"):
        if sep in cleaned.lower():
            part = re.split(re.escape(sep), cleaned, flags=re.IGNORECASE)[0].strip()
            if len(part) >= 3:
                return part[:120]
    words = cleaned.split()
    return " ".join(words[:6])[:120]


def _entity_type_for_entry(entry_type: str, source_type: str | None) -> str:
    if entry_type == "product_mention":
        return "product"
    if entry_type == "restaurant_mention":
        return "restaurant"
    if entry_type == "app_or_tool_mention":
        return "tool_or_app"
    if _is_medical_source(source_type):
        return "study"
    if source_type in {"official_api", "official_recall_page", "certification_body"}:
        return "rule_or_recall"
    return "community_theme"


def _is_authoritative_source(source_type: str | None) -> bool:
    normalized = (source_type or "").lower()
    return normalized in AUTHORITATIVE_SOURCE_TYPES or "pubmed" in normalized


def _is_medical_source(source_type: str | None) -> bool:
    normalized = (source_type or "").lower()
    return normalized in {"medical_research", "medical_article"} or "pubmed" in normalized


def _is_community_source(source_type: str | None) -> bool:
    normalized = (source_type or "").lower()
    return normalized in COMMUNITY_SOURCE_TYPES or "reddit" in normalized or "community" in normalized


def _recheck_date(lane: str, source_type: str | None) -> str:
    days = 30 if lane in SENSITIVE_LANES else 90
    if source_type in COMMUNITY_SOURCE_TYPES or source_type in {"trend_topics", "trendy_topics"}:
        days = 45
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 2}


def _json_list(value: str | None) -> list:
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _json_dict(value: str | None) -> dict:
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _draft_excerpt(content: dict) -> str:
    sections = content.get("sections") or []
    parts = []
    for section in sections[:2]:
        if isinstance(section, dict):
            parts.append(section.get("body") or "")
    return "\n".join(part for part in parts if part).strip()
