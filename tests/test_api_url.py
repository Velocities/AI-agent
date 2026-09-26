from ai_agent.cli.api_url import public_api_base_url_hint


def test_https_public_host_with_8000_warns() -> None:
    hint = public_api_base_url_hint("https://agent.example.com:8000")
    assert hint is not None
    assert "443" in hint
    assert "no port" in hint.lower() or "with no port" in hint


def test_https_without_port_is_fine() -> None:
    assert public_api_base_url_hint("https://agent.example.com") is None


def test_local_https_with_8000_is_fine() -> None:
    assert public_api_base_url_hint("https://127.0.0.1:8000") is None


def test_http_localhost_8000_is_fine() -> None:
    assert public_api_base_url_hint("http://127.0.0.1:8000") is None
