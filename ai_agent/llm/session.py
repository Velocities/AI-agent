from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import httpx

from ai_agent.llm.base import LLMErrorKind


class LlmSessionError(Exception):
    """Transport failure mapped to a vendor-neutral error kind."""

    def __init__(self, kind: LLMErrorKind, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


class LlmHttpSession:
    """HTTP session used by LLM providers. Callers do not manage sockets."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 600.0,
        connect_timeout: float = 10.0,
        *,
        before_request: Callable[[], None] | None = None,
        on_close: Callable[[], None] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(
            connect=connect_timeout,
            read=timeout,
            write=10.0,
            pool=10.0,
        )
        self._client = httpx.Client(timeout=self._timeout)
        self._before_request = before_request
        self._on_close = on_close

    def _prepare(self) -> None:
        if self._before_request is not None:
            self._before_request()

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{self.base_url}{path}"

    @contextmanager
    def stream_post(self, path: str, payload: dict) -> Iterator[httpx.Response]:
        self._prepare()
        try:
            with self._client.stream("POST", self._url(path), json=payload) as response:
                self._raise_for_status(response)
                yield response
        except LlmSessionError:
            raise
        except httpx.ConnectError as exc:
            raise LlmSessionError(
                LLMErrorKind.UNAVAILABLE,
                f"LLM endpoint is unavailable: {self.base_url}",
            ) from exc
        except httpx.TimeoutException as exc:
            raise LlmSessionError(
                LLMErrorKind.TIMEOUT,
                "LLM request timed out.",
            ) from exc
        except (httpx.ReadError, httpx.RemoteProtocolError, httpx.StreamError) as exc:
            raise LlmSessionError(
                LLMErrorKind.STREAM_INTERRUPTED,
                "LLM stream was interrupted.",
            ) from exc

    def get_json(self, path: str, *, timeout: float | None = None) -> object:
        self._prepare()
        request_timeout = timeout if timeout is not None else self._timeout
        try:
            response = self._client.get(self._url(path), timeout=request_timeout)
            self._raise_for_status(response)
            return response.json()
        except LlmSessionError:
            raise
        except json.JSONDecodeError as exc:
            raise LlmSessionError(
                LLMErrorKind.PROTOCOL,
                "LLM returned malformed JSON.",
            ) from exc
        except httpx.ConnectError as exc:
            raise LlmSessionError(
                LLMErrorKind.UNAVAILABLE,
                f"LLM endpoint is unavailable: {self.base_url}",
            ) from exc
        except httpx.TimeoutException as exc:
            raise LlmSessionError(
                LLMErrorKind.TIMEOUT,
                "LLM request timed out.",
            ) from exc
        except httpx.HTTPError as exc:
            raise LlmSessionError(
                LLMErrorKind.UNAVAILABLE,
                f"LLM healthcheck failed: {exc}",
            ) from exc

    def close(self) -> None:
        self._client.close()
        if self._on_close is not None:
            self._on_close()
            self._on_close = None

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LlmSessionError(
                LLMErrorKind.HTTP,
                f"LLM HTTP error: {exc.response.status_code}",
            ) from exc
