"""Fetch several public pages at once and return readable text.

The tool does not crawl links, log in, or send anything except a GET.
Private, loopback, and link-local hosts are refused before a connection
is opened.
"""

from __future__ import annotations

import gzip
import ipaddress
import json
import re
import socket
import sys
import threading
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import urlparse

MAX_URLS = 16
MAX_BODY_BYTES = 1_000_000
DEFAULT_CONCURRENCY = 8
MAX_CONCURRENCY = 8
HOST_CONCURRENCY = 4
DEFAULT_CHARS = 3000
DEFAULT_EXCERPT_CHARS = 1200
MAX_CHARS = 6000
MIN_CHARS = 500
TIMEOUT_SECONDS = 12
USER_AGENT = "ai-agent-fetch-pages/0.1 (public page text; no login)"

_SKIP_TAGS = {"script", "style", "noscript", "svg", "iframe", "template", "canvas"}
_BLOCK_TAGS = {
    "p", "div", "li", "tr", "br", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "header", "footer", "blockquote", "pre", "table",
}
_TEXT_KEYS = {
    "title", "name", "body", "selftext", "text", "description", "content",
    "excerpt", "comment_text", "story_text", "body_markdown",
}
_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata.internal",
}


class _PageText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self._parts: list[str] = []
        self.title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if self._skip_depth or tag in _SKIP_TAGS:
            if tag in _SKIP_TAGS:
                self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._skip_depth:
            if tag in _SKIP_TAGS:
                self._skip_depth -= 1
            return
        if tag == "title":
            self._in_title = False
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        text = " ".join(data.split())
        if text:
            self._parts.append(text)
            self._parts.append(" ")

    def text(self) -> str:
        return _collapse("".join(self._parts))

    def title(self) -> str:
        return " ".join("".join(self.title_parts).split())


def fetch_pages(urls, *, concurrency=DEFAULT_CONCURRENCY, max_chars=DEFAULT_CHARS, fetch=None):
    """Fetch each URL and return pages in the same order."""
    ordered = _url_list(urls)
    workers = _bounded_int(concurrency, "concurrency", 1, MAX_CONCURRENCY)
    limit = _bounded_int(max_chars, "max_chars", MIN_CHARS, MAX_CHARS)
    retrieve = fetch or _fetch_url
    unique = list(dict.fromkeys(ordered))
    host_limits: dict[str, threading.Semaphore] = defaultdict(
        lambda: threading.Semaphore(HOST_CONCURRENCY)
    )

    def run(url: str) -> dict:
        host = urlparse(url).hostname or ""
        with host_limits[host]:
            try:
                return retrieve(url, limit)
            except Exception as exc:
                return _page(url, error=_short(exc))

    found: dict[str, dict] = {}
    if unique:
        with ThreadPoolExecutor(max_workers=min(workers, len(unique))) as pool:
            for url, page in zip(unique, pool.map(run, unique)):
                found[url] = page
    pages = [found[url] for url in ordered]
    fetched = sum(1 for page in pages if not page["error"])
    return {"pages": pages, "fetched": fetched, "failed": len(pages) - fetched}


def readable_document(content_type: str, body: str) -> tuple[str, str]:
    """Turn an HTTP body into a title and plain text."""
    kind = content_type.lower()
    stripped = body.lstrip()
    if "html" in kind or stripped.startswith("<"):
        parser = _PageText()
        try:
            parser.feed(stripped)
            parser.close()
        except Exception:
            text = _collapse(_strip_tags(stripped))
            return _first_line(text), text
        text = parser.text()
        title = parser.title() or _first_line(text)
        return title, text
    if "json" in kind or stripped.startswith("{") or stripped.startswith("["):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            text = _collapse(stripped)
            return _first_line(text), text
        text = _text_from_json(data)
        return _first_line(text), text
    text = _collapse(body)
    return _first_line(text), text


def public_url(url: str) -> str:
    """Accept one http(s) URL whose addresses are all on the public internet."""
    if not isinstance(url, str):
        raise ValueError("each url must be a string")
    candidate = url.strip()
    if not candidate or len(candidate) > 2000 or any(ord(char) < 32 for char in candidate):
        raise ValueError("url must be a single line of at most 2000 characters")
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("only http and https URLs are allowed")
    if parsed.username or parsed.password:
        raise ValueError("URLs must not include a username or password")
    host = parsed.hostname
    if not host:
        raise ValueError("URL is missing a host")
    lowered = host.lower().rstrip(".")
    if lowered in _BLOCKED_HOSTS or lowered.endswith((".local", ".localhost", ".internal")):
        raise ValueError("that host is not a public website")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(lowered, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"could not resolve {lowered}") from exc
    addresses = [item[4][0] for item in infos]
    if not addresses:
        raise ValueError(f"could not resolve {lowered}")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("only public internet hosts are allowed")
    return candidate


def _fetch_url(url: str, max_chars: int) -> dict:
    target = public_url(url)
    opener = urllib.request.build_opener(
        _SafeRedirect(),
        urllib.request.ProxyHandler({}),
    )
    request = urllib.request.Request(
        target,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html, application/json, text/plain;q=0.8",
            "Accept-Language": "en",
        },
        method="GET",
    )
    try:
        response = opener.open(request, timeout=TIMEOUT_SECONDS)
    except urllib.error.HTTPError as exc:
        response = exc
    except urllib.error.URLError as exc:
        return _page(target, error=f"request failed: {_short(exc.reason)}")
    with response:
        raw, truncated = _read_limited(response, MAX_BODY_BYTES)
        content_type = response.headers.get("Content-Type", "")
        status = getattr(response, "status", None) or getattr(response, "code", 0) or 0
        final_url = response.geturl()
        encoding = response.headers.get("Content-Encoding", "")
    try:
        body = gzip.decompress(raw) if "gzip" in encoding.lower() else raw
    except (OSError, EOFError) as exc:
        return _page(target, final_url=final_url, status=int(status), error=f"could not read response: {_short(exc)}")
    title, text = readable_document(content_type, _decode(body, content_type))
    if truncated:
        text = _clip(text, max_chars)
        if not text.endswith("[truncated]"):
            text = text + "\n[truncated]"
    else:
        text = _clip(text, max_chars)
    error = "" if 200 <= int(status) < 300 else f"HTTP {status}"
    blocked = _blocked_page(final_url, title, text)
    if blocked:
        error = blocked
    return _page(target, final_url=final_url, status=int(status), title=title, text=text, error=error)


def _blocked_page(final_url: str, title: str, text: str) -> str:
    url = final_url.lower()
    if "/login" in url or "reason=lor" in url:
        return "site returned a login wall, not the discussion"
    sample = (title + " " + text[:300]).lower()
    if "welcome to reddit" in sample and len(text) < 500:
        return "site returned a block page, not the discussion"
    if "just a moment" in title.lower() and len(text) < 500:
        return "site returned a block page, not the discussion"
    return ""


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _text_from_json(data) -> str:
    for formatter in (
        _format_reddit,
        _format_hacker_news,
        _format_lobsters,
        _format_subreddit_posts,
        _format_titled_items,
    ):
        text = formatter(data)
        if text:
            return text
    return _harvest(data)


def _format_reddit(data) -> str:
    listings = data if isinstance(data, list) else [data]
    lines: list[str] = []
    for listing in listings:
        payload = listing.get("data") if isinstance(listing, dict) else None
        children = payload.get("children") if isinstance(payload, dict) else None
        if not isinstance(children, list):
            continue
        for child in children:
            if not isinstance(child, dict):
                continue
            fields = child.get("data") or {}
            if not isinstance(fields, dict):
                continue
            kind = child.get("kind")
            if kind == "t3":
                lines.extend(_reddit_post(fields))
            elif kind == "t1":
                body = str(fields.get("body") or "").strip()
                if body:
                    lines.append(f"comment ({fields.get('score', 0)}): {body}")
                    lines.append("")
    return "\n".join(lines).strip()


def _reddit_post(fields: dict) -> list[str]:
    subreddit = fields.get("subreddit_name_prefixed") or fields.get("subreddit") or "reddit"
    title = str(fields.get("title") or "").strip()
    score = fields.get("score", 0)
    comments = fields.get("num_comments", 0)
    lines = [f"[{subreddit}] {title} ({score} points, {comments} comments)"]
    permalink = str(fields.get("permalink") or "")
    if permalink.startswith("/"):
        lines.append("https://old.reddit.com" + permalink)
    body = str(fields.get("selftext") or "").strip()
    if body:
        lines.append(body)
    else:
        link = str(fields.get("url_overridden_by_dest") or fields.get("url") or "")
        if link:
            lines.append(link)
    lines.append("")
    return lines


def _format_lobsters(data) -> str:
    rows = data if isinstance(data, list) else []
    if not rows or not any(isinstance(row, dict) and "short_id_url" in row for row in rows):
        return ""
    lines: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        lines.append(
            f"[lobste.rs] {title} ({row.get('score', 0)} points, {row.get('comment_count', 0)} comments)"
        )
        discussion = str(row.get("short_id_url") or "")
        if discussion:
            lines.append(discussion)
        body = str(row.get("description_plain") or "").strip()
        if not body and row.get("description"):
            body = _html_fragment(str(row.get("description")))
        if body:
            lines.append(body)
        lines.append("")
    return "\n".join(lines).strip()


def _format_subreddit_posts(data) -> str:
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        return ""
    if not any(isinstance(row, dict) and ("selftext" in row or "subreddit" in row) for row in rows):
        return ""
    lines: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        body = str(row.get("selftext") or row.get("body") or "").strip()
        if not title and not body:
            continue
        subreddit = row.get("subreddit") or "reddit"
        comments = row.get("num_comments", row.get("comment_count", 0))
        if title:
            lines.append(
                f"[r/{subreddit}] {title} ({row.get('score', 0)} points, {comments} comments)"
            )
        link = str(row.get("url") or "")
        if link:
            lines.append(link)
        if body and body not in {"[removed]", "[deleted]"}:
            lines.append(body)
        lines.append("")
    return "\n".join(lines).strip()


def _format_hacker_news(data) -> str:
    hits = data.get("hits") if isinstance(data, dict) else None
    if not isinstance(hits, list) or not hits:
        return ""
    lines: list[str] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        title = str(hit.get("title") or hit.get("story_title") or "").strip()
        text = str(hit.get("story_text") or hit.get("comment_text") or "").strip()
        if not title and not text:
            continue
        meta = []
        if hit.get("points") is not None:
            meta.append(f"{hit.get('points')} points")
        if hit.get("num_comments") is not None:
            meta.append(f"{hit.get('num_comments')} comments")
        head = title or _first_line(_html_fragment(text))
        if meta:
            head = head + " (" + ", ".join(meta) + ")"
        lines.append(head)
        object_id = hit.get("objectID")
        if object_id:
            lines.append(f"https://news.ycombinator.com/item?id={object_id}")
        link = str(hit.get("url") or "")
        if link:
            lines.append(link)
        if text:
            lines.append(_html_fragment(text))
        lines.append("")
    return "\n".join(lines).strip()


def _format_titled_items(data) -> str:
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        return ""
    lines: list[str] = []
    for item in items:
        if not isinstance(item, dict) or "title" not in item:
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        lines.append(title)
        link = str(item.get("html_url") or item.get("link") or "")
        if not link:
            raw_url = str(item.get("url") or "")
            if raw_url.startswith("https://") and "api.github.com" not in raw_url:
                link = raw_url
        if link:
            lines.append(link)
        body = item.get("body_markdown") or item.get("body") or item.get("excerpt") or ""
        if isinstance(body, str) and body.strip():
            lines.append(_html_fragment(body))
        lines.append("")
    return "\n".join(lines).strip()


def _harvest(data) -> str:
    found: list[str] = []
    _walk(data, found, 0)
    unique = list(dict.fromkeys(found))
    return "\n\n".join(unique)


def _walk(value, found: list[str], depth: int) -> None:
    if depth > 6 or len(found) >= 40:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _TEXT_KEYS and isinstance(item, str) and item.strip():
                found.append(_html_fragment(item) if "<" in item else item.strip())
            else:
                _walk(item, found, depth + 1)
    elif isinstance(value, list):
        for item in value[:50]:
            _walk(item, found, depth + 1)


def _html_fragment(value: str) -> str:
    parser = _PageText()
    try:
        parser.feed(value)
        parser.close()
    except Exception:
        return _collapse(_strip_tags(value))
    return parser.text() or _collapse(value)


def _url_list(urls) -> list[str]:
    if not isinstance(urls, list) or not urls:
        raise ValueError("urls must be a non-empty list")
    if len(urls) > MAX_URLS:
        raise ValueError(f"pass at most {MAX_URLS} urls per call")
    cleaned = []
    for url in urls:
        if not isinstance(url, str) or not url.strip():
            raise ValueError("each url must be a non-empty string")
        cleaned.append(url.strip())
    return cleaned


def _bounded_int(value, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < low or value > high:
        raise ValueError(f"{name} must be from {low} to {high}")
    return value


def _page(url, *, final_url="", status=0, title="", text="", error="") -> dict:
    excerpt = _clip(text, DEFAULT_EXCERPT_CHARS)
    if text and len(text) > len(excerpt):
        excerpt = excerpt.rstrip() + "…"
    return {
        "url": url,
        "final_url": final_url or url,
        "status": status,
        "title": _clip(title, 200).replace("\n", " "),
        "excerpt": excerpt,
        "text": text,
        "error": error,
    }


def _read_limited(response, limit: int) -> tuple[bytes, bool]:
    chunks = []
    total = 0
    while total < limit:
        block = response.read(min(65536, limit - total))
        if not block:
            return b"".join(chunks), False
        chunks.append(block)
        total += len(block)
    return b"".join(chunks), bool(response.read(1))


def _decode(body: bytes, content_type: str) -> str:
    charset = "utf-8"
    lowered = content_type.lower()
    if "charset=" in lowered:
        charset = lowered.split("charset=", 1)[1].split(";", 1)[0].strip(" \"'")
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _collapse(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.splitlines()]
    kept: list[str] = []
    blank = False
    for line in lines:
        if not line:
            if kept and not blank:
                kept.append("")
            blank = True
            continue
        kept.append(line)
        blank = False
    return "\n".join(kept).strip()


def _strip_tags(text: str) -> str:
    return _collapse(re.sub(r"<[^>]*>", " ", text))


def _clip(text: str, limit: int) -> str:
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    cut = cleaned[:limit].rsplit(" ", 1)[0]
    return (cut or cleaned[:limit]).rstrip() + "\n[truncated]"


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:200]
    return ""


def _short(exc) -> str:
    message = " ".join(str(exc).split())
    return message[:300] or "request failed"


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"stdin must be JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit("stdin must be a JSON object")
    try:
        result = fetch_pages(
            data.get("urls"),
            concurrency=data.get("concurrency", DEFAULT_CONCURRENCY),
            max_chars=data.get("max_chars", DEFAULT_CHARS),
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
