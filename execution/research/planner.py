from __future__ import annotations

from execution.editorial.taxonomy import classify_lane
from execution.research.models import ResearchPlan, ResearchTask
from execution.research.source_registry import get_sources_for_lane


LANE_SOURCE_TYPES: dict[str, tuple[tuple[str, str], ...]] = {
    "laws_labeling": (
        ("official_recall_page", "Check official recall and safety alert pages for timely allergen or gluten-related issues."),
        ("official_api", "Search structured enforcement data for undeclared wheat, allergens, gluten, and labeling problems."),
        ("certification_body", "Verify certification context and gluten-free standard language."),
        ("web_search", "Catch recent news coverage of the labeling change or recall that official pages haven't indexed yet."),
    ),
    "product_watch": (
        ("brand_product_page", "Verify product details, ingredients, allergen statements, and launch claims."),
        ("retailer_product_page", "Check availability, pricing signals, reviews, and supermarket discovery."),
        ("web_search", "Discover the specific product/brand page and recent reviews or launch coverage live."),
    ),
    "comparison": (
        ("brand_product_page", "Collect official product details for each compared item."),
        ("retailer_product_page", "Compare reviews, price, availability, and specifications."),
        ("web_search", "Find independent taste-test/comparison coverage and current pricing across retailers."),
    ),
    "restaurants_travel": (
        ("restaurant_allergen_page", "Verify allergen menu details and official gluten-free claims."),
        ("web_search", "Find recent diner/traveler reporting on this chain, city, or route."),
    ),
    "gadgets_tools": (
        ("tool_product_page", "Verify dimensions, materials, use cases, and manufacturer claims."),
        ("retailer_product_page", "Check reviews, price, and availability."),
        ("web_search", "Find independent reviews and real kitchen use cases for the specific tool."),
    ),
    "apps_digital": (
        ("app_review_page", "Verify app features, reviews, update history, and pricing."),
        ("web_search", "Find recent user reviews, update notes, and trust/feature complaints."),
    ),
    "organization_life": (
        ("web_search", "Find real routines, systems, and product roundups gluten-free households are actually using."),
        ("tool_product_page", "Find relevant storage, lunch, freezer, and travel tools where useful."),
    ),
    "recipe_experiments": (
        ("web_search", "Find what people are trying, craving, or struggling to recreate gluten-free right now."),
        ("brand_product_page", "Verify product ingredients and recommended use if a packaged product is involved."),
    ),
    "science_health": (
        ("medical_research", "Find current studies or review papers relevant to the topic."),
        ("gluten_free_organization", "Find patient-facing summaries and practical context."),
        ("web_search", "Catch recent science journalism or org explainers not yet indexed in PubMed."),
    ),
    "community_questions": (
        ("web_search", "Capture the real question, emotional context, and recurring advice patterns."),
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
    if source_type == "web_search":
        return _web_search_query(topic_title, lane)
    if lane == "comparison":
        return f"{topic_title} comparison reviews gluten free"
    return f"{topic_title} gluten free discussion"


def _web_search_query(topic_title: str, lane: str) -> str:
    """Seed query for the live web-search collector, tuned per lane."""

    if lane == "laws_labeling":
        return f"{topic_title} gluten-free news"
    if lane in {"product_watch", "comparison"}:
        return f"{topic_title} gluten free review"
    if lane == "restaurants_travel":
        return f"{topic_title} gluten free menu OR travel"
    if lane == "gadgets_tools":
        return f"{topic_title} gluten free kitchen review"
    if lane == "apps_digital":
        return f"{topic_title} app review gluten free"
    if lane == "organization_life":
        return f"{topic_title} gluten free household system"
    if lane == "recipe_experiments":
        return f"{topic_title} gluten free recipe"
    if lane == "science_health":
        return f"{topic_title} celiac gluten-free news"
    return f"{topic_title} gluten free"

