"""Build the GitHub Pages site with only the posts that are about to go out (or just went out).

The repo holds months of posts (well over GitHub Pages' 1 GB site limit), but Instagram and TikTok
only need a post's images around its publish time. So the site = root pages + verification files +
posts whose publish_at is within WINDOW_BEFORE..WINDOW_AFTER of now.

Usage: python tools/build_site.py _site
"""
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

WINDOW_BEFORE = timedelta(days=3)   # keep recently posted images up (retries, TikTok pull)
WINDOW_AFTER = timedelta(days=3)    # publish upcoming images early


def in_window(post_json, now=None):
    now = now or datetime.now(timezone.utc)
    p = json.loads(Path(post_json).read_text())
    t = datetime.fromisoformat(p["publish_at"])
    return now - WINDOW_BEFORE <= t <= now + WINDOW_AFTER


def build(out, now=None):
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for f in Path(".").iterdir():  # index/privacy/terms/callback pages + TikTok verification files
        if f.is_file() and (f.suffix == ".html" or (f.suffix == ".txt" and f.name.startswith("tiktok"))
                            or f.name == ".nojekyll"):
            shutil.copy(f, out / f.name)
    n = 0
    for pj in sorted(Path("posts").glob("*/post.json")):
        if in_window(pj, now):
            shutil.copytree(pj.parent, out / pj.parent)
            n += 1
    print(f"site: {n} posts in window")
    return n


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "_site")
