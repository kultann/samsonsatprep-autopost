"""Publish photo carousels to TikTok with the Content Posting API (Direct Post).

Notes
- Until TikTok audits the app, posts can only be PRIVATE (SELF_ONLY).
  The code reads the allowed privacy levels from creator_info and uses
  PUBLIC_TO_EVERYONE when it's allowed, otherwise the most private option.
- Photo URLs must sit under a domain or URL prefix verified in the TikTok
  developer portal.
- Access tokens last ~24h, so every run refreshes using the refresh token.
  TikTok can rotate the refresh token; the runner saves the new one.
"""
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
    return _call("post/publish/content/init/", token, body).get("publish_id")
