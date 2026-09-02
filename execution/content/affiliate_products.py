from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlencode

from execution.config import AMAZON_ASSOCIATE_TAG
from execution.db import get_connection
from execution.utils.logger import setup_logger

logger = setup_logger("affiliate_products")


SENSITIVE_LANES = {"laws_labeling", "science_without_boring", "science_health", "restaurants_travel"}

LANE_DEFAULT_SOLUTIONS = {
    "laws_labeling": ("food label magnifier", "reading tiny gluten-free label details without losing your will to grocery shop"),
    "product_watch": ("gluten free snack variety pack", "keeping useful gluten-free pantry backups around"),
    "comparison": ("gluten free bread storage container", "making expensive gluten-free bread survive real life a little longer"),
    "bread_wars": ("gluten free bread storage container", "making expensive gluten-free bread survive real life a little longer"),
    "restaurants_travel": ("gluten free travel snack kit", "having safe backup snacks when restaurants or airports get complicated"),
    "gadgets_tools": ("gluten free toaster bags", "reducing crumb drama in shared kitchens and travel situations"),
    "kitchen_gadget_lab": ("gluten free toaster bags", "reducing crumb drama in shared kitchens and travel situations"),
    "apps_digital": ("kitchen label maker gluten free pantry", "turning label-reading and pantry rules into visible household systems"),
    "organization_life": ("pantry labels airtight food storage containers", "keeping gluten-free food organized and easier to grab"),
    "recipe_experiments": ("digital kitchen scale for baking", "making gluten-free recipe testing more consistent"),
    "science_without_boring": ("digital kitchen scale for baking", "making gluten-free cooking more precise without implying medical certainty"),
    "community_drama": ("gluten free toaster bags", "solving the everyday gluten-free annoyance behind the article"),
}

QUERY_RULES = [
    ({"toaster", "toast", "crumb", "cross", "shared"}, "gluten free toaster bags"),
    ({"lunch", "school", "work", "office", "box"}, "insulated lunch box meal prep"),
    ({"travel", "airport", "road", "trip", "hotel"}, "gluten free travel snack kit"),
    ({"label", "labels", "labeling", "packaging", "claims", "ingredient", "ingredients"}, "food label magnifier"),
    ({"pantry", "organize", "storage", "freezer", "labels"}, "pantry labels airtight food storage containers"),
    ({"bread", "loaf", "sandwich"}, "gluten free bread storage container"),
    ({"baking", "recipe", "flour", "cookies", "muffins"}, "digital kitchen scale for baking"),
    ({"app", "scanner", "digital"}, "kitchen label maker gluten free pantry"),
]

STOPWORDS = {
    "gluten", "free", "glutenfree", "guide", "practical", "readers", "reader",
    "article", "topic", "check", "checks", "shopping", "shopper", "shoppers",
    "easy", "help", "helps", "helpful", "best", "good", "current", "before",
    "trusting", "front", "details",
}


def ensure_affiliate_product_schema() -> None:
    """Add product-intelligence columns used by the solution matcher."""
    columns = {
        "solution_tags": "TEXT",
        "problem_tags": "TEXT",
        "source_type": "TEXT DEFAULT 'manual'",
        "media_status": "TEXT DEFAULT 'complete'",
        "auto_created": "INTEGER DEFAULT 0",
        "needs_manual_image": "INTEGER DEFAULT 0",
        "evidence_notes": "TEXT",
        "match_notes": "TEXT",
    }
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(amazon_products)")
        existing = {row[1] for row in cursor.fetchall()}
        for column, ddl in columns.items():
            if column not in existing:
                cursor.execute(f"ALTER TABLE amazon_products ADD COLUMN {column} {ddl}")
        conn.commit()


def select_solution_product_for_blog(
    topic_title: str,
    topic_description: str | None = None,
    content_lane: str | None = None,
) -> dict | None:
    """Return or create a relevant, affordable affiliate product for the reader problem."""
    ensure_affiliate_product_schema()
    lane = (content_lane or "").strip().lower()
    topic_text = f"{topic_title} {topic_description or ''} {lane}"
    topic_tokens = _tokens(topic_text)
    solution_query, pain_point = _solution_query(topic_tokens, lane)

    products = _load_products()
    scored = [
        (_score_product(product, topic_tokens, lane, solution_query), product)
        for product in products
    ]
    scored.sort(key=lambda item: (item[0], _has_image(item[1]), item[1].get("last_used") or ""), reverse=True)

    if scored and scored[0][0] >= _minimum_score(lane):
        product = _with_media_flags(scored[0][1])
        product["match_notes"] = product.get("match_notes") or _match_notes(solution_query, pain_point, "approved catalog")
        logger.info("Selected existing affiliate product %s for topic '%s'", product["product_id"], topic_title)
        return product

    product = _create_or_update_solution_search_product(
        topic_title=topic_title,
        topic_description=topic_description,
        lane=lane or "general",
        solution_query=solution_query,
        pain_point=pain_point,
    )
    logger.info("Created/selected affiliate solution search product %s for topic '%s'", product["product_id"], topic_title)
    return product


def _load_products() -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT product_id, title, description, url, image_url, keywords,
                   content_lanes, price_tier, priority_score, active, last_used,
                   solution_tags, problem_tags, source_type, media_status,
                   auto_created, needs_manual_image, evidence_notes, match_notes
            FROM amazon_products
            WHERE COALESCE(active, 1) = 1
            """
        )
        return [dict(row) for row in cursor.fetchall()]


def _score_product(product: dict, topic_tokens: set[str], lane: str, solution_query: str) -> float:
    keywords = _tokens(
        " ".join(
            [
                product.get("title") or "",
                product.get("description") or "",
                product.get("keywords") or "",
                product.get("solution_tags") or "",
                product.get("problem_tags") or "",
            ]
        )
    )
    product_lanes = {
        item.strip().lower()
        for item in (product.get("content_lanes") or "").split(",")
        if item.strip()
    }
    solution_tokens = _tokens(solution_query)
    overlap = len(topic_tokens & keywords)
    solution_overlap = len(solution_tokens & keywords)
    lane_score = 8.0 if lane and lane in product_lanes else 0.0
    if solution_overlap == 0 and lane_score == 0:
        return 0.0
    affordability = 2.0 if (product.get("price_tier") or "").lower() in {"affordable", "low", "budget"} else 0.0
    media_bonus = 1.0 if _has_image(product) else 0.0
    priority = float(product.get("priority_score") or 1.0)
    return (overlap * 1.5 + solution_overlap * 2.5 + lane_score + affordability + media_bonus) * priority


def _minimum_score(lane: str) -> float:
    return 13.0 if lane in SENSITIVE_LANES else 10.0


def _solution_query(tokens: set[str], lane: str) -> tuple[str, str]:
    for required, query in QUERY_RULES:
        if tokens & required:
            return query, _pain_point_for_query(query)
    return LANE_DEFAULT_SOLUTIONS.get(
        lane,
        ("gluten free meal prep containers", "making the practical next step easier for the reader"),
    )


def _pain_point_for_query(query: str) -> str:
    for default_query, pain_point in LANE_DEFAULT_SOLUTIONS.values():
        if query == default_query:
            return pain_point
    if "toaster" in query:
        return "reducing crumb drama in shared kitchens and travel situations"
    if "snack" in query:
        return "having safe backup snacks when restaurants, offices, or travel plans get complicated"
    if "storage" in query or "label" in query:
        return "making gluten-free food easier to organize, spot, and protect"
    if "scale" in query:
        return "making gluten-free recipe testing more consistent"
    return "solving the practical reader problem behind the article"


def _create_or_update_solution_search_product(
    topic_title: str,
    topic_description: str | None,
    lane: str,
    solution_query: str,
    pain_point: str,
) -> dict:
    title = f"Helpful Amazon search: {_title_case(solution_query)}"
    url = _amazon_search_url(solution_query)
    description = _description(solution_query, pain_point, lane)
    now = datetime.now(timezone.utc).isoformat()
    evidence_notes = (
        "Auto-created by the EGF affiliate solution matcher from blog topic, lane, "
        "and reusable intelligence context. This is a transparent Amazon search link, "
        "not scraped Amazon product content."
    )
    match_notes = _match_notes(solution_query, pain_point, "auto-created solution search")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT *
            FROM amazon_products
            WHERE source_type = 'auto_solution_search'
              AND lower(title) = lower(?)
            LIMIT 1
            """,
            (title,),
        )
        existing = cursor.fetchone()
        if existing:
            product_id = int(existing["product_id"])
            cursor.execute(
                """
                UPDATE amazon_products
                SET description = ?, url = ?, keywords = ?, content_lanes = ?,
                    price_tier = 'affordable', priority_score = 0.95,
                    media_status = CASE WHEN COALESCE(image_url, '') = '' THEN 'needs_image' ELSE 'complete' END,
                    needs_manual_image = CASE WHEN COALESCE(image_url, '') = '' THEN 1 ELSE 0 END,
                    evidence_notes = ?, match_notes = ?, active = 1
                WHERE product_id = ?
                """,
                (
                    description,
                    url,
                    _keywords(solution_query, topic_title, topic_description),
                    lane,
                    evidence_notes,
                    match_notes,
                    product_id,
                ),
            )
        else:
            cursor.execute(
                """
                INSERT INTO amazon_products
                    (title, description, url, image_url, keywords, content_lanes,
                     price_tier, priority_score, solution_tags, problem_tags,
                     source_type, media_status, auto_created, needs_manual_image,
                     evidence_notes, match_notes, active, last_used)
                VALUES (?, ?, ?, '', ?, ?, 'affordable', 0.95, ?, ?, 
                        'auto_solution_search', 'needs_image', 1, 1, ?, ?, 1, ?)
                """,
                (
                    title,
                    description,
                    url,
                    _keywords(solution_query, topic_title, topic_description),
                    lane,
                    solution_query,
                    pain_point,
                    evidence_notes,
                    match_notes,
                    now,
                ),
            )
            product_id = int(cursor.lastrowid)
        conn.commit()
        cursor.execute(
            """
            SELECT product_id, title, description, url, image_url, keywords,
                   content_lanes, price_tier, priority_score, active, last_used,
                   solution_tags, problem_tags, source_type, media_status,
                   auto_created, needs_manual_image, evidence_notes, match_notes
            FROM amazon_products
            WHERE product_id = ?
            """,
            (product_id,),
        )
        return _with_media_flags(dict(cursor.fetchone()))


def _amazon_search_url(query: str) -> str:
    params = {"k": query}
    if AMAZON_ASSOCIATE_TAG:
        params["tag"] = AMAZON_ASSOCIATE_TAG
    return f"https://www.amazon.com/s?{urlencode(params)}"


def _description(query: str, pain_point: str, lane: str) -> str:
    caution = ""
    if lane in SENSITIVE_LANES:
        caution = " This is a practical utility suggestion only, not a medical, legal, allergen-safety, or restaurant-safety guarantee."
    return (
        f"A budget-conscious Amazon search starting point for readers who need help with {pain_point}. "
        f"It points to options related to {query}; check current price, labels, materials, reviews, and fit before buying."
        f"{caution}"
    )


def _match_notes(solution_query: str, pain_point: str, source: str) -> str:
    return f"Matched as {source}: '{solution_query}' supports the reader pain point of {pain_point}."


def _keywords(query: str, title: str, description: str | None) -> str:
    return " ".join(sorted(_tokens(f"{query} {title} {description or ''}")))


def _with_media_flags(product: dict) -> dict:
    product["has_image"] = _has_image(product)
    product["needs_manual_image"] = 0 if product["has_image"] else 1
    product["media_status"] = "complete" if product["has_image"] else "needs_image"
    return product


def _has_image(product: dict) -> bool:
    return bool((product.get("image_url") or "").strip())


def _tokens(value: str | None) -> set[str]:
    if not value:
        return set()
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) > 2 and token not in STOPWORDS
    }


def _title_case(value: str) -> str:
    return " ".join(word.capitalize() for word in value.split())
