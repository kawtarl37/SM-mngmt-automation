import os
import sys
import html
import json
import uuid
import base64
import secrets
import sqlite3
import threading
import re
import zipfile
import requests as http_requests
from io import BytesIO
from flask import Flask, jsonify, request, send_from_directory, redirect, send_file
from flask_cors import CORS
from pathlib import Path
from dotenv import set_key

# Fix python path to allow running script directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Imports from the execution package
from execution.config import DB_PATH, TMP_PINS_DIR, SANDBOX_MODE
from execution.content.publish_scheduler import schedule_approved_pins, run_scheduled_publishes, execute_single_publish
from execution.content.generate_custom_content import generate_custom
from execution.content.recipe_generator import generate_recipe
from execution.content.recipe_wp_publisher import build_wprm_import_payload, publish_recipe_to_wp, upload_recipe_image_to_wp
from execution.content.pinterest_publisher import post_pin_to_pinterest

# ── Async recipe generation task store ──────────────────────────────────────
# task_id → {"status": "running"|"done"|"error", "result": dict|None, "error": str}
_RECIPE_TASKS: dict = {}
_RECIPE_TASKS_LOCK = threading.Lock()

# DB initialization imports
from execution.db import init_db, seed_amazon_products
from execution.content.affiliate_products import ensure_affiliate_product_schema
from execution.content.recipe_idea_service import ensure_recipe_idea_schema
from execution.database import Base, engine
from execution.knowledge.schema import ensure_knowledge_schema

app = Flask(__name__)
CORS(app)
BLOG_PREVIEW_DIR = Path(__file__).resolve().parent.parent / ".tmp" / "blog_previews"

BLOG_PREVIEW_DEFAULTS = {
    "laws_labeling": {
        "title": "What gluten-free shoppers should check on packaging before trusting the front label",
        "description": "A practical guide to gluten-free labels, certification marks, allergen statements, and recall-aware shopping.",
    },
    "product_watch": {
        "title": "The gluten-free grocery finds people actually want in their pantry this month",
        "description": "New and useful gluten-free products, snacks, meal helpers, and supermarket staples worth watching.",
    },
    "comparison": {
        "title": "Canyon Bakehouse vs Schar: which gluten-free bread survives real life better?",
        "description": "A practical bread comparison focused on texture, toastability, sandwich survival, price, and daily use.",
    },
    "restaurants_travel": {
        "title": "How to build a gluten-free road trip snack kit that does not feel depressing",
        "description": "Travel-safe gluten-free snacks, backup meals, restaurant checks, and airport survival ideas.",
    },
    "gadgets_tools": {
        "title": "The gluten-free kitchen gadgets that actually earn their cabinet space",
        "description": "Useful tools for cross-contact prevention, meal prep, baking, packed lunches, and everyday gluten-free cooking.",
    },
    "apps_digital": {
        "title": "Which gluten-free apps are actually helpful when you are staring at a label?",
        "description": "A conversational look at scanner apps, restaurant finder apps, label tools, and where human judgment still matters.",
    },
    "organization_life": {
        "title": "The shared-kitchen system that keeps gluten-free food from becoming a daily negotiation",
        "description": "Pantry zones, toaster rules, labels, freezer backups, lunch systems, and real-life household organization.",
    },
    "recipe_experiments": {
        "title": "Can a trending muffin recipe become gluten-free without turning into a doorstop?",
        "description": "A recipe experiment about flour blends, moisture, binding, texture, and adapting viral recipes safely.",
    },
    "science_health": {
        "title": "Oats, cross-contact, and why gluten-free science does not need to sound like homework",
        "description": "A human-readable explanation of gluten-free oats, cross-contact risk, studies, and practical takeaways.",
    },
    "community_questions": {
        "title": "Why does gluten-free bread cost rent money and still need emotional support?",
        "description": "A funny but useful answer to common gluten-free community frustrations about price, texture, and daily workarounds.",
    },
}


def _sample_blog_preview_content(topic_title: str, lane: str):
    """Build deterministic sample blog content for visual template testing."""
    from execution.models import BlogGenerationResponse

    lane_label = lane.replace("_", " ").title()
    return BlogGenerationResponse(
        main_title=topic_title,
        ebook_hero_title="Your 7-Day Beginner's Guide to Delicious & Stress-Free Meals",
        intro_paragraph=(
            "A practical gluten-free guide with fewer vague promises and more real-life systems."
        ),
        intro_paragraph_1=(
            f"<p>If gluten-free life had a group chat, the topic would be: {html.escape(topic_title)}. "
            "This preview shows how the finished article layout reads with the updated typography, planner CTA, "
            "product recommendation, recipe grid, and takeaways.</p>"
        ),
        intro_paragraph_2=(
            "<p>The goal is conversational and useful: the kind of article that feels like a smart friend did the "
            "homework, then spared you the beige wellness lecture.</p>"
        ),
        intro_paragraph_3=(
            f"<p>For this sample, the editorial lane is <strong>{html.escape(lane_label)}</strong>, so the article "
            "leans into the problems, checks, and everyday decisions a reader would actually care about.</p>"
        ),
        section_1_title="The Real-Life Problem",
        section_1_content=(
            "<p>Gluten-free advice gets repetitive fast when it stays at the 101 level. Readers need the specific "
            "thing: what to buy, what to check, what to avoid, and what will make Tuesday night less dramatic.</p>"
            "<ul><li>Start with the reader's actual situation.</li><li>Name the friction clearly.</li>"
            "<li>Give them a practical next move.</li></ul>"
        ),
        section_2_title="The Tool or Product That Fits This Topic",
        section_2_content=(
            "<p>This section connects the article to one relevant, affordable product from the approved Amazon "
            "catalog. It should feel like a helpful recommendation, not a random ad parachuting into the room.</p>"
        ),
        section_3_title="How to Decide What Is Worth It",
        section_3_content=(
            "<p>Good gluten-free content should help readers make decisions. Compare price, convenience, safety, "
            "repeat use, and whether the product or system solves a problem they actually have.</p>"
            "<ol><li>Check the use case.</li><li>Check the label or source.</li><li>Check whether it saves time.</li></ol>"
        ),
        section_4_title="Claire's Honest Take",
        section_4_content=(
            "<p>The tone here should be opinionated but fair. Not everything needs to be a miracle. Sometimes the "
            "win is simply fewer crumbs, fewer emergency snacks, and fewer moments of staring into the pantry like it owes you money.</p>"
        ),
        section_5_title="What to Do Next",
        section_5_content=(
            "<p>End with a clear next step: choose one system, one product, or one check to try this week. "
            "Gluten-free living gets easier when the article turns information into action.</p>"
        ),
        takeaway_1="Specific beats generic every time.",
        takeaway_2="The product recommendation should match the topic, not the rotation schedule.",
        takeaway_3="Planner CTAs work better when they show a concrete life benefit.",
        takeaway_4="Readable typography makes the whole article feel more trustworthy.",
        takeaway_5="A good gluten-free blog should help the reader decide what to do next.",
        category="Tips & Tools",
    )

# Auto-initialize all databases and tables if they don't exist
init_db()
seed_amazon_products()
ensure_affiliate_product_schema()
ensure_recipe_idea_schema()
ensure_knowledge_schema()
Base.metadata.create_all(bind=engine)

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _request_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _safe_download_name(value: str, fallback: str = "recipe") -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return name[:80] or fallback


def _get_recipe_row(recipe_id: int) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM generated_recipes WHERE recipe_id=?", (recipe_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def _image_url_from_path(path_value: str | None) -> str | None:
    if not path_value:
        return None
    return f"/images/{Path(path_value).name}"


def _blog_status_filter(status: str | None) -> tuple[str, tuple]:
    if status == "pending":
        return "WHERE b.status IN ('generated', 'pending_review')", ()
    if status == "approved":
        return "WHERE (b.status IN ('approved', 'published') OR b.wp_url IS NOT NULL)", ()
    if status in {"generated", "pending_review", "rejected", "deleted", "published"}:
        return "WHERE b.status = ?", (status,)
    return "WHERE b.status != 'deleted'", ()


def _draft_status_filter(status: str | None) -> tuple[str, tuple]:
    if status == "pending":
        return "WHERE platform = 'newsletter' AND status = 'pending_review'", ()
    if status == "approved":
        return "WHERE platform = 'newsletter' AND status = 'approved'", ()
    if status in {"pending_review", "approved", "rejected", "deleted"}:
        return "WHERE platform = 'newsletter' AND status = ?", (status,)
    return "WHERE platform = 'newsletter' AND status != 'deleted'", ()

# ──────────────────────────────────────────────
# API: Pins
# ──────────────────────────────────────────────

@app.route('/api/pins', methods=['GET'])
def get_pending_pins():
    from execution.editorial.schema import ensure_editorial_schema
    ensure_editorial_schema()
    status_filter = request.args.get("status", "pending")
    conn = get_db_connection()
    cursor = conn.cursor()
    # Left join to accommodate custom pins where idea_id = 0
    where = "WHERE p.status = ?"
    params: tuple = (status_filter,)
    if status_filter == "approved":
        where = "WHERE p.status IN ('approved', 'posted', 'published')"
        params = ()
    elif status_filter == "all":
        where = "WHERE p.status != 'deleted'"
        params = ()
    cursor.execute("""
        SELECT p.pin_id, p.title, p.description, p.image_path, p.destination_url,
               p.status, p.seo_keywords, p.created_at,
               c.content_type, c.content_lane, c.angle_type, c.freshness_hook, c.source_hint,
               b.blog_id, b.title AS blog_title, b.wp_url,
               pp.pinterest_id, pp.posted_at
        FROM generated_pins p
        LEFT JOIN content_ideas c ON p.idea_id = c.idea_id
        LEFT JOIN blogs b ON b.pin_id = p.pin_id AND b.status != 'deleted'
        LEFT JOIN posted_pins pp ON pp.pin_id = p.pin_id
        """ + where + """
        GROUP BY p.pin_id
        ORDER BY p.created_at DESC, p.pin_id DESC
        LIMIT 100
    """, params)
    pins = [dict(row) for row in cursor.fetchall()]
    for pin in pins:
        pin["image_url"] = _image_url_from_path(pin.get("image_path"))
    conn.close()
    return jsonify(pins)


@app.route('/api/pins/<int:pin_id>', methods=['GET'])
def api_pin_detail(pin_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.*,
               c.content_type, c.content_lane, c.angle_type, c.freshness_hook, c.source_hint,
               b.blog_id, b.title AS blog_title, b.wp_url,
               pp.pinterest_id, pp.posted_at
        FROM generated_pins p
        LEFT JOIN content_ideas c ON p.idea_id = c.idea_id
        LEFT JOIN blogs b ON b.pin_id = p.pin_id AND b.status != 'deleted'
        LEFT JOIN posted_pins pp ON pp.pin_id = p.pin_id
        WHERE p.pin_id = ?
        ORDER BY b.blog_id DESC
        LIMIT 1
    """, (pin_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return jsonify({"success": False, "error": "Pin not found."}), 404
    pin = dict(row)
    pin["image_url"] = _image_url_from_path(pin.get("image_path"))
    return jsonify({"success": True, "pin": pin})

@app.route('/api/pins/<int:pin_id>/approve', methods=['POST'])
def approve_pin(pin_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE generated_pins SET status = 'approved' WHERE pin_id = ?", (pin_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Pin approved."})

@app.route('/api/pins/<int:pin_id>/reject', methods=['POST'])
def reject_pin(pin_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    data = request.get_json() or {}
    reason = data.get("reason", "")
    cursor.execute(
        "UPDATE generated_pins SET status = 'rejected', rejection_reason = ? WHERE pin_id = ?",
        (reason, pin_id)
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True})


# API: Blogs
@app.route('/api/blogs', methods=['GET'])
def api_blogs():
    status_filter = request.args.get("status")
    where_sql, params = _blog_status_filter(status_filter)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT b.blog_id, b.pin_id, b.title, b.category, b.product_id, b.wp_post_id,
               b.wp_url, b.wp_featured_image_id, b.status, b.created_at, b.published_at,
               p.image_path, p.title AS pin_title, p.description AS pin_description,
               p.status AS pin_status, p.destination_url,
               a.title AS product_title
        FROM blogs b
        LEFT JOIN generated_pins p ON b.pin_id = p.pin_id
        LEFT JOIN amazon_products a ON b.product_id = a.product_id
        """ + where_sql + """
        ORDER BY b.created_at DESC, b.blog_id DESC
        LIMIT 100
    """, params)
    blogs = [dict(row) for row in cursor.fetchall()]
    conn.close()
    for blog in blogs:
        blog["image_url"] = _image_url_from_path(blog.get("image_path"))
    return jsonify(blogs)


@app.route('/api/blogs/<int:blog_id>', methods=['GET'])
def api_blog_detail(blog_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT b.*, p.image_path, p.title AS pin_title, p.description AS pin_description,
               p.seo_keywords, p.destination_url, p.status AS pin_status,
               a.title AS product_title, a.url AS product_url, a.image_url AS product_image_url
        FROM blogs b
        LEFT JOIN generated_pins p ON b.pin_id = p.pin_id
        LEFT JOIN amazon_products a ON b.product_id = a.product_id
        WHERE b.blog_id = ?
        LIMIT 1
    """, (blog_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return jsonify({"success": False, "error": "Blog not found."}), 404
    blog = dict(row)
    blog["image_url"] = _image_url_from_path(blog.get("image_path"))
    return jsonify({"success": True, "blog": blog})


@app.route('/api/blogs/<int:blog_id>/approve', methods=['POST'])
def api_blog_approve(blog_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE blogs SET status = 'approved' WHERE blog_id = ? AND status != 'deleted'", (blog_id,))
    conn.commit()
    updated = cursor.rowcount
    conn.close()
    if not updated:
        return jsonify({"success": False, "error": "Blog not found."}), 404
    return jsonify({"success": True, "message": "Blog approved."})


@app.route('/api/blogs/<int:blog_id>/reject', methods=['POST'])
def api_blog_reject(blog_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE blogs SET status = 'rejected' WHERE blog_id = ? AND status != 'deleted'", (blog_id,))
    conn.commit()
    updated = cursor.rowcount
    conn.close()
    if not updated:
        return jsonify({"success": False, "error": "Blog not found."}), 404
    return jsonify({"success": True})


@app.route('/api/blogs/<int:blog_id>', methods=['DELETE'])
def api_blog_delete(blog_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE blogs SET status = 'deleted' WHERE blog_id = ?", (blog_id,))
    blog_updated = cursor.rowcount
    cursor.execute("UPDATE publish_schedule SET status = 'cancelled' WHERE blog_id = ? AND status IN ('pending', 'failed')", (blog_id,))
    cancelled = cursor.rowcount
    conn.commit()
    conn.close()
    if not blog_updated:
        return jsonify({"success": False, "error": "Blog not found."}), 404
    return jsonify({"success": True, "cancelled_schedules": cancelled})

# ──────────────────────────────────────────────
# API: Publish Schedule Queue
# ──────────────────────────────────────────────

@app.route('/api/schedule', methods=['GET'])
def get_schedule():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.schedule_id, s.pin_id, s.blog_id, s.scheduled_time, s.status,
               s.error_message, s.completed_at,
               p.title as pin_title,
               b.title AS blog_title, b.wp_url
        FROM publish_schedule s
        JOIN generated_pins p ON s.pin_id = p.pin_id
        LEFT JOIN blogs b ON s.blog_id = b.blog_id
        WHERE s.status != 'cancelled'
        ORDER BY s.scheduled_time ASC
        LIMIT 30
    """)
    schedule = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(schedule)

@app.route('/api/schedule/<int:schedule_id>', methods=['DELETE'])
def api_schedule_cancel(schedule_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE publish_schedule SET status = 'cancelled' WHERE schedule_id = ? AND status IN ('pending', 'failed')",
        (schedule_id,),
    )
    conn.commit()
    updated = cursor.rowcount
    conn.close()
    if not updated:
        return jsonify({"success": False, "error": "Queue item not found or cannot be cancelled."}), 404
    return jsonify({"success": True, "message": "Queue item cancelled."})

@app.route('/api/publish/run', methods=['POST'])
def run_publish():
    """Manually trigger the scheduled publishes check."""
    try:
        run_scheduled_publishes()
        return jsonify({"success": True, "message": "Publish runner executed successfully."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/publish/now/<int:pin_id>', methods=['POST'])
def publish_now(pin_id):
    """Publish a pin immediately, out of schedule."""
    try:
        success = execute_single_publish(pin_id)
        if success:
            return jsonify({"success": True, "message": "Pin published immediately."})
        else:
            return jsonify({"success": False, "error": "Internal publishing error."}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/generate_custom', methods=['POST'])
def generate_custom_api():
    """Generate on-demand custom content."""
    data = request.get_json() or {}
    topic_type = data.get("topic_type", "Educational")
    try:
        result = generate_custom(topic_type)
        if result:
            return jsonify({"success": True, "pin": result})
        return jsonify({"success": False, "error": "Failed to generate (returned None)."}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ──────────────────────────────────────────────
# API: Recipe Generation (Async)
# ──────────────────────────────────────────────

def _run_recipe_task(task_id: str, recipe_idea_id: int | None = None):
    """Background worker: generate recipe and store result in _RECIPE_TASKS."""
    try:
        result = generate_recipe(recipe_idea_id=recipe_idea_id)
        with _RECIPE_TASKS_LOCK:
            if result:
                _RECIPE_TASKS[task_id] = {"status": "done", "result": result, "error": None}
            else:
                _RECIPE_TASKS[task_id] = {"status": "error", "result": None,
                                          "error": "Generation returned None — check server logs."}
    except Exception as e:
        with _RECIPE_TASKS_LOCK:
            _RECIPE_TASKS[task_id] = {"status": "error", "result": None, "error": str(e)}


@app.route('/api/recipe/generate', methods=['POST'])
def api_recipe_generate():
    """Start async recipe generation. Returns {task_id} immediately."""
    data = request.get_json(silent=True) or {}
    recipe_idea_id = data.get("recipe_idea_id")
    task_id = str(uuid.uuid4())
    with _RECIPE_TASKS_LOCK:
        _RECIPE_TASKS[task_id] = {"status": "running", "result": None, "error": None}
    t = threading.Thread(target=_run_recipe_task, args=(task_id, recipe_idea_id), daemon=True)
    t.start()
    return jsonify({"task_id": task_id})


@app.route('/api/recipe-ideas/generate', methods=['POST'])
def api_recipe_ideas_generate():
    """Generate recipe title ideas only; no full recipe/images yet."""
    from execution.content.recipe_idea_service import generate_recipe_title_ideas

    data = request.get_json() or {}
    try:
        result = generate_recipe_title_ideas(
            category=data.get("category"),
            dish_request=data.get("dish_request"),
            limit=int(data.get("limit", 5)),
        )
        return jsonify({"success": True, **result})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/recipe-ideas', methods=['GET'])
def api_recipe_ideas_list():
    """List generated recipe title ideas for dashboard review."""
    from execution.content.recipe_idea_service import list_recipe_ideas

    try:
        return jsonify(list_recipe_ideas(
            status=request.args.get("status"),
            limit=int(request.args.get("limit", 50)),
        ))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/recipe-ideas/<int:idea_id>/approve-generate', methods=['POST'])
def api_recipe_idea_approve_generate(idea_id):
    """Approve one recipe title idea and start full recipe/image generation."""
    from execution.content.recipe_idea_service import get_recipe_idea, mark_recipe_idea_approved

    idea = get_recipe_idea(idea_id)
    if not idea:
        return jsonify({"success": False, "error": "Recipe idea not found."}), 404
    if idea["status"] not in {"pending_review", "approved"}:
        return jsonify({"success": False, "error": f"Recipe idea is already {idea['status']}."}), 400
    if idea["status"] == "pending_review" and not mark_recipe_idea_approved(idea_id):
        return jsonify({"success": False, "error": "Could not approve recipe idea."}), 400

    task_id = str(uuid.uuid4())
    with _RECIPE_TASKS_LOCK:
        _RECIPE_TASKS[task_id] = {"status": "running", "result": None, "error": None}
    t = threading.Thread(target=_run_recipe_task, args=(task_id, idea_id), daemon=True)
    t.start()
    return jsonify({"success": True, "task_id": task_id})


@app.route('/api/recipe-ideas/<int:idea_id>/reject', methods=['POST'])
def api_recipe_idea_reject(idea_id):
    """Reject a recipe title idea before it becomes a full recipe."""
    from execution.content.recipe_idea_service import reject_recipe_idea

    if reject_recipe_idea(idea_id):
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Recipe idea not found or cannot be rejected."}), 404


@app.route('/api/recipe/generate/status/<task_id>', methods=['GET'])
def api_recipe_generate_status(task_id):
    """Poll endpoint for async recipe generation."""
    with _RECIPE_TASKS_LOCK:
        task = _RECIPE_TASKS.get(task_id)
    if not task:
        return jsonify({"error": "Unknown task_id"}), 404
    return jsonify(task)


@app.route('/api/recipes', methods=['GET'])
def api_list_recipes():
    """List recipes. Optional ?status=pending|approved|published|rejected."""
    status_filter = request.args.get("status")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    if status_filter:
        cursor.execute(
            "SELECT * FROM generated_recipes WHERE status=? ORDER BY created_at DESC",
            (status_filter,)
        )
    else:
        cursor.execute("SELECT * FROM generated_recipes ORDER BY created_at DESC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    # Parse recipe_json for each row
    for row in rows:
        try:
            row["recipe_data"] = json.loads(row["recipe_json"])
        except Exception:
            row["recipe_data"] = {}
    return jsonify(rows)


@app.route('/api/recipe/<int:recipe_id>/approve', methods=['POST'])
def api_recipe_approve(recipe_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE generated_recipes SET status='approved' WHERE recipe_id=?", (recipe_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Recipe approved."})


@app.route('/api/recipe/<int:recipe_id>/reject', methods=['POST'])
def api_recipe_reject(recipe_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE generated_recipes SET status='rejected' WHERE recipe_id=?", (recipe_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route('/api/recipe/<int:recipe_id>/download/images', methods=['GET'])
def api_recipe_download_images(recipe_id):
    """Download the generated cover, Pinterest pin, and step images for a recipe as a zip file."""
    row = _get_recipe_row(recipe_id)
    if not row:
        return jsonify({"success": False, "error": "Recipe not found"}), 404

    try:
        recipe_data = json.loads(row["recipe_json"])
    except Exception:
        recipe_data = {"title": row.get("title") or f"recipe-{recipe_id}"}

    image_fields = [
        ("cover", row.get("cover_image")),
        ("pinterest-pin", row.get("pinterest_image")),
        ("step-1", row.get("step_image_1")),
        ("step-2", row.get("step_image_2")),
        ("step-3", row.get("step_image_3")),
    ]

    buffer = BytesIO()
    added = 0
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for label, image_path in image_fields:
            if not image_path:
                continue
            path = Path(image_path)
            if not path.exists() or not path.is_file():
                continue
            zf.write(path, arcname=f"{label}{path.suffix.lower() or '.jpg'}")
            added += 1

    if added == 0:
        return jsonify({"success": False, "error": "No generated image files found for this recipe."}), 404

    buffer.seek(0)
    filename = f"recipe-{recipe_id}-{_safe_download_name(recipe_data.get('title', row.get('title', 'recipe')))}-images.zip"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/zip")


@app.route('/api/recipe/<int:recipe_id>/download/wprm-json', methods=['GET'])
def api_recipe_download_wprm_json(recipe_id):
    """Download a WP Recipe Maker REST JSON payload for a generated recipe."""
    row = _get_recipe_row(recipe_id)
    if not row:
        return jsonify({"success": False, "error": "Recipe not found"}), 404

    try:
        recipe_data = json.loads(row["recipe_json"])
    except Exception as e:
        return jsonify({"success": False, "error": f"Recipe JSON is invalid: {e}"}), 500

    payload = build_wprm_import_payload(recipe_data)
    buffer = BytesIO(json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"))
    filename = f"recipe-{recipe_id}-{_safe_download_name(recipe_data.get('title', row.get('title', 'recipe')))}-wprm.json"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/json")


@app.route('/api/recipe/<int:recipe_id>/publish/wp', methods=['POST'])
def api_recipe_publish_wp(recipe_id):
    """Publish recipe to WordPress via WPRM REST API."""
    try:
        result = publish_recipe_to_wp(recipe_id)
        if result:
            return jsonify({"success": True, "wp_url": result["wp_url"],
                            "wp_post_id": result["wp_post_id"],
                            "media_url": result.get("media_url")})
        return jsonify({"success": False, "error": "Publishing returned None. Check server logs."}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/recipe/<int:recipe_id>/publish/pinterest', methods=['POST'])
def api_recipe_publish_pinterest(recipe_id):
    """Post recipe pin to Pinterest using cover image + WP URL."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM generated_recipes WHERE recipe_id=?", (recipe_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({"success": False, "error": "Recipe not found"}), 404
    row = dict(row)
    if not row.get("wp_url"):
        return jsonify({"success": False, "error": "Recipe must be published to WordPress first."}), 400

    recipe_data = json.loads(row["recipe_json"])
    pin_image_path = row.get("pinterest_image") or row.get("cover_image", "")

    # Temporarily insert into generated_pins table so the existing publisher can use it
    pin_conn = sqlite3.connect(DB_PATH)
    pin_conn.row_factory = sqlite3.Row
    pin_cur = pin_conn.cursor()
    pin_cur.execute("""
        INSERT INTO generated_pins (idea_id, title, description, seo_keywords,
                                    image_path, destination_url, status, batch_date)
        VALUES (0, ?, ?, ?, ?, ?, 'approved', date('now'))
    """, (
        recipe_data["title"],
        recipe_data.get("pinterest_description", recipe_data.get("description", "")),
        ", ".join(recipe_data.get("tags", [])),
        pin_image_path,
        row["wp_url"],
    ))
    temp_pin_id = pin_cur.lastrowid
    pin_conn.commit()
    pin_conn.close()

    try:
        media_result = upload_recipe_image_to_wp(
            pin_image_path,
            f"{recipe_data['title']} Pinterest pin",
        ) if pin_image_path else None
        media_url = media_result.get("media_url") if media_result else None
        if not media_url:
            return jsonify({"success": False, "error": "Could not upload the Pinterest pin image to WordPress media."}), 500

        result = post_pin_to_pinterest(
            pin_id=temp_pin_id,
            wp_url=row["wp_url"],
            media_url=media_url
        )
        if result:
            # Update recipe with pinterest_id
            pconn = sqlite3.connect(DB_PATH)
            pconn.execute(
                "UPDATE generated_recipes SET pinterest_id=? WHERE recipe_id=?",
                (result["pinterest_id"], recipe_id)
            )
            pconn.commit()
            pconn.close()
            return jsonify({"success": True, "pinterest_id": result["pinterest_id"]})
        return jsonify({"success": False, "error": "Pinterest posting returned None."}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        # Cleanup temp pin
        try:
            cconn = sqlite3.connect(DB_PATH)
            cconn.execute("DELETE FROM generated_pins WHERE pin_id=? AND idea_id=0", (temp_pin_id,))
            cconn.commit()
            cconn.close()
        except Exception:
            pass


# ──────────────────────────────────────────────
# API: Pinterest OAuth 2.0
# Uses port 8888 callback — already registered in Pinterest app
# ──────────────────────────────────────────────

from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

_PINTEREST_OAUTH_STATE  = None
_OAUTH_RESULT           = {}    # shared dict: {"success": bool, "error": str}
_OAUTH_DONE             = threading.Event()

REDIRECT_URI = "http://localhost:8888/callback"


class _PinterestCallbackHandler(BaseHTTPRequestHandler):
    """Tiny one-shot HTTP handler that catches the Pinterest redirect on port 8888."""

    def do_GET(self):
        global _PINTEREST_OAUTH_STATE
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        error = params.get("error", [None])[0]
        code  = params.get("code",  [None])[0]
        state = params.get("state", [None])[0]

        BASE_DIR = Path(__file__).resolve().parent.parent
        ENV_PATH = BASE_DIR / ".env"

        if error:
            _OAUTH_RESULT["success"] = False
            _OAUTH_RESULT["error"]   = f"Pinterest denied access: {error}"
            self._html(400, f"<h2>❌ Pinterest denied: {error}</h2><p>You can close this tab.</p>")

        elif state != _PINTEREST_OAUTH_STATE:
            _OAUTH_RESULT["success"] = False
            _OAUTH_RESULT["error"]   = "CSRF state mismatch"
            self._html(400, "<h2>❌ Security error: state mismatch.</h2><p>You can close this tab.</p>")

        elif not code:
            _OAUTH_RESULT["success"] = False
            _OAUTH_RESULT["error"]   = "No authorization code received"
            self._html(400, "<h2>❌ No code in callback.</h2><p>You can close this tab.</p>")

        else:
            # Exchange code for tokens
            app_id     = os.getenv("PINTEREST_APP_ID")
            app_secret = os.getenv("PINTEREST_APP_SECRET")
            auth_str   = base64.b64encode(f"{app_id}:{app_secret}".encode()).decode()

            try:
                resp = http_requests.post(
                    "https://api.pinterest.com/v5/oauth/token",
                    headers={
                        "Authorization": f"Basic {auth_str}",
                        "Content-Type":  "application/x-www-form-urlencoded",
                    },
                    data={
                        "grant_type":         "authorization_code",
                        "code":               code,
                        "redirect_uri":       REDIRECT_URI,
                        "continuous_refresh": "true",
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                token_data = resp.json()

                access_token  = token_data.get("access_token")
                refresh_token = token_data.get("refresh_token", "")
                expires_in    = token_data.get("expires_in", "unknown")

                if not access_token:
                    raise ValueError(f"No access_token in response: {token_data}")

                set_key(str(ENV_PATH), "PINTEREST_ACCESS_TOKEN",  access_token)
                set_key(str(ENV_PATH), "PINTEREST_REFRESH_TOKEN", refresh_token)
                _PINTEREST_OAUTH_STATE = None

                _OAUTH_RESULT["success"]    = True
                _OAUTH_RESULT["expires_in"] = expires_in
                self._html(200, f"""
                    <h2 style='color:#27ae60'>✅ Pinterest OAuth Complete!</h2>
                    <p>Tokens saved to <code>.env</code></p>
                    <ul>
                        <li>Access token expires in: <strong>{expires_in}s</strong></li>
                        <li>Continuous refresh: <strong>enabled</strong></li>
                    </ul>
                    <p style='margin-top:16px;color:#666'>You can close this tab — your pin will now be published.</p>
                    <script>setTimeout(()=>window.close(),2000);</script>
                """)

            except Exception as exc:
                _OAUTH_RESULT["success"] = False
                _OAUTH_RESULT["error"]   = str(exc)
                self._html(500, f"<h2>❌ Token exchange failed</h2><pre>{exc}</pre>")

        _OAUTH_DONE.set()

    def _html(self, status, body):
        page = (
            f"<html><body style='font-family:sans-serif;padding:40px;background:#f0f4f3'>"
            f"<div style='background:white;max-width:500px;margin:auto;padding:40px;"
            f"border-radius:14px;box-shadow:0 2px 20px rgba(0,0,0,0.08)'>{body}</div>"
            f"</body></html>"
        ).encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", len(page))
        self.end_headers()
        self.wfile.write(page)

    def log_message(self, *args):
        pass  # suppress access logs


def _run_callback_server():
    """Start a one-shot HTTP server on port 8888, handle one request, then stop."""
    try:
        server = HTTPServer(("localhost", 8888), _PinterestCallbackHandler)
        server.handle_request()  # blocks until Pinterest redirects here
        server.server_close()
    except Exception as e:
        _OAUTH_RESULT["success"] = False
        _OAUTH_RESULT["error"]   = f"Callback server error: {e}"
        _OAUTH_DONE.set()


@app.route('/api/oauth/start')
def oauth_start():
    """Generate Pinterest auth URL, start callback server on port 8888, return URL."""
    global _PINTEREST_OAUTH_STATE, _OAUTH_RESULT, _OAUTH_DONE

    app_id = os.getenv("PINTEREST_APP_ID")
    if not app_id:
        return jsonify({"error": "PINTEREST_APP_ID not set in .env"}), 500

    # Reset shared state
    _OAUTH_RESULT = {}
    _OAUTH_DONE   = threading.Event()
    _PINTEREST_OAUTH_STATE = secrets.token_urlsafe(16)

    # Start background callback server (daemon so it dies if Flask dies)
    t = threading.Thread(target=_run_callback_server, daemon=True)
    t.start()

    from urllib.parse import urlencode
    params = urlencode({
        "client_id":     app_id,
        "redirect_uri":  REDIRECT_URI,
        "response_type": "code",
        "scope":         "boards:read,pins:read,pins:write",
        "state":         _PINTEREST_OAUTH_STATE,
    })
    url = f"https://www.pinterest.com/oauth/?{params}"
    return jsonify({"auth_url": url})


@app.route('/api/oauth/status')
def oauth_status():
    """Poll endpoint — frontend calls this to know when OAuth is done."""
    if _OAUTH_DONE.is_set():
        return jsonify({"done": True,  **_OAUTH_RESULT})
    return jsonify({"done": False})


# ──────────────────────────────────────────────
# API: Trend Analysis & Blog Gen
# ──────────────────────────────────────────────

_TRENDS_SCRAPE_STATUS = {"status": "idle", "error": None}
_TRENDS_LOCK = threading.Lock()

def _run_trends_scrape_task():
    global _TRENDS_SCRAPE_STATUS
    try:
        from execution.scrapers.reddit_scraper import run_scraper as run_reddit
        run_reddit()
        
        from execution.scrapers.medical_articles_scraper import run_scraper as run_pubmed
        run_pubmed()
        
        from execution.intelligence.trend_analyzer import rank_trends
        rank_trends()
        
        from execution.intelligence.trend_synthesizer import synthesize_trends
        synthesize_trends()
        
        with _TRENDS_LOCK:
            _TRENDS_SCRAPE_STATUS = {"status": "done", "error": None}
    except Exception as e:
        import logging
        logging.getLogger("dashboard").error(f"Background trends scrape failed: {e}", exc_info=True)
        with _TRENDS_LOCK:
            _TRENDS_SCRAPE_STATUS = {"status": "error", "error": str(e)}

@app.route('/api/trends', methods=['GET'])
def get_trends():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trendy_topics ORDER BY relevance_score DESC, created_at DESC")
    trends = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(trends)

@app.route('/api/trends/scrape', methods=['POST'])
def api_trends_scrape():
    global _TRENDS_SCRAPE_STATUS
    with _TRENDS_LOCK:
        if _TRENDS_SCRAPE_STATUS["status"] == "running":
            return jsonify({"status": "running", "message": "Scrape already in progress."})
        _TRENDS_SCRAPE_STATUS = {"status": "running", "error": None}
    t = threading.Thread(target=_run_trends_scrape_task, daemon=True)
    t.start()
    return jsonify({"status": "started"})

@app.route('/api/trends/scrape/status', methods=['GET'])
def api_trends_scrape_status():
    with _TRENDS_LOCK:
        return jsonify(_TRENDS_SCRAPE_STATUS)

@app.route('/api/trends/<int:topic_id>/approve', methods=['POST'])
def api_trend_approve(topic_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE trendy_topics SET status='approved' WHERE topic_id=?", (topic_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/api/trends/<int:topic_id>/reject', methods=['POST'])
def api_trend_reject(topic_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE trendy_topics SET status='rejected' WHERE topic_id=?", (topic_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/api/trends/<int:topic_id>/suggest_title', methods=['POST'])
def api_trend_suggest_title(topic_id):
    """Suggest and apply one alternate title for a trendy topic."""
    from execution.config import PROMPTS_DIR
    from execution.models import BlogTitleSuggestionResponse
    from execution.utils.llm_client import LLMClient

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trendy_topics WHERE topic_id=?", (topic_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return jsonify({"success": False, "error": "Topic not found"}), 404
    topic = dict(row)
    conn.close()

    try:
        system_prompt = (PROMPTS_DIR / "brand_system_prompt.txt").read_text(encoding="utf-8")
        user_prompt = f"""
Suggest ONE alternate blog title for this approved Easy Gluten Free trend.

Current title: {topic['title']}
Details: {topic['details']}
Source: {topic['source']}

Rules:
- Return one title only in the structured schema.
- Keep it factual and aligned with the topic details.
- Keep it SEO-friendly and natural for gluten-free readers.
- Do not use generic phrases like "ultimate guide" or "game changer".
- Do not use emojis.
"""
        response: BlogTitleSuggestionResponse = LLMClient().generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format=BlogTitleSuggestionResponse,
            task_name="trend_title_suggestion",
        )
        new_title = response.title.strip()
        if not new_title:
            return jsonify({"success": False, "error": "Title suggestion was empty."}), 500
    except Exception as e:
        return jsonify({"success": False, "error": f"Failed to suggest title: {e}"}), 500

    conn = get_db_connection()
    conn.execute("UPDATE trendy_topics SET title=? WHERE topic_id=?", (new_title, topic_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "title": new_title})

@app.route('/api/trends/<int:topic_id>/generate_blog', methods=['POST'])
def api_trend_generate_blog(topic_id):
    import datetime
    from execution.config import PROMPTS_DIR
    from execution.utils.llm_client import LLMClient
    from execution.content.image_generator import generate_pin_image
    from execution.content.blog_generator import generate_blog
    
    # 1. Fetch topic
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trendy_topics WHERE topic_id=?", (topic_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return jsonify({"success": False, "error": "Topic not found"}), 404
    topic = dict(row)
    conn.close()

    # 2. Call LLM for caption
    client = LLMClient()
    system_prompt = (PROMPTS_DIR / "brand_system_prompt.txt").read_text(encoding="utf-8")
    user_prompt = f"""
Create a new Pinterest pin idea and caption for this trendy topic:
Title: {topic['title']}
Details: {topic['details']}
Source: {topic['source']}
Editorial lane: {topic.get('content_lane') or 'unspecified'}
Angle type: {topic.get('angle_type') or 'unspecified'}
Freshness hook: {topic.get('freshness_hook') or 'Make the topic feel current and useful.'}

Provide:
1. A catchy, Pinterest-optimized Pin Title (incorporating GF keywords, max 70 chars).
2. A descriptive Pin Caption / Description (max 160 chars, in Claire's voice, witty and relatable).
3. A list of 3-5 relevant hashtags.
4. An alt text description for the image.

Output should match the CaptionGenerationResponse schema.
"""
    try:
        from execution.models import CaptionGenerationResponse
        caption_resp: CaptionGenerationResponse = client.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format=CaptionGenerationResponse,
            task_name="custom_caption"
        )
    except Exception as e:
        return jsonify({"success": False, "error": f"Failed to generate caption: {e}"}), 500

    # 3. Insert Pin as approved
    try:
        from execution.database import get_db, GeneratedPin
        db_generator = get_db()
        db = next(db_generator)
        new_pin = GeneratedPin(
            idea_id=0,
            title=topic["title"],
            description=caption_resp.pin_description,
            seo_keywords=", ".join(caption_resp.hashtags),
            status="approved",
            batch_date=datetime.date.today(),
            created_at=datetime.datetime.utcnow()
        )
        db.add(new_pin)
        db.commit()
        db.refresh(new_pin)
        pin_id = new_pin.pin_id
        next(db_generator, None)
    except Exception as e:
        return jsonify({"success": False, "error": f"Failed to save pin: {e}"}), 500

    # 4. Generate Pin image
    try:
        subtitle = "Tips & Tricks" if "Reddit" in topic['source'] else "Know Your Ingredients"
        image_path = generate_pin_image(topic["title"], pin_id, subtitle=subtitle)
        if image_path:
            conn = get_db_connection()
            conn.execute("UPDATE generated_pins SET image_path=? WHERE pin_id=?", (image_path, pin_id))
            conn.commit()
            conn.close()
    except Exception:
        pass

    # 5. Generate Blog
    try:
        blog_data = generate_blog(pin_id, forced_title=topic["title"])
        if not blog_data:
            return jsonify({"success": False, "error": "Blog generation failed."}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    # 6. Update trend status; publish/post actions stay manual from approved pages.
    conn = get_db_connection()
    conn.execute("UPDATE trendy_topics SET status='generated' WHERE topic_id=?", (topic_id,))
    conn.commit()
    conn.close()

    return jsonify({"success": True, "pin_id": pin_id, "blog_title": blog_data["title"]})


@app.route('/api/config')
def api_config():
    """Return runtime configuration flags to the frontend."""
    from execution.config import SANDBOX_MODE as _SM
    return jsonify({
        "sandbox_mode": _SM,
        "api_base": "https://api-sandbox.pinterest.com/v5" if _SM else "https://api.pinterest.com/v5",
    })


@app.route('/api/editorial/lanes', methods=['GET'])
def api_editorial_lanes():
    from execution.editorial.lane_content_service import list_lane_specs
    from execution.editorial.platforms import PLATFORMS

    return jsonify({
        "lanes": list_lane_specs(),
        "platforms": [
            {
                "key": platform.key,
                "label": platform.label,
                "purpose": platform.purpose,
                "required_sections": list(platform.required_sections),
                "style_notes": list(platform.style_notes),
            }
            for platform in PLATFORMS
        ],
    })


@app.route('/api/editorial/lanes/<lane>/ideas', methods=['GET'])
def api_editorial_lane_ideas(lane):
    from execution.editorial.lane_content_service import list_lane_ideas

    try:
        limit = int(request.args.get("limit", 20))
        return jsonify(list_lane_ideas(lane, limit=limit))
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/editorial/lanes/<lane>/ideas', methods=['POST'])
def api_editorial_lane_ideas_generate(lane):
    from execution.editorial.lane_content_service import create_lane_ideas

    data = request.get_json() or {}
    try:
        result = create_lane_ideas(
            lane_key=lane,
            idea_count=int(data.get("idea_count", 3)),
            topic_hint=data.get("topic_hint"),
            sample=_request_bool(data.get("sample"), False),
            persist=_request_bool(data.get("persist"), True),
        )
        return jsonify({"success": True, **result})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/editorial/lanes/<lane>/content', methods=['POST'])
def api_editorial_lane_content_generate(lane):
    from execution.editorial.lane_content_service import create_lane_content

    data = request.get_json() or {}
    try:
        result = create_lane_content(
            lane_key=lane,
            topic_title=data.get("topic_title"),
            platform=data.get("platform", "newsletter"),
            angle_type=data.get("angle_type"),
            topic_hint=data.get("topic_hint"),
            limit_per_task=int(data.get("limit_per_task", 3)),
            sample=_request_bool(data.get("sample"), False),
            persist=_request_bool(data.get("persist"), True),
        )
        return jsonify({"success": True, **result})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/editorial/ideas/<int:idea_id>/assets', methods=['POST'])
def api_editorial_idea_assets_generate(idea_id):
    from execution.editorial.content_asset_service import create_assets_from_idea

    data = request.get_json() or {}
    try:
        result = create_assets_from_idea(
            idea_id=idea_id,
            assets=data.get("assets"),
            sample=_request_bool(data.get("sample"), False),
            persist=_request_bool(data.get("persist"), True),
        )
        return jsonify({"success": True, **result})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/editorial/assets', methods=['GET'])
def api_editorial_assets():
    from execution.editorial.content_asset_service import list_content_assets

    try:
        limit = int(request.args.get("limit", 30))
        return jsonify(list_content_assets(limit=limit))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/blogs/<int:blog_id>/publish/wp', methods=['POST'])
def api_blog_publish_wp(blog_id):
    from execution.editorial.content_asset_service import publish_blog_asset

    try:
        return jsonify({"success": True, **publish_blog_asset(blog_id)})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/pins/<int:pin_id>/post/pinterest', methods=['POST'])
def api_pin_post_pinterest(pin_id):
    from execution.editorial.content_asset_service import post_pin_asset

    try:
        return jsonify({"success": True, **post_pin_asset(pin_id)})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/pins/<int:pin_id>/copy', methods=['GET'])
def api_pin_copy(pin_id):
    from execution.editorial.content_asset_service import pin_copy_payload

    try:
        return jsonify({"success": True, **pin_copy_payload(pin_id)})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/newsletters/<int:draft_id>/copy', methods=['GET'])
def api_newsletter_copy(draft_id):
    from execution.editorial.content_asset_service import newsletter_copy_payload

    try:
        return jsonify({"success": True, **newsletter_copy_payload(draft_id)})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/newsletters', methods=['GET'])
def api_newsletters():
    status_filter = request.args.get("status")
    where_sql, params = _draft_status_filter(status_filter)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT *
        FROM content_drafts
        """ + where_sql + """
        ORDER BY created_at DESC, draft_id DESC
        LIMIT 100
    """, params)
    drafts = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(drafts)


@app.route('/api/newsletters/<int:draft_id>', methods=['GET'])
def api_newsletter_detail(draft_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM content_drafts WHERE draft_id = ? AND platform = 'newsletter'", (draft_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return jsonify({"success": False, "error": "Newsletter draft not found."}), 404
    return jsonify({"success": True, "newsletter": dict(row)})


@app.route('/api/newsletters/<int:draft_id>/approve', methods=['POST'])
def api_newsletter_approve(draft_id):
    from execution.research.draft_generator import approve_content_draft

    ok = approve_content_draft(draft_id)
    if not ok:
        return jsonify({"success": False, "error": "Newsletter draft not found."}), 404
    return jsonify({"success": True, "message": "Newsletter approved."})


@app.route('/api/newsletters/<int:draft_id>/reject', methods=['POST'])
def api_newsletter_reject(draft_id):
    from execution.research.draft_generator import reject_content_draft

    data = request.get_json() or {}
    ok = reject_content_draft(draft_id, data.get("reason", ""))
    if not ok:
        return jsonify({"success": False, "error": "Newsletter draft not found."}), 404
    return jsonify({"success": True})


@app.route('/api/newsletters/<int:draft_id>', methods=['DELETE'])
def api_newsletter_delete(draft_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE content_drafts SET status = 'deleted' WHERE draft_id = ? AND platform = 'newsletter'",
        (draft_id,),
    )
    conn.commit()
    updated = cursor.rowcount
    conn.close()
    if not updated:
        return jsonify({"success": False, "error": "Newsletter draft not found."}), 404
    return jsonify({"success": True})


@app.route('/api/sources', methods=['GET'])
def api_sources():
    from execution.research.source_manager import list_sources

    status = request.args.get("status")
    return jsonify(list_sources(status=status))


@app.route('/api/source-notifications', methods=['GET'])
def api_source_notifications():
    from execution.research.source_manager import list_notifications

    status = request.args.get("status", "unread")
    return jsonify(list_notifications(status=status))


@app.route('/api/sources/propose', methods=['POST'])
def api_source_propose():
    from execution.research.models import SourceDefinition
    from execution.research.source_manager import propose_source

    data = request.get_json() or {}
    required = ("name", "source_type", "base_url", "lane")
    missing = [field for field in required if not data.get(field)]
    if missing:
        return jsonify({"success": False, "error": f"Missing fields: {', '.join(missing)}"}), 400

    try:
        source_id = propose_source(
            SourceDefinition(
                name=data["name"].strip(),
                source_type=data["source_type"].strip(),
                base_url=data["base_url"].strip(),
                lane=data["lane"].strip(),
                credibility_score=float(data.get("credibility_score", 0.65)),
                monitor_frequency=data.get("monitor_frequency", "weekly"),
                notes=data.get("notes", ""),
                enabled=False,
                approval_status="pending_approval",
                added_by="dashboard",
            ),
            added_by="dashboard",
        )
        return jsonify({"success": True, "source_id": source_id})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/sources/<int:source_id>/approve', methods=['POST'])
def api_source_approve(source_id):
    from execution.research.source_manager import approve_source

    return jsonify({"success": approve_source(source_id)})


@app.route('/api/sources/<int:source_id>/reject', methods=['POST'])
def api_source_reject(source_id):
    from execution.research.source_manager import reject_source

    return jsonify({"success": reject_source(source_id)})


@app.route('/api/content-drafts', methods=['GET'])
def api_content_drafts():
    from execution.research.draft_generator import list_content_drafts

    return jsonify(
        list_content_drafts(
            status=request.args.get("status"),
            platform=request.args.get("platform"),
        )
    )


@app.route('/api/content-drafts/generate', methods=['POST'])
def api_content_draft_generate():
    from execution.research.draft_generator import generate_research_draft

    data = request.get_json() or {}
    topic_title = data.get("topic_title")
    if not topic_title:
        return jsonify({"success": False, "error": "topic_title is required"}), 400

    try:
        result = generate_research_draft(
            topic_title=topic_title,
            lane=data.get("lane"),
            angle_type=data.get("angle_type"),
            platform=data.get("platform", "newsletter"),
            limit_per_task=int(data.get("limit_per_task", 5)),
            persist=True,
        )
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/content-drafts/<int:draft_id>/approve', methods=['POST'])
def api_content_draft_approve(draft_id):
    from execution.research.draft_generator import approve_content_draft

    return jsonify({"success": approve_content_draft(draft_id)})


@app.route('/api/content-drafts/<int:draft_id>/reject', methods=['POST'])
def api_content_draft_reject(draft_id):
    from execution.research.draft_generator import reject_content_draft

    data = request.get_json() or {}
    return jsonify({"success": reject_content_draft(draft_id, data.get("reason", ""))})


@app.route('/api/knowledge/stats', methods=['GET'])
def api_knowledge_stats():
    from execution.knowledge.service import knowledge_stats

    return jsonify(knowledge_stats())


@app.route('/api/knowledge/entries', methods=['GET'])
def api_knowledge_entries():
    from execution.knowledge.service import list_knowledge_entries

    min_quality = request.args.get("min_quality")
    return jsonify(
        list_knowledge_entries(
            search=request.args.get("search"),
            lane=request.args.get("lane"),
            entry_type=request.args.get("entry_type"),
            source_type=request.args.get("source_type"),
            quality_status=request.args.get("quality_status"),
            min_quality=float(min_quality) if min_quality else None,
            limit=int(request.args.get("limit", 100)),
        )
    )


@app.route('/api/knowledge/entries/<int:entry_id>', methods=['GET'])
def api_knowledge_entry_detail(entry_id):
    from execution.knowledge.service import get_knowledge_entry

    entry = get_knowledge_entry(entry_id)
    if not entry:
        return jsonify({"success": False, "error": "Knowledge entry not found."}), 404
    return jsonify({"success": True, "entry": entry})


@app.route('/api/knowledge/ingest', methods=['POST'])
def api_knowledge_ingest():
    from execution.knowledge.service import ingest_current_intelligence, knowledge_stats

    result = ingest_current_intelligence()
    return jsonify({"success": True, "ingest": result, "stats": knowledge_stats()})


@app.route('/api/knowledge/entries/<int:entry_id>/block', methods=['POST'])
def api_knowledge_entry_block(entry_id):
    from execution.knowledge.service import set_entry_quality_status

    return jsonify({"success": set_entry_quality_status(entry_id, "blocked")})


@app.route('/api/knowledge/entries/<int:entry_id>/restore', methods=['POST'])
def api_knowledge_entry_restore(entry_id):
    from execution.knowledge.service import set_entry_quality_status

    return jsonify({"success": set_entry_quality_status(entry_id, "auto_approved")})


@app.route('/api/knowledge/entries/<int:entry_id>/mark-stale', methods=['POST'])
def api_knowledge_entry_mark_stale(entry_id):
    from execution.knowledge.service import set_entry_quality_status

    return jsonify({"success": set_entry_quality_status(entry_id, "stale")})


@app.route('/api/amazon-products', methods=['GET'])
def api_amazon_products():
    include_inactive = _request_bool(request.args.get("include_inactive"), False)
    conn = get_db_connection()
    cursor = conn.cursor()
    where = "" if include_inactive else "WHERE COALESCE(active, 1) = 1"
    cursor.execute(f"""
        SELECT product_id, title, description, url, image_url, keywords,
               content_lanes, price_tier, priority_score, active, last_used,
               solution_tags, problem_tags, source_type, media_status,
               auto_created, needs_manual_image, evidence_notes, match_notes
        FROM amazon_products
        {where}
        ORDER BY COALESCE(active, 1) DESC, title COLLATE NOCASE ASC
    """)
    products = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(products)


def _amazon_product_payload() -> tuple[dict, list[str]]:
    data = request.get_json() or {}
    payload = {
        "title": (data.get("title") or "").strip(),
        "description": (data.get("description") or "").strip(),
        "url": (data.get("url") or "").strip(),
        "image_url": (data.get("image_url") or "").strip(),
        "keywords": (data.get("keywords") or "").strip(),
        "content_lanes": (data.get("content_lanes") or "").strip(),
        "price_tier": (data.get("price_tier") or "affordable").strip() or "affordable",
        "priority_score": float(data.get("priority_score") or 1.0),
        "active": 1 if _request_bool(data.get("active"), True) else 0,
    }
    required = ["title", "description", "url"]
    missing = [field for field in required if not payload[field]]
    return payload, missing


@app.route('/api/amazon-products', methods=['POST'])
def api_amazon_product_create():
    try:
        payload, missing = _amazon_product_payload()
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "priority_score must be a number."}), 400
    if missing:
        return jsonify({"success": False, "error": f"Missing fields: {', '.join(missing)}"}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO amazon_products
            (title, description, url, image_url, keywords, content_lanes, price_tier,
             priority_score, media_status, needs_manual_image, active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        payload["title"], payload["description"], payload["url"], payload["image_url"],
        payload["keywords"], payload["content_lanes"], payload["price_tier"],
        payload["priority_score"],
        "complete" if payload["image_url"] else "needs_image",
        0 if payload["image_url"] else 1,
        payload["active"],
    ))
    product_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"success": True, "product_id": product_id})


@app.route('/api/amazon-products/<int:product_id>', methods=['PUT'])
def api_amazon_product_update(product_id):
    try:
        payload, missing = _amazon_product_payload()
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "priority_score must be a number."}), 400
    if missing:
        return jsonify({"success": False, "error": f"Missing fields: {', '.join(missing)}"}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE amazon_products
        SET title = ?, description = ?, url = ?, image_url = ?, keywords = ?,
            content_lanes = ?, price_tier = ?, priority_score = ?,
            media_status = ?, needs_manual_image = ?, active = ?
        WHERE product_id = ?
    """, (
        payload["title"], payload["description"], payload["url"], payload["image_url"],
        payload["keywords"], payload["content_lanes"], payload["price_tier"],
        payload["priority_score"],
        "complete" if payload["image_url"] else "needs_image",
        0 if payload["image_url"] else 1,
        payload["active"],
        product_id,
    ))
    conn.commit()
    updated = cursor.rowcount
    conn.close()
    if not updated:
        return jsonify({"success": False, "error": "Product not found."}), 404
    return jsonify({"success": True})


@app.route('/api/amazon-products/<int:product_id>', methods=['DELETE'])
def api_amazon_product_delete(product_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE amazon_products SET active = 0 WHERE product_id = ?", (product_id,))
    conn.commit()
    updated = cursor.rowcount
    conn.close()
    if not updated:
        return jsonify({"success": False, "error": "Product not found."}), 404
    return jsonify({"success": True})


@app.route('/api/amazon-products/match', methods=['POST'])
def api_amazon_product_match():
    from urllib.parse import urlparse

    from execution.config import AMAZON_ASSOCIATE_TAG
    from execution.content.blog_generator import _apply_amazon_associate_tag, get_relevant_product

    data = request.get_json() or {}
    topic_title = data.get("topic_title", "").strip()
    if not topic_title:
        return jsonify({"success": False, "error": "topic_title is required"}), 400

    product = get_relevant_product(
        topic_title=topic_title,
        topic_description=data.get("description", ""),
        content_lane=data.get("lane"),
    )
    if not product:
        return jsonify({"success": False, "error": "No Amazon products are available"}), 404

    final_url = _apply_amazon_associate_tag(product["url"])
    host = urlparse(product["url"]).netloc.lower()
    if not AMAZON_ASSOCIATE_TAG:
        affiliate_status = "No AMAZON_ASSOCIATE_TAG configured"
    elif "amazon." in host and final_url != product["url"]:
        affiliate_status = "Amazon Associates tag will be appended"
    elif "amzn.to" in host:
        affiliate_status = "Amazon short link preserved; attribution depends on the short link destination"
    else:
        affiliate_status = "Non-Amazon URL preserved"

    return jsonify({
        "success": True,
        "product": {
            "product_id": product["product_id"],
            "title": product["title"],
            "description": product["description"],
            "image_url": product["image_url"],
            "keywords": product.get("keywords"),
            "content_lanes": product.get("content_lanes"),
            "price_tier": product.get("price_tier"),
            "media_status": product.get("media_status"),
            "needs_manual_image": bool(product.get("needs_manual_image")),
            "match_notes": product.get("match_notes"),
            "final_url": final_url,
        },
        "affiliate_status": affiliate_status,
    })


@app.route('/api/blog-preview/generate', methods=['POST'])
def api_blog_preview_generate():
    from execution.config import PROMPTS_DIR
    from execution.content.blog_generator import fill_template, get_relevant_product, load_html_template
    from execution.models import BlogGenerationResponse
    from execution.utils.llm_client import LLMClient

    data = request.get_json() or {}
    lane = data.get("lane") or "product_watch"
    defaults = BLOG_PREVIEW_DEFAULTS.get(lane, BLOG_PREVIEW_DEFAULTS["product_watch"])
    topic_title = (data.get("topic_title") or defaults["title"]).strip()
    topic_description = (data.get("description") or defaults["description"]).strip()

    product = get_relevant_product(
        topic_title=topic_title,
        topic_description=topic_description,
        content_lane=lane,
    )
    if not product:
        return jsonify({"success": False, "error": "No Amazon products are available"}), 404

    try:
        if data.get("sample"):
            content = _sample_blog_preview_content(topic_title, lane)
            generation_mode = "sample"
        else:
            system_prompt = (PROMPTS_DIR / "brand_system_prompt.txt").read_text(encoding="utf-8")
            user_prompt_template = (PROMPTS_DIR / "blog_generation.txt").read_text(encoding="utf-8")
            user_prompt = user_prompt_template.format(
                pin_topic=topic_title,
                pin_description=topic_description,
                product_title=product["title"],
                product_description=product["description"],
                product_match_notes=product.get("match_notes") or "Matched by topic, lane, and reader pain point.",
                content_lane=lane,
                angle_type="preview",
                freshness_hook="Make the value concrete and useful.",
                source_hint="Use cautious wording and name the source type to verify.",
            )
            user_prompt += (
                "\n\nPREVIEW MODE:\n"
                "Generate a complete blog draft for visual review only. "
                "Do not mention that this is a preview. Keep the structure complete."
            )

            content = LLMClient().generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format=BlogGenerationResponse,
                task_name="blog_preview_generation",
            )
            generation_mode = "llm"
        final_html = fill_template(load_html_template(), content, product)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    BLOG_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    preview_id = uuid.uuid4().hex
    filename = f"{preview_id}.html"
    preview_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(content.main_title)}</title>
  <style>
    body {{ margin:0; background:#f7f4ef; }}
    .egf-preview-bar {{
      background:#17212b;
      color:#fff;
      font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
      font-size:13px;
      padding:10px 18px;
      text-align:center;
    }}
  </style>
</head>
<body>
  <div class="egf-preview-bar">Preview only - not published or scheduled</div>
  {final_html}
</body>
</html>"""
    (BLOG_PREVIEW_DIR / filename).write_text(preview_doc, encoding="utf-8")

    return jsonify({
        "success": True,
        "preview_id": preview_id,
        "preview_url": f"/blog-previews/{filename}",
        "title": content.main_title,
        "category": content.category,
        "topic_title": topic_title,
        "lane": lane,
        "generation_mode": generation_mode,
        "product": {
            "title": product["title"],
            "description": product["description"],
            "image_url": product["image_url"],
            "content_lanes": product.get("content_lanes"),
            "media_status": product.get("media_status"),
            "needs_manual_image": bool(product.get("needs_manual_image")),
            "match_notes": product.get("match_notes"),
        },
    })


@app.route('/blog-previews/<path:filename>')
def serve_blog_preview(filename):
    return send_from_directory(BLOG_PREVIEW_DIR, filename)


@app.route('/sandbox/pin')
def sandbox_pin():
    return """
    <html>
    <head><title>Pinterest</title></head>
    <body style="font-family:sans-serif; background:#e9e9e9; margin:0; padding:40px;">
        <div style="background:white; border-radius:16px; max-width:800px; margin:auto; display:flex; overflow:hidden; box-shadow:0 10px 30px rgba(0,0,0,0.1);">
            <div style="flex:1; background:#f0f0f0; min-height:500px; display:flex; align-items:center; justify-content:center;">
                <img src="/images/sandbox-image.jpg" onerror="this.style.display='none'" style="width:100%; height:100%; object-fit:cover;" />
                <h1 style="color:#aaa;">(Generated Image)</h1>
            </div>
            <div style="flex:1; padding:40px;">
                <h2 style="margin-top:0;">10 Incredible Gluten Free Tips</h2>
                <p style="color:#666;">Easy Gluten Free • 12k followers</p>
                <div style="margin-top:40px;">
                    <a href="#" style="background:#e60023; color:white; padding:12px 20px; text-decoration:none; border-radius:24px; font-weight:bold;">Save</a>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

# ──────────────────────────────────────────────
# Static: Images
# ──────────────────────────────────────────────

@app.route('/images/<path:filename>')
def serve_image(filename):
    return send_from_directory(TMP_PINS_DIR, filename)

# ──────────────────────────────────────────────
# Frontend
# ──────────────────────────────────────────────

@app.route('/')
def index():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>EGF Content Dashboard</title>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
        <style>
            *{box-sizing:border-box;margin:0;padding:0}
            body{font-family:'Inter',sans-serif;background:#f0f4f3;color:#1a1a2e}

            /* ── Header ── */
            header{background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%);color:white;padding:16px 28px;display:flex;align-items:center;justify-content:space-between;box-shadow:0 2px 20px rgba(0,0,0,0.25)}
            .logo{font-size:1.25rem;font-weight:700;letter-spacing:.3px;display:flex;align-items:center;gap:12px}
            .header-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
            /* ── Sandbox Banner ── */
            .sandbox-banner{display:none;width:100%;background:linear-gradient(90deg,#f39c12,#e67e22);color:white;text-align:center;padding:8px 16px;font-size:0.85rem;font-weight:700;letter-spacing:.4px;z-index:999;align-items:center;justify-content:center;gap:10px}
            .sandbox-banner.visible{display:flex}
            .sandbox-pill{background:rgba(255,255,255,0.25);border-radius:20px;padding:2px 10px;font-size:0.78rem;font-weight:800;letter-spacing:1px}
            .btn-hdr{border:none;border-radius:8px;cursor:pointer;font-weight:600;font-size:0.82rem;padding:8px 14px;transition:all .2s;display:flex;align-items:center;gap:6px}
            .btn-hdr-primary{background:#e94560;color:white}
            .btn-hdr-primary:hover{background:#c73652}
            .btn-hdr-recipe{background:linear-gradient(135deg,#27ae60,#1e8449);color:white}
            .btn-hdr-recipe:hover{background:linear-gradient(135deg,#1e8449,#145a32)}
            .btn-hdr-ghost{background:rgba(255,255,255,0.1);color:white}
            .btn-hdr-ghost:hover{background:rgba(255,255,255,0.2)}
            .tab-nav{display:flex;gap:6px}
            .tab-btn{background:rgba(255,255,255,0.08);border:none;color:rgba(255,255,255,0.7);padding:7px 18px;border-radius:20px;cursor:pointer;font-size:0.85rem;font-family:inherit;transition:all .2s}
            .tab-btn.active,.tab-btn:hover{background:#e94560;color:white}

            /* ── Layout ── */
            main{max-width:1380px;margin:0 auto;padding:28px 20px}
            .section-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px}
            .section-title{font-size:1rem;font-weight:700;color:#1a1a2e}
            .tab-content{display:none}
            .tab-content.active{display:block}
            .empty{text-align:center;padding:60px 20px;color:#aaa;font-size:1rem;grid-column:1/-1}
            .review-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:18px;align-items:start}
            .review-panel{background:white;border-radius:14px;box-shadow:0 2px 12px rgba(0,0,0,.07);border:1px solid #edf0f2;padding:16px}
            .review-panel h3{font-size:.98rem;color:#1a1a2e;margin-bottom:6px}
            .review-panel p{font-size:.8rem;color:#666;line-height:1.5;margin-bottom:12px}
            .asset-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}
            .asset-card{background:white;border:1px solid #edf0f2;border-radius:12px;box-shadow:0 2px 10px rgba(0,0,0,.06);overflow:hidden;cursor:pointer;transition:transform .15s,box-shadow .15s}
            .asset-card:hover{transform:translateY(-2px);box-shadow:0 6px 20px rgba(0,0,0,.11)}
            .asset-card-body{padding:13px}
            .asset-title{font-size:.96rem;font-weight:800;color:#1a1a2e;line-height:1.3;margin-bottom:6px}
            .asset-copy{font-size:.8rem;color:#555;line-height:1.5;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}
            .asset-thumb{width:100%;height:180px;object-fit:cover;background:#eef2f7;display:block}
            .asset-thumb.pin{height:300px}
            .asset-actions{display:flex;gap:8px;flex-wrap:wrap;padding:0 13px 13px}
            .btn-muted{background:#eef2f7;color:#1f2937;flex:none;padding:8px 12px}
            .btn-danger{background:#f8d7da;color:#842029;flex:none;padding:8px 12px}
            .safety-box{background:#fff8e1;border:1px solid #ffe08a;border-radius:10px;padding:10px;margin:12px 0;font-size:.84rem;color:#6b4e00}
            .safety-box label{display:flex;gap:8px;align-items:flex-start;line-height:1.4}
            .detail-overlay{position:fixed;inset:0;background:rgba(8,12,22,.62);display:none;align-items:center;justify-content:center;z-index:1100;padding:24px}
            .detail-overlay.active{display:flex}
            .detail-modal{background:white;border-radius:14px;box-shadow:0 20px 70px rgba(0,0,0,.35);width:min(1040px,96vw);max-height:92vh;display:flex;flex-direction:column;overflow:hidden}
            .detail-header{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:14px 18px;border-bottom:1px solid #edf0f2}
            .detail-title{font-size:1rem;font-weight:800;color:#1a1a2e}
            .detail-body{padding:18px;overflow:auto}
            .detail-actions{display:flex;gap:8px;flex-wrap:wrap;padding:13px 18px;border-top:1px solid #edf0f2;background:#fbfcfd}
            .detail-image{width:100%;max-height:420px;object-fit:contain;background:#eef2f7;border-radius:10px;margin-bottom:14px}
            .blog-frame{width:100%;height:68vh;border:1px solid #edf0f2;border-radius:10px;background:white}
            .product-toolbar{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:14px}
            .product-table-wrap{background:white;border-radius:14px;box-shadow:0 2px 12px rgba(0,0,0,.07);overflow:auto}
            .product-table{width:100%;border-collapse:collapse;min-width:980px}
            .product-table th{background:#1a1a2e;color:white;text-align:left;padding:10px 12px;font-size:.78rem}
            .product-table td{padding:10px 12px;border-bottom:1px solid #edf0f2;font-size:.8rem;vertical-align:top}
            .product-table tr.muted{opacity:.55}
            .product-img{width:64px;height:64px;object-fit:cover;border-radius:8px;background:#eef2f7}
            .form-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
            .form-grid .wide{grid-column:1/-1}
            .form-grid input,.form-grid textarea{width:100%;border:1px solid #d9e0e4;border-radius:8px;padding:9px 10px;font-family:inherit;font-size:.84rem}
            .form-grid textarea{min-height:80px;resize:vertical}

            /* ── Pin Cards (existing tab) ── */
            .pins-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:20px}
            .pin-card{background:white;border-radius:14px;box-shadow:0 2px 12px rgba(0,0,0,0.07);overflow:hidden;display:flex;flex-direction:column}
            .pin-image{width:100%;height:440px;object-fit:cover;background:#eee}
            .pin-content{padding:14px;flex-grow:1}
            .pin-badge{display:inline-block;font-size:0.68rem;font-weight:700;text-transform:uppercase;letter-spacing:1px;background:#f0f4f3;color:#555;padding:3px 10px;border-radius:20px;margin-bottom:9px}
            .pin-title{font-size:1rem;font-weight:700;margin-bottom:7px}
            .pin-desc{font-size:0.84rem;color:#666;line-height:1.5;white-space:pre-wrap;margin-bottom:10px}
            .pin-keywords{font-size:0.74rem;color:#999}
            .pin-actions{display:flex;padding:12px 14px;border-top:1px solid #f0f0f0;gap:8px}
            .btn{flex:1;padding:9px;border:none;border-radius:8px;cursor:pointer;font-weight:700;font-size:0.87rem;font-family:inherit;transition:opacity .2s,transform .1s}
            .btn:hover{opacity:.85;transform:translateY(-1px)}
            .btn-approve{background:#27ae60;color:white}
            .btn-reject{background:#e74c3c;color:white}
            .btn-publish{background:#f39c12;color:white;font-size:0.78rem;padding:5px 10px;border-radius:5px;flex:none}
            .btn-trigger{background:#e94560;color:white;flex:none;padding:9px 18px;font-size:0.84rem}
            .btn-trigger:disabled,.btn-gen:disabled{background:#ccc;cursor:not-allowed}

            /* ── Schedule Table ── */
            .schedule-table{width:100%;border-collapse:collapse;background:white;border-radius:14px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.07)}
            .schedule-table th{background:#1a1a2e;color:white;padding:11px 15px;text-align:left;font-size:0.82rem}
            .schedule-table td{padding:11px 15px;border-bottom:1px solid #f0f0f0;font-size:0.84rem}
            .schedule-table tr:last-child td{border-bottom:none}
            .status-badge{padding:3px 10px;border-radius:20px;font-size:0.72rem;font-weight:700}
            .status-pending{background:#fff3cd;color:#856404}
            .status-published{background:#d1e7dd;color:#155724}
            .status-failed{background:#f8d7da;color:#842029}
            .status-approved{background:#cce5ff;color:#004085}
            .error-text{color:#e74c3c;font-size:0.72rem;display:block;margin-top:3px;max-width:230px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:help}
            .action-col{display:flex;gap:6px;flex-wrap:wrap}

            /* ── Spinner ── */
            .spinner{display:inline-block;width:13px;height:13px;border:2px solid rgba(255,255,255,.3);border-radius:50%;border-top-color:#fff;animation:spin 1s linear infinite;margin-right:6px;vertical-align:middle;display:none}
            @keyframes spin{to{transform:rotate(360deg)}}
            .loading .spinner{display:inline-block}

            /* ── Modal (existing generate content) ── */
            .modal-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);display:none;justify-content:center;align-items:center;z-index:900}
            .modal{background:white;padding:24px;border-radius:14px;max-width:400px;width:100%;box-shadow:0 10px 30px rgba(0,0,0,0.2)}
            .modal h2{font-size:1.1rem;margin-bottom:13px;color:#1a1a2e}
            .modal select{width:100%;padding:10px;margin-bottom:18px;border-radius:6px;border:1px solid #ddd;font-size:.95rem;font-family:inherit}
            .modal input,.modal textarea{width:100%;padding:10px;margin-bottom:12px;border-radius:6px;border:1px solid #ddd;font-size:.95rem;font-family:inherit}
            .modal textarea{min-height:76px;resize:vertical}
            .modal .actions{display:flex;gap:8px;justify-content:flex-end}
            .btn-close{background:#eee;color:#333;padding:9px 18px;border:none;border-radius:8px;cursor:pointer;font-weight:600;font-family:inherit}
            .recipe-idea-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px;margin-bottom:24px}
            .recipe-idea-card{background:#fff;border:1px solid #edf0f4;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,.06);padding:16px}
            .recipe-idea-title{font-size:1rem;font-weight:800;color:#1a1a2e;line-height:1.3;margin-bottom:8px}
            .recipe-idea-meta{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
            .recipe-idea-chip{background:#f3f6f8;border-radius:999px;color:#556070;font-size:.72rem;font-weight:700;padding:4px 9px}
            .recipe-idea-chip.warn{background:#fff3cd;color:#7a4b00}
            .recipe-idea-copy{color:#58616d;font-size:.86rem;line-height:1.5;margin-bottom:12px}
            .recipe-idea-actions{display:flex;gap:8px;flex-wrap:wrap}

            /* ── Recipe Generation Loading Overlay ── */
            .recipe-loading-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(15,20,30,0.88);display:none;flex-direction:column;justify-content:center;align-items:center;z-index:1000;backdrop-filter:blur(4px)}
            .recipe-loading-overlay.active{display:flex}
            .recipe-loading-box{background:white;border-radius:20px;padding:40px 50px;text-align:center;max-width:420px;box-shadow:0 20px 60px rgba(0,0,0,0.4)}
            .recipe-loading-box h2{font-size:1.3rem;margin-bottom:8px;color:#1a1a2e}
            .recipe-loading-box p{color:#666;font-size:.9rem;line-height:1.5;margin-bottom:24px}
            .recipe-progress-bar{height:5px;background:#eee;border-radius:10px;overflow:hidden;margin-bottom:12px}
            .recipe-progress-fill{height:100%;width:0%;background:linear-gradient(90deg,#27ae60,#e94560);border-radius:10px;transition:width .4s ease;animation:progress-pulse 2.5s ease-in-out infinite}
            @keyframes progress-pulse{0%,100%{opacity:1}50%{opacity:.6}}
            .recipe-loading-steps{font-size:.8rem;color:#999;min-height:22px}
            .recipe-leaf-spin{font-size:2.5rem;display:block;margin:0 auto 18px;animation:leaf-bounce 1.4s ease-in-out infinite}
            @keyframes leaf-bounce{0%,100%{transform:scale(1) rotate(0deg)}50%{transform:scale(1.15) rotate(12deg)}}

            /* ── Recipe Cards ── */
            .recipes-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(520px,1fr));gap:24px}
            .recipe-card{background:white;border-radius:16px;box-shadow:0 3px 16px rgba(0,0,0,0.09);overflow:hidden;display:flex;flex-direction:column;border:1px solid #f0f0f0;transition:box-shadow .2s}
            .recipe-card:hover{box-shadow:0 6px 24px rgba(0,0,0,0.13)}
            .recipe-card-top{display:flex;gap:0}
            .recipe-cover-wrap{width:200px;min-height:260px;flex-shrink:0;background:#e8ede8;position:relative;overflow:hidden}
            .recipe-cover-img{width:100%;height:100%;object-fit:cover}
            .recipe-cover-placeholder{width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:2.5rem;color:#ccc;background:#f5f5f5}
            .recipe-info{flex:1;padding:18px;display:flex;flex-direction:column;min-width:0}
            .recipe-category-badge{font-size:0.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.8px;background:linear-gradient(135deg,#e8f5e9,#c8e6c9);color:#2e7d32;padding:3px 10px;border-radius:20px;display:inline-block;margin-bottom:10px}
            .recipe-title{font-size:1.05rem;font-weight:700;color:#1a1a2e;margin-bottom:8px;line-height:1.3}
            .recipe-meta{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:10px}
            .recipe-meta-chip{font-size:0.75rem;color:#666;background:#f7f7f7;padding:3px 9px;border-radius:12px;display:flex;align-items:center;gap:4px}
            .recipe-desc{font-size:0.83rem;color:#555;line-height:1.5;margin-bottom:12px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
            .recipe-status-row{display:flex;gap:6px;flex-wrap:wrap;margin-top:auto}
            .recipe-pub-badge{font-size:0.72rem;font-weight:600;padding:3px 10px;border-radius:20px;display:flex;align-items:center;gap:4px}
            .pub-wp{background:#e8f4fd;color:#1565c0}
            .pub-pin{background:#fde8e8;color:#c0392b}

            /* ── Recipe Inner Tabs ── */
            .recipe-inner-tabs{display:flex;gap:0;border-top:1px solid #eee;border-bottom:1px solid #eee;background:#fafafa}
            .recipe-tab-btn{flex:1;padding:9px 6px;border:none;background:none;cursor:pointer;font-size:0.78rem;font-weight:600;color:#888;font-family:inherit;border-bottom:2px solid transparent;transition:all .15s}
            .recipe-tab-btn.active{color:#27ae60;border-bottom-color:#27ae60;background:white}
            .recipe-tab-content{padding:16px;font-size:0.84rem;display:none;max-height:310px;overflow-y:auto}
            .recipe-tab-content.active{display:block}

            /* Ingredient list */
            .ing-list{list-style:none;display:flex;flex-direction:column;gap:5px}
            .ing-item{display:flex;gap:8px;padding:5px 0;border-bottom:1px solid #f5f5f5}
            .ing-amount{font-weight:700;color:#1a1a2e;min-width:70px;flex-shrink:0}
            .ing-name{color:#333}
            .ing-notes{color:#999;font-style:italic;font-size:.8rem}

            /* Instruction list */
            .step-list{display:flex;flex-direction:column;gap:14px}
            .step-item{display:flex;gap:12px}
            .step-num{width:26px;height:26px;border-radius:50%;background:#1a1a2e;color:white;font-size:.78rem;font-weight:700;display:flex;align-items:center;justify-content:center;flex-shrink:0;margin-top:1px}
            .step-text{flex:1;color:#333;line-height:1.55}

            /* Image grid */
            .step-images-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
            .step-img-wrap{position:relative;border-radius:8px;overflow:hidden;background:#eee;aspect-ratio:1}
            .step-img-wrap img{width:100%;height:100%;object-fit:cover}
            .step-img-label{position:absolute;bottom:0;left:0;right:0;background:rgba(0,0,0,0.5);color:white;font-size:0.7rem;padding:3px 6px;text-align:center}

            /* ── Recipe Footer Actions ── */
            .recipe-actions{display:flex;padding:13px 16px;border-top:1px solid #f0f0f0;gap:8px;flex-wrap:wrap}
            .btn-recipe-approve{background:linear-gradient(135deg,#27ae60,#1e8449);color:white;padding:9px 18px;border:none;border-radius:8px;cursor:pointer;font-weight:700;font-size:.85rem;font-family:inherit;transition:opacity .2s}
            .btn-recipe-approve:hover{opacity:.88}
            .btn-recipe-reject{background:#f8d7da;color:#842029;padding:9px 18px;border:none;border-radius:8px;cursor:pointer;font-weight:700;font-size:.85rem;font-family:inherit;transition:opacity .2s}
            .btn-recipe-reject:hover{opacity:.85}
            .btn-recipe-wp{background:linear-gradient(135deg,#1565c0,#0d47a1);color:white;padding:9px 18px;border:none;border-radius:8px;cursor:pointer;font-weight:700;font-size:.85rem;font-family:inherit;transition:opacity .2s;display:flex;align-items:center;gap:6px}
            .btn-recipe-wp:hover{opacity:.88}
            .btn-recipe-pin{background:linear-gradient(135deg,#e60023,#c0001e);color:white;padding:9px 18px;border:none;border-radius:8px;cursor:pointer;font-weight:700;font-size:.85rem;font-family:inherit;transition:opacity .2s;display:flex;align-items:center;gap:6px}
            .btn-recipe-pin:hover{opacity:.88}
            .btn-recipe-download{background:#eef2f7;color:#1f2937;padding:9px 14px;border:none;border-radius:8px;cursor:pointer;font-weight:700;font-size:.85rem;font-family:inherit;transition:opacity .2s;display:flex;align-items:center;gap:6px}
            .btn-recipe-download:hover{opacity:.82}
            .btn-recipe-json{background:#fff3cd;color:#7a4b00;padding:9px 14px;border:none;border-radius:8px;cursor:pointer;font-weight:700;font-size:.85rem;font-family:inherit;transition:opacity .2s;display:flex;align-items:center;gap:6px}
            .btn-recipe-json:hover{opacity:.82}
            button:disabled{opacity:.45;cursor:not-allowed!important}

            /* ── Approved section divider ── */
            .section-divider{margin:28px 0 18px;padding:10px 16px;background:linear-gradient(135deg,#e8f5e9,#f0f9f0);border-radius:10px;border-left:4px solid #27ae60}
            .section-divider h3{font-size:.95rem;color:#1e8449;font-weight:700}
            .section-divider p{font-size:.8rem;color:#666;margin-top:2px}

            /* Editorial Lab */
            .lab-grid{display:grid;grid-template-columns:minmax(320px,.9fr) minmax(420px,1.1fr);gap:20px;align-items:start}
            .lab-panel{background:white;border-radius:14px;box-shadow:0 2px 12px rgba(0,0,0,.07);padding:18px;border:1px solid #edf0f2}
            .lab-panel h3{font-size:.98rem;color:#1a1a2e;margin-bottom:6px}
            .lab-panel p{font-size:.82rem;color:#666;line-height:1.5;margin-bottom:12px}
            .lab-form{display:grid;gap:10px}
            .lab-form input,.lab-form select,.lab-form textarea{width:100%;border:1px solid #d9e0e4;border-radius:8px;padding:9px 10px;font-family:inherit;font-size:.84rem;background:white}
            .lab-form textarea{min-height:74px;resize:vertical}
            .lab-row{display:grid;grid-template-columns:1fr 1fr;gap:10px}
            .lab-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
            .lab-list{display:grid;gap:10px;margin-top:12px}
            .lab-item{border:1px solid #edf0f2;border-radius:10px;padding:12px;background:#fbfcfd}
            .lab-item-title{font-size:.9rem;font-weight:700;color:#1a1a2e;margin-bottom:4px}
            .lab-meta{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}
            .lab-chip{font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.6px;background:#eef2f7;color:#46505a;padding:3px 8px;border-radius:999px}
            .lab-chip.pending{background:#fff3cd;color:#856404}
            .lab-chip.approved{background:#d1e7dd;color:#155724}
            .lab-chip.rejected{background:#f8d7da;color:#842029}
            .lab-source-url{font-size:.76rem;color:#1565c0;word-break:break-word}
            .draft-card{background:white;border-radius:14px;box-shadow:0 2px 12px rgba(0,0,0,.07);border:1px solid #edf0f2;padding:16px}
            .draft-title{font-size:1rem;font-weight:800;color:#1a1a2e;margin-bottom:6px}
            .draft-dek{font-size:.84rem;color:#555;line-height:1.55;margin-bottom:10px}
            .draft-section{background:#f7f9fb;border-radius:9px;padding:10px;margin-top:8px;font-size:.82rem;color:#333;line-height:1.5}
            .draft-section strong{display:block;margin-bottom:3px;color:#1a1a2e}
            .source-links{margin-top:8px;display:grid;gap:4px}
            .source-links a{font-size:.76rem;color:#1565c0;word-break:break-word}
            .kb-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:16px}
            .kb-stat{background:white;border:1px solid #edf0f2;border-radius:12px;padding:14px;box-shadow:0 2px 10px rgba(0,0,0,.05)}
            .kb-stat-value{font-size:1.45rem;font-weight:800;color:#1a1a2e}
            .kb-stat-label{font-size:.74rem;color:#667085;text-transform:uppercase;letter-spacing:.6px;margin-top:3px}
            .kb-filters{background:white;border:1px solid #edf0f2;border-radius:14px;padding:14px;display:grid;grid-template-columns:1.4fr repeat(5,1fr) auto;gap:10px;align-items:end;margin-bottom:16px}
            .kb-filters input,.kb-filters select{width:100%;border:1px solid #d9e0e4;border-radius:8px;padding:9px 10px;font-family:inherit;font-size:.84rem;background:white}
            .kb-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:14px}
            .kb-card{background:white;border:1px solid #edf0f2;border-radius:14px;box-shadow:0 2px 12px rgba(0,0,0,.06);padding:15px;display:flex;flex-direction:column;gap:8px}
            .kb-title{font-size:.95rem;font-weight:800;color:#1a1a2e;line-height:1.35}
            .kb-summary{font-size:.82rem;color:#555;line-height:1.5;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
            .kb-meta{display:flex;gap:6px;flex-wrap:wrap}
            .kb-pill{font-size:.67rem;font-weight:800;text-transform:uppercase;letter-spacing:.55px;background:#eef2f7;color:#46505a;padding:3px 8px;border-radius:999px}
            .kb-pill.good{background:#d1e7dd;color:#155724}
            .kb-pill.warn{background:#fff3cd;color:#856404}
            .kb-pill.bad{background:#f8d7da;color:#842029}
            .kb-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:auto}
            .studio-grid{display:grid;grid-template-columns:minmax(320px,.85fr) minmax(520px,1.15fr);gap:20px;align-items:start}
            .studio-stack{display:grid;gap:16px}
            .studio-panel{background:white;border-radius:14px;box-shadow:0 2px 12px rgba(0,0,0,.07);padding:18px;border:1px solid #edf0f2}
            .studio-panel h3{font-size:.98rem;color:#1a1a2e;margin-bottom:6px}
            .studio-panel p{font-size:.82rem;color:#666;line-height:1.5;margin-bottom:12px}
            .studio-list{display:grid;gap:10px;margin-top:12px}
            .studio-card{border:1px solid #edf0f2;border-radius:10px;padding:12px;background:#fbfcfd}
            .studio-title{font-size:.92rem;font-weight:800;color:#1a1a2e;margin-bottom:5px}
            .studio-copy{font-size:.8rem;color:#555;line-height:1.5;white-space:pre-wrap}
            .studio-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
            .studio-checks{display:flex;gap:12px;flex-wrap:wrap;font-size:.8rem;color:#46505a}
            .studio-checks label{display:flex;gap:5px;align-items:center}
            .studio-mini-img{width:74px;height:104px;object-fit:cover;border-radius:8px;background:#eee;flex-shrink:0}
            .btn-copy{background:#eef2f7;color:#1f2937;flex:none;padding:8px 12px}
            .btn-wp{background:#1565c0;color:white;flex:none;padding:8px 12px}
            .btn-pin{background:#e60023;color:white;flex:none;padding:8px 12px}
            .btn-small{flex:none;padding:8px 12px;font-size:.78rem}
            @media(max-width:1080px){.studio-grid{grid-template-columns:1fr}}
            @media(max-width:1080px){.kb-filters{grid-template-columns:1fr 1fr}.kb-list{grid-template-columns:1fr}}
            @media(max-width:980px){.lab-grid{grid-template-columns:1fr}.lab-row{grid-template-columns:1fr}}
    </style>
    </head>
    <body>
        <!-- Sandbox mode banner (shown dynamically by JS) -->
        <div class="sandbox-banner" id="sandbox-banner">
            <span class="sandbox-pill">SANDBOX</span>
            Pinterest API calls are routed to <strong>api-sandbox.pinterest.com</strong> &mdash; no live pins will be created.
            <span class="sandbox-pill">SANDBOX</span>
        </div>
        <header>
            <div class="logo">
                🌿 Easy Gluten Free
                <div class="header-actions">
                    <button class="btn-hdr btn-hdr-recipe" id="btn-gen-recipe" onclick="openRecipeIdeaModal()">
                        <span class="spinner"></span>🍽️ Generate Recipe
                    </button>
                    <button class="btn-hdr btn-hdr-primary" onclick="openGenModal()">+ Generate Content</button>
                    <button class="btn-hdr btn-hdr-ghost" onclick="reauthorizePinterest()" title="Re-run Pinterest OAuth">🔑 Re-auth</button>
                </div>
            </div>
            <nav class="tab-nav">
                <button class="tab-btn active" id="tabnav-pending" onclick="showTab('tab-pending',this)">Pending Review</button>
                <button class="tab-btn" id="tabnav-approved-blogs" onclick="showTab('tab-approved-blogs',this)">Approved Blogs</button>
                <button class="tab-btn" id="tabnav-approved-pins" onclick="showTab('tab-approved-pins',this)">Approved Pins</button>
                <button class="tab-btn" id="tabnav-approved-newsletters" onclick="showTab('tab-approved-newsletters',this)">Approved Emails</button>
                <button class="tab-btn" id="tabnav-amazon" onclick="showTab('tab-amazon',this)">Amazon Products</button>
                <button class="tab-btn" id="tabnav-knowledge" onclick="showTab('tab-knowledge',this)">Knowledge DB</button>
                <button class="tab-btn" id="tabnav-recipes" onclick="showTab('tab-recipes',this)">🍽️ Recipes</button>
                <button class="tab-btn" id="tabnav-trends" onclick="showTab('tab-trends',this)">🔥 Trends &amp; Blog Gen</button>
                <button class="tab-btn" id="tabnav-studio" onclick="showTab('tab-studio',this)">Content Studio</button>
                <button class="tab-btn" id="tabnav-editorial" onclick="showTab('tab-editorial',this)">Editorial Lab</button>
            </nav>
        </header>

        <!-- Recipe Generation Loading Overlay -->
        <div class="recipe-loading-overlay" id="recipe-loading-overlay">
            <div class="recipe-loading-box">
                <span class="recipe-leaf-spin">🌿</span>
                <h2>Generating Your Recipe…</h2>
                <p>Claire is in the Sunday Light Kitchen crafting something delicious. This takes about 30–40 seconds.</p>
                <div class="recipe-progress-bar"><div class="recipe-progress-fill" id="recipe-progress-fill"></div></div>
                <div class="recipe-loading-steps" id="recipe-loading-steps">Starting up…</div>
            </div>
        </div>

        <main>
            <!-- PENDING REVIEW -->
            <div id="tab-pending" class="tab-content active">
                <div class="section-header">
                    <p class="section-title">Pending Review</p>
                    <button class="btn btn-trigger" onclick="fetchPendingReview()">Refresh</button>
                </div>
                <div class="review-grid">
                    <div class="review-panel">
                        <h3>Blogs</h3>
                        <p>Open each article, read the full blog, inspect the linked image, then approve or reject.</p>
                        <div id="pending-blogs-container" class="studio-list"><div class="empty">Loading blogs...</div></div>
                    </div>
                    <div class="review-panel">
                        <h3>Pins</h3>
                        <p>Open the image and caption details before approving. Modesty confirmation is required.</p>
                        <div id="pins-container" class="studio-list"><div class="empty">Loading pins...</div></div>
                    </div>
                    <div class="review-panel">
                        <h3>Newsletter Emails</h3>
                        <p>Read the complete email draft before approving it for the approved email page.</p>
                        <div id="pending-newsletters-container" class="studio-list"><div class="empty">Loading emails...</div></div>
                    </div>
                </div>
            </div>

            <!-- APPROVED BLOGS -->
            <div id="tab-approved-blogs" class="tab-content">
                <div class="section-header">
                    <p class="section-title">Approved Blogs</p>
                    <button class="btn btn-trigger" onclick="fetchApprovedBlogs()">Refresh</button>
                </div>
                <div id="approved-blogs-container" class="asset-grid"><div class="empty">Loading approved blogs...</div></div>
            </div>

            <!-- APPROVED PINS -->
            <div id="tab-approved-pins" class="tab-content">
                <div class="section-header">
                    <p class="section-title">Approved Pins</p>
                    <button class="btn btn-trigger" onclick="fetchApprovedPins()">Refresh</button>
                </div>
                <div id="approved-pins-container" class="asset-grid"><div class="empty">Loading approved pins...</div></div>
            </div>

            <!-- APPROVED NEWSLETTERS -->
            <div id="tab-approved-newsletters" class="tab-content">
                <div class="section-header">
                    <p class="section-title">Approved Newsletter Emails</p>
                    <button class="btn btn-trigger" onclick="fetchApprovedNewsletters()">Refresh</button>
                </div>
                <div id="approved-newsletters-container" class="asset-grid"><div class="empty">Loading approved emails...</div></div>
            </div>

            <!-- AMAZON PRODUCTS -->
            <div id="tab-amazon" class="tab-content">
                <div class="product-toolbar">
                    <p class="section-title">Amazon Products Catalog</p>
                    <div style="display:flex;gap:8px;flex-wrap:wrap">
                        <button class="btn btn-muted" onclick="fetchAmazonProducts()">Refresh</button>
                        <button class="btn btn-approve" onclick="openProductModal()">Add New Product</button>
                    </div>
                </div>
                <div class="product-table-wrap">
                    <table class="product-table">
                        <thead>
                            <tr>
                                <th>Image</th><th>Product</th><th>Description</th><th>Lanes</th><th>Keywords</th><th>Priority</th><th>Actions</th>
                            </tr>
                        </thead>
                        <tbody id="amazon-products-body">
                            <tr><td colspan="7" style="text-align:center;padding:28px;color:#aaa">Loading products...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- KNOWLEDGE DATABASE -->
            <div id="tab-knowledge" class="tab-content">
                <div class="section-header">
                    <p class="section-title">Knowledge DB: Quality-Gated Editorial Memory</p>
                    <div style="display:flex;gap:8px;flex-wrap:wrap">
                        <button class="btn btn-muted" onclick="fetchKnowledgeDb()">Refresh</button>
                        <button class="btn btn-approve" id="btn-kb-ingest" onclick="ingestKnowledgeDb()">
                            <span class="spinner"></span>Ingest Current Intelligence
                        </button>
                    </div>
                </div>
                <div class="kb-stats" id="kb-stats">
                    <div class="kb-stat"><div class="kb-stat-value">-</div><div class="kb-stat-label">Total</div></div>
                    <div class="kb-stat"><div class="kb-stat-value">-</div><div class="kb-stat-label">Reusable</div></div>
                    <div class="kb-stat"><div class="kb-stat-value">-</div><div class="kb-stat-label">Needs Evidence</div></div>
                    <div class="kb-stat"><div class="kb-stat-value">-</div><div class="kb-stat-label">Blocked/Stale</div></div>
                </div>
                <div class="kb-filters">
                    <input id="kb-search" placeholder="Search facts, feelings, products, restaurants, questions..." onkeydown="if(event.key==='Enter') fetchKnowledgeEntries()">
                    <select id="kb-lane">
                        <option value="">All lanes</option>
                        <option value="product_watch">Product Watch</option>
                        <option value="laws_labeling">Laws & Labeling</option>
                        <option value="comparison">Comparisons</option>
                        <option value="restaurants_travel">Restaurants & Travel</option>
                        <option value="gadgets_tools">Gadgets & Tools</option>
                        <option value="apps_digital">Apps & Digital Tools</option>
                        <option value="organization_life">Organization & Life</option>
                        <option value="recipe_experiments">Recipe Experiments</option>
                        <option value="science_health">Science & Health</option>
                        <option value="community_questions">Community Questions</option>
                    </select>
                    <select id="kb-entry-type">
                        <option value="">All types</option>
                        <option value="fact">Facts</option>
                        <option value="community_sentiment">Community Sentiment</option>
                        <option value="product_mention">Product Mentions</option>
                        <option value="restaurant_mention">Restaurant Mentions</option>
                        <option value="app_or_tool_mention">Apps & Tools</option>
                        <option value="recurring_question">Recurring Questions</option>
                        <option value="tip_or_system">Tips & Systems</option>
                        <option value="warning_or_risk">Warnings & Risks</option>
                    </select>
                    <select id="kb-quality-status">
                        <option value="">All statuses</option>
                        <option value="auto_approved">Reusable</option>
                        <option value="needs_more_evidence">Needs Evidence</option>
                        <option value="blocked">Blocked</option>
                        <option value="stale">Stale</option>
                    </select>
                    <select id="kb-source-type">
                        <option value="">All source types</option>
                        <option value="official_api">Official API</option>
                        <option value="official_recall_page">Official Recall Page</option>
                        <option value="certification_body">Certification Body</option>
                        <option value="gluten_free_organization">GF Organization</option>
                        <option value="medical_research">Medical Research</option>
                        <option value="medical_article">Medical Article</option>
                        <option value="reddit">Reddit</option>
                        <option value="restaurant_allergen_page">Restaurant Allergen Page</option>
                        <option value="brand_product_page">Brand/Product Page</option>
                        <option value="retailer_product_page">Retailer Product Page</option>
                        <option value="community_discussion">Community Discussion</option>
                        <option value="content_draft">Content Draft</option>
                        <option value="content_brief">Content Brief</option>
                    </select>
                    <select id="kb-min-quality">
                        <option value="">Any score</option>
                        <option value="0.55">0.55+</option>
                        <option value="0.72">0.72+</option>
                        <option value="0.85">0.85+</option>
                    </select>
                    <button class="btn btn-trigger" onclick="fetchKnowledgeEntries()">Search</button>
                </div>
                <div id="kb-list" class="kb-list"><div class="empty">Click "Ingest Current Intelligence" to build your Knowledge DB.</div></div>
            </div>

            <!-- RECIPES TAB -->
            <div id="tab-recipes" class="tab-content">
                <div class="section-header">
                    <p class="section-title">Recipe Review Queue</p>
                    <button class="btn btn-trigger" onclick="fetchRecipes()">↻ Refresh</button>
                </div>
                <div class="section-divider">
                    <h3>Recipe Title Ideas</h3>
                    <p>Approve one title to generate the full recipe, cover image, Pinterest pin, and step images.</p>
                </div>
                <div id="recipe-ideas-container" class="recipe-idea-list"><div class="empty">No recipe title ideas yet. Click "Generate Recipe" to suggest names first.</div></div>
                <!-- Pending Recipes -->
                <div class="section-divider">
                    <h3>Pending Full Recipes</h3>
                    <p>These already have full recipe data and generated images. Review before approval.</p>
                </div>
                <div id="recipes-pending-container" class="recipes-grid"><div class="empty">No pending recipes. Click "Generate Recipe" to create one.</div></div>
                <!-- Approved Recipes -->
                <div class="section-divider">
                    <h3>✅ Approved Recipes</h3>
                    <p>Recipes publish to WordPress only through WP Recipe Maker. They are not sent through the blog-post pipeline.</p>
                </div>
                <div id="recipes-approved-container" class="recipes-grid"><div class="empty">No approved recipes yet.</div></div>
            </div>

            <!-- TRENDS TAB -->
            <div id="tab-trends" class="tab-content">
                <div class="section-header">
                    <p class="section-title">Trendy Topics Discovered (AI &amp; PubMed)</p>
                    <button class="btn btn-trigger" id="btn-scrape-trends" onclick="scrapeAndSynthesizeTrends()">
                        <span class="spinner"></span>↻ Scrape &amp; Synthesize Trends
                    </button>
                </div>
                
                <!-- Pending Trends Section -->
                <div style="margin-bottom: 24px;">
                    <h3 style="font-size: 1.1rem; color: #1a1a2e; margin-bottom: 12px; display: flex; align-items: center; gap: 8px;">
                        🔥 Discovered Trends (Pending Review)
                    </h3>
                    <div id="trends-pending-container" class="pins-grid">
                        <div class="empty">Click "Scrape &amp; Synthesize Trends" to fetch and learn the latest trends.</div>
                    </div>
                </div>

                <!-- Approved Trends Section -->
                <div class="section-divider" style="margin-top: 36px;">
                    <h3>✅ Approved Topics &amp; Blog Queue</h3>
                    <p>Generate a complete WordPress blog + Pinterest Pin package directly from these topics.</p>
                </div>
                
                <table class="schedule-table" style="margin-top: 14px;">
                    <thead>
                        <tr>
                            <th style="width: 250px;">Topic Title</th>
                            <th style="width: 150px;">Source</th>
                            <th>Details &amp; AI Learnings</th>
                            <th style="width: 180px;">Actions</th>
                        </tr>
                    </thead>
                    <tbody id="trends-approved-body">
                        <tr>
                            <td colspan="4" style="text-align:center;padding:28px;color:#aaa">No approved topics yet. Approve a discovered trend above.</td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <!-- CONTENT STUDIO TAB -->
            <div id="tab-studio" class="tab-content">
                <div class="section-header">
                    <p class="section-title">Content Studio: Lane Ideas to Publishable Assets</p>
                    <button class="btn btn-trigger" onclick="fetchContentStudio()">Refresh</button>
                </div>
                <div class="studio-grid">
                    <div class="studio-stack">
                        <div class="studio-panel">
                            <h3>Generate Ideas by Topic Lane</h3>
                            <p>Pick a lane, generate fresh ideas, then turn any idea into a blog, Pinterest pin, and newsletter copy.</p>
                            <div class="lab-form">
                                <div class="lab-row">
                                    <select id="studio-lane" onchange="fetchStudioIdeas()">
                                        <option value="product_watch">Product Watch</option>
                                        <option value="laws_labeling">Laws & Labeling</option>
                                        <option value="comparison">Comparisons</option>
                                        <option value="restaurants_travel">Restaurants & Travel</option>
                                        <option value="gadgets_tools">Gadgets & Tools</option>
                                        <option value="apps_digital">Apps & Digital Tools</option>
                                        <option value="organization_life">Organization & Life</option>
                                        <option value="recipe_experiments">Recipe Experiments</option>
                                        <option value="science_health">Science & Health</option>
                                        <option value="community_questions">Community Questions</option>
                                    </select>
                                    <select id="studio-idea-count">
                                        <option value="1">1 idea</option>
                                        <option value="3" selected>3 ideas</option>
                                        <option value="5">5 ideas</option>
                                        <option value="8">8 ideas</option>
                                    </select>
                                </div>
                                <input id="studio-topic-hint" placeholder="Optional narrowing hint, e.g. Costco snacks, scanner apps, shared kitchen">
                                <div class="studio-checks">
                                    <label><input type="checkbox" id="studio-sample"> No-token sample mode</label>
                                </div>
                                <button class="btn btn-approve" id="btn-studio-generate" onclick="generateStudioIdeas()">
                                    <span class="spinner"></span>Generate Lane Ideas
                                </button>
                            </div>
                        </div>

                        <div class="studio-panel">
                            <h3>Latest Ideas for Selected Lane</h3>
                            <p>Newest ideas are shown first. Choose which assets to generate from each idea.</p>
                            <div id="studio-ideas-list" class="studio-list"><div class="empty">Select a lane and generate or refresh ideas.</div></div>
                        </div>
                    </div>

                    <div class="studio-stack">
                        <div class="studio-panel">
                            <h3>Website Content</h3>
                            <p>Generated blogs live here. Publish these to the website separately from Pinterest.</p>
                            <div id="studio-website-list" class="studio-list"><div class="empty">Loading website content...</div></div>
                        </div>

                        <div class="studio-panel">
                            <h3>Pinterest Content</h3>
                            <p>Generated pin images, titles, and descriptions live here. Post or copy manually.</p>
                            <div id="studio-pinterest-list" class="studio-list"><div class="empty">Loading Pinterest content...</div></div>
                        </div>

                        <div class="studio-panel">
                            <h3>Email Newsletter Text</h3>
                            <p>Newsletter drafts are text-only and ready to copy after review.</p>
                            <div id="studio-newsletter-list" class="studio-list"><div class="empty">Loading newsletter drafts...</div></div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- EDITORIAL LAB TAB -->
            <div id="tab-editorial" class="tab-content">
                <div class="section-header">
                    <p class="section-title">Editorial Lab: Sources, Research Drafts, and Review</p>
                    <button class="btn btn-trigger" onclick="fetchEditorialLab()">Refresh</button>
                </div>
                <div class="lab-grid">
                    <div class="lab-panel">
                        <h3>Propose a Source for Approval</h3>
                        <p>Add a source as pending approval. This lets you test the notification and approval gate before the source is used automatically.</p>
                        <div class="lab-form">
                            <input id="source-name" placeholder="Source name, e.g. Trader Joe's GF page">
                            <input id="source-url" placeholder="Base URL, e.g. https://www.traderjoes.com/home/products">
                            <div class="lab-row">
                                <select id="source-lane">
                                    <option value="product_watch">Product Watch</option>
                                    <option value="laws_labeling">Laws & Labeling</option>
                                    <option value="comparison">Bread Wars / Comparisons</option>
                                    <option value="restaurants_travel">Restaurant & Travel Buzz</option>
                                    <option value="gadgets_tools">Kitchen Gadget Lab</option>
                                    <option value="apps_digital">Apps & Digital Tools</option>
                                    <option value="organization_life">Organization & Real Life Systems</option>
                                    <option value="recipe_experiments">Recipe Experiments</option>
                                    <option value="science_health">Science Without Being Boring</option>
                                    <option value="community_questions">Community Drama / Real Questions</option>
                                </select>
                                <select id="source-type">
                                    <option value="brand_product_page">Brand/Product Page</option>
                                    <option value="retailer_product_page">Retailer Product Page</option>
                                    <option value="restaurant_allergen_page">Restaurant Allergen Page</option>
                                    <option value="official_recall_page">Official Recall Page</option>
                                    <option value="official_api">Official API</option>
                                    <option value="certification_body">Certification Body</option>
                                    <option value="medical_research">Medical Research</option>
                                    <option value="app_review_page">App Review Page</option>
                                    <option value="tool_product_page">Tool Product Page</option>
                                    <option value="community_discussion">Community Discussion</option>
                                </select>
                            </div>
                            <textarea id="source-notes" placeholder="Why this source matters, what to monitor, or what claims it can verify"></textarea>
                            <button class="btn btn-approve" id="btn-source-propose" onclick="proposeEditorialSource()">Propose Source</button>
                        </div>

                        <div class="section-divider">
                            <h3>Pending Source Notifications</h3>
                            <p>Approve trusted sources before they can be used automatically.</p>
                        </div>
                        <div id="source-notifications-list" class="lab-list"><div class="empty">Loading source notifications...</div></div>

                        <div class="section-divider">
                            <h3>Approved Sources</h3>
                            <p>These are eligible for automatic research and scheduling workflows.</p>
                        </div>
                        <div id="approved-sources-list" class="lab-list"><div class="empty">Loading approved sources...</div></div>
                    </div>

                    <div class="lab-panel">
                        <h3>Generate Full Blog Preview</h3>
                        <p>Pick a topic lane and generate a complete blog using the live blog template, improved planner section, readable typography, and relevant Amazon product block. Nothing is published or scheduled.</p>
                        <div class="lab-form">
                            <div class="lab-row">
                                <select id="blog-preview-lane">
                                    <option value="product_watch">Product Watch</option>
                                    <option value="laws_labeling">Laws & Labeling</option>
                                    <option value="comparison">Bread Wars / Comparisons</option>
                                    <option value="restaurants_travel">Restaurant & Travel Buzz</option>
                                    <option value="gadgets_tools">Kitchen Gadget Lab</option>
                                    <option value="apps_digital">Apps & Digital Tools</option>
                                    <option value="organization_life">Organization & Real Life Systems</option>
                                    <option value="recipe_experiments">Recipe Experiments</option>
                                    <option value="science_health">Science Without Being Boring</option>
                                    <option value="community_questions">Community Drama / Real Questions</option>
                                </select>
                                <button class="btn btn-approve" id="btn-blog-preview" onclick="generateBlogPreview()">
                                    <span class="spinner"></span>Generate Blog Preview
                                </button>
                            </div>
                            <input id="blog-preview-topic" placeholder="Optional custom topic. Leave blank to use a lane-specific test topic.">
                            <textarea id="blog-preview-description" placeholder="Optional topic description or angle. Leave blank for a default lane description."></textarea>
                            <button class="btn btn-trigger" id="btn-blog-sample" onclick="generateBlogPreview(true)">Generate Sample Preview (No Tokens)</button>
                        </div>
                        <div id="blog-preview-result" class="lab-list"></div>

                        <div class="section-divider">
                            <h3>Amazon Matcher</h3>
                            <p>Check product relevance without spending tokens.</p>
                        </div>
                        <h3>Test Amazon Product Match</h3>
                        <p>Check which approved affordable product would be inserted into a blog for a topic, before generating the full article.</p>
                        <div class="lab-form">
                            <input id="amazon-topic" placeholder="Blog topic, e.g. gluten-free road trip snack kit">
                            <div class="lab-row">
                                <select id="amazon-lane">
                                    <option value="product_watch">Product Watch</option>
                                    <option value="restaurants_travel">Restaurant & Travel Buzz</option>
                                    <option value="organization_life">Organization & Real Life Systems</option>
                                    <option value="gadgets_tools">Kitchen Gadget Lab</option>
                                    <option value="recipe_experiments">Recipe Experiments</option>
                                    <option value="comparison">Bread Wars / Comparisons</option>
                                    <option value="science_health">Science Without Being Boring</option>
                                </select>
                                <button class="btn btn-trigger" id="btn-amazon-match" onclick="testAmazonMatch()">Match Product</button>
                            </div>
                        </div>
                        <div id="amazon-match-result" class="lab-list"></div>

                        <div class="section-divider">
                            <h3>Draft Generator</h3>
                            <p>Create a source-backed content draft for review.</p>
                        </div>
                        <h3>Generate a Research-Backed Draft</h3>
                        <p>Create a reusable draft for blog, newsletter, Pinterest, or the future app from the same source-backed brief.</p>
                        <div class="lab-form">
                            <input id="draft-topic" placeholder="Topic, e.g. best gluten-free lunch boxes for school">
                            <div class="lab-row">
                                <select id="draft-lane">
                                    <option value="product_watch">Product Watch</option>
                                    <option value="laws_labeling">Laws & Labeling</option>
                                    <option value="comparison">Bread Wars / Comparisons</option>
                                    <option value="restaurants_travel">Restaurant & Travel Buzz</option>
                                    <option value="gadgets_tools">Kitchen Gadget Lab</option>
                                    <option value="apps_digital">Apps & Digital Tools</option>
                                    <option value="organization_life">Organization & Real Life Systems</option>
                                    <option value="recipe_experiments">Recipe Experiments</option>
                                    <option value="science_health">Science Without Being Boring</option>
                                    <option value="community_questions">Community Drama / Real Questions</option>
                                </select>
                                <select id="draft-platform">
                                    <option value="blog">Blog</option>
                                    <option value="newsletter">Newsletter</option>
                                    <option value="pinterest">Pinterest</option>
                                    <option value="app">Future App</option>
                                </select>
                            </div>
                            <input id="draft-angle" placeholder="Optional angle, e.g. practical comparison, buyer guide, myth-busting">
                            <button class="btn btn-approve" id="btn-draft-generate" onclick="generateEditorialDraft()">
                                <span class="spinner"></span>Generate Draft
                            </button>
                        </div>

                        <div class="section-divider">
                            <h3>Draft Review Queue</h3>
                            <p>Approve good drafts, reject weak ones, and inspect the sources used.</p>
                        </div>
                        <div id="content-drafts-list" class="lab-list"><div class="empty">Loading content drafts...</div></div>
                    </div>
                </div>
            </div>
        </main>

        <!-- Generate Content Modal -->
        <div class="modal-overlay" id="gen-modal">
            <div class="modal">
                <h2>Generate Custom Content</h2>
                <p style="font-size:.87rem;color:#666;margin-bottom:14px">Generate a blog + pin package for a topic. Added silently to Pending Review.</p>
                <select id="gen-topic">
                    <option value="Educational">Educational (Know Your Ingredients)</option>
                    <option value="Practical Guide">Practical Guide (Tips &amp; Tricks)</option>
                    <option value="Lifestyle">Lifestyle (Living Gluten-Free)</option>
                    <option value="Health &amp; Wellness">Health &amp; Wellness (Healthy Living)</option>
                </select>
                <div class="actions">
                    <button class="btn-close" onclick="closeGenModal()">Cancel</button>
                    <button class="btn btn-approve" id="btn-gen-submit" onclick="submitGenerate()">
                        <span class="spinner"></span> Generate
                    </button>
                </div>
            </div>
        </div>

        <!-- Recipe Idea Modal -->
        <div class="modal-overlay" id="recipe-idea-modal">
            <div class="modal" style="max-width:520px">
                <h2>Generate Recipe Title Ideas</h2>
                <p style="font-size:.87rem;color:#666;margin-bottom:14px">Choose a category or type a dish to make gluten-free. This creates title ideas only; full recipes and images wait for approval.</p>
                <label style="display:block;font-size:.78rem;font-weight:700;color:#58616d;margin-bottom:6px">Category</label>
                <select id="recipe-idea-category">
                    <option value="">Choose a category...</option>
                    <option value="Bake / Make It Yourself">Bake / Make It Yourself</option>
                    <option value="Breakfasts That Fuel Your Day">Breakfasts That Fuel Your Day</option>
                    <option value="Comfort Food Classics (Made Gluten-Free)">Comfort Food Classics (Made Gluten-Free)</option>
                    <option value="Desserts & Baked Treats">Desserts & Baked Treats</option>
                    <option value="Meal Prep & Freezer-Friendly Recipes">Meal Prep & Freezer-Friendly Recipes</option>
                    <option value="Quick & Easy Weeknight Dinners">Quick & Easy Weeknight Dinners</option>
                </select>
                <label style="display:block;font-size:.78rem;font-weight:700;color:#58616d;margin-bottom:6px">Or type a dish to make gluten-free</label>
                <textarea id="recipe-idea-dish" placeholder="Example: sourdough sandwich bread, cinnamon rolls, chicken pot pie, croissants"></textarea>
                <p style="font-size:.78rem;color:#777;margin:-4px 0 14px">If you fill both, the typed dish wins and the system infers the best category.</p>
                <div class="actions">
                    <button class="btn-close" onclick="closeRecipeIdeaModal()">Cancel</button>
                    <button class="btn btn-approve" id="btn-recipe-idea-submit" onclick="submitRecipeIdeaGeneration()">
                        <span class="spinner"></span> Suggest Titles
                    </button>
                </div>
            </div>
        </div>

        <!-- Detail Review Modal -->
        <div class="detail-overlay" id="detail-overlay">
            <div class="detail-modal">
                <div class="detail-header">
                    <div class="detail-title" id="detail-title">Details</div>
                    <button class="btn-close" onclick="closeDetailModal()">Close</button>
                </div>
                <div class="detail-body" id="detail-body"></div>
                <div class="detail-actions" id="detail-actions"></div>
            </div>
        </div>

        <!-- Amazon Product Modal -->
        <div class="detail-overlay" id="product-overlay">
            <div class="detail-modal" style="width:min(760px,96vw)">
                <div class="detail-header">
                    <div class="detail-title" id="product-modal-title">Amazon Product</div>
                    <button class="btn-close" onclick="closeProductModal()">Close</button>
                </div>
                <div class="detail-body">
                    <input type="hidden" id="product-id">
                    <div class="form-grid">
                        <input id="product-title" class="wide" placeholder="Product title">
                        <textarea id="product-description" class="wide" placeholder="Short product description"></textarea>
                        <input id="product-url" class="wide" placeholder="Amazon/product URL">
                        <input id="product-image-url" class="wide" placeholder="Image URL (optional; dashboard will flag missing images)">
                        <input id="product-keywords" placeholder="Keywords, comma separated">
                        <input id="product-lanes" placeholder="Content lanes, comma separated">
                        <input id="product-price-tier" placeholder="Price tier" value="affordable">
                        <input id="product-priority" type="number" min="0" step="0.1" placeholder="Priority score" value="1">
                        <label class="wide" style="font-size:.84rem;color:#46505a;display:flex;gap:8px;align-items:center">
                            <input id="product-active" type="checkbox" checked> Active in product matching
                        </label>
                    </div>
                </div>
                <div class="detail-actions">
                    <button class="btn btn-close" onclick="closeProductModal()">Cancel</button>
                    <button class="btn btn-approve" onclick="saveAmazonProduct()">Save Product</button>
                </div>
            </div>
        </div>

        <script>
        // ── Sandbox mode: fetch config and show banner ──
        let _sandboxMode = false;
        (async function initConfig() {
            try {
                const cfg = await fetch('/api/config').then(r => r.json());
                _sandboxMode = cfg.sandbox_mode;
                if (_sandboxMode) {
                    document.getElementById('sandbox-banner').classList.add('visible');
                    console.info('[EGF] SANDBOX MODE active — Pinterest calls go to api-sandbox.pinterest.com');
                }
            } catch(e) { /* ignore */ }
        })();

        // ── Tab navigation ──
        function showTab(id, el) {
            document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.getElementById(id).classList.add('active');
            el.classList.add('active');
            if (id === 'tab-approved-blogs') fetchApprovedBlogs();
            else if (id === 'tab-approved-pins') fetchApprovedPins();
            else if (id === 'tab-approved-newsletters') fetchApprovedNewsletters();
            else if (id === 'tab-amazon') fetchAmazonProducts();
            else if (id === 'tab-knowledge') fetchKnowledgeDb();
            else if (id === 'tab-recipes') fetchRecipes();
            else if (id === 'tab-trends') fetchTrends();
            else if (id === 'tab-studio') fetchContentStudio();
            else if (id === 'tab-editorial') fetchEditorialLab();
            else fetchPendingReview();
        }

        // ── Generate Content Modal ──
        function openGenModal() { document.getElementById('gen-modal').style.display = 'flex'; }
        function closeGenModal() { document.getElementById('gen-modal').style.display = 'none'; }
        async function submitGenerate() {
            const topic = document.getElementById('gen-topic').value;
            const btn = document.getElementById('btn-gen-submit');
            btn.classList.add('loading'); btn.disabled = true;
            try {
                const res = await fetch('/api/generate_custom', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({topic_type:topic})});
                const data = await res.json();
                if (data.success) { alert('Done! Check Pending Review.'); closeGenModal(); fetchPendingReview(); }
                else alert('Failed: ' + data.error);
            } catch(e) { alert('Error: ' + e); }
            btn.classList.remove('loading'); btn.disabled = false;
        }

        // Review dashboard
        async function fetchPendingReview() {
            await Promise.all([fetchPendingBlogs(), fetchPins(), fetchPendingNewsletters()]);
        }

        async function fetchPendingBlogs() {
            const list = document.getElementById('pending-blogs-container');
            try {
                const blogs = await (await fetch('/api/blogs?status=pending')).json();
                if (!blogs.length) { list.innerHTML = '<div class="empty">No pending blogs.</div>'; return; }
                list.innerHTML = blogs.map(blog => buildBlogCard(blog, true)).join('');
            } catch(e) {
                list.innerHTML = `<div class="empty">Could not load blogs: ${esc(e)}</div>`;
            }
        }

        async function fetchPins() {
            const list = document.getElementById('pins-container');
            try {
                const pins = await (await fetch('/api/pins?status=pending')).json();
                if (!pins.length) { list.innerHTML = '<div class="empty">No pending pins.</div>'; return; }
                list.innerHTML = pins.map(pin => buildPinCard(pin, true)).join('');
            } catch(e) {
                list.innerHTML = `<div class="empty">Could not load pins: ${esc(e)}</div>`;
            }
        }

        async function fetchPendingNewsletters() {
            const list = document.getElementById('pending-newsletters-container');
            try {
                const newsletters = await (await fetch('/api/newsletters?status=pending')).json();
                if (!newsletters.length) { list.innerHTML = '<div class="empty">No pending emails.</div>'; return; }
                list.innerHTML = newsletters.map(item => buildNewsletterCard(item, true)).join('');
            } catch(e) {
                list.innerHTML = `<div class="empty">Could not load emails: ${esc(e)}</div>`;
            }
        }

        function buildBlogCard(blog, pending=false) {
            const image = blog.image_url ? `<img class="asset-thumb" src="${esc(blog.image_url)}" loading="lazy">` : '<div class="asset-thumb"></div>';
            const actions = pending
                ? `<button class="btn btn-approve btn-small" onclick="event.stopPropagation();openBlogDetail(${blog.blog_id}, true)">Read & Review</button>
                   <button class="btn btn-danger btn-small" onclick="event.stopPropagation();rejectBlog(${blog.blog_id})">Reject</button>`
                : `<button class="btn btn-wp btn-small" onclick="event.stopPropagation();publishWebsiteAsset(${blog.blog_id}, this)" ${blog.wp_url ? 'disabled' : ''}>${blog.wp_url ? 'Published' : 'Publish'}</button>
                   <button class="btn btn-danger btn-small" onclick="event.stopPropagation();deleteBlog(${blog.blog_id})">Delete</button>`;
            return `<div class="asset-card" onclick="openBlogDetail(${blog.blog_id}, ${pending})">
                ${image}
                <div class="asset-card-body">
                    <div class="asset-title">${esc(blog.title)}</div>
                    <div class="asset-copy">${esc(blog.pin_description || blog.category || '')}</div>
                    <div class="lab-meta">
                        <span class="lab-chip ${blog.status === 'approved' ? 'approved' : 'pending'}">${esc(blog.status)}</span>
                        ${blog.product_title ? `<span class="lab-chip">${esc(blog.product_title)}</span>` : ''}
                    </div>
                </div>
                <div class="asset-actions">${actions}</div>
            </div>`;
        }

        function buildPinCard(pin, pending=false) {
            const image = pin.image_url ? `<img class="asset-thumb pin" src="${esc(pin.image_url)}" loading="lazy">` : '<div class="asset-thumb pin"></div>';
            const posted = pin.pinterest_id || pin.status === 'posted' || pin.status === 'published';
            const actions = pending
                ? `<button class="btn btn-approve btn-small" onclick="event.stopPropagation();openPinDetail(${pin.pin_id}, true)">Review Pin</button>
                   <button class="btn btn-danger btn-small" onclick="event.stopPropagation();rejectPin(${pin.pin_id})">Reject</button>`
                : `<button class="btn btn-pin btn-small" onclick="event.stopPropagation();postPinterestAsset(${pin.pin_id}, this)" ${posted ? 'disabled' : ''}>${posted ? 'Posted' : 'Post'}</button>
                   <button class="btn btn-copy btn-small" onclick="event.stopPropagation();copyPinText(${pin.pin_id})">Copy Text</button>`;
            return `<div class="asset-card" onclick="openPinDetail(${pin.pin_id}, ${pending})">
                ${image}
                <div class="asset-card-body">
                    <div class="asset-title">${esc(pin.title)}</div>
                    <div class="asset-copy">${esc(pin.description || '')}</div>
                    <div class="lab-meta">
                        <span class="lab-chip ${posted ? 'approved' : (pin.status === 'approved' ? 'approved' : 'pending')}">${posted ? 'posted' : esc(pin.status)}</span>
                        ${pin.content_lane ? `<span class="lab-chip">${esc(pin.content_lane)}</span>` : ''}
                    </div>
                </div>
                <div class="asset-actions">${actions}</div>
            </div>`;
        }

        function buildNewsletterCard(item, pending=false) {
            const actions = pending
                ? `<button class="btn btn-approve btn-small" onclick="event.stopPropagation();openNewsletterDetail(${item.draft_id}, true)">Read & Review</button>
                   <button class="btn btn-danger btn-small" onclick="event.stopPropagation();rejectNewsletter(${item.draft_id})">Reject</button>`
                : `<button class="btn btn-copy btn-small" onclick="event.stopPropagation();copyNewsletterText(${item.draft_id})">Copy Email Text</button>`;
            return `<div class="asset-card" onclick="openNewsletterDetail(${item.draft_id}, ${pending})">
                <div class="asset-card-body">
                    <div class="asset-title">${esc(item.title)}</div>
                    <div class="asset-copy">${esc(item.dek || item.topic_title || '')}</div>
                    <div class="lab-meta">
                        <span class="lab-chip ${item.status === 'approved' ? 'approved' : 'pending'}">${esc(item.status)}</span>
                        <span class="lab-chip">${esc(item.lane || '')}</span>
                    </div>
                </div>
                <div class="asset-actions">${actions}</div>
            </div>`;
        }

        function checkEmpty(cid, html) { const c=document.getElementById(cid); if(c&&!c.querySelector('.pin-card,.recipe-card,.asset-card')) c.innerHTML=html; }

        function openDetailModal(title, bodyHtml, actionsHtml='') {
            document.getElementById('detail-title').textContent = title;
            document.getElementById('detail-body').innerHTML = bodyHtml;
            document.getElementById('detail-actions').innerHTML = actionsHtml;
            document.getElementById('detail-overlay').classList.add('active');
        }

        function closeDetailModal() {
            document.getElementById('detail-overlay').classList.remove('active');
            document.getElementById('detail-body').innerHTML = '';
            document.getElementById('detail-actions').innerHTML = '';
        }

        function safetyGate(kind, approveCall) {
            return `<div class="safety-box">
                <label><input type="checkbox" id="safety-check" onchange="document.getElementById('detail-approve-btn').disabled=!this.checked">
                I reviewed the full ${kind} and confirm the image is modest and appropriate.</label>
            </div>
            <button class="btn btn-approve" id="detail-approve-btn" disabled onclick="${approveCall}">Accept</button>`;
        }

        async function openBlogDetail(blogId, pending=false) {
            const data = await (await fetch(`/api/blogs/${blogId}`)).json();
            if (!data.success) { alert(data.error || 'Could not load blog.'); return; }
            const b = data.blog;
            const image = b.image_url ? `<img class="detail-image" src="${esc(b.image_url)}" alt="">` : '<div class="safety-box">No linked image found for this blog.</div>';
            const body = `${image}<iframe class="blog-frame" id="blog-frame-preview"></iframe>`;
            const actions = pending
                ? `${safetyGate('blog article and linked image', `approveBlog(${blogId})`)}
                   <button class="btn btn-reject" onclick="rejectBlog(${blogId})">Reject</button>`
                : `<button class="btn btn-wp" onclick="publishWebsiteAsset(${blogId}, this)" ${b.wp_url ? 'disabled' : ''}>${b.wp_url ? 'Published' : 'Publish to Website'}</button>
                   ${b.wp_url ? `<a class="btn btn-copy" href="${esc(b.wp_url)}" target="_blank" rel="noopener" style="text-decoration:none;text-align:center">Open Published Post</a>` : ''}
                   <button class="btn btn-danger" onclick="deleteBlog(${blogId})">Delete Blog</button>`;
            openDetailModal(b.title || 'Blog', body, actions);
            document.getElementById('blog-frame-preview').srcdoc = b.html_content || '<p>No blog content found.</p>';
        }

        async function openPinDetail(pinId, pending=false) {
            const data = await (await fetch(`/api/pins/${pinId}`)).json();
            if (!data.success) { alert(data.error || 'Could not load pin.'); return; }
            const p = data.pin;
            const image = p.image_url ? `<img class="detail-image" src="${esc(p.image_url)}" alt="">` : '<div class="safety-box">No pin image found.</div>';
            const body = `${image}
                <div class="draft-section"><strong>Caption</strong>${esc(p.description || '')}</div>
                <div class="draft-section"><strong>Keywords</strong>${esc(p.seo_keywords || 'N/A')}</div>
                <div class="draft-section"><strong>Destination</strong>${p.destination_url ? `<a href="${esc(p.destination_url)}" target="_blank" rel="noopener">${esc(p.destination_url)}</a>` : 'No destination URL yet.'}</div>
                ${p.blog_id ? `<div class="draft-section"><strong>Linked blog</strong>${esc(p.blog_title || '')}</div>` : ''}`;
            const actions = pending
                ? `${safetyGate('pin image and caption', `approvePin(${pinId})`)}
                   <button class="btn btn-reject" onclick="rejectPin(${pinId})">Reject</button>`
                : `<button class="btn btn-pin" onclick="postPinterestAsset(${pinId}, this)" ${p.pinterest_id ? 'disabled' : ''}>${p.pinterest_id ? 'Posted' : 'Post to Pinterest'}</button>
                   <button class="btn btn-copy" onclick="copyPinText(${pinId})">Copy Text</button>
                   ${p.image_url ? `<button class="btn btn-copy" onclick="copyPinImage('${esc(p.image_url)}')">Copy Image</button>` : ''}`;
            openDetailModal(p.title || 'Pin', body, actions);
        }

        function newsletterHtml(draft) {
            let content = {};
            let sources = [];
            try { content = JSON.parse(draft.content_json || '{}'); } catch(_) {}
            try { sources = JSON.parse(draft.source_urls_json || '[]'); } catch(_) {}
            const sections = (content.sections || []).map(section => `
                <div class="draft-section"><strong>${esc(section.heading || 'Section')}</strong>${esc(section.body || '')}</div>
            `).join('');
            const sourceLinks = sources.map(url => `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(url)}</a>`).join('');
            return `<div class="draft-dek">${esc(draft.dek || '')}</div>
                ${sections || `<div class="draft-section">${esc(draft.topic_title || '')}</div>`}
                ${content.call_to_action ? `<div class="draft-section"><strong>CTA</strong>${esc(content.call_to_action)}</div>` : ''}
                ${sourceLinks ? `<div class="source-links"><strong>Sources</strong>${sourceLinks}</div>` : ''}`;
        }

        async function openNewsletterDetail(draftId, pending=false) {
            const data = await (await fetch(`/api/newsletters/${draftId}`)).json();
            if (!data.success) { alert(data.error || 'Could not load email.'); return; }
            const n = data.newsletter;
            const actions = pending
                ? `<button class="btn btn-approve" onclick="approveNewsletter(${draftId})">Accept</button>
                   <button class="btn btn-reject" onclick="rejectNewsletter(${draftId})">Reject</button>`
                : `<button class="btn btn-copy" onclick="copyNewsletterText(${draftId})">Copy Email Text</button>`;
            openDetailModal(n.title || 'Newsletter Email', newsletterHtml(n), actions);
        }

        async function approveBlog(id) {
            const data = await (await fetch(`/api/blogs/${id}/approve`, {method:'POST'})).json();
            if (data.success) { closeDetailModal(); await fetchPendingBlogs(); await fetchApprovedBlogs(); }
            else alert(data.error || 'Could not approve blog.');
        }

        async function rejectBlog(id) {
            if (!confirm('Reject this blog?')) return;
            const data = await (await fetch(`/api/blogs/${id}/reject`, {method:'POST'})).json();
            if (data.success) { closeDetailModal(); fetchPendingBlogs(); }
            else alert(data.error || 'Could not reject blog.');
        }

        async function deleteBlog(id) {
            if (!confirm('Delete this blog from the dashboard? This is a soft delete and will cancel pending queue rows.')) return;
            const data = await (await fetch(`/api/blogs/${id}`, {method:'DELETE'})).json();
            if (data.success) { closeDetailModal(); await fetchApprovedBlogs(); await fetchPendingBlogs(); }
            else alert(data.error || 'Could not delete blog.');
        }

        async function approvePin(id) {
            const data = await (await fetch(`/api/pins/${id}/approve`,{method:'POST'})).json();
            if (data.success) { closeDetailModal(); await fetchPins(); await fetchApprovedPins(); }
            else alert(data.error || 'Could not approve pin.');
        }

        async function rejectPin(id) {
            const reason = prompt('Rejection reason (optional):') || '';
            const data = await (await fetch(`/api/pins/${id}/reject`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason})})).json();
            if (data.success) { closeDetailModal(); fetchPins(); }
            else alert(data.error || 'Could not reject pin.');
        }

        async function approveNewsletter(id) {
            const data = await (await fetch(`/api/newsletters/${id}/approve`, {method:'POST'})).json();
            if (data.success) { closeDetailModal(); await fetchPendingNewsletters(); await fetchApprovedNewsletters(); }
            else alert(data.error || 'Could not approve email.');
        }

        async function rejectNewsletter(id) {
            const reason = prompt('Rejection reason (optional):') || '';
            const data = await (await fetch(`/api/newsletters/${id}/reject`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason})})).json();
            if (data.success) { closeDetailModal(); fetchPendingNewsletters(); }
            else alert(data.error || 'Could not reject email.');
        }

        async function fetchApprovedBlogs() {
            const list = document.getElementById('approved-blogs-container');
            const blogs = await (await fetch('/api/blogs?status=approved')).json();
            list.innerHTML = blogs.length ? blogs.map(blog => buildBlogCard(blog, false)).join('') : '<div class="empty">No approved blogs yet.</div>';
        }

        async function fetchApprovedPins() {
            const list = document.getElementById('approved-pins-container');
            const pins = await (await fetch('/api/pins?status=approved')).json();
            list.innerHTML = pins.length ? pins.map(pin => buildPinCard(pin, false)).join('') : '<div class="empty">No approved pins yet.</div>';
        }

        async function fetchApprovedNewsletters() {
            const list = document.getElementById('approved-newsletters-container');
            const newsletters = await (await fetch('/api/newsletters?status=approved')).json();
            list.innerHTML = newsletters.length ? newsletters.map(item => buildNewsletterCard(item, false)).join('') : '<div class="empty">No approved newsletter emails yet.</div>';
        }

        // ── Schedule ──
        async function fetchSchedule() {
            const rows = await (await fetch('/api/schedule')).json();
            const tbody = document.getElementById('schedule-body');
            if (!rows.length) { tbody.innerHTML='<tr><td colspan="6" style="text-align:center;padding:28px;color:#aaa">No scheduled publishes yet.</td></tr>'; return; }
            tbody.innerHTML = rows.map((r,i) => {
                const estTime = new Date(r.scheduled_time).toLocaleString('en-US',{timeZone:'America/New_York',dateStyle:'medium',timeStyle:'short'});
                const statusCls = `status-${r.status}`;
                let link = r.wp_url ? `<a href="${r.wp_url}" target="_blank" style="color:#27ae60;font-weight:600">View Post</a>` : (r.blog_title ? esc(r.blog_title) : '-');
                const err = r.error_message ? `<span class="error-text" title="${r.error_message}">${r.error_message}</span>` : '';
                const actions = (r.status==='pending'||r.status==='failed')
                    ? `<button class="btn btn-publish" onclick="initiatePostNow(${r.pin_id},this)"><span class="spinner"></span>Post Now</button>
                       <button class="btn btn-danger btn-small" onclick="cancelSchedule(${r.schedule_id})">Cancel</button>`
                    : '';
                return `<tr><td>${i+1}</td><td>${r.pin_title}</td><td>${estTime}</td>
                    <td><span class="status-badge ${statusCls}">${r.status}</span>${err}</td>
                    <td>${link}</td><td class="action-col">${actions}</td></tr>`;
            }).join('');
        }
        async function cancelSchedule(scheduleId) {
            if (!confirm('Cancel this queue item? The content will stay available on its approved page.')) return;
            const data = await (await fetch(`/api/schedule/${scheduleId}`, {method:'DELETE'})).json();
            if (data.success) fetchSchedule();
            else alert(data.error || 'Could not cancel queue item.');
        }
        async function triggerPublishRunner() {
            const btn = document.getElementById('btn-run-publish');
            if (!confirm('Run the publish runner now?')) return;
            btn.classList.add('loading'); btn.disabled=true;
            try {
                const data = await (await fetch('/api/publish/run',{method:'POST'})).json();
                if (data.success) { alert(data.message); fetchSchedule(); }
                else alert('Error: '+(data.error||'Unknown'));
            } catch(e) { alert('Failed: '+e); }
            btn.classList.remove('loading'); btn.disabled=false;
        }
        async function initiatePostNow(pin_id, btnEl) {
            if (!confirm('Publish this pin immediately? Pinterest authorization will open.')) return;
            btnEl.classList.add('loading'); btnEl.disabled=true;
            try {
                const res = await fetch('/api/oauth/start');
                const data = await res.json();
                if (!data.auth_url) throw new Error(data.error||'No auth URL');
                const popup = window.open(data.auth_url,'pinterest_oauth','width=620,height=720,left=200,top=100');
                if (!popup) { alert('Popup blocked. Allow popups and retry.'); btnEl.classList.remove('loading'); btnEl.disabled=false; return; }
                const poll = setInterval(async () => {
                    try {
                        const s = await (await fetch('/api/oauth/status')).json();
                        if (!s.done) return;
                        clearInterval(poll);
                        if (popup && !popup.closed) popup.close();
                        if (!s.success) { alert('Pinterest auth failed: '+(s.error||'Unknown')); btnEl.classList.remove('loading'); btnEl.disabled=false; return; }
                        await postNow(pin_id, btnEl);
                    } catch(_) {}
                }, 800);
            } catch(e) { alert('OAuth start failed: '+e); btnEl.classList.remove('loading'); btnEl.disabled=false; }
        }
        async function postNow(pin_id, btnEl) {
            try {
                const data = await (await fetch(`/api/publish/now/${pin_id}`,{method:'POST'})).json();
                if (data.success) { alert(data.message); fetchSchedule(); }
                else { alert('Error: '+data.error); btnEl.classList.remove('loading'); btnEl.disabled=false; }
            } catch(e) { alert('Request failed: '+e); btnEl.classList.remove('loading'); btnEl.disabled=false; }
        }

        // ─────────────────────────────────────────────────────
        // ── Recipe Generation (Async) ──
        // ─────────────────────────────────────────────────────
        let _recipeTaskId = null;
        let _recipePollInterval = null;
        let _progressVal = 0;
        const LOADING_STEPS = [
            "Consulting Claire\u2019s recipe notebook\u2026",
            'Picking the perfect category…',
            'Writing ingredients & instructions…',
            'Generating cover image…',
            'Generating step photos…',
            'Almost there — finishing touches…'
        ];
        let _stepIdx = 0;
        let _stepInterval = null;

        function openRecipeIdeaModal() {
            document.getElementById('recipe-idea-category').value = '';
            document.getElementById('recipe-idea-dish').value = '';
            document.getElementById('recipe-idea-modal').style.display = 'flex';
        }

        function closeRecipeIdeaModal() {
            document.getElementById('recipe-idea-modal').style.display = 'none';
        }

        async function submitRecipeIdeaGeneration() {
            const btn = document.getElementById('btn-recipe-idea-submit');
            const category = document.getElementById('recipe-idea-category').value;
            const dish = document.getElementById('recipe-idea-dish').value.trim();
            if (!category && !dish) {
                alert('Choose a category or type a dish to make gluten-free.');
                return;
            }
            btn.disabled = true;
            btn.classList.add('loading');
            try {
                const data = await (await fetch('/api/recipe-ideas/generate', {
                    method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body:JSON.stringify({category, dish_request:dish, limit:5})
                })).json();
                if (!data.success) {
                    alert('Could not generate recipe title ideas: ' + (data.error || 'Unknown error'));
                } else {
                    closeRecipeIdeaModal();
                    showTab('tab-recipes', document.getElementById('tabnav-recipes'));
                    await fetchRecipes();
                    alert(`Generated ${data.ideas.length} recipe title idea(s). Approve one to create the full recipe with images.`);
                }
            } catch(e) {
                alert('Recipe title idea generation failed: ' + e);
            }
            btn.disabled = false;
            btn.classList.remove('loading');
        }

        function startRecipeGenerationForIdea(ideaId) {
            const btn = document.getElementById('btn-gen-recipe');
            btn.disabled = true;
            // Show overlay
            document.getElementById('recipe-loading-overlay').classList.add('active');
            _progressVal = 0;
            _stepIdx = 0;
            document.getElementById('recipe-loading-steps').textContent = LOADING_STEPS[0];
            document.getElementById('recipe-progress-fill').style.width = '0%';
            // Animate progress + steps
            _stepInterval = setInterval(() => {
                _progressVal = Math.min(_progressVal + (100 / 42), 92);
                document.getElementById('recipe-progress-fill').style.width = _progressVal + '%';
                if (_stepIdx < LOADING_STEPS.length - 1) {
                    _stepIdx++;
                    document.getElementById('recipe-loading-steps').textContent = LOADING_STEPS[_stepIdx];
                }
            }, 5000);
            fetch(`/api/recipe-ideas/${ideaId}/approve-generate`, {method:'POST'})
                .then(r => r.json())
                .then(data => {
                    if (!data.success || !data.task_id) throw new Error(data.error || 'No task_id returned');
                    _recipeTaskId = data.task_id;
                    _recipePollInterval = setInterval(pollRecipeStatus, 2500);
                })
                .catch(e => { stopRecipeLoading(); alert('Failed to start full recipe generation: ' + e); btn.disabled = false; });
        }

        async function pollRecipeStatus() {
            try {
                const data = await (await fetch(`/api/recipe/generate/status/${_recipeTaskId}`)).json();
                if (data.status === 'running') return;
                clearInterval(_recipePollInterval);
                stopRecipeLoading();
                document.getElementById('btn-gen-recipe').disabled = false;
                if (data.status === 'done') {
                    // Switch to recipes tab and refresh
                    showTab('tab-recipes', document.getElementById('tabnav-recipes'));
                    fetchRecipes();
                    fetchRecipeIdeas();
                } else {
                    alert('Recipe generation failed: ' + (data.error || 'Unknown error. Check server logs.'));
                }
            } catch(_) { /* network blip */ }
        }

        function stopRecipeLoading() {
            clearInterval(_stepInterval);
            clearInterval(_recipePollInterval);
            document.getElementById('recipe-progress-fill').style.width = '100%';
            document.getElementById('recipe-loading-steps').textContent = 'Done!';
            setTimeout(() => {
                document.getElementById('recipe-loading-overlay').classList.remove('active');
                document.getElementById('recipe-progress-fill').style.width = '0%';
            }, 600);
        }

        // ── Recipe listing ──
        async function fetchRecipes() {
            await fetchRecipeIdeas();
            const all = await (await fetch('/api/recipes')).json();
            const pending  = all.filter(r => r.status === 'pending');
            const approved = all.filter(r => r.status === 'approved' || r.status === 'published');
            renderRecipes('recipes-pending-container',  pending,  true);
            renderRecipes('recipes-approved-container', approved, false);
        }

        async function fetchRecipeIdeas() {
            const container = document.getElementById('recipe-ideas-container');
            try {
                const ideas = await (await fetch('/api/recipe-ideas?status=pending_review&limit=30')).json();
                renderRecipeIdeas(ideas);
            } catch(e) {
                container.innerHTML = `<div class="empty">Could not load recipe title ideas: ${esc(e)}</div>`;
            }
        }

        function renderRecipeIdeas(ideas) {
            const container = document.getElementById('recipe-ideas-container');
            if (!ideas.length) {
                container.innerHTML = '<div class="empty">No recipe title ideas yet. Click "Generate Recipe" to suggest names first.</div>';
                return;
            }
            container.innerHTML = ideas.map(idea => {
                const mode = idea.mode === 'custom_dish' ? 'custom dish' : 'category';
                const warning = idea.duplicate_warning ? `<span class="recipe-idea-chip warn">${esc(idea.duplicate_warning)}</span>` : '';
                const dish = idea.dish_request ? `<div class="recipe-idea-copy"><strong>Dish request:</strong> ${esc(idea.dish_request)}</div>` : '';
                return `
                    <div class="recipe-idea-card" id="recipe-idea-${idea.idea_id}">
                        <div class="recipe-idea-title">${esc(idea.suggested_title)}</div>
                        <div class="recipe-idea-meta">
                            <span class="recipe-idea-chip">${esc(idea.category)}</span>
                            <span class="recipe-idea-chip">${esc(mode)}</span>
                            ${Number(idea.duplicate_score || 0) ? `<span class="recipe-idea-chip">similarity ${Number(idea.duplicate_score).toFixed(2)}</span>` : ''}
                            ${warning}
                        </div>
                        ${dish}
                        <div class="recipe-idea-copy">${esc(idea.rationale || '')}</div>
                        <div class="recipe-idea-actions">
                            <button class="btn-recipe-approve" onclick="approveRecipeIdea(${idea.idea_id}, this)">Approve & Generate Full Recipe</button>
                            <button class="btn-recipe-reject" onclick="rejectRecipeIdea(${idea.idea_id}, this)">Reject</button>
                        </div>
                    </div>
                `;
            }).join('');
        }

        async function approveRecipeIdea(ideaId, btn) {
            if (!confirm('Approve this recipe title and generate the full recipe with images?')) return;
            btn.disabled = true;
            startRecipeGenerationForIdea(ideaId);
        }

        async function rejectRecipeIdea(ideaId, btn) {
            if (!confirm('Reject this recipe title idea?')) return;
            btn.disabled = true;
            const data = await (await fetch(`/api/recipe-ideas/${ideaId}/reject`, {method:'POST'})).json();
            if (data.success) fetchRecipeIdeas();
            else {
                alert(data.error || 'Could not reject recipe idea.');
                btn.disabled = false;
            }
        }

        function imgFile(path) { return path ? path.split(/[\\\\/]/).pop() : null; }

        function renderRecipes(containerId, recipes, showApproveReject) {
            const container = document.getElementById(containerId);
            if (!recipes.length) {
                container.innerHTML = '<div class="empty">' + (showApproveReject ? 'No pending recipes. Click "Generate Recipe" to create one.' : 'No approved recipes yet.') + '</div>';
                return;
            }
            container.innerHTML = recipes.map(r => buildRecipeCard(r, showApproveReject)).join('');
        }

        function buildRecipeCard(r, showApproveReject) {
            const d = r.recipe_data || {};
            const cover = imgFile(r.cover_image);
            const pin = imgFile(r.pinterest_image);
            const s1 = imgFile(r.step_image_1), s2 = imgFile(r.step_image_2), s3 = imgFile(r.step_image_3);
            const difficulty = d.difficulty || '—';
            const prep = d.prep_time ? d.prep_time+'m' : '—';
            const cook = d.cook_time ? d.cook_time+'m' : '—';
            const servings = d.servings ? d.servings+' '+(d.servings_unit||'servings') : '—';
            const tags = (d.tags||[]).slice(0,4).map(t=>`<span style="background:#f0f0f0;padding:2px 7px;border-radius:10px;font-size:.72rem">${t}</span>`).join(' ');

            const wpBadge  = r.wp_url ? `<span class="recipe-pub-badge pub-wp">🌐 WP Published</span>` : '';
            const pinBadge = r.pinterest_id ? `<span class="recipe-pub-badge pub-pin">📌 Pinned</span>` : '';

            // Ingredient rows
            const ings = (d.ingredients||[]).map(ing =>
                `<li class="ing-item">
                    <span class="ing-amount">${ing.amount||''} ${ing.unit||''}</span>
                    <span class="ing-name">${ing.name||''}</span>
                    ${ing.notes ? `<span class="ing-notes">— ${ing.notes}</span>` : ''}
                </li>`
            ).join('');

            // Instruction steps
            const steps = (d.instructions||[]).map(ins =>
                `<div class="step-item">
                    <div class="step-num">${ins.step_number}</div>
                    <div class="step-text">${ins.text}</div>
                </div>`
            ).join('');

            // Step images
            const stepImgs = [s1,s2,s3].map((s,i) => s
                ? `<div class="step-img-wrap"><img src="/images/${s}" loading="lazy"><span class="step-img-label">Step ${i+1}</span></div>`
                : `<div class="step-img-wrap" style="background:#f0f0f0;display:flex;align-items:center;justify-content:center;color:#ccc;font-size:1.5rem">📷</div>`
            ).join('');

            // Action buttons
            let actionBtns = '';
            const exportBtns = `
                <button class="btn-recipe-download" onclick="downloadRecipeImages(${r.recipe_id})">Download Images</button>
                <button class="btn-recipe-json" onclick="downloadRecipeJson(${r.recipe_id})">WPRM JSON</button>`;
            if (showApproveReject) {
                actionBtns = `
                    <button class="btn-recipe-approve" onclick="approveRecipe(${r.recipe_id},this)">✓ Accept</button>
                    <button class="btn-recipe-reject"  onclick="rejectRecipe(${r.recipe_id},this)">✗ Reject</button>`;
            } else {
                const wpDisabled  = r.wp_url ? 'disabled' : '';
                const pinDisabled = (!r.wp_url || r.pinterest_id) ? 'disabled' : '';
                const wpLabel  = r.wp_url ? '🌐 WP Published' : '🌐 Post to WordPress';
                const pinEnv   = _sandboxMode ? ' [SANDBOX]' : '';
                const pinLabel = r.pinterest_id ? '📌 Pinned' : `📌 Post to Pinterest${pinEnv}`;
                const pinStyle = _sandboxMode && !r.pinterest_id ? 'background:linear-gradient(135deg,#e67e22,#d35400)' : '';
                actionBtns = `
                    <button class="btn-recipe-wp"  id="wp-btn-${r.recipe_id}"  onclick="publishRecipeWP(${r.recipe_id},this)"  ${wpDisabled}><span class="spinner"></span>${wpLabel}</button>
                    <button class="btn-recipe-pin" id="pin-btn-${r.recipe_id}" onclick="publishRecipePinterest(${r.recipe_id},this)" ${pinDisabled} style="${pinStyle}"><span class="spinner"></span>${pinLabel}</button>`;
            }
            actionBtns += exportBtns;

            return `<div class="recipe-card" id="recipe-${r.recipe_id}">
                <div class="recipe-card-top">
                    <div class="recipe-cover-wrap">
                        ${cover ? `<img class="recipe-cover-img" src="/images/${cover}" loading="lazy">` : '<div class="recipe-cover-placeholder">🥘</div>'}
                    </div>
                    <div class="recipe-info">
                        <span class="recipe-category-badge">${d.category||r.category}</span>
                        <div class="recipe-title">${d.title||r.title}</div>
                        <div class="recipe-meta">
                            <span class="recipe-meta-chip">⏱ Prep ${prep}</span>
                            <span class="recipe-meta-chip">🔥 Cook ${cook}</span>
                            <span class="recipe-meta-chip">🍽 ${servings}</span>
                            <span class="recipe-meta-chip">📊 ${difficulty}</span>
                        </div>
                        <div class="recipe-desc">${d.description||''}</div>
                        <div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:8px">${tags}</div>
                        <div class="recipe-status-row">${wpBadge}${pinBadge}</div>
                    </div>
                </div>
                <div class="recipe-inner-tabs">
                    <button class="recipe-tab-btn active" onclick="switchRecipeTab(${r.recipe_id},'overview',this)">Overview</button>
                    <button class="recipe-tab-btn" onclick="switchRecipeTab(${r.recipe_id},'ingredients',this)">Ingredients</button>
                    <button class="recipe-tab-btn" onclick="switchRecipeTab(${r.recipe_id},'instructions',this)">Instructions</button>
                    <button class="recipe-tab-btn" onclick="switchRecipeTab(${r.recipe_id},'images',this)">Images</button>
                </div>
                <div id="rtab-${r.recipe_id}-overview" class="recipe-tab-content active">
                    <p style="margin-bottom:10px">${d.description||''}</p>
                    ${d.notes ? `<p style="margin-bottom:8px"><strong>📝 Notes:</strong> ${d.notes}</p>` : ''}
                    ${d.tips  ? `<p><strong>💡 Tips:</strong> ${d.tips}</p>` : ''}
                </div>
                <div id="rtab-${r.recipe_id}-ingredients" class="recipe-tab-content">
                    <ul class="ing-list">${ings}</ul>
                </div>
                <div id="rtab-${r.recipe_id}-instructions" class="recipe-tab-content">
                    <div class="step-list">${steps}</div>
                </div>
                <div id="rtab-${r.recipe_id}-images" class="recipe-tab-content">
                    <p style="margin-bottom:10px;font-size:.8rem;color:#888">Cover + Pinterest pin + 3 step photos</p>
                    ${cover ? `<div style="margin-bottom:10px;border-radius:8px;overflow:hidden;max-height:200px"><img src="/images/${cover}" style="width:100%;object-fit:cover"></div>` : ''}
                    ${pin ? `<div style="position:relative;margin-bottom:10px;border-radius:8px;overflow:hidden;max-height:260px;background:#f6f1ec"><img src="/images/${pin}" style="width:100%;object-fit:contain;display:block"><span class="step-img-label">Pinterest Pin</span></div>` : ''}
                    <div class="step-images-grid">${stepImgs}</div>
                </div>
                <div class="recipe-actions">${actionBtns}</div>
            </div>`;
        }

        function switchRecipeTab(id, tab, el) {
            const card = document.getElementById(`recipe-${id}`);
            card.querySelectorAll('.recipe-tab-btn').forEach(b => b.classList.remove('active'));
            card.querySelectorAll('.recipe-tab-content').forEach(c => c.classList.remove('active'));
            el.classList.add('active');
            document.getElementById(`rtab-${id}-${tab}`).classList.add('active');
        }

        function downloadRecipeImages(id) {
            window.location.href = `/api/recipe/${id}/download/images`;
        }

        function downloadRecipeJson(id) {
            window.location.href = `/api/recipe/${id}/download/wprm-json`;
        }

        async function approveRecipe(id, btn) {
            if (!confirm('Accept this recipe? It will move to the Approved queue.')) return;
            btn.disabled = true;
            const data = await (await fetch(`/api/recipe/${id}/approve`,{method:'POST'})).json();
            if (data.success) { fetchRecipes(); }
            else { alert('Error: '+data.error); btn.disabled=false; }
        }

        async function rejectRecipe(id, btn) {
            if (!confirm('Reject and discard this recipe?')) return;
            btn.disabled = true;
            await fetch(`/api/recipe/${id}/reject`,{method:'POST'});
            fetchRecipes();
        }

        async function publishRecipeWP(id, btn) {
            if (!confirm('Publish this recipe to WordPress?')) return;
            btn.classList.add('loading'); btn.disabled = true;
            try {
                const data = await (await fetch(`/api/recipe/${id}/publish/wp`,{method:'POST'})).json();
                if (data.success) {
                    alert('Published to WordPress! URL: ' + data.wp_url);
                    fetchRecipes();
                } else {
                    alert('WP publish failed: ' + data.error);
                    btn.classList.remove('loading'); btn.disabled = false;
                }
            } catch(e) { alert('Request failed: '+e); btn.classList.remove('loading'); btn.disabled = false; }
        }

        async function publishRecipePinterest(id, btn) {
            const env = _sandboxMode ? 'Pinterest SANDBOX (api-sandbox.pinterest.com)' : 'Pinterest (production)';
            if (!confirm(`Post this recipe to ${env}?\nThe Pinterest pin image + WP URL will be used.`)) return;
            btn.classList.add('loading'); btn.disabled = true;
            if (_sandboxMode) {
                console.info(`[EGF SANDBOX] Calling POST /api/recipe/${id}/publish/pinterest`);
                console.info('[EGF SANDBOX] Backend will forward to: POST https://api-sandbox.pinterest.com/v5/pins');
            }
            try {
                const data = await (await fetch(`/api/recipe/${id}/publish/pinterest`,{method:'POST'})).json();
                if (data.success) {
                    const envLabel = _sandboxMode ? ' (Sandbox)' : '';
                    alert(`Posted to Pinterest${envLabel}!\nPin ID: ${data.pinterest_id}`);
                    fetchRecipes();
                } else {
                    alert('Pinterest failed: ' + data.error);
                    btn.classList.remove('loading'); btn.disabled = false;
                }
            } catch(e) { alert('Request failed: '+e); btn.classList.remove('loading'); btn.disabled = false; }
        }

        // ── Pinterest Re-auth ──
        async function reauthorizePinterest() {
            try {
                const data = await (await fetch('/api/oauth/start')).json();
                if (data.auth_url) window.open(data.auth_url,'_blank','width=600,height=700');
                else alert('Error: '+(data.error||'Unknown'));
            } catch(e) { alert('Error: '+e); }
        }

        // ── Trends & Insights ──
        async function fetchTrends() {
            try {
                const res = await fetch('/api/trends');
                const trends = await res.json();
                
                const pending = trends.filter(t => t.status === 'pending');
                const approved = trends.filter(t => t.status === 'approved');
                
                renderPendingTrends(pending);
                renderApprovedTrends(approved);
            } catch(e) {
                console.error("Error fetching trends:", e);
            }
        }
        
        function renderPendingTrends(trends) {
            const container = document.getElementById('trends-pending-container');
            if (!trends.length) {
                container.innerHTML = '<div class="empty">🎉 All caught up! No pending trends. Click "Scrape & Synthesize Trends" above to discover new ones.</div>';
                return;
            }
            container.innerHTML = trends.map(t => {
                const isPubMed = t.source.toLowerCase().includes('pubmed');
                const badgeColor = isPubMed ? 'background:#e8f4fd;color:#1565c0;border:1px solid #bbdefb;' : 'background:#fde8e8;color:#c0392b;border:1px solid #ffcdd2;';
                const scoreColor = t.relevance_score >= 0.8 ? 'color:#27ae60' : t.relevance_score >= 0.5 ? 'color:#e67e22' : 'color:#555';
                
                return `<div class="pin-card" id="trend-card-${t.topic_id}" style="padding:18px;min-height:220px;display:flex;flex-direction:column;justify-content:space-between;">
                    <div style="flex-grow:1;">
                        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                            <span class="pin-badge" style="${badgeColor}">${t.source}</span>
                            <span style="font-size:0.75rem;font-weight:700;${scoreColor}">★ ${t.relevance_score.toFixed(2)} Relevance</span>
                        </div>
                        <h4 style="font-size:0.95rem;font-weight:700;margin-bottom:8px;color:#1a1a2e;">${t.title}</h4>
                        <p style="font-size:0.8rem;color:#555;line-height:1.55;margin-bottom:12px;">${t.details}</p>
                    </div>
                    <div class="pin-actions" style="border-top:1px solid #f0f0f0;padding-top:10px;margin-top:10px;display:flex;gap:8px;">
                        <button class="btn btn-approve" onclick="approveTrend(${t.topic_id})">✓ Approve</button>
                        <button class="btn btn-reject" onclick="rejectTrend(${t.topic_id})">✗ Reject</button>
                    </div>
                </div>`;
            }).join('');
        }
        
        function renderApprovedTrends(trends) {
            const tbody = document.getElementById('trends-approved-body');
            if (!trends.length) {
                tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:28px;color:#aaa">No approved topics yet. Approve a discovered trend above.</td></tr>';
                return;
            }
            tbody.innerHTML = trends.map(t => {
                const isPubMed = t.source.toLowerCase().includes('pubmed');
                const badgeColor = isPubMed ? 'background:#e8f4fd;color:#1565c0;border:1px solid #bbdefb;' : 'background:#fde8e8;color:#c0392b;border:1px solid #ffcdd2;';
                
                return `<tr id="trend-row-${t.topic_id}">
                    <td style="font-weight:700;color:#1a1a2e;vertical-align:top;padding-top:14px;">${t.title}</td>
                    <td style="vertical-align:top;padding-top:14px;"><span class="pin-badge" style="${badgeColor}">${t.source}</span></td>
                    <td style="color:#555;line-height:1.5;font-size:0.8rem;vertical-align:top;padding-top:14px;">${t.details}</td>
                    <td style="vertical-align:top;padding-top:10px;">
                        <button class="btn btn-trigger" onclick="suggestTrendTitle(${t.topic_id}, this)" style="padding:6px 12px;font-size:0.78rem;margin-bottom:6px;width:100%;">
                            Suggest Another Title
                        </button>
                        <button class="btn btn-approve" onclick="generateBlogFromTrend(${t.topic_id}, this)" style="padding:6px 12px;font-size:0.78rem;background:linear-gradient(135deg,#e94560,#c73652);display:flex;align-items:center;justify-content:center;gap:4px;width:100%;">
                            <span class="spinner"></span>✍️ Generate Blog &amp; Pin
                        </button>
                    </td>
                </tr>`;
            }).join('');
        }

        async function approveTrend(id) {
            try {
                const res = await fetch(`/api/trends/${id}/approve`, {method:'POST'});
                const data = await res.json();
                if (data.success) {
                    fetchTrends();
                }
            } catch(e) { alert("Error approving trend: " + e); }
        }

        async function rejectTrend(id) {
            if (!confirm('Reject and dismiss this trendy topic?')) return;
            try {
                const res = await fetch(`/api/trends/${id}/reject`, {method:'POST'});
                const data = await res.json();
                if (data.success) {
                    fetchTrends();
                }
            } catch(e) { alert("Error rejecting trend: " + e); }
        }

        async function suggestTrendTitle(id, btn) {
            if (!confirm('Suggest and replace this approved topic title?')) return;
            const original = btn.textContent;
            btn.disabled = true;
            btn.textContent = 'Suggesting...';
            try {
                const res = await fetch(`/api/trends/${id}/suggest_title`, {method:'POST'});
                const data = await res.json();
                if (data.success) {
                    fetchTrends();
                } else {
                    alert("Failed: " + data.error);
                    btn.disabled = false;
                    btn.textContent = original;
                }
            } catch(e) {
                alert("Error suggesting title: " + e);
                btn.disabled = false;
                btn.textContent = original;
            }
        }

        async function generateBlogFromTrend(id, btn) {
            if (!confirm('Generate a complete Blog Post and Pinterest Pin for this topic? It will be automatically scheduled in the publish queue.')) return;
            btn.classList.add('loading'); btn.disabled = true;
            try {
                const res = await fetch(`/api/trends/${id}/generate_blog`, {method:'POST'});
                const data = await res.json();
                if (data.success) {
                    alert(`Success! Blog generated: "${data.blog_title}".\nReview it from the approved blog and pin pages.`);
                    fetchTrends();
                } else {
                    alert("Failed: " + data.error);
                    btn.classList.remove('loading'); btn.disabled = false;
                }
            } catch(e) { 
                alert("Error generating blog: " + e); 
                btn.classList.remove('loading'); btn.disabled = false;
            }
        }

        let _trendsScrapePollInterval = null;
        async function scrapeAndSynthesizeTrends() {
            const btn = document.getElementById('btn-scrape-trends');
            btn.classList.add('loading'); btn.disabled = true;
            try {
                const res = await fetch('/api/trends/scrape', {method:'POST'});
                const data = await res.json();
                if (data.status === 'started' || data.status === 'running') {
                    _trendsScrapePollInterval = setInterval(pollScrapeStatus, 2000);
                } else {
                    alert("Could not start scraping: " + data.message);
                    btn.classList.remove('loading'); btn.disabled = false;
                }
            } catch(e) {
                alert("Error starting scrape: " + e);
                btn.classList.remove('loading'); btn.disabled = false;
            }
        }

        async function pollScrapeStatus() {
            try {
                const res = await fetch('/api/trends/scrape/status');
                const data = await res.json();
                if (data.status === 'running') return;
                
                clearInterval(_trendsScrapePollInterval);
                const btn = document.getElementById('btn-scrape-trends');
                btn.classList.remove('loading'); btn.disabled = false;
                
                if (data.status === 'done') {
                    alert("Successfully scraped new subreddits/medical articles and synthesized trendy topics!");
                    fetchTrends();
                } else if (data.status === 'error') {
                    alert("Scraping failed: " + data.error);
                }
            } catch(e) {
                console.error("Error polling scrape status:", e);
            }
        }

        // Knowledge DB
        async function fetchKnowledgeDb() {
            await Promise.all([fetchKnowledgeStats(), fetchKnowledgeEntries()]);
        }

        async function fetchKnowledgeStats() {
            try {
                const stats = await (await fetch('/api/knowledge/stats')).json();
                const blockedStale = (stats.blocked || 0) + (stats.stale || 0);
                document.getElementById('kb-stats').innerHTML = `
                    <div class="kb-stat"><div class="kb-stat-value">${stats.total || 0}</div><div class="kb-stat-label">Total</div></div>
                    <div class="kb-stat"><div class="kb-stat-value">${stats.reusable || 0}</div><div class="kb-stat-label">Reusable</div></div>
                    <div class="kb-stat"><div class="kb-stat-value">${stats.needs_more_evidence || 0}</div><div class="kb-stat-label">Needs Evidence</div></div>
                    <div class="kb-stat"><div class="kb-stat-value">${blockedStale}</div><div class="kb-stat-label">Blocked/Stale</div></div>
                `;
            } catch(e) {
                console.error('Knowledge stats failed', e);
            }
        }

        async function ingestKnowledgeDb() {
            const btn = document.getElementById('btn-kb-ingest');
            btn.classList.add('loading');
            btn.disabled = true;
            try {
                const data = await (await fetch('/api/knowledge/ingest', {method:'POST'})).json();
                if (!data.success) {
                    alert(data.error || 'Knowledge ingest failed.');
                } else {
                    const ingest = data.ingest || {};
                    alert(`Knowledge DB updated.\nCreated: ${ingest.entries_created || 0}\nExisting: ${ingest.entries_existing || 0}\nEvidence added: ${ingest.evidence_created || 0}`);
                    await fetchKnowledgeDb();
                }
            } catch(e) {
                alert('Knowledge ingest failed: ' + e);
            }
            btn.classList.remove('loading');
            btn.disabled = false;
        }

        async function fetchKnowledgeEntries() {
            const params = new URLSearchParams();
            const search = document.getElementById('kb-search').value.trim();
            const lane = document.getElementById('kb-lane').value;
            const entryType = document.getElementById('kb-entry-type').value;
            const qualityStatus = document.getElementById('kb-quality-status').value;
            const sourceType = document.getElementById('kb-source-type').value;
            const minQuality = document.getElementById('kb-min-quality').value;
            if (search) params.set('search', search);
            if (lane) params.set('lane', lane);
            if (entryType) params.set('entry_type', entryType);
            if (qualityStatus) params.set('quality_status', qualityStatus);
            if (sourceType) params.set('source_type', sourceType);
            if (minQuality) params.set('min_quality', minQuality);
            params.set('limit', '120');

            const list = document.getElementById('kb-list');
            list.innerHTML = '<div class="empty">Loading knowledge entries...</div>';
            try {
                const entries = await (await fetch('/api/knowledge/entries?' + params.toString())).json();
                list.innerHTML = entries.length
                    ? entries.map(buildKnowledgeCard).join('')
                    : '<div class="empty">No knowledge entries match these filters.</div>';
            } catch(e) {
                list.innerHTML = `<div class="empty">Could not load Knowledge DB: ${esc(e)}</div>`;
            }
        }

        function buildKnowledgeCard(entry) {
            const status = entry.quality_status || 'needs_more_evidence';
            const statusClass = status === 'auto_approved' ? 'good' : (status === 'blocked' || status === 'stale') ? 'bad' : 'warn';
            const reuseClass = entry.reuse_allowed ? 'good' : 'warn';
            const summary = entry.summary || 'No summary captured yet.';
            return `<div class="kb-card" id="kb-entry-${entry.entry_id}">
                <div class="kb-title">${esc(entry.claim)}</div>
                <div class="kb-summary">${esc(summary)}</div>
                <div class="kb-meta">
                    <span class="kb-pill ${statusClass}">${esc(status)}</span>
                    <span class="kb-pill ${reuseClass}">${entry.reuse_allowed ? 'reusable' : 'not reusable'}</span>
                    <span class="kb-pill">${esc(entry.entry_type)}</span>
                    <span class="kb-pill">${esc(entry.lane)}</span>
                    <span class="kb-pill">score ${Number(entry.quality_score || 0).toFixed(2)}</span>
                    <span class="kb-pill">${Number(entry.evidence_count || 0)} sources</span>
                </div>
                <div class="draft-dek">Entity: ${esc(entry.entity_name || 'Unknown')} ${entry.source_type ? '| Source: ' + esc(entry.source_type) : ''}</div>
                <div class="kb-actions">
                    <button class="btn btn-trigger btn-small" onclick="openKnowledgeDetail(${entry.entry_id})">Evidence</button>
                    <button class="btn btn-danger btn-small" onclick="blockKnowledgeEntry(${entry.entry_id})">Block</button>
                    <button class="btn btn-muted btn-small" onclick="markKnowledgeStale(${entry.entry_id})">Mark Stale</button>
                    <button class="btn btn-approve btn-small" onclick="restoreKnowledgeEntry(${entry.entry_id})">Restore</button>
                </div>
            </div>`;
        }

        async function openKnowledgeDetail(entryId) {
            const data = await (await fetch(`/api/knowledge/entries/${entryId}`)).json();
            if (!data.success) {
                alert(data.error || 'Could not load knowledge entry.');
                return;
            }
            const entry = data.entry;
            const evidence = (entry.evidence || []).map(ev => `
                <div class="draft-section">
                    <strong>${esc(ev.title || ev.source_type || 'Evidence')}</strong>
                    <div>${esc(ev.evidence_text || 'No snippet captured.')}</div>
                    ${ev.source_url ? `<div class="source-links"><a href="${esc(ev.source_url)}" target="_blank" rel="noopener">${esc(ev.source_url)}</a></div>` : ''}
                    <div class="draft-dek">type: ${esc(ev.source_type || 'unknown')} | credibility: ${Number(ev.credibility_score || 0).toFixed(2)}</div>
                </div>
            `).join('');
            const body = `
                <div class="draft-title">${esc(entry.claim)}</div>
                <div class="draft-dek">Entity: ${esc(entry.entity_name || 'Unknown')} | ${esc(entry.entry_type)} | ${esc(entry.lane)}</div>
                <div class="kb-meta">
                    <span class="kb-pill">${esc(entry.quality_status)}</span>
                    <span class="kb-pill">${entry.reuse_allowed ? 'reusable' : 'not reusable'}</span>
                    <span class="kb-pill">quality ${Number(entry.quality_score || 0).toFixed(2)}</span>
                    <span class="kb-pill">confidence ${Number(entry.confidence_score || 0).toFixed(2)}</span>
                </div>
                <div class="draft-section"><strong>Summary</strong>${esc(entry.summary || 'No summary captured.')}</div>
                ${evidence || '<div class="draft-section">No evidence records found.</div>'}
            `;
            const actions = `
                <button class="btn btn-danger" onclick="blockKnowledgeEntry(${entry.entry_id})">Block</button>
                <button class="btn btn-muted" onclick="markKnowledgeStale(${entry.entry_id})">Mark Stale</button>
                <button class="btn btn-approve" onclick="restoreKnowledgeEntry(${entry.entry_id})">Restore Reuse</button>
            `;
            openDetailModal('Knowledge Evidence', body, actions);
        }

        async function blockKnowledgeEntry(entryId) {
            if (!confirm('Block this knowledge entry from reuse?')) return;
            const data = await (await fetch(`/api/knowledge/entries/${entryId}/block`, {method:'POST'})).json();
            if (data.success) { closeDetailModal(); await fetchKnowledgeDb(); }
            else alert('Could not block entry.');
        }

        async function markKnowledgeStale(entryId) {
            const data = await (await fetch(`/api/knowledge/entries/${entryId}/mark-stale`, {method:'POST'})).json();
            if (data.success) { closeDetailModal(); await fetchKnowledgeDb(); }
            else alert('Could not mark entry stale.');
        }

        async function restoreKnowledgeEntry(entryId) {
            const data = await (await fetch(`/api/knowledge/entries/${entryId}/restore`, {method:'POST'})).json();
            if (data.success) { closeDetailModal(); await fetchKnowledgeDb(); }
            else alert('Could not restore entry. It may still need stronger evidence.');
        }

        // Content Studio
        function studioImageUrl(path) {
            return path ? `/images/${path.split(/[\\\\/]/).pop()}` : '';
        }

        async function fetchContentStudio() {
            await Promise.all([fetchStudioIdeas(), fetchStudioAssets()]);
        }

        async function fetchStudioIdeas() {
            const lane = document.getElementById('studio-lane').value;
            const list = document.getElementById('studio-ideas-list');
            try {
                const ideas = await (await fetch(`/api/editorial/lanes/${lane}/ideas?limit=12`)).json();
                if (!ideas.length) {
                    list.innerHTML = '<div class="empty">No ideas for this lane yet. Generate a batch above.</div>';
                    return;
                }
                list.innerHTML = ideas.map(buildStudioIdeaCard).join('');
            } catch(e) {
                list.innerHTML = `<div class="empty">Could not load ideas: ${esc(e)}</div>`;
            }
        }

        async function generateStudioIdeas() {
            const btn = document.getElementById('btn-studio-generate');
            const lane = document.getElementById('studio-lane').value;
            const payload = {
                idea_count: Number(document.getElementById('studio-idea-count').value || 3),
                topic_hint: document.getElementById('studio-topic-hint').value.trim(),
                sample: document.getElementById('studio-sample').checked,
                persist: true
            };
            btn.classList.add('loading');
            btn.disabled = true;
            try {
                const data = await (await fetch(`/api/editorial/lanes/${lane}/ideas`, {
                    method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body:JSON.stringify(payload)
                })).json();
                if (!data.success) {
                    alert('Idea generation failed: ' + data.error);
                    return;
                }
                await fetchStudioIdeas();
            } catch(e) {
                alert('Idea generation error: ' + e);
            }
            btn.classList.remove('loading');
            btn.disabled = false;
        }

        function buildStudioIdeaCard(idea) {
            const lane = idea.content_lane || 'unknown';
            const angle = idea.angle_type || 'angle pending';
            return `
                <div class="studio-card" id="studio-idea-${idea.idea_id}">
                    <div class="studio-title">${esc(idea.title)}</div>
                    <div class="studio-copy">${esc(idea.description || '')}</div>
                    <div class="lab-meta">
                        <span class="lab-chip">${esc(lane)}</span>
                        <span class="lab-chip">${esc(angle)}</span>
                        ${idea.source_hint ? `<span class="lab-chip">${esc(idea.source_hint)}</span>` : ''}
                    </div>
                    <div class="studio-actions">
                        <button class="btn btn-approve btn-small" onclick="generateAssetsForIdea(${idea.idea_id}, ['blog','pin','newsletter'], this)">Full Set</button>
                        <button class="btn btn-trigger btn-small" onclick="generateAssetsForIdea(${idea.idea_id}, ['blog','pin'], this)">Blog + Pin</button>
                        <button class="btn btn-pin btn-small" onclick="generateAssetsForIdea(${idea.idea_id}, ['pin'], this)">Pin Only</button>
                        <button class="btn btn-copy btn-small" onclick="generateAssetsForIdea(${idea.idea_id}, ['newsletter'], this)">Newsletter</button>
                    </div>
                </div>
            `;
        }

        async function generateAssetsForIdea(ideaId, assets, btn) {
            const sample = false;
            if (!sample && !confirm('Generate selected assets now? This may use OpenAI/image generation credits.')) return;
            btn.classList.add('loading');
            btn.disabled = true;
            try {
                const data = await (await fetch(`/api/editorial/ideas/${ideaId}/assets`, {
                    method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body:JSON.stringify({assets, sample, persist:true})
                })).json();
                if (!data.success) {
                    alert('Asset generation failed: ' + data.error);
                    return;
                }
                await fetchStudioAssets();
                await fetchPins();
                const blogProduct = data.assets && data.assets.blog && data.assets.blog.product;
                if (blogProduct && blogProduct.needs_manual_image) {
                    await fetchAmazonProducts();
                    alert(`Assets created. Affiliate product added: ${blogProduct.title}\n\nManual task: add a product image in the Amazon Products tab. Publishing can continue without the image; the blog will show the title, description, and link only.`);
                } else {
                    alert('Assets created. Review them in the panels on the right.');
                }
            } catch(e) {
                alert('Asset generation error: ' + e);
            }
            btn.classList.remove('loading');
            btn.disabled = false;
        }

        async function fetchStudioAssets() {
            try {
                const assets = await (await fetch('/api/editorial/assets?limit=20')).json();
                renderWebsiteAssets(assets.website || []);
                renderPinterestAssets(assets.pinterest || []);
                renderNewsletterAssets(assets.newsletters || []);
            } catch(e) {
                document.getElementById('studio-website-list').innerHTML = `<div class="empty">Could not load assets: ${esc(e)}</div>`;
            }
        }

        function renderWebsiteAssets(items) {
            const list = document.getElementById('studio-website-list');
            if (!items.length) {
                list.innerHTML = '<div class="empty">No website posts generated yet.</div>';
                return;
            }
            list.innerHTML = items.map(item => {
                const status = item.wp_url ? 'published' : item.status;
                const open = item.wp_url ? `<a class="btn btn-copy btn-small" href="${esc(item.wp_url)}" target="_blank" rel="noopener" style="text-decoration:none;text-align:center">Open</a>` : '';
                const publish = item.wp_url ? '' : `<button class="btn btn-wp btn-small" onclick="publishWebsiteAsset(${item.blog_id}, this)">Publish to Website</button>`;
                return `
                    <div class="studio-card">
                        <div class="studio-title">${esc(item.title)}</div>
                        <div class="lab-meta">
                            <span class="lab-chip ${item.wp_url ? 'approved' : 'pending'}">${esc(status)}</span>
                            ${item.content_lane ? `<span class="lab-chip">${esc(item.content_lane)}</span>` : ''}
                            ${item.product_title ? `<span class="lab-chip">${esc(item.product_title)}</span>` : ''}
                            ${Number(item.product_needs_manual_image || 0) ? '<span class="lab-chip rejected">needs product image</span>' : ''}
                        </div>
                        <div class="studio-actions">${publish}${open}</div>
                    </div>
                `;
            }).join('');
        }

        function renderPinterestAssets(items) {
            const list = document.getElementById('studio-pinterest-list');
            if (!items.length) {
                list.innerHTML = '<div class="empty">No Pinterest assets generated yet.</div>';
                return;
            }
            list.innerHTML = items.map(item => {
                const imageUrl = studioImageUrl(item.image_path);
                const posted = item.pinterest_id || item.status === 'published' || item.status === 'posted';
                const postBtn = posted ? '' : `<button class="btn btn-pin btn-small" onclick="postPinterestAsset(${item.pin_id}, this)">Post to Pinterest</button>`;
                return `
                    <div class="studio-card">
                        <div style="display:flex;gap:12px;align-items:flex-start">
                            ${imageUrl ? `<img class="studio-mini-img" src="${esc(imageUrl)}" loading="lazy">` : '<div class="studio-mini-img"></div>'}
                            <div style="min-width:0;flex:1">
                                <div class="studio-title">${esc(item.title)}</div>
                                <div class="studio-copy">${esc((item.description || '').slice(0, 220))}</div>
                                <div class="lab-meta">
                                    <span class="lab-chip ${posted ? 'approved' : 'pending'}">${posted ? 'posted' : esc(item.status)}</span>
                                    ${item.content_lane ? `<span class="lab-chip">${esc(item.content_lane)}</span>` : ''}
                                </div>
                            </div>
                        </div>
                        <div class="studio-actions">
                            ${postBtn}
                            <button class="btn btn-copy btn-small" onclick="copyPinText(${item.pin_id})">Copy Text</button>
                            ${imageUrl ? `<button class="btn btn-copy btn-small" onclick="copyPinImage('${esc(imageUrl)}')">Copy Image</button>` : ''}
                        </div>
                    </div>
                `;
            }).join('');
        }

        function renderNewsletterAssets(items) {
            const list = document.getElementById('studio-newsletter-list');
            if (!items.length) {
                list.innerHTML = '<div class="empty">No newsletter drafts generated yet.</div>';
                return;
            }
            list.innerHTML = items.map(item => `
                <div class="studio-card">
                    <div class="studio-title">${esc(item.title)}</div>
                    <div class="studio-copy">${esc(item.dek || '')}</div>
                    <div class="lab-meta">
                        <span class="lab-chip ${item.status === 'approved' ? 'approved' : 'pending'}">${esc(item.status)}</span>
                        <span class="lab-chip">${esc(item.lane || '')}</span>
                    </div>
                    <div class="studio-actions">
                        <button class="btn btn-copy btn-small" onclick="copyNewsletterText(${item.draft_id})">Copy Email Text</button>
                    </div>
                </div>
            `).join('');
        }

        async function publishWebsiteAsset(blogId, btn) {
            if (!confirm('Publish this blog post to the website now?')) return;
            btn.classList.add('loading');
            btn.disabled = true;
            try {
                const data = await (await fetch(`/api/blogs/${blogId}/publish/wp`, {method:'POST'})).json();
                if (data.success) {
                    alert('Published to website: ' + data.wp_url);
                    fetchStudioAssets();
                } else {
                    alert('Website publish failed: ' + data.error);
                }
            } catch(e) {
                alert('Website publish error: ' + e);
            }
            btn.classList.remove('loading');
            btn.disabled = false;
        }

        async function postPinterestAsset(pinId, btn) {
            const env = _sandboxMode ? 'Pinterest sandbox' : 'Pinterest';
            if (!confirm(`Post this pin to ${env}? The website asset must already be published or linked.`)) return;
            btn.classList.add('loading');
            btn.disabled = true;
            try {
                const data = await (await fetch(`/api/pins/${pinId}/post/pinterest`, {method:'POST'})).json();
                if (data.success) {
                    alert('Posted to Pinterest. Pin ID: ' + data.pinterest_id);
                    fetchStudioAssets();
                } else {
                    alert('Pinterest post failed: ' + data.error);
                }
            } catch(e) {
                alert('Pinterest post error: ' + e);
            }
            btn.classList.remove('loading');
            btn.disabled = false;
        }

        async function copyPinText(pinId) {
            const data = await (await fetch(`/api/pins/${pinId}/copy`)).json();
            if (!data.success) {
                alert('Copy failed: ' + data.error);
                return;
            }
            const text = `${data.title}\n\n${data.description}${data.destination_url ? `\n\n${data.destination_url}` : ''}`;
            await navigator.clipboard.writeText(text);
            alert('Pin title, description, and link copied.');
        }

        async function copyPinImage(imageUrl) {
            try {
                const blob = await (await fetch(imageUrl)).blob();
                await navigator.clipboard.write([new ClipboardItem({[blob.type || 'image/jpeg']: blob})]);
                alert('Pin image copied.');
            } catch(e) {
                window.open(imageUrl, '_blank');
                alert('Could not copy image directly, so I opened it in a new tab.');
            }
        }

        async function copyNewsletterText(draftId) {
            const data = await (await fetch(`/api/newsletters/${draftId}/copy`)).json();
            if (!data.success) {
                alert('Copy failed: ' + data.error);
                return;
            }
            await navigator.clipboard.writeText(data.text);
            alert('Newsletter text copied.');
        }

        // Editorial Lab
        function esc(value) {
            return String(value ?? '').replace(/[&<>"']/g, ch => ({
                '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
            }[ch]));
        }

        async function fetchEditorialLab() {
            await Promise.all([
                fetchSourceNotifications(),
                fetchApprovedSources(),
                fetchContentDrafts()
            ]);
        }

        async function fetchSourceNotifications() {
            const list = document.getElementById('source-notifications-list');
            try {
                const notifications = await (await fetch('/api/source-notifications')).json();
                if (!notifications.length) {
                    list.innerHTML = '<div class="empty">No pending source approvals.</div>';
                    return;
                }
                list.innerHTML = notifications.map(n => `
                    <div class="lab-item" id="source-note-${n.source_id}">
                        <div class="lab-item-title">${esc(n.name || 'Unnamed source')}</div>
                        <div class="lab-meta">
                            <span class="lab-chip pending">pending</span>
                            <span class="lab-chip">${esc(n.lane)}</span>
                            <span class="lab-chip">${esc(n.source_type)}</span>
                            <span class="lab-chip">cred ${Number(n.credibility_score || 0).toFixed(2)}</span>
                        </div>
                        <div class="lab-source-url">${esc(n.base_url)}</div>
                        <p style="margin-top:8px">${esc(n.message || '')}</p>
                        <div class="lab-actions">
                            <button class="btn btn-approve" onclick="approveEditorialSource(${n.source_id})">Approve</button>
                            <button class="btn btn-reject" onclick="rejectEditorialSource(${n.source_id})">Reject</button>
                        </div>
                    </div>
                `).join('');
            } catch(e) {
                list.innerHTML = `<div class="empty">Could not load source notifications: ${esc(e)}</div>`;
            }
        }

        async function fetchApprovedSources() {
            const list = document.getElementById('approved-sources-list');
            try {
                const sources = await (await fetch('/api/sources?status=approved')).json();
                if (!sources.length) {
                    list.innerHTML = '<div class="empty">No approved sources yet.</div>';
                    return;
                }
                list.innerHTML = sources.slice(0, 12).map(s => `
                    <div class="lab-item">
                        <div class="lab-item-title">${esc(s.name)}</div>
                        <div class="lab-meta">
                            <span class="lab-chip approved">approved</span>
                            <span class="lab-chip">${esc(s.lane)}</span>
                            <span class="lab-chip">${esc(s.source_type)}</span>
                        </div>
                        <div class="lab-source-url">${esc(s.base_url)}</div>
                    </div>
                `).join('');
            } catch(e) {
                list.innerHTML = `<div class="empty">Could not load approved sources: ${esc(e)}</div>`;
            }
        }

        async function proposeEditorialSource() {
            const btn = document.getElementById('btn-source-propose');
            const payload = {
                name: document.getElementById('source-name').value.trim(),
                base_url: document.getElementById('source-url').value.trim(),
                lane: document.getElementById('source-lane').value,
                source_type: document.getElementById('source-type').value,
                notes: document.getElementById('source-notes').value.trim(),
                credibility_score: 0.72,
                monitor_frequency: 'weekly'
            };
            if (!payload.name || !payload.base_url) {
                alert('Source name and URL are required.');
                return;
            }
            btn.disabled = true;
            try {
                const data = await (await fetch('/api/sources/propose', {
                    method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body:JSON.stringify(payload)
                })).json();
                if (data.success) {
                    document.getElementById('source-name').value = '';
                    document.getElementById('source-url').value = '';
                    document.getElementById('source-notes').value = '';
                    await fetchEditorialLab();
                    alert('Source proposed. It is now waiting for approval.');
                } else {
                    alert('Failed: ' + data.error);
                }
            } catch(e) {
                alert('Error proposing source: ' + e);
            }
            btn.disabled = false;
        }

        async function approveEditorialSource(id) {
            const data = await (await fetch(`/api/sources/${id}/approve`, {method:'POST'})).json();
            if (data.success) fetchEditorialLab();
            else alert('Could not approve source.');
        }

        async function rejectEditorialSource(id) {
            if (!confirm('Reject this source? It will not be used automatically.')) return;
            const data = await (await fetch(`/api/sources/${id}/reject`, {method:'POST'})).json();
            if (data.success) fetchEditorialLab();
            else alert('Could not reject source.');
        }

        let _amazonProducts = [];

        async function fetchAmazonProducts() {
            const body = document.getElementById('amazon-products-body');
            try {
                _amazonProducts = await (await fetch('/api/amazon-products?include_inactive=true')).json();
                if (!_amazonProducts.length) {
                    body.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:28px;color:#aaa">No products yet.</td></tr>';
                    return;
                }
                body.innerHTML = _amazonProducts.map(p => `
                    <tr class="${Number(p.active) ? '' : 'muted'}">
                        <td>${p.image_url ? `<img class="product-img" src="${esc(p.image_url)}" alt="" onerror="this.style.display='none'">` : '<div class="product-img" style="display:grid;place-items:center;font-size:10px;color:#7a4d12;text-align:center;padding:4px">needs image</div>'}</td>
                        <td>
                            <strong>${esc(p.title)}</strong>
                            <div class="lab-source-url">${esc(p.url)}</div>
                            <div class="lab-meta">
                                <span class="lab-chip ${Number(p.active) ? 'approved' : 'rejected'}">${Number(p.active) ? 'active' : 'inactive'}</span>
                                <span class="lab-chip">${esc(p.price_tier || '')}</span>
                                ${Number(p.auto_created || 0) ? '<span class="lab-chip">auto-created</span>' : ''}
                                ${Number(p.needs_manual_image || 0) ? '<span class="lab-chip rejected">needs image</span>' : ''}
                            </div>
                        </td>
                        <td>${esc(p.description || '')}</td>
                        <td>${esc(p.content_lanes || '')}</td>
                        <td>${esc(p.keywords || '')}</td>
                        <td>${Number(p.priority_score || 1).toFixed(1)}</td>
                        <td>
                            <div class="action-col">
                                <button class="btn btn-muted btn-small" onclick="openProductModal(${p.product_id})">Edit</button>
                                <button class="btn btn-danger btn-small" onclick="deleteAmazonProduct(${p.product_id})" ${Number(p.active) ? '' : 'disabled'}>Delete</button>
                            </div>
                        </td>
                    </tr>
                `).join('');
            } catch(e) {
                body.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:28px;color:#aaa">Could not load products: ${esc(e)}</td></tr>`;
            }
        }

        function openProductModal(productId=null) {
            const product = productId ? _amazonProducts.find(p => Number(p.product_id) === Number(productId)) : null;
            document.getElementById('product-modal-title').textContent = product ? 'Edit Amazon Product' : 'Add Amazon Product';
            document.getElementById('product-id').value = product ? product.product_id : '';
            document.getElementById('product-title').value = product ? product.title || '' : '';
            document.getElementById('product-description').value = product ? product.description || '' : '';
            document.getElementById('product-url').value = product ? product.url || '' : '';
            document.getElementById('product-image-url').value = product ? product.image_url || '' : '';
            document.getElementById('product-keywords').value = product ? product.keywords || '' : '';
            document.getElementById('product-lanes').value = product ? product.content_lanes || '' : '';
            document.getElementById('product-price-tier').value = product ? product.price_tier || 'affordable' : 'affordable';
            document.getElementById('product-priority').value = product ? product.priority_score || 1 : 1;
            document.getElementById('product-active').checked = product ? Boolean(Number(product.active)) : true;
            document.getElementById('product-overlay').classList.add('active');
        }

        function closeProductModal() {
            document.getElementById('product-overlay').classList.remove('active');
        }

        async function saveAmazonProduct() {
            const productId = document.getElementById('product-id').value;
            const payload = {
                title: document.getElementById('product-title').value.trim(),
                description: document.getElementById('product-description').value.trim(),
                url: document.getElementById('product-url').value.trim(),
                image_url: document.getElementById('product-image-url').value.trim(),
                keywords: document.getElementById('product-keywords').value.trim(),
                content_lanes: document.getElementById('product-lanes').value.trim(),
                price_tier: document.getElementById('product-price-tier').value.trim() || 'affordable',
                priority_score: Number(document.getElementById('product-priority').value || 1),
                active: document.getElementById('product-active').checked
            };
            const url = productId ? `/api/amazon-products/${productId}` : '/api/amazon-products';
            const method = productId ? 'PUT' : 'POST';
            const data = await (await fetch(url, {method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)})).json();
            if (data.success) {
                closeProductModal();
                fetchAmazonProducts();
            } else {
                alert(data.error || 'Could not save product.');
            }
        }

        async function deleteAmazonProduct(productId) {
            if (!confirm('Delete this product from active matching? Existing blogs will keep their history.')) return;
            const data = await (await fetch(`/api/amazon-products/${productId}`, {method:'DELETE'})).json();
            if (data.success) fetchAmazonProducts();
            else alert(data.error || 'Could not delete product.');
        }

        async function testAmazonMatch() {
            const topic = document.getElementById('amazon-topic').value.trim();
            const lane = document.getElementById('amazon-lane').value;
            const result = document.getElementById('amazon-match-result');
            const btn = document.getElementById('btn-amazon-match');
            if (!topic) {
                alert('Enter a topic to match.');
                return;
            }
            btn.disabled = true;
            result.innerHTML = '<div class="empty">Matching product...</div>';
            try {
                const data = await (await fetch('/api/amazon-products/match', {
                    method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body:JSON.stringify({topic_title:topic, lane})
                })).json();
                if (!data.success) {
                    result.innerHTML = `<div class="empty">Match failed: ${esc(data.error)}</div>`;
                    return;
                }
                const p = data.product;
                result.innerHTML = `
                    <div class="lab-item">
                        <div style="display:flex;gap:12px;align-items:flex-start">
                            ${p.image_url ? `<img src="${esc(p.image_url)}" alt="" style="width:86px;height:86px;object-fit:cover;border-radius:10px;background:#eee">` : '<div style="width:86px;height:86px;border-radius:10px;background:#fff7ed;color:#7a4d12;display:grid;place-items:center;text-align:center;font-size:12px;padding:8px">needs image</div>'}
                            <div>
                                <div class="lab-item-title">${esc(p.title)}</div>
                                <div class="lab-meta">
                                    <span class="lab-chip approved">${esc(p.price_tier || 'product')}</span>
                                    <span class="lab-chip">${esc(p.content_lanes || '')}</span>
                                    ${p.needs_manual_image ? '<span class="lab-chip rejected">needs image</span>' : ''}
                                </div>
                                <p>${esc(p.description)}</p>
                                ${p.match_notes ? `<div class="lab-source-url">${esc(p.match_notes)}</div>` : ''}
                                <div class="lab-source-url">${esc(data.affiliate_status)}</div>
                            </div>
                        </div>
                    </div>
                `;
            } catch(e) {
                result.innerHTML = `<div class="empty">Match error: ${esc(e)}</div>`;
            }
            btn.disabled = false;
        }

        async function generateBlogPreview(sample=false) {
            const btn = document.getElementById(sample ? 'btn-blog-sample' : 'btn-blog-preview');
            const result = document.getElementById('blog-preview-result');
            const payload = {
                lane: document.getElementById('blog-preview-lane').value,
                topic_title: document.getElementById('blog-preview-topic').value.trim(),
                description: document.getElementById('blog-preview-description').value.trim(),
                sample
            };
            btn.classList.add('loading');
            btn.disabled = true;
            result.innerHTML = sample
                ? '<div class="empty">Generating sample preview from the live template...</div>'
                : '<div class="empty">Generating full blog preview. This uses the LLM and may take a minute...</div>';
            try {
                const data = await (await fetch('/api/blog-preview/generate', {
                    method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body:JSON.stringify(payload)
                })).json();
                if (!data.success) {
                    result.innerHTML = `<div class="empty">Preview failed: ${esc(data.error)}</div>`;
                    return;
                }
                result.innerHTML = `
                    <div class="draft-card">
                        <div class="draft-title">${esc(data.title)}</div>
                        <div class="draft-dek">Lane: ${esc(data.lane)} | Category: ${esc(data.category)}</div>
                        <div class="lab-meta">
                            <span class="lab-chip approved">preview generated</span>
                            <span class="lab-chip">${esc(data.generation_mode || 'preview')}</span>
                            <span class="lab-chip">${esc(data.product.title)}</span>
                            ${data.product.needs_manual_image ? '<span class="lab-chip rejected">needs product image</span>' : ''}
                        </div>
                        <div class="draft-section">
                            <strong>Topic used</strong>
                            ${esc(data.topic_title)}
                        </div>
                        <div class="draft-section">
                            <strong>Amazon product inserted</strong>
                            ${esc(data.product.title)} - ${esc(data.product.description)}
                            ${data.product.match_notes ? `<div class="lab-source-url">${esc(data.product.match_notes)}</div>` : ''}
                        </div>
                        <div class="lab-actions">
                            <a class="btn btn-approve" href="${esc(data.preview_url)}" target="_blank" rel="noopener" style="text-align:center;text-decoration:none">Open Preview</a>
                            <button class="btn btn-trigger" onclick="window.open('${esc(data.preview_url)}','_blank')">Open in New Tab</button>
                        </div>
                    </div>
                `;
            } catch(e) {
                result.innerHTML = `<div class="empty">Preview error: ${esc(e)}</div>`;
            }
            btn.classList.remove('loading');
            btn.disabled = false;
        }

        async function generateEditorialDraft() {
            const btn = document.getElementById('btn-draft-generate');
            const payload = {
                topic_title: document.getElementById('draft-topic').value.trim(),
                lane: document.getElementById('draft-lane').value,
                platform: document.getElementById('draft-platform').value,
                angle_type: document.getElementById('draft-angle').value.trim(),
                limit_per_task: 3
            };
            if (!payload.topic_title) {
                alert('Enter a topic first.');
                return;
            }
            btn.classList.add('loading');
            btn.disabled = true;
            try {
                const data = await (await fetch('/api/content-drafts/generate', {
                    method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body:JSON.stringify(payload)
                })).json();
                if (data.success) {
                    alert('Draft generated and added to review.');
                    await fetchContentDrafts();
                } else {
                    alert('Draft generation failed: ' + data.error);
                }
            } catch(e) {
                alert('Draft generation error: ' + e);
            }
            btn.classList.remove('loading');
            btn.disabled = false;
        }

        async function fetchContentDrafts() {
            const list = document.getElementById('content-drafts-list');
            try {
                const drafts = await (await fetch('/api/content-drafts')).json();
                if (!drafts.length) {
                    list.innerHTML = '<div class="empty">No content drafts yet. Generate one above.</div>';
                    return;
                }
                list.innerHTML = drafts.slice(0, 10).map(buildDraftCard).join('');
            } catch(e) {
                list.innerHTML = `<div class="empty">Could not load drafts: ${esc(e)}</div>`;
            }
        }

        function buildDraftCard(draft) {
            let content = {};
            let sources = [];
            try { content = JSON.parse(draft.content_json || '{}'); } catch(_) {}
            try { sources = JSON.parse(draft.source_urls_json || '[]'); } catch(_) {}
            const sections = (content.sections || []).slice(0, 4).map(section => `
                <div class="draft-section">
                    <strong>${esc(section.heading)}</strong>
                    <span>${esc(section.body).slice(0, 700)}</span>
                </div>
            `).join('');
            const sourceLinks = sources.slice(0, 5).map(url => `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(url)}</a>`).join('');
            const statusClass = draft.status === 'approved' ? 'approved' : draft.status === 'rejected' ? 'rejected' : 'pending';
            const reviewActions = draft.status === 'pending_review' ? `
                <button class="btn btn-approve" onclick="approveEditorialDraft(${draft.draft_id})">Approve Draft</button>
                <button class="btn btn-reject" onclick="rejectEditorialDraft(${draft.draft_id})">Reject Draft</button>
            ` : '';
            return `
                <div class="draft-card" id="draft-${draft.draft_id}">
                    <div class="draft-title">${esc(draft.title)}</div>
                    <div class="draft-dek">${esc(draft.dek || '')}</div>
                    <div class="lab-meta">
                        <span class="lab-chip ${statusClass}">${esc(draft.status)}</span>
                        <span class="lab-chip">${esc(draft.platform)}</span>
                        <span class="lab-chip">${esc(draft.lane)}</span>
                    </div>
                    ${sections || '<div class="draft-section">No sections parsed.</div>'}
                    ${content.call_to_action ? `<div class="draft-section"><strong>CTA</strong>${esc(content.call_to_action)}</div>` : ''}
                    ${sourceLinks ? `<div class="source-links"><strong style="font-size:.78rem">Sources used</strong>${sourceLinks}</div>` : ''}
                    <div class="lab-actions">${reviewActions}</div>
                </div>
            `;
        }

        async function approveEditorialDraft(id) {
            const data = await (await fetch(`/api/content-drafts/${id}/approve`, {method:'POST'})).json();
            if (data.success) fetchContentDrafts();
            else alert('Could not approve draft.');
        }

        async function rejectEditorialDraft(id) {
            const reason = prompt('Why reject this draft?') || '';
            const data = await (await fetch(`/api/content-drafts/${id}/reject`, {
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body:JSON.stringify({reason})
            })).json();
            if (data.success) fetchContentDrafts();
            else alert('Could not reject draft.');
        }

        // Initial load
        fetchPendingReview();
        </script>
    </body>
    </html>
    """

if __name__ == '__main__':
    print("Starting EGF Dashboard on http://127.0.0.1:5000")
    app.run(debug=True, port=5000)

