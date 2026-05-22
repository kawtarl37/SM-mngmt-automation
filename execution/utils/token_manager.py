"""
token_manager.py
----------------
Handles Pinterest access token refresh using the refresh token.
Called automatically by pinterest_publisher.py when a 401/403 is received.

For a fresh token from scratch, run:
    python -m execution.utils.pinterest_oauth
"""

import os
import base64
import requests
from pathlib import Path
from dotenv import load_dotenv, set_key

# ── Project root ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = BASE_DIR / ".env"

TOKEN_URL = "https://api.pinterest.com/v5/oauth/token"


def refresh_pinterest_token() -> str | None:
    """
    Use PINTEREST_REFRESH_TOKEN to obtain a new PINTEREST_ACCESS_TOKEN.

    Per Pinterest docs (for apps created before Sept 25, 2025):
      - continuous_refresh=true must have been set during the initial token exchange
        (handled by pinterest_oauth.py) to keep the refresh token alive.
      - Each refresh call rotates both access_token AND refresh_token.
      - New tokens are automatically written back to .env.

    Returns the new access token string, or None on failure.
    """
    load_dotenv(ENV_PATH, override=True)

    app_id        = os.getenv("PINTEREST_APP_ID")
    app_secret    = os.getenv("PINTEREST_APP_SECRET")
    refresh_token = os.getenv("PINTEREST_REFRESH_TOKEN")

    if not all([app_id, app_secret, refresh_token]):
        print("❌ Missing PINTEREST_APP_ID, APP_SECRET, or REFRESH_TOKEN in .env")
        print("   Run: python -m execution.utils.pinterest_oauth")
        return None

    # Basic auth header
    auth_str = f"{app_id}:{app_secret}"
    b64_auth = base64.b64encode(auth_str.encode()).decode()

    headers = {
        "Authorization": f"Basic {b64_auth}",
        "Content-Type":  "application/x-www-form-urlencoded",
    }

    data = {
        "grant_type":    "refresh_token",
        "refresh_token": refresh_token,
        # continuous_refresh keeps the new refresh_token alive too
        "continuous_refresh": "true",
    }

    try:
        print(f"🔄 Refreshing Pinterest access token for App ID {app_id}...")
        resp = requests.post(TOKEN_URL, headers=headers, data=data, timeout=15)
        resp.raise_for_status()
        token_data = resp.json()

        new_access_token  = token_data.get("access_token")
        new_refresh_token = token_data.get("refresh_token")
        expires_in        = token_data.get("expires_in", "unknown")

        if not new_access_token:
            print(f"❌ No access_token in Pinterest response: {token_data}")
            return None

        # Save both tokens back to .env (they rotate on each refresh)
        set_key(str(ENV_PATH), "PINTEREST_ACCESS_TOKEN", new_access_token)
        if new_refresh_token:
            set_key(str(ENV_PATH), "PINTEREST_REFRESH_TOKEN", new_refresh_token)

        print(f"✅ Pinterest access token refreshed. Expires in {expires_in}s.")
        return new_access_token

    except requests.exceptions.HTTPError as e:
        resp_text = e.response.text if e.response is not None else "no body"
        print(f"❌ Pinterest token refresh HTTP error {e.response.status_code}: {resp_text}")

        # Detect expired/invalid refresh token — user must re-authorize
        if e.response is not None and e.response.status_code in [400, 401]:
            print("   ⚠️  Refresh token may be expired or invalid.")
            print("   Run: python -m execution.utils.pinterest_oauth")
        return None

    except Exception as e:
        print(f"❌ Failed to refresh Pinterest token: {e}")
        return None


if __name__ == "__main__":
    token = refresh_pinterest_token()
    if token:
        print(f"New access token: {token[:30]}...")
