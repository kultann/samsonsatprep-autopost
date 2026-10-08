"""Link each YouTube Short to a related long-form video.

YouTube's API can't set a Short's clickable "Related video" link (that's YouTube Studio only, and it needs
advanced features), so the bot does what the API allows:
  1. picks the best matching long video that is already public and names it in the Short's description
     (links in Shorts descriptions aren't clickable, but the title and youtu.be address still show), and
  2. records the pick in state/posted.json (<short id> -> youtube -> related), so tools/related_links.py
     can list the Shorts whose Related video still needs to be set in Studio.
longform/related_map.json maps each script id (the last part of a short's id, e.g. M1-036) to long-form ids,
best match first. Build it with tools/build_related_map.py.
"""
import json
from pathlib import Path

from . import config, longform


def load_map():
    p = Path(config.RELATED_MAP)
    return json.loads(p.read_text()) if p.exists() else {}


def script_id(post_id):
    return post_id.rsplit("_", 1)[-1]


def live_longs(state, now):
    """{long id: YouTube video id} for long videos that are public by `now` (never the private test copy)."""
    out = {}
    for key, val in state.items():
        rec = val.get("youtube") if key.startswith("long-") and isinstance(val, dict) else None
        if not isinstance(rec, dict) or not rec.get("id") or rec.get("privacy") not in ("public", "scheduled"):
            continue
        when = rec.get("publish_at") or rec.get("at")
        if when and longform.parse(when) <= now:
            out[key] = rec["id"]
    return out


def titles():
    try:
        return {p["id"]: p.get("title") or p["id"] for p in longform.load()}
    except Exception:  # a broken long-form folder must never block a Short
        return {}


def pick(post_id, state, now, mapping=None):
    """Best related long video that is public by `now`: {"long", "video", "title"}, or None."""
    cands = (load_map() if mapping is None else mapping).get(script_id(post_id), [])
    live = live_longs(state, now)
    for c in cands:
        if c in live:
            return {"long": c, "video": live[c], "title": titles().get(c, c)}
    return None


def description_line(rel):
    return f"Full lesson: {rel['title']} (youtu.be/{rel['video']})"
