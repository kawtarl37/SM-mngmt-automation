import requests
from datetime import datetime, timezone
from execution.config import (
    PINTEREST_ACCESS_TOKEN,
    PINTEREST_BOARD_ID,
    PINTEREST_SANDBOX_TOKEN,
    PINTEREST_SANDBOX_BOARD_ID,
    SANDBOX_MODE,
)
from execution.db import get_connection
from execution.utils.logger import setup_logger

logger = setup_logger("pinterest_publisher")

# ── API base URLs ─────────────────────────────────────────────────────────────
_PROD_BASE    = "https://api.pinterest.com/v5"
_SANDBOX_BASE = "https://api-sandbox.pinterest.com/v5"


def _api_base() -> str:
    return _SANDBOX_BASE if SANDBOX_MODE else _PROD_BASE


def _active_token() -> str:
    """Return the sandbox token when in sandbox mode, production token otherwise."""
    return PINTEREST_SANDBOX_TOKEN if SANDBOX_MODE else PINTEREST_ACCESS_TOKEN


def _active_board_id() -> str:
    return PINTEREST_SANDBOX_BOARD_ID if SANDBOX_MODE else PINTEREST_BOARD_ID


def _get_headers(token: str | None = None) -> dict:
    return {
        "Authorization": f"Bearer {token or _active_token()}",
        "Content-Type": "application/json",
    }


def post_pin_to_pinterest(pin_id: int, wp_url: str, media_url: str) -> dict | None:
    """
    Post an approved pin to Pinterest.

    When SANDBOX_MODE=True  → calls api-sandbox.pinterest.com (real HTTP, visible on Pinterest sandbox)
    When SANDBOX_MODE=False → calls api.pinterest.com (production)

    Args:
        pin_id:    The pin_id from generated_pins table.
        wp_url:    The live WordPress blog URL (becomes the pin link).
        media_url: The public image URL for the pin.

    Returns dict with 'pinterest_id' on success, None on failure.
    """
    env_label = "[SANDBOX]" if SANDBOX_MODE else "[PRODUCTION]"
    logger.info(f"{env_label} Posting pin_id={pin_id} to Pinterest ({_api_base()})...")

    # ── Load pin data from DB ─────────────────────────────────────────────────
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
    board_id = _active_board_id()

    # ── Build Pinterest v5 payload ────────────────────────────────────────────
    payload = {
        "board_id": board_id,
        "title": pin["title"],
        "description": pin["description"],
        "link": wp_url,
        "media_source": {
            "source_type": "image_url",
            "url": media_url,
        },
    }

    logger.info(f"{env_label} POST {_api_base()}/pins  board_id={board_id}")

    # ── Make the API call (sandbox OR production — both are real HTTP) ────────
    try:
        response = requests.post(
            f"{_api_base()}/pins",
            headers=_get_headers(),
            json=payload,
            timeout=30,
        )

        # Handle token expiry: 401/403 that is NOT the trial-access error (code 29)
        if response.status_code in (401, 403) and not SANDBOX_MODE:
            error_data = response.json() if response.text else {}
            if error_data.get("code") == 29:
                logger.error(
                    "Pinterest 'Trial Access' limit hit (code 29). "
                    "Standard Access is required for production pins."
                )
                return None

            logger.info("Access token potentially expired — attempting refresh...")
            from execution.utils.token_manager import refresh_pinterest_token
            new_token = refresh_pinterest_token()
            if new_token:
                logger.info("Retrying with refreshed access token...")
                response = requests.post(
                    f"{_api_base()}/pins",
                    headers=_get_headers(new_token),
                    json=payload,
                    timeout=30,
                )

        response.raise_for_status()
        data = response.json()
        pinterest_id = data.get("id")
        logger.info(f"{env_label} Pin created on Pinterest!  pinterest_id={pinterest_id}")

    except Exception as e:
        logger.error(f"{env_label} Failed to post pin to Pinterest: {e}")
        if hasattr(e, "response") and e.response is not None:
            logger.error(f"Pinterest API response: {e.response.text}")
        return None

    # ── Log to posted_pins table ──────────────────────────────────────────────
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO posted_pins (pin_id, pinterest_id, board_id, posted_at)
            VALUES (?, ?, ?, ?)
        """, (pin_id, pinterest_id, board_id, now))

        cursor.execute("""
            UPDATE generated_pins SET status = 'published' WHERE pin_id = ?
        """, (pin_id,))
        conn.commit()

    logger.info(f"{env_label} pin_id={pin_id} marked as published in DB.")
    return {"pinterest_id": pinterest_id, "pin_id": pin_id}
