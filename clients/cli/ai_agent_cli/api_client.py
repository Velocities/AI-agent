from __future__ import annotations

import json
from collections.abc import Iterator, Sequence

import httpx

from ai_agent.llm.client.types import ImageInput

_IMAGE_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}


class AgentApiError(RuntimeError):
    def __init__(self, status: int, detail: str, *, code: str | None = None):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.code = code


class AgentApiClient:
    def __init__(self, base_url: str, access_token: str):
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self._http = httpx.Client(timeout=httpx.Timeout(30.0, read=None))

    def close(self) -> None:
        self._http.close()

    def list_conversations(self) -> list[dict]:
        payload = self._request("GET", "/api/conversations")
        rows = payload.get("conversations", [])
        return rows if isinstance(rows, list) else []

    def create_conversation(self, title: str = "") -> dict:
        return self._request("POST", "/api/conversations", json={"title": title})

    def list_messages(self, conversation_id: str) -> list[dict]:
        payload = self._request("GET", f"/api/conversations/{conversation_id}/messages")
        rows = payload.get("messages", [])
        return rows if isinstance(rows, list) else []

    def get_model(self) -> dict:
        return self._request("GET", "/api/model")

    def stream_turn(
        self,
        conversation_id: str,
        content: str,
        images: Sequence[ImageInput] | None = None,
    ) -> Iterator[dict]:
        request: dict = {"headers": self._headers()}
        if images:
            request["data"] = {"content": content}
            request["files"] = [
                (
                    "images",
                    (
                        f"image-{index}.{_IMAGE_EXTENSIONS.get(image.media_type, 'img')}",
                        image.data,
                        image.media_type,
                    ),
                )
                for index, image in enumerate(images)
            ]
        else:
            request["json"] = {"content": content}
        with self._http.stream(
            "POST",
            f"{self.base_url}/api/conversations/{conversation_id}/turns",
            **request,
        ) as response:
            if response.status_code >= 400:
                body = response.read().decode("utf-8", errors="replace")
                message, code = _detail(body, response.status_code)
                raise AgentApiError(response.status_code, message, code=code)
            for line in response.iter_lines():
                if not line:
                    continue
                yield json.loads(line)

    def resolve_approval(
        self,
        conversation_id: str,
        approval_id: str,
        *,
        approved: bool | None = None,
        grant_scope: str | None = None,
        decisions: list[dict] | None = None,
    ) -> None:
        # A second connection: the turn stream is still open on self._http.
        if decisions is not None:
            payload: dict = {"decisions": decisions}
        else:
            payload = {"approved": approved, "grant_scope": grant_scope}
        with httpx.Client(timeout=30) as http:
            response = http.post(
                f"{self.base_url}/api/conversations/{conversation_id}/approvals/{approval_id}",
                headers=self._headers(),
                json=payload,
            )
        if response.status_code >= 400:
            message, code = _detail(response.text, response.status_code)
            raise AgentApiError(response.status_code, message, code=code)

    def _request(self, method: str, path: str, **kwargs) -> dict:
        response = self._http.request(
            method,
            f"{self.base_url}{path}",
            headers=self._headers(),
            **kwargs,
        )
        if response.status_code >= 400:
            message, code = _detail(response.text, response.status_code)
            raise AgentApiError(response.status_code, message, code=code)
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


def _detail(body: str, status: int) -> tuple[str, str | None]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body or f"HTTP {status}", None
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict):
        message = detail.get("message")
        code = detail.get("code")
        if isinstance(message, str):
            return message, code if isinstance(code, str) else None
    if isinstance(detail, str):
        return detail, None
    return body or f"HTTP {status}", None
