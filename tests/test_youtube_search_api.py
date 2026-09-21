import asyncio

from backend.api import youtube


class _Response:
    is_error = False
    status_code = 200

    def json(self):
        return {"items": [{"id": {"videoId": "abc123"}}]}


class _Client:
    def __init__(self, **_kwargs):
        self.params = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, _url, params):
        self.params = params
        assert params["key"] == "server-key"
        return _Response()


def test_youtube_search_uses_server_side_key(monkeypatch):
    settings = type("Settings", (), {"REACT_APP_YOUTUBE_API_KEY": "server-key"})()
    monkeypatch.setattr(youtube, "get_settings", lambda: settings)
    monkeypatch.setattr(youtube.httpx, "AsyncClient", _Client)

    result = asyncio.run(youtube.search_videos("podcast", "any", 20))

    assert result == {"items": [{"id": {"videoId": "abc123"}}]}
