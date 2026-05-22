"""
pinterest_oauth.py
------------------
One-time OAuth 2.0 setup for the Pinterest API (Authorization Code Flow).

Run this script ONCE to get fresh access + refresh tokens and save them to .env.
After this, token_manager.py handles automatic refreshes.

Usage:
    python -m execution.utils.pinterest_oauth
"""

import os
import sys
import base64
import secrets
import webbrowser
import requests
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv, set_key

# ── Project root & .env path ──────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = BASE_DIR / ".env"

load_dotenv(ENV_PATH, override=True)

# ── Config ────────────────────────────────────────────────────────────────────
APP_ID        = os.getenv("PINTEREST_APP_ID")
APP_SECRET    = os.getenv("PINTEREST_APP_SECRET")
REDIRECT_URI  = "http://localhost:8888/callback"
SCOPES        = "boards:read,pins:read,pins:write"
TOKEN_URL     = "https://api.pinterest.com/v5/oauth/token"
AUTH_BASE_URL = "https://www.pinterest.com/oauth/"

# ── Callback HTTP handler ─────────────────────────────────────────────────────
class _CallbackHandler(BaseHTTPRequestHandler):
    """Tiny HTTP server that catches Pinterest's redirect and extracts the code."""
    auth_code  = None
    csrf_state = None

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        code  = params.get("code",  [None])[0]
        state = params.get("state", [None])[0]

        if state != _CallbackHandler.csrf_state:
            self._respond(400, "❌ CSRF state mismatch. Aborting.")
            return

        if not code:
            self._respond(400, "❌ No authorization code received.")
            return

        _CallbackHandler.auth_code = code
        self._respond(200, (
            "✅ Authorization successful! "
            "You can close this tab and return to the terminal."
        ))

    def _respond(self, status, message):
        body = f"<html><body style='font-family:sans-serif;padding:40px'>" \
               f"<h2>{message}</h2></body></html>"
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):
        pass  # suppress default server logs


def _build_auth_url(state: str) -> str:
    params = {
        "client_id":     APP_ID,
        "redirect_uri":  REDIRECT_URI,
        "response_type": "code",
        "scope":         SCOPES,
        "state":         state,
    }
    return f"{AUTH_BASE_URL}?{urlencode(params)}"


def _exchange_code(code: str) -> dict | None:
    """Exchange authorization code → access_token + refresh_token."""
    auth_str = f"{APP_ID}:{APP_SECRET}"
    b64_auth = base64.b64encode(auth_str.encode()).decode()

    headers = {
        "Authorization": f"Basic {b64_auth}",
        "Content-Type":  "application/x-www-form-urlencoded",
    }

    # continuous_refresh=true ensures the refresh token stays alive
    # Required for apps created BEFORE September 25, 2025
    data = {
        "grant_type":         "authorization_code",
        "code":               code,
        "redirect_uri":       REDIRECT_URI,
        "continuous_refresh": "true",
    }

    try:
        resp = requests.post(TOKEN_URL, headers=headers, data=data, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"❌ Token exchange failed: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"   Pinterest response: {e.response.text}")
        return None


def run_oauth_flow():
    """
    Execute the full OAuth 2.0 Authorization Code Flow.
    Saves PINTEREST_ACCESS_TOKEN and PINTEREST_REFRESH_TOKEN to .env on success.
    """
    if not APP_ID or not APP_SECRET:
        print("❌ PINTEREST_APP_ID or PINTEREST_APP_SECRET is missing from .env")
        sys.exit(1)

    # Generate CSRF state token
    state = secrets.token_urlsafe(16)
    _CallbackHandler.csrf_state = state

    auth_url = _build_auth_url(state)

    print("\n" + "="*60)
    print("🔐 Pinterest OAuth 2.0 Authorization")
    print("="*60)
    print(f"\n📋 App ID:       {APP_ID}")
    print(f"🔗 Redirect URI: {REDIRECT_URI}")
    print(f"📝 Scopes:       {SCOPES}")
    print("\nOpening Pinterest authorization page in your browser...")
    print("If it doesn't open, copy and paste this URL:\n")
    print(auth_url)
    print()

    webbrowser.open(auth_url)

    # Start local server to catch the callback
    print("⏳ Waiting for authorization (listening on port 8888)...")
    server = HTTPServer(("localhost", 8888), _CallbackHandler)
    server.handle_request()  # blocks until one request comes in

    code = _CallbackHandler.auth_code
    if not code:
        print("❌ No authorization code received. Aborting.")
        sys.exit(1)

    print(f"✅ Authorization code received.")
    print("🔄 Exchanging code for access + refresh tokens...")

    token_data = _exchange_code(code)
    if not token_data:
        sys.exit(1)

    access_token  = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in    = token_data.get("expires_in", "unknown")

    if not access_token:
        print(f"❌ No access_token in response: {token_data}")
        sys.exit(1)

    # Save to .env
    set_key(str(ENV_PATH), "PINTEREST_ACCESS_TOKEN",  access_token)
    set_key(str(ENV_PATH), "PINTEREST_REFRESH_TOKEN", refresh_token or "")

    print("\n" + "="*60)
    print("✅ OAuth Complete — Tokens Saved to .env")
    print("="*60)
    print(f"   Access Token:  {access_token[:30]}...")
    print(f"   Refresh Token: {(refresh_token or '')[:30]}...")
    print(f"   Expires In:    {expires_in} seconds")
    if refresh_token:
        print("\n   continuous_refresh=true was set — your refresh token will")
        print("   be automatically renewed on each use.")
    print("\n🚀 You can now restart the dashboard — pins will post to Pinterest.")
    print("="*60 + "\n")

    return {"access_token": access_token, "refresh_token": refresh_token}


if __name__ == "__main__":
    run_oauth_flow()
