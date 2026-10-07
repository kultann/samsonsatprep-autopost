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



# ---------------------------------------------------------------------------
# Long-form videos (longform/<id>/post.json, see autopost/longform.py)
# ---------------------------------------------------------------------------
THUMB_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
CAPTIONS_URL = "https://www.googleapis.com/upload/youtube/v3/captions"
LONG_CHUNK = 32 * 1024 * 1024  # resumable chunks must be multiples of 256 KiB


def upload_video(token, path, title, description, tags=(), privacy="public", publish_at=None,
                 synthetic=False, language="en", category=EDUCATION, notify=True, made_for_kids=False):
    """Upload a long-form video in chunks (resumes after a dropped connection).

    publish_at (RFC 3339, UTC) schedules it: the video is uploaded private and YouTube makes it
    public at that time. Returns (video_id, status dict from the API).
    """
    if publish_at:
        privacy = "private"
    if config.DRY_RUN:
        when = f", publishAt {publish_at}" if publish_at else ""
        print(f"[dry-run] YouTube would upload {path} as {privacy}{when}: {title}")
        return "dry-run", {}

    size = os.path.getsize(path)
    if size <= 0:
        raise YouTubeError(f"{path} is empty")
    status = {"privacyStatus": privacy, "selfDeclaredMadeForKids": bool(made_for_kids),
              "containsSyntheticMedia": bool(synthetic)}
    if publish_at:
        status["publishAt"] = publish_at
    meta = {
        "snippet": {"title": title[:100], "description": description[:5000], "tags": list(tags),
                    "categoryId": str(category), "defaultLanguage": language,
                    "defaultAudioLanguage": language},
        "status": status,
    }
    r = requests.post(
        UPLOAD_URL,
        params={"uploadType": "resumable", "part": "snippet,status",
                "notifySubscribers": "true" if notify else "false"},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"},
        json=meta,
        timeout=60,
    )
    loc = r.headers.get("Location") or r.headers.get("location")
    if r.status_code != 200 or not loc:
        raise YouTubeError(f"upload session failed: {r.status_code} {r.text[:500]}")
    video = _send_chunks(token, loc, path, size)
    got = video.get("status", {})
    if got.get("privacyStatus") and got["privacyStatus"] != privacy:
        print(f"YouTube: uploaded as {got['privacyStatus']} (asked for {privacy}). Unverified API projects "
              "are locked to private until the YouTube API audit passes.")
    elif publish_at and not got.get("publishAt"):
        print("YouTube: the upload came back without a publish time; check it in YouTube Studio "
              "(unverified API projects are locked to private).")
    return video["id"], got


def _resume_point(token, loc, size):
    """Ask YouTube how much of an interrupted upload it has. Returns (finished_video or None, next_offset)."""
    r = requests.put(loc, data=b"", headers={"Authorization": f"Bearer {token}", "Content-Length": "0",
                                             "Content-Range": f"bytes */{size}"}, timeout=60)
    if r.status_code in (200, 201):
        return r.json(), size
    if r.status_code == 308:
        rng = r.headers.get("Range") or r.headers.get("range")
        return None, (int(rng.rsplit("-", 1)[1]) + 1) if rng else 0
    raise YouTubeError(f"couldn't resume the upload: {r.status_code} {r.text[:300]}")


def _send_chunks(token, loc, path, size, chunk=None):
    chunk = chunk or LONG_CHUNK
    offset, errors = 0, 0
    with open(path, "rb") as fh:
        while True:
            fh.seek(offset)
            data = fh.read(chunk)
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "video/mp4",
                       "Content-Length": str(len(data)),
                       "Content-Range": f"bytes {offset}-{offset + len(data) - 1}/{size}"}
            try:
                r = requests.put(loc, data=data, headers=headers, timeout=600)
            except requests.RequestException as e:
                r, problem = None, str(e)
            if r is not None:
                if r.status_code in (200, 201):
                    return r.json()
                if r.status_code == 308:  # chunk stored; YouTube says how far it got
                    rng = r.headers.get("Range") or r.headers.get("range")
                    offset = (int(rng.rsplit("-", 1)[1]) + 1) if rng else 0
                    errors = 0
                    continue
                if r.status_code not in (500, 502, 503, 504):
                    raise YouTubeError(f"upload failed: {r.status_code} {r.text[:500]}")
                problem = f"HTTP {r.status_code}"
            errors += 1
            if errors > 6:
                raise YouTubeError(f"upload failed after retries: {problem}")
            time.sleep(min(60, 5 * 2 ** (errors - 1)))
            done, offset = _resume_point(token, loc, size)
            if done:
                return done


def set_thumbnail(token, video_id, path):
    """Custom thumbnail (the channel must be phone-verified to use custom thumbnails)."""
    if config.DRY_RUN:
        print(f"[dry-run] YouTube would set thumbnail {path} on {video_id}")
        return True
    mime = "image/png" if str(path).lower().endswith(".png") else "image/jpeg"
    with open(path, "rb") as fh:
        body = fh.read()
    r = requests.post(THUMB_URL, params={"videoId": video_id, "uploadType": "media"},
                      headers={"Authorization": f"Bearer {token}", "Content-Type": mime},
                      data=body, timeout=120)
    if r.status_code != 200:
        raise YouTubeError(f"thumbnail failed: {r.status_code} {r.text[:300]}")
    return True


def upload_captions(token, video_id, path, language="en", name="English"):
    """Upload an .srt caption track. Needs the youtube.force-ssl scope (not in the default login)."""
    import json

    if config.DRY_RUN:
        print(f"[dry-run] YouTube would add captions {path} to {video_id}")
        return "dry-run"
    boundary = "sprep" + os.urandom(8).hex()
    meta = json.dumps({"snippet": {"videoId": video_id, "language": language, "name": name, "isDraft": False}})
    with open(path, "rb") as fh:
        srt = fh.read()
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n"
            f"--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n").encode("utf-8") \
        + srt + f"\r\n--{boundary}--\r\n".encode("utf-8")
    r = requests.post(CAPTIONS_URL, params={"part": "snippet", "uploadType": "multipart"},
                      headers={"Authorization": f"Bearer {token}",
                               "Content-Type": f"multipart/related; boundary={boundary}"},
                      data=body, timeout=120)
    if r.status_code != 200:
        raise YouTubeError(f"captions failed: {r.status_code} {r.text[:300]}")
    return r.json().get("id")
