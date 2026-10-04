"""Publish single images and carousels to Instagram.

Flow (Instagram API with Instagram Login):
  1. Create a media container for each image (carousel items get is_carousel_item=true)
  2. For carousels, create a CAROUSEL container that lists the children
  3. Wait until the container status is FINISHED
  4. Publish it with /media_publish

Images must be JPEGs at a public HTTPS URL.
"""
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
