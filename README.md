# samsonsatprep-autopost

Scheduled auto-posting of carousels and images to Instagram and TikTok for @samsonsatprep.

- `posts/<id>/`: slides (JPEG) + `post.json` (time, caption, hashtags, platforms)
- `autopost/`: posting code (Instagram Graph API, TikTok Content Posting API)
- `.github/workflows/`: hourly poster + weekly Instagram token refresh
- `tools/`: `make_post.py` (PNG slides → post folder), `tiktok_auth.py` (one-time login), `ig_whoami.py`
- `index.html`, `privacy.html`, `terms.html`, `callback.html`: pages the Meta/TikTok apps need

Setup: see **SETUP.md**. Tests: `python3 -m unittest discover tests`.
