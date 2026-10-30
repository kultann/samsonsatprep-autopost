"""Read-only: what YouTube says about one or more of the channel's videos (2026-10-30).

    python tools/yt_status.py VIDEO_ID [VIDEO_ID ...]

Prints privacy, upload/processing status and any rejection or failure reason, using the
channel's own login (YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN, youtube.readonly
scope), so private and locked videos show up too. Exits 1 if a video isn't public, so the
"yt-status" workflow goes red. Changes nothing.
"""
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from autopost import youtube  # noqa: E402

ids = [a.strip() for a in sys.argv[1:] if a.strip()]
if not ids:
    sys.exit("usage: python tools/yt_status.py VIDEO_ID [VIDEO_ID ...]")
tok = youtube.access_token()
r = requests.get(youtube.VIDEOS_URL, params={"part": "status,snippet,processingDetails,contentDetails",
                                             "id": ",".join(ids)},
                 headers={"Authorization": f"Bearer {tok}"}, timeout=30)
r.raise_for_status()
items = {v["id"]: v for v in r.json().get("items", [])}
bad = 0
for vid in ids:
    v = items.get(vid)
    if not v:
        print(f"{vid}: NOT FOUND on the channel")
        bad += 1
        continue
    s, sn = v.get("status", {}), v.get("snippet", {})
    proc = v.get("processingDetails", {}).get("processingStatus")
    print(f"{vid}: {sn.get('title')!r}")
    print(f"  privacyStatus={s.get('privacyStatus')} uploadStatus={s.get('uploadStatus')} processing={proc}")
    print(f"  rejectionReason={s.get('rejectionReason')} failureReason={s.get('failureReason')} "
          f"madeForKids={s.get('madeForKids')} embeddable={s.get('embeddable')} "
          f"duration={v.get('contentDetails', {}).get('duration')} published={sn.get('publishedAt')}")
    print(f"  https://www.youtube.com/shorts/{vid}")
    if s.get("privacyStatus") != "public" or s.get("uploadStatus") in ("rejected", "failed"):
        bad += 1
sys.exit(1 if bad else 0)
