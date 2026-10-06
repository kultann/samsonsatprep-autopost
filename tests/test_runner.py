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
        self.pushes = []
        self.ig_error = None
        self.n = 0

    def post(self, url, data=None, json=None, headers=None, timeout=None, params=None):
        self.calls.append(("POST", url, data or json))
        if "ntfy" in url:
            self.pushes.append((url, data, headers))
            return FakeResp({})
        if "graph.instagram.com" in url:
            if self.ig_error:
                return FakeResp({"error": {"message": self.ig_error, "type": "OAuthException", "code": 200}}, 400)
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
        if params and params.get("fields") == "permalink":
            return FakeResp({"permalink": "https://www.instagram.com/p/ABC123/"})
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
            "COOLDOWN_FILE": os.path.join(self.tmp, "cooldown.json"),
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

        # TikTok: photos go to the inbox as drafts (sound + privacy picked in-app), rotated refresh token handed back
        init = [c for c in self.fake.calls if "content/init" in c[1]][0][2]
        self.assertEqual(init["post_mode"], "MEDIA_UPLOAD")
        self.assertNotIn("privacy_level", init["post_info"])
        self.assertNotIn("auto_add_music", init["post_info"])
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

    def test_runner_sends_photos_as_drafts_by_default(self):
        import autopost.config as cfg
        self.assertEqual(cfg.TIKTOK_PHOTO_MODE, "draft")
        self.assertFalse(cfg.TIKTOK_AUTO_MUSIC)

    def test_full_draft_inbox_waits_instead_of_failing(self):
        import autopost.tiktok as tt
        due = datetime(2026, 10, 12, 21, 7, tzinfo=timezone.utc)
        err = tt.TikTokError("post/publish/content/init/ failed: {'error': {'code': 'spam_risk_too_many_pending_share'}}")
        with mock.patch.object(tt, "publish_photos", side_effect=err):
            self.assertEqual(self.runner.run(now=due), 0)  # not a failed run
        state = json.loads(Path(os.environ["STATE_FILE"]).read_text())
        self.assertIn("instagram", state["2026-10-12_q01"])
        self.assertNotIn("tiktok", state["2026-10-12_q01"])  # retried on a later run

    def test_music_reminder_push_after_instagram_post(self):
        due = datetime(2026, 10, 12, 21, 7, tzinfo=timezone.utc)
        self.assertEqual(self.runner.run(now=due), 0)
        self.assertEqual(self.fake.pushes, [])  # off when NTFY_TOPIC is empty
        Path(os.environ["STATE_FILE"]).unlink()
        with mock.patch.object(self.runner.config, "NTFY_TOPIC", "test-topic"):
            self.assertEqual(self.runner.run(now=due), 0)
        self.assertEqual(len(self.fake.pushes), 1)  # one per Instagram feed post, not per platform
        url, body, headers = self.fake.pushes[0]
        self.assertTrue(url.endswith("/test-topic"))
        self.assertEqual(headers["Click"], "https://www.instagram.com/p/ABC123/")
        self.assertIn("Test caption", body.decode("utf-8"))

    def test_instagram_block_pauses_instead_of_hammering(self):
        from datetime import timedelta
        due = datetime(2026, 10, 12, 21, 7, tzinfo=timezone.utc)
        self.fake.ig_error = "API access blocked."
        self.assertEqual(self.runner.run(now=due), 1)  # first failure of the streak is red
        cool = json.loads(Path(os.environ["COOLDOWN_FILE"]).read_text())
        self.assertEqual(cool["instagram"]["reason"], "API access blocked")
        state = json.loads(Path(os.environ["STATE_FILE"]).read_text())
        self.assertIn("tiktok", state["2026-10-12_q01"])  # other platforms keep going

        n = len(self.fake.calls)  # 1 h later: paused, no Instagram calls, green run
        self.assertEqual(self.runner.run(now=due + timedelta(hours=1)), 0)
        self.assertFalse([c for c in self.fake.calls[n:] if "instagram" in c[1]])

        n = len(self.fake.calls)  # 7 h later: tries once, still blocked -> paused again, still green
        self.assertEqual(self.runner.run(now=due + timedelta(hours=7)), 0)
        self.assertTrue([c for c in self.fake.calls[n:] if "instagram" in c[1]])
        cool = json.loads(Path(os.environ["COOLDOWN_FILE"]).read_text())
        self.assertEqual(cool["instagram"]["since"], due.isoformat(timespec="seconds"))

        self.fake.ig_error = None  # unblocked: posts and clears the pause
        self.assertEqual(self.runner.run(now=due + timedelta(hours=14)), 0)
        self.assertIn("instagram", json.loads(Path(os.environ["STATE_FILE"]).read_text())["2026-10-12_q01"])
        self.assertNotIn("instagram", json.loads(Path(os.environ["COOLDOWN_FILE"]).read_text()))

    def test_instagram_feed_posts_are_spaced_out(self):
        from datetime import timedelta
        second = dict(POST, id="2026-10-12_q02", publish_at="2026-10-12T16:05:00-05:00")
        d = Path("posts") / second["id"]
        d.mkdir(parents=True)
        (d / "post.json").write_text(json.dumps(second))
        for f in second["slides"] + second["slides_tiktok"]:
            (d / f).write_bytes(b"\xff\xd8\xff\xd9")
        due = datetime(2026, 10, 12, 21, 30, tzinfo=timezone.utc)
        self.assertEqual(self.runner.run(now=due), 0)
        state = json.loads(Path(os.environ["STATE_FILE"]).read_text())
        self.assertIn("instagram", state["2026-10-12_q01"])
        self.assertNotIn("instagram", state["2026-10-12_q02"])  # waits for the gap
        self.assertIn("tiktok", state["2026-10-12_q02"])  # TikTok isn't spaced
        self.runner.run(now=due + timedelta(minutes=15))
        self.assertNotIn("instagram", json.loads(Path(os.environ["STATE_FILE"]).read_text())["2026-10-12_q02"])
        self.runner.run(now=due + timedelta(minutes=45))
        self.assertIn("instagram", json.loads(Path(os.environ["STATE_FILE"]).read_text())["2026-10-12_q02"])

    def test_check_passes(self):
        self.assertEqual(self.runner.check(), 0)


if __name__ == "__main__":
    unittest.main()
