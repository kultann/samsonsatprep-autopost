"""Offline tests for linking YouTube Shorts to long-form videos (autopost/related.py)."""
import importlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

NOW = datetime(2026, 11, 20, 18, 0, tzinfo=timezone.utc)
SHORT_ID = "2026-11-20_1200_M1-036"
SHORT = {
    "id": SHORT_ID, "publish_at": "2026-11-20T12:00:00-06:00", "type": "short",
    "video": "video.mp4", "cover": "cover.jpg", "cover_time_ms": 500, "platforms": ["youtube"],
    "caption": "Turn the words into a slope first.", "tiktok_caption": "Slope first.",
    "hashtags_instagram": [], "hashtags_tiktok": [],
    "youtube": {"title": "Build a Linear Function From Rate Words", "description": "SAT-style practice question (original).",
                "hashtags": ["#SAT", "#SATmath"]},
}


def long_rec(vid, publish_at, privacy="scheduled"):
    return {"youtube": {"id": vid, "at": "2026-11-01T00:00:00+00:00", "publish_at": publish_at, "privacy": privacy}}


class RelatedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        t = Path(self.tmp)
        d = t / "posts" / SHORT_ID
        d.mkdir(parents=True)
        (d / "post.json").write_text(json.dumps(SHORT))
        (d / "video.mp4").write_bytes(b"\x00" * 100)
        (d / "cover.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        for lid, title in (("long-13_linear", "SAT Linear Functions & Word Problems"),
                           ("long-09_math", "All 19 SAT Math Skills Explained")):
            (t / "longform" / lid).mkdir(parents=True)
            (t / "longform" / lid / "post.json").write_text(json.dumps({"id": lid, "title": title}))
        (t / "related_map.json").write_text(json.dumps({"M1-036": ["long-13_linear", "long-09_math"]}))
        self.state_file = t / "posted.json"
        self.cwd = os.getcwd(); os.chdir(self.tmp)
        env = {"POSTS_DIR": "posts", "LONGFORM_DIR": "longform", "STATE_FILE": str(self.state_file),
               "RELATED_MAP": str(t / "related_map.json"), "DRY_RUN": "0", "MEDIA_BASE_URL": "",
               "YT_CLIENT_ID": "id", "YT_CLIENT_SECRET": "s", "YT_REFRESH_TOKEN": "r"}
        self.env = mock.patch.dict(os.environ, env); self.env.start()
        import autopost.config, autopost.longform, autopost.related, autopost.runner
        for m in (autopost.config, autopost.longform, autopost.related, autopost.runner):
            importlib.reload(m)
        self.related, self.runner = autopost.related, autopost.runner

    def tearDown(self):
        mock.patch.stopall(); self.env.stop(); os.chdir(self.cwd)

    def test_picks_best_match_that_is_already_public(self):
        state = {"long-13_linear": long_rec("LIN", "2026-11-25T22:00:00+00:00"),   # not live yet
                 "long-09_math": long_rec("MATH", "2026-11-01T22:00:00+00:00", "public")}
        self.assertEqual(self.related.pick(SHORT_ID, state, NOW)["long"], "long-09_math")
        later = NOW + timedelta(days=6)
        rel = self.related.pick(SHORT_ID, state, later)
        self.assertEqual((rel["long"], rel["video"], rel["title"]),
                         ("long-13_linear", "LIN", "SAT Linear Functions & Word Problems"))

    def test_nothing_live_or_test_copy_gives_none(self):
        self.assertIsNone(self.related.pick(SHORT_ID, {}, NOW))
        state = {"long-13_linear": long_rec("T", "2026-11-01T00:00:00+00:00", "test")}
        self.assertIsNone(self.related.pick(SHORT_ID, state, NOW))
        self.assertIsNone(self.related.pick("2026-11-20_1200_ZZ-999", {"long-13_linear": long_rec("L", "2026-11-01T00:00:00+00:00", "public")}, NOW))

    def test_upload_names_the_long_video_and_records_it(self):
        self.state_file.write_text(json.dumps({"long-13_linear": long_rec("LIN", "2026-11-10T22:00:00+00:00", "public")}))
        seen = []

        def fake_post_one(p, platform, tok):
            seen.append(self.runner.yt_fields(p)[1])
            return "YTSHORT"
        with mock.patch.object(self.runner, "post_one", fake_post_one):
            self.assertEqual(self.runner.run(now=NOW), 0)
        self.assertIn("Full lesson: SAT Linear Functions & Word Problems (youtu.be/LIN)", seen[0])
        self.assertTrue(seen[0].endswith("#SAT #SATmath"))
        rec = json.loads(self.state_file.read_text())[SHORT_ID]["youtube"]
        self.assertEqual((rec["id"], rec["related"]), ("YTSHORT", "long-13_linear"))

    def test_upload_without_a_live_long_video_has_no_line(self):
        seen = []

        def fake_post_one(p, platform, tok):
            seen.append(self.runner.yt_fields(p)[1])
            return "YTSHORT"
        with mock.patch.object(self.runner, "post_one", fake_post_one):
            self.runner.run(now=NOW)
        self.assertNotIn("Full lesson", seen[0])
        self.assertNotIn("related", json.loads(self.state_file.read_text())[SHORT_ID]["youtube"])


if __name__ == "__main__":
    unittest.main()
