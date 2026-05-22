"""
recipe_wp_publisher.py
──────────────────────
Publishes an approved recipe to WordPress using WP Recipe Maker REST API.

Steps:
  1. Load recipe from generated_recipes table
  2. Upload cover image to WP Media Library
  3. POST to /wp-json/wp/v2/wprm_recipe → creates WPRM recipe block
  4. Create a standard WP post that embeds the WPRM recipe shortcode
  5. Update generated_recipes with wp_post_id, wp_url
"""

import json
import time
import sqlite3
import requests
from datetime import datetime, timezone
from pathlib import Path

from execution.config import WP_BASE_URL, WP_USERNAME, WP_APP_PASSWORD, SANDBOX_MODE, DB_PATH
from execution.utils.logger import setup_logger

logger = setup_logger("recipe_wp_publisher")


def _auth() -> tuple:
    return (WP_USERNAME, WP_APP_PASSWORD)


# ─────────────────────────────────────────────
# Step 1: Upload image to WP Media Library
# ─────────────────────────────────────────────

def _upload_image(image_path: str, title: str) -> dict | None:
    """Upload image to WP Media Library. Returns {media_id, media_url} or None."""
    image_file = Path(image_path)
    if not image_file.exists():
        logger.error(f"Image not found: {image_path}")
        return None

    if SANDBOX_MODE:
        logger.info("[SANDBOX] Simulating WP image upload...")
        time.sleep(1)
        return {
            "media_id": 999000,
            "media_url": "https://easygluten-free.com/wp-content/uploads/sandbox-recipe.jpg",
        }

    try:
        with open(image_file, "rb") as f:
            resp = requests.post(
                f"{WP_BASE_URL}/wp-json/wp/v2/media",
                headers={
                    "Content-Disposition": f'attachment; filename="{image_file.name}"',
                    "Content-Type": "image/jpeg",
                },
                data=f,
                auth=_auth(),
                timeout=30,
            )
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"Uploaded image: media_id={data['id']}")
        return {"media_id": data["id"], "media_url": data["source_url"]}
    except Exception as e:
        logger.error(f"Image upload failed: {e}")
        return None


# ─────────────────────────────────────────────
# Step 2: Create WPRM Recipe
# ─────────────────────────────────────────────

def _build_wprm_payload(
    recipe_data: dict,
    cover_media_id: int | None,
    step_media_ids: list[int | None] | None = None,
) -> dict:
    """Build the WP Recipe Maker API payload from our recipe dict.

    Args:
        recipe_data:     The recipe dict from the DB (parsed recipe_json).
        cover_media_id:  WP Media ID for the hero/cover image.
        step_media_ids:  List of WP Media IDs for the first N instruction steps
                         (index-aligned with instructions list). None entries are skipped.
    """
    ingredients = recipe_data.get("ingredients", [])
    instructions = recipe_data.get("instructions", [])
    step_media_ids = step_media_ids or []

    # WPRM ingredients format: single group
    wprm_ingredients = [
        {
            "name": "",  # No group name — flat list
            "ingredients": [
                {
                    "amount": str(ing.get("amount", "")),
                    "unit": ing.get("unit", ""),
                    "name": ing.get("name", ""),
                    "notes": ing.get("notes", ""),
                }
                for ing in ingredients
            ],
        }
    ]

    # WPRM instructions_flat format — attach step image IDs where available
    wprm_instructions = []
    wprm_instructions.append({"type": "group", "name": ""})  # single unnamed group
    for i, ins in enumerate(instructions):
        step_entry: dict = {
            "type": "instruction",
            "text": ins.get("text", ""),
        }
        # Attach step image if we have one for this index
        if i < len(step_media_ids) and step_media_ids[i]:
            step_entry["image_id"] = step_media_ids[i]
        wprm_instructions.append(step_entry)

    # ── Structured notes matching the live recipe format ──────────────────────
    # Section 1: Substitutions & Variations  (from the new `substitutions` field)
    # Section 2: Claire's Gluten-Free Baking Notes  (from `notes` field)
    # Section 3: Tips  (from `tips` field)
    notes_html_parts = []

    if recipe_data.get("substitutions"):
        notes_html_parts.append(
            "<strong>Substitutions &amp; Variations:</strong>"
            f"{recipe_data['substitutions']}"
        )

    if recipe_data.get("notes"):
        notes_html_parts.append(
            "<strong>Claire's Gluten-Free Baking Notes:</strong>"
            f"<p>{recipe_data['notes']}</p>"
        )

    if recipe_data.get("tips"):
        notes_html_parts.append(
            "<strong>Tips:</strong>"
            f"<p>{recipe_data['tips']}</p>"
        )

    combined_notes = "<br><br>".join(notes_html_parts)

    payload: dict = {
        "recipe_type": "food",
        "name": recipe_data["title"],
        "summary": recipe_data.get("description", ""),
        "author_display": "custom",
        "author_name": "Claire Bennett",
        "author_link": WP_BASE_URL,
        "servings": recipe_data.get("servings", 4),
        "servings_unit": recipe_data.get("servings_unit", "servings"),
        "prep_time": recipe_data.get("prep_time", 0),
        "cook_time": recipe_data.get("cook_time", 0),
        "total_time": recipe_data.get("total_time", 0),
        "tags": {
            "course": [recipe_data.get("category", "")],
            "keyword": recipe_data.get("tags", []),
        },
        "ingredients": wprm_ingredients,
        "instructions_flat": wprm_instructions,
        "notes": combined_notes,
    }

    if cover_media_id:
        payload["image_id"] = cover_media_id

    return payload


def _create_wprm_recipe(
    recipe_data: dict,
    cover_media_id: int | None,
    step_media_ids: list[int | None] | None = None,
) -> int | None:
    """
    POST to /wp-json/wp/v2/wprm_recipe to create the recipe.
    Returns the WPRM recipe post ID, or None on failure.

    Args:
        recipe_data:     Parsed recipe dict.
        cover_media_id:  WP media ID for the cover/hero photo.
        step_media_ids:  WP media IDs for step 1, 2, 3 (index-aligned). May contain None.
    """
    if SANDBOX_MODE:
        logger.info("[SANDBOX] Simulating WPRM recipe creation...")
        time.sleep(1)
        return 888001

    payload = _build_wprm_payload(recipe_data, cover_media_id, step_media_ids)
    try:
        resp = requests.post(
            f"{WP_BASE_URL}/wp-json/wp/v2/wprm_recipe",
            json={"title": recipe_data["title"], "status": "publish", "recipe": payload},
            auth=_auth(),
            timeout=30,
        )
        resp.raise_for_status()
        wprm_id = resp.json()["id"]
        logger.info(f"WPRM recipe created: id={wprm_id}")
        return wprm_id
    except Exception as e:
        logger.error(f"WPRM recipe creation failed: {e}")
        if hasattr(e, "response") and e.response is not None:
            logger.error(f"Response: {e.response.text}")
        return None


# ─────────────────────────────────────────────
# Step 3: Create WP Blog Post with WPRM shortcode
# ─────────────────────────────────────────────

def _create_wp_post(recipe_data: dict, wprm_recipe_id: int,
                    cover_media_id: int | None) -> dict | None:
    """
    Create a standard WP post that embeds the WPRM recipe via shortcode.
    Returns {wp_post_id, wp_url} or None.
    """
    shortcode = f'[wprm-recipe id="{wprm_recipe_id}"]'
    tags_str = ", ".join(recipe_data.get("tags", []))

    intro_html = (
        f"<p>{recipe_data.get('description', '')}</p>\n\n"
        f"{shortcode}\n\n"
        f"<p><em>Tags: {tags_str}</em></p>"
    )

    post_payload = {
        "title": recipe_data["title"],
        "content": intro_html,
        "excerpt": recipe_data.get("description", "")[:160],
        "status": "publish",
        "featured_media": cover_media_id or 0,
    }

    # Resolve WP category
    category_id = _get_or_create_category(recipe_data.get("category", "Recipes"))
    if category_id:
        post_payload["categories"] = [category_id]

    if SANDBOX_MODE:
        logger.info("[SANDBOX] Simulating WP post creation...")
        time.sleep(1)
        return {
            "wp_post_id": 999900,
            "wp_url": f"https://easygluten-free.com/sandbox-recipe-{wprm_recipe_id}",
        }

    try:
        resp = requests.post(
            f"{WP_BASE_URL}/wp-json/wp/v2/posts",
            json=post_payload,
            auth=_auth(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"WP post created: id={data['id']}, url={data['link']}")
        return {"wp_post_id": data["id"], "wp_url": data["link"]}
    except Exception as e:
        logger.error(f"WP post creation failed: {e}")
        if hasattr(e, "response") and e.response is not None:
            logger.error(f"Response: {e.response.text}")
        return None


def _get_or_create_category(name: str) -> int | None:
    """Find or create a WP category by name."""
    try:
        resp = requests.get(
            f"{WP_BASE_URL}/wp-json/wp/v2/categories",
            params={"search": name},
            auth=_auth(),
            timeout=10,
        )
        resp.raise_for_status()
        for cat in resp.json():
            if cat["name"].lower() == name.lower():
                return cat["id"]
        # Create it
        create = requests.post(
            f"{WP_BASE_URL}/wp-json/wp/v2/categories",
            json={"name": name},
            auth=_auth(),
            timeout=10,
        )
        create.raise_for_status()
        return create.json()["id"]
    except Exception as e:
        logger.warning(f"Could not resolve WP category '{name}': {e}")
        return None


# ─────────────────────────────────────────────
# Public entrypoint
# ─────────────────────────────────────────────

def publish_recipe_to_wp(recipe_id: int) -> dict | None:
    """
    Full publishing pipeline for an approved recipe:
      1. Load recipe from DB
      2. Upload cover image → WP Media
      3. Create WPRM recipe
      4. Create WP post with WPRM shortcode
      5. Update DB with WP IDs and URL
    Returns {wp_post_id, wp_url, media_url} or None.
    """
    logger.info(f"Publishing recipe_id={recipe_id} to WordPress...")

    # Load recipe
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM generated_recipes WHERE recipe_id=?", (recipe_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        logger.error(f"Recipe {recipe_id} not found in DB.")
        return None

    row = dict(row)
    recipe_data = json.loads(row["recipe_json"])

    # Upload cover image
    media_result = None
    if row.get("cover_image"):
        media_result = _upload_image(row["cover_image"], recipe_data["title"])
    cover_media_id = media_result["media_id"] if media_result else None
    media_url = media_result["media_url"] if media_result else None

    # Upload step images (up to 3) — these get attached to individual instruction steps
    step_media_ids: list[int | None] = []
    for step_key in ("step_image_1", "step_image_2", "step_image_3"):
        step_path = row.get(step_key)
        if step_path:
            step_result = _upload_image(step_path, f"{recipe_data['title']} – step {step_key[-1]}")
            step_media_ids.append(step_result["media_id"] if step_result else None)
        else:
            step_media_ids.append(None)
    logger.info(f"Step image media IDs: {step_media_ids}")

    # Create WPRM recipe (cover + step images all wired in)
    wprm_id = _create_wprm_recipe(recipe_data, cover_media_id, step_media_ids)
    if not wprm_id:
        return None

    # Create WP post
    post_result = _create_wp_post(recipe_data, wprm_id, cover_media_id)
    if not post_result:
        return None

    wp_post_id = post_result["wp_post_id"]
    wp_url = post_result["wp_url"]

    # Update DB
    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE generated_recipes SET wp_post_id=?, wp_url=?, status='published' WHERE recipe_id=?",
        (wp_post_id, wp_url, recipe_id),
    )
    conn.commit()
    conn.close()

    logger.info(f"Recipe {recipe_id} published: {wp_url}")
    return {"wp_post_id": wp_post_id, "wp_url": wp_url, "media_url": media_url, "wprm_id": wprm_id}
