"""Turn rendered PNG slides into a ready-to-schedule post folder.

python tools/make_post.py --id 2026-10-06_q01 --at 2026-10-06T16:00:00-05:00 \
    --type carousel --slides slide1.png slide2.png slide3.png slide4.png \
    --caption "Can you solve this in 30 seconds?" --topic math

Converts slides to JPEG (Instagram requires JPEG), copies them into
posts/<id>/ and writes post.json with the right hashtag set for the topic.
"""
import argparse
import json
from pathlib import Path

from PIL import Image

HASHTAGS = {
    "math": (["#SAT", "#SATprep", "#SATmath", "#DigitalSAT", "#SATpractice"],
             ["#studytok", "#satprep", "#sattips", "#digitalsat", "#satmath"]),
    "rw": (["#SAT", "#SATprep", "#SATreading", "#SATgrammar", "#DigitalSAT"],
           ["#studytok", "#satprep", "#sattips", "#digitalsat", "#satgrammar"]),
    "desmos": (["#SAT", "#SATmath", "#Desmos", "#MathHacks", "#DigitalSAT"],
               ["#studytok", "#satprep", "#sattips", "#digitalsat", "#desmos"]),
    "strategy": (["#SAT", "#SATprep", "#DigitalSAT", "#SATtips", "#StudyTips"],
                 ["#studytok", "#satprep", "#sattips", "#digitalsat"]),
}

ap = argparse.ArgumentParser()
ap.add_argument("--id", required=True)
ap.add_argument("--at", required=True, help="ISO time with offset")
ap.add_argument("--type", default="carousel", choices=["carousel", "image", "reel", "story"])
ap.add_argument("--slides", nargs="+", required=True)
ap.add_argument("--caption", required=True)
ap.add_argument("--tiktok-title")
ap.add_argument("--topic", default="math", choices=list(HASHTAGS))
ap.add_argument("--audio", default="lofi", help="audio vibe note for manual posts")
ap.add_argument("--platforms", nargs="+", default=["instagram", "tiktok"])
a = ap.parse_args()

out = Path("posts") / a.id
out.mkdir(parents=True, exist_ok=True)
names = []
for i, src in enumerate(a.slides, 1):
    name = f"slide{i}.jpg"
    Image.open(src).convert("RGB").save(out / name, "JPEG", quality=92, optimize=True)
    names.append(name)

ig_tags, tt_tags = HASHTAGS[a.topic]
post = {
    "id": a.id,
    "publish_at": a.at,
    "type": a.type,
    "slides": names,
    "platforms": a.platforms,
    "caption": a.caption,
    "tiktok_title": a.tiktok_title or a.caption.split("\n")[0][:90],
    "hashtags_instagram": ig_tags,
    "hashtags_tiktok": tt_tags,
    "audio_vibe": a.audio,
}
(out / "post.json").write_text(json.dumps(post, indent=2, ensure_ascii=False) + "\n")
print(f"wrote {out}/post.json with {len(names)} slides")
