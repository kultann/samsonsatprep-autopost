"""Upload Shorts to YouTube with the Data API v3 (resumable upload).

Notes
- A vertical video of 3 minutes or less is treated as a Short automatically.
- Auth: OAuth refresh token for the channel (tools/youtube_auth.py makes one).
  Publish the Google Cloud OAuth consent screen ("In production"); in "Testing"
  mode Google kills refresh tokens after 7 days.
- Google locks uploads from UNVERIFIED API projects to private. Until the
  project passes the YouTube API audit, Shorts land as private videos; the
  runner logs a warning when that happens.
- Upload quota: 1 call per upload from the Video Uploads bucket (100/day default).
"""
import os
import time

import requests

from . import config

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
EDUCATION = "27"


class YouTubeError(RuntimeError):
    pass


def access_token():
    r = requests.post(
        TOKEN_URL,
        data={
            "client_id": config.YT_CLIENT_ID,
            "client_secret": config.YT_CLIENT_SECRET,
            "refresh_token": config.YT_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        },
        timeout=60,
    )
    data = r.json()
    if "access_token" not in data:
        raise YouTubeError(f"token refresh failed: {data}")
    return data["access_token"]


def upload_short(token, path, title, description, tags=(), synthetic=False, privacy=None):
    """Upload one Short. Returns the video id."""
    privacy = privacy or config.YT_PRIVACY
    if config.DRY_RUN:
        print(f"[dry-run] YouTube would upload {path} as {privacy}: {title}")
        return "dry-run"

    size = os.path.getsize(path)
    meta = {
        "snippet": {"title": title[:100], "description": description[:5000],
                    "tags": list(tags), "categoryId": EDUCATION},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False,
                   "containsSyntheticMedia": bool(synthetic)},
    }
    r = requests.post(
        UPLOAD_URL,
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"},
        json=meta,
        timeout=60,
    )
    loc = r.headers.get("Location") or r.headers.get("location")
    if r.status_code != 200 or not loc:
        raise YouTubeError(f"upload session failed: {r.status_code} {r.text[:500]}")

    with open(path, "rb") as fh:
        body = fh.read()
    for attempt in range(4):
        r = requests.put(loc, data=body, headers={"Authorization": f"Bearer {token}",
                                                  "Content-Type": "video/mp4", "Content-Length": str(size)},
                         timeout=900)
        if r.status_code in (200, 201):
            break
        if r.status_code in (500, 502, 503, 504) and attempt < 3:
            time.sleep(10 * (attempt + 1))
            continue
        raise YouTubeError(f"upload failed: {r.status_code} {r.text[:500]}")

    video = r.json()
    got = video.get("status", {}).get("privacyStatus")
    if got and got != privacy:
        print(f"YouTube: uploaded as {got} (asked for {privacy}). Unverified API projects are "
              "locked to private until the YouTube API audit passes.")
    return video["id"]
