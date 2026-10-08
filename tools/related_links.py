#!/usr/bin/env python3
"""List the YouTube Shorts whose clickable "Related video" still has to be set in YouTube Studio
(YouTube's API can't set it). Each Short gets the best matching long video that is public right now.

  python3 tools/related_links.py                     # the to-do list, oldest Short first
  python3 tools/related_links.py --csv links.csv     # same list as a CSV
  python3 tools/related_links.py --done ID [ID ...]  # mark Shorts (YouTube video ids) as linked
  python3 tools/related_links.py --done-all          # mark everything on the list as linked

In Studio: Content -> Shorts -> open the Short -> Related video -> pick the long video -> Save.
It needs advanced features (Studio -> Settings -> Channel -> Feature eligibility), and the long video
must be public. Marks are saved in state/related_done.json: commit and push it with the rest.
"""
import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from autopost import config, related  # noqa: E402

DONE = Path(config.STATE_FILE).parent / "related_done.json"


def load_done():
    return set(json.loads(DONE.read_text())) if DONE.exists() else set()


def todo(state, now, done):
    rows = []
    for pid, rec in state.items():
        yt = rec.get("youtube") if isinstance(rec, dict) and not pid.startswith(("long-", "_")) else None
        if not isinstance(yt, dict) or not yt.get("id") or yt["id"] in done:
            continue
        rel = related.pick(pid, state, now)
        if rel:
            rows.append({"posted": yt.get("at", ""), "short": pid, "short_video": yt["id"],
                         "studio": f"https://studio.youtube.com/video/{yt['id']}/edit",
                         "related_title": rel["title"], "related_video": rel["video"],
                         "related_url": f"https://youtu.be/{rel['video']}"})
    return sorted(rows, key=lambda r: r["posted"])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv")
    ap.add_argument("--done", nargs="+", metavar="VIDEO_ID")
    ap.add_argument("--done-all", action="store_true")
    a = ap.parse_args()
    state = json.loads(Path(config.STATE_FILE).read_text()) if Path(config.STATE_FILE).exists() else {}
    done = load_done()
    rows = todo(state, datetime.now(timezone.utc), done)
    if a.done or a.done_all:
        done |= set(a.done or []) | ({r["short_video"] for r in rows} if a.done_all else set())
        DONE.parent.mkdir(parents=True, exist_ok=True)
        DONE.write_text(json.dumps(sorted(done), indent=1) + "\n")
        print(f"Marked as linked. {len(done)} Shorts linked so far.")
        return
    if a.csv:
        with open(a.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["short"])
            w.writeheader()
            w.writerows(rows)
    if not rows:
        print("Nothing to link: no YouTube Shorts are waiting, or no long video is public yet.")
        return
    for r in rows:
        print(f"{r['posted'][:10]}  {r['short']}\n   Short:   {r['studio']}\n   Related: {r['related_title']}  ({r['related_url']})")
    print(f"\n{len(rows)} Shorts to link. When done: python3 tools/related_links.py --done-all")


if __name__ == "__main__":
    main()
