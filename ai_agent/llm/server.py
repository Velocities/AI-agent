from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from ai_agent.llm.session import LlmHttpSession, LlmSessionError

logger = logging.getLogger(__name__)


def public_url(host: str, port: int) -> str:
    """URL a local client should use to reach this bind address."""
    display = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
    if ":" in display and not display.startswith("["):
        display = f"[{display}]"
    return f"http://{display}:{port}"


class LlmFacade:
    """Ollama-compatible HTTP surface over an upstream session."""

    def __init__(self, session: LlmHttpSession):
        self.session = session

    def tags(self) -> object:
        return self.session.get_json("/api/tags", timeout=5.0)

    def chat_lines(self, payload: dict[str, Any]) -> Iterator[str]:
        with self.session.stream_post("/api/chat", payload) as response:
            for line in response.iter_lines():
                if line:
                    yield line


def bind_llm_server(host: str, port: int, facade: LlmFacade) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), _make_handler(facade))


def _make_handler(facade: LlmFacade) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, format: str, *args: object) -> None:
            logger.info("%s - %s", self.address_string(), format % args)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in {"/", "/health"}:
                self._send_json(
                    200,
                    {"status": "ok", "upstream": facade.session.base_url},
                )
                return
            if path == "/api/tags":
                try:
                    self._send_json(200, facade.tags())
                except LlmSessionError as exc:
                    self._send_json(502, {"error": exc.message})
                return
            self.send_error(404, "Not Found")

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path != "/api/chat":
                self.send_error(404, "Not Found")
                return
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._send_json(400, {"error": "Request body must be JSON."})
                return
            if not isinstance(payload, dict):
                self._send_json(400, {"error": "Request body must be a JSON object."})
                return
            try:
                stream = facade.chat_lines(payload)
                first = next(stream)
            except StopIteration:
                self._send_json(502, {"error": "LLM stream ended with no data."})
                return
            except LlmSessionError as exc:
                self._send_json(502, {"error": exc.message})
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                self._write_ndjson_line(first)
                for line in stream:
                    self._write_ndjson_line(line)
            except LlmSessionError as exc:
                logger.warning("Upstream chat failed after stream started: %s", exc)

        def _write_ndjson_line(self, line: str | bytes) -> None:
            data = line if isinstance(line, str) else line.decode("utf-8")
            self.wfile.write(data.encode("utf-8"))
            self.wfile.write(b"\n")
            self.wfile.flush()

        def _send_json(self, status: int, payload: object) -> None:
            body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

    return Handler
