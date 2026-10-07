"""Build longform/<id>/ (post.json + thumbnail + captions) from the rendered videos.

Reads ~/Desktop/SAT/youtube/<NN_slug>/ (final/<slug>.mp4, metadata/<slug>_metadata.md,
thumbnail/<slug>_thumbnail.png, captions/<slug>.srt). The MP4 itself is NOT copied into the repo:
attach final/<slug>.mp4 to the GitHub release tagged "longform" under the same file name
(GitHub caps repo files at 100 MB). Then date everything with tools/schedule_longform.py.

  python3 tools/make_longform.py                   # every video folder with a final/<slug>.mp4
  python3 tools/make_longform.py --only 28 29      # just these video numbers
  python3 tools/make_longform.py --src /path/to/youtube

Re-running refreshes title/description/tags/thumbnail/captions/video_bytes but keeps an existing
post's publish_at, expires_at, window and manual flag.
"""
import argparse
import json
import re
import shutil
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent
TZ = ZoneInfo("America/Chicago")

# Videos tied to a test date. lead_days = how long before the test it should ideally go live.
# required = its title names the date, so it's useless after the test (held instead of uploaded late).
WINDOWS = {
    "03": {"test_date": "2026-11-07", "lead_days": 13, "required": True},   # 10 Hard SAT Math ... Nov 7
    "04": {"test_date": "2026-11-07", "lead_days": 6, "required": False},   # The Last Week Before the SAT
    "07": {"test_date": "2026-12-05", "lead_days": 13, "required": True},   # 10 Hard R&W ... Dec 5
    "08": {"test_date": "2026-12-05", "lead_days": 6, "required": False},   # SAT Test Day
}


def parse_metadata(md):
    title = re.search(r"^\*\*Pick:\*\*\s*(.+)$", md, re.M)
    desc = re.search(r"^## Description.*?\n```\n(.*?)\n```", md, re.S | re.M)
    tags = re.search(r"^## Tags\s*\n+(.+)$", md, re.M)
    if not (title and desc and tags):
        raise ValueError("metadata.md needs '**Pick:**', a '## Description' code block and '## Tags'")
    return (title.group(1).strip(), desc.group(1).strip(),
            [t.strip() for t in tags.group(1).split(",") if t.strip()])


def safe(text):
    """YouTube rejects < and > in titles/descriptions; swap in look-alikes."""
    return text.replace("<", "＜").replace(">", "＞")


def build(folder, out_root, old=None):
    slug = folder.name
    num = slug.split("_", 1)[0]
    video = folder / "final" / f"{slug}.mp4"
    meta = folder / "metadata" / f"{slug}_metadata.md"
    thumb = folder / "thumbnail" / f"{slug}_thumbnail.png"
    caps = folder / "captions" / f"{slug}.srt"
    for f in (video, meta):
        if not f.exists():
            raise FileNotFoundError(f)
    title, desc, tags = parse_metadata(meta.read_text())
    if "<" in title + desc or ">" in title + desc:
        print(f"  note {slug}: replaced < or > (YouTube doesn't allow them)")
    pid = f"long-{slug}"
    d = out_root / pid
    d.mkdir(parents=True, exist_ok=True)
    p = {
        "id": pid, "type": "longform", "order": int(num) if num.isdigit() else 0,
        "publish_at": (old or {}).get("publish_at") or "2099-01-01T16:00:00-06:00",
        "video": video.name, "video_bytes": video.stat().st_size,
        "title": safe(title)[:100], "description": safe(desc), "tags": tags,
        "category": "27", "language": "en", "synthetic_media": False, "made_for_kids": False,
        "notify_subscribers": True, "source": f"youtube/{slug}",
    }
    if thumb.exists():
        shutil.copyfile(thumb, d / "thumbnail.png")
        p["thumbnail"] = "thumbnail.png"
    if caps.exists():
        shutil.copyfile(caps, d / "captions.srt")
        p["captions"] = "captions.srt"
    win = (old or {}).get("window") or WINDOWS.get(num)
    if win:
        p["window"] = win
        if win.get("required"):
            test_day = date.fromisoformat(win["test_date"])
            p["expires_at"] = datetime.combine(test_day - timedelta(days=1), time(23, 59), TZ).isoformat()
    for keep in ("publish_at", "expires_at", "manual"):
        if old and keep in old:
            p[keep] = old[keep]
    (d / "post.json").write_text(json.dumps(p, indent=2, ensure_ascii=False) + "\n")
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(REPO.parent / "youtube"))
    ap.add_argument("--out", default=str(REPO / "longform"))
    ap.add_argument("--only", nargs="*", help="video numbers, e.g. 01 27")
    args = ap.parse_args()
    src, out = Path(args.src), Path(args.out)
    folders = sorted(f for f in src.iterdir() if f.is_dir() and re.match(r"^\d{2}_", f.name))
    if args.only:
        want = {n.zfill(2) for n in args.only}
        folders = [f for f in folders if f.name[:2] in want]
    made, problems = 0, 0
    for f in folders:
        old_file = out / f"long-{f.name}" / "post.json"
        old = json.loads(old_file.read_text()) if old_file.exists() else None
        try:
            p = build(f, out, old)
            made += 1
            print(f"OK  {p['id']}  {p['video_bytes'] / 1e6:.0f} MB  {p['title']}")
        except Exception as e:
            problems += 1
            print(f"BAD {f.name}: {e}")
    print(f"\n{made} long-form post(s) in {out}; {problems} problem(s).")
    print("Next: attach the MP4s to the 'longform' release, then run tools/schedule_longform.py.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
