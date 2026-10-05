"""Post everything that's due.

Each post lives in posts/<id>/ with a post.json and its media.
- carousel / image: JPEG slides -> Instagram + TikTok (photo mode)
- short: one vertical MP4 -> Instagram Reels, TikTok video, YouTube Shorts
A post is due when publish_at <= now and it isn't recorded in state/posted.json
for that platform yet. Run this on a schedule (GitHub Actions does it hourly).

Usage:
  python -m autopost.runner            # post what's due (+ prune old short videos)
  python -m autopost.runner --check    # validate every post.json, post nothing
"""
import argparse
import contextlib
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from . import config, instagram, tiktok, youtube

IG_MAX_HASHTAGS = 5
AUTO_TYPES = {"carousel", "image", "short"}  # reels/stories stay manual (trending audio)
SHORT_PLATFORMS = {"instagram", "tiktok", "youtube"}
MAX_VIDEO_MB = 250


def load_posts():
    posts = []
    for f in sorted(Path(config.POSTS_DIR).glob("*/post.json")):
        p = json.loads(f.read_text())
        p["_dir"] = f.parent
        posts.append(p)
    posts += load_media_posts()
    return posts


def load_media_posts():
    """Shorts scheduled in the media repo, read from its Pages site (shorts/index.json)."""
    if not config.MEDIA_BASE_URL:
        return []
    url = f"{config.MEDIA_BASE_URL}/shorts/index.json"
    try:
        r = requests.get(url, timeout=60)
        entries = r.json() if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        entries = None
    if not isinstance(entries, list):
        print(f"WARN couldn't read {url}; skipping media-repo shorts this run")
        return []
    out = []
    for p in entries:
        p["_dir"] = Path("media") / "shorts" / p.get("folder", p["id"])
        p["_media"] = True
        out.append(p)
    return out


def fully_posted(p, state):
    done = state.get(p.get("id"), {})
    return bool(p.get("platforms")) and all(pl in done for pl in p["platforms"])


def validate(p, state=None):
    state = state or {}
    errs = []
    need = ["id", "publish_at", "type", "platforms", "caption"]
    if p.get("type") != "short":
        need.append("slides")
    for key in need:
        if key not in p:
            errs.append(f"missing '{key}'")
    if errs:
        return errs
    try:
        datetime.fromisoformat(p["publish_at"])
    except ValueError:
        errs.append("publish_at must be ISO 8601 with offset, e.g. 2026-10-06T16:00:00-05:00")
    if p["type"] in ("carousel", "image"):
        for s in p["slides"] + p.get("slides_tiktok", []):
            if not s.lower().endswith((".jpg", ".jpeg")):
                errs.append(f"{s}: Instagram needs JPEG")
            if not (p["_dir"] / s).exists():
                errs.append(f"{s}: file not found")
        if p["type"] == "carousel" and not 2 <= len(p["slides"]) <= 20:
            errs.append("carousel needs 2-20 slides")
        if "youtube" in p["platforms"]:
            errs.append("youtube only takes shorts")
    if p["type"] == "short":
        errs += validate_short(p, fully_posted(p, state))
    if len(p.get("hashtags_instagram", [])) > IG_MAX_HASHTAGS:
        errs.append(f"Instagram allows max {IG_MAX_HASHTAGS} hashtags")
    return errs


def validate_short(p, already_posted=False):
    errs = []
    video = p.get("video")
    if not video:
        return ["missing 'video'"]
    if not video.lower().endswith(".mp4"):
        errs.append(f"{video}: needs to be an MP4")
    path = p["_dir"] / video
    if p.get("_media"):
        pass  # lives on the media repo's Pages site; fetched when it's time to post
    elif not path.exists():
        if not already_posted:  # posted shorts get their video pruned; that's fine
            errs.append(f"{video}: file not found")
    elif path.stat().st_size > MAX_VIDEO_MB * 1024 * 1024:
        errs.append(f"{video}: over {MAX_VIDEO_MB} MB")
    cover = p.get("cover")
    if cover and not cover.lower().endswith((".jpg", ".jpeg")):
        errs.append(f"{cover}: cover must be JPEG")
    if cover and not p.get("_media") and not (p["_dir"] / cover).exists():
        errs.append(f"{cover}: file not found")
    bad = set(p["platforms"]) - SHORT_PLATFORMS
    if bad:
        errs.append(f"unknown platform(s) {sorted(bad)}")
    if "youtube" in p["platforms"]:
        yt = p.get("youtube") or {}
        title = yt.get("title", "")
        if not title:
            errs.append("youtube.title missing")
        elif len(title) > 100 or "<" in title or ">" in title:
            errs.append("youtube.title must be <=100 chars with no < or >")
    if p.get("tiktok_mode", "direct") not in ("direct", "draft"):
        errs.append("tiktok_mode must be 'direct' or 'draft'")
    return errs


def public_url(p, name):
    if p.get("_media"):
        return f"{config.MEDIA_BASE_URL}/shorts/{p.get('folder', p['id'])}/{name}"
    return f"{config.PUBLIC_BASE_URL}/{p['_dir'].as_posix()}/{name}"


@contextlib.contextmanager
def local_video(p):
    """Path to the short's MP4: the repo copy, or a temp download from the media repo."""
    path = p["_dir"] / p["video"]
    if path.exists() or config.DRY_RUN:
        yield str(path)
        return
    url = public_url(p, p["video"])
    r = requests.get(url, timeout=300)
    if r.status_code != 200:
        raise RuntimeError(f"couldn't download {url} ({r.status_code})")
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as fh:
        fh.write(r.content)
        tmp = fh.name
    try:
        yield tmp
    finally:
        os.unlink(tmp)


def public_urls(p, key="slides"):
    """Instagram uses 4:5 `slides`; TikTok uses 9:16 `slides_tiktok` when present."""
    files = p.get(key) or p["slides"]
    return [public_url(p, s) for s in files]


def ig_caption(p):
    tags = " ".join(p.get("hashtags_instagram", []))
    return f"{p['caption']}\n\n{tags}".strip()


def tt_description(p):
    tags = " ".join(p.get("hashtags_tiktok", []))
    body = p.get("tiktok_caption") or p["caption"]
    return f"{body}\n\n{tags}".strip()


def yt_fields(p):
    yt = p.get("youtube") or {}
    tags = yt.get("hashtags", [])
    desc = f"{yt.get('description', '')}\n\n{' '.join(tags)}".strip()
    keywords = yt.get("tags") or [t.lstrip("#") for t in tags]
    return yt["title"], desc, keywords


def url_live(url):
    """Pages can lag a few minutes behind a push; Instagram fetches the video by URL."""
    if config.DRY_RUN:
        return True
    try:
        return requests.head(url, allow_redirects=True, timeout=30).status_code == 200
    except requests.RequestException:
        return False


def load_state():
    path = Path(config.STATE_FILE)
    return json.loads(path.read_text()) if path.exists() else {}


def save_state(state):
    path = Path(config.STATE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def write_new_secret(name, value):
    """Hand rotated tokens to the workflow, which saves them as repo secrets."""
    out = os.environ.get("NEW_SECRETS_FILE")
    if out and value:
        with open(out, "a") as fh:
            fh.write(f"{name}={value}\n")


class Tokens:
    """Fetch each platform's access token once per run."""

    def __init__(self):
        self.tt = None
        self.yt = None

    def tiktok(self):
        if self.tt is None and not config.DRY_RUN:
            self.tt, new_refresh = tiktok.refresh_access_token()
            if new_refresh != config.TIKTOK_REFRESH_TOKEN:
                write_new_secret("TIKTOK_REFRESH_TOKEN", new_refresh)
        return self.tt

    def youtube(self):
        if self.yt is None and not config.DRY_RUN:
            self.yt = youtube.access_token()
        return self.yt


def post_one(p, platform, tok):
    """Publish p to one platform. Returns the media id, or None to retry next run."""
    short = p["type"] == "short"
    if platform == "instagram":
        if short:
            url = public_url(p, p["video"])
            if not url_live(url):
                print(f"WAIT {p['id']} -> instagram: video not on GitHub Pages yet ({url})")
                return None
            cover = public_url(p, p["cover"]) if p.get("cover") else None
            return instagram.publish_reel(url, ig_caption(p), cover_url=cover,
                                          thumb_offset_ms=p.get("cover_time_ms"),
                                          share_to_feed=p.get("share_to_feed", True))
        return instagram.publish(public_urls(p), ig_caption(p))
    if platform == "tiktok":
        if short:
            with local_video(p) as path:
                return tiktok.publish_video(tok.tiktok(), path, tt_description(p),
                                            cover_ms=p.get("cover_time_ms"), ai_label=p.get("ai_label", True),
                                            mode=p.get("tiktok_mode", "direct"))
        return tiktok.publish_photos(tok.tiktok(), public_urls(p, "slides_tiktok"),
                                     p.get("tiktok_title", p["caption"].split("\n")[0]), tt_description(p))
    if platform == "youtube" and short:
        title, desc, keywords = yt_fields(p)
        with local_video(p) as path:
            return youtube.upload_short(tok.youtube(), path, title, desc, keywords,
                                        synthetic=p.get("youtube", {}).get("synthetic_media", False))
    raise ValueError(f"unknown platform {platform}")


def prune_videos(posts, state, now):
    """Delete a short's MP4 once every platform has had it for PRUNE_VIDEOS_AFTER_HOURS."""
    if config.PRUNE_VIDEOS_AFTER_HOURS <= 0 or config.DRY_RUN:
        return []
    removed = []
    for p in posts:
        if p.get("type") != "short" or not p.get("video") or p.get("_media") or not fully_posted(p, state):
            continue  # media-repo shorts are pruned by that repo's own workflow
        path = p["_dir"] / p["video"]
        if not path.exists():
            continue
        last = max(datetime.fromisoformat(v["at"]) for v in state[p["id"]].values())
        if now - last >= timedelta(hours=config.PRUNE_VIDEOS_AFTER_HOURS):
            path.unlink()
            removed.append(str(path))
            print(f"PRUNED {path} (posted everywhere)")
    return removed


def run(now=None):
    now = now or datetime.now(timezone.utc)
    state = load_state()
    posts = load_posts()
    due = []
    for p in posts:
        errs = validate(p, state)
        if errs:
            print(f"SKIP {p.get('id', p['_dir'])}: " + "; ".join(errs))
            continue
        if p["type"] not in AUTO_TYPES:
            continue
        if datetime.fromisoformat(p["publish_at"]) <= now:
            pending = [pl for pl in p["platforms"] if pl not in state.get(p["id"], {})]
            if pending:
                due.append((p, pending))

    failures = 0
    if not due:
        print("Nothing due.")
    tok = Tokens()
    for p, pending in due:
        for platform in pending:
            try:
                media_id = post_one(p, platform, tok)
                if media_id is None:
                    continue
                state.setdefault(p["id"], {})[platform] = {
                    "id": media_id,
                    "at": max(now, datetime.now(timezone.utc)).isoformat(timespec="seconds"),
                }
                print(f"POSTED {p['id']} -> {platform} ({media_id})")
            except Exception as e:  # keep going with the other posts
                failures += 1
                print(f"FAILED {p['id']} -> {platform}: {e}")
        if not config.DRY_RUN:
            save_state(state)
    prune_videos(posts, state, now)
    return 1 if failures else 0


def check():
    bad = 0
    state = load_state()
    for p in load_posts():
        errs = validate(p, state)
        status = "OK " if not errs else "BAD"
        bad += bool(errs)
        print(f"{status} {p.get('id', p['_dir'])} {p.get('publish_at', '')} {p.get('type', '')}"
              + ("" if not errs else "  -> " + "; ".join(errs)))
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="validate posts only")
    args = ap.parse_args()
    sys.exit(check() if args.check else run())
