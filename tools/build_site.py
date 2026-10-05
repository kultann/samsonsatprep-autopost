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
    write_music_page(out, now)
    print(f"site: {n} posts in window")
    return n


def write_music_page(out, now=None):
    """music.html: the posts flagged "type": "manual" (post by hand with a trending song), next few days."""
    import html
    now = now or datetime.now(timezone.utc)
    rows = []
    for pj in sorted(Path("posts").glob("*/post.json")):
        p = json.loads(pj.read_text())
        if p.get("type") != "manual":
            continue
        t = datetime.fromisoformat(p["publish_at"])
        if not (now - timedelta(days=1) <= t <= now + WINDOW_AFTER):
            continue
        d = pj.parent.as_posix()
        m = p.get("music", {})
        imgs = "".join(f'<a href="{d}/{s}"><img src="{d}/{s}"></a>' for s in p["slides"])
        timgs = "".join(f'<a href="{d}/{s}">{i + 1}</a> ' for i, s in enumerate(p.get("slides_tiktok", [])))
        cap = html.escape(p["caption"])
        tcap = html.escape(p.get("tiktok_caption") or p["caption"])
        rows.append(f"""<section><h2>{t.strftime('%a %b %d')} · post around {t.strftime('%-I:%M %p')} CT</h2>
<p class=song>♫ <b>{html.escape(m.get('song', ''))}</b> · {html.escape(m.get('artist', ''))}</p>
<div class=imgs>{imgs}</div>
<p><b>Instagram caption</b> <button onclick="cp(this)">Copy</button></p><pre>{cap}</pre>
<p><b>TikTok</b> 9:16 slides: {timgs}<button onclick="cp(this)">Copy caption</button></p><pre>{tcap}</pre></section>""")
    body = "".join(rows) or "<p>No music posts in the next few days.</p>"
    page = f"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<meta name=robots content=noindex><title>music posts</title><style>
body{{font-family:-apple-system,system-ui,sans-serif;margin:0;padding:16px;background:#111;color:#eee}}
section{{border-bottom:1px solid #333;padding:12px 0 20px}}h2{{font-size:18px;margin:0 0 6px}}
.song{{font-size:16px;color:#7ee787}}.imgs{{display:flex;gap:6px;overflow-x:auto}}.imgs img{{height:220px;border-radius:6px}}
pre{{white-space:pre-wrap;background:#1c1c1c;padding:10px;border-radius:6px;font-size:14px}}
button{{background:#2f81f7;color:#fff;border:0;border-radius:6px;padding:6px 10px;margin-left:6px}}a{{color:#58a6ff}}
</style></head><body><h1>Post these by hand with the song</h1>
<p>Tap a slide to open it full size, long-press to save, then post in Instagram/TikTok and add the song.</p>{body}
<script>function cp(b){{const pre=b.parentElement.nextElementSibling;navigator.clipboard.writeText(pre.innerText);b.textContent='Copied';}}</script>
</body></html>"""
    (Path(out) / "music.html").write_text(page)


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "_site")
