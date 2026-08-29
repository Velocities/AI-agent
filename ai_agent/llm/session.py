from __future__ import annotations

import json
from collections.abc import Iterator
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
    ):
        self.base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(
            connect=connect_timeout,
            read=timeout,
            write=10.0,
            pool=10.0,
        )
        self._client = httpx.Client(timeout=self._timeout)

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{self.base_url}{path}"

    @contextmanager
    def stream_post(self, path: str, payload: dict) -> Iterator[httpx.Response]:
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

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LlmSessionError(
                LLMErrorKind.HTTP,
                f"LLM HTTP error: {exc.response.status_code}",
            ) from exc
