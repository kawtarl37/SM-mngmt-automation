from __future__ import annotations

import re
from difflib import SequenceMatcher

from execution.config import PROMPTS_DIR
from execution.db import get_connection
from execution.models import RECIPE_CATEGORIES, RecipeTitleIdeaResponse
from execution.utils.llm_client import LLMClient
from execution.utils.logger import setup_logger

logger = setup_logger("recipe_idea_service")

STRICT_DUPLICATE_THRESHOLD = 0.86
SOFT_DUPLICATE_THRESHOLD = 0.78


def ensure_recipe_idea_schema() -> None:
    """Create the recipe title idea table if the app has not been initialized yet."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS recipe_ideas (
                idea_id INTEGER PRIMARY KEY AUTOINCREMENT,
                mode TEXT NOT NULL,
                category TEXT NOT NULL,
                dish_request TEXT,
                suggested_title TEXT NOT NULL,
                rationale TEXT,
                duplicate_score REAL DEFAULT 0.0,
                duplicate_warning TEXT,
                status TEXT DEFAULT 'pending_review',
                generated_recipe_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute("PRAGMA table_info(generated_recipes)")
        recipe_columns = {row[1] for row in cursor.fetchall()}
        if "recipe_idea_id" not in recipe_columns:
            cursor.execute("ALTER TABLE generated_recipes ADD COLUMN recipe_idea_id INTEGER")
        conn.commit()


def generate_recipe_title_ideas(
    category: str | None = None,
    dish_request: str | None = None,
    limit: int = 5,
) -> dict:
    """Generate and save reviewable recipe title ideas without creating recipes/images."""
    ensure_recipe_idea_schema()
    mode = "custom_dish" if (dish_request or "").strip() else "category"
    selected_category = _validated_category(category)
    dish = (dish_request or "").strip()
    if mode == "category" and not selected_category:
        raise ValueError("Choose a recipe category or type a dish to make gluten-free.")

    existing = _existing_recipe_titles()
    existing_block = _titles_block(existing)
    prompt = _build_title_prompt(
        mode=mode,
        category=selected_category,
        dish_request=dish,
        existing_titles=existing_block,
        limit=max(1, min(int(limit or 5), 8)),
    )

    response = LLMClient().generate_structured(
        system_prompt=(PROMPTS_DIR / "brand_system_prompt.txt").read_text(encoding="utf-8"),
        user_prompt=prompt,
        response_format=RecipeTitleIdeaResponse,
        task_name="recipe_title_ideas",
    )

    saved = []
    for idea in response.ideas:
        normalized_category = _validated_category(idea.category) or selected_category or _infer_category(dish)
        title = _clean_title(idea.title)
        if not title:
            continue
        duplicate = _duplicate_assessment(title, existing)
        if duplicate["strict_block"]:
            logger.info("Skipping duplicate recipe idea '%s': %s", title, duplicate["warning"])
            continue
        saved.append(
            _save_recipe_idea(
                mode=mode,
                category=normalized_category,
                dish_request=dish,
                title=title,
                rationale=idea.rationale,
                duplicate_score=duplicate["score"],
                duplicate_warning=duplicate["warning"],
            )
        )

    return {"ideas": saved, "skipped_duplicates": max(0, len(response.ideas) - len(saved))}


def list_recipe_ideas(status: str | None = None, limit: int = 50) -> list[dict]:
    ensure_recipe_idea_schema()
    safe_limit = max(1, min(int(limit or 50), 100))
    where = ""
    params: list[object] = []
    if status:
        where = "WHERE status = ?"
        params.append(status)
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT *
            FROM recipe_ideas
            {where}
            ORDER BY created_at DESC, idea_id DESC
            LIMIT ?
            """,
            tuple(params + [safe_limit]),
        )
        return [dict(row) for row in cursor.fetchall()]


def get_recipe_idea(idea_id: int) -> dict | None:
    ensure_recipe_idea_schema()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM recipe_ideas WHERE idea_id = ?", (idea_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def reject_recipe_idea(idea_id: int) -> bool:
    ensure_recipe_idea_schema()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE recipe_ideas
            SET status = 'rejected', updated_at = CURRENT_TIMESTAMP
            WHERE idea_id = ? AND status IN ('pending_review', 'approved')
            """,
            (idea_id,),
        )
        conn.commit()
        return cursor.rowcount > 0


def mark_recipe_idea_generated(idea_id: int, recipe_id: int) -> None:
    ensure_recipe_idea_schema()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE recipe_ideas
            SET status = 'generated', generated_recipe_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE idea_id = ?
            """,
            (recipe_id, idea_id),
        )
        conn.commit()


def mark_recipe_idea_approved(idea_id: int) -> bool:
    ensure_recipe_idea_schema()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE recipe_ideas
            SET status = 'approved', updated_at = CURRENT_TIMESTAMP
            WHERE idea_id = ? AND status = 'pending_review'
            """,
            (idea_id,),
        )
        conn.commit()
        return cursor.rowcount > 0


def _save_recipe_idea(
    mode: str,
    category: str,
    dish_request: str,
    title: str,
    rationale: str,
    duplicate_score: float,
    duplicate_warning: str | None,
) -> dict:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO recipe_ideas
                (mode, category, dish_request, suggested_title, rationale,
                 duplicate_score, duplicate_warning, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending_review')
            """,
            (mode, category, dish_request or None, title, rationale, duplicate_score, duplicate_warning),
        )
        idea_id = int(cursor.lastrowid)
        conn.commit()
        cursor.execute("SELECT * FROM recipe_ideas WHERE idea_id = ?", (idea_id,))
        return dict(cursor.fetchone())


def _existing_recipe_titles() -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT title, category, status
            FROM generated_recipes
            ORDER BY created_at DESC
            """
        )
        generated = [dict(row) for row in cursor.fetchall()]
        cursor.execute(
            """
            SELECT suggested_title AS title, category, status
            FROM recipe_ideas
            WHERE status IN ('pending_review', 'approved', 'generated')
            ORDER BY created_at DESC
            """
        )
        ideas = [dict(row) for row in cursor.fetchall()]
        return generated + ideas


def _duplicate_assessment(title: str, existing: list[dict]) -> dict:
    normalized = _normalize_title(title)
    best_score = 0.0
    best_title = None
    best_status = None
    for row in existing:
        existing_title = row.get("title") or ""
        score = SequenceMatcher(None, normalized, _normalize_title(existing_title)).ratio()
        if score > best_score:
            best_score = score
            best_title = existing_title
            best_status = row.get("status")

    strict_status = best_status in {"approved", "published"}
    strict_block = strict_status and best_score >= STRICT_DUPLICATE_THRESHOLD
    warning = None
    if best_score >= SOFT_DUPLICATE_THRESHOLD and best_title:
        warning = f"Similar to existing recipe: {best_title}"
    return {"score": round(best_score, 3), "warning": warning, "strict_block": strict_block}


def _build_title_prompt(
    mode: str,
    category: str | None,
    dish_request: str,
    existing_titles: str,
    limit: int,
) -> str:
    categories = "\n".join(f"- {item}" for item in RECIPE_CATEGORIES)
    if mode == "custom_dish":
        direction = (
            f"Create gluten-free recipe title ideas for this requested dish: {dish_request}.\n"
            "Infer the closest allowed category. Keep the dish recognizable, but make it safely gluten-free."
        )
    else:
        direction = f"Create gluten-free recipe title ideas for the category: {category}."
        if category == "Bake / Make It Yourself":
            direction += (
                "\nFor this category, prioritize from-scratch gluten-free bread recipes: sandwich bread, "
                "boules, focaccia, rolls, flatbreads, baguette-style loaves, seeded loaves, and enriched breads. "
                "Avoid another generic muffin, scone, or galette unless the idea is unusually specific."
            )

    return f"""
Generate {limit} recipe title ideas only. Do not write ingredients, instructions, or image prompts yet.

Allowed categories:
{categories}

Direction:
{direction}

Already-created titles to avoid:
{existing_titles}

Rules:
1. Every title must include "Gluten-Free" or "GF".
2. Do not suggest near-duplicates of the existing titles.
3. Titles must be specific enough to approve before recipe generation.
4. Avoid generic "easy gluten-free dinner" style ideas.
5. Return only the structured RecipeTitleIdeaResponse.
""".strip()


def _titles_block(existing: list[dict]) -> str:
    if not existing:
        return "(none yet)"
    return "\n".join(f"- {row.get('title')} ({row.get('category')}; {row.get('status')})" for row in existing[:80])


def _validated_category(category: str | None) -> str | None:
    normalized = (category or "").strip()
    for item in RECIPE_CATEGORIES:
        if item.lower() == normalized.lower():
            return item
    return None


def _infer_category(dish_request: str) -> str:
    text = dish_request.lower()
    if any(token in text for token in ["bread", "roll", "baguette", "focaccia", "sourdough", "bake", "cake", "muffin"]):
        return "Bake / Make It Yourself"
    if any(token in text for token in ["breakfast", "pancake", "waffle", "egg", "oat"]):
        return "Breakfasts That Fuel Your Day"
    if any(token in text for token in ["prep", "freezer", "lunch"]):
        return "Meal Prep & Freezer-Friendly Recipes"
    if any(token in text for token in ["cookie", "brownie", "dessert", "pie", "tart"]):
        return "Desserts & Baked Treats"
    if any(token in text for token in ["quick", "skillet", "weeknight", "dinner"]):
        return "Quick & Easy Weeknight Dinners"
    return "Comfort Food Classics (Made Gluten-Free)"


def _clean_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip()).strip("\"'")


def _normalize_title(title: str) -> str:
    text = title.lower()
    text = re.sub(r"\b(gluten free|gluten-free|gf|easy|best|homemade)\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()
