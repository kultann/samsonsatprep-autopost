#!/usr/bin/env python3
"""Build one week of TikToks to upload and schedule by hand in TikTok Studio (desktop).

TikTok rejected the developer app for production on 2026-10-13 ("apps for personal use are not eligible"),
so the bot no longer posts to TikTok (config.TIKTOK_ENABLED is off). Once a week, run:

  python3 tools/tiktok_week.py --start 2026-10-19

It makes ~/Desktop/SAT/tiktok-weekly/2026-10-19/ for the 7 days starting that date:
  - every short scheduled for TikTok that week, copied from the render archive (~/Desktop/SAT/shorts/<id>/final/,
    the same version Instagram got), named in posting order with the time: 01_Mon_0730_Q1-020.mp4
  - with --carousels, each photo carousel as a numbered folder of its TikTok slides (tslideN.jpg, in order)
  - checklist.html: open it in Chrome. One card per post: day and time (Central), file, the full TikTok caption
    with a Copy button, the AI-label reminder, and a checkbox that stays ticked.
Then it lists those shorts in samsonsatprep-media/tiktok_weekly.json, so the media repo's daily prune may delete
their videos (push the media repo in GitHub Desktop afterwards). The render archive is never touched.

Settings: edit the constants below or use the flags (--per-day, --carousels, --mix, --days, --no-record).
Re-running a week rebuilds its folder; ticks in checklist.html are kept.
"""
import argparse
import ast
import html
import json
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------- settings
CAROUSELS = False    # also prepare photo carousels (folders of tslideN.jpg)          flag: --carousels
SHORTS_PER_DAY = 7   # shorts per day for TikTok; fewer keeps the 2 long ones first,  flag: --per-day N
                     # then the best of the rest (FORMAT_PRIORITY)
MIX = "final"        # "final" = voice + SFX + music (what Instagram got)               flag: --mix clean
                     # "clean" = voice + SFX only, to add a TikTok sound in the app
# "Best of the rest" when SHORTS_PER_DAY < 7: earlier formats win (ties: earlier time), and a format already
# kept that day is passed over while a different one is left. Reorder freely.
FORMAT_PRIORITY = ["countdown", "trap", "solve", "desmos", "spot_error", "quickfire",
                   "myth", "formula", "rule", "explain", "tip"]
SCHEDULE_LEAD = timedelta(minutes=20)  # TikTok can't schedule a post that's already (nearly) due
# ----------------------------------------------------------------

REPO = Path(__file__).resolve().parent.parent
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
# TikTok hashtags per hashtag_set. Read from tools/shorts/render.py (HASHTAGS, TikTok column) when possible;
# these are the fallback (same values as of 2026-10-13).
TIKTOK_TAGS = {
    "math": "#studytok #satprep #sattips #digitalsat #satmath",
    "rw": "#studytok #satprep #sattips #digitalsat #satgrammar",
    "desmos": "#studytok #satprep #sattips #digitalsat #desmos",
    "strategy": "#studytok #satprep #sattips #digitalsat",
}

try:
    from zoneinfo import ZoneInfo
    CENTRAL = ZoneInfo("America/Chicago")
except Exception:  # no tz database: publish_at strings are already Central wall times
    CENTRAL = None


class Paths:
    def __init__(self, sat, posts=None):
        self.sat = Path(sat).expanduser().resolve()
        self.archive = self.sat / "shorts"
        self.bank = self.archive / "shorts_bank.json"
        self.media = self.sat / "samsonsatprep-media"
        self.record = self.media / "tiktok_weekly.json"
        self.posts = Path(posts) if posts else self.sat / REPO.name / "posts"
        self.out = self.sat / "tiktok-weekly"
        self.render_py = self.sat / "tools" / "shorts" / "render.py"


def central(ts):
    t = datetime.fromisoformat(ts)
    if CENTRAL is not None and t.tzinfo is not None:
        t = t.astimezone(CENTRAL)
    return t


def nice_time(t):
    return f"{t:%a} {t:%b} {t.day} · {t.hour % 12 or 12}:{t:%M} {'AM' if t.hour < 12 else 'PM'}"


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def label(pid):
    """2026-10-19_0730_Q1-020 -> Q1-020, 2026-10-07_reading01 -> reading01."""
    parts = pid.split("_")
    if parts and len(parts[0]) == 10 and parts[0][4:5] == "-":
        parts = parts[1:]
    if len(parts) > 1 and len(parts[0]) == 4 and parts[0].isdigit():
        parts = parts[1:]
    return "_".join(parts) or pid


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def tiktok_tags(paths):
    tags = dict(TIKTOK_TAGS)
    try:
        tree = ast.parse(paths.render_py.read_text())
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "HASHTAGS" for t in node.targets):
                tags.update({k: v[1] for k, v in ast.literal_eval(node.value).items()})
    except (OSError, ValueError, SyntaxError, IndexError, TypeError):
        pass
    return tags


def load_shorts(paths, start, end):
    """Shorts scheduled for TikTok in [start, end): the shorts bank, plus any media-repo short not in it."""
    seen = {}
    for it in read_json(paths.bank, []):
        if it.get("post_id"):
            seen[it["post_id"]] = dict(it)
    for f in sorted((paths.media / "shorts").glob("*/post.json")):
        p = read_json(f, None)
        pid = (p or {}).get("id", f.parent.name)
        if p and pid not in seen:  # made outside the bank
            seen[pid] = {"post_id": pid, "publish_at": p.get("publish_at"), "platforms": p.get("platforms", []),
                         "tiktok_caption": p.get("tiktok_caption") or p.get("caption", ""),
                         "tags": p.get("hashtags_tiktok", [])}
    out = []
    for it in seen.values():
        if "tiktok" not in it.get("platforms", []) or not it.get("publish_at"):
            continue
        t = central(it["publish_at"])
        if start <= t.date() < end:
            out.append(dict(it, _t=t))
    return sorted(out, key=lambda i: i["_t"])


def load_carousels(paths, start, end):
    out = []
    for f in sorted(paths.posts.glob("*/post.json")):
        p = read_json(f, None)
        if not p or p.get("type") not in ("carousel", "image") or "tiktok" not in p.get("platforms", []):
            continue
        if not p.get("publish_at"):
            continue
        t = central(p["publish_at"])
        if start <= t.date() < end:
            out.append(dict(p, post_id=p.get("id", f.parent.name), _t=t, _dir=f.parent))
    return sorted(out, key=lambda i: i["_t"])


def find_video(paths, pid, mix):
    """The archive render Instagram got: the final MP4 hard-linked into the media repo, else the newest final
    (tools/shorts/publish.py stages the newest). mix="clean" takes the clean mix of that same version."""
    folder = paths.archive / pid / "final"
    finals = sorted(folder.glob(f"{pid}_final*.mp4"))
    if not finals:
        return None
    pick = None
    media = paths.media / "shorts" / pid / "video.mp4"
    if media.exists():
        ms = media.stat()
        pick = next((c for c in finals if (c.stat().st_ino, c.stat().st_dev) == (ms.st_ino, ms.st_dev)), None)
    pick = pick or max(finals, key=lambda c: c.stat().st_mtime)
    if mix == "clean":
        twin = pick.with_name(pick.name.replace("_final", "_clean", 1))
        cleans = sorted(folder.glob(f"{pid}_clean*.mp4"))
        if twin.exists():
            return twin
        return max(cleans, key=lambda c: c.stat().st_mtime) if cleans else None
    return pick


def short_text(it, tags):
    body = (it.get("tiktok_caption") or "").strip()
    if not body:
        return None
    t = it.get("tags") or tags.get(it.get("hashtag_set", ""), "").split()
    return f"{body}\n\n{' '.join(t)}".strip()


def carousel_text(p):
    body = (p.get("tiktok_caption") or p.get("caption") or "").strip()
    if not body:
        return None
    return f"{body}\n\n{' '.join(p.get('hashtags_tiktok', []))}".strip()


def rank(fmt):
    return FORMAT_PRIORITY.index(fmt) if fmt in FORMAT_PRIORITY else len(FORMAT_PRIORITY)


def apply_cap(day_items, cap):
    """Keep `cap` shorts: the long ones first, then the best of the rest. Returns (kept, dropped)."""
    if cap >= len(day_items):
        return day_items, []
    keep = [i for i in day_items if i.get("length") == "long"][:cap]
    kinds = {i.get("format") for i in keep}
    kept_ids = {i["post_id"] for i in keep}
    rest = sorted((i for i in day_items if i["post_id"] not in kept_ids), key=lambda i: (rank(i.get("format")), i["_t"]))
    while len(keep) < cap and rest:
        pick = next((i for i in rest if i.get("format") not in kinds), rest[0])
        keep.append(pick)
        rest.remove(pick)
        kinds.add(pick.get("format"))
    return sorted(keep, key=lambda i: i["_t"]), sorted(rest, key=lambda i: i["_t"])


def clone(src, dst):
    """Copy a file; on a Mac (APFS) as a clone, which takes no extra disk space."""
    if dst.exists():
        dst.unlink()
    if sys.platform == "darwin" and subprocess.run(["cp", "-c", str(src), str(dst)], capture_output=True).returncode == 0:
        return
    shutil.copy2(src, dst)


def clear_previous(week):
    """Remove what an earlier run of this week made (listed in .tiktok_week.json); nothing else."""
    for name in read_json(week / ".tiktok_week.json", {}).get("made", []):
        p = week / name
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()


def update_record(paths, entries):
    if not entries or not paths.media.is_dir():
        return False
    rec = read_json(paths.record, {})
    rec = rec if isinstance(rec, dict) else {}
    rec.update(entries)
    paths.record.write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n")
    return True


def build(paths, start, days=7, per_day=SHORTS_PER_DAY, carousels=CAROUSELS, mix=MIX, record=True, now=None):
    now = now or datetime.now(timezone.utc)
    end = start + timedelta(days=days)
    week = paths.out / start.isoformat()
    tags = tiktok_tags(paths)
    skipped, rec = [], {}
    stamp = now.isoformat(timespec="seconds")

    def skip(item, reason, kind="short", keep_record=False):
        skipped.append({"when": item["_t"], "label": label(item["post_id"]), "kind": kind, "reason": reason})
        if keep_record:  # won't go to TikTok on purpose: the media repo may prune it
            rec[item["post_id"]] = {"week": start.isoformat(), "at": stamp, "skipped": reason}

    # shorts: drop what can't be posted, then apply the daily cap
    ready, by_day = [], {}
    for it in load_shorts(paths, start, end):
        if it["_t"] < now + SCHEDULE_LEAD:
            skip(it, "time already passed (TikTok can't schedule it)", keep_record=True)
            continue
        text = short_text(it, tags)
        video = find_video(paths, it["post_id"], mix)
        if not video:
            skip(it, f"missing render (no {mix} MP4 in shorts/{it['post_id']}/final/)")
            continue
        if not text:
            skip(it, "missing caption (tiktok_caption is empty)")
            continue
        by_day.setdefault(it["_t"].date(), []).append(dict(it, _video=video, _text=text))
    for d in sorted(by_day):
        kept, dropped = apply_cap(by_day[d], per_day)
        ready += kept
        for it in dropped:
            skip(it, f"over the daily cap ({per_day} shorts/day)", keep_record=True)

    posts = [dict(it, _kind="short") for it in ready]
    if carousels:
        for p in load_carousels(paths, start, end):
            if p["_t"] < now + SCHEDULE_LEAD:
                skip(p, "time already passed (TikTok can't schedule it)", "carousel")
                continue
            slides = p.get("slides_tiktok") or p.get("slides") or []
            missing = [s for s in slides if not (p["_dir"] / s).exists()]
            text = carousel_text(p)
            if not slides or missing:
                skip(p, f"missing slide(s): {', '.join(missing) or 'none listed'}", "carousel")
            elif not text:
                skip(p, "missing caption", "carousel")
            else:
                posts.append(dict(p, _kind="carousel", _slides=[p["_dir"] / s for s in slides], _text=text))
    posts.sort(key=lambda p: p["_t"])

    week.mkdir(parents=True, exist_ok=True)
    clear_previous(week)
    width = 3 if len(posts) > 99 else 2
    made, cards = [], []
    for n, p in enumerate(posts, 1):
        t = p["_t"]
        base = f"{n:0{width}d}_{DAYS[t.weekday()]}_{t:%H%M}_{label(p['post_id'])}"
        card = {"n": n, "id": p["post_id"], "kind": p["_kind"], "when": t, "text": p["_text"]}
        if p["_kind"] == "short":
            name = base + ".mp4"
            clone(p["_video"], week / name)
            qc = read_json(paths.archive / p["post_id"] / "metadata" / "qc.json", {})
            card.update(file=name, seconds=qc.get("seconds"), length=p.get("length", ""), fmt=p.get("format", ""))
            rec[p["post_id"]] = {"week": start.isoformat(), "at": stamp, "file": name}
        else:
            name = base
            (week / name).mkdir(exist_ok=True)
            for i, s in enumerate(p["_slides"], 1):
                clone(s, week / name / f"{i:02d}_{s.name}")
            card.update(file=name + "/", slides=len(p["_slides"]),
                        title=(p.get("tiktok_title") or p["_text"].split("\n")[0])[:90])
        made.append(name)
        cards.append(card)

    summary = {
        "week": start.isoformat(), "days": days, "folder": str(week), "posts": len(cards),
        "shorts": sum(c["kind"] == "short" for c in cards), "carousels": sum(c["kind"] == "carousel" for c in cards),
        "first": cards[0]["when"] if cards else None, "last": cards[-1]["when"] if cards else None,
        "skipped": sorted(skipped, key=lambda s: s["when"]),
        "settings": {"per_day": per_day, "carousels": carousels, "mix": mix},
    }
    (week / "checklist.html").write_text(checklist_html(start, end, cards, summary), encoding="utf-8")
    made.append("checklist.html")
    (week / ".tiktok_week.json").write_text(json.dumps({"made": made, "built": stamp}, indent=1) + "\n")
    summary["recorded"] = update_record(paths, rec) if record else False
    summary["record_count"] = len(rec) if summary["recorded"] else 0
    return summary


# ---------------------------------------------------------------- checklist.html
CSS = """
:root{--bg:#f5f6f8;--card:#fff;--ink:#16191d;--mute:#5f6873;--line:#dde1e6;--acc:#e8174a;--ok:#16794a;--chip:#eceff3}
@media (prefers-color-scheme:dark){:root{--bg:#0f1114;--card:#171a1f;--ink:#e7eaee;--mute:#9aa3ad;--line:#2a2f36;--acc:#ff4f72;--ok:#37c787;--chip:#21262d}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:760px;margin:0 auto;padding:28px 16px 72px}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}
.sub{color:var(--mute);margin:0}
.bar-wrap{position:sticky;top:0;z-index:5;background:var(--bg);padding:12px 0;margin:14px 0 6px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:12px}
.bar{flex:1;height:8px;border-radius:99px;background:var(--chip);overflow:hidden}
.bar i{display:block;height:100%;width:0;background:var(--ok);transition:width .2s}
#count{font-weight:650;white-space:nowrap}
.how{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 18px;margin:14px 0 8px}
.how ol{margin:6px 0 4px;padding-left:20px}.how li{margin:2px 0}.how p{margin:6px 0 0;color:var(--mute);font-size:13px}
a{color:var(--acc)}
h2{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--mute);margin:30px 0 8px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px;margin:10px 0;display:grid;gap:10px}
.card.done{opacity:.5}
.top{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.num{font-weight:750;color:var(--acc);font-variant-numeric:tabular-nums}
.when{font-weight:700;font-size:18px}
.chip{font-size:12px;background:var(--chip);color:var(--mute);border-radius:99px;padding:2px 9px}
.file{font:13px/1.3 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--mute);word-break:break-all}
label.lbl{font-size:12px;color:var(--mute);margin-bottom:-6px}
textarea{width:100%;min-height:76px;resize:vertical;border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:var(--bg);color:var(--ink);font-family:inherit;font-size:14px;line-height:1.45}
textarea.title{min-height:44px}
button.copy{font-family:inherit;font-weight:650;font-size:17px;line-height:1;padding:14px 16px;border:0;border-radius:12px;background:var(--acc);color:#fff;cursor:pointer;width:100%}
button.copy.small{font-size:14px;padding:10px 14px;background:var(--chip);color:var(--ink)}
button.copy.ok{background:var(--ok);color:#fff}
.ai{font-size:14px;padding:8px 12px;border-radius:10px;background:var(--chip);border-left:4px solid var(--acc)}
.tick{display:flex;align-items:center;gap:10px;font-weight:650;cursor:pointer;user-select:none}
.tick input{width:22px;height:22px;accent-color:var(--ok)}
details summary{cursor:pointer;color:var(--mute);font-size:13px}
video{display:block;width:200px;max-width:100%;border-radius:10px;margin-top:8px;background:#000}
.summary{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 18px;margin-top:30px}
.summary h3{margin:0 0 6px;font-size:16px}
.summary ul{margin:6px 0 0;padding-left:18px}
.empty{color:var(--mute)}
"""

JS = """
const WEEK = document.body.dataset.week;
const key = id => "tiktokweek:" + WEEK + ":" + id;
function saved(k){ try { return localStorage.getItem(k) === "1"; } catch (e) { return false; } }
function save(k, on){ try { on ? localStorage.setItem(k, "1") : localStorage.removeItem(k); } catch (e) {} }
function progress(){
  const all = document.querySelectorAll(".card").length, done = document.querySelectorAll(".card.done").length;
  document.getElementById("count").textContent = done + " / " + all + " scheduled";
  document.getElementById("fill").style.width = (all ? 100 * done / all : 0) + "%";
}
document.querySelectorAll(".card").forEach(card => {
  const box = card.querySelector(".tick input"), k = key(card.dataset.id);
  box.checked = saved(k); card.classList.toggle("done", box.checked);
  box.addEventListener("change", () => { save(k, box.checked); card.classList.toggle("done", box.checked); progress(); });
});
document.querySelectorAll("button.copy").forEach(btn => btn.addEventListener("click", async () => {
  const ta = document.getElementById(btn.dataset.for), label = btn.textContent;
  let ok = false;
  try { await navigator.clipboard.writeText(ta.value); ok = true; }
  catch (e) { ta.focus(); ta.select(); try { ok = document.execCommand("copy"); } catch (e2) {} }
  btn.textContent = ok ? "Copied ✓" : "Selected: press ⌘C";
  btn.classList.toggle("ok", ok);
  setTimeout(() => { btn.textContent = label; btn.classList.remove("ok"); }, 1500);
}));
progress();
"""


def checklist_html(start, end, cards, summary):
    e = html.escape
    last_day = end - timedelta(days=1)
    title = f"TikTok week of {start:%b} {start.day}"
    s = summary["settings"]
    out = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>{e(title)}</title><style>{CSS}</style></head>",
        f"<body data-week='{e(start.isoformat())}'><main>",
        f"<h1>{e(title)}</h1>",
        f"<p class='sub'>{start:%a %b} {start.day} – {last_day:%a %b} {last_day.day} · {plural(summary['posts'], 'post')} · times are Central"
        f" · {s['per_day']} shorts/day · carousels {'on' if s['carousels'] else 'off'} · {e(s['mix'])} mix</p>",
        "<div class='bar-wrap'><div class='bar'><i id='fill'></i></div><span id='count'></span></div>",
        "<div class='how'><b>For each card</b><ol>",
        "<li>Open <a href='https://www.tiktok.com/tiktokstudio/upload' target='_blank' rel='noopener'>TikTok Studio → Upload</a>"
        " and drag in the file from this folder.</li>",
        "<li>Copy the caption and paste it into the description.</li>",
        "<li>Shorts: under <b>Show more</b>, turn on <b>AI-generated content</b>.</li>",
        "<li>Choose <b>Schedule</b> and set the day and time on the card (your Mac's time zone, Central).</li>",
        "<li>Tick the card.</li></ol>",
        "<p>TikTok only schedules about 10 days ahead, so build each week's folder a day or two before it starts.</p></div>",
    ]
    day = None
    for c in cards:
        t = c["when"]
        if t.date() != day:
            day = t.date()
            out.append(f"<h2>{t:%A}, {t:%B} {t.day}</h2>")
        cid = f"c{c['n']}"
        meta = []
        if c["kind"] == "short":
            meta.append(f"{c['length']} video" if c.get("length") in ("long", "short") else "video")
            if c.get("seconds"):
                meta.append(f"{round(c['seconds'])} s")
            if c.get("fmt"):
                meta.append(c["fmt"].replace("_", " "))
        else:
            meta.append(f"photo carousel · {c['slides']} slides")
        out.append(f"<section class='card' data-id='{e(c['id'])}'>")
        out.append(f"<div class='top'><span class='num'>#{c['n']:02d}</span><span class='when'>{e(nice_time(t))}</span>"
                   + "".join(f"<span class='chip'>{e(m)}</span>" for m in meta) + "</div>")
        out.append(f"<div class='file'>{e(c['file'])}</div>")
        if c["kind"] == "short":
            out.append(f"<details><summary>Preview</summary><video src='{e(c['file'])}' controls preload='none'></video></details>")
        else:
            out.append(f"<label class='lbl' for='{cid}t'>Title</label>"
                       f"<textarea class='title' id='{cid}t' readonly>{e(c['title'])}</textarea>"
                       f"<button class='copy small' data-for='{cid}t'>Copy title</button>")
        out.append(f"<label class='lbl' for='{cid}'>TikTok caption</label>"
                   f"<textarea id='{cid}' readonly>{e(c['text'])}</textarea>"
                   f"<button class='copy' data-for='{cid}'>Copy caption</button>")
        if c["kind"] == "short":
            out.append("<div class='ai'>Turn on the <b>AI-generated content</b> label (Show more). The narration is AI.</div>")
        out.append("<label class='tick'><input type='checkbox'> Scheduled in TikTok Studio</label></section>")
    if not cards:
        out.append("<p class='empty'>Nothing to schedule this week.</p>")
    out.append("<div class='summary'><h3>Summary</h3>")
    if cards:
        out.append(f"<div>{plural(summary['posts'], 'post')} ({plural(summary['shorts'], 'short')}, "
                   f"{plural(summary['carousels'], 'carousel')}) · "
                   f"first {e(nice_time(summary['first']))} · last {e(nice_time(summary['last']))}</div>")
    if summary["skipped"]:
        out.append(f"<div style='margin-top:8px'><b>Skipped ({len(summary['skipped'])})</b><ul>")
        out += [f"<li>{e(nice_time(k['when']))} · {e(k['label'])} ({k['kind']}): {e(k['reason'])}</li>" for k in summary["skipped"]]
        out.append("</ul></div>")
    else:
        out.append("<div style='margin-top:8px'>Nothing skipped.</div>")
    out.append(f"</div></main><script>{JS}</script></body></html>")
    return "\n".join(out)


# ---------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description="Build a week of TikToks to schedule by hand in TikTok Studio.")
    ap.add_argument("--start", required=True, help="first day, YYYY-MM-DD (usually a Monday)")
    ap.add_argument("--days", type=int, default=7, help="how many days (default 7)")
    ap.add_argument("--per-day", type=int, default=SHORTS_PER_DAY, help=f"shorts per day (default {SHORTS_PER_DAY})")
    ap.add_argument("--carousels", action=argparse.BooleanOptionalAction, default=CAROUSELS,
                    help="also prepare photo carousels (default: %(default)s)")
    ap.add_argument("--mix", choices=["final", "clean"], default=MIX, help="final (with music) or clean (to add a TikTok sound)")
    ap.add_argument("--no-record", action="store_true", help="don't list the shorts in samsonsatprep-media/tiktok_weekly.json")
    ap.add_argument("--sat", default=str(REPO.parent), help="the SAT folder (default: %(default)s)")
    a = ap.parse_args(argv)
    paths = Paths(a.sat)
    if not paths.bank.exists():
        ap.error(f"shorts bank not found: {paths.bank}")
    s = build(paths, date.fromisoformat(a.start), a.days, max(0, a.per_day), a.carousels, a.mix, record=not a.no_record)
    print(f"TikTok week {s['week']} -> {s['folder']}")
    if s["posts"]:
        print(f"  {plural(s['posts'], 'post')} ({plural(s['shorts'], 'short')}, {plural(s['carousels'], 'carousel')})")
        print(f"  first: {nice_time(s['first'])} CT   last: {nice_time(s['last'])} CT")
    else:
        print("  nothing to schedule")
    print(f"  skipped: {len(s['skipped'])}" + ("" if s["skipped"] else " (none)"))
    for k in s["skipped"]:
        print(f"    {nice_time(k['when'])}  {k['label']} ({k['kind']}): {k['reason']}")
    print(f"  checklist: {Path(s['folder']) / 'checklist.html'}")
    if s["recorded"]:
        print(f"  listed {s['record_count']} shorts in samsonsatprep-media/tiktok_weekly.json: push the media repo"
              " (GitHub Desktop) so the daily prune knows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
