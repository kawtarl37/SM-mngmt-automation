from __future__ import annotations

from execution.db import get_connection
from execution.research.collectors.base import CollectedSource
from execution.research.schema import ensure_research_schema


def save_collected_sources(sources: list[CollectedSource]) -> int:
    """Persist collected sources, de-duping by topic and URL."""

    if not sources:
        return 0

    ensure_research_schema()
    inserted = 0
    with get_connection() as conn:
        cursor = conn.cursor()
        for source in sources:
            cursor.execute(
                "SELECT 1 FROM research_sources WHERE topic_title = ? AND url = ?",
                (source.topic_title, source.url),
            )
            if cursor.fetchone():
                continue
            cursor.execute(
                """
                INSERT INTO research_sources
                    (topic_title, lane, source_type, url, title, credibility_score,
                     fetched_at, status, notes, snippet, published_at, external_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source.topic_title,
                    source.lane,
                    source.source_type,
                    source.url,
                    source.title,
                    source.credibility_score,
                    source.fetched_at,
                    source.status,
                    source.notes,
                    source.snippet,
                    source.published_at,
                    source.external_id,
                ),
            )
            inserted += 1
        conn.commit()
    return inserted


def save_research_fact(
    topic_title: str,
    source_url: str,
    claim: str,
    evidence_text: str,
    confidence_score: float,
) -> int:
    """Persist one extracted fact/claim from a collected source."""

    ensure_research_schema()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO research_facts
                (topic_title, source_url, claim, evidence_text, confidence_score)
            VALUES (?, ?, ?, ?, ?)
            """,
            (topic_title, source_url, claim, evidence_text, confidence_score),
        )
        fact_id = cursor.lastrowid
        conn.commit()
        return int(fact_id)


def save_fact_from_source(source: CollectedSource) -> int | None:
    """Create a conservative fact from a normalized source snippet."""

    if not source.snippet:
        return None
    return save_research_fact(
        topic_title=source.topic_title,
        source_url=source.url,
        claim=source.title,
        evidence_text=source.snippet,
        confidence_score=source.credibility_score,
    )

