"""
recipe_generator.py
───────────────────
Main orchestration script for the Generate Recipe feature.
Generates a structured GF recipe via LLM, then generates recipe images,
and saves everything to the generated_recipes DB table.

Returns a full recipe dict on success (for the async task result), or None.
"""

import json
import sqlite3
from pathlib import Path

from execution.config import PROMPTS_DIR, DB_PATH
from execution.models import RecipeGenerationResponse
from execution.utils.llm_client import LLMClient
from execution.utils.logger import setup_logger
from execution.content.recipe_image_generator import (
    generate_recipe_cover,
    generate_recipe_pinterest_pin,
    generate_recipe_step_images,
)

logger = setup_logger("recipe_generator")


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _get_existing_titles() -> list[str]:
    """Return all previously generated recipe titles for duplication prevention."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT title FROM generated_recipes ORDER BY created_at DESC")
        titles = [row["title"] for row in cursor.fetchall()]
        conn.close()
        return titles
    except Exception:
        return []


def _save_recipe(
    recipe: RecipeGenerationResponse,
    cover_image: str | None,
    pinterest_image: str | None,
    step_images: list[str | None],
) -> int:
    """Insert recipe into generated_recipes table. Returns new recipe_id."""
    payload = recipe.model_dump()
    recipe_json = json.dumps(payload)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO generated_recipes
            (title, category, recipe_json, cover_image, pinterest_image,
             step_image_1, step_image_2, step_image_3, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
        """,
        (
            recipe.title,
            recipe.category,
            recipe_json,
            cover_image,
            pinterest_image,
            step_images[0] if len(step_images) > 0 else None,
            step_images[1] if len(step_images) > 1 else None,
            step_images[2] if len(step_images) > 2 else None,
        ),
    )
    recipe_id = cursor.lastrowid
    conn.commit()
    conn.close()
    logger.info(f"Saved recipe to DB: recipe_id={recipe_id}")
    return recipe_id


def _build_result(recipe_id: int, recipe: RecipeGenerationResponse,
                  cover_image: str | None, pinterest_image: str | None,
                  step_images: list[str | None]) -> dict:
    """Build the full dict returned to the dashboard API."""
    payload = recipe.model_dump()
    payload["recipe_id"] = recipe_id
    payload["cover_image"] = cover_image
    payload["pinterest_image"] = pinterest_image
    payload["step_image_1"] = step_images[0] if len(step_images) > 0 else None
    payload["step_image_2"] = step_images[1] if len(step_images) > 1 else None
    payload["step_image_3"] = step_images[2] if len(step_images) > 2 else None
    payload["status"] = "pending"

    # Serialize nested Pydantic objects to plain dicts
    payload["ingredients"] = [ing.model_dump() for ing in recipe.ingredients]
    payload["instructions"] = [ins.model_dump() for ins in recipe.instructions]
    return payload


# ─────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────

def generate_recipe() -> dict | None:
    """
    Full pipeline:
      1. Load prompts
      2. Call LLM → RecipeGenerationResponse
      3. Generate 1 cover + 3 step images via the configured image provider
      4. Save to DB
      5. Return recipe dict

    Takes ~25-40s. Designed to run in a background thread (async from API).
    """
    logger.info("Starting recipe generation pipeline...")

    # 1. Load prompt
    try:
        prompt_template = (PROMPTS_DIR / "recipe_generation.txt").read_text(encoding="utf-8")
        brand_system = (PROMPTS_DIR / "brand_system_prompt.txt").read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to load prompt templates: {e}")
        return None

    existing_titles = _get_existing_titles()
    existing_block = "\n".join(f"- {t}" for t in existing_titles) if existing_titles else "(none yet)"
    user_prompt = prompt_template.format(existing_titles=existing_block)

    # 2. LLM call
    client = LLMClient()
    try:
        recipe: RecipeGenerationResponse = client.generate_structured(
            system_prompt=brand_system,
            user_prompt=user_prompt,
            response_format=RecipeGenerationResponse,
            task_name="recipe_generation",
        )
        logger.info(f"LLM generated recipe: '{recipe.title}' ({recipe.category})")
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return None

    # 3. Save preliminary DB record to get recipe_id (images need it for filenames)
    cover_image = None
    pinterest_image = None
    step_images = [None, None, None]
    recipe_id = _save_recipe(recipe, cover_image, pinterest_image, step_images)

    # 4. Generate cover image
    try:
        cover_image = generate_recipe_cover(recipe_id, recipe.cover_image_prompt)
        if cover_image:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("UPDATE generated_recipes SET cover_image=? WHERE recipe_id=?",
                         (cover_image, recipe_id))
            conn.commit()
            conn.close()
    except Exception as e:
        logger.warning(f"Cover image generation failed: {e}")

    # 4b. Compose Pinterest pin from the generated cover image
    try:
        pinterest_image = generate_recipe_pinterest_pin(recipe_id, cover_image, recipe.title)
        if pinterest_image:
            conn = sqlite3.connect(DB_PATH)
            conn.execute(
                "UPDATE generated_recipes SET pinterest_image=? WHERE recipe_id=?",
                (pinterest_image, recipe_id),
            )
            conn.commit()
            conn.close()
    except Exception as e:
        logger.warning(f"Pinterest pin composition failed: {e}")

    # 5. Generate step images — only use first 3 instruction steps
    step_prompts = [ins.image_prompt for ins in recipe.instructions[:3]]
    try:
        step_images = generate_recipe_step_images(recipe_id, step_prompts)
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE generated_recipes SET step_image_1=?, step_image_2=?, step_image_3=? WHERE recipe_id=?",
            (step_images[0], step_images[1], step_images[2], recipe_id),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Step image generation failed: {e}")

    logger.info(f"Recipe pipeline complete: recipe_id={recipe_id}")
    return _build_result(recipe_id, recipe, cover_image, pinterest_image, step_images)
