"""(Re)date the long-form videos that haven't been uploaded yet.

Fills slots on the chosen weekdays at a fixed local time, in video order. Videos with a test-date
"window" go in the slot closest to (test date - lead_days) that's still before the test; a
date-specific one ("required") that can't fit before its test is left alone (the bot holds it).
Already-uploaded videos (state/posted.json) and "manual" ones are never touched.

  python3 tools/schedule_longform.py --start 2026-10-11                  # Sun/Tue/Thu at 4:00 PM Central
  python3 tools/schedule_longform.py --start 2026-11-01 --days sun,wed --time 15:30
  python3 tools/schedule_longform.py --start 2026-10-11 --dry            # print only
"""
import argparse
import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent
DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def slots(start, days, at, tz, n):
    out, d = [], start
    while len(out) < n:
        if d.weekday() in days:
            out.append(datetime.combine(d, at, tz))
        d += timedelta(days=1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="first possible day, YYYY-MM-DD")
    ap.add_argument("--days", default="sun,tue,thu")
    ap.add_argument("--time", default="16:00", help="local time, HH:MM")
    ap.add_argument("--tz", default="America/Chicago")
    ap.add_argument("--dir", default=str(REPO / "longform"))
    ap.add_argument("--state", default=str(REPO / "state" / "posted.json"))
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    tz = ZoneInfo(args.tz)
    days = {DAYS[x.strip().lower()[:3]] for x in args.days.split(",")}
    at = time.fromisoformat(args.time)
    start = date.fromisoformat(args.start)
    state_file = Path(args.state)
    state = json.loads(state_file.read_text()) if state_file.exists() else {}

    files = sorted(Path(args.dir).glob("*/post.json"))
    posts = []
    for f in files:
        p = json.loads(f.read_text())
        if p.get("manual") or "youtube" in (state.get(p["id"]) or {}):
            continue
        posts.append((f, p))
    posts.sort(key=lambda fp: fp[1].get("order", 0))
    free = slots(start, days, at, tz, len(posts) + 60)
    plan = {}

    for f, p in posts:  # test-date videos first
        win = p.get("window")
        if not win:
            continue
        test_day = date.fromisoformat(win["test_date"])
        target = test_day - timedelta(days=win.get("lead_days", 7))
        fits = [s for s in free if s.date() < test_day]
        if not fits:
            if win.get("required"):
                print(f"HOLD {p['id']}: no slot before {test_day}; retitle it (drop the date) and remove 'window'/'expires_at'")
                plan[p["id"]] = None
            continue  # evergreen: scheduled with the rest below
        best = min(fits, key=lambda s: (abs((s.date() - target).days), s))
        free.remove(best)
        plan[p["id"]] = best
    for f, p in posts:
        if p["id"] not in plan:
            plan[p["id"]] = free.pop(0)

    for f, p in sorted(posts, key=lambda fp: (plan[fp[1]["id"]] or datetime.max.replace(tzinfo=tz))):
        when = plan[p["id"]]
        if when is None:
            continue
        print(f"{when.strftime('%a %Y-%m-%d %H:%M %Z'):<26} {p['id']}")
        if not args.dry:
            p["publish_at"] = when.isoformat()
            f.write_text(json.dumps(p, indent=2, ensure_ascii=False) + "\n")
    print(f"\n{len(posts)} video(s) {'would be ' if args.dry else ''}scheduled from {start}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
