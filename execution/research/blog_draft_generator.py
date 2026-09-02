"""Research-backed blog generation.

Replaces the old execution.content.blog_generator.generate_blog(), which
only ever received a title and a 160-character Pinterest caption -- no real
source text -- despite its prompt claiming to "address real gluten-free pain
points sourced from Reddit and the GF community." This module runs the same
research pipeline used for newsletter/pinterest drafts (run_research) before
writing, and the LLM is held to the same "only use collected-source facts"
discipline as platform_draft_generation.txt.

The output still fills the locked Blog-Template.md and writes into the same
`blogs` table shape as before, so wordpress_publisher.py needs no changes.
"""

from __future__ import annotations

import json

from execution.config import PROMPTS_DIR
from execution.content.blog_generator import (
    _blog_content_problems,
    fill_template,
    get_relevant_product,
    load_html_template,
    mark_product_used,
)
from execution.db import get_connection
from execution.models import BlogGenerationResponse
from execution.research.research_runner import run_research
from execution.utils.llm_client import LLMClient
from execution.utils.logger import setup_logger

logger = setup_logger("blog_draft_generator")


def generate_blog_content(
    topic_title: str,
    topic_description: str | None = None,
    lane: str | None = None,
    angle_type: str | None = None,
    forced_title: str | None = None,
    limit_per_task: int = 5,
    persist_research: bool = True,
) -> dict | None:
    """Run research + LLM to produce blog content and pick a product.

    Returns {"content": BlogGenerationResponse, "product": dict, "research": dict, "html": str}
    or None on failure. Does not write to the `blogs` table -- callers decide
    whether/how to persist (see generate_research_backed_blog below for the
    real pipeline path, or the dashboard's blog-preview route for a
    persist-free preview).
    """

    research_result = run_research(
        topic_title=topic_title,
        lane=lane,
        angle_type=angle_type,
        platform="blog",
        limit_per_task=limit_per_task,
        persist=persist_research,
    )
    resolved_lane = research_result["brief"]["lane"]

    product = get_relevant_product(
        topic_title=topic_title,
        topic_description=topic_description or research_result["brief"].get("reader_problem"),
        content_lane=resolved_lane,
    )
    if not product:
        logger.error("No Amazon products available in DB. Run db.py to seed them.")
        return None

    try:
        system_prompt = (PROMPTS_DIR / "brand_system_prompt.txt").read_text(encoding="utf-8")
        user_prompt_template = (PROMPTS_DIR / "blog_generation.txt").read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to load blog prompt templates: {e}")
        return None

    user_prompt = user_prompt_template.format(
        topic_title=topic_title,
        lane=resolved_lane,
        angle_type=angle_type or "unspecified",
        brief_json=json.dumps(research_result["brief"], indent=2),
        platform_package_json=json.dumps(research_result["platform_package"], indent=2),
        sources_json=json.dumps(research_result["sources"], indent=2),
        product_title=product["title"],
        product_description=product["description"],
        product_match_notes=product.get("match_notes") or "Matched by topic, lane, and reader pain point.",
    )
    if forced_title:
        user_prompt += (
            "\n\nLOCKED BLOG TITLE:\n"
            f"{forced_title}\n\n"
            "Use this exact text for `main_title`. Do not rewrite, expand, shorten, or retitle it."
        )

    client = LLMClient()
    try:
        content: BlogGenerationResponse = client.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format=BlogGenerationResponse,
            task_name="blog_generation",
        )
        # Quality gate: catch outline/placeholder language or too-short
        # sections and give the model one corrective retry before giving up.
        problems = _blog_content_problems(content)
        if problems:
            retry_prompt = (
                f"{user_prompt}\n\n"
                "The previous response was not acceptable for review because: "
                f"{'; '.join(problems)}.\n\n"
                "Regenerate a complete final reader-facing blog post. Do not return an outline, "
                "placeholder, section prompt, or instruction telling an editor what to write later."
            )
            content = client.generate_structured(
                system_prompt=system_prompt,
                user_prompt=retry_prompt,
                response_format=BlogGenerationResponse,
                task_name="blog_generation_retry",
            )
            retry_problems = _blog_content_problems(content)
            if retry_problems:
                logger.error(
                    "Generated blog was not saved because it was not final reader-facing copy: %s",
                    "; ".join(retry_problems),
                )
                return None
        if forced_title:
            content.main_title = forced_title
    except Exception as e:
        logger.error(f"LLM call failed for blog generation: {e}")
        return None

    try:
        final_html = fill_template(load_html_template(), content, product)
    except Exception as e:
        logger.error(f"Failed to fill HTML template: {e}")
        return None

    return {"content": content, "product": product, "research": research_result, "html": final_html}


def generate_research_backed_blog(
    pin_id: int,
    lane: str | None = None,
    angle_type: str | None = None,
    forced_title: str | None = None,
    limit_per_task: int = 5,
) -> dict | None:
    """Generate a complete, research-backed blog for an existing pin and save
    it to the `blogs` table. Drop-in replacement for the old
    execution.content.blog_generator.generate_blog()."""

    logger.info(f"Starting research-backed blog generation for pin_id={pin_id}")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT p.pin_id, p.title, p.description, p.image_path,
                   i.content_type, i.content_lane, i.angle_type
            FROM generated_pins p
            LEFT JOIN content_ideas i ON p.idea_id = i.idea_id
            WHERE p.pin_id = ?
            """,
            (pin_id,),
        )
        pin = cursor.fetchone()

    if not pin:
        logger.error(f"Pin {pin_id} not found in DB.")
        return None
    pin = dict(pin)

    resolved_lane = lane or pin.get("content_lane")
    resolved_angle = angle_type or pin.get("angle_type")
    resolved_title = forced_title or pin["title"]

    generated = generate_blog_content(
        topic_title=resolved_title,
        topic_description=pin["description"],
        lane=resolved_lane,
        angle_type=resolved_angle,
        forced_title=resolved_title,
        limit_per_task=limit_per_task,
        persist_research=True,
    )
    if not generated:
        return None
    content = generated["content"]
    product = generated["product"]
    final_html = generated["html"]

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO blogs (pin_id, title, html_content, category, product_id, status)
            VALUES (?, ?, ?, ?, ?, 'generated')
            """,
            (pin_id, content.main_title, final_html, content.category, product["product_id"]),
        )
        blog_id = cursor.lastrowid
        conn.commit()
    logger.info(f"Blog saved to DB with blog_id={blog_id}")

    mark_product_used(product["product_id"])

    return {
        "blog_id": blog_id,
        "pin_id": pin_id,
        "title": content.main_title,
        "category": content.category,
        "html_content": final_html,
        "product_id": product["product_id"],
        "product": product,
        "image_path": pin["image_path"],
        "source_notes": content.source_notes,
        "verification_notes": content.verification_notes,
        "status_recommendation": content.status_recommendation,
    }
