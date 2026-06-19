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
from html import escape
from datetime import datetime, timezone
from pathlib import Path

from execution.config import WP_BASE_URL, WP_USERNAME, WP_APP_PASSWORD, SANDBOX_MODE, DB_PATH
from execution.utils.logger import setup_logger

logger = setup_logger("recipe_wp_publisher")


def _auth() -> tuple:
    return (WP_USERNAME, WP_APP_PASSWORD)


def _to_float_amount(value: object) -> float | None:
    """Parse common recipe quantities such as 1, 1/2, or 1 1/2."""
    if value is None:
        return None

    text = str(value).strip().lower()
    if not text:
        return None

    text = text.replace("about ", "").replace("approx. ", "").replace("approximately ", "")
    text = text.split("-")[0].strip()
    if not text:
        return None

    total = 0.0
    parsed_any = False
    for part in text.split():
        try:
            if "/" in part:
                numerator, denominator = part.split("/", 1)
                total += float(numerator) / float(denominator)
            else:
                total += float(part)
            parsed_any = True
        except (TypeError, ValueError, ZeroDivisionError):
            continue

    return total if parsed_any else None


def _estimate_ingredient_kcal(ingredient: dict) -> float:
    """Return a rough calorie estimate for common generated recipe ingredients."""
    amount = _to_float_amount(ingredient.get("amount"))
    if amount is None:
        return 0.0

    unit = str(ingredient.get("unit", "")).strip().lower()
    name = str(ingredient.get("name", "")).strip().lower()
    notes = str(ingredient.get("notes", "")).strip().lower()
    full_text = f"{name} {notes}"

    def per_unit(values: dict[str, float]) -> float:
        normalized_unit = unit.rstrip("s")
        return amount * values.get(normalized_unit, values.get("", 0.0))

    if "olive oil" in full_text or full_text.endswith(" oil") or " avocado oil" in full_text:
        return per_unit({"tbsp": 119, "tablespoon": 119, "tsp": 40, "teaspoon": 40, "cup": 1909})
    if "butter" in full_text:
        return per_unit({"tbsp": 102, "tablespoon": 102, "tsp": 34, "teaspoon": 34, "cup": 1628})
    if "sugar" in full_text or "maple syrup" in full_text or "honey" in full_text:
        return per_unit({"cup": 774, "tbsp": 49, "tablespoon": 49, "tsp": 16, "teaspoon": 16})
    if "flour" in full_text:
        return per_unit({"cup": 455, "tbsp": 28, "tablespoon": 28})
    if "rice" in full_text:
        return per_unit({"cup": 640})
    if "quinoa" in full_text:
        return per_unit({"cup": 222})
    if "oat" in full_text:
        return per_unit({"cup": 307})
    if "parmesan" in full_text:
        return per_unit({"cup": 431, "tbsp": 22, "tablespoon": 22, "oz": 122})
    if "cheddar" in full_text or "mozzarella" in full_text or "cheese" in full_text:
        return per_unit({"cup": 400, "oz": 110, "tbsp": 25, "tablespoon": 25})
    if "heavy cream" in full_text:
        return per_unit({"cup": 821, "tbsp": 51, "tablespoon": 51})
    if "coconut cream" in full_text:
        return per_unit({"cup": 792, "tbsp": 50, "tablespoon": 50})
    if "coconut milk" in full_text:
        return per_unit({"cup": 445, "tbsp": 28, "tablespoon": 28})
    if "milk" in full_text:
        return per_unit({"cup": 149})
    if "egg" in full_text:
        return per_unit({"": 72, "large": 72})
    if "onion" in full_text:
        return per_unit({"": 44, "medium": 44, "large": 60, "small": 30, "cup": 64})
    if "garlic" in full_text:
        return per_unit({"clove": 4, "": 4, "tsp": 4, "teaspoon": 4})
    if "tomato" in full_text:
        return per_unit({"can": 50, "medium": 22, "cup": 32})
    if "zucchini" in full_text:
        return per_unit({"medium": 33, "cup": 20, "": 33})
    if "sweet potato" in full_text:
        return per_unit({"medium": 112, "cup": 180, "lb": 390, "oz": 24})
    if "potato" in full_text:
        return per_unit({"medium": 161, "cup": 136, "lb": 350, "oz": 22})
    if "chicken" in full_text:
        return per_unit({"lb": 748, "oz": 47, "cup": 335})
    if "beef" in full_text:
        return per_unit({"lb": 1000, "oz": 63, "cup": 339})
    if "bean" in full_text or "chickpea" in full_text:
        return per_unit({"can": 350, "cup": 225})
    if "lentil" in full_text:
        return per_unit({"cup": 230})
    if "broth" in full_text or "stock" in full_text:
        return per_unit({"cup": 15})
    if "basil" in full_text or "spinach" in full_text or "herb" in full_text:
        return per_unit({"cup": 7})

    return 0.0


def _get_kcal_per_serving(recipe_data: dict) -> int | None:
    """Use generated nutrition first; otherwise estimate from common ingredients."""
    for key in ("kcal_per_serving", "calories_per_serving", "calories"):
        value = recipe_data.get(key)
        try:
            if value is not None and int(value) > 0:
                return int(value)
        except (TypeError, ValueError):
            continue

    total_kcal = sum(_estimate_ingredient_kcal(ing) for ing in recipe_data.get("ingredients", []))
    servings = recipe_data.get("servings") or 1
    try:
        servings_count = max(float(servings), 1.0)
    except (TypeError, ValueError):
        servings_count = 1.0

    if total_kcal <= 0:
        return None
    return max(1, round(total_kcal / servings_count))


def _build_nutrition_html(recipe_data: dict) -> str:
    kcal = _get_kcal_per_serving(recipe_data)
    if not kcal:
        return ""

    return (
        "<h2>Nutrition Facts</h2>\n"
        "<ul class=\"egf-nutrition-facts\">\n"
        f"<li><strong>Calories:</strong> about {kcal} kcal per serving</li>\n"
        "</ul>"
    )


def _build_step_instructions_html(recipe_data: dict, step_media_results: list[dict | None]) -> str:
    instructions = recipe_data.get("instructions", [])
    if not instructions:
        return ""

    title = recipe_data.get("title", "Recipe")
    parts = ["<h2>Step-by-Step Instructions</h2>", "<ol class=\"egf-step-instructions\">"]

    for i, instruction in enumerate(instructions):
        text = escape(str(instruction.get("text", "")))
        parts.append(f"<li><p>{text}</p>")

        media = step_media_results[i] if i < len(step_media_results) else None
        media_url = media.get("media_url") if media else None
        if media_url:
            step_number = instruction.get("step_number") or i + 1
            alt = escape(f"{title} step {step_number}")
            parts.append(
                "<figure class=\"wp-block-image size-large egf-step-image\">"
                f"<img src=\"{escape(media_url, quote=True)}\" alt=\"{alt}\" loading=\"lazy\" />"
                "</figure>"
            )

        parts.append("</li>")

    parts.append("</ol>")
    return "\n".join(parts)


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


def build_wprm_import_payload(
    recipe_data: dict,
    cover_media_id: int | None = None,
    step_media_ids: list[int | None] | None = None,
) -> dict:
    """Build a JSON payload suitable for creating a WPRM recipe via WP REST."""
    return {
        "title": recipe_data["title"],
        "status": "publish",
        "recipe": _build_wprm_payload(recipe_data, cover_media_id, step_media_ids),
    }


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

    payload = build_wprm_import_payload(recipe_data, cover_media_id, step_media_ids)
    try:
        resp = requests.post(
            f"{WP_BASE_URL}/wp-json/wp/v2/wprm_recipe",
            json=payload,
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

def _create_wp_post(
    recipe_data: dict,
    wprm_recipe_id: int,
    cover_media_id: int | None,
    step_media_results: list[dict | None] | None = None,
) -> dict | None:
    """
    Create a standard WP post that embeds the WPRM recipe via shortcode.
    Returns {wp_post_id, wp_url} or None.
    """
    shortcode = f'[wprm-recipe id="{wprm_recipe_id}"]'
    tags_str = ", ".join(recipe_data.get("tags", []))
    description = escape(str(recipe_data.get("description", "")))
    step_media_results = step_media_results or []

    content_parts = [
        f"<p>{description}</p>",
        shortcode,
        _build_nutrition_html(recipe_data),
        _build_step_instructions_html(recipe_data, step_media_results),
    ]

    if tags_str:
        content_parts.append(f"<p><em>Tags: {escape(tags_str)}</em></p>")

    post_content = "\n\n".join(part for part in content_parts if part)

    post_payload = {
        "title": recipe_data["title"],
        "content": post_content,
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
    step_media_results: list[dict | None] = []
    for step_key in ("step_image_1", "step_image_2", "step_image_3"):
        step_path = row.get(step_key)
        if step_path:
            step_result = _upload_image(step_path, f"{recipe_data['title']} – step {step_key[-1]}")
            step_media_results.append(step_result)
            step_media_ids.append(step_result["media_id"] if step_result else None)
        else:
            step_media_results.append(None)
            step_media_ids.append(None)
    logger.info(f"Step image media IDs: {step_media_ids}")

    # Create WPRM recipe (cover + step images all wired in)
    wprm_id = _create_wprm_recipe(recipe_data, cover_media_id, step_media_ids)
    if not wprm_id:
        return None

    # Create WP post
    post_result = _create_wp_post(recipe_data, wprm_id, cover_media_id, step_media_results)
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
