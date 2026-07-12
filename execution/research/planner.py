from __future__ import annotations

from execution.editorial.taxonomy import classify_lane
from execution.research.models import ResearchPlan, ResearchTask
from execution.research.source_registry import get_sources_for_lane


LANE_SOURCE_TYPES: dict[str, tuple[tuple[str, str], ...]] = {
    "laws_labeling": (
        ("official_recall_page", "Check official recall and safety alert pages for timely allergen or gluten-related issues."),
        ("official_api", "Search structured enforcement data for undeclared wheat, allergens, gluten, and labeling problems."),
        ("certification_body", "Verify certification context and gluten-free standard language."),
    ),
    "product_watch": (
        ("brand_product_page", "Verify product details, ingredients, allergen statements, and launch claims."),
        ("retailer_product_page", "Check availability, pricing signals, reviews, and supermarket discovery."),
        ("community_discussion", "Look for real-user chatter and recurring complaints or praise."),
    ),
    "comparison": (
        ("brand_product_page", "Collect official product details for each compared item."),
        ("retailer_product_page", "Compare reviews, price, availability, and specifications."),
        ("community_discussion", "Identify texture, taste, and practical use complaints."),
    ),
    "restaurants_travel": (
        ("restaurant_allergen_page", "Verify allergen menu details and official gluten-free claims."),
        ("community_discussion", "Collect traveler and diner pain points to frame the story."),
    ),
    "gadgets_tools": (
        ("tool_product_page", "Verify dimensions, materials, use cases, and manufacturer claims."),
        ("retailer_product_page", "Check reviews, price, and availability."),
        ("community_discussion", "Find real kitchen use cases and cross-contact concerns."),
    ),
    "apps_digital": (
        ("app_review_page", "Verify app features, reviews, update history, and pricing."),
        ("community_discussion", "Find real-user trust issues, missing features, and useful workflows."),
    ),
    "organization_life": (
        ("community_discussion", "Collect lived problems and routines from gluten-free households."),
        ("tool_product_page", "Find relevant storage, lunch, freezer, and travel tools where useful."),
    ),
    "recipe_experiments": (
        ("community_discussion", "Find what people are trying, craving, or struggling to recreate gluten-free."),
        ("brand_product_page", "Verify product ingredients and recommended use if a packaged product is involved."),
    ),
    "science_health": (
        ("medical_research", "Find current studies or review papers relevant to the topic."),
        ("gluten_free_organization", "Find patient-facing summaries and practical context."),
    ),
    "community_questions": (
        ("community_discussion", "Capture the real question, emotional context, and recurring advice patterns."),
        ("gluten_free_organization", "Verify any health or safety claims before writing."),
    ),
}


def plan_research(
    topic_title: str,
    lane: str | None = None,
    angle_type: str | None = None,
    platform: str = "blog",
) -> ResearchPlan:
    """Build a deterministic source plan for a topic before writing."""

    resolved_lane = lane or classify_lane(topic_title)
    source_types = LANE_SOURCE_TYPES.get(resolved_lane, LANE_SOURCE_TYPES["community_questions"])
    tasks = []
    for index, (source_type, reason) in enumerate(source_types, start=1):
        tasks.append(
            ResearchTask(
                lane=resolved_lane,
                source_type=source_type,
                query=_build_query(topic_title, resolved_lane, source_type),
                priority=index,
                reason=reason,
            )
        )

    return ResearchPlan(
        topic_title=topic_title,
        lane=resolved_lane,
        angle_type=angle_type,
        platform=platform,
        tasks=tuple(tasks),
        candidate_sources=get_sources_for_lane(resolved_lane),
    )


def _build_query(topic_title: str, lane: str, source_type: str) -> str:
    """Create a search/API query seed for a source type."""

    if source_type == "official_api":
        return f'("gluten" OR "wheat" OR "allergen") AND "{topic_title}"'
    if source_type in {"official_recall_page", "certification_body"}:
        return f"{topic_title} gluten-free recall labeling certification"
    if source_type == "restaurant_allergen_page":
        return f"{topic_title} official allergen menu gluten free"
    if source_type == "medical_research":
        return f"{topic_title} celiac gluten-free study"
    if source_type == "app_review_page":
        return f"{topic_title} app reviews gluten free scanner"
    if source_type in {"brand_product_page", "retailer_product_page", "tool_product_page"}:
        return f"{topic_title} gluten free product review ingredients"
    if lane == "comparison":
        return f"{topic_title} comparison reviews gluten free"
    return f"{topic_title} gluten free discussion"

