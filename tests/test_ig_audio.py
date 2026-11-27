import json
from unittest import mock

from autopost import config, instagram


class Resp:
    def __init__(self, data, code=200):
        self._d, self.status_code, self.content = data, code, b"x"
        self.text = json.dumps(data)

    def json(self):
        return self._d


TRACKS = {"audio": [{"audio_id": "111", "duration_in_ms": 60000, "title": "A", "display_artist": "X"},
                    {"audio_id": "222", "duration_in_ms": 5000, "title": "short"}]}


def test_audio_path_sends_configuration(monkeypatch):
    monkeypatch.setattr(config, "IG_FB_TOKEN", "tok")
    monkeypatch.setattr(config, "IG_AUDIO", True)
    monkeypatch.setattr(config, "DRY_RUN", False)
    sent = {}

    def get(url, params=None, timeout=None):
        if url.endswith("/ig_audio"):
            return Resp(TRACKS)
        return Resp({"status_code": "FINISHED"})

    def post(url, data=None, timeout=None):
        if url.endswith("/media"):
            sent.update(data)
            return Resp({"id": "c1"})
        return Resp({"id": "m1"})

    with mock.patch.object(instagram.requests, "get", get), mock.patch.object(instagram.requests, "post", post):
        info = {}
        assert instagram.publish_reel("https://v/x.mp4", "cap", seed="S1", info=info) == "m1"
    cfg = json.loads(sent["audio_configuration"])
    assert cfg["audio_id"] == "111"  # the 5 s track is skipped
    assert info["audio"]["title"] == "A"
    assert sent["media_type"] == "REELS"


def test_falls_back_without_audio(monkeypatch):
    monkeypatch.setattr(config, "IG_FB_TOKEN", "tok")
    monkeypatch.setattr(config, "IG_AUDIO", True)
    monkeypatch.setattr(config, "DRY_RUN", False)
    calls = []

    def get(url, params=None, timeout=None):
        if url.endswith("/ig_audio"):
            return Resp({"error": {"message": "nope"}}, 400)
        return Resp({"status_code": "FINISHED"})

    def post(url, data=None, timeout=None):
        calls.append(url)
        return Resp({"id": "c2" if url.endswith("/media") else "m2"})

    with mock.patch.object(instagram.requests, "get", get), mock.patch.object(instagram.requests, "post", post):
        info = {}
        assert instagram.publish_reel("https://v/x.mp4", "cap", seed="S1", info=info) == "m2"
    assert all("graph.instagram.com" in u for u in calls)
    assert "audio_error" in info
