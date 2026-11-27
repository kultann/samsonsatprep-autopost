"""Publish single images, carousels and Reels to Instagram.

Flow (Instagram API with Instagram Login):
  1. Create a media container for each image (carousel items get is_carousel_item=true)
  2. For carousels, create a CAROUSEL container that lists the children
  3. Wait until the container status is FINISHED
  4. Publish it with /media_publish

Images must be JPEGs at a public HTTPS URL. Reels need the MP4 at a public HTTPS
URL too (Instagram Login apps can't use resumable upload), so shorts are served
from GitHub Pages like the slides.
"""
import hashlib
import json
import time
import requests

from . import config


class InstagramError(RuntimeError):
    pass


def _post(path, **params):
    params["access_token"] = config.IG_ACCESS_TOKEN
    r = requests.post(f"{config.IG_GRAPH}/{path}", data=params, timeout=60)
    data = r.json() if r.content else {}
    if r.status_code >= 400 or "error" in data:
        raise InstagramError(f"POST {path} failed: {data or r.text}")
    return data


def _get(path, **params):
    params["access_token"] = config.IG_ACCESS_TOKEN
    r = requests.get(f"{config.IG_GRAPH}/{path}", params=params, timeout=60)
    data = r.json() if r.content else {}
    if r.status_code >= 400 or "error" in data:
        raise InstagramError(f"GET {path} failed: {data or r.text}")
    return data


def permalink(media_id):
    """Public link to a published post (None if Instagram doesn't return one)."""
    try:
        return _get(media_id, fields="permalink").get("permalink")
    except InstagramError:
        return None


def _wait_ready(container_id, tries=20, delay=3):
    for _ in range(tries):
        status = _get(container_id, fields="status_code").get("status_code")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise InstagramError(f"container {container_id} status {status}")
        time.sleep(delay)
    raise InstagramError(f"container {container_id} not ready after {tries * delay}s")


def publish(image_urls, caption):
    """Publish one image or a carousel (2-20 images). Returns the new media id."""
    if not image_urls:
        raise InstagramError("no images")
    if config.DRY_RUN:
        print(f"[dry-run] IG would publish {len(image_urls)} image(s)")
        return "dry-run"

    uid = config.IG_USER_ID
    if len(image_urls) == 1:
        container = _post(f"{uid}/media", image_url=image_urls[0], caption=caption)["id"]
    else:
        children = []
        for url in image_urls[:20]:
            cid = _post(f"{uid}/media", image_url=url, is_carousel_item="true")["id"]
            children.append(cid)
        for cid in children:
            _wait_ready(cid)
        container = _post(
            f"{uid}/media",
            media_type="CAROUSEL",
            children=",".join(children),
            caption=caption,
        )["id"]

    _wait_ready(container)
    return _post(f"{uid}/media_publish", creation_id=container)["id"]


def _fb(method, path, **params):
    """Instagram Graph call through Facebook Login (needed for the Audio API)."""
    params["access_token"] = config.IG_FB_TOKEN
    url = f"{config.FB_GRAPH}/{path}"
    r = requests.post(url, data=params, timeout=60) if method == "POST" else requests.get(url, params=params, timeout=60)
    data = r.json() if r.content else {}
    if r.status_code >= 400 or "error" in data:
        raise InstagramError(f"{method} fb:{path} failed: {data or r.text}")
    return data


def trending_audio():
    """Licensed tracks Instagram currently suggests for this account (Sound Collection music)."""
    data = _fb("GET", "ig_audio", ig_user_id=config.IG_FB_USER_ID, audio_type="music")
    return data.get("audio", [])


def pick_audio(seed, min_ms=20000):
    """Pick one track, stable for a given post id so retries reuse the same sound."""
    tracks = [t for t in trending_audio() if t.get("audio_id") and (t.get("duration_in_ms") or 0) >= min_ms]
    if not tracks:
        return None
    tracks = tracks[:15]
    i = int(hashlib.sha1(str(seed).encode()).hexdigest(), 16) % len(tracks)
    return tracks[i]


def _wait_ready_fb(container_id, tries=60, delay=10):
    for _ in range(tries):
        status = _fb("GET", container_id, fields="status_code").get("status_code")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise InstagramError(f"container {container_id} status {status}")
        time.sleep(delay)
    raise InstagramError(f"container {container_id} not ready after {tries * delay}s")


def _reel_params(video_url, caption, cover_url, thumb_offset_ms, share_to_feed):
    params = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "share_to_feed": "true" if share_to_feed else "false",
    }
    if cover_url:
        params["cover_url"] = cover_url
    elif thumb_offset_ms is not None:
        params["thumb_offset"] = str(int(thumb_offset_ms))
    return params


def publish_reel_with_audio(video_url, caption, seed, cover_url=None, thumb_offset_ms=None, share_to_feed=True):
    """Publish through Facebook Login with a trending track under the video.
    Returns (media id, track dict)."""
    track = pick_audio(seed)
    if not track:
        raise InstagramError("no trending audio returned")
    params = _reel_params(video_url, caption, cover_url, thumb_offset_ms, share_to_feed)
    params["audio_configuration"] = json.dumps({
        "audio_id": str(track["audio_id"]),
        "audio_volume": config.IG_AUDIO_VOLUME,
        "video_volume": config.IG_VIDEO_VOLUME,
    })
    uid = config.IG_FB_USER_ID
    container = _fb("POST", f"{uid}/media", **params)["id"]
    _wait_ready_fb(container)
    return _fb("POST", f"{uid}/media_publish", creation_id=container)["id"], track


def publish_reel(video_url, caption, cover_url=None, thumb_offset_ms=None, share_to_feed=True, seed=None, info=None):
    """Publish a Reel from a public MP4 URL. Returns the new media id.
    With IG_FB_TOKEN set, a trending licensed track is added (see config.IG_AUDIO); on any error there
    it falls back to the plain Instagram Login upload. `info` (a dict) gets audio details written into it."""
    if config.DRY_RUN:
        print(f"[dry-run] IG would publish reel {video_url}")
        return "dry-run"
    if config.IG_AUDIO and config.IG_FB_TOKEN:
        try:
            mid, track = publish_reel_with_audio(video_url, caption, seed or video_url, cover_url,
                                                 thumb_offset_ms, share_to_feed)
            print(f"IG audio: {track.get('title')} - {track.get('display_artist')} ({track['audio_id']})")
            if info is not None:
                info["audio"] = {"id": str(track["audio_id"]), "title": track.get("title"),
                                 "artist": track.get("display_artist")}
            return mid
        except (InstagramError, requests.RequestException, ValueError, KeyError) as e:
            print(f"IG audio path failed, posting without added audio: {e}")
            if info is not None:
                info["audio_error"] = str(e)[:300]
    params = _reel_params(video_url, caption, cover_url, thumb_offset_ms, share_to_feed)
    container = _post(f"{config.IG_USER_ID}/media", **params)["id"]
    _wait_ready(container, tries=60, delay=10)  # video processing can take a few minutes
    return _post(f"{config.IG_USER_ID}/media_publish", creation_id=container)["id"]


def comment(media_id, message):
    """Comment on one of our own posts as the account. Needs the instagram_business_manage_comments
    permission on the token. Returns the comment id."""
    if config.DRY_RUN:
        print(f"[dry-run] IG would comment on {media_id}: {message}")
        return "dry-run"
    return _post(f"{media_id}/comments", message=message)["id"]


def refresh_token():
    """Exchange the current long-lived token (60 days) for a fresh one."""
    r = requests.get(
        "https://graph.instagram.com/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": config.IG_ACCESS_TOKEN},
        timeout=60,
    )
    data = r.json()
    if "access_token" not in data:
        raise InstagramError(f"token refresh failed: {data}")
    return data["access_token"]
