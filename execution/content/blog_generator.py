import re

from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from execution.config import AMAZON_ASSOCIATE_TAG, BLOG_TEMPLATE_PATH
from execution.content.affiliate_products import select_solution_product_for_blog
from execution.db import get_connection
from execution.models import BlogGenerationResponse
from execution.utils.logger import setup_logger

logger = setup_logger("blog_generator")

# NOTE: the ungrounded generate_blog() entrypoint that used to live here has
# been replaced by execution.research.blog_draft_generator, which runs real
# research before writing instead of an LLM call from a title + caption
# alone. This module now only keeps the reusable template/product utilities
# both the old and new paths share.


# ──────────────────────────────────────────────
# Product rotation
# ──────────────────────────────────────────────

def _tokenize(value: str | None) -> set[str]:
    """Return normalized keywords from free text."""
    if not value:
        return set()
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) > 2
    }


def _split_csv(value: str | None) -> set[str]:
    """Return normalized comma-separated values."""
    if not value:
        return set()
    return {
        item.strip().lower()
        for item in value.split(",")
        if item.strip()
    }


def _score_product(product: dict, topic_tokens: set[str], content_lane: str | None) -> float:
    """Score a product by lane fit, keyword overlap, and editorial priority."""
    keywords = _tokenize(product.get("keywords"))
    product_lanes = _split_csv(product.get("content_lanes"))
    normalized_lane = (content_lane or "").strip().lower()

    keyword_score = len(topic_tokens & keywords) * 2.0
    lane_score = 8.0 if normalized_lane and normalized_lane in product_lanes else 0.0
    affordable_score = 1.5 if (product.get("price_tier") or "").lower() == "affordable" else 0.0
    priority_score = float(product.get("priority_score") or 1.0)

    return (keyword_score + lane_score + affordable_score) * priority_score


def _apply_amazon_associate_tag(url: str) -> str:
    """Attach the configured Amazon Associates tag to direct Amazon links."""
    if not AMAZON_ASSOCIATE_TAG:
        return url

    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if "amazon." not in host:
        return url

    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["tag"] = AMAZON_ASSOCIATE_TAG
    return urlunparse(parsed._replace(query=urlencode(query)))


def get_relevant_product(
    topic_title: str,
    topic_description: str | None = None,
    content_lane: str | None = None,
) -> dict | None:
    """Return a solution-based affiliate product for the blog topic."""
    return select_solution_product_for_blog(topic_title, topic_description, content_lane)


def get_catalog_product(
    topic_title: str,
    topic_description: str | None = None,
    content_lane: str | None = None,
) -> dict | None:
    """Return the approved Amazon product that best matches the blog topic."""
    topic_tokens = _tokenize(f"{topic_title} {topic_description or ''} {content_lane or ''}")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                product_id,
                title,
                description,
                url,
                image_url,
                keywords,
                content_lanes,
                price_tier,
                priority_score,
                last_used
            FROM amazon_products
            WHERE COALESCE(active, 1) = 1
        """)
        products = [dict(row) for row in cursor.fetchall()]

    if not products:
        return None

    scored_products = [
        (_score_product(product, topic_tokens, content_lane), product)
        for product in products
    ]
    best_score = max(score for score, _ in scored_products)

    if best_score <= 0:
        logger.info("No strong Amazon product match found. Falling back to oldest last_used.")
        return sorted(products, key=lambda p: p.get("last_used") or "")[0]

    candidates = [
        product
        for score, product in scored_products
        if score == best_score
    ]
    return sorted(candidates, key=lambda p: p.get("last_used") or "")[0]


def get_next_product() -> dict | None:
    """Compatibility wrapper for older callers."""
    return get_relevant_product("")


def mark_product_used(product_id: int):
    """Update the last_used timestamp for the product just selected."""
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE amazon_products SET last_used = ? WHERE product_id = ?",
            (now, product_id)
        )
        conn.commit()
    logger.info(f"Updated last_used for product_id={product_id}")


# ──────────────────────────────────────────────
# HTML template filling
# ──────────────────────────────────────────────

def load_html_template() -> str:
    """Extract the locked HTML block from Blog-Template.md."""
    raw = BLOG_TEMPLATE_PATH.read_text(encoding="utf-8")

    # Extract content between the ```html and ``` fences
    match = re.search(r"```html\s*(.*?)```", raw, re.DOTALL)
    if not match:
        raise ValueError("Could not find ```html block in Blog-Template.md")
    return match.group(1).strip()


def fill_template(template: str, content: BlogGenerationResponse, product: dict) -> str:
    """Replace all placeholders in the HTML template with generated content."""
    html = template

    # Simple text placeholders
    replacements = {
        "[MAIN_TITLE_DYNAMIC]":  content.main_title,
        "[EBOOK_HERO_TITLE]":    content.ebook_hero_title,
        "[INTRO_PARAGRAPH]":     content.intro_paragraph,
        "[INTRO_PARAGRAPH_1]":   content.intro_paragraph_1,
        "[INTRO_PARAGRAPH_2]":   content.intro_paragraph_2,
        "[INTRO_PARAGRAPH_3]":   content.intro_paragraph_3,
        "[SECTION_1_TITLE]":     content.section_1_title,
        "[SECTION_1_CONTENT]":   content.section_1_content,
        "[SECTION_2_TITLE]":     content.section_2_title,
        "[SECTION_2_CONTENT]":   content.section_2_content,
        "[SECTION_3_TITLE]":     content.section_3_title,
        "[SECTION_3_CONTENT]":   content.section_3_content,
        "[SECTION_4_TITLE]":     content.section_4_title,
        "[SECTION_4_CONTENT]":   content.section_4_content,
        "[SECTION_5_TITLE]":     content.section_5_title,
        "[SECTION_5_CONTENT]":   content.section_5_content,
        "[TAKEAWAY_1]":          content.takeaway_1,
        "[TAKEAWAY_2]":          content.takeaway_2,
        "[TAKEAWAY_3]":          content.takeaway_3,
        "[TAKEAWAY_4]":          content.takeaway_4,
        "[TAKEAWAY_5]":          content.takeaway_5,
        "[CATEGORY]":            content.category,
    }

    for placeholder, value in replacements.items():
        html = html.replace(placeholder, value)

    # Amazon product block (Make.com-style variables replaced with real data)
    product_image_url = (product.get("image_url") or "").strip()
    if not product_image_url:
        html = re.sub(
            r"\s*<div class=\"egf-split-card-2025__image\">\s*"
            r"<img src=\"\{\{49\.`4`\}\}\" alt=\"\{\{49\.`1`\}\}\">\s*"
            r"</div>",
            "",
            html,
        )
    html = html.replace("{{49.`1`}}", product["title"])
    html = html.replace("{{49.`2`}}", product["description"])
    html = html.replace("{{49.`3`}}", _apply_amazon_associate_tag(product["url"]))
    html = html.replace("{{49.`4`}}", product_image_url)

    # Sanity check — warn if any placeholders remain unfilled
    remaining = re.findall(r"\[([A-Z_0-9]+)\]", html)
    if remaining:
        logger.warning(f"Unfilled placeholders detected: {remaining}")

    return html


# ──────────────────────────────────────────────
# Quality gate — shared by the research-backed generator
# ──────────────────────────────────────────────

def _blog_content_problems(content: BlogGenerationResponse) -> list[str]:
    """Return reasons generated blog content should not enter review."""

    sections = [
        content.section_1_content,
        content.section_2_content,
        content.section_3_content,
        content.section_4_content,
        content.section_5_content,
    ]
    text = "\n".join(
        [
            content.main_title,
            content.intro_paragraph,
            content.intro_paragraph_1,
            content.intro_paragraph_2,
            content.intro_paragraph_3,
            content.section_1_title,
            content.section_2_title,
            content.section_3_title,
            content.section_4_title,
            content.section_5_title,
            *sections,
            content.takeaway_1,
            content.takeaway_2,
            content.takeaway_3,
            content.takeaway_4,
            content.takeaway_5,
        ]
    )
    lower_text = text.lower()
    problems: list[str] = []
    outline_markers = (
        "todo",
        "tbd",
        "placeholder",
        "outline",
        "section should",
        "this section should",
        "write a section",
        "write an intro",
        "write copy",
        "add details",
        "expand on",
        "fill in",
        "insert ",
        "[",
        "]",
    )
    found_markers = [marker for marker in outline_markers if marker in lower_text]
    if found_markers:
        problems.append("contains outline or placeholder language: " + ", ".join(found_markers[:4]))
    if len(text.split()) < 900:
        problems.append("too short for a complete blog post")
    short_sections = [str(index + 1) for index, section in enumerate(sections) if len(section.split()) < 80]
    if short_sections:
        problems.append("short blog sections: " + ", ".join(short_sections))
    return problems
