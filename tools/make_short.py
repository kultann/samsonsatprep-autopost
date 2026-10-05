"""Turn a finished short into a ready-to-schedule post folder.

python3 tools/make_short.py --id 2026-10-13_desmos-systems --at 2026-10-13T17:00:00-05:00 \
    --video final.mp4 --cover cover.png --topic desmos \
    --caption "Stop solving systems by hand. Desmos does it in 5 seconds." \
    --yt-title "Solve SAT Systems of Equations in Desmos (5 Seconds)" \
    --yt-description "Graph both equations, click where they cross."

Copies the MP4 to posts/<id>/video.mp4, converts the cover to cover.jpg, and writes
post.json with the hashtag sets for the topic. Platforms default to all three.
Check it before pushing: python3 -m autopost.runner --check
"""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

HASHTAGS = {  # (instagram max 5, tiktok, youtube 3-5)
    "math": (["#SAT", "#SATprep", "#SATmath", "#DigitalSAT", "#SATpractice"],
             ["#studytok", "#satprep", "#sattips", "#digitalsat", "#satmath"],
             ["#SAT", "#SATmath", "#DigitalSAT", "#SATprep"]),
    "rw": (["#SAT", "#SATprep", "#SATreading", "#SATgrammar", "#DigitalSAT"],
           ["#studytok", "#satprep", "#sattips", "#digitalsat", "#satgrammar"],
           ["#SAT", "#SATgrammar", "#DigitalSAT", "#SATprep"]),
    "desmos": (["#SAT", "#SATmath", "#Desmos", "#MathHacks", "#DigitalSAT"],
               ["#studytok", "#satprep", "#sattips", "#digitalsat", "#desmos"],
               ["#SAT", "#Desmos", "#SATmath", "#DigitalSAT"]),
    "strategy": (["#SAT", "#SATprep", "#DigitalSAT", "#SATtips", "#StudyTips"],
                 ["#studytok", "#satprep", "#sattips", "#digitalsat"],
                 ["#SAT", "#SATtips", "#DigitalSAT", "#SATprep"]),
}

ap = argparse.ArgumentParser()
ap.add_argument("--id", required=True)
ap.add_argument("--at", required=True, help="ISO time with offset, e.g. 2026-10-13T17:00:00-05:00")
ap.add_argument("--video", required=True)
ap.add_argument("--cover", help="PNG/JPEG cover (Instagram Reels tab + grid)")
ap.add_argument("--cover-ms", type=int, default=500, help="frame used as cover on TikTok (and IG if no --cover)")
ap.add_argument("--caption", required=True, help="Instagram caption (hashtags added automatically)")
ap.add_argument("--tiktok-caption", help="defaults to --caption")
ap.add_argument("--yt-title", required=True)
ap.add_argument("--yt-description", default="")
ap.add_argument("--topic", default="math", choices=list(HASHTAGS))
ap.add_argument("--platforms", nargs="+", default=["instagram", "tiktok", "youtube"])
ap.add_argument("--tiktok-mode", default="direct", choices=["direct", "draft"])
ap.add_argument("--no-ai-label", action="store_true", help="skip TikTok's AI-generated label (e.g. your own voice)")
a = ap.parse_args()

out = Path("posts") / a.id
out.mkdir(parents=True, exist_ok=True)
shutil.copyfile(a.video, out / "video.mp4")

try:  # optional sanity check on the video
    meta = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
         "-of", "json", str(out / "video.mp4")], capture_output=True, text=True, check=True).stdout)
    w, h = meta["streams"][0]["width"], meta["streams"][0]["height"]
    dur = float(meta["format"]["duration"])
    if h <= w:
        print(f"WARNING: video is {w}x{h}; Shorts/Reels need vertical 9:16")
    if dur > 180:
        print(f"WARNING: {dur:.0f}s is over 3 minutes, so YouTube won't treat it as a Short")
except (FileNotFoundError, subprocess.CalledProcessError, KeyError, IndexError, ValueError):
    print("(ffprobe not available; skipped the size/length check)")

cover_name = None
if a.cover:
    from PIL import Image
    Image.open(a.cover).convert("RGB").save(out / "cover.jpg", "JPEG", quality=92, optimize=True)
    cover_name = "cover.jpg"

ig, tt, yt = HASHTAGS[a.topic]
post = {
    "id": a.id,
    "publish_at": a.at,
    "type": "short",
    "video": "video.mp4",
    "cover_time_ms": a.cover_ms,
    "platforms": a.platforms,
    "caption": a.caption,
    "hashtags_instagram": ig,
    "hashtags_tiktok": tt,
    "youtube": {"title": a.yt_title, "description": a.yt_description, "hashtags": yt},
    "tiktok_mode": a.tiktok_mode,
    "ai_label": not a.no_ai_label,
}
if cover_name:
    post["cover"] = cover_name
if a.tiktok_caption:
    post["tiktok_caption"] = a.tiktok_caption
(out / "post.json").write_text(json.dumps(post, indent=2, ensure_ascii=False) + "\n")
print(f"Wrote {out}/ (video.mp4{', cover.jpg' if cover_name else ''}, post.json)")
