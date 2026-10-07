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

from . import config, instagram, longform, tiktok, youtube

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
    vy = p.get("video_youtube")
    if vy and not vy.lower().endswith(".mp4"):
        errs.append(f"{vy}: needs to be an MP4")
    elif vy and not p.get("_media") and not already_posted and not (p["_dir"] / vy).exists():
        errs.append(f"{vy}: file not found")
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
def local_video(p, name=None):
    """Path to the short's MP4: the repo copy, or a temp download from the media repo."""
    name = name or p["video"]
    path = p["_dir"] / name
    if path.exists() or config.DRY_RUN:
        yield str(path)
        return
    url = public_url(p, name)
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


def cooldown_rules():
    """(platform, text in the error, hours to pause)."""
    return [
        ("instagram", "API access blocked", config.IG_BLOCK_COOLDOWN_HOURS),
        ("tiktok", "app_version_check_failed", config.TIKTOK_APP_COOLDOWN_HOURS),
    ]


def load_cooldowns():
    path = Path(config.COOLDOWN_FILE)
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except ValueError:
        return {}


def save_cooldowns(cool):
    path = Path(config.COOLDOWN_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cool, indent=2, sort_keys=True) + "\n")


def last_ig_post(state):
    """Time of the most recent Instagram publish (feed post or Reel)."""
    times = [datetime.fromisoformat(v["instagram"]["at"]) for v in state.values()
             if isinstance(v, dict) and isinstance(v.get("instagram"), dict) and "at" in v["instagram"]]
    return max(times) if times else None


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
        try:
            return tiktok.publish_photos(tok.tiktok(), public_urls(p, "slides_tiktok"),
                                         p.get("tiktok_title", p["caption"].split("\n")[0]), tt_description(p),
                                         mode=p.get("tiktok_mode", config.TIKTOK_PHOTO_MODE))
        except tiktok.TikTokError as e:
            if "too_many_pending_share" in str(e):  # inbox full of unposted drafts: wait, don't fail
                print(f"WAIT {p['id']} -> tiktok: TikTok inbox has the max unposted drafts; retrying next run")
                return None
            raise
    if platform == "youtube" and short:
        title, desc, keywords = yt_fields(p)
        # trending-audio shorts send the clean mix to TikTok drafts; YouTube gets the full mix
        with local_video(p, p.get("video_youtube")) as path:
            return youtube.upload_short(tok.youtube(), path, title, desc, keywords,
                                        synthetic=p.get("youtube", {}).get("synthetic_media", False))
    raise ValueError(f"unknown platform {platform}")


def notify_music(p, media_id):
    """Push a phone notification (ntfy) when a feed post goes live on Instagram, so music can
    be added in the app (post -> Edit -> Add music). Never breaks posting."""
    if not config.NTFY_TOPIC or config.DRY_RUN:
        return
    try:
        link = instagram.permalink(media_id)
        hook = (p.get("caption") or "").split("\n")[0][:150]
        headers = {"Title": "Add music to the new Instagram post", "Tags": "musical_note"}
        if link:
            headers["Click"] = link
        body = f"{hook}\n\nTap to open it, then ... > Edit > Add music."
        requests.post(f"{config.NTFY_SERVER}/{config.NTFY_TOPIC}", data=body.encode("utf-8"),
                      headers=headers, timeout=15)
    except Exception as e:  # a missed reminder must never fail a run
        print(f"WARN music reminder for {p['id']} failed: {e}")


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
    due.sort(key=lambda x: datetime.fromisoformat(x[0]["publish_at"]))  # oldest first
    cap, shorts_posted = config.MAX_SHORTS_PER_RUN, 0
    tok = Tokens()
    cool = load_cooldowns()
    cool_before = json.dumps(cool, sort_keys=True)
    last_ig = last_ig_post(state)
    feed_gap = timedelta(minutes=config.IG_FEED_MIN_GAP_MINUTES)
    for p, pending in due:
        if p["type"] == "short" and cap and shorts_posted >= cap:
            print(f"LATER {p['id']}: max {cap} short(s) per run, posts on a later run")
            continue
        posted_any = False
        for platform in pending:
            rec = cool.get(platform)
            if rec and datetime.fromisoformat(rec["until"]) > now:
                print(f"WAIT {p['id']} -> {platform}: paused until {rec['until']} ({rec['reason']})")
                continue
            ig_feed = platform == "instagram" and p["type"] != "short"
            if platform == "instagram" and last_ig and now - last_ig < feed_gap:
                print(f"LATER {p['id']} -> instagram: Instagram posts (feed + Reels) are spaced "
                      f"{config.IG_FEED_MIN_GAP_MINUTES:g} min apart")
                continue
            try:
                media_id = post_one(p, platform, tok)
                if media_id is None:
                    continue
                posted_any = True
                posted_at = max(now, datetime.now(timezone.utc))
                state.setdefault(p["id"], {})[platform] = {
                    "id": media_id,
                    "at": posted_at.isoformat(timespec="seconds"),
                }
                cool.pop(platform, None)  # it works again
                print(f"POSTED {p['id']} -> {platform} ({media_id})")
                if platform == "instagram":
                    last_ig = now  # one Instagram post per run; the gap is measured from here
                if ig_feed:
                    notify_music(p, media_id)
            except Exception as e:  # keep going with the other posts
                print(f"FAILED {p['id']} -> {platform}: {e}")
                reason = next((needle for plat, needle, _ in cooldown_rules()
                               if plat == platform and needle in str(e)), None)
                if not reason:
                    failures += 1
                    continue
                hours = next(h for plat, needle, h in cooldown_rules() if plat == platform and needle == reason)
                repeat = bool(rec) and rec.get("reason") == reason
                until = (now + timedelta(hours=hours)).isoformat(timespec="seconds")
                cool[platform] = {"until": until, "reason": reason,
                                  "since": rec["since"] if repeat else now.isoformat(timespec="seconds")}
                print(f"PAUSE {platform} until {until}: {reason}" + (" (still blocked)" if repeat else ""))
                if not repeat:
                    failures += 1  # only the first failure of a streak turns the run red
        if p["type"] == "short" and posted_any:
            shorts_posted += 1
        if not config.DRY_RUN:
            save_state(state)
    if not config.DRY_RUN and json.dumps(cool, sort_keys=True) != cool_before:
        save_cooldowns(cool)
    # long-form YouTube videos (longform/<id>/), off until the repo variable YT_LONGFORM=1
    failures += longform.run(now, state, tok, lambda s: None if config.DRY_RUN else save_state(s))
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
    bad += longform.check()
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="validate posts only")
    args = ap.parse_args()
    sys.exit(check() if args.check else run())
