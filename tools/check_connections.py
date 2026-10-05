"""Check every connection without posting anything.

Runs from the "check-connections" GitHub Action. Prints OK/FAIL per item.
"""
import json
import os
import sys
from pathlib import Path

import requests

ok = True


def report(name, passed, detail=""):
    global ok
    ok &= passed
    print(f"{'OK  ' if passed else 'FAIL'} {name}" + (f" -> {detail}" if detail else ""))


# 1. Image hosting (GitHub Pages)
base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
first = next(iter(sorted(Path("posts").glob("*/post.json"))), None)
if not base:
    report("PUBLIC_BASE_URL variable", False, "not set")
elif first:
    post = json.loads(first.read_text())
    url = f"{base}/{first.parent.as_posix()}/{post['slides'][0]}"
    try:
        r = requests.get(url, timeout=30)
        report("Image hosting", r.status_code == 200 and "image" in r.headers.get("content-type", ""),
               f"{r.status_code} {r.headers.get('content-type')} {url}")
    except Exception as e:
        report("Image hosting", False, str(e))

# 2. Instagram
tok, uid = os.environ.get("IG_ACCESS_TOKEN"), os.environ.get("IG_USER_ID")
if not (tok and uid):
    report("Instagram secrets", False, "IG_ACCESS_TOKEN or IG_USER_ID missing")
else:
    me = requests.get("https://graph.instagram.com/me",
                      params={"fields": "user_id,username,account_type", "access_token": tok}, timeout=30).json()
    if "error" in me:
        report("Instagram token", False, me["error"].get("message"))
    else:
        report("Instagram token", True, f"@{me.get('username')} ({me.get('account_type')})")
        report("IG_USER_ID matches", str(me.get("user_id")) == uid.strip(),
               f"secret={uid.strip()} account={me.get('user_id')}")
        lim = requests.get(f"https://graph.instagram.com/v23.0/{uid.strip()}/content_publishing_limit",
                           params={"fields": "quota_usage,config", "access_token": tok}, timeout=30).json()
        report("Instagram publish permission", "error" not in lim,
               lim.get("error", {}).get("message", f"used today: {lim.get('data', [{}])[0].get('quota_usage', '?')}"))

# 3. TikTok
key, sec, rt = (os.environ.get(k) for k in ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN"))
if not (key and sec and rt):
    report("TikTok secrets", False, "client key/secret or refresh token missing")
else:
    t = requests.post("https://open.tiktokapis.com/v2/oauth/token/",
                      headers={"Content-Type": "application/x-www-form-urlencoded"},
                      data={"client_key": key, "client_secret": sec, "grant_type": "refresh_token",
                            "refresh_token": rt}, timeout=30).json()
    if "access_token" not in t:
        report("TikTok token", False, t.get("error_description") or t.get("error") or str(t))
    else:
        report("TikTok token", True, f"scopes: {t.get('scope')}")
        new_rt = t.get("refresh_token")
        out = os.environ.get("NEW_SECRETS_FILE")
        if out and new_rt and new_rt != rt:
            with open(out, "a") as fh:
                fh.write(f"TIKTOK_REFRESH_TOKEN={new_rt}\n")
        ci = requests.post("https://open.tiktokapis.com/v2/post/publish/creator_info/query/",
                           headers={"Authorization": f"Bearer {t['access_token']}",
                                    "Content-Type": "application/json; charset=UTF-8"},
                           json={}, timeout=30).json()
        err = ci.get("error", {})
        if err.get("code") not in (None, "ok"):
            report("TikTok posting permission", False, err.get("message") or err.get("code"))
        else:
            d = ci.get("data", {})
            report("TikTok posting permission", True,
                   f"@{d.get('creator_username')} privacy options: {d.get('privacy_level_options')}")

# 4. YouTube (optional until you set it up)
cid, csec, yrt = (os.environ.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))
if not (cid and csec and yrt):
    print("SKIP YouTube -> YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN not set (Shorts won't post to YouTube)")
else:
    t = requests.post("https://oauth2.googleapis.com/token",
                      data={"client_id": cid, "client_secret": csec, "refresh_token": yrt,
                            "grant_type": "refresh_token"}, timeout=30).json()
    if "access_token" not in t:
        report("YouTube token", False, t.get("error_description") or t.get("error") or str(t))
    else:
        report("YouTube token", True, f"scopes: {t.get('scope')}")
        ch = requests.get("https://www.googleapis.com/youtube/v3/channels",
                          params={"part": "snippet", "mine": "true"},
                          headers={"Authorization": f"Bearer {t['access_token']}"}, timeout=30).json()
        items = ch.get("items") or []
        report("YouTube channel", bool(items),
               items[0]["snippet"]["title"] if items else (ch.get("error", {}).get("message") or "no channel on this account"))

# 5. Short videos are reachable on GitHub Pages (Instagram fetches Reels by URL)
shorts = [f for f in sorted(Path("posts").glob("*/post.json")) if json.loads(f.read_text()).get("type") == "short"]
pending_video = next((f for f in shorts if (f.parent / json.loads(f.read_text()).get("video", "")).exists()), None)
if base and pending_video:
    v = json.loads(pending_video.read_text())["video"]
    url = f"{base}/{pending_video.parent.as_posix()}/{v}"
    try:
        r = requests.head(url, allow_redirects=True, timeout=30)
        report("Video hosting", r.status_code == 200, f"{r.status_code} {r.headers.get('content-type')} {url}")
    except Exception as e:
        report("Video hosting", False, str(e))

# 6. Media repo (shorts): index readable, next video reachable
mbase = os.environ.get("MEDIA_BASE_URL", "").rstrip("/")
if not mbase:
    print("SKIP Media repo -> MEDIA_BASE_URL variable not set (shorts from the media repo won't post)")
else:
    try:
        r = requests.get(f"{mbase}/shorts/index.json", timeout=30)
        entries = r.json() if r.status_code == 200 else None
        report("Media repo index", isinstance(entries, list),
               f"{len(entries)} shorts scheduled" if isinstance(entries, list) else f"{r.status_code} {mbase}/shorts/index.json")
        if entries:
            e = sorted(entries, key=lambda x: x["publish_at"])[-1]
            url = f"{mbase}/shorts/{e.get('folder', e['id'])}/{e['video']}"
            h = requests.head(url, allow_redirects=True, timeout=30)
            report("Media repo video hosting", h.status_code == 200, f"{h.status_code} {url}")
    except Exception as ex:
        report("Media repo index", False, str(ex))

print("\nALL GOOD" if ok else "\nSomething needs fixing (see FAIL lines)")
sys.exit(0 if ok else 1)
