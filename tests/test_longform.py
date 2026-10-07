"""Offline tests for long-form YouTube uploads (autopost/longform.py). Fakes every API.

python3 -m unittest discover -s tests
"""
import importlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

VIDEO = b"\x01" * 1000
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


def post(pid, publish_at, order=1, **extra):
    p = {"id": pid, "type": "longform", "order": order, "publish_at": publish_at,
         "video": f"{pid}.mp4", "video_bytes": len(VIDEO), "thumbnail": "thumbnail.png",
         "captions": "captions.srt", "title": f"Title {pid}",
         "description": "Lesson.\n\nCHAPTERS\n0:00 Intro\n1:00 Part 1",
         "tags": ["SAT grammar", "digital SAT", "SAT prep"], "category": "27", "language": "en"}
    p.update(extra)
    return p


class Resp:
    def __init__(self, data=None, status=200, headers=None, body=b""):
        self._d, self.status_code, self.headers = data or {}, status, headers or {}
        self.text, self._body = json.dumps(self._d), body

    def json(self):
        return self._d

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_content(self, n):
        for i in range(0, len(self._body), n):
            yield self._body[i:i + n]


class Fake:
    """YouTube: session -> chunk PUTs (308 until done) -> 200. Thumbnails/captions/ntfy/token."""

    def __init__(self):
        self.calls, self.received = [], 0
        self.thumb_fail = False
        self.fail_put_once = False
        self.download = VIDEO
        self.download_status = 200
        self.n = 0

    def post(self, url, data=None, json=None, headers=None, timeout=None, params=None):
        self.calls.append(("POST", url, json if json is not None else data, headers, params))
        if "oauth2.googleapis.com" in url:
            return Resp({"access_token": "YT"})
        if "thumbnails/set" in url:
            return Resp({"error": "forbidden"}, status=403) if self.thumb_fail else Resp({"items": []})
        if "/captions" in url:
            return Resp({"id": "CAP1"})
        if "upload/youtube/v3/videos" in url:
            self.n += 1
            self.received = 0
            return Resp({}, headers={"Location": f"https://upload.youtube/session{self.n}"})
        if "ntfy" in url:
            return Resp({})
        raise AssertionError(f"unexpected POST {url}")

    def put(self, url, data=None, headers=None, timeout=None):
        self.calls.append(("PUT", url, len(data), headers, None))
        total = int(headers["Content-Range"].split("/")[1])
        if headers["Content-Range"].startswith("bytes */"):  # resume query
            return Resp({}, status=308, headers={"Range": f"bytes=0-{self.received - 1}"} if self.received else {})
        if self.fail_put_once:
            self.fail_put_once = False
            return Resp({}, status=503)
        start = int(headers["Content-Range"].split(" ")[1].split("-")[0])
        assert start == self.received, (start, self.received)
        self.received += len(data)
        if self.received >= total:
            meta = [c for c in self.calls if c[0] == "POST" and "upload/youtube/v3/videos" in c[1]][-1][2]
            st = {"privacyStatus": meta["status"]["privacyStatus"]}
            if meta["status"].get("publishAt"):
                st["publishAt"] = meta["status"]["publishAt"]
            return Resp({"id": f"VID{self.n}", "status": st})
        return Resp({}, status=308, headers={"Range": f"bytes=0-{self.received - 1}"})

    def get(self, url, params=None, timeout=None, stream=False):
        self.calls.append(("GET", url, None, None, None))
        return Resp({}, status=self.download_status, body=self.download)

    def head(self, url, allow_redirects=True, timeout=None):
        return Resp({}, status=200)


class LongformTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.tmp)
        Path("posts").mkdir()
        self.env = mock.patch.dict(os.environ, {
            "YT_CLIENT_ID": "id", "YT_CLIENT_SECRET": "sec", "YT_REFRESH_TOKEN": "rt",
            "POSTS_DIR": "posts", "LONGFORM_DIR": "longform", "STATE_FILE": os.path.join(self.tmp, "posted.json"),
            "COOLDOWN_FILE": os.path.join(self.tmp, "cool.json"), "DRY_RUN": "0", "YT_LONGFORM": "1",
            "GITHUB_REPOSITORY": "someone/repo", "MEDIA_BASE_URL": "", "NTFY_TOPIC": "",
        })
        self.env.start()
        self.reload()
        self.fake = Fake()
        for name in ("post", "get", "put", "head"):
            mock.patch(f"requests.{name}", getattr(self.fake, name)).start()
        mock.patch("time.sleep", lambda s: None).start()
        self.add(post("long-01", "2026-10-11T16:00:00-05:00", 1))

    def reload(self):
        import autopost.config, autopost.youtube, autopost.longform, autopost.runner
        for m in (autopost.config, autopost.youtube, autopost.longform, autopost.runner):
            importlib.reload(m)
        self.runner, self.lf, self.yt = autopost.runner, autopost.longform, autopost.youtube
        self.yt.LONG_CHUNK = 256  # 1000-byte "video" -> 4 chunks

    def tearDown(self):
        mock.patch.stopall()
        self.env.stop()
        os.chdir(self.cwd)

    def add(self, p):
        d = Path("longform") / p["id"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "post.json").write_text(json.dumps(p))
        (d / "thumbnail.png").write_bytes(PNG)
        (d / "captions.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\nHi\n")

    def state(self):
        f = Path(os.environ["STATE_FILE"])
        return json.loads(f.read_text()) if f.exists() else {}

    def uploads(self):
        return [c for c in self.fake.calls if c[0] == "POST" and "upload/youtube/v3/videos" in c[1]]

    def at(self, s):
        return datetime.fromisoformat(s).astimezone(timezone.utc)

    # ---------------------------------------------------------------- tests
    def test_off_by_default_uploads_nothing(self):
        os.environ["YT_LONGFORM"] = "0"
        self.reload()
        self.assertEqual(self.runner.run(now=self.at("2026-10-11T12:00:00-05:00")), 0)
        self.assertEqual(self.uploads(), [])

    def test_not_uploaded_before_the_lead_window(self):
        self.assertEqual(self.runner.run(now=self.at("2026-10-10T15:00:00-05:00")), 0)  # 25 h early
        self.assertEqual(self.uploads(), [])

    def test_scheduled_upload_24h_early(self):
        now = self.at("2026-10-10T17:00:00-05:00")  # 23 h before publish_at
        self.assertEqual(self.runner.run(now=now), 0)
        meta = self.uploads()[0][2]
        self.assertEqual(meta["status"]["privacyStatus"], "private")
        self.assertEqual(meta["status"]["publishAt"], "2026-10-11T21:00:00Z")
        self.assertEqual(meta["snippet"]["categoryId"], "27")
        self.assertEqual(meta["snippet"]["defaultAudioLanguage"], "en")
        self.assertFalse(meta["status"]["selfDeclaredMadeForKids"])
        self.assertIn("SAT grammar", meta["snippet"]["tags"])
        self.assertTrue(any("releases/download/longform/long-01.mp4" in c[1] for c in self.fake.calls if c[0] == "GET"))
        puts = [c for c in self.fake.calls if c[0] == "PUT"]
        self.assertEqual([p[3]["Content-Range"] for p in puts],
                         ["bytes 0-255/1000", "bytes 256-511/1000", "bytes 512-767/1000", "bytes 768-999/1000"])
        rec = self.state()["long-01"]["youtube"]
        self.assertEqual(rec["id"], "VID1")
        self.assertEqual(rec["privacy"], "scheduled")
        self.assertTrue(rec["thumbnail"])
        self.assertEqual(rec["captions"], "off")  # YT_CAPTIONS not set
        self.assertTrue(any("thumbnails/set" in c[1] for c in self.fake.calls))
        n = len(self.uploads())
        self.runner.run(now=now + timedelta(hours=1))  # never twice
        self.assertEqual(len(self.uploads()), n)

    def test_overdue_goes_public_now(self):
        self.runner.run(now=self.at("2026-10-12T09:00:00-05:00"))
        meta = self.uploads()[0][2]
        self.assertEqual(meta["status"]["privacyStatus"], "public")
        self.assertNotIn("publishAt", meta["status"])
        self.assertEqual(self.state()["long-01"]["youtube"]["privacy"], "public")

    def test_stale_schedule_drips_with_min_gap(self):
        self.add(post("long-02", "2026-10-13T16:00:00-05:00", 2))
        self.add(post("long-03", "2026-10-15T16:00:00-05:00", 3))
        now = self.at("2026-11-01T12:00:00-05:00")  # audit passed late: all three overdue
        self.runner.run(now=now)
        self.runner.run(now=now + timedelta(minutes=15))  # 02 would be 40 h after 01: not yet (lead 24 h)
        st = self.state()
        self.assertEqual(set(k for k in st if k.startswith("long-")), {"long-01"})
        later = now + timedelta(hours=17)  # now 02 is 23 h out
        self.runner.run(now=later)
        rec = self.state()["long-02"]["youtube"]
        self.assertEqual(rec["privacy"], "scheduled")
        self.assertEqual(self.at(rec["publish_at"]), now + timedelta(hours=40))
        self.assertEqual(self.uploads()[-1][2]["status"]["publishAt"],
                         (now + timedelta(hours=40)).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def test_one_upload_per_run(self):
        self.add(post("long-02", "2026-10-11T18:00:00-05:00", 2))
        os.environ["LONGFORM_MIN_GAP_HOURS"] = "1"
        self.reload()
        self.runner.run(now=self.at("2026-10-11T10:00:00-05:00"))
        self.assertEqual(len(self.uploads()), 1)
        self.runner.run(now=self.at("2026-10-11T10:15:00-05:00"))
        self.assertEqual(len(self.uploads()), 2)

    def test_expired_date_specific_video_is_held(self):
        self.add(post("long-03", "2026-10-25T16:00:00-05:00", 3, expires_at="2026-11-06T23:59:00-06:00"))
        Path("longform/long-01/post.json").unlink()  # only 03
        self.runner.run(now=self.at("2026-11-08T12:00:00-06:00"))
        self.assertEqual(self.uploads(), [])
        self.assertNotIn("long-03", self.state())

    def test_manual_is_skipped(self):
        p = post("long-01", "2026-10-11T16:00:00-05:00", 1, manual=True)
        self.add(p)
        self.runner.run(now=self.at("2026-10-12T09:00:00-05:00"))
        self.assertEqual(self.uploads(), [])

    def test_thumbnail_failure_is_retried_not_reuploaded(self):
        self.fake.thumb_fail = True
        now = self.at("2026-10-12T09:00:00-05:00")
        self.assertEqual(self.runner.run(now=now), 0)
        rec = self.state()["long-01"]["youtube"]
        self.assertFalse(rec["thumbnail"])
        self.assertEqual(rec["extra_tries"], 1)
        self.fake.thumb_fail = False
        self.runner.run(now=now + timedelta(minutes=15))
        rec = self.state()["long-01"]["youtube"]
        self.assertTrue(rec["thumbnail"])
        self.assertEqual(len(self.uploads()), 1)

    def test_upload_resumes_after_server_error(self):
        self.fake.fail_put_once = True
        self.assertEqual(self.runner.run(now=self.at("2026-10-12T09:00:00-05:00")), 0)
        self.assertEqual(self.state()["long-01"]["youtube"]["id"], "VID1")
        self.assertTrue(any(c[3]["Content-Range"] == "bytes */1000" for c in self.fake.calls if c[0] == "PUT"))

    def test_partial_download_fails_and_records_nothing(self):
        self.fake.download = VIDEO[:500]
        self.assertEqual(self.runner.run(now=self.at("2026-10-12T09:00:00-05:00")), 1)
        self.assertEqual(self.uploads(), [])
        self.assertNotIn("long-01", self.state())

    def test_missing_release_asset_fails_cleanly(self):
        self.fake.download_status = 404
        self.assertEqual(self.runner.run(now=self.at("2026-10-12T09:00:00-05:00")), 1)
        self.assertNotIn("long-01", self.state())

    def test_test_mode_uploads_one_private_copy(self):
        os.environ["YT_LONGFORM"] = "test"
        self.reload()
        self.runner.run(now=self.at("2026-10-08T09:00:00-05:00"))
        meta = self.uploads()[0][2]
        self.assertTrue(meta["snippet"]["title"].startswith("[TEST] "))
        self.assertEqual(meta["status"]["privacyStatus"], "private")
        self.assertNotIn("publishAt", meta["status"])
        self.assertEqual(self.uploads()[0][4]["notifySubscribers"], "false")
        st = self.state()
        self.assertEqual(st["_longform_test"]["post"], "long-01")
        self.assertNotIn("long-01", st)  # the real post is untouched
        self.runner.run(now=self.at("2026-10-08T09:15:00-05:00"))
        self.assertEqual(len(self.uploads()), 1)

    def test_captions_when_enabled(self):
        os.environ["YT_CAPTIONS"] = "1"
        self.reload()
        self.runner.run(now=self.at("2026-10-12T09:00:00-05:00"))
        self.assertTrue(self.state()["long-01"]["youtube"]["captions"])
        cap = [c for c in self.fake.calls if c[0] == "POST" and "/captions" in c[1]][0]
        self.assertIn(b'"videoId": "VID1"', cap[2])
        self.assertIn(b"00:00:00,000 --> 00:00:02,000", cap[2])

    def test_dry_run_saves_nothing(self):
        os.environ["DRY_RUN"] = "1"
        self.reload()
        self.runner.run(now=self.at("2026-10-12T09:00:00-05:00"))
        self.assertEqual(self.uploads(), [])
        self.assertEqual(self.state(), {})

    def test_validation(self):
        d = Path("longform/long-01")
        p = dict(post("x", "2026-10-11T16:00:00-05:00"), _dir=d)
        self.assertEqual(self.lf.validate(p), [])
        self.assertTrue(self.lf.validate(dict(p, title="x" * 101)))
        self.assertTrue(self.lf.validate(dict(p, description="if x < 5")))
        self.assertTrue(self.lf.validate(dict(p, publish_at="2026-10-11T16:00:00")))
        self.assertTrue(self.lf.validate(dict(p, thumbnail="nope.png")))
        self.assertEqual(self.runner.check(), 0)

    def test_tags_fit_500_chars(self):
        tags = [f"tag number {i}" for i in range(100)]
        fit = self.lf.tags_fit(tags)
        self.assertLessEqual(sum(len(t) + 2 for t in fit) + len(fit) - 1, 500)
        self.assertEqual(self.lf.tags_fit(["a<b", " ", "c,d"]), ["ab", "c d"])


if __name__ == "__main__":
    unittest.main()
