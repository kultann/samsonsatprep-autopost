"""Publish photo carousels and videos to TikTok with the Content Posting API.

Notes
- Until TikTok audits the app, posts can only be PRIVATE (SELF_ONLY).
  The code reads the allowed privacy levels from creator_info and uses
  PUBLIC_TO_EVERYONE when it's allowed, otherwise the most private option.
- Photo URLs must sit under a domain or URL prefix verified in the TikTok
  developer portal. Videos are sent as a file upload instead (no URL needed).
- Videos: mode "direct" posts straight to the profile (video.publish);
  mode "draft" drops it in the TikTok inbox to finish in-app (video.upload),
  e.g. to add a trending sound yourself.
- Access tokens last ~24h, so every run refreshes using the refresh token.
  TikTok can rotate the refresh token; the runner saves the new one.
"""
import os

import requests

from . import config


class TikTokError(RuntimeError):
    pass


def refresh_access_token():
    """Returns (access_token, refresh_token)."""
    r = requests.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": config.TIKTOK_CLIENT_KEY,
            "client_secret": config.TIKTOK_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": config.TIKTOK_REFRESH_TOKEN,
        },
        timeout=60,
    )
    data = r.json()
    if "access_token" not in data:
        raise TikTokError(f"token refresh failed: {data}")
    return data["access_token"], data.get("refresh_token", config.TIKTOK_REFRESH_TOKEN)


def _call(path, token, body):
    r = requests.post(
        f"{config.TIKTOK_API}/{path}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
        json=body,
        timeout=60,
    )
    data = r.json()
    err = data.get("error", {})
    if r.status_code >= 400 or (err.get("code") not in (None, "ok")):
        raise TikTokError(f"{path} failed: {data}")
    return data.get("data", {})


def _pick_privacy(options):
    """Public if TikTok allows it, otherwise the most private option."""
    if "PUBLIC_TO_EVERYONE" in options:
        return "PUBLIC_TO_EVERYONE"
    return "SELF_ONLY" if "SELF_ONLY" in options else options[0]


def publish_photos(token, image_urls, title, description):
    """Direct-post a photo carousel. Returns the publish_id."""
    if config.DRY_RUN:
        print(f"[dry-run] TikTok would publish {len(image_urls)} photo(s)")
        return "dry-run"

    info = _call("post/publish/creator_info/query/", token, {})
    privacy = _pick_privacy(info.get("privacy_level_options", ["SELF_ONLY"]))
    if privacy != "PUBLIC_TO_EVERYONE":
        print(f"TikTok: public posting not allowed yet, posting as {privacy}")

    body = {
        "media_type": "PHOTO",
        "post_mode": "DIRECT_POST",
        "post_info": {
            "title": title[:90],
            "description": description[:4000],
            "privacy_level": privacy,
            "disable_comment": False,
            "auto_add_music": True,
        },
        "source_info": {
            "source": "PULL_FROM_URL",
            "photo_cover_index": 0,
            "photo_images": image_urls[:35],
        },
    }
    try:
        return _call("post/publish/content/init/", token, body).get("publish_id")
    except TikTokError as e:
        # Unaudited apps list PUBLIC as an option but reject it; retry privately.
        if "unaudited" in str(e) and privacy != "SELF_ONLY":
            print("TikTok: app not audited yet, retrying as SELF_ONLY (private)")
            body["post_info"]["privacy_level"] = "SELF_ONLY"
            return _call("post/publish/content/init/", token, body).get("publish_id")
        raise


# ---------------- video ----------------
CHUNK = 10 * 1024 * 1024
MAX_SINGLE = 64 * 1024 * 1024


def _chunk_plan(size):
    """TikTok: one chunk up to 64 MB; above that 5-64 MB chunks, last one takes the remainder."""
    if size <= MAX_SINGLE:
        return size, 1
    return CHUNK, size // CHUNK


def _upload(upload_url, path, size, chunk, count):
    with open(path, "rb") as fh:
        for i in range(count):
            start = i * chunk
            end = size - 1 if i == count - 1 else start + chunk - 1
            fh.seek(start)
            body = fh.read(end - start + 1)
            r = requests.put(upload_url, data=body, timeout=600, headers={
                "Content-Type": "video/mp4",
                "Content-Length": str(len(body)),
                "Content-Range": f"bytes {start}-{end}/{size}",
            })
            if r.status_code not in (200, 201, 206):
                raise TikTokError(f"upload chunk {i + 1}/{count} failed: {r.status_code} {r.text[:300]}")


def publish_video(token, path, caption, cover_ms=None, ai_label=True, mode="direct"):
    """Post an MP4 (direct to profile, or to the inbox as a draft). Returns the publish_id."""
    if config.DRY_RUN:
        print(f"[dry-run] TikTok would {'draft' if mode == 'draft' else 'post'} video {path}")
        return "dry-run"

    size = os.path.getsize(path)
    chunk, count = _chunk_plan(size)
    source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": count}

    if mode == "draft":
        data = _call("post/publish/inbox/video/init/", token, {"source_info": source})
    else:
        info = _call("post/publish/creator_info/query/", token, {})
        privacy = _pick_privacy(info.get("privacy_level_options", ["SELF_ONLY"]))
        if privacy != "PUBLIC_TO_EVERYONE":
            print(f"TikTok: public posting not allowed yet, posting as {privacy}")
        post_info = {
            "title": caption[:2200],
            "privacy_level": privacy,
            "disable_comment": False,
            "disable_duet": False,
            "disable_stitch": False,
            "is_aigc": bool(ai_label),
        }
        if cover_ms is not None:
            post_info["video_cover_timestamp_ms"] = int(cover_ms)
        body = {"post_info": post_info, "source_info": source}
        try:
            data = _call("post/publish/video/init/", token, body)
        except TikTokError as e:
            if "unaudited" in str(e) and privacy != "SELF_ONLY":
                print("TikTok: app not audited yet, retrying as SELF_ONLY (private)")
                body["post_info"]["privacy_level"] = "SELF_ONLY"
                data = _call("post/publish/video/init/", token, body)
            else:
                raise

    _upload(data["upload_url"], path, size, chunk, count)
    return data.get("publish_id")
