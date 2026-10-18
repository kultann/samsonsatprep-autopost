"""Offline tests for Facebook Page Reels (repo variable FB_PAGE). Fakes every API.

python3 -m unittest discover tests
"""
import importlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

PAGE_TOKEN = "EAAPAGESECRET123"
SHORT = {
    "id": "2026-10-13_desmos-systems", "publish_at": "2026-10-13T17:00:00-05:00", "type": "short",
    "video": "video.mp4", "platforms": ["instagram", "youtube"],
    "caption": "Stop solving systems by hand.", "hashtags_instagram": ["#SAT", "#Desmos"],
    "youtube": {"title": "Solve SAT Systems in Desmos", "description": "Graph both.", "hashtags": ["#SAT"]},
}


class Resp:
    def __init__(self, data=None, status=200):
        self._d, self.status_code = data or {}, status
        self.headers = {"content-type": "application/json"}
        self.content = b"x"; self.text = json.dumps(self._d)

    def json(self):
        return self._d


class FakeFB:
    """graph.facebook.com + rupload.facebook.com"""
    def __init__(self, me_id="999", fail_upload=0, publish_error=None):
        self.calls, self.me_id, self.fail_upload, self.publish_error = [], me_id, fail_upload, publish_error

    def request(self, method, url, timeout=None, data=None, params=None, headers=None):
        self.calls.append((method, url, data if not isinstance(data, bytes) else len(data), params, headers))
        assert PAGE_TOKEN not in url, "token must never be in a URL"
        assert headers and headers.get("Authorization") == f"OAuth {PAGE_TOKEN}"
        if url.endswith("/me"):
            return Resp({"id": self.me_id, "name": "Samsonsatprep" if self.me_id == "999" else "Samson Watson"})
        if url.endswith("/999/video_reels") and data.get("upload_phase") == "start":
            return Resp({"video_id": "FBVID", "upload_url": "https://rupload.facebook.com/video-upload/FBVID"})
        if "rupload.facebook.com" in url:
            if self.fail_upload:
                self.fail_upload -= 1
                return Resp({"error": {"message": f"boom {PAGE_TOKEN}"}}, status=500)
            assert headers["offset"] == "0" and headers["file_size"] == "1000"
            return Resp({"success": True})
        if url.endswith("/999/video_reels") and data.get("upload_phase") == "finish":
            assert data["video_state"] == "PUBLISHED" and data["video_id"] == "FBVID"
            return Resp({"success": True})
        if url.endswith("/FBVID"):
            if self.publish_error:
                return Resp({"status": {"processing_phase": {"status": "error", "error": {"message": self.publish_error}}}})
            return Resp({"status": {"video_status": "ready", "publishing_phase": {"status": "complete"}}})
        raise AssertionError(f"unexpected {method} {url}")


class FacebookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        d = Path(self.tmp) / "posts" / SHORT["id"]
        d.mkdir(parents=True)
        (d / "post.json").write_text(json.dumps(SHORT))
        (d / "video.mp4").write_bytes(b"\x00" * 1000)
        self.cwd = os.getcwd(); os.chdir(self.tmp)
        self.state_file = Path(self.tmp) / "posted.json"
        self.env = {"PUBLIC_BASE_URL": "https://example.github.io/x", "POSTS_DIR": "posts",
                    "STATE_FILE": str(self.state_file), "DRY_RUN": "0", "FB_PAGE_ID": "999", "FB_PAGE_TOKEN": PAGE_TOKEN,
                    "PRUNE_VIDEOS_AFTER_HOURS": "0"}
        # the reel is already on Instagram and YouTube, so only Facebook can be due
        self.state_file.write_text(json.dumps({SHORT["id"]: {
            "instagram": {"id": "IGREEL", "at": "2026-10-13T22:07:00+00:00"},
            "youtube": {"id": "YTVID", "at": "2026-10-13T22:08:00+00:00"}}}))
        self.now = datetime(2026, 10, 14, 10, 7, tzinfo=timezone.utc)
        mock.patch("time.sleep", lambda s: None).start()

    def tearDown(self):
        mock.patch.stopall(); os.chdir(self.cwd)

    def runner(self, mode, fake):
        mock.patch.dict(os.environ, {**self.env, "FB_PAGE": mode}).start()
        import autopost.config, autopost.facebook, autopost.runner
        for m in (autopost.config, autopost.facebook, autopost.runner):
            importlib.reload(m)
        mock.patch("requests.request", fake.request).start()
        return autopost.runner

    def state(self):
        return json.loads(self.state_file.read_text())

    def test_off_by_default(self):
        fake = FakeFB()
        r = self.runner("0", fake)
        self.assertEqual(r.run(now=self.now), 0)
        self.assertEqual(fake.calls, [])
        self.assertNotIn("facebook", self.state()[SHORT["id"]])

    def test_test_mode_posts_once_with_instagram_caption(self):
        fake = FakeFB()
        r = self.runner("test", fake)
        self.assertEqual(r.run(now=self.now), 0)
        st = self.state()
        self.assertEqual(st[SHORT["id"]]["facebook"]["id"], "FBVID")
        self.assertEqual(st["_facebook"]["test"]["post"], SHORT["id"])
        fin = [c for c in fake.calls if isinstance(c[2], dict) and c[2].get("upload_phase") == "finish"][0]
        self.assertEqual(fin[2]["description"], "Stop solving systems by hand.\n\n#SAT #Desmos")
        n = len(fake.calls)
        r.run(now=self.now)                      # second run: test already done, nothing more is posted
        self.assertEqual(len(fake.calls), n)

    def test_mode_1_does_not_backfill_and_posts_new_reels(self):
        fake = FakeFB()
        r = self.runner("1", fake)
        r.run(now=self.now)                      # first run starts the clock; the old reel stays off Facebook
        self.assertNotIn("facebook", self.state()[SHORT["id"]])
        self.assertIn("since", self.state()["_facebook"])
        st = self.state()                        # a reel that reaches Instagram after FB_PAGE=1 gets posted
        st[SHORT["id"]]["instagram"]["at"] = "2026-10-14T11:00:00+00:00"
        self.state_file.write_text(json.dumps(st))
        r.run(now=datetime(2026, 10, 14, 11, 7, tzinfo=timezone.utc))
        self.assertEqual(self.state()[SHORT["id"]]["facebook"]["id"], "FBVID")

    def test_failure_is_logged_retried_and_never_blocks(self):
        fake = FakeFB(fail_upload=1)
        r = self.runner("test", fake)
        with mock.patch("builtins.print") as pr:
            self.assertEqual(r.run(now=self.now), 0)         # Facebook failing doesn't fail the run
        out = " ".join(str(c.args[0]) for c in pr.call_args_list)
        self.assertIn("FAILED", out); self.assertIn("retrying next run", out)
        self.assertNotIn(PAGE_TOKEN, out)                    # the token never reaches the log
        self.assertNotIn("facebook", self.state()[SHORT["id"]])
        self.assertEqual(self.state()["_facebook"]["tries"][SHORT["id"]], 1)
        r.run(now=self.now)                                  # next run retries and succeeds, once
        self.assertEqual(self.state()[SHORT["id"]]["facebook"]["id"], "FBVID")
        self.assertNotIn(SHORT["id"], self.state()["_facebook"]["tries"])

    def test_processing_error_is_not_recorded_as_posted(self):
        fake = FakeFB(publish_error="Resolution too low")
        r = self.runner("test", fake)
        r.run(now=self.now)
        self.assertNotIn("facebook", self.state()[SHORT["id"]])

    def test_refuses_a_personal_token(self):
        fake = FakeFB(me_id="111")                           # /me is a person, not the Page
        r = self.runner("test", fake)
        with mock.patch("builtins.print") as pr:
            r.run(now=self.now)
        out = " ".join(str(c.args[0]) for c in pr.call_args_list)
        self.assertIn("not Page 999", out)
        self.assertFalse([c for c in fake.calls if "video_reels" in c[1]])
        self.assertNotIn("facebook", self.state()[SHORT["id"]])


if __name__ == "__main__":
    unittest.main()
