from __future__ import annotations

from execution.editorial.taxonomy import LANES_BY_KEY
from execution.research.models import SourceDefinition


DEFAULT_SOURCE_REGISTRY: tuple[SourceDefinition, ...] = (
    SourceDefinition(
        name="FDA Recalls, Market Withdrawals, & Safety Alerts",
        source_type="official_recall_page",
        base_url="https://www.fda.gov/safety/recalls-market-withdrawals-safety-alerts",
        lane="laws_labeling",
        credibility_score=0.98,
        monitor_frequency="daily",
        notes="Primary official source for FDA recall and safety-alert pages.",
    ),
    SourceDefinition(
        name="openFDA Food Enforcement API",
        source_type="official_api",
        base_url="https://api.fda.gov/food/enforcement.json",
        lane="laws_labeling",
        credibility_score=0.95,
        monitor_frequency="daily",
        notes="Structured FDA enforcement data. Use with context, not as the only public-alert source.",
    ),
    SourceDefinition(
        name="USDA FSIS Recalls & Public Health Alerts",
        source_type="official_recall_page",
        base_url="https://www.fsis.usda.gov/recalls",
        lane="laws_labeling",
        credibility_score=0.95,
        monitor_frequency="daily",
        notes="Useful for meat, poultry, and egg product recalls that may mention undeclared allergens.",
    ),
    SourceDefinition(
        name="Gluten-Free Certification Organization",
        source_type="certification_body",
        base_url="https://gfco.org/",
        lane="laws_labeling",
        credibility_score=0.88,
        monitor_frequency="weekly",
        notes="Certification context and gluten-free product standards.",
    ),
    SourceDefinition(
        name="Celiac Disease Foundation",
        source_type="gluten_free_organization",
        base_url="https://celiac.org/",
        lane="science_health",
        credibility_score=0.88,
        monitor_frequency="weekly",
        notes="Celiac education, research summaries, and community resources.",
    ),
    SourceDefinition(
        name="Beyond Celiac",
        source_type="gluten_free_organization",
        base_url="https://www.beyondceliac.org/",
        lane="science_health",
        credibility_score=0.86,
        monitor_frequency="weekly",
        notes="Celiac research, education, and patient-facing explainers.",
    ),
    SourceDefinition(
        name="PubMed",
        source_type="medical_research",
        base_url="https://pubmed.ncbi.nlm.nih.gov/",
        lane="science_health",
        credibility_score=0.92,
        monitor_frequency="weekly",
        notes="Primary discovery surface for medical and nutrition studies.",
    ),
    SourceDefinition(
        name="Brand Product Pages",
        source_type="brand_product_page",
        base_url="dynamic://brand-product-pages",
        lane="product_watch",
        credibility_score=0.72,
        monitor_frequency="weekly",
        notes="Discovered per topic from brands, product pages, and official ingredient/allergen pages.",
    ),
    SourceDefinition(
        name="Retailer Product Pages",
        source_type="retailer_product_page",
        base_url="dynamic://retailer-product-pages",
        lane="product_watch",
        credibility_score=0.68,
        monitor_frequency="weekly",
        notes="Target, Walmart, Amazon, Instacart, grocery chains, and supermarket pages.",
    ),
    SourceDefinition(
        name="Restaurant Allergen Menus",
        source_type="restaurant_allergen_page",
        base_url="dynamic://restaurant-allergen-pages",
        lane="restaurants_travel",
        credibility_score=0.82,
        monitor_frequency="weekly",
        notes="Official chain allergen menus and restaurant gluten-free information pages.",
    ),
    SourceDefinition(
        name="Travel and Restaurant Community Chatter",
        source_type="community_discussion",
        base_url="dynamic://community-restaurant-travel",
        lane="restaurants_travel",
        credibility_score=0.48,
        monitor_frequency="weekly",
        notes="Use as a lead source only; verify claims with official menus when possible.",
    ),
    SourceDefinition(
        name="Kitchen Tool Product Pages",
        source_type="tool_product_page",
        base_url="dynamic://kitchen-tool-product-pages",
        lane="gadgets_tools",
        credibility_score=0.66,
        monitor_frequency="monthly",
        notes="Manufacturer and retailer pages for tool specs, dimensions, and claims.",
    ),
    SourceDefinition(
        name="App Store and Product Review Pages",
        source_type="app_review_page",
        base_url="dynamic://app-review-pages",
        lane="apps_digital",
        credibility_score=0.62,
        monitor_frequency="monthly",
        notes="App store listings, official app websites, and review patterns.",
    ),
    SourceDefinition(
        name="Community Questions and Reddit Threads",
        source_type="community_discussion",
        base_url="dynamic://community-questions",
        lane="community_questions",
        credibility_score=0.45,
        monitor_frequency="daily",
        notes="Excellent for pain points and language. Never use alone for factual medical/legal claims.",
    ),
)


def get_sources_for_lane(lane: str) -> tuple[SourceDefinition, ...]:
    """Return source definitions for a lane plus cross-lane support sources."""

    if lane not in LANES_BY_KEY:
        lane = "community_questions"

    support_lanes = {lane}
    if lane in {"product_watch", "comparison", "gadgets_tools", "apps_digital"}:
        support_lanes.add("community_questions")
    if lane == "recipe_experiments":
        support_lanes.update({"product_watch", "community_questions"})
    if lane == "organization_life":
        support_lanes.update({"gadgets_tools", "community_questions"})

    return tuple(source for source in DEFAULT_SOURCE_REGISTRY if source.lane in support_lanes)


def source_registry_prompt_block(lane: str) -> str:
    """Return prompt-ready source candidates for a lane."""

    lines = []
    for source in get_sources_for_lane(lane):
        lines.append(
            f"- {source.name} [{source.source_type}] credibility={source.credibility_score:.2f}: "
            f"{source.base_url}. {source.notes}"
        )
    return "\n".join(lines)

