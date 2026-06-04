import os
import sys
import json
import uuid
import base64
import secrets
import sqlite3
import threading
import requests as http_requests
from flask import Flask, jsonify, request, send_from_directory, redirect
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
from execution.content.recipe_wp_publisher import publish_recipe_to_wp
from execution.content.pinterest_publisher import post_pin_to_pinterest

# ── Async recipe generation task store ──────────────────────────────────────
# task_id → {"status": "running"|"done"|"error", "result": dict|None, "error": str}
_RECIPE_TASKS: dict = {}
_RECIPE_TASKS_LOCK = threading.Lock()

# DB initialization imports
from execution.db import init_db, seed_amazon_products
from execution.database import Base, engine

app = Flask(__name__)
CORS(app)

# Auto-initialize all databases and tables if they don't exist
init_db()
seed_amazon_products()
Base.metadata.create_all(bind=engine)

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ──────────────────────────────────────────────
# API: Pins
# ──────────────────────────────────────────────

@app.route('/api/pins', methods=['GET'])
def get_pending_pins():
    conn = get_db_connection()
    cursor = conn.cursor()
    # Left join to accommodate custom pins where idea_id = 0
    cursor.execute("""
        SELECT p.pin_id, p.title, p.description, p.image_path, p.status, p.seo_keywords,
               c.content_type
        FROM generated_pins p
        LEFT JOIN content_ideas c ON p.idea_id = c.idea_id
        WHERE p.status = 'pending'
    """)
    pins = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(pins)

@app.route('/api/pins/<int:pin_id>/approve', methods=['POST'])
def approve_pin(pin_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE generated_pins SET status = 'approved' WHERE pin_id = ?", (pin_id,))
    conn.commit()
    conn.close()

    # Auto-schedule the pin for publishing
    try:
        schedule_approved_pins()
    except Exception as e:
        return jsonify({"success": True, "warning": f"Pin approved but scheduling failed: {e}"}), 200

    return jsonify({"success": True, "message": "Pin approved and added to publish queue."})

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

# ──────────────────────────────────────────────
# API: Publish Schedule Queue
# ──────────────────────────────────────────────

@app.route('/api/schedule', methods=['GET'])
def get_schedule():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.schedule_id, s.pin_id, s.scheduled_time, s.status,
               s.error_message, s.completed_at,
               p.title as pin_title,
               b.wp_url
        FROM publish_schedule s
        JOIN generated_pins p ON s.pin_id = p.pin_id
        LEFT JOIN blogs b ON s.blog_id = b.blog_id
        ORDER BY s.scheduled_time ASC
        LIMIT 30
    """)
    schedule = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(schedule)

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

def _run_recipe_task(task_id: str):
    """Background worker: generate recipe and store result in _RECIPE_TASKS."""
    try:
        result = generate_recipe()
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
    task_id = str(uuid.uuid4())
    with _RECIPE_TASKS_LOCK:
        _RECIPE_TASKS[task_id] = {"status": "running", "result": None, "error": None}
    t = threading.Thread(target=_run_recipe_task, args=(task_id,), daemon=True)
    t.start()
    return jsonify({"task_id": task_id})


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
        row.get("cover_image", ""),
        row["wp_url"],
    ))
    temp_pin_id = pin_cur.lastrowid
    pin_conn.commit()
    pin_conn.close()

    try:
        # Get media_url from WP for the cover image
        import requests as _req
        from execution.config import WP_BASE_URL, WP_USERNAME, WP_APP_PASSWORD
        media_url = None
        if row.get("wp_post_id"):
            try:
                resp = _req.get(
                    f"{WP_BASE_URL}/wp-json/wp/v2/posts/{row['wp_post_id']}",
                    auth=(WP_USERNAME, WP_APP_PASSWORD), timeout=10
                )
                featured_id = resp.json().get("featured_media", 0)
                if featured_id:
                    mresp = _req.get(
                        f"{WP_BASE_URL}/wp-json/wp/v2/media/{featured_id}",
                        auth=(WP_USERNAME, WP_APP_PASSWORD), timeout=10
                    )
                    media_url = mresp.json().get("source_url")
            except Exception:
                pass

        result = post_pin_to_pinterest(
            pin_id=temp_pin_id,
            wp_url=row["wp_url"],
            media_url=media_url or ""
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
            title=caption_resp.pin_title,
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
        image_path = generate_pin_image(caption_resp.pin_title, pin_id, subtitle=subtitle)
        if image_path:
            conn = get_db_connection()
            conn.execute("UPDATE generated_pins SET image_path=? WHERE pin_id=?", (image_path, pin_id))
            conn.commit()
            conn.close()
    except Exception:
        pass

    # 5. Generate Blog
    try:
        blog_data = generate_blog(pin_id)
        if not blog_data:
            return jsonify({"success": False, "error": "Blog generation failed."}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    # 6. Schedule approved pin
    try:
        schedule_approved_pins()
    except Exception as e:
        return jsonify({"success": True, "warning": f"Blog generated but scheduling failed: {e}", "pin_id": pin_id}), 200

    # 7. Update trend status
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
            .modal .actions{display:flex;gap:8px;justify-content:flex-end}
            .btn-close{background:#eee;color:#333;padding:9px 18px;border:none;border-radius:8px;cursor:pointer;font-weight:600;font-family:inherit}

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
            button:disabled{opacity:.45;cursor:not-allowed!important}

            /* ── Approved section divider ── */
            .section-divider{margin:28px 0 18px;padding:10px 16px;background:linear-gradient(135deg,#e8f5e9,#f0f9f0);border-radius:10px;border-left:4px solid #27ae60}
            .section-divider h3{font-size:.95rem;color:#1e8449;font-weight:700}
            .section-divider p{font-size:.8rem;color:#666;margin-top:2px}
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
                    <button class="btn-hdr btn-hdr-recipe" id="btn-gen-recipe" onclick="startRecipeGeneration()">
                        <span class="spinner"></span>🍽️ Generate Recipe
                    </button>
                    <button class="btn-hdr btn-hdr-primary" onclick="openGenModal()">+ Generate Content</button>
                    <button class="btn-hdr btn-hdr-ghost" onclick="reauthorizePinterest()" title="Re-run Pinterest OAuth">🔑 Re-auth</button>
                </div>
            </div>
            <nav class="tab-nav">
                <button class="tab-btn active" id="tabnav-pending" onclick="showTab('tab-pending',this)">Pending Review</button>
                <button class="tab-btn" id="tabnav-queue" onclick="showTab('tab-queue',this)">Publish Queue</button>
                <button class="tab-btn" id="tabnav-recipes" onclick="showTab('tab-recipes',this)">🍽️ Recipes</button>
                <button class="tab-btn" id="tabnav-trends" onclick="showTab('tab-trends',this)">🔥 Trends &amp; Blog Gen</button>
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
            <!-- PENDING PINS -->
            <div id="tab-pending" class="tab-content active">
                <div class="section-header">
                    <p class="section-title">Pins Awaiting Approval</p>
                </div>
                <div id="pins-container" class="pins-grid"><div class="empty">Loading pins…</div></div>
            </div>

            <!-- PUBLISH QUEUE -->
            <div id="tab-queue" class="tab-content">
                <div class="section-header">
                    <p class="section-title">Upcoming Publish Schedule (US Eastern)</p>
                    <button id="btn-run-publish" class="btn btn-trigger" onclick="triggerPublishRunner()">
                        <span class="spinner"></span>Trigger Publish Now
                    </button>
                </div>
                <table class="schedule-table">
                    <thead><tr><th>#</th><th>Pin Title</th><th>Scheduled (EST)</th><th>Status</th><th>Blog Link</th><th>Actions</th></tr></thead>
                    <tbody id="schedule-body"><tr><td colspan="6" style="text-align:center;padding:28px;color:#aaa">Loading…</td></tr></tbody>
                </table>
            </div>

            <!-- RECIPES TAB -->
            <div id="tab-recipes" class="tab-content">
                <div class="section-header">
                    <p class="section-title">Recipe Review Queue</p>
                    <button class="btn btn-trigger" onclick="fetchRecipes()">↻ Refresh</button>
                </div>
                <!-- Pending Recipes -->
                <div id="recipes-pending-container" class="recipes-grid"><div class="empty">No pending recipes. Click "Generate Recipe" to create one.</div></div>
                <!-- Approved Recipes -->
                <div class="section-divider">
                    <h3>✅ Approved Recipes</h3>
                    <p>Publish to WordPress (via WP Recipe Maker), then post to Pinterest.</p>
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
            if (id === 'tab-queue') fetchSchedule();
            else if (id === 'tab-recipes') fetchRecipes();
            else if (id === 'tab-trends') fetchTrends();
            else fetchPins();
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
                if (data.success) { alert('Done! Check Pending Review.'); closeGenModal(); fetchPins(); }
                else alert('Failed: ' + data.error);
            } catch(e) { alert('Error: ' + e); }
            btn.classList.remove('loading'); btn.disabled = false;
        }

        // ── Pins ──
        async function fetchPins() {
            const res = await fetch('/api/pins');
            const pins = await res.json();
            const container = document.getElementById('pins-container');
            if (!pins.length) { container.innerHTML = '<div class="empty">🎉 All caught up! No pending pins.</div>'; return; }
            container.innerHTML = pins.map(pin => {
                const filename = pin.image_path ? pin.image_path.split(/[\\\\/]/).pop() : '';
                const cType = pin.content_type || 'Custom Gen';
                return `<div class="pin-card" id="pin-${pin.pin_id}">
                    <img src="/images/${filename}" class="pin-image" alt="" onerror="this.style.display='none'">
                    <div class="pin-content">
                        <span class="pin-badge">${cType}</span>
                        <div class="pin-title">${pin.title}</div>
                        <div class="pin-desc">${pin.description}</div>
                        <div class="pin-keywords"><strong>Keywords:</strong> ${pin.seo_keywords||'N/A'}</div>
                    </div>
                    <div class="pin-actions">
                        <button class="btn btn-approve" onclick="approvePin(${pin.pin_id})">✓ Approve</button>
                        <button class="btn btn-reject"  onclick="rejectPin(${pin.pin_id})">✗ Reject</button>
                    </div>
                </div>`;
            }).join('');
        }
        async function approvePin(id) {
            if (!confirm('Approve this pin?')) return;
            const data = await (await fetch(`/api/pins/${id}/approve`,{method:'POST'})).json();
            if (data.success) { document.getElementById(`pin-${id}`).remove(); checkEmpty('pins-container','<div class="empty">🎉 No pending pins.</div>'); alert(data.message||'Approved!'); }
        }
        async function rejectPin(id) {
            const reason = prompt('Rejection reason (optional):') || '';
            const data = await (await fetch(`/api/pins/${id}/reject`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason})})).json();
            if (data.success) { document.getElementById(`pin-${id}`).remove(); checkEmpty('pins-container','<div class="empty">🎉 No pending pins.</div>'); }
        }
        function checkEmpty(cid, html) { const c=document.getElementById(cid); if(c&&!c.querySelector('.pin-card,.recipe-card')) c.innerHTML=html; }

        // ── Schedule ──
        async function fetchSchedule() {
            const rows = await (await fetch('/api/schedule')).json();
            const tbody = document.getElementById('schedule-body');
            if (!rows.length) { tbody.innerHTML='<tr><td colspan="6" style="text-align:center;padding:28px;color:#aaa">No scheduled publishes yet.</td></tr>'; return; }
            tbody.innerHTML = rows.map((r,i) => {
                const estTime = new Date(r.scheduled_time).toLocaleString('en-US',{timeZone:'America/New_York',dateStyle:'medium',timeStyle:'short'});
                const statusCls = `status-${r.status}`;
                let link = r.wp_url ? `<a href="${r.wp_url}" target="_blank" style="color:#27ae60;font-weight:600">View Post ↗</a>` : '—';
                const err = r.error_message ? `<span class="error-text" title="${r.error_message}">${r.error_message}</span>` : '';
                const actions = (r.status==='pending'||r.status==='failed') ? `<button class="btn btn-publish" onclick="initiatePostNow(${r.pin_id},this)"><span class="spinner"></span>Post Now</button>` : '';
                return `<tr><td>${i+1}</td><td>${r.pin_title}</td><td>${estTime}</td>
                    <td><span class="status-badge ${statusCls}">${r.status}</span>${err}</td>
                    <td>${link}</td><td class="action-col">${actions}</td></tr>`;
            }).join('');
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

        function startRecipeGeneration() {
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
            // Fire the async request
            fetch('/api/recipe/generate', {method:'POST'})
                .then(r => r.json())
                .then(data => {
                    if (!data.task_id) throw new Error('No task_id returned');
                    _recipeTaskId = data.task_id;
                    _recipePollInterval = setInterval(pollRecipeStatus, 2500);
                })
                .catch(e => { stopRecipeLoading(); alert('Failed to start recipe generation: ' + e); btn.disabled = false; });
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
            const all = await (await fetch('/api/recipes')).json();
            const pending  = all.filter(r => r.status === 'pending');
            const approved = all.filter(r => r.status === 'approved' || r.status === 'published');
            renderRecipes('recipes-pending-container',  pending,  true);
            renderRecipes('recipes-approved-container', approved, false);
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
                    <p style="margin-bottom:10px;font-size:.8rem;color:#888">Cover + 3 step photos</p>
                    ${cover ? `<div style="margin-bottom:10px;border-radius:8px;overflow:hidden;max-height:200px"><img src="/images/${cover}" style="width:100%;object-fit:cover"></div>` : ''}
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
            if (!confirm(`Post this recipe to ${env}?\nThe cover image + WP URL will be used as the Pin.`)) return;
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

        async function generateBlogFromTrend(id, btn) {
            if (!confirm('Generate a complete Blog Post and Pinterest Pin for this topic? It will be automatically scheduled in the publish queue.')) return;
            btn.classList.add('loading'); btn.disabled = true;
            try {
                const res = await fetch(`/api/trends/${id}/generate_blog`, {method:'POST'});
                const data = await res.json();
                if (data.success) {
                    alert(`Success! Blog generated: "${data.blog_title}".\nIt has been added to the Publish Queue.`);
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

        // Initial load
        fetchPins();
        </script>
    </body>
    </html>
    """

if __name__ == '__main__':
    print("Starting EGF Dashboard on http://127.0.0.1:5000")
    app.run(debug=True, port=5000)
