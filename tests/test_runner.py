"""Offline tests: fake the Instagram/TikTok APIs and run the whole flow.

python -m unittest discover tests
"""
import importlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


class FakeResp:
    def __init__(self, data, status=200):
        self._d, self.status_code, self.content, self.text = data, status, b"x", json.dumps(data)

    def json(self):
        return self._d


class FakeAPIs:
    def __init__(self):
        self.calls = []
        self.n = 0

    def post(self, url, data=None, json=None, headers=None, timeout=None, params=None):
        self.calls.append(("POST", url, data or json))
        if "graph.instagram.com" in url:
            if url.endswith("/media_publish"):
                return FakeResp({"id": "IGMEDIA1"})
            self.n += 1
            return FakeResp({"id": f"C{self.n}"})
        if url.endswith("/oauth/token/"):
            return FakeResp({"access_token": "TT_ACCESS", "refresh_token": "TT_REFRESH_NEW"})
        if "creator_info" in url:
            return FakeResp({"data": {"privacy_level_options": ["SELF_ONLY"]}, "error": {"code": "ok"}})
        if "content/init" in url:
            return FakeResp({"data": {"publish_id": "TTPUB1"}, "error": {"code": "ok"}})
        raise AssertionError(f"unexpected POST {url}")

    def get(self, url, params=None, timeout=None):
        self.calls.append(("GET", url, params))
        return FakeResp({"status_code": "FINISHED"})


POST = {
    "id": "2026-10-12_q01", "publish_at": "2026-10-12T16:00:00-05:00", "type": "carousel",
    "slides": [f"slide{i}.jpg" for i in range(1, 5)],
    "slides_tiktok": [f"tslide{i}.jpg" for i in range(1, 5)],
    "platforms": ["instagram", "tiktok"], "caption": "Test caption", "tiktok_title": "Test",
    "hashtags_instagram": ["#SAT", "#SATmath", "#SATprep", "#digitalSAT", "#studytips"],
    "hashtags_tiktok": ["#SAT"],
}


def make_fixture(root):
    d = Path(root) / "posts" / POST["id"]
    d.mkdir(parents=True)
    (d / "post.json").write_text(json.dumps(POST))
    for f in POST["slides"] + POST["slides_tiktok"]:
        (d / f).write_bytes(b"\xff\xd8\xff\xd9")  # tiny JPEG marker, content isn't read


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        make_fixture(self.tmp)
        self.cwd = os.getcwd()
        os.chdir(self.tmp)  # public URLs use the post folder's path relative to the repo root
        env = {
            "PUBLIC_BASE_URL": "https://example.github.io/samsonsatprep-autopost",
            "IG_USER_ID": "123", "IG_ACCESS_TOKEN": "IGTOKEN",
            "TIKTOK_CLIENT_KEY": "k", "TIKTOK_CLIENT_SECRET": "s", "TIKTOK_REFRESH_TOKEN": "TT_REFRESH_OLD",
            "POSTS_DIR": "posts",
            "STATE_FILE": os.path.join(self.tmp, "posted.json"),
            "NEW_SECRETS_FILE": os.path.join(self.tmp, "new.env"),
            "DRY_RUN": "0",
        }
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        import autopost.config, autopost.instagram, autopost.tiktok, autopost.runner
        for m in (autopost.config, autopost.instagram, autopost.tiktok, autopost.runner):
            importlib.reload(m)
        self.runner = autopost.runner
        self.fake = FakeAPIs()
        self.p1 = mock.patch("requests.post", self.fake.post)
        self.p2 = mock.patch("requests.get", self.fake.get)
        self.p1.start(); self.p2.start()

    def tearDown(self):
        self.p1.stop(); self.p2.stop(); self.env.stop()
        os.chdir(self.cwd)

    def test_not_due_before_publish_time(self):
        early = datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc)  # 3pm CT, post is 4pm CT
        self.assertEqual(self.runner.run(now=early), 0)
        self.assertEqual(self.fake.calls, [])

    def test_posts_when_due_and_only_once(self):
        due = datetime(2026, 10, 12, 21, 7, tzinfo=timezone.utc)
        self.assertEqual(self.runner.run(now=due), 0)
        state = json.loads(Path(os.environ["STATE_FILE"]).read_text())
        self.assertEqual(state["2026-10-12_q01"]["instagram"]["id"], "IGMEDIA1")
        self.assertEqual(state["2026-10-12_q01"]["tiktok"]["id"], "TTPUB1")

        # Instagram: 4 carousel items + 1 carousel container + publish
        ig_posts = [c for c in self.fake.calls if c[0] == "POST" and "instagram" in c[1]]
        self.assertEqual(len(ig_posts), 6)
        carousel = ig_posts[4][2]
        self.assertEqual(carousel["media_type"], "CAROUSEL")
        self.assertEqual(carousel["children"], "C1,C2,C3,C4")
        self.assertIn("#SATmath", carousel["caption"])
        self.assertTrue(ig_posts[0][2]["image_url"].endswith("/posts/2026-10-12_q01/slide1.jpg"))

        # TikTok: direct post, private until audited, music auto-added, rotated refresh token handed back
        init = [c for c in self.fake.calls if "content/init" in c[1]][0][2]
        self.assertEqual(init["post_mode"], "DIRECT_POST")
        self.assertEqual(init["post_info"]["privacy_level"], "SELF_ONLY")
        self.assertTrue(init["post_info"]["auto_add_music"])
        self.assertEqual(init["post_info"]["description"], "Test caption\n\n#SAT")
        self.assertEqual(len(init["source_info"]["photo_images"]), 4)
        self.assertTrue(all("/posts/2026-10-12_q01/tslide" in u for u in init["source_info"]["photo_images"]))
        self.assertIn("TIKTOK_REFRESH_TOKEN=TT_REFRESH_NEW", Path(os.environ["NEW_SECRETS_FILE"]).read_text())

        # second run: nothing new
        n = len(self.fake.calls)
        self.assertEqual(self.runner.run(now=due), 0)
        self.assertEqual(len(self.fake.calls), n)

    def test_tiktok_unaudited_falls_back_to_private(self):
        import autopost.tiktok as tt
        calls = []
        def fake_call(path, token, body):
            calls.append(body.get("post_info", {}).get("privacy_level"))
            if "creator_info" in path:
                return {"privacy_level_options": ["PUBLIC_TO_EVERYONE", "SELF_ONLY"]}
            if body["post_info"]["privacy_level"] != "SELF_ONLY":
                raise tt.TikTokError("init failed: unaudited_client_can_only_post_to_private_accounts")
            return {"publish_id": "P"}
        with mock.patch.object(tt, "_call", fake_call):
            self.assertEqual(tt.publish_photos("t", ["u"], "x", "y"), "P")
        self.assertEqual(calls[1:], ["PUBLIC_TO_EVERYONE", "SELF_ONLY"])

    def test_tiktok_photo_draft_uses_media_upload(self):
        import autopost.tiktok as tt
        bodies = []
        def fake_call(path, token, body):
            bodies.append((path, body))
            return {"publish_id": "D"}
        with mock.patch.object(tt, "_call", fake_call):
            self.assertEqual(tt.publish_photos("t", ["u1", "u2"], "title", "desc", mode="draft"), "D")
        self.assertEqual(len(bodies), 1)  # no creator_info query for drafts
        path, body = bodies[0]
        self.assertEqual(path, "post/publish/content/init/")
        self.assertEqual(body["post_mode"], "MEDIA_UPLOAD")
        self.assertEqual(body["post_info"], {"title": "title", "description": "desc"})
        self.assertEqual(body["source_info"]["photo_images"], ["u1", "u2"])

    def test_runner_posts_photos_directly_by_default(self):
        import autopost.config as cfg
        self.assertEqual(cfg.TIKTOK_PHOTO_MODE, "direct")

    def test_check_passes(self):
        self.assertEqual(self.runner.check(), 0)


if __name__ == "__main__":
    unittest.main()
