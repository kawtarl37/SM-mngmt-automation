import os
import base64
import requests
from pathlib import Path
from dotenv import load_dotenv, set_key

# Resolve project root
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = BASE_DIR / ".env"

def refresh_pinterest_token():
    """
    Use the REFRESH_TOKEN to get a new ACCESS_TOKEN from Pinterest.
    Updates the .env file automatically.
    """
    load_dotenv(ENV_PATH, override=True)
    
    app_id = os.getenv("PINTEREST_APP_ID")
    app_secret = os.getenv("PINTEREST_APP_SECRET")
    refresh_token = os.getenv("PINTEREST_REFRESH_TOKEN")
    
    if not all([app_id, app_secret, refresh_token]):
        print("❌ Missing PINTEREST_APP_ID, APP_SECRET, or REFRESH_TOKEN in .env")
        return None

    print(f"🔄 Refreshing Pinterest access token for App ID {app_id}...")
    
    # Pinterest OAuth Refresh Flow
    auth_str = f"{app_id}:{app_secret}"
    b64_auth = base64.b64encode(auth_str.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {b64_auth}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }
    
    try:
        response = requests.post("https://api.pinterest.com/v5/oauth/token", headers=headers, data=data)
        response.raise_for_status()
        token_data = response.json()
        
        new_access_token = token_data.get("access_token")
        
        if new_access_token:
            # Update .env file
            set_key(str(ENV_PATH), "PINTEREST_ACCESS_TOKEN", new_access_token)
            print("✅ Successfully updated PINTEREST_ACCESS_TOKEN in .env")
            return new_access_token
        else:
            print("❌ No access token in Pinterest response.")
            return None
            
    except Exception as e:
        print(f"❌ Failed to refresh Pinterest token: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"Response: {e.response.text}")
        return None

if __name__ == "__main__":
    refresh_pinterest_token()
