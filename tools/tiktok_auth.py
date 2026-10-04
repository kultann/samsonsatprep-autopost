"""One-time TikTok login to get a refresh token for the auto-poster.

1. Set env vars TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, PUBLIC_BASE_URL
2. python tools/tiktok_auth.py
3. Open the printed link, log in as @samsonsatprep, approve
4. You land on callback.html, which shows a code. Paste it here.
5. Save the printed refresh token as the GitHub secret TIKTOK_REFRESH_TOKEN
"""
import os
import secrets
import sys
import urllib.parse

import requests

key = os.environ.get("TIKTOK_CLIENT_KEY")
secret = os.environ.get("TIKTOK_CLIENT_SECRET")
base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
if not (key and secret and base):
    sys.exit("Set TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET and PUBLIC_BASE_URL first.")

redirect_uri = f"{base}/callback.html"
params = {
    "client_key": key,
    "scope": "user.info.basic,video.publish,video.upload",
    "response_type": "code",
    "redirect_uri": redirect_uri,
    "state": secrets.token_urlsafe(16),
}
print("\nOpen this link and approve:\n")
print("https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode(params))
code = urllib.parse.unquote(input("\nPaste the code from the callback page: ").strip())

r = requests.post(
    "https://open.tiktokapis.com/v2/oauth/token/",
    headers={"Content-Type": "application/x-www-form-urlencoded"},
    data={
        "client_key": key,
        "client_secret": secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    },
    timeout=60,
)
data = r.json()
if "refresh_token" not in data:
    sys.exit(f"Failed: {data}")
print("\nSuccess. Save this as the GitHub secret TIKTOK_REFRESH_TOKEN:\n")
print(data["refresh_token"])
print(f"\n(scopes granted: {data.get('scope')})")
