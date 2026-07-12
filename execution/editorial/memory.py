from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from execution.db import get_connection


@dataclass(frozen=True)
class PublishedTopic:
    title: str
    source_table: str
    status: str | None
    created_at: str | None


STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "best",
    "easy",
    "for",
    "free",
    "from",
    "gf",
    "gluten",
    "glutenfree",
    "gluten-free",
    "guide",
    "how",
    "in",
    "is",
    "make",
    "of",
    "on",
    "the",
    "this",
    "to",
    "with",
    "your",
}


def normalize_text(value: str) -> str:
    """Normalize a title for lexical novelty checks."""

    words = re.findall(r"[a-z0-9]+", value.lower().replace("-", " "))
    return " ".join(word for word in words if word not in STOP_WORDS)


def token_set(value: str) -> set[str]:
    return set(normalize_text(value).split())


def jaccard_similarity(left: str, right: str) -> float:
    """Return a simple similarity score between two titles."""

    left_tokens = token_set(left)
    right_tokens = token_set(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def get_recent_topic_memory(limit: int = 150) -> list[PublishedTopic]:
    """Collect recent titles across generated surfaces to discourage repetition."""

    rows: list[PublishedTopic] = []
    with get_connection() as conn:
        cursor = conn.cursor()
        queries = (
            ("blogs", "SELECT title, status, created_at FROM blogs ORDER BY created_at DESC LIMIT ?"),
            (
                "generated_pins",
                "SELECT title, status, created_at FROM generated_pins ORDER BY created_at DESC LIMIT ?",
            ),
            (
                "trendy_topics",
                "SELECT title, status, created_at FROM trendy_topics ORDER BY created_at DESC LIMIT ?",
            ),
            (
                "generated_recipes",
                "SELECT title, status, created_at FROM generated_recipes ORDER BY created_at DESC LIMIT ?",
            ),
        )
        for source_table, query in queries:
            cursor.execute(query, (limit,))
            for row in cursor.fetchall():
                rows.append(
                    PublishedTopic(
                        title=row["title"],
                        source_table=source_table,
                        status=row["status"],
                        created_at=row["created_at"],
                    )
                )

    rows.sort(key=lambda item: item.created_at or "", reverse=True)
    return rows[:limit]


def novelty_score(title: str, memory: list[PublishedTopic] | None = None) -> float:
    """Score how different a proposed title is from recent generated content."""

    memory = memory if memory is not None else get_recent_topic_memory()
    if not memory:
        return 1.0

    max_similarity = max((jaccard_similarity(title, item.title) for item in memory), default=0.0)
    return max(0.0, 1.0 - max_similarity)


def memory_prompt_block(limit: int = 60) -> str:
    """Return recent generated titles for prompt-level anti-repetition."""

    memory = get_recent_topic_memory(limit=limit)
    if not memory:
        return "No recent generated titles found."

    lines = []
    for item in memory:
        status = f", status={item.status}" if item.status else ""
        lines.append(f"- {item.title} ({item.source_table}{status})")
    return "\n".join(lines)


def current_month_label() -> str:
    """Keep prompts grounded in the current editorial calendar month."""

    return datetime.utcnow().strftime("%B %Y")

