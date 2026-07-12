from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from execution.research.models import ResearchTask


@dataclass(frozen=True)
class CollectedSource:
    """Normalized source record returned by every collector."""

    topic_title: str
    lane: str
    source_type: str
    url: str
    title: str
    credibility_score: float
    status: str = "fetched"
    notes: str = ""
    snippet: str = ""
    published_at: str | None = None
    external_id: str | None = None
    fetched_at: str = ""

    def __post_init__(self):
        if not self.fetched_at:
            object.__setattr__(self, "fetched_at", datetime.now(timezone.utc).isoformat())


class SourceCollector(Protocol):
    """Interface implemented by all research collectors."""

    source_type: str

    def collect(self, task: ResearchTask, topic_title: str, limit: int = 10) -> list[CollectedSource]:
        """Collect normalized source records for a research task."""

