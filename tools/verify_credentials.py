import os
import requests
from pathlib import Path
from dotenv import load_dotenv

# Add project root to sys.path equivalent
import sys
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from execution.config import (
    OPENAI_API_KEY,
    GOOGLE_API_KEY,
    PINTEREST_ACCESS_TOKEN,
    WP_APP_PASSWORD,
    WP_BASE_URL,
    WP_USERNAME
)

def verify_openai():
    print("🔍 Verifying OpenAI API...")
    if not OPENAI_API_KEY:
        print("❌ OPENAI_API_KEY is missing.")
        return False
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        client.models.list()
        print("✅ OpenAI API is valid.")
        return True
    except Exception as e:
        print(f"❌ OpenAI API verification failed: {e}")
        return False

def verify_google():
    print("🔍 Verifying Google (Imagen) API...")
    if not GOOGLE_API_KEY:
        print("❌ GOOGLE_API_KEY is missing.")
        return False
    # Simplified check (just check if key exists, real check requires a generation)
    print("✅ Google API key detected.")
    return True

def verify_pinterest():
    print("🔍 Verifying Pinterest API...")
    if not PINTEREST_ACCESS_TOKEN:
        print("❌ PINTEREST_ACCESS_TOKEN is missing.")
        return False
    
    headers = {"Authorization": f"Bearer {PINTEREST_ACCESS_TOKEN}"}
    try:
        resp = requests.get("https://api.pinterest.com/v5/user_account", headers=headers)
        if resp.status_code == 200:
            user_data = resp.json()
            print(f"✅ Pinterest API is valid. Logged in as: {user_data.get('username')}")
            return True
        else:
            print(f"❌ Pinterest API returned {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        print(f"❌ Pinterest API verification failed: {e}")
        return False

def verify_wordpress():
    print("🔍 Verifying WordPress API...")
    if not WP_APP_PASSWORD or not WP_USERNAME:
        print("❌ WP_APP_PASSWORD or WP_USERNAME is missing.")
        return False
    
    auth_str = f"{WP_USERNAME}:{WP_APP_PASSWORD}"
    import base64
    b64_auth = base64.b64encode(auth_str.encode()).decode()
    headers = {"Authorization": f"Basic {b64_auth}"}
    
    try:
        test_url = f"{WP_BASE_URL}/wp-json/wp/v2/users/me"
        resp = requests.get(test_url, headers=headers)
        if resp.status_code == 200:
            print("✅ WordPress API is valid.")
            return True
        else:
            print(f"❌ WordPress API returned {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        print(f"❌ WordPress API verification failed: {e}")
        return False

def main():
    print("="*60)
    print("EGF SYSTEM CREDENTIAL VERIFICATION")
    print("="*60)
    
    results = [
        verify_openai(),
        verify_google(),
        verify_pinterest(),
        verify_wordpress()
    ]
    
    print("="*60)
    if all(results):
        print("🚀 ALL SYSTEMS GO! Your production credentials are valid.")
    else:
        print("⚠️ SOME SYSTEMS FAILED. Check the errors above before running the pipeline.")
    print("="*60)

if __name__ == "__main__":
    main()
