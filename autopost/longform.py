"""Long-form YouTube videos.

Each video lives in longform/<id>/:
  post.json      title, description (with real chapter times), tags, publish_at, video file name ...
  thumbnail.png  the A thumbnail (the B one is added by hand in Studio: Test & Compare)
  captions.srt   optional (uploaded only when YT_CAPTIONS=1)
The MP4 is NOT in the repo (GitHub caps files at 100 MB): it's an asset of the release tagged
"longform" (config.LONGFORM_VIDEO_BASE), downloaded only when it's time to upload.

How a video goes out (repo variable YT_LONGFORM=1):
- LONGFORM_UPLOAD_LEAD_HOURS (24) before publish_at it's uploaded as a scheduled video
  (private + publishAt), so YouTube finishes HD processing and publishes it right on time.
  Overdue videos go public immediately.
- Two long videos never go live closer than LONGFORM_MIN_GAP_HOURS (40) apart, so a stale
  schedule drips out instead of dumping a backlog. One upload per run (LONGFORM_MAX_PER_RUN).
- expires_at (optional): a date-specific video (e.g. "... before November 7") is held, not
  uploaded, if it can't go live by then.
- "manual": true means it was uploaded by hand; the bot skips it.
- Results go into state/posted.json under <id> -> "youtube" (id, at, publish_at, ...), saved right
  after the upload so a video is never uploaded twice.

post.json fields: id, type="longform", order, publish_at, expires_at?, window?, video, video_bytes?,
video_url?, thumbnail?, captions?, title, description, tags, category ("27" Education), language,
synthetic_media, made_for_kids, notify_subscribers, manual?
"""
import contextlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from . import config, youtube

TITLE_MAX, DESC_MAX, TAGS_MAX = 100, 5000, 500
THUMB_MAX = 2 * 1024 * 1024  # YouTube's custom thumbnail limit
EXTRA_TRIES = 5              # thumbnail/captions retries on later runs
TEST_KEY = "_longform_test"


def load():
    posts = []
    for f in sorted(Path(config.LONGFORM_DIR).glob("*/post.json")):
        p = json.loads(f.read_text())
        p["_dir"] = f.parent
        posts.append(p)
    return posts


def parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def rfc3339(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def video_url(p):
    return p.get("video_url") or f"{config.LONGFORM_VIDEO_BASE}/{p['video']}"


def tags_fit(tags):
    """YouTube allows 500 characters of tags (a tag with a space counts its quotes too)."""
    out, total = [], 0
    for t in tags or []:
        t = str(t).replace("<", "").replace(">", "").replace(",", " ").strip()
        if not t:
            continue
        n = len(t) + (2 if " " in t else 0) + (1 if out else 0)
        if total + n > TAGS_MAX:
            break
        out.append(t)
        total += n
    return out


def validate(p):
    errs = []
    for key in ("id", "type", "publish_at", "title", "description", "video"):
        if not p.get(key):
            errs.append(f"missing '{key}'")
    if errs:
        return errs
    if p["type"] != "longform":
        errs.append("type must be 'longform'")
    for key in ("publish_at", "expires_at"):
        if p.get(key):
            try:
                if parse(p[key]).tzinfo is None:
                    errs.append(f"{key} needs a UTC offset, e.g. 2026-10-11T16:00:00-05:00")
            except ValueError:
                errs.append(f"{key} must be ISO 8601 with an offset, e.g. 2026-10-11T16:00:00-05:00")
    title, desc = p["title"], p["description"]
    if len(title) > TITLE_MAX or "<" in title or ">" in title:
        errs.append("title must be <=100 characters with no < or >")
    if len(desc.encode("utf-8")) > DESC_MAX or "<" in desc or ">" in desc:
        errs.append("description must be <=5000 bytes with no < or >")
    if not p["video"].lower().endswith(".mp4"):
        errs.append("video must be an .mp4")
    thumb = p.get("thumbnail")
    if thumb:
        path = p["_dir"] / thumb
        if not thumb.lower().endswith((".png", ".jpg", ".jpeg")):
            errs.append(f"{thumb}: thumbnail must be PNG or JPEG")
        elif not path.exists():
            errs.append(f"{thumb}: file not found")
        elif path.stat().st_size > THUMB_MAX:
            errs.append(f"{thumb}: over 2 MB (YouTube's thumbnail limit)")
    cap = p.get("captions")
    if cap and not (p["_dir"] / cap).exists():
        errs.append(f"{cap}: file not found")
    return errs


def uploaded(p, state):
    return isinstance(state.get(p["id"]), dict) and "youtube" in state[p["id"]]


def last_publish(state, ids):
    times = []
    for i in ids:
        rec = state.get(i, {}).get("youtube") if isinstance(state.get(i), dict) else None
        if isinstance(rec, dict) and rec.get("publish_at"):
            times.append(parse(rec["publish_at"]))
    return max(times) if times else None


@contextlib.contextmanager
def downloaded(p):
    """Temp copy of the MP4 from the release (it redirects to GitHub's file host)."""
    url = video_url(p)
    if config.DRY_RUN:
        yield url
        return
    fd, tmp = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    try:
        with requests.get(url, stream=True, timeout=600) as r:
            if r.status_code != 200:
                raise RuntimeError(f"couldn't download {url} ({r.status_code}). Is {p['video']} attached "
                                   "to the 'longform' release?")
            with open(tmp, "wb") as fh:
                for part in r.iter_content(8 * 1024 * 1024):
                    fh.write(part)
        size = os.path.getsize(tmp)
        want = p.get("video_bytes")
        if want and size != want:
            raise RuntimeError(f"downloaded {size} bytes from {url}, expected {want} (wrong or partial file)")
        yield tmp
    finally:
        os.unlink(tmp)


def captions_wanted(p):
    return bool(config.YT_CAPTIONS and p.get("captions"))


def do_extras(p, rec, tok):
    """Thumbnail (+ captions). Failures are retried on later runs, never re-upload the video."""
    failed = False
    if not rec.get("thumbnail"):
        if not p.get("thumbnail"):
            rec["thumbnail"] = "none"
        else:
            try:
                youtube.set_thumbnail(tok.youtube(), rec["id"], str(p["_dir"] / p["thumbnail"]))
                rec["thumbnail"] = True
                rec.pop("thumbnail_error", None)
            except Exception as e:
                failed = True
                rec["thumbnail"] = False
                rec["thumbnail_error"] = str(e)[:300]
                print(f"WARN {p['id']}: thumbnail not set ({e}). Custom thumbnails need a phone-verified "
                      "channel; retrying next run.")
    if not rec.get("captions"):
        if not captions_wanted(p):
            rec["captions"] = "off"
        else:
            try:
                youtube.upload_captions(tok.youtube(), rec["id"], str(p["_dir"] / p["captions"]),
                                        language=p.get("language", "en"))
                rec["captions"] = True
                rec.pop("captions_error", None)
            except Exception as e:
                failed = True
                rec["captions"] = False
                rec["captions_error"] = str(e)[:300]
                print(f"WARN {p['id']}: captions not added ({e}); retrying next run.")
    if failed:
        rec["extra_tries"] = rec.get("extra_tries", 0) + 1
    return failed


def extras_pending(rec):
    return (not rec.get("thumbnail") or not rec.get("captions")) and rec.get("extra_tries", 0) < EXTRA_TRIES


def notify(p, rec):
    """Phone push (ntfy) so Samson can add the Test & Compare B thumbnail before it goes live."""
    if not config.NTFY_TOPIC or config.DRY_RUN:
        return
    try:
        try:
            from zoneinfo import ZoneInfo
            local = parse(rec["publish_at"]).astimezone(ZoneInfo("America/Chicago"))
            when = local.strftime("%a %b %d, %I:%M %p") + " Central"
        except Exception:
            when = rec["publish_at"]
        live = "is live now" if rec.get("privacy") == "public" else f"goes live {when}"
        body = f"{p['title']}\n\nIt {live}. Add the B thumbnail in Studio: Test & Compare."
        requests.post(f"{config.NTFY_SERVER}/{config.NTFY_TOPIC}", data=body.encode("utf-8"),
                      headers={"Title": "Long video uploaded", "Tags": "film_projector",
                               "Click": f"https://studio.youtube.com/video/{rec['id']}/edit"}, timeout=15)
    except Exception as e:  # a missed push never fails a run
        print(f"WARN push for {p['id']} failed: {e}")


def upload_one(p, when, now, tok, title=None, test=False):
    public_now = (not test) and when <= now + timedelta(minutes=10)
    publish_at = None if (public_now or test) else rfc3339(when)
    with downloaded(p) as path:
        vid, status = youtube.upload_video(
            tok.youtube(), path, (title or p["title"])[:TITLE_MAX], p["description"], tags_fit(p.get("tags")),
            privacy="public" if public_now else "private", publish_at=publish_at,
            synthetic=p.get("synthetic_media", False), language=p.get("language", "en"),
            category=str(p.get("category", youtube.EDUCATION)),
            notify=False if test else p.get("notify_subscribers", True),
            made_for_kids=p.get("made_for_kids", False))
    rec = {"id": vid, "at": max(now, datetime.now(timezone.utc)).isoformat(timespec="seconds"),
           "publish_at": (now if public_now else when).isoformat(timespec="seconds"),
           "privacy": "test" if test else ("public" if public_now else "scheduled")}
    if status.get("privacyStatus"):
        rec["status"] = status["privacyStatus"]
    return rec


def run_test(posts, now, state, tok, save):
    if TEST_KEY in state:
        print(f"LONGFORM test already uploaded (video {state[TEST_KEY].get('id')}). Delete it in Studio and set "
              "YT_LONGFORM back to 0 (or 1 once the YouTube API audit has passed).")
        return 0
    ok = [p for p in posts if not validate(p)]
    if not ok:
        print("LONGFORM test: no valid long-form post to test with")
        return 1
    p = sorted(ok, key=lambda x: (x.get("order", 0), parse(x["publish_at"])))[0]
    try:
        rec = upload_one(p, now, now, tok, title="[TEST] " + p["title"], test=True)
    except Exception as e:
        print(f"FAILED longform test with {p['id']}: {e}")
        return 1
    rec["post"] = p["id"]
    state[TEST_KEY] = rec
    save(state)
    do_extras(p, rec, tok)
    save(state)
    print(f"TEST uploaded {p['id']} as private video {rec['id']} (thumbnail: {rec.get('thumbnail')}). "
          "Check it in YouTube Studio, then delete it.")
    return 0


def run(now, state, tok, save):
    """Upload what's due. Returns the number of failures (0 = run stays green)."""
    posts = load()
    if not posts:
        return 0
    mode = config.YT_LONGFORM
    waiting = [p for p in posts if not p.get("manual") and not uploaded(p, state)]
    if mode in ("", "0", "off", "false", "no"):
        if waiting:
            print(f"LONGFORM off: {len(waiting)} long video(s) waiting. Set the repo variable YT_LONGFORM=1 "
                  "once the YouTube API audit has passed.")
        return 0
    if mode == "test":
        return run_test(posts, now, state, tok, save)
    if mode not in ("1", "on", "true", "yes"):
        print(f"WARN YT_LONGFORM={mode!r} isn't 0, test or 1; doing nothing")
        return 0

    failures = 0
    for p in posts:  # finish thumbnails/captions that failed on an earlier run
        rec = state.get(p["id"], {}).get("youtube") if uploaded(p, state) else None
        if rec and extras_pending(rec):
            if do_extras(p, rec, tok) and rec.get("extra_tries", 0) >= EXTRA_TRIES:
                failures += 1  # gave up: make the run red once so someone looks
            save(state)

    ids = [p["id"] for p in posts]
    last = last_publish(state, ids)
    gap = timedelta(hours=config.LONGFORM_MIN_GAP_HOURS)
    lead = timedelta(hours=config.LONGFORM_UPLOAD_LEAD_HOURS)
    todo = []
    for p in waiting:
        errs = validate(p)
        if errs:
            print(f"SKIP {p.get('id', p['_dir'])}: " + "; ".join(errs))
            continue
        todo.append(p)
    todo.sort(key=lambda x: (parse(x["publish_at"]), x.get("order", 0)))

    done_now = 0
    for p in todo:
        when = parse(p["publish_at"])
        if last:
            when = max(when, last + gap)
        live = max(when, now)
        if p.get("expires_at") and live > parse(p["expires_at"]):
            print(f"HOLD {p['id']}: can't go live before its expires_at ({p['expires_at']}); its title is "
                  "date-specific. Retitle it and give it a new date, or set \"manual\": true.")
            continue
        if when - now > lead:
            continue  # not yet
        if done_now >= config.LONGFORM_MAX_PER_RUN:
            print(f"LATER {p['id']}: max {config.LONGFORM_MAX_PER_RUN} long video(s) per run")
            break
        try:
            rec = upload_one(p, when, now, tok)
        except Exception as e:
            print(f"FAILED {p['id']} -> youtube (long-form): {e}")
            failures += 1
            break  # keep the order: try again next run
        state.setdefault(p["id"], {})["youtube"] = rec
        save(state)  # saved before anything else can fail: never upload twice
        live_txt = "public now" if rec["privacy"] == "public" else f"scheduled for {rec['publish_at']}"
        print(f"POSTED {p['id']} -> youtube long-form ({rec['id']}), {live_txt}")
        do_extras(p, rec, tok)
        save(state)
        notify(p, rec)
        done_now += 1
        last = parse(rec["publish_at"])
    return failures


def check():
    """Validation lines for runner --check. Returns the number of bad posts."""
    bad = 0
    for p in load():
        errs = validate(p)
        bad += bool(errs)
        flag = " manual" if p.get("manual") else ""
        print(("OK  " if not errs else "BAD ") + f"{p.get('id', p['_dir'])} {p.get('publish_at', '')} longform{flag}"
              + ("" if not errs else "  -> " + "; ".join(errs)))
    return bad
