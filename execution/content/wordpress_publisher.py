import requests
from pathlib import Path
from datetime import datetime, timezone
import time
from execution.config import WP_BASE_URL, WP_USERNAME, WP_APP_PASSWORD, SANDBOX_MODE
from execution.db import get_connection
from execution.utils.logger import setup_logger

logger = setup_logger("wordpress_publisher")


def _get_auth() -> tuple:
    """Return Basic Auth tuple for WP REST API."""
    return (WP_USERNAME, WP_APP_PASSWORD)


# ──────────────────────────────────────────────
# Step 1: Upload image to WP Media Library
# ──────────────────────────────────────────────

def upload_image_to_wp(image_path: str, title: str) -> dict | None:
    """
    Upload a local image file to the WordPress Media Library.
    Returns dict with 'media_id' and 'media_url', or None on failure.
    """
    image_file = Path(image_path)
    if not image_file.exists():
        logger.error(f"Image file not found: {image_path}")
        return None

    if SANDBOX_MODE:
        logger.info("[SANDBOX] Simulating WP image upload (2s)...")
        time.sleep(2)
        return {"media_id": 999123, "media_url": "https://easygluten-free.com/wp-content/uploads/sandbox-image.jpg"}

    url = f"{WP_BASE_URL}/wp-json/wp/v2/media"
    headers = {
        "Content-Disposition": f'attachment; filename="{image_file.name}"',
        "Content-Type": "image/jpeg",
    }

    try:
        with open(image_file, "rb") as f:
            response = requests.post(
                url,
                headers=headers,
                data=f,
                auth=_get_auth(),
                timeout=30
            )
        response.raise_for_status()
        data = response.json()
        media_id = data["id"]
        media_url = data["source_url"]
        logger.info(f"Uploaded image to WP Media: id={media_id}, url={media_url}")
        return {"media_id": media_id, "media_url": media_url}

    except Exception as e:
        logger.error(f"Failed to upload image to WP: {e}")
        return None


# ──────────────────────────────────────────────
# Step 2: Publish blog post to WordPress
# ──────────────────────────────────────────────

def publish_blog_to_wp(blog_id: int) -> dict | None:
    """
    Publish a blog from the blogs table to WordPress.
    Steps:
      1. Load blog record from DB
      2. Upload pin image as featured image
      3. Create WP post (status: publish)
      4. Update blogs table with WP post ID, URL, and featured image ID
    Returns dict with 'wp_url', 'wp_post_id', and 'media_url', or None on failure.
    """
    logger.info(f"Publishing blog_id={blog_id} to WordPress...")

    # Load blog from DB
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT b.blog_id, b.pin_id, b.title, b.html_content, b.category,
                   p.image_path
            FROM blogs b
            JOIN generated_pins p ON b.pin_id = p.pin_id
            WHERE b.blog_id = ?
        """, (blog_id,))
        blog = cursor.fetchone()

    if not blog:
        logger.error(f"Blog {blog_id} not found in DB.")
        return None

    blog = dict(blog)

    # Upload featured image
    image_result = upload_image_to_wp(blog["image_path"], blog["title"])
    featured_image_id = image_result["media_id"] if image_result else None
    media_url = image_result["media_url"] if image_result else None

    # Build WP post payload
    post_payload = {
        "title":          blog["title"],
        "content":        blog["html_content"],
        "status":         "publish",
        "categories":     [],           # category IDs — resolved below
        "featured_media": featured_image_id or 0,
    }

    # Try to resolve category — create if not exists
    category_id = get_or_create_category(blog["category"])
    if category_id:
        post_payload["categories"] = [category_id]

    if SANDBOX_MODE:
        logger.info("[SANDBOX] Simulating WP blog post creation (2s)...")
        time.sleep(2)
        wp_post_id = 999456 + blog_id
        wp_url = f"https://easygluten-free.com/sandbox-post-{blog_id}"
        logger.info(f"Blog published to WordPress (Sandbox): post_id={wp_post_id}, url={wp_url}")
    else:
        # Create the WP post
        try:
            response = requests.post(
                f"{WP_BASE_URL}/wp-json/wp/v2/posts",
                json=post_payload,
                auth=_get_auth(),
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            wp_post_id = data["id"]
            wp_url = data["link"]
            logger.info(f"Blog published to WordPress: post_id={wp_post_id}, url={wp_url}")
        except Exception as e:
            logger.error(f"Failed to create WP post: {e}")
            return None

    # Update DB: save WP post ID, URL, featured image ID, and mark as published
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE blogs
            SET wp_post_id = ?, wp_url = ?, wp_featured_image_id = ?,
                status = 'published', published_at = ?
            WHERE blog_id = ?
        """, (wp_post_id, wp_url, featured_image_id, now, blog_id))

        # Also update the pin's destination_url so the Pinterest post links here
        cursor.execute("""
            UPDATE generated_pins SET destination_url = ? WHERE pin_id = ?
        """, (wp_url, blog["pin_id"]))

        conn.commit()

    logger.info(f"DB updated: blog_id={blog_id} → wp_url={wp_url}")
    return {
        "wp_post_id":  wp_post_id,
        "wp_url":      wp_url,
        "media_url":   media_url,
        "blog_id":     blog_id,
        "pin_id":      blog["pin_id"],
    }


# ──────────────────────────────────────────────
# Helper: category management
# ──────────────────────────────────────────────

def get_or_create_category(name: str) -> int | None:
    """
    Find a WP category by name or create it if it doesn't exist.
    Returns the category ID, or None on failure.
    """
    try:
        # Search for existing category
        resp = requests.get(
            f"{WP_BASE_URL}/wp-json/wp/v2/categories",
            params={"search": name},
            auth=_get_auth(),
            timeout=10
        )
        resp.raise_for_status()
        cats = resp.json()
        for cat in cats:
            if cat["name"].lower() == name.lower():
                return cat["id"]

        # Create new category
        create_resp = requests.post(
            f"{WP_BASE_URL}/wp-json/wp/v2/categories",
            json={"name": name},
            auth=_get_auth(),
            timeout=10
        )
        create_resp.raise_for_status()
        return create_resp.json()["id"]

    except Exception as e:
        logger.warning(f"Could not resolve WP category '{name}': {e}")
        return None
