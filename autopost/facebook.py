"""Publish a Reel to the Facebook Page (never a personal profile) with the Page Reels API.

Flow (developers.facebook.com/docs/video-api/guides/reels-publishing, Graph API v26.0):
  1. POST graph.facebook.com/{page-id}/video_reels  upload_phase=start           -> video_id
  2. POST rupload.facebook.com/video-upload/{v}/{video_id}  (the MP4 bytes; headers offset=0, file_size)
  3. POST graph.facebook.com/{page-id}/video_reels  upload_phase=finish, video_state=PUBLISHED, description
  4. GET  graph.facebook.com/{video_id}?fields=status until publishing is complete (or an error shows up)
Auth is a Page access token (secret FB_PAGE_TOKEN, from /me/accounts with pages_show_list, pages_read_engagement and
pages_manage_posts). It always travels in the Authorization header, never in a URL, and error messages are scrubbed,
so it can't end up in the Actions log.
"""
import time

import requests

from . import config


class FacebookError(RuntimeError):
    pass


def _scrub(text):
    tok = config.FB_PAGE_TOKEN
    return str(text).replace(tok, "***") if tok else str(text)


def _headers(extra=None):
    h = {"Authorization": f"OAuth {config.FB_PAGE_TOKEN}"}
    h.update(extra or {})
    return h


def _call(method, url, **kw):
    try:
        r = requests.request(method, url, timeout=kw.pop("timeout", 120), **kw)
    except requests.RequestException as e:
        raise FacebookError(_scrub(f"{method} {url.split('?')[0]} failed: {e}")) from None
    data = r.json() if r.content and r.headers.get("content-type", "").startswith(("application/json", "text/javascript")) else {}
    if r.status_code >= 400 or (isinstance(data, dict) and "error" in data):
        raise FacebookError(_scrub(f"{method} {url.split('?')[0]} -> {r.status_code}: {data or r.text[:300]}"))
    return data


def ready():
    """True when the Page id and token are set."""
    return bool(config.FB_PAGE_ID and config.FB_PAGE_TOKEN)


def page_name():
    """The Page the token posts to (check_connections uses this; posts nothing)."""
    return _call("GET", f"{config.FB_GRAPH}/{config.FB_PAGE_ID}", params={"fields": "id,name"}, headers=_headers())


def verify_page():
    """The token must be the Page's own token: /me has to be the Page itself, never a person. Raises otherwise."""
    me = _call("GET", f"{config.FB_GRAPH}/me", params={"fields": "id,name"}, headers=_headers())
    if str(me.get("id")) != config.FB_PAGE_ID:
        raise FacebookError(f"FB_PAGE_TOKEN belongs to {me.get('name')!r} ({me.get('id')}), not Page {config.FB_PAGE_ID}: "
                            "use the Page access token from /me/accounts")
    return me


def reel_url(video_id):
    return f"https://www.facebook.com/reel/{video_id}"


def _status(video_id):
    return _call("GET", f"{config.FB_GRAPH}/{video_id}", params={"fields": "status"}, headers=_headers()).get("status", {})


def publish_reel(path, caption, wait_s=300):
    """Upload the MP4 at `path` and publish it as a Reel on the Page. Returns the video id."""
    if config.DRY_RUN:
        print(f"[dry-run] Facebook would publish reel {path}")
        return "dry-run"
    if not ready():
        raise FacebookError("FB_PAGE_ID or FB_PAGE_TOKEN missing")
    page = config.FB_PAGE_ID
    start = _call("POST", f"{config.FB_GRAPH}/{page}/video_reels", data={"upload_phase": "start"}, headers=_headers())
    vid = start.get("video_id")
    if not vid:
        raise FacebookError(f"start gave no video_id: {_scrub(start)}")
    with open(path, "rb") as fh:
        body = fh.read()
    up = _call("POST", f"{config.FB_RUPLOAD}/{vid}", data=body, timeout=600,
               headers=_headers({"offset": "0", "file_size": str(len(body)), "Content-Type": "application/octet-stream"}))
    if up.get("success") is not True:
        raise FacebookError(f"upload of video {vid} not confirmed: {_scrub(up)}")
    fin = _call("POST", f"{config.FB_GRAPH}/{page}/video_reels", headers=_headers(),
                data={"upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED", "description": caption})
    if fin.get("success") is not True:
        raise FacebookError(f"publish of video {vid} not confirmed: {_scrub(fin)}")
    # publishing is asynchronous: wait for it, and surface a processing error instead of recording a dead post
    deadline = time.time() + wait_s
    while time.time() < deadline:
        st = _status(vid)
        for phase in ("uploading_phase", "processing_phase", "publishing_phase"):
            err = (st.get(phase) or {}).get("error")
            if err:
                raise FacebookError(f"video {vid} {phase}: {_scrub(err)}")
        if (st.get("publishing_phase") or {}).get("status") == "complete" or st.get("video_status") == "ready":
            return vid
        time.sleep(10)
    print(f"WARN facebook video {vid}: still processing after {wait_s}s (published request accepted)")
    return vid
