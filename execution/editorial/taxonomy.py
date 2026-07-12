from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContentLane:
    """A durable editorial category used to keep content varied."""

    key: str
    label: str
    description: str
    keywords: tuple[str, ...]
    example_angles: tuple[str, ...]


CONTENT_LANES: tuple[ContentLane, ...] = (
    ContentLane(
        key="laws_labeling",
        label="Laws & Labeling",
        description="Packaging rules, certification, recalls, allergen claims, and regulatory changes.",
        keywords=(
            "fda",
            "label",
            "labeling",
            "certified",
            "certification",
            "recall",
            "allergen",
            "packaging",
            "ppm",
            "law",
            "rule",
            "regulation",
        ),
        example_angles=(
            "What this labeling change means in the grocery aisle",
            "The packaging claim worth checking twice",
            "A recall explained without legal soup",
        ),
    ),
    ContentLane(
        key="product_watch",
        label="Product Watch",
        description="New or popular gluten-free groceries, snacks, mixes, frozen items, and pantry staples.",
        keywords=(
            "product",
            "brand",
            "snack",
            "frozen",
            "costco",
            "trader joe",
            "aldi",
            "target",
            "walmart",
            "pasta",
            "cracker",
            "cookie",
            "cereal",
        ),
        example_angles=(
            "Is this new gluten-free product useful or just expensive cardboard cosplay?",
            "The freezer-aisle find people keep mentioning",
            "A pantry staple worth keeping around",
        ),
    ),
    ContentLane(
        key="comparison",
        label="Comparisons & Taste Tests",
        description="Side-by-side comparisons of breads, pastas, flours, apps, restaurants, or tools.",
        keywords=(
            "vs",
            "versus",
            "compare",
            "comparison",
            "best",
            "better",
            "bread",
            "taste test",
            "review",
            "texture",
        ),
        example_angles=(
            "Which gluten-free bread survives an actual sandwich?",
            "The texture test nobody asked for but everyone needs",
            "Two popular products, one brutally honest kitchen counter",
        ),
    ),
    ContentLane(
        key="restaurants_travel",
        label="Restaurants & Travel",
        description="Restaurant chatter, chain allergen menus, travel planning, airports, hotels, and local finds.",
        keywords=(
            "restaurant",
            "menu",
            "chain",
            "travel",
            "airport",
            "hotel",
            "vacation",
            "city",
            "dining",
            "eat out",
            "takeout",
        ),
        example_angles=(
            "What gluten-free diners are actually saying about this chain",
            "The travel snack plan that prevents airport despair",
            "How to read a restaurant menu like a tiny detective",
        ),
    ),
    ContentLane(
        key="gadgets_tools",
        label="Kitchen Gadgets & Tools",
        description="Air fryers, toaster bags, bread makers, storage, thermometers, lunch boxes, and cross-contact tools.",
        keywords=(
            "air fryer",
            "toaster",
            "bread maker",
            "gadget",
            "tool",
            "pan",
            "storage",
            "lunch box",
            "knife",
            "cutting board",
            "thermometer",
        ),
        example_angles=(
            "The tool that makes shared kitchens less emotionally athletic",
            "A gadget worth buying and three that can sit down",
            "How to set up a cross-contact-safe counter zone",
        ),
    ),
    ContentLane(
        key="apps_digital",
        label="Apps & Digital Tools",
        description="Scanner apps, restaurant finder apps, meal planners, shopping tools, and digital workflows.",
        keywords=(
            "app",
            "scanner",
            "barcode",
            "digital",
            "meal planner",
            "find me gluten free",
            "review app",
            "shopping list",
        ),
        example_angles=(
            "Can a gluten scanner app actually save dinner?",
            "The app feature that matters more than the pretty interface",
            "A realistic digital setup for grocery shopping",
        ),
    ),
    ContentLane(
        key="organization_life",
        label="Organization & Real Life Systems",
        description="Pantry systems, shared kitchens, school lunches, freezer prep, travel kits, and daily routines.",
        keywords=(
            "pantry",
            "organize",
            "organization",
            "system",
            "shared kitchen",
            "lunch",
            "school",
            "freezer",
            "meal prep",
            "routine",
            "storage",
        ),
        example_angles=(
            "The pantry setup that stops gluten-free chaos at 6 PM",
            "A shared kitchen system for people who enjoy keeping their sanity",
            "The emergency snack kit every gluten-free person deserves",
        ),
    ),
    ContentLane(
        key="recipe_experiments",
        label="Recipe Experiments",
        description="Specific new recipes, seasonal ideas, copycat recipes, and practical cooking experiments.",
        keywords=(
            "recipe",
            "dinner",
            "breakfast",
            "dessert",
            "copycat",
            "seasonal",
            "make",
            "cook",
            "bake",
            "meal",
        ),
        example_angles=(
            "A gluten-free dinner that does not taste like a compromise memo",
            "Can this trending recipe become gluten-free without falling apart?",
            "A cozy seasonal recipe with practical swaps",
        ),
    ),
    ContentLane(
        key="science_health",
        label="Science Without Being Boring",
        description="Research, oats, cross-contact, symptoms, celiac studies, and evidence-led explanations.",
        keywords=(
            "study",
            "research",
            "celiac",
            "symptom",
            "oats",
            "cross contact",
            "contamination",
            "pubmed",
            "clinical",
            "nutrition",
        ),
        example_angles=(
            "The new study explained for people who have dinner to make",
            "What this oat debate means before breakfast gets dramatic",
            "Cross-contact advice that is useful, not terrifying",
        ),
    ),
    ContentLane(
        key="community_questions",
        label="Community Questions",
        description="Real reader dilemmas, Reddit arguments, etiquette, family issues, and recurring frustrations.",
        keywords=(
            "question",
            "help",
            "advice",
            "family",
            "friend",
            "party",
            "wedding",
            "work",
            "roommate",
            "diagnosed",
            "newly",
        ),
        example_angles=(
            "The gluten-free etiquette question everyone eventually faces",
            "How to answer the family member who thinks crumbs are decorative",
            "A real-life dilemma with a practical exit plan",
        ),
    ),
)


LANES_BY_KEY = {lane.key: lane for lane in CONTENT_LANES}


ANGLE_TYPES = (
    "comparison",
    "explainer",
    "product_roundup",
    "field_guide",
    "review_test",
    "trend_reaction",
    "recipe_story",
    "checklist",
)


GENERIC_TOPIC_PATTERNS = (
    "gluten free living 101",
    "gluten-free living 101",
    "beginner guide",
    "ultimate guide",
    "bread making",
    "baking basics",
    "flour substitute",
)


def lane_prompt_block() -> str:
    """Return a compact, prompt-ready summary of the editorial taxonomy."""

    lines = []
    for lane in CONTENT_LANES:
        examples = "; ".join(lane.example_angles[:2])
        lines.append(f"- {lane.label} (`{lane.key}`): {lane.description} Examples: {examples}.")
    return "\n".join(lines)


def classify_lane(text: str, fallback: str = "community_questions") -> str:
    """Classify text into the most likely content lane using transparent keyword scoring."""

    normalized = text.lower()
    scores: dict[str, int] = {}
    for lane in CONTENT_LANES:
        score = sum(1 for keyword in lane.keywords if keyword in normalized)
        if score:
            scores[lane.key] = score

    if not scores:
        return fallback

    return max(scores.items(), key=lambda item: item[1])[0]


def is_generic_topic(text: str) -> bool:
    """Return True when a title is one of the stale patterns we want to suppress."""

    normalized = text.lower()
    return any(pattern in normalized for pattern in GENERIC_TOPIC_PATTERNS)

