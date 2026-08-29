from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from execution.config import TMP_PINS_DIR
from execution.content.blog_generator import fill_template, get_relevant_product, load_html_template
from execution.content.image_generator import generate_pin_image
from execution.content.pinterest_publisher import post_pin_to_pinterest
from execution.content.wordpress_publisher import publish_blog_to_wp, upload_image_to_wp
from execution.db import get_connection
from execution.editorial.lane_content_service import create_lane_content
from execution.models import BlogGenerationResponse, CaptionGenerationResponse
from execution.research.blog_draft_generator import generate_research_backed_blog


DEFAULT_ASSETS = ("pin", "blog", "newsletter")


def create_assets_from_idea(
    idea_id: int,
    assets: list[str] | None = None,
    sample: bool = False,
    persist: bool = True,
) -> dict:
    """Create selected publishing assets from a content_ideas row."""

    idea = _get_idea(idea_id)
    requested = _normalize_assets(assets)
    result = {"idea": idea, "generation_mode": "sample" if sample else "llm", "assets": {}}

    pin = None
    if "pin" in requested or "blog" in requested:
        pin = _build_pin_asset(idea, sample=sample, persist=persist)
        result["assets"]["pin"] = pin

    if "blog" in requested:
        if not pin:
            pin = _build_pin_asset(idea, sample=sample, persist=persist)
        result["assets"]["blog"] = _build_blog_asset(idea, pin, sample=sample, persist=persist)

    if "newsletter" in requested:
        result["assets"]["newsletter"] = _build_newsletter_asset(
            idea,
            sample=sample,
            persist=persist,
        )

    return result


def list_content_assets(limit: int = 30) -> dict:
    """Return recent website, Pinterest, and newsletter assets for dashboard review."""

    safe_limit = max(1, min(int(limit), 100))
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                b.blog_id,
                b.pin_id,
                b.title,
                b.category,
                b.status,
                b.wp_url,
                b.wp_post_id,
                b.created_at,
                b.published_at,
                p.image_path,
                p.status AS pin_status,
                i.idea_id,
                i.content_lane,
                i.angle_type
            FROM blogs b
            LEFT JOIN generated_pins p ON b.pin_id = p.pin_id
            LEFT JOIN content_ideas i ON p.idea_id = i.idea_id
            ORDER BY b.created_at DESC, b.blog_id DESC
            LIMIT ?
            """,
            (safe_limit,),
        )
        website = [dict(row) for row in cursor.fetchall()]

        cursor.execute(
            """
            SELECT
                p.pin_id,
                p.idea_id,
                p.title,
                p.description,
                p.seo_keywords,
                p.image_path,
                p.destination_url,
                p.status,
                p.created_at,
                pp.pinterest_id,
                pp.posted_at,
                i.content_lane,
                i.angle_type
            FROM generated_pins p
            LEFT JOIN posted_pins pp ON pp.pin_id = p.pin_id
            LEFT JOIN content_ideas i ON p.idea_id = i.idea_id
            ORDER BY p.created_at DESC, p.pin_id DESC
            LIMIT ?
            """,
            (safe_limit,),
        )
        pinterest = [dict(row) for row in cursor.fetchall()]

        cursor.execute(
            """
            SELECT *
            FROM content_drafts
            WHERE platform = 'newsletter'
            ORDER BY created_at DESC, draft_id DESC
            LIMIT ?
            """,
            (safe_limit,),
        )
        newsletters = [dict(row) for row in cursor.fetchall()]

    return {
        "website": website,
        "pinterest": pinterest,
        "newsletters": newsletters,
    }


def publish_blog_asset(blog_id: int) -> dict:
    """Publish one generated blog to WordPress."""

    result = publish_blog_to_wp(blog_id)
    if not result:
        raise RuntimeError("WordPress publishing returned None. Check logs for details.")
    return result


def post_pin_asset(pin_id: int) -> dict:
    """Post one generated pin to Pinterest after resolving its public link and media URL."""

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT p.*, b.wp_url
            FROM generated_pins p
            LEFT JOIN blogs b ON b.pin_id = p.pin_id
            WHERE p.pin_id = ?
            ORDER BY b.blog_id DESC
            LIMIT 1
            """,
            (pin_id,),
        )
        row = cursor.fetchone()

    if not row:
        raise ValueError("Pin not found.")
    pin = dict(row)
    destination_url = pin.get("destination_url") or pin.get("wp_url")
    if not destination_url:
        raise ValueError("Publish the website/blog asset first so the pin has a destination URL.")
    if not pin.get("image_path"):
        raise ValueError("Generate a pin image before posting to Pinterest.")

    media_result = upload_image_to_wp(pin["image_path"], f"{pin['title']} Pinterest pin")
    media_url = media_result.get("media_url") if media_result else None
    if not media_url:
        raise RuntimeError("Could not upload the pin image to WordPress media.")

    result = post_pin_to_pinterest(pin_id=pin_id, wp_url=destination_url, media_url=media_url)
    if not result:
        raise RuntimeError("Pinterest posting returned None. Check logs for details.")
    return result


def pin_copy_payload(pin_id: int) -> dict:
    """Return the text and local image URL needed for manual Pinterest posting."""

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM generated_pins WHERE pin_id = ?", (pin_id,))
        row = cursor.fetchone()

    if not row:
        raise ValueError("Pin not found.")
    pin = dict(row)
    filename = Path(pin["image_path"]).name if pin.get("image_path") else None
    return {
        "pin_id": pin["pin_id"],
        "title": pin["title"],
        "description": pin["description"],
        "seo_keywords": pin.get("seo_keywords"),
        "destination_url": pin.get("destination_url"),
        "image_url": f"/images/{filename}" if filename else None,
        "image_filename": filename,
    }


def newsletter_copy_payload(draft_id: int) -> dict:
    """Return plain newsletter copy from a content_drafts row."""

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM content_drafts WHERE draft_id = ?", (draft_id,))
        row = cursor.fetchone()

    if not row:
        raise ValueError("Newsletter draft not found.")
    draft = dict(row)
    return {"draft_id": draft_id, "text": _newsletter_text(draft), "draft": draft}


def _build_pin_asset(idea: dict, sample: bool, persist: bool) -> dict:
    caption = _sample_caption(idea) if sample else _generate_caption(idea)
    image_path = None
    pin_id = None

    if persist:
        pin_id = _upsert_pin(idea, caption)
        image_path = _sample_pin_image(caption["title"], pin_id) if sample else generate_pin_image(
            caption["title"],
            pin_id,
            subtitle=_subtitle_for_idea(idea),
        )
        if image_path:
            with get_connection() as conn:
                conn.execute("UPDATE generated_pins SET image_path = ? WHERE pin_id = ?", (image_path, pin_id))
                conn.commit()

    return {
        "pin_id": pin_id,
        "title": caption["title"],
        "description": caption["description"],
        "seo_keywords": caption["seo_keywords"],
        "image_path": image_path,
        "image_url": f"/images/{Path(image_path).name}" if image_path else None,
    }


def _build_blog_asset(idea: dict, pin: dict, sample: bool, persist: bool) -> dict:
    if sample:
        product = get_relevant_product(
            topic_title=idea["title"],
            topic_description=idea.get("description"),
            content_lane=idea.get("content_lane"),
        )
        if not product:
            raise RuntimeError("No Amazon products are available.")
        content = _sample_blog_content(idea)
        html = fill_template(load_html_template(), content, product)
        if not persist:
            return {"blog_id": None, "title": content.main_title, "category": content.category}
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO blogs (pin_id, title, html_content, category, product_id, status)
                VALUES (?, ?, ?, ?, ?, 'generated')
                """,
                (pin["pin_id"], content.main_title, html, content.category, product["product_id"]),
            )
            blog_id = int(cursor.lastrowid)
            conn.commit()
        return {"blog_id": blog_id, "title": content.main_title, "category": content.category}

    if not persist:
        return {"blog_id": None, "title": idea["title"], "category": "Preview only"}

    blog = generate_research_backed_blog(
        int(pin["pin_id"]),
        lane=idea.get("content_lane"),
        angle_type=idea.get("angle_type"),
        forced_title=idea["title"],
    )
    if not blog:
        raise RuntimeError("Blog generation returned None.")
    return {
        "blog_id": blog["blog_id"],
        "title": blog["title"],
        "category": blog["category"],
        "source_notes": blog.get("source_notes", []),
        "verification_notes": blog.get("verification_notes", []),
        "status_recommendation": blog.get("status_recommendation", "ready_for_review"),
    }


def _build_newsletter_asset(idea: dict, sample: bool, persist: bool) -> dict:
    if sample:
        content = {
            "title": idea["title"],
            "dek": idea.get("description") or "",
            "sections": [
                {"heading": "Opening Note", "body": f"Quick gluten-free note: {idea['title']}"},
                {"heading": "Why It Matters", "body": idea.get("description") or "A practical reader-first angle."},
                {"heading": "Try This", "body": "Save the idea, verify the source, and turn it into a short newsletter section."},
            ],
            "call_to_action": "Reply with the gluten-free problem you want solved next.",
            "source_notes": [idea.get("source_hint") or "No live sources fetched in sample mode."],
            "verification_notes": ["Sample mode only."],
            "status_recommendation": "ready_for_review",
        }
        if not persist:
            return {"draft_id": None, "title": content["title"], "text": _content_json_to_text(content)}
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO content_drafts
                    (topic_title, lane, angle_type, platform, title, dek,
                     content_json, source_urls_json, status)
                VALUES (?, ?, ?, 'newsletter', ?, ?, ?, '[]', 'pending_review')
                """,
                (
                    idea["title"],
                    idea.get("content_lane"),
                    idea.get("angle_type"),
                    content["title"],
                    content["dek"],
                    json.dumps(content),
                ),
            )
            draft_id = int(cursor.lastrowid)
            conn.commit()
        return {"draft_id": draft_id, "title": content["title"], "text": _content_json_to_text(content)}

    if not persist:
        return {"draft_id": None, "title": idea["title"], "text": "Preview only. Enable persist to generate a draft."}

    result = create_lane_content(
        lane_key=idea["content_lane"],
        topic_title=idea["title"],
        platform="newsletter",
        angle_type=idea.get("angle_type"),
        sample=False,
        persist=True,
    )
    draft_id = result.get("draft_id")
    draft = result.get("draft", {})
    return {"draft_id": draft_id, "title": draft.get("title") or idea["title"]}


def _get_idea(idea_id: int) -> dict:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM content_ideas WHERE idea_id = ?", (idea_id,))
        row = cursor.fetchone()
    if not row:
        raise ValueError("Content idea not found.")
    idea = dict(row)
    if idea.get("content_lane") == "recipe_experiments" and idea.get("content_type") == "recipe":
        idea["content_type"] = "education"
    return idea


def _upsert_pin(idea: dict, caption: dict) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT pin_id
            FROM generated_pins
            WHERE idea_id = ?
            ORDER BY pin_id DESC
            LIMIT 1
            """,
            (idea["idea_id"],),
        )
        existing = cursor.fetchone()
        if existing:
            pin_id = int(existing["pin_id"])
            cursor.execute(
                """
                UPDATE generated_pins
                SET title = ?, description = ?, seo_keywords = ?
                WHERE pin_id = ?
                """,
                (caption["title"], caption["description"], caption["seo_keywords"], pin_id),
            )
        else:
            cursor.execute(
                """
                INSERT INTO generated_pins
                    (idea_id, title, description, seo_keywords, status, batch_date)
                VALUES (?, ?, ?, ?, 'pending', date('now'))
                """,
                (idea["idea_id"], caption["title"], caption["description"], caption["seo_keywords"]),
            )
            pin_id = int(cursor.lastrowid)
        conn.commit()
    return pin_id


def _generate_caption(idea: dict) -> dict:
    from execution.config import PROMPTS_DIR
    from execution.utils.llm_client import LLMClient

    system_prompt = (PROMPTS_DIR / "brand_system_prompt.txt").read_text(encoding="utf-8")
    user_prompt_template = (PROMPTS_DIR / "caption_generation.txt").read_text(encoding="utf-8")
    user_prompt = user_prompt_template.format(
        idea_title=idea["title"],
        content_type=idea.get("content_type") or "education",
        target_keyword=idea["title"].lower(),
        content_lane=idea.get("content_lane") or "unspecified",
        angle_type=idea.get("angle_type") or "unspecified",
        freshness_hook=idea.get("freshness_hook") or idea.get("source_hint") or "Make the value concrete.",
    )
    response: CaptionGenerationResponse = LLMClient().generate_structured(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_format=CaptionGenerationResponse,
        task_name="single_caption_generation",
    )
    return {
        "title": response.pin_title,
        "description": f"{response.pin_description}\n\n" + " ".join(response.hashtags),
        "seo_keywords": ",".join(response.hashtags),
    }


def _sample_caption(idea: dict) -> dict:
    tags = ["#glutenfree", "#glutenfreelife", "#easyglutenfree"]
    return {
        "title": idea["title"][:70],
        "description": f"{idea.get('description') or idea['title']}\n\n" + " ".join(tags),
        "seo_keywords": ",".join(tags),
    }


def _sample_pin_image(title: str, pin_id: int) -> str:
    TMP_PINS_DIR.mkdir(parents=True, exist_ok=True)
    output = TMP_PINS_DIR / f"pin_{pin_id}.jpg"
    img = Image.new("RGB", (1000, 1500), "#f7f1e8")
    draw = ImageDraw.Draw(img)
    try:
        title_font = ImageFont.truetype("C:/Windows/Fonts/georgiab.ttf", 70)
        small_font = ImageFont.truetype("C:/Windows/Fonts/georgia.ttf", 34)
    except OSError:
        title_font = ImageFont.load_default()
        small_font = ImageFont.load_default()

    draw.rectangle((70, 70, 930, 1430), outline="#1f2a37", width=6)
    draw.text((110, 160), "Easy Gluten Free", fill="#2f6f4e", font=small_font)
    y = 420
    for line in _wrap_for_image(title.upper(), title_font, 760, draw):
        draw.text((110, y), line, fill="#1f2a37", font=title_font)
        y += 92
    draw.text((110, 1260), "Sample Pinterest asset", fill="#6b7280", font=small_font)
    img.save(output, "JPEG", quality=95)
    return str(output)


def _wrap_for_image(text: str, font, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:8]


def _sample_blog_content(idea: dict) -> BlogGenerationResponse:
    return BlogGenerationResponse(
        main_title=idea["title"],
        ebook_hero_title="Your 7-Day Beginner's Guide to Delicious & Stress-Free Meals",
        intro_paragraph=idea.get("description") or "A practical gluten-free guide.",
        intro_paragraph_1=f"<p>{idea.get('description') or idea['title']}</p>",
        intro_paragraph_2="<p>This sample blog asset uses the live template and stays review-only.</p>",
        intro_paragraph_3="<p>Use it to inspect layout, product fit, and publishing workflow before spending tokens.</p>",
        section_1_title="The Reader Problem",
        section_1_content="<p>Start with the real gluten-free decision the reader is trying to make.</p>",
        section_2_title="What Helps",
        section_2_content="<p>Connect the topic to one useful product, source, or practical system.</p>",
        section_3_title="How To Decide",
        section_3_content="<p>Give clear criteria: safety, usefulness, cost, repeat use, and confidence.</p>",
        section_4_title="Claire's Take",
        section_4_content="<p>Opinionated, fair, and useful. No miracle claims required.</p>",
        section_5_title="Next Step",
        section_5_content="<p>Choose one check or action to try this week.</p>",
        takeaway_1="Specific topics beat generic gluten-free basics.",
        takeaway_2="Verify sensitive claims before publishing.",
        takeaway_3="Match products to the reader problem.",
        takeaway_4="Keep the next action clear.",
        takeaway_5="Review before scheduling.",
        category="Gluten-Free Living",
        source_notes=["Sample mode only. No live sources were fetched."],
        verification_notes=["Sample mode only."],
        status_recommendation="ready_for_review",
    )


def _normalize_assets(assets: list[str] | None) -> list[str]:
    allowed = set(DEFAULT_ASSETS)
    if not assets:
        return list(DEFAULT_ASSETS)
    normalized = [asset for asset in assets if asset in allowed]
    if not normalized:
        raise ValueError("At least one asset is required: pin, blog, newsletter.")
    return normalized


def _subtitle_for_idea(idea: dict) -> str:
    lane = idea.get("content_lane") or ""
    if lane in {"laws_labeling", "science_health"}:
        return "Know Your Ingredients"
    if lane in {"gadgets_tools", "organization_life", "apps_digital"}:
        return "Tips & Tools"
    return "Easy Gluten-Free Help"


def _newsletter_text(draft: dict) -> str:
    try:
        content = json.loads(draft.get("content_json") or "{}")
    except json.JSONDecodeError:
        content = {}
    if content:
        return _content_json_to_text(content)
    return f"{draft.get('title', '')}\n\n{draft.get('dek', '')}".strip()


def _content_json_to_text(content: dict) -> str:
    parts = [content.get("title", ""), content.get("dek", "")]
    for section in content.get("sections", []):
        parts.append(section.get("heading", ""))
        parts.append(section.get("body", ""))
    if content.get("call_to_action"):
        parts.append("CTA")
        parts.append(content["call_to_action"])
    return "\n\n".join(part for part in parts if part).strip()
