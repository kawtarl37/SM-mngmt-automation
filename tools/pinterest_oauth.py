"""
Pinterest OAuth 2.0 Authorization Flow

This script starts a local web server to handle the OAuth redirect and exchange
an authorization code for an access token and refresh token.

Requirements:
1. Add PINTEREST_APP_ID and PINTEREST_APP_SECRET to your .env file
2. Add http://localhost:8080/callback as a Redirect URI in your Pinterest App settings.
"""
import os
import requests
import base64
import urllib.parse
from flask import Flask, request, redirect
from dotenv import load_dotenv

# Load config
load_dotenv(override=True)
APP_ID = os.getenv("PINTEREST_APP_ID")
APP_SECRET = os.getenv("PINTEREST_APP_SECRET")
REDIRECT_URI = "http://localhost:8080/callback"

app = Flask(__name__)

if not APP_ID or not APP_SECRET:
    print("❌ ERROR: PINTEREST_APP_ID and PINTEREST_APP_SECRET are not set in .env")
    print("Please add your App ID and App Secret from developers.pinterest.com to .env")
    exit(1)

@app.route("/")
def index():
    # Construct the authorization URL
    scopes = "boards:read,boards:write,pins:read,pins:write"
    auth_url = (
        f"https://www.pinterest.com/oauth/?"
        f"client_id={APP_ID}&"
        f"redirect_uri={urllib.parse.quote(REDIRECT_URI)}&"
        f"response_type=code&"
        f"scope={scopes}&"
        f"state=egf_auth_state"
    )
    return f"""
    <h2>Pinterest OAuth Authorization</h2>
    <p>Click the link below to authorize the app:</p>
    <a href="{auth_url}">Authorize with Pinterest</a>
    """

@app.route("/callback")
def callback():
    code = request.args.get("code")
    state = request.args.get("state")

    if not code:
        return "Error: No authorization code provided.", 400

    print(f"✅ Received authorization code: {code}")
    print("Exchanging code for access token...")

    # Exchange code for token
    auth_str = f"{APP_ID}:{APP_SECRET}"
    b64_auth = base64.b64encode(auth_str.encode()).decode()

    headers = {
        "Authorization": f"Basic {b64_auth}",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI
    }

    try:
        response = requests.post("https://api.pinterest.com/v5/oauth/token", headers=headers, data=data)
        response.raise_for_status()
        token_data = response.json()
        
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        
        # Save to a file to show the user
        with open(".tmp/pinterest_tokens.txt", "w") as f:
            f.write(f"ACCESS_TOKEN={access_token}\n")
            f.write(f"REFRESH_TOKEN={refresh_token}\n")
            
        print("\n🎉 SUCCESS! Tokens generated.")
        print(f"Access Token: {access_token[:20]}...")
        if refresh_token:
            print(f"Refresh Token: {refresh_token[:20]}...")
            
        return f"""
        <h2>Authorization Successful!</h2>
        <p>Your access token has been generated.</p>
        <p>Please check your terminal window or <b>.tmp/pinterest_tokens.txt</b> for the token.</p>
        <p>You can now update your .env file with this new token and close this window.</p>
        """
        
    except Exception as e:
        print(f"❌ Failed to exchange token: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"Response: {e.response.text}")
        return f"Error exchanging token. Check terminal logs.", 500

if __name__ == "__main__":
    print("-" * 60)
    print("Starting Pinterest OAuth Server...")
    print(f"Make sure you have added exactly this Redirect URI to your Pinterest app:")
    print(f"  {REDIRECT_URI}")
    print("-" * 60)
    print("Open this URL in your browser to start:")
    print("  http://localhost:8080")
    print("-" * 60)
    app.run(port=8080)
