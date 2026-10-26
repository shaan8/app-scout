from scout import http
from scout.http import MAX_INTERVAL, Fetcher


def test_throttling_slows_the_host_down_up_to_a_cap(tmp_path):
    fetch = Fetcher(tmp_path, min_interval={"app.sensortower.com": 4.0})
    fetch._slow_down("app.sensortower.com")
    assert fetch.min_interval["app.sensortower.com"] == 6.0
    for _ in range(10):
        fetch._slow_down("app.sensortower.com")
    assert fetch.min_interval["app.sensortower.com"] == MAX_INTERVAL


def test_connection_reset_is_retried(tmp_path, monkeypatch):
    fetch = Fetcher(tmp_path, min_interval={})
    calls = []

    def flaky_open(url, headers, limit):
        calls.append(url)
        if len(calls) == 1:
            raise ConnectionResetError(54, "Connection reset by peer")
        return b'{"ok": true}', 200, url

    monkeypatch.setattr(fetch, "_open", flaky_open)
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    assert fetch.get_json("https://itunes.apple.com/lookup?id=1") == {"ok": True}
    assert len(calls) == 2


def test_api_responses_are_not_truncated(tmp_path, monkeypatch):
    fetch = Fetcher(tmp_path, min_interval={})
    seen = {}

    def fake_open(url, headers, limit):
        seen["limit"] = limit
        return b'{"results": []}', 200, url

    monkeypatch.setattr(fetch, "_open", fake_open)
    fetch.get_json("https://itunes.apple.com/lookup?id=1&entity=software")
    assert seen["limit"] is None
