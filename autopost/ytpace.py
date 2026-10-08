"""Pace YouTube uploads (Shorts + long-form) so the channel never looks like a bot burst.

Samson, 2026-10-08: "make sure the post time is timed out so YouTube doesn't think my API is sus"
(Instagram flagged the account twice after bursts). Rules, all from repo variables:
- at least YT_MIN_GAP_MINUTES (45) between any two YouTube uploads, Shorts or long videos
- at most YT_MAX_PER_DAY (10) uploads in any rolling 24 hours (the plan is ~7 Shorts a day +
  3 long videos a week)
- errors that mean "slow down" pause YouTube (state/cooldown.json, same as Instagram/TikTok):
  quotaExceeded / uploadLimitExceeded -> YT_COOLDOWN_HOURS (12), rateLimitExceeded -> 1 hour
Videos that are held back just go out on a later run (log: LATER); nothing is skipped.
"""
from datetime import datetime, timedelta

from . import config


def _parse(ts):
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def rules():
    """(text in the error, hours to pause YouTube)."""
    return [
        ("quotaExceeded", config.YT_COOLDOWN_HOURS),
        ("uploadLimitExceeded", config.YT_COOLDOWN_HOURS),
        ("rateLimitExceeded", 1),
    ]


def upload_times(state, now):
    """When each YouTube upload happened (from state/posted.json)."""
    out = []
    for v in state.values():
        if not isinstance(v, dict):
            continue
        rec = v.get("youtube") if isinstance(v.get("youtube"), dict) else (v if "post" in v else None)
        if isinstance(rec, dict) and rec.get("at"):
            try:
                t = _parse(rec["at"])
            except ValueError:
                continue
            if t <= now:  # ignore records stamped "in the future" (only happens in tests)
                out.append(t)
    return out


def blocked(state, now, cool=None):
    """Why YouTube can't take another upload right now, or None."""
    rec = (cool or {}).get("youtube")
    if rec and _parse(rec["until"]) > now:
        return f"paused until {rec['until']} ({rec['reason']})"
    times = upload_times(state, now)
    if not times:
        return None
    if now - max(times) < timedelta(minutes=config.YT_MIN_GAP_MINUTES):
        return f"YouTube uploads are spaced {config.YT_MIN_GAP_MINUTES:g} min apart"
    if sum(1 for t in times if now - t < timedelta(hours=24)) >= config.YT_MAX_PER_DAY:
        return f"max {config.YT_MAX_PER_DAY} YouTube uploads per 24 hours"
    return None


def pause_for(err, cool, now):
    """Pause YouTube if err means 'slow down'. Returns 'new', 'repeat' or None."""
    for needle, hours in rules():
        if needle in str(err):
            prev = cool.get("youtube")
            repeat = bool(prev) and prev.get("reason") == needle
            until = (now + timedelta(hours=hours)).isoformat(timespec="seconds")
            cool["youtube"] = {"until": until, "reason": needle,
                               "since": prev["since"] if repeat else now.isoformat(timespec="seconds")}
            print(f"PAUSE youtube until {until}: {needle}" + (" (still limited)" if repeat else ""))
            return "repeat" if repeat else "new"
    return None
