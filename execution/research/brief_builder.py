from __future__ import annotations

import json
from dataclasses import asdict

from execution.db import get_connection
from execution.editorial.platforms import PLATFORMS_BY_KEY
from execution.research.models import ContentBrief, ResearchPlan
from execution.research.planner import plan_research
from execution.research.schema import ensure_research_schema


def build_content_brief(
    topic_title: str,
    lane: str | None = None,
    angle_type: str | None = None,
    platform: str = "blog",
    reader_problem: str | None = None,
    thesis: str | None = None,
    persist: bool = True,
) -> ContentBrief:
    """Create a portable content brief for any supported platform."""

    ensure_research_schema()
    plan = plan_research(topic_title, lane=lane, angle_type=angle_type, platform=platform)
    platform_spec = PLATFORMS_BY_KEY.get(platform, PLATFORMS_BY_KEY["blog"])
    brief = ContentBrief(
        topic_title=topic_title,
        lane=plan.lane,
        angle_type=angle_type,
        platform=platform_spec.key,
        reader_problem=reader_problem or _default_reader_problem(plan),
        thesis=thesis or _default_thesis(plan),
        source_plan=plan.tasks,
        source_candidates=plan.candidate_sources,
        platform_sections=platform_spec.required_sections,
    )

    if persist:
        save_content_brief(brief, plan)

    return brief


def save_content_brief(brief: ContentBrief, plan: ResearchPlan) -> int:
    """Persist the research plan and portable content brief."""

    with get_connection() as conn:
        cursor = conn.cursor()
        for task in plan.tasks:
            cursor.execute(
                """
                INSERT INTO research_queries
                    (topic_title, lane, angle_type, platform, source_type,
                     query_text, priority, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.topic_title,
                    plan.lane,
                    plan.angle_type,
                    plan.platform,
                    task.source_type,
                    task.query,
                    task.priority,
                    task.reason,
                ),
            )

        cursor.execute(
            """
            INSERT INTO content_briefs
                (topic_title, lane, angle_type, platform, reader_problem, thesis,
                 source_plan_json, source_candidates_json, platform_sections_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                brief.topic_title,
                brief.lane,
                brief.angle_type,
                brief.platform,
                brief.reader_problem,
                brief.thesis,
                json.dumps([asdict(task) for task in brief.source_plan]),
                json.dumps([asdict(source) for source in brief.source_candidates]),
                json.dumps(list(brief.platform_sections)),
            ),
        )
        brief_id = cursor.lastrowid
        conn.commit()
        return int(brief_id)


def _default_reader_problem(plan: ResearchPlan) -> str:
    return (
        f"Readers need a practical, trustworthy take on '{plan.topic_title}' "
        "without turning one gluten-free question into a full-time unpaid research job."
    )


def _default_thesis(plan: ResearchPlan) -> str:
    return (
        f"Use verified {plan.lane.replace('_', ' ')} sources plus real community context "
        "to explain what matters, what is still uncertain, and what readers can do next."
    )


if __name__ == "__main__":
    brief = build_content_brief(
        "FDA gluten-free labeling and undeclared wheat recalls",
        lane="laws_labeling",
        platform="newsletter",
    )
    print(json.dumps(asdict(brief), indent=2))
