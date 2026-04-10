import re
from datetime import datetime, timezone
from pathlib import Path
from execution.config import PROMPTS_DIR, BLOG_TEMPLATE_PATH
from execution.db import get_connection
from execution.models import BlogGenerationResponse
from execution.utils.llm_client import LLMClient
from execution.utils.logger import setup_logger

logger = setup_logger("blog_generator")


# ──────────────────────────────────────────────
# Product rotation
# ──────────────────────────────────────────────

def get_next_product() -> dict | None:
    """Return the Amazon product with the oldest last_used date."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT product_id, title, description, url, image_url, last_used
            FROM amazon_products
            ORDER BY last_used ASC
            LIMIT 1
        """)
        row = cursor.fetchone()
        return dict(row) if row else None


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
    html = html.replace("{{49.`1`}}", product["title"])
    html = html.replace("{{49.`2`}}", product["description"])
    html = html.replace("{{49.`3`}}", product["url"])
    html = html.replace("{{49.`4`}}", product["image_url"])

    # Sanity check — warn if any placeholders remain unfilled
    remaining = re.findall(r"\[([A-Z_0-9]+)\]", html)
    if remaining:
        logger.warning(f"Unfilled placeholders detected: {remaining}")

    return html


# ──────────────────────────────────────────────
# Main entrypoint
# ──────────────────────────────────────────────

def generate_blog(pin_id: int) -> dict | None:
    """
    Generate a complete blog HTML from an approved pin.
    
    Steps:
    1. Load pin data from DB
    2. Pick the Amazon product with the oldest last_used
    3. Call LLM to generate all blog content fields
    4. Fill the locked HTML template
    5. Save blog record to DB
    6. Mark product as used
    Returns the saved blog record dict, or None on failure.
    """
    logger.info(f"Starting blog generation for pin_id={pin_id}")

    # 1. Load pin data
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.pin_id, p.title, p.description, p.image_path, i.content_type
            FROM generated_pins p
            LEFT JOIN content_ideas i ON p.idea_id = i.idea_id
            WHERE p.pin_id = ?
        """, (pin_id,))
        pin = cursor.fetchone()

    if not pin:
        logger.error(f"Pin {pin_id} not found in DB.")
        return None

    pin = dict(pin)

    # 2. Pick product
    product = get_next_product()
    if not product:
        logger.error("No Amazon products available in DB. Run db.py to seed them.")
        return None

    logger.info(f"Selected product: {product['title']} (last_used: {product['last_used']})")

    # 3. Load prompts
    try:
        system_prompt = (PROMPTS_DIR / "brand_system_prompt.txt").read_text(encoding="utf-8")
        user_prompt_template = (PROMPTS_DIR / "blog_generation.txt").read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to load blog prompt templates: {e}")
        return None

    user_prompt = user_prompt_template.format(
        pin_topic=pin["title"],
        pin_description=pin["description"],
        product_title=product["title"],
        product_description=product["description"],
    )

    # 4. Call LLM
    client = LLMClient()
    try:
        content: BlogGenerationResponse = client.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format=BlogGenerationResponse,
            task_name="blog_generation"
        )
    except Exception as e:
        logger.error(f"LLM call failed for blog generation: {e}")
        return None

    # 5. Fill HTML template
    try:
        template_html = load_html_template()
        final_html = fill_template(template_html, content, product)
    except Exception as e:
        logger.error(f"Failed to fill HTML template: {e}")
        return None

    # 6. Save to blogs table
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO blogs (pin_id, title, html_content, category, product_id, status)
            VALUES (?, ?, ?, ?, ?, 'generated')
        """, (pin_id, content.main_title, final_html, content.category, product["product_id"]))
        blog_id = cursor.lastrowid
        conn.commit()

    logger.info(f"Blog saved to DB with blog_id={blog_id}")

    # 7. Mark product as used
    mark_product_used(product["product_id"])

    return {
        "blog_id": blog_id,
        "pin_id": pin_id,
        "title": content.main_title,
        "category": content.category,
        "html_content": final_html,
        "product_id": product["product_id"],
        "image_path": pin["image_path"],
    }
