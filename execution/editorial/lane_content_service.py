from __future__ import annotations

import json
from datetime import datetime

from execution.config import PROMPTS_DIR
from execution.db import get_connection
from execution.editorial.memory import current_month_label, memory_prompt_block
from execution.editorial.schema import ensure_editorial_schema
from execution.editorial.taxonomy import ANGLE_TYPES, CONTENT_LANES, LANES_BY_KEY, ContentLane
from execution.models import IdeaGenerationItem, IdeaGenerationResponse
from execution.research.draft_generator import generate_research_draft
from execution.utils.llm_client import LLMClient


DEFAULT_IDEA_COUNT = 3
MAX_IDEA_COUNT = 10


def list_lane_specs() -> list[dict]:
    """Return API-safe metadata for all editorial lanes."""

    return [_lane_to_dict(lane) for lane in CONTENT_LANES]


def list_lane_ideas(lane_key: str, limit: int = 20) -> list[dict]:
    """Return recent persisted ideas for a lane."""

    _require_lane(lane_key)
    ensure_editorial_schema()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT *
            FROM content_ideas
            WHERE content_lane = ?
            ORDER BY created_at DESC, idea_id DESC
            LIMIT ?
            """,
            (lane_key, max(1, min(int(limit), 100))),
        )
        return [dict(row) for row in cursor.fetchall()]


def create_lane_ideas(
    lane_key: str,
    idea_count: int = DEFAULT_IDEA_COUNT,
    topic_hint: str | None = None,
    sample: bool = False,
    persist: bool = True,
) -> dict:
    """Create ideas for one editorial lane and optionally persist them."""

    lane = _require_lane(lane_key)
    normalized_count = max(1, min(int(idea_count), MAX_IDEA_COUNT))

    if sample:
        ideas = _sample_ideas_for_lane(lane, normalized_count, topic_hint)
        generation_mode = "sample"
    else:
        response = _generate_lane_ideas_with_llm(lane, normalized_count, topic_hint)
        ideas = response.ideas
        generation_mode = "llm"

    saved_ideas = _save_lane_ideas(ideas) if persist else [_idea_to_dict(idea) for idea in ideas]

    return {
        "lane": _lane_to_dict(lane),
        "generation_mode": generation_mode,
        "persisted": persist,
        "idea_count": len(saved_ideas),
        "ideas": saved_ideas,
    }


def create_lane_content(
    lane_key: str,
    topic_title: str | None = None,
    platform: str = "newsletter",
    angle_type: str | None = None,
    topic_hint: str | None = None,
    limit_per_task: int = 3,
    sample: bool = False,
    persist: bool = True,
) -> dict:
    """Create platform content for one lane, using research-backed drafts when not in sample mode."""

    lane = _require_lane(lane_key)
    resolved_title = (topic_title or "").strip()
    if not resolved_title:
        sample_idea = _sample_ideas_for_lane(lane, 1, topic_hint)[0]
        resolved_title = sample_idea.title
        angle_type = angle_type or sample_idea.angle_type

    if sample:
        return {
            "lane": _lane_to_dict(lane),
            "generation_mode": "sample",
            "persisted": False,
            "platform": platform,
            "content": _sample_content_for_lane(lane, resolved_title, platform, angle_type),
        }

    result = generate_research_draft(
        topic_title=resolved_title,
        lane=lane.key,
        angle_type=angle_type,
        platform=platform,
        limit_per_task=max(1, int(limit_per_task)),
        persist=persist,
    )
    return {
        "lane": _lane_to_dict(lane),
        "generation_mode": "llm",
        "persisted": persist,
        "platform": platform,
        **result,
    }


def _generate_lane_ideas_with_llm(
    lane: ContentLane,
    idea_count: int,
    topic_hint: str | None,
) -> IdeaGenerationResponse:
    system_prompt = (PROMPTS_DIR / "brand_system_prompt.txt").read_text(encoding="utf-8")
    prompt_template = (PROMPTS_DIR / "lane_idea_generation.txt").read_text(encoding="utf-8")
    user_prompt = prompt_template.format(
        idea_count=idea_count,
        current_month=current_month_label(),
        lane_key=lane.key,
        lane_label=lane.label,
        lane_description=lane.description,
        lane_examples="\n".join(f"- {angle}" for angle in lane.example_angles),
        recent_titles=memory_prompt_block(limit=80),
        topic_hint=(topic_hint or "None supplied."),
    )
    return LLMClient().generate_structured(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_format=IdeaGenerationResponse,
        task_name=f"{lane.key}_idea_generation",
    )


def _save_lane_ideas(ideas: list[IdeaGenerationItem]) -> list[dict]:
    ensure_editorial_schema()
    batch_date = datetime.now().strftime("%Y-%m-%d")
    saved: list[dict] = []
    with get_connection() as conn:
        cursor = conn.cursor()
        for idea in ideas:
            cursor.execute(
                """
                INSERT INTO content_ideas
                    (title, content_type, description, content_lane, angle_type,
                     freshness_hook, source_hint, batch_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    idea.title,
                    idea.content_type,
                    idea.description,
                    idea.content_lane,
                    idea.angle_type,
                    idea.freshness_hook,
                    idea.source_hint,
                    batch_date,
                ),
            )
            saved.append({"idea_id": int(cursor.lastrowid), **_idea_to_dict(idea), "batch_date": batch_date})
        conn.commit()
    return saved


def _sample_ideas_for_lane(
    lane: ContentLane,
    idea_count: int,
    topic_hint: str | None = None,
) -> list[IdeaGenerationItem]:
    hint = (topic_hint or "").strip()
    ideas: list[IdeaGenerationItem] = []
    for index in range(idea_count):
        angle = lane.example_angles[index % len(lane.example_angles)]
        angle_type = ANGLE_TYPES[index % len(ANGLE_TYPES)]
        title = angle if not hint else f"{angle}: {hint}"
        ideas.append(
            IdeaGenerationItem(
                title=title,
                content_type=_content_type_for_lane(lane.key),
                description=(
                    f"A {lane.label.lower()} idea about {hint or lane.description.lower()} "
                    "with a practical reader takeaway and one clear verification path."
                ),
                target_keyword=_target_keyword(lane, hint),
                estimated_engagement="medium",
                content_lane=lane.key,
                angle_type=angle_type,
                freshness_hook=f"Uses the {lane.label} lane to avoid another generic gluten-free basics post.",
                source_hint=_source_hint_for_lane(lane.key),
            )
        )
    return ideas


def _sample_content_for_lane(
    lane: ContentLane,
    topic_title: str,
    platform: str,
    angle_type: str | None,
) -> dict:
    return {
        "title": topic_title,
        "dek": f"A sample {platform} draft for the {lane.label} lane.",
        "lane": lane.key,
        "angle_type": angle_type or "explainer",
        "sections": [
            {
                "heading": "Reader Problem",
                "body": f"Readers need a specific, low-drama answer about {topic_title}, not another broad gluten-free overview.",
            },
            {
                "heading": "What To Verify",
                "body": f"Check { _source_hint_for_lane(lane.key) } before turning this into publishable advice.",
            },
            {
                "heading": "Practical Takeaway",
                "body": "Give the reader one concrete decision, checklist, product check, or next step they can use today.",
            },
        ],
        "call_to_action": "Save this as a draft, verify the sources, then move it through review.",
        "source_notes": [_source_hint_for_lane(lane.key)],
        "verification_notes": ["Sample mode only. No live sources were fetched."],
        "status_recommendation": "ready_for_review",
    }


def _require_lane(lane_key: str) -> ContentLane:
    lane = LANES_BY_KEY.get((lane_key or "").strip())
    if not lane:
        valid = ", ".join(sorted(LANES_BY_KEY))
        raise ValueError(f"Unknown content lane '{lane_key}'. Valid lanes: {valid}")
    return lane


def _lane_to_dict(lane: ContentLane) -> dict:
    return {
        "key": lane.key,
        "label": lane.label,
        "description": lane.description,
        "keywords": list(lane.keywords),
        "example_angles": list(lane.example_angles),
    }


def _idea_to_dict(idea: IdeaGenerationItem) -> dict:
    return json.loads(idea.model_dump_json())


def _content_type_for_lane(lane_key: str) -> str:
    if lane_key == "recipe_experiments":
        return "recipe"
    if lane_key in {"product_watch", "comparison", "gadgets_tools", "apps_digital"}:
        return "tip"
    return "education"


def _target_keyword(lane: ContentLane, hint: str) -> str:
    if hint:
        return f"gluten free {hint.lower()}"
    return f"gluten free {lane.label.lower()}"


def _source_hint_for_lane(lane_key: str) -> str:
    hints = {
        "laws_labeling": "FDA, USDA, certification body, or official recall page",
        "product_watch": "brand page, retailer product page, or current product listing",
        "comparison": "brand pages, retailer listings, and hands-on test notes",
        "restaurants_travel": "official allergen menu, restaurant page, or travel source",
        "gadgets_tools": "manufacturer page, retailer listing, and safety/use notes",
        "apps_digital": "official app site, app store listing, and review pattern",
        "organization_life": "reader workflow notes plus product or safety sources where needed",
        "recipe_experiments": "tested recipe notes, ingredient labels, and substitution evidence",
        "science_health": "PubMed, celiac organization, or recognized medical source",
        "community_questions": "community discussion for language plus stronger sources for factual claims",
    }
    return hints.get(lane_key, "approved source registry")
