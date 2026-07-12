from __future__ import annotations

from dataclasses import dataclass, field

from execution.editorial.platforms import PLATFORMS_BY_KEY
from execution.research.models import ContentBrief


@dataclass(frozen=True)
class PlatformPackage:
    """A structured package ready for a writer, newsletter tool, pin flow, or app."""

    platform: str
    topic_title: str
    lane: str
    angle_type: str | None
    sections: dict[str, str]
    source_urls: tuple[str, ...] = field(default_factory=tuple)


def package_for_platform(brief: ContentBrief, sources: list[dict]) -> PlatformPackage:
    """Convert a portable brief and sources into platform-specific sections."""

    platform = PLATFORMS_BY_KEY.get(brief.platform, PLATFORMS_BY_KEY["blog"])
    source_urls = tuple(_source_url(source) for source in sources if _source_url(source))
    source_summary = _source_summary(sources)

    section_builders = {
        "specific_hook": lambda: _specific_hook(brief),
        "reader_problem": lambda: brief.reader_problem,
        "verified_context": lambda: source_summary,
        "practical_steps": lambda: _practical_steps(brief),
        "claire_take": lambda: _claire_take(brief),
        "next_action": lambda: _next_action(brief),
        "subject_line": lambda: _subject_line(brief),
        "opening_note": lambda: _specific_hook(brief),
        "top_takeaway": lambda: _top_takeaway(brief, sources),
        "quick_hits": lambda: source_summary,
        "recommended_action": lambda: _next_action(brief),
        "pin_title": lambda: brief.topic_title[:70],
        "pin_description": lambda: _top_takeaway(brief, sources)[:450],
        "visual_concept": lambda: _visual_concept(brief),
        "destination_url_plan": lambda: "Link to the final approved blog or app topic page.",
        "card_title": lambda: brief.topic_title[:90],
        "summary": lambda: _top_takeaway(brief, sources),
        "source_confidence": lambda: _source_confidence(sources),
        "tags": lambda: f"{brief.lane}, {brief.angle_type or 'general'}, gluten-free",
        "action_items": lambda: _next_action(brief),
    }

    sections = {}
    for section in platform.required_sections:
        builder = section_builders.get(section, lambda value=section: f"TODO: {value}")
        sections[section] = builder()

    return PlatformPackage(
        platform=platform.key,
        topic_title=brief.topic_title,
        lane=brief.lane,
        angle_type=brief.angle_type,
        sections=sections,
        source_urls=source_urls,
    )


def _source_url(source: dict) -> str:
    return str(source.get("url") or "")


def _source_summary(sources: list[dict]) -> str:
    usable = [source for source in sources if source.get("status") != "failed"]
    failed = [source for source in sources if source.get("status") == "failed"]
    lines = []
    for source in usable[:5]:
        lines.append(f"- {source.get('title')}: {source.get('snippet') or source.get('notes')}")
    for source in failed[:3]:
        lines.append(f"- Source check failed: {source.get('title')} ({source.get('notes')})")
    return "\n".join(lines) if lines else "No collected sources yet."


def _specific_hook(brief: ContentBrief) -> str:
    return (
        f"Today's question: {brief.topic_title}. The short version is that gluten-free life "
        "gets easier when the source-checking happens before panic-shopping, not during it."
    )


def _practical_steps(brief: ContentBrief) -> str:
    return (
        "Check the official source first, compare it with current product/menu/app details, "
        "then turn the finding into one concrete reader action."
    )


def _claire_take(brief: ContentBrief) -> str:
    return (
        f"Claire's take: this is a {brief.lane.replace('_', ' ')} topic, so useful beats dramatic. "
        "The goal is not to make readers suspicious of everything. It is to make the next decision less annoying."
    )


def _next_action(brief: ContentBrief) -> str:
    return "Verify the current official page before publishing, then draft for the selected platform."


def _subject_line(brief: ContentBrief) -> str:
    return f"About {brief.topic_title}..."


def _top_takeaway(brief: ContentBrief, sources: list[dict]) -> str:
    if sources:
        best = next((source for source in sources if source.get("status") != "failed"), sources[0])
        return f"The main thing to know: {best.get('title')}. Verify the source before turning it into advice."
    return brief.thesis


def _visual_concept(brief: ContentBrief) -> str:
    return f"A clear, vertical visual showing the practical gluten-free decision behind: {brief.topic_title}."


def _source_confidence(sources: list[dict]) -> str:
    if not sources:
        return "no_sources"
    usable_scores = [
        float(source.get("credibility_score") or 0)
        for source in sources
        if source.get("status") != "failed"
    ]
    if not usable_scores:
        return "blocked_or_failed"
    average = sum(usable_scores) / len(usable_scores)
    if average >= 0.85:
        return "high"
    if average >= 0.65:
        return "medium"
    return "low"

