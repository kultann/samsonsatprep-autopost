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

# Behaviour
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"
POSTS_DIR = os.environ.get("POSTS_DIR", "posts")
STATE_FILE = os.environ.get("STATE_FILE", "state/posted.json")
