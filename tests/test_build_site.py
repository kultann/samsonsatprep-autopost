"""The Pages site only carries posts within a few days of their publish time."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_site  # noqa: E402


class BuildSiteTest(unittest.TestCase):
    def test_only_posts_in_window(self):
        tmp = tempfile.mkdtemp()
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            Path("index.html").write_text("hi")
            Path("tiktokABC.txt").write_text("verify")
            Path("requirements.txt").write_text("requests")
            for pid, when in [("old", "2026-10-01T07:00:00-05:00"), ("soon", "2026-10-11T07:00:00-05:00"),
                              ("later", "2026-12-01T07:00:00-06:00")]:
                d = Path("posts") / pid
                d.mkdir(parents=True)
                (d / "post.json").write_text(json.dumps({"publish_at": when}))
                (d / "slide1.jpg").write_bytes(b"x")
            n = build_site.build("_site", now=datetime(2026, 10, 10, 12, tzinfo=timezone.utc))
            self.assertEqual(n, 1)
            self.assertTrue(Path("_site/posts/soon/slide1.jpg").exists())
            self.assertFalse(Path("_site/posts/later").exists())
            self.assertTrue(Path("_site/index.html").exists())
            self.assertTrue(Path("_site/tiktokABC.txt").exists())
            self.assertFalse(Path("_site/requirements.txt").exists())
        finally:
            os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
