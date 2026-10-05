"""One-time YouTube login to get a refresh token for the auto-poster.

1. Set env vars YT_CLIENT_ID and YT_CLIENT_SECRET (Google Cloud "Desktop app" OAuth client)
2. python3 tools/youtube_auth.py
3. A browser tab opens. Log in with the Google account that owns the @samsonsatprep
   channel, pick that channel, and approve. Google warns the app is unverified:
   click Advanced -> Go to (app name). That's expected for a personal tool.
4. Save the printed value as the GitHub secret YT_REFRESH_TOKEN
"""
import http.server
import os
import secrets
import sys
import urllib.parse
import webbrowser

import requests

PORT = 8765
REDIRECT = f"http://127.0.0.1:{PORT}"
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"

cid, csec = os.environ.get("YT_CLIENT_ID"), os.environ.get("YT_CLIENT_SECRET")
if not (cid and csec):
    sys.exit("Set YT_CLIENT_ID and YT_CLIENT_SECRET first.")

state = secrets.token_urlsafe(16)
got = {}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        got.update({k: v[0] for k, v in q.items()})
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<h2>Done. You can close this tab and go back to Terminal.</h2>")

    def log_message(self, *a):
        pass


url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
    "client_id": cid, "redirect_uri": REDIRECT, "response_type": "code", "scope": SCOPES,
    "access_type": "offline", "prompt": "consent", "state": state,
})
print("\nOpening your browser. If it doesn't open, paste this link:\n\n" + url + "\n")
webbrowser.open(url)
server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
while "code" not in got and "error" not in got:
    server.handle_request()
if got.get("error"):
    sys.exit(f"Google said: {got['error']}")
if got.get("state") != state:
    sys.exit("State mismatch, try again.")

r = requests.post("https://oauth2.googleapis.com/token", data={
    "code": got["code"], "client_id": cid, "client_secret": csec,
    "redirect_uri": REDIRECT, "grant_type": "authorization_code",
}, timeout=60)
data = r.json()
if "refresh_token" not in data:
    sys.exit(f"Failed: {data}")
print("Success. Save this as the GitHub secret YT_REFRESH_TOKEN:\n")
print(data["refresh_token"])
print(f"\n(scopes granted: {data.get('scope')})")
