# samsonsatprep-autopost

Scheduled auto-posting for @samsonsatprep: carousels and images to Instagram and TikTok, and short videos to Instagram Reels, TikTok and YouTube Shorts.

- `posts/<id>/`: slides (JPEG) + `post.json` (time, caption, hashtags, platforms); shorts have `video.mp4` (+ optional `cover.jpg`) and `"type": "short"`
- `autopost/`: posting code (Instagram Graph API, TikTok Content Posting API, YouTube Data API)
- `.github/workflows/`: hourly poster + weekly Instagram token refresh
- `tools/`: `make_post.py` (PNG slides → post folder), `make_short.py` (MP4 → short post folder), `tiktok_auth.py` / `youtube_auth.py` (one-time logins), `ig_whoami.py`
- `index.html`, `privacy.html`, `terms.html`, `callback.html`: pages the Meta/TikTok apps need

Scheduled shorts (the 1000-short plan) live in the separate media repo `samsonsatprep-media`; the runner reads its `shorts/index.json` (variable `MEDIA_BASE_URL`).

Setup: see **SETUP.md**. Tests: `python3 -m unittest discover tests`.
