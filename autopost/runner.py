"""Post everything that's due.

Each post lives in posts/<id>/ with a post.json and its slide images.
A post is due when publish_at <= now and it isn't recorded in state/posted.json
for that platform yet. Run this on a schedule (GitHub Actions does it hourly).

Usage:
  python -m autopost.runner            # post what's due
  python -m autopost.runner --check    # validate every post.json, post nothing
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import config, instagram, tiktok

IG_MAX_HASHTAGS = 5
AUTO_TYPES = {"carousel", "image"}  # reels/stories are posted by hand (trending audio)


def load_posts():
    posts = []
    for f in sorted(Path(config.POSTS_DIR).glob("*/post.json")):
        p = json.loads(f.read_text())
        p["_dir"] = f.parent
        posts.append(p)
    return posts


def validate(p):
    errs = []
    for key in ("id", "publish_at", "type", "slides", "platforms", "caption"):
        if key not in p:
            errs.append(f"missing '{key}'")
    if errs:
        return errs
    try:
        datetime.fromisoformat(p["publish_at"])
    except ValueError:
        errs.append("publish_at must be ISO 8601 with offset, e.g. 2026-10-06T16:00:00-05:00")
    if p["type"] in AUTO_TYPES:
        for s in p["slides"]:
            if not s.lower().endswith((".jpg", ".jpeg")):
                errs.append(f"{s}: Instagram needs JPEG")
            if not (p["_dir"] / s).exists():
                errs.append(f"{s}: file not found")
        if p["type"] == "carousel" and not 2 <= len(p["slides"]) <= 20:
            errs.append("carousel needs 2-20 slides")
    if len(p.get("hashtags_instagram", [])) > IG_MAX_HASHTAGS:
        errs.append(f"Instagram allows max {IG_MAX_HASHTAGS} hashtags")
    return errs


def public_urls(p):
    rel = p["_dir"].as_posix()
    return [f"{config.PUBLIC_BASE_URL}/{rel}/{s}" for s in p["slides"]]


def ig_caption(p):
    tags = " ".join(p.get("hashtags_instagram", []))
    return f"{p['caption']}\n\n{tags}".strip()


def tt_description(p):
    tags = " ".join(p.get("hashtags_tiktok", []))
    return f"{p['caption']}\n\n{tags}".strip()


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


def run(now=None):
    now = now or datetime.now(timezone.utc)
    state = load_state()
    posts = load_posts()
    due = []
    for p in posts:
        errs = validate(p)
        if errs:
            print(f"SKIP {p.get('id', p['_dir'])}: " + "; ".join(errs))
            continue
        if p["type"] not in AUTO_TYPES:
            continue
        if datetime.fromisoformat(p["publish_at"]) <= now:
            pending = [pl for pl in p["platforms"] if pl not in state.get(p["id"], {})]
            if pending:
                due.append((p, pending))

    if not due:
        print("Nothing due.")
        return 0

    tt_token = None
    failures = 0
    for p, pending in due:
        urls = public_urls(p)
        for platform in pending:
            try:
                if platform == "instagram":
                    media_id = instagram.publish(urls, ig_caption(p))
                elif platform == "tiktok":
                    if tt_token is None and not config.DRY_RUN:
                        tt_token, new_refresh = tiktok.refresh_access_token()
                        if new_refresh != config.TIKTOK_REFRESH_TOKEN:
                            write_new_secret("TIKTOK_REFRESH_TOKEN", new_refresh)
                    media_id = tiktok.publish_photos(
                        tt_token, urls, p.get("tiktok_title", p["caption"].split("\n")[0]), tt_description(p)
                    )
                else:
                    print(f"{p['id']}: unknown platform {platform}")
                    continue
                state.setdefault(p["id"], {})[platform] = {
                    "id": media_id,
                    "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
                print(f"POSTED {p['id']} -> {platform} ({media_id})")
            except Exception as e:  # keep going with the other posts
                failures += 1
                print(f"FAILED {p['id']} -> {platform}: {e}")
        if not config.DRY_RUN:
            save_state(state)
    return 1 if failures else 0


def check():
    bad = 0
    for p in load_posts():
        errs = validate(p)
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
