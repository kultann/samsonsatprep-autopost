"""Offline tests for shorts (Reels / TikTok video / YouTube Shorts). Fakes every API.

python3 -m unittest discover tests
"""
import importlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

VIDEO_BYTES = b"\x00" * 1000

SHORT = {
    "id": "2026-10-13_desmos-systems", "publish_at": "2026-10-13T17:00:00-05:00", "type": "short",
    "video": "video.mp4", "cover": "cover.jpg", "cover_time_ms": 800,
    "platforms": ["instagram", "tiktok", "youtube"],
    "caption": "Stop solving systems by hand.", "tiktok_caption": "Stop solving systems by hand (Desmos trick)",
    "hashtags_instagram": ["#SAT", "#SATmath", "#Desmos", "#MathHacks", "#DigitalSAT"],
    "hashtags_tiktok": ["#studytok", "#satprep", "#desmos"],
    "youtube": {"title": "Solve SAT Systems in Desmos in 5 Seconds", "description": "Graph both, click the cross.",
                "hashtags": ["#SAT", "#Desmos", "#DigitalSAT"]},
    "ai_label": True,
}


class Resp:
    def __init__(self, data=None, status=200, headers=None):
        self._d, self.status_code, self.headers = data or {}, status, headers or {}
        self.content = b"x"; self.text = json.dumps(self._d)

    def json(self):
        return self._d


class Fake:
    def __init__(self, pages_live=True):
        self.calls, self.pages_live = [], pages_live

    def post(self, url, data=None, json=None, headers=None, timeout=None, params=None):
        self.calls.append(("POST", url, data or json, headers))
        if "graph.instagram.com" in url:
            return Resp({"id": "IGREEL" if url.endswith("media_publish") else "C1"})
        if url.endswith("/oauth/token/"):
            return Resp({"access_token": "TT", "refresh_token": "TT_REFRESH_OLD"})
        if "creator_info" in url:
            return Resp({"data": {"privacy_level_options": ["SELF_ONLY"]}, "error": {"code": "ok"}})
        if "video/init" in url:
            return Resp({"data": {"publish_id": "TTVID", "upload_url": "https://upload.tiktok/x"}, "error": {"code": "ok"}})
        if "oauth2.googleapis.com" in url:
            return Resp({"access_token": "YT"})
        if "upload/youtube" in url:
            return Resp({}, headers={"Location": "https://upload.youtube/session1"})
        raise AssertionError(f"unexpected POST {url}")

    def get(self, url, params=None, timeout=None):
        self.calls.append(("GET", url, params, None))
        return Resp({"status_code": "FINISHED"})

    def put(self, url, data=None, headers=None, timeout=None):
        self.calls.append(("PUT", url, len(data), headers))
        if "tiktok" in url:
            return Resp({}, status=201)
        return Resp({"id": "YTVID", "status": {"privacyStatus": "private"}})

    def head(self, url, allow_redirects=True, timeout=None):
        self.calls.append(("HEAD", url, None, None))
        return Resp({}, status=200 if self.pages_live else 404)


class ShortsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        d = Path(self.tmp) / "posts" / SHORT["id"]
        d.mkdir(parents=True)
        (d / "post.json").write_text(json.dumps(SHORT))
        (d / "video.mp4").write_bytes(VIDEO_BYTES)
        (d / "cover.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        self.dir = d
        self.cwd = os.getcwd(); os.chdir(self.tmp)
        env = {
            "PUBLIC_BASE_URL": "https://example.github.io/samsonsatprep-autopost",
            "IG_USER_ID": "123", "IG_ACCESS_TOKEN": "IGTOKEN",
            "TIKTOK_CLIENT_KEY": "k", "TIKTOK_CLIENT_SECRET": "s", "TIKTOK_REFRESH_TOKEN": "TT_REFRESH_OLD",
            "YT_CLIENT_ID": "id", "YT_CLIENT_SECRET": "sec", "YT_REFRESH_TOKEN": "rt",
            "POSTS_DIR": "posts", "STATE_FILE": os.path.join(self.tmp, "posted.json"),
            "NEW_SECRETS_FILE": os.path.join(self.tmp, "new.env"), "DRY_RUN": "0",
        }
        self.env = mock.patch.dict(os.environ, env); self.env.start()
        import autopost.config, autopost.instagram, autopost.tiktok, autopost.youtube, autopost.runner
        for m in (autopost.config, autopost.instagram, autopost.tiktok, autopost.youtube, autopost.runner):
            importlib.reload(m)
        self.runner = autopost.runner
        self.due = datetime(2026, 10, 13, 22, 7, tzinfo=timezone.utc)

    def tearDown(self):
        mock.patch.stopall(); self.env.stop(); os.chdir(self.cwd)

    def patch(self, fake):
        for name in ("post", "get", "put", "head"):
            mock.patch(f"requests.{name}", getattr(fake, name)).start()

    def test_short_posts_to_all_three(self):
        fake = Fake(); self.patch(fake)
        self.assertEqual(self.runner.run(now=self.due), 0)
        state = json.loads(Path(os.environ["STATE_FILE"]).read_text())[SHORT["id"]]
        self.assertEqual({k: v["id"] for k, v in state.items()},
                         {"instagram": "IGREEL", "tiktok": "TTVID", "youtube": "YTVID"})

        ig = [c[2] for c in fake.calls if c[0] == "POST" and c[1].endswith("/123/media")][0]
        self.assertEqual(ig["media_type"], "REELS")
        self.assertTrue(ig["video_url"].endswith(f"/posts/{SHORT['id']}/video.mp4"))
        self.assertTrue(ig["cover_url"].endswith("/cover.jpg"))
        self.assertIn("#Desmos", ig["caption"])

        init = [c[2] for c in fake.calls if "video/init" in c[1]][0]
        self.assertEqual(init["post_info"]["privacy_level"], "SELF_ONLY")
        self.assertTrue(init["post_info"]["is_aigc"])
        self.assertEqual(init["post_info"]["video_cover_timestamp_ms"], 800)
        self.assertIn("#desmos", init["post_info"]["title"])
        self.assertEqual(init["source_info"], {"source": "FILE_UPLOAD", "video_size": 1000,
                                               "chunk_size": 1000, "total_chunk_count": 1})
        tput = [c for c in fake.calls if c[0] == "PUT" and "tiktok" in c[1]][0]
        self.assertEqual(tput[3]["Content-Range"], "bytes 0-999/1000")

        sess = [c for c in fake.calls if "upload/youtube" in c[1]][0]
        self.assertEqual(sess[2]["snippet"]["title"], SHORT["youtube"]["title"])
        self.assertEqual(sess[2]["snippet"]["categoryId"], "27")
        self.assertEqual(sess[2]["status"]["privacyStatus"], "public")
        self.assertIn("#Desmos", sess[2]["snippet"]["description"])
        self.assertEqual(sess[3]["X-Upload-Content-Length"], "1000")

        n = len(fake.calls)  # second run posts nothing
        self.assertEqual(self.runner.run(now=self.due), 0)
        self.assertEqual(len([c for c in fake.calls[n:] if c[0] != "HEAD"]), 0)

    def test_instagram_waits_for_pages(self):
        fake = Fake(pages_live=False); self.patch(fake)
        self.assertEqual(self.runner.run(now=self.due), 0)  # not a failure, just retried next hour
        state = json.loads(Path(os.environ["STATE_FILE"]).read_text())[SHORT["id"]]
        self.assertNotIn("instagram", state)
        self.assertIn("tiktok", state)
        fake.pages_live = True
        self.runner.run(now=self.due)
        state = json.loads(Path(os.environ["STATE_FILE"]).read_text())[SHORT["id"]]
        self.assertIn("instagram", state)

    def test_video_pruned_after_everything_posted(self):
        fake = Fake(); self.patch(fake)
        self.runner.run(now=self.due)
        self.runner.run(now=self.due + timedelta(hours=1))
        self.assertTrue((self.dir / "video.mp4").exists())  # too soon
        self.runner.run(now=self.due + timedelta(hours=49))
        self.assertFalse((self.dir / "video.mp4").exists())
        self.assertEqual(self.runner.check(), 0)  # a pruned, fully posted short still validates

    def test_validation(self):
        p = dict(SHORT, _dir=self.dir, youtube={"title": ""})
        self.assertIn("youtube.title missing", self.runner.validate(p))
        p = dict(SHORT, _dir=self.dir, video="nope.mp4")
        self.assertTrue(any("file not found" in e for e in self.runner.validate(p)))
        p = dict(SHORT, _dir=self.dir, platforms=["instagram", "snapchat"])
        self.assertTrue(any("unknown platform" in e for e in self.runner.validate(p)))

    def test_tiktok_draft_for_trending_audio(self):
        """Manual trending-audio shorts: TikTok gets a draft (clean mix), YouTube the full mix."""
        fake = Fake(); self.patch(fake)
        (self.dir / "video_final.mp4").write_bytes(b"\x00" * 2000)
        post = dict(SHORT, platforms=["tiktok", "youtube"], tiktok_mode="draft", video_youtube="video_final.mp4")
        (self.dir / "post.json").write_text(json.dumps(post))
        self.assertEqual(self.runner.run(now=self.due), 0)
        self.assertTrue(any("inbox/video/init" in c[1] for c in fake.calls if c[0] == "POST"))
        yt = [c for c in fake.calls if "upload/youtube" in c[1]][0]
        self.assertEqual(yt[3]["X-Upload-Content-Length"], "2000")

    def test_chunk_plan(self):
        import autopost.tiktok as tt
        MB = 1024 * 1024
        self.assertEqual(tt._chunk_plan(3 * MB), (3 * MB, 1))
        self.assertEqual(tt._chunk_plan(64 * MB), (64 * MB, 1))
        self.assertEqual(tt._chunk_plan(95 * MB), (10 * MB, 9))  # last chunk carries the extra 5 MB

    def test_tiktok_draft_mode(self):
        import autopost.tiktok as tt
        seen = []
        def fake_call(path, token, body):
            seen.append(path)
            return {"publish_id": "D1", "upload_url": "https://upload.tiktok/x"}
        with mock.patch.object(tt, "_call", fake_call), mock.patch.object(tt, "_upload", lambda *a: None):
            self.assertEqual(tt.publish_video("t", str(self.dir / "video.mp4"), "cap", mode="draft"), "D1")
        self.assertEqual(seen, ["post/publish/inbox/video/init/"])


class MediaRepoTest(unittest.TestCase):
    """Shorts that live in the separate media repo: read from shorts/index.json, video downloaded at post time."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        (Path(self.tmp) / "posts").mkdir()
        self.cwd = os.getcwd(); os.chdir(self.tmp)
        env = {
            "PUBLIC_BASE_URL": "https://example.github.io/samsonsatprep-autopost",
            "MEDIA_BASE_URL": "https://example.github.io/samsonsatprep-media",
            "IG_USER_ID": "123", "IG_ACCESS_TOKEN": "IGTOKEN",
            "TIKTOK_CLIENT_KEY": "k", "TIKTOK_CLIENT_SECRET": "s", "TIKTOK_REFRESH_TOKEN": "TT_REFRESH_OLD",
            "POSTS_DIR": "posts", "STATE_FILE": os.path.join(self.tmp, "posted.json"),
            "NEW_SECRETS_FILE": os.path.join(self.tmp, "new.env"), "DRY_RUN": "0",
        }
        self.env = mock.patch.dict(os.environ, env); self.env.start()
        import autopost.config, autopost.instagram, autopost.tiktok, autopost.youtube, autopost.runner
        for m in (autopost.config, autopost.instagram, autopost.tiktok, autopost.youtube, autopost.runner):
            importlib.reload(m)
        self.runner = autopost.runner
        entry = dict(SHORT, id="2026-10-12_0800_M1-036", folder="2026-10-12_0800_M1-036",
                     publish_at="2026-10-12T08:00:00-05:00", platforms=["instagram", "tiktok"])
        entry.pop("youtube")
        self.fake = Fake()
        real_get = self.fake.get
        downloads = []
        def get(url, params=None, timeout=None):
            if url.endswith("/shorts/index.json"):
                return Resp(json.loads(json.dumps([entry])))  # fresh copy, like a real HTTP response
            if url.endswith("/video.mp4"):
                downloads.append(url)
                r = Resp({}); r.content = VIDEO_BYTES; return r
            return real_get(url, params=params, timeout=timeout)
        self.fake.get = get
        self.downloads = downloads
        for name in ("post", "get", "put", "head"):
            mock.patch(f"requests.{name}", getattr(self.fake, name)).start()

    def tearDown(self):
        mock.patch.stopall(); self.env.stop(); os.chdir(self.cwd)

    def test_media_short_posts_and_downloads_video(self):
        self.assertEqual(self.runner.check(), 0)
        due = datetime(2026, 10, 12, 13, 7, tzinfo=timezone.utc)
        self.assertEqual(self.runner.run(now=due), 0)
        state = json.loads(Path(os.environ["STATE_FILE"]).read_text())["2026-10-12_0800_M1-036"]
        self.assertEqual(sorted(state), ["instagram", "tiktok"])
        ig = [c[2] for c in self.fake.calls if c[0] == "POST" and c[1].endswith("/123/media")][0]
        self.assertEqual(ig["video_url"], "https://example.github.io/samsonsatprep-media/shorts/2026-10-12_0800_M1-036/video.mp4")
        self.assertEqual(len(self.downloads), 1)  # TikTok upload pulled the file from the media repo
        tput = [c for c in self.fake.calls if c[0] == "PUT" and "tiktok" in c[1]][0]
        self.assertEqual(tput[3]["Content-Range"], "bytes 0-999/1000")


if __name__ == "__main__":
    unittest.main()
