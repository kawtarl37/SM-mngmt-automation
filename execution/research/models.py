from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SourceDefinition:
    """A source the system can monitor or consult for research."""

    name: str
    source_type: str
    base_url: str
    lane: str
    credibility_score: float
    monitor_frequency: str
    notes: str = ""
    enabled: bool = True
    approval_status: str = "approved"
    added_by: str = "system"
    approved_at: str | None = None
    approved_by: str | None = None


@dataclass(frozen=True)
class ResearchTask:
    """One planned research action for a topic."""

    lane: str
    source_type: str
    query: str
    priority: int
    reason: str


@dataclass(frozen=True)
class ResearchPlan:
    """Research plan generated before content writing."""

    topic_title: str
    lane: str
    angle_type: str | None
    platform: str
    tasks: tuple[ResearchTask, ...]
    candidate_sources: tuple[SourceDefinition, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ContentBrief:
    """Portable brief that can be used by blog, newsletter, Pinterest, or app flows."""

    topic_title: str
    lane: str
    angle_type: str | None
    platform: str
    reader_problem: str
    thesis: str
    source_plan: tuple[ResearchTask, ...]
    source_candidates: tuple[SourceDefinition, ...]
    platform_sections: tuple[str, ...]
