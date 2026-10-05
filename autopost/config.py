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

# TikTok photo carousels: "draft" (default) sends each one to the TikTok inbox so a sound can be
# added before posting; "direct" posts straight to the profile. A post's "tiktok_mode" overrides it.
TIKTOK_PHOTO_MODE = os.environ.get("TIKTOK_PHOTO_MODE", "") or "draft"

# Behaviour
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"
POSTS_DIR = os.environ.get("POSTS_DIR", "posts")
STATE_FILE = os.environ.get("STATE_FILE", "state/posted.json")
