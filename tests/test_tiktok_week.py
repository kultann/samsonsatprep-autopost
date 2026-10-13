"""Offline tests for tools/tiktok_week.py (the weekly manual TikTok batch). Builds a tiny fake SAT folder.

python3 -m unittest discover -s tests
"""
import importlib.util
import json
import os
import tempfile
import time
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "tiktok_week", Path(__file__).resolve().parent.parent / "tools" / "tiktok_week.py")
tw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tw)

MON = "2026-10-19"
SLOTS = [  # Monday: 5 short + 2 long, like the real schedule
    ("0730", "short", "trap", "R1-001"), ("0930", "short", "tip", "T1-002"), ("1230", "short", "solve", "M1-003"),
    ("1500", "short", "quickfire", "Q1-004"), ("1700", "long", "desmos", "D1-005"), ("1930", "short", "trap", "R1-006"),
    ("2130", "long", "solve", "M1-007"),
]
BEFORE = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)  # the Saturday before the week


def item(day, hhmm, length, fmt, sid, caption=None):
    pid = f"{day}_{hhmm}_{sid}"
    return {"id": sid, "post_id": pid, "publish_at": f"{day}T{hhmm[:2]}:{hhmm[2:]}:00-05:00", "date": day,
            "length": length, "format": fmt, "hashtag_set": "math", "platforms": ["instagram", "tiktok"],
            "tiktok_caption": f"Caption for {sid}" if caption is None else caption}


class TikTokWeekTest(unittest.TestCase):
    def setUp(self):
        self.sat = Path(tempfile.mkdtemp())
        bank = [item(MON, *s) for s in SLOTS]
        bank.append(item("2026-10-20", "0730", "short", "trap", "R2-008"))           # no render
        bank.append(item("2026-10-20", "0930", "short", "tip", "T2-009", caption=""))  # no caption
        bank.append(item("2026-10-26", "0730", "short", "trap", "R3-010"))           # next week
        (self.sat / "shorts").mkdir()
        (self.sat / "shorts" / "shorts_bank.json").write_text(json.dumps(bank))
        for it in bank:
            if it["id"] == "R2-008":
                continue
            fin = self.sat / "shorts" / it["post_id"] / "final"
            fin.mkdir(parents=True)
            (fin / f"{it['post_id']}_final.mp4").write_bytes(b"v1-" + it["id"].encode())
            (fin / f"{it['post_id']}_clean.mp4").write_bytes(b"clean-v1")
        (self.sat / "samsonsatprep-media" / "shorts").mkdir(parents=True)
        posts = self.sat / "samsonsatprep-autopost" / "posts" / f"{MON}_0800_q01"
        posts.mkdir(parents=True)
        slides = [f"tslide{i}.jpg" for i in range(1, 11)]
        for s in slides:
            (posts / s).write_bytes(s.encode())
        (posts / "post.json").write_text(json.dumps({
            "id": f"{MON}_0800_q01", "publish_at": f"{MON}T08:00:00-05:00", "type": "carousel",
            "slides": slides, "slides_tiktok": slides, "platforms": ["instagram", "tiktok"],
            "caption": "Feed caption #SAT", "tiktok_caption": "TikTok carousel caption", "tiktok_title": "Q1",
            "hashtags_tiktok": ["#satprep"]}))
        self.paths = tw.Paths(self.sat)
        self.week = self.sat / "tiktok-weekly" / MON

    def build(self, **kw):
        kw.setdefault("now", BEFORE)
        return tw.build(self.paths, date(2026, 10, 19), **kw)

    def mp4s(self):
        return sorted(p.name for p in self.week.glob("*.mp4"))

    def test_default_week(self):
        s = self.build()
        self.assertEqual((s["posts"], s["shorts"], s["carousels"]), (7, 7, 0))  # carousels are off by default
        self.assertEqual(self.mp4s()[0], "01_Mon_0730_R1-001.mp4")
        self.assertEqual(self.mp4s()[-1], "07_Mon_2130_M1-007.mp4")
        self.assertEqual((self.week / "05_Mon_1700_D1-005.mp4").read_bytes(), b"v1-D1-005")  # copied, not moved
        self.assertTrue((self.sat / "shorts" / f"{MON}_1700_D1-005" / "final" / f"{MON}_1700_D1-005_final.mp4").exists())
        reasons = {k["label"]: k["reason"] for k in s["skipped"]}
        self.assertIn("missing render", reasons["R2-008"])
        self.assertIn("missing caption", reasons["T2-009"])
        self.assertNotIn("R3-010", reasons)  # next week isn't this week's business
        self.assertEqual(s["first"].strftime("%a %H:%M"), "Mon 07:30")
        self.assertEqual(s["last"].strftime("%a %H:%M"), "Mon 21:30")
        page = (self.week / "checklist.html").read_text()
        self.assertEqual(page.count("class='card'"), 7)
        self.assertIn("Caption for R1-001\n\n#studytok #satprep #sattips #digitalsat #satmath", page)
        self.assertIn("Copy caption", page)
        self.assertIn("AI-generated content", page)
        self.assertIn("localStorage", page)
        self.assertIn("Mon Oct 19 · 7:30 AM", page)
        rec = json.loads((self.sat / "samsonsatprep-media" / "tiktok_weekly.json").read_text())
        self.assertEqual(len(rec), 7)  # missing render/caption aren't recorded, so the media repo keeps them
        self.assertEqual(rec[f"{MON}_0730_R1-001"]["file"], "01_Mon_0730_R1-001.mp4")

    def test_daily_cap_keeps_long_shorts_then_best(self):
        s = self.build(per_day=4)
        self.assertEqual([n.split("_", 3)[3] for n in self.mp4s()],
                         ["R1-001.mp4", "Q1-004.mp4", "D1-005.mp4", "M1-007.mp4"])
        capped = sorted(k["label"] for k in s["skipped"] if "daily cap" in k["reason"])
        self.assertEqual(capped, ["M1-003", "R1-006", "T1-002"])
        rec = json.loads((self.sat / "samsonsatprep-media" / "tiktok_weekly.json").read_text())
        self.assertIn("skipped", rec[f"{MON}_1930_R1-006"])  # on purpose: the media repo may prune it

    def test_carousels_when_on(self):
        s = self.build(carousels=True)
        self.assertEqual(s["carousels"], 1)
        folder = self.week / "02_Mon_0800_q01"
        self.assertEqual(sorted(p.name for p in folder.iterdir())[:3], ["01_tslide1.jpg", "02_tslide2.jpg", "03_tslide3.jpg"])
        self.assertEqual(sorted(p.name for p in folder.iterdir())[-1], "10_tslide10.jpg")
        page = (self.week / "checklist.html").read_text()
        self.assertIn("TikTok carousel caption\n\n#satprep", page)
        self.assertIn("Copy title", page)

    def test_uses_the_version_instagram_got(self):
        pid = f"{MON}_0730_R1-001"
        fin = self.sat / "shorts" / pid / "final"
        media = self.sat / "samsonsatprep-media" / "shorts" / pid
        media.mkdir(parents=True)
        os.link(fin / f"{pid}_final.mp4", media / "video.mp4")  # publish.py hard-links the version it staged
        time.sleep(0.01)
        (fin / f"{pid}_final_v2.mp4").write_bytes(b"v2 newer, never staged")
        self.build()
        self.assertEqual((self.week / "01_Mon_0730_R1-001.mp4").read_bytes(), b"v1-R1-001")
        (media / "video.mp4").unlink()  # pruned from the media repo: newest render wins
        self.build()
        self.assertEqual((self.week / "01_Mon_0730_R1-001.mp4").read_bytes(), b"v2 newer, never staged")
        self.build(mix="clean")
        self.assertEqual((self.week / "01_Mon_0730_R1-001.mp4").read_bytes(), b"clean-v1")

    def test_past_slots_are_skipped(self):
        s = self.build(now=datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc))  # Mon 10:00 CT
        self.assertEqual(s["shorts"], 5)
        past = sorted(k["label"] for k in s["skipped"] if "already passed" in k["reason"])
        self.assertEqual(past, ["R1-001", "T1-002"])

    def test_rerun_rebuilds_only_its_own_files(self):
        self.build()
        (self.week / "my notes.txt").write_text("keep me")
        self.build(per_day=2)
        self.assertEqual(len(self.mp4s()), 2)
        self.assertTrue((self.week / "my notes.txt").exists())

    def test_cli(self):
        self.assertEqual(tw.main(["--start", "2026-10-26", "--sat", str(self.sat), "--no-record"]), 0)
        self.assertTrue((self.sat / "tiktok-weekly" / "2026-10-26" / "checklist.html").exists())
        self.assertFalse((self.sat / "samsonsatprep-media" / "tiktok_weekly.json").exists())


if __name__ == "__main__":
    unittest.main()
