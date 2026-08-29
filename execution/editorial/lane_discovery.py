"""Grounds topic-idea generation in real, current information.

Before this module existed, lane-scoped idea generation (lane_content_service)
was pure LLM brainstorming from the lane taxonomy description plus recent-title
memory -- nothing actually looked up what's currently happening in a lane
before proposing a topic. discover_lane_topics() closes that gap: it runs the
same research collectors used for single-topic research (research_runner)
proactively across a lane's whole source mix to gather current raw signals,
then has the LLM turn those real signals into ideas, each one tied back to
the discovered URL(s) it's actually based on.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from execution.config import PROMPTS_DIR
from execution.editorial.memory import current_month_label, memory_prompt_block
from execution.editorial.taxonomy import LANES_BY_KEY, ContentLane
from execution.models import IdeaGenerationResponse
from execution.research.models import ResearchTask
from execution.research.planner import LANE_SOURCE_TYPES, _build_query
from execution.research.research_runner import collect_and_gate_sources
from execution.research.schema import ensure_research_schema
from execution.research.store import save_collected_sources, save_fact_from_source
from execution.utils.llm_client import LLMClient
from execution.utils.logger import setup_logger

logger = setup_logger("lane_discovery")

DEFAULT_SIGNAL_LIMIT = 5


def _require_lane(lane_key: str) -> ContentLane:
    lane = LANES_BY_KEY.get((lane_key or "").strip())
    if not lane:
        valid = ", ".join(sorted(LANES_BY_KEY))
        raise ValueError(f"Unknown content lane '{lane_key}'. Valid lanes: {valid}")
    return lane


def _discovery_tasks(lane: ContentLane) -> list[ResearchTask]:
    """Build a lane-wide scan (not a single-topic plan): the same source_type
    mix planner.py would use for a topic in this lane, seeded with the lane's
    own label/keywords so collectors surface "what's current here" rather
    than research for one already-chosen title."""

    source_types = LANE_SOURCE_TYPES.get(lane.key, LANE_SOURCE_TYPES["community_questions"])
    seed_topic = f"{lane.label}: {', '.join(lane.keywords[:5])}"
    return [
        ResearchTask(
            lane=lane.key,
            source_type=source_type,
            query=_build_query(seed_topic, lane.key, source_type),
            priority=index,
            reason=reason,
        )
        for index, (source_type, reason) in enumerate(source_types, start=1)
    ]


def discover_lane_signals(lane_key: str, limit_per_task: int = DEFAULT_SIGNAL_LIMIT, persist: bool = True) -> dict:
    """Run research collectors across a lane's source mix and gate results
    through the same source-approval flow as single-topic research."""

    ensure_research_schema()
    lane = _require_lane(lane_key)
    tasks = _discovery_tasks(lane)
    seed_topic = f"{lane.label} discovery scan"
    sources, pending_sources = collect_and_gate_sources(
        tasks, topic_title=seed_topic, limit_per_task=limit_per_task, persist=persist
    )

    saved_sources = save_collected_sources(sources) if persist else 0
    saved_facts = 0
    if persist:
        for source in sources:
            if save_fact_from_source(source):
                saved_facts += 1

    return {
        "lane": lane.key,
        "signal_count": len(sources),
        "saved_sources": saved_sources,
        "saved_facts": saved_facts,
        "signals": [asdict(source) for source in sources],
        "pending_sources": pending_sources,
    }


def discover_lane_topics(
    lane_key: str,
    idea_count: int = 3,
    limit_per_task: int = DEFAULT_SIGNAL_LIMIT,
    topic_hint: str | None = None,
    persist: bool = True,
) -> dict:
    """Discover real current signals for a lane, then have the LLM turn them
    into grounded content ideas -- each one tied back to the discovered
    item(s) it's actually based on, not general knowledge."""

    lane = _require_lane(lane_key)
    discovery = discover_lane_signals(lane_key, limit_per_task=limit_per_task, persist=persist)

    response = _generate_grounded_ideas(lane, idea_count, discovery["signals"], topic_hint)

    # Local import: lane_content_service imports draft_generator which imports
    # research_runner -- importing it at module level here would risk a cycle
    # since lane_content_service will import discover_lane_topics from us.
    from execution.editorial.lane_content_service import _idea_to_dict, _save_lane_ideas

    saved_ideas = _save_lane_ideas(response.ideas) if persist else [_idea_to_dict(idea) for idea in response.ideas]

    return {
        "lane": lane.key,
        "generation_mode": "llm",
        "persisted": persist,
        "signal_count": discovery["signal_count"],
        "pending_source_count": len(discovery["pending_sources"]),
        "idea_count": len(saved_ideas),
        "ideas": saved_ideas,
    }


def _generate_grounded_ideas(
    lane: ContentLane,
    idea_count: int,
    signals: list[dict],
    topic_hint: str | None,
) -> IdeaGenerationResponse:
    system_prompt = (PROMPTS_DIR / "brand_system_prompt.txt").read_text(encoding="utf-8")
    prompt_template = (PROMPTS_DIR / "lane_discovery_generation.txt").read_text(encoding="utf-8")
    user_prompt = prompt_template.format(
        idea_count=max(1, int(idea_count)),
        current_month=current_month_label(),
        lane_key=lane.key,
        lane_label=lane.label,
        lane_description=lane.description,
        discovered_signals=_signals_prompt_block(signals),
        recent_titles=memory_prompt_block(limit=80),
        topic_hint=(topic_hint or "None supplied."),
    )
    return LLMClient().generate_structured(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_format=IdeaGenerationResponse,
        task_name=f"{lane.key}_discovery_idea_generation",
    )


def _signals_prompt_block(signals: list[dict]) -> str:
    if not signals:
        return (
            "No live signals were collected this run (collectors returned nothing usable, "
            "or fresh discoveries are still pending source approval). Do not invent specifics -- "
            "say plainly in freshness_hook that fresh research is still needed before writing."
        )
    lines = []
    for signal in signals:
        status = f" [status={signal['status']}]" if signal.get("status") != "fetched" else ""
        lines.append(
            f"- ({signal['source_type']}{status}) {signal['title']} — {signal['url']}\n"
            f"  {signal.get('snippet') or 'No snippet available.'}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover grounded content ideas for an EGF editorial lane.")
    parser.add_argument("lane_key")
    parser.add_argument("--idea-count", type=int, default=3)
    parser.add_argument("--limit-per-task", type=int, default=DEFAULT_SIGNAL_LIMIT)
    parser.add_argument("--topic-hint", default=None)
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()

    result = discover_lane_topics(
        lane_key=args.lane_key,
        idea_count=args.idea_count,
        limit_per_task=args.limit_per_task,
        topic_hint=args.topic_hint,
        persist=not args.no_persist,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
