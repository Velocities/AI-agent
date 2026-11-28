"""fetch-pages reads public pages without a model or a container."""

import importlib.util
import json
import threading
from pathlib import Path

import pytest

from ai_agent.workflows.manifests import default_workflow_image_root, load_workflow

def _tool_path() -> Path:
    manifest = load_workflow(default_workflow_image_root(), "product-ideas")
    return manifest.tool("fetch-pages").directory / "fetch_pages.py"


def _tool():
    spec = importlib.util.spec_from_file_location("fetch_pages_tool", _tool_path())
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_product_ideas_manifest_asks_for_five_preferences() -> None:
    manifest = load_workflow(default_workflow_image_root(), "product-ideas")
    assert [tool.name for tool in manifest.tools] == ["fetch-pages"]
    assert manifest.parameters == ()
    prompt = manifest.initial_prompt
    assert "ask these five questions" in prompt
    assert "arctic-shift.photon-reddit.com" in prompt
    assert "hn.algolia.com" in prompt
    assert "lobste.rs" in prompt
    assert "fetch-pages" in prompt


def test_html_drops_scripts_and_keeps_the_complaint() -> None:
    tool = _tool()
    title, text = tool.readable_document(
        "text/html",
        "<html><head><title>Need a tool</title><style>h1{}</style></head>"
        "<body><script>secret()</script><p>Backup takes all Sunday.</p></body></html>",
    )
    assert title == "Need a tool"
    assert "Backup takes all Sunday." in text
    assert "secret" not in text
    assert "h1{}" not in text


def test_reddit_and_hacker_news_json_become_posts() -> None:
    tool = _tool()
    reddit = {
        "data": {
            "children": [
                {
                    "kind": "t3",
                    "data": {
                        "subreddit_name_prefixed": "r/sysadmin",
                        "title": "Is there a tool that rotates local admin passwords?",
                        "score": 42,
                        "num_comments": 17,
                        "permalink": "/r/sysadmin/comments/abc/is_there/",
                        "selftext": "We still do this in a spreadsheet.",
                    },
                }
            ]
        }
    }
    _title, text = tool.readable_document("application/json", json.dumps(reddit))
    assert "spreadsheet" in text
    assert "https://old.reddit.com/r/sysadmin/comments/abc/is_there/" in text

    hacker_news = {
        "hits": [
            {
                "title": "Ask HN: internal tool for laptop inventory",
                "points": 10,
                "num_comments": 4,
                "objectID": "99",
                "url": "https://example.com/inventory",
                "story_text": "<p>We email a form.</p>",
            }
        ]
    }
    _title, text = tool.readable_document("application/json", json.dumps(hacker_news))
    assert "laptop inventory" in text
    assert "We email a form." in text
    assert "https://news.ycombinator.com/item?id=99" in text

    arctic = {
        "data": [
            {
                "subreddit": "SomebodyMakeThis",
                "title": "A desktop tool that renames files from a spreadsheet",
                "selftext": "I still do this by hand every Friday.",
                "score": 12,
                "num_comments": 4,
                "url": "https://www.reddit.com/r/SomebodyMakeThis/comments/abc/rename/",
            }
        ]
    }
    _title, text = tool.readable_document("application/json", json.dumps(arctic))
    assert "every Friday" in text
    assert "https://www.reddit.com/r/SomebodyMakeThis/comments/abc/rename/" in text

    lobsters = [
        {
            "title": "Ask: inventory for a small IT team",
            "score": 8,
            "comment_count": 3,
            "short_id_url": "https://lobste.rs/s/abc123",
            "description_plain": "We keep it in a shared mailbox.",
        }
    ]
    _title, text = tool.readable_document("application/json", json.dumps(lobsters))
    assert "shared mailbox" in text
    assert "https://lobste.rs/s/abc123" in text

    github = {
        "items": [
            {
                "title": "Add a way to export audit logs",
                "html_url": "https://github.com/example/app/issues/4",
                "url": "https://api.github.com/repos/example/app/issues/4",
                "body": "We copy them out of the admin page.",
            }
        ]
    }
    _title, text = tool.readable_document("application/json", json.dumps(github))
    assert "https://github.com/example/app/issues/4" in text
    assert "api.github.com" not in text


def test_login_wall_is_not_treated_as_a_discussion() -> None:
    tool = _tool()
    message = tool._blocked_page(
        "https://old.reddit.com/login/?reason=lor2",
        "Welcome to Reddit",
        "Welcome to Reddit Skip to main content",
    )
    assert "login wall" in message
    assert tool._blocked_page("https://example.com/post", "Need a tool", "Backup takes all Sunday.") == ""


def test_private_and_non_http_urls_are_refused() -> None:
    tool = _tool()
    for url in (
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.1.2.3/",
        "http://localhost/admin",
        "file:///etc/passwd",
        "https://user:pass@example.com/",
    ):
        with pytest.raises(ValueError):
            tool.public_url(url)


def test_urls_are_fetched_together_and_duplicates_once() -> None:
    tool = _tool()
    started: list[str] = []
    lock = threading.Lock()
    both = threading.Event()
    first = "https://news.ycombinator.com/a"
    second = "https://old.reddit.com/b"

    def fake(url, _max_chars):
        with lock:
            started.append(url)
            if len(started) >= 2:
                both.set()
        assert both.wait(2)
        return tool._page(url, status=200, title=url, text="ok")

    result = tool.fetch_pages([first, second, first], concurrency=2, fetch=fake)
    assert sorted(started) == sorted([first, second])
    assert [page["url"] for page in result["pages"]] == [first, second, first]
    assert result["fetched"] == 3
    assert result["failed"] == 0


def test_more_than_sixteen_urls_is_rejected_before_fetching() -> None:
    tool = _tool()
    called = False

    def fake(url, _max_chars):
        nonlocal called
        called = True
        return tool._page(url, status=200, text="no")

    with pytest.raises(ValueError, match="16"):
        tool.fetch_pages(
            [f"https://example.com/{index}" for index in range(17)],
            fetch=fake,
        )
    assert called is False
