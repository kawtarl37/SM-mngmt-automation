import base64
import sys
from pathlib import Path

import requests

# Add project root to sys.path equivalent
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from execution.config import (  # noqa: E402
    GOOGLE_API_KEY,
    IMAGE_GENERATION_PROVIDER,
    OPENAI_API_KEY,
    OPENAI_IMAGE_API_KEY,
    PINTEREST_ACCESS_TOKEN,
    WP_APP_PASSWORD,
    WP_BASE_URL,
    WP_USERNAME,
)


def verify_openai():
    print("Verifying OpenAI API...")
    if not OPENAI_API_KEY:
        print("OPENAI_API_KEY is missing.")
        return False
    try:
        from openai import OpenAI

        client = OpenAI(api_key=OPENAI_API_KEY)
        client.models.list()
        print("OpenAI API is valid.")
        return True
    except Exception as e:
        print(f"OpenAI API verification failed: {e}")
        return False


def verify_image_provider():
    print(f"Verifying image provider: {IMAGE_GENERATION_PROVIDER}...")
    provider = IMAGE_GENERATION_PROVIDER.lower()
    if provider == "openai":
        if not OPENAI_IMAGE_API_KEY:
            print("OPENAI_IMAGE_API_KEY or OPENAI_API_KEY is missing.")
            return False
        print("OpenAI image API key detected.")
        return True
    if provider == "gemini":
        if not GOOGLE_API_KEY:
            print("GOOGLE_API_KEY is missing.")
            return False
        print("Gemini image API key detected.")
        return True
    print("Unsupported IMAGE_GENERATION_PROVIDER. Use 'openai' or 'gemini'.")
    return False


def verify_pinterest():
    print("Verifying Pinterest API...")
    if not PINTEREST_ACCESS_TOKEN:
        print("PINTEREST_ACCESS_TOKEN is missing.")
        return False

    headers = {"Authorization": f"Bearer {PINTEREST_ACCESS_TOKEN}"}
    try:
        resp = requests.get("https://api.pinterest.com/v5/user_account", headers=headers, timeout=20)
        if resp.status_code == 200:
            user_data = resp.json()
            print(f"Pinterest API is valid. Logged in as: {user_data.get('username')}")
            return True
        print(f"Pinterest API returned {resp.status_code}: {resp.text}")
        return False
    except Exception as e:
        print(f"Pinterest API verification failed: {e}")
        return False


def verify_wordpress():
    print("Verifying WordPress API...")
    if not WP_APP_PASSWORD or not WP_USERNAME:
        print("WP_APP_PASSWORD or WP_USERNAME is missing.")
        return False

    auth_str = f"{WP_USERNAME}:{WP_APP_PASSWORD}"
    b64_auth = base64.b64encode(auth_str.encode()).decode()
    headers = {"Authorization": f"Basic {b64_auth}"}

    try:
        test_url = f"{WP_BASE_URL}/wp-json/wp/v2/users/me"
        resp = requests.get(test_url, headers=headers, timeout=20)
        if resp.status_code == 200:
            print("WordPress API is valid.")
            return True
        print(f"WordPress API returned {resp.status_code}: {resp.text}")
        return False
    except Exception as e:
        print(f"WordPress API verification failed: {e}")
        return False


def main():
    print("=" * 60)
    print("EGF SYSTEM CREDENTIAL VERIFICATION")
    print("=" * 60)

    results = [
        verify_openai(),
        verify_image_provider(),
        verify_pinterest(),
        verify_wordpress(),
    ]

    print("=" * 60)
    if all(results):
        print("ALL SYSTEMS GO. Your production credentials are valid.")
    else:
        print("SOME SYSTEMS FAILED. Check the errors above before running the pipeline.")
    print("=" * 60)


if __name__ == "__main__":
    main()
