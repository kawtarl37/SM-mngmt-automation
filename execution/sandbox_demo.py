"""
sandbox_demo.py
---------------
Pinterest API Sandbox Demo - for Standard Access application video.

This script demonstrates full Pinterest API usage against the official
Sandbox environment (api-sandbox.pinterest.com):

  1. Authenticate using an existing access token (or sandbox token).
  2. List boards available in the sandbox account.
  3. Create a new Pin via POST /pins.
  4. Retrieve the newly created Pin via GET /pins/{pin_id}.
  5. Print the confirmed response — proving the Pin exists on Pinterest.

Run from project root:
    python -m execution.sandbox_demo

Requirements:
    - PINTEREST_ACCESS_TOKEN set in .env  (your current production token also
      works for the sandbox; the subdomain is the only difference)
    - PINTEREST_BOARD_ID set in .env
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

# ── Load env ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

ACCESS_TOKEN = os.getenv("PINTEREST_SANDBOX_TOKEN") or os.getenv("PINTEREST_ACCESS_TOKEN", "")
BOARD_ID     = os.getenv("PINTEREST_BOARD_ID", "")

if not os.getenv("PINTEREST_SANDBOX_TOKEN"):
    print("[WARN] PINTEREST_SANDBOX_TOKEN not set in .env")
    print("       To get a sandbox token:")
    print("       1. Go to: https://developer.pinterest.com/apps/")
    print("       2. Select 'Manage' for your app")
    print("       3. In the Configure tab, scroll to 'Generate Access Token'")
    print("       4. Choose 'Sandbox' environment, click 'Generate token'")
    print("       5. Add PINTEREST_SANDBOX_TOKEN=<token> to your .env")
    print("       Using production token as fallback...\n")

# ── Sandbox base URL ──────────────────────────────────────────────────────────
SANDBOX_BASE = "https://api-sandbox.pinterest.com/v5"

HEADERS = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json",
}

# ── Helpers ───────────────────────────────────────────────────────────────────
SEP  = "=" * 65
SEP2 = "-" * 65

def _print_request(method: str, url: str, payload: dict | None = None):
    print(f"\n{SEP}")
    print(f"  >>  {method}  {url}")
    if payload:
        print(f"{SEP2}")
        print("  Request Body:")
        print(json.dumps(payload, indent=4))
    print(SEP)

def _print_response(resp: requests.Response):
    print(f"  HTTP {resp.status_code}  {resp.reason}")
    print(SEP2)
    try:
        data = resp.json()
        print(json.dumps(data, indent=4))
    except Exception:
        print(resp.text)
    print(SEP)

def _check(resp: requests.Response, step: str):
    if not resp.ok:
        print(f"\n[FAIL]  Step failed: {step}")
        _print_response(resp)
        sys.exit(1)

# ── Step 0: Validate token ────────────────────────────────────────────────────
def validate_token():
    print(f"\n{SEP}")
    print("  STEP 0 - Verify Sandbox access token (GET /user_account)")
    url = f"{SANDBOX_BASE}/user_account"
    _print_request("GET", url)
    resp = requests.get(url, headers=HEADERS, timeout=15)
    _print_response(resp)
    _check(resp, "validate token")
    username = resp.json().get("username", "unknown")
    print(f"  [OK]  Authenticated as: @{username}")
    return resp.json()

# ── Step 1: List boards ───────────────────────────────────────────────────────
def list_boards():
    print(f"\n{SEP}")
    print("  STEP 1 - List boards (GET /boards)")
    url = f"{SANDBOX_BASE}/boards"
    _print_request("GET", url)
    resp = requests.get(url, headers=HEADERS, timeout=15)
    _print_response(resp)
    _check(resp, "list boards")
    boards = resp.json().get("items", [])
    print(f"  [OK]  Found {len(boards)} board(s)")
    return boards

# ── Step 2: Create a Pin ──────────────────────────────────────────────────────
def create_pin(board_id: str) -> dict:
    print(f"\n{SEP}")
    print("  STEP 2 - Create a Pin (POST /pins)")

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    payload = {
        "board_id": board_id,
        "title": f"Easy Gluten-Free Banana Pancakes [{timestamp}]",
        "description": (
            "Light, fluffy, and completely gluten-free! "
            "These banana oat pancakes are ready in 15 minutes — "
            "perfect for a wholesome weekend breakfast. "
            "#GlutenFree #HealthyBreakfast #EasyRecipe"
        ),
        "link": "https://easygluten-free.com/recipes/banana-oat-pancakes/",
        "media_source": {
            "source_type": "image_url",
            "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/14/Gatto_europeo4.jpg/1024px-Gatto_europeo4.jpg",
        },
        "alt_text": "Stack of gluten-free banana oat pancakes on a rustic plate",
    }

    url = f"{SANDBOX_BASE}/pins"
    _print_request("POST", url, payload)
    resp = requests.post(url, headers=HEADERS, json=payload, timeout=30)
    _print_response(resp)
    _check(resp, "create pin")

    pin_data = resp.json()
    pin_id = pin_data.get("id")
    print(f"  [OK]  Pin created!  pinterest_id = {pin_id}")
    return pin_data

# ── Step 3: Retrieve the Pin ──────────────────────────────────────────────────
def get_pin(pin_id: str) -> dict:
    print(f"\n{SEP}")
    print(f"  STEP 3 - Retrieve the Pin (GET /pins/{pin_id})")
    url = f"{SANDBOX_BASE}/pins/{pin_id}"
    _print_request("GET", url)
    resp = requests.get(url, headers=HEADERS, timeout=15)
    _print_response(resp)
    _check(resp, "get pin")
    print(f"  [OK]  Pin confirmed on Pinterest Sandbox!  id = {resp.json().get('id')}")
    return resp.json()

# ── Step 4: List pins on board ────────────────────────────────────────────────
def list_board_pins(board_id: str) -> dict:
    print(f"\n{SEP}")
    print(f"  STEP 4 - List Pins on board (GET /boards/{board_id}/pins)")
    url = f"{SANDBOX_BASE}/boards/{board_id}/pins"
    _print_request("GET", url)
    resp = requests.get(url, headers=HEADERS, timeout=15)
    _print_response(resp)
    _check(resp, "list board pins")
    pins = resp.json().get("items", [])
    print(f"  [OK]  Board now contains {len(pins)} pin(s)")
    return resp.json()

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"\n{'#'*65}")
    print("  Easy Gluten-Free - Pinterest API Sandbox Demo")
    print("  Demonstrating: Create Pin -> Retrieve Pin -> Confirm on platform")
    print(f"{'#'*65}")

    if not ACCESS_TOKEN:
        print("[ERR]  PINTEREST_ACCESS_TOKEN is missing from .env")
        sys.exit(1)

    if not BOARD_ID:
        print("[ERR]  PINTEREST_BOARD_ID is missing from .env")
        sys.exit(1)

    print(f"\n  Sandbox endpoint: {SANDBOX_BASE}")
    print(f"  Board ID in use:  {BOARD_ID}")
    print(f"  Token (first 30): {ACCESS_TOKEN[:30]}...")

    # Run demo steps
    validate_token()
    boards = list_boards()

    # Use the configured board or fall back to first sandbox board
    board_id = BOARD_ID
    if boards:
        # Prefer matching board; otherwise use first returned
        matched = next((b for b in boards if b["id"] == board_id), None)
        if not matched:
            board_id = boards[0]["id"]
            print(f"\n  [WARN]  Configured board not in sandbox - using: {board_id}")

    pin_data  = create_pin(board_id)
    pin_id    = pin_data["id"]
    get_pin(pin_id)
    list_board_pins(board_id)

    print(f"\n{'#'*65}")
    print("  [DONE] DEMO COMPLETE - Pin successfully created & confirmed in sandbox")
    print(f"  Pinterest Sandbox Pin ID: {pin_id}")
    print(f"  Board ID:                 {board_id}")
    print(f"  View in sandbox UI:       https://developer.pinterest.com/docs/developer-tools/sandbox/")
    print(f"{'#'*65}\n")


if __name__ == "__main__":
    main()
