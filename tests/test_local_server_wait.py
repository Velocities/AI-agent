from unittest.mock import MagicMock

from ai_agent_cli.local_server import _wait_for_ready


def test_wait_for_ready_accepts_bearer(monkeypatch) -> None:
    calls: list[str] = []

    class FakeResponse:
        def __init__(self, status_code: int):
            self.status_code = status_code

    class FakeClient:
        def get(self, url, **kwargs):
            calls.append(url)
            if url.endswith("/health"):
                return FakeResponse(200)
            if url.endswith("/api/me"):
                return FakeResponse(200)
            return FakeResponse(404)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("ai_agent_cli.local_server.httpx.Client", lambda **_k: FakeClient())
    process = MagicMock()
    process.poll.return_value = None
    assert _wait_for_ready("http://127.0.0.1:59999", "secret", process, timeout=1.0)
    assert any(url.endswith("/api/me") for url in calls)