import requests
from datetime import datetime, timezone
from execution.config import PINTEREST_ACCESS_TOKEN, PINTEREST_BOARD_ID
from execution.db import get_connection
from execution.utils.logger import setup_logger

logger = setup_logger("pinterest_publisher")

PINTEREST_API_BASE = "https://api.pinterest.com/v5"


def _get_headers() -> dict:
    return {
        "Authorization": f"Bearer {PINTEREST_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def post_pin_to_pinterest(pin_id: int, wp_url: str, media_url: str) -> dict | None:
    """
    Post an approved pin to Pinterest.

    Args:
        pin_id:    The pin_id from generated_pins table.
        wp_url:    The live WordPress blog URL (becomes the pin link).
        media_url: The public WP Media URL for the pin image.

    Returns dict with 'pinterest_id' on success, None on failure.
    """
    logger.info(f"Posting pin_id={pin_id} to Pinterest...")

    # Load pin data from DB
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT pin_id, title, description, seo_keywords
            FROM generated_pins
            WHERE pin_id = ?
        """, (pin_id,))
        pin = cursor.fetchone()

    if not pin:
        logger.error(f"Pin {pin_id} not found in DB.")
        return None

    pin = dict(pin)

    # Pinterest v5 pin creation payload
    payload = {
        "board_id": PINTEREST_BOARD_ID,
        "title": pin["title"],
        "description": pin["description"],
        "link": wp_url,
        "media_source": {
            "source_type": "image_url",
            "url": media_url,
        },
    }

    try:
        response = requests.post(
            f"{PINTEREST_API_BASE}/pins",
            headers=_get_headers(),
            json=payload,
            timeout=30,
        )
        
        # Auto-refresh token if expired (401 Unauthorized or 403 forbidden but NOT Trial limit)
        if response.status_code in [401, 403]:
            error_data = response.json() if response.text else {}
            if error_data.get("code") == 29:
                logger.error("❌ Pinterest 'Trial Access' limit hit. Standard Access is required for production pins.")
                return None
            
            logger.info("Access token potentially expired. Attempting refresh...")
            from execution.utils.token_manager import refresh_pinterest_token
            new_token = refresh_pinterest_token()
            if new_token:
                # Retry once with new token
                logger.info("Retrying with new access token...")
                headers = _get_headers()
                headers["Authorization"] = f"Bearer {new_token}"
                response = requests.post(
                    f"{PINTEREST_API_BASE}/pins",
                    headers=headers,
                    json=payload,
                    timeout=30,
                )

        response.raise_for_status()
        data = response.json()
        pinterest_id = data.get("id")
        logger.info(f"Pin posted to Pinterest: pinterest_id={pinterest_id}")

    except Exception as e:
        logger.error(f"Failed to post pin to Pinterest: {e}")
        if hasattr(e, "response") and e.response is not None:
            logger.error(f"Pinterest API response: {e.response.text}")
        return None

    # Log to posted_pins table
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO posted_pins (pin_id, pinterest_id, board_id, posted_at)
            VALUES (?, ?, ?, ?)
        """, (pin_id, pinterest_id, PINTEREST_BOARD_ID, now))

        # Mark pin as published
        cursor.execute("""
            UPDATE generated_pins SET status = 'published' WHERE pin_id = ?
        """, (pin_id,))
        conn.commit()

    logger.info(f"pin_id={pin_id} marked as published in DB.")
    return {"pinterest_id": pinterest_id, "pin_id": pin_id}
