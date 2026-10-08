"""Settings read from environment variables (set as GitHub Actions secrets/vars)."""
import os

# Public base URL where the repo's files are served (GitHub Pages).
# e.g. https://<github-username>.github.io/samsonsatprep-autopost
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")

# Instagram (Instagram API with Instagram Login)
IG_USER_ID = os.environ.get("IG_USER_ID", "")
IG_ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "")
IG_API_VERSION = os.environ.get("IG_API_VERSION", "v23.0")
IG_GRAPH = f"https://graph.instagram.com/{IG_API_VERSION}"

# TikTok (Content Posting API)
TIKTOK_CLIENT_KEY = os.environ.get("TIKTOK_CLIENT_KEY", "")
TIKTOK_CLIENT_SECRET = os.environ.get("TIKTOK_CLIENT_SECRET", "")
TIKTOK_REFRESH_TOKEN = os.environ.get("TIKTOK_REFRESH_TOKEN", "")
TIKTOK_API = "https://open.tiktokapis.com/v2"

# YouTube (Data API v3). Refresh token from tools/youtube_auth.py
YT_CLIENT_ID = os.environ.get("YT_CLIENT_ID", "")
YT_CLIENT_SECRET = os.environ.get("YT_CLIENT_SECRET", "")
YT_REFRESH_TOKEN = os.environ.get("YT_REFRESH_TOKEN", "")
YT_PRIVACY = os.environ.get("YT_PRIVACY", "") or "public"

# Shorts: delete a short's video file this many hours after every platform has it,
# so GitHub Pages stays under its 1 GB limit. 0 = keep forever.
PRUNE_VIDEOS_AFTER_HOURS = float(os.environ.get("PRUNE_VIDEOS_AFTER_HOURS", "") or 48)

# Short videos live in a separate public "media" repo with its own GitHub Pages site, so this
# repo's Pages site stays under 1 GB. The runner reads MEDIA_BASE_URL/shorts/index.json (every
# scheduled short's post.json) and downloads a video only when it's time to post it.
MEDIA_BASE_URL = os.environ.get("MEDIA_BASE_URL", "").rstrip("/")

# Post at most this many shorts per run (oldest first). If a batch is rendered late or GitHub
# Actions was down, overdue shorts drip out one per hourly run instead of all at once. 0 = no limit.
MAX_SHORTS_PER_RUN = int(os.environ.get("MAX_SHORTS_PER_RUN", "") or 1)

# Phone push (ntfy.sh) each time a feed post goes live on Instagram, so Samson can add music
# in the app (post -> Edit -> Add music). The API can't attach Instagram library music.
# Set the secret NTFY_TOPIC to a long random name and subscribe to it in the ntfy app. Empty = off.
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()

# Back off instead of hammering a platform that is blocking us (Samson, 2026-10-06: Instagram returned
# "API access blocked" and every 15-min run retried every post, 44 red runs in a day).
# A matching error pauses that platform; only the first failure of a streak turns the run red.
COOLDOWN_FILE = os.environ.get("COOLDOWN_FILE", "state/cooldown.json")
IG_BLOCK_COOLDOWN_HOURS = float(os.environ.get("IG_BLOCK_COOLDOWN_HOURS", "") or 6)
TIKTOK_APP_COOLDOWN_HOURS = float(os.environ.get("TIKTOK_APP_COOLDOWN_HOURS", "") or 3)
# Space out Instagram posts (feed AND Reels, 2026-10-06 after two flags): at most one per run and at
# least this many minutes apart, so a
# backlog drips out instead of posting in a burst (bursts on a new account look automated).
# 40 min with runs every 15 min (cron-job.org) = one Instagram post about every 45 min.
IG_FEED_MIN_GAP_MINUTES = float(os.environ.get("IG_FEED_MIN_GAP_MINUTES", "") or 40)
NTFY_SERVER = (os.environ.get("NTFY_SERVER", "") or "https://ntfy.sh").rstrip("/")

# TikTok photo carousels: "direct" (default, Samson 2026-10-05) posts straight to the profile (no
# auto-added sound, see TIKTOK_AUTO_MUSIC); "draft" sends each one to the TikTok inbox (needs the TikTok phone app on its latest
# version) so a sound can be added before posting. A post's "tiktok_mode" overrides it.
# Samson 2026-10-06: "direct", silent. Drafts only reach the TikTok PHONE app (he is only logged in on
# the computer, so they failed with app_version_check_failed); switch back if he installs the app.
TIKTOK_PHOTO_MODE = os.environ.get("TIKTOK_PHOTO_MODE", "") or "direct"
# Let TikTok pick a random sound for direct photo posts? Off (Samson, 2026-10-05: the picks can be anything).
TIKTOK_AUTO_MUSIC = (os.environ.get("TIKTOK_AUTO_MUSIC", "") or "0") == "1"

# Behaviour
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"
POSTS_DIR = os.environ.get("POSTS_DIR", "posts")
STATE_FILE = os.environ.get("STATE_FILE", "state/posted.json")

# Long-form videos (longform/<id>/post.json), YouTube only. See autopost/longform.py and SETUP.md section 8.
# OFF until the YouTube API audit passes: uploads from an unverified project are locked private for good,
# so the bot must not burn the real videos early. "0" = off, "test" = one private [TEST] upload of the
# first video to check the whole pipeline (delete it in Studio afterwards), "1" = on.
YT_LONGFORM = (os.environ.get("YT_LONGFORM", "") or "0").strip().lower()
LONGFORM_DIR = os.environ.get("LONGFORM_DIR", "longform")
# Each YouTube Short is matched to a long-form video (best match first) by script id; see autopost/related.py.
RELATED_MAP = os.environ.get("RELATED_MAP", "") or os.path.join(LONGFORM_DIR, "related_map.json")
# Upload this many hours before publish_at as a scheduled video (private + publishAt): YouTube finishes HD
# processing, and there's time to add the Test & Compare B thumbnail in Studio before it goes live.
LONGFORM_UPLOAD_LEAD_HOURS = float(os.environ.get("LONGFORM_UPLOAD_LEAD_HOURS", "") or 24)
# Never publish two long videos closer than this. If the schedule is stale (say the audit passed weeks
# after the planned dates), overdue videos go out one at a time this far apart instead of all at once.
LONGFORM_MIN_GAP_HOURS = float(os.environ.get("LONGFORM_MIN_GAP_HOURS", "") or 40)
LONGFORM_MAX_PER_RUN = int(os.environ.get("LONGFORM_MAX_PER_RUN", "") or 1)
# Where the MP4s live: GitHub caps repo files at 100 MB, so they're assets of a release tagged "longform"
# in this repo (2 GB per file, no total limit). Override with the repo variable LONGFORM_VIDEO_BASE.
LONGFORM_VIDEO_BASE = (os.environ.get("LONGFORM_VIDEO_BASE", "") or
                       "https://github.com/{}/releases/download/longform".format(
                           os.environ.get("GITHUB_REPOSITORY", "") or "kultann/samsonsatprep-autopost")).rstrip("/")
# Also upload each video's .srt captions. Needs the youtube.force-ssl scope, which the current login
# (tools/youtube_auth.py) doesn't have, so it's off; without it YouTube makes automatic captions.
YT_CAPTIONS = (os.environ.get("YT_CAPTIONS", "") or "0") == "1"

# YouTube pacing (autopost/ytpace.py), for Shorts and long-form alike, so uploads never come in a burst.
YT_MIN_GAP_MINUTES = float(os.environ.get("YT_MIN_GAP_MINUTES", "") or 45)
YT_MAX_PER_DAY = int(os.environ.get("YT_MAX_PER_DAY", "") or 10)
YT_COOLDOWN_HOURS = float(os.environ.get("YT_COOLDOWN_HOURS", "") or 12)
