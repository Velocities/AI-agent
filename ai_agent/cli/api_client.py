from __future__ import annotations

import json
from collections.abc import Iterator

import httpx


class AgentApiError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


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

    def stream_turn(self, conversation_id: str, content: str) -> Iterator[dict]:
        with self._http.stream(
            "POST",
            f"{self.base_url}/api/conversations/{conversation_id}/turns",
            headers=self._headers(),
            json={"content": content},
        ) as response:
            if response.status_code >= 400:
                body = response.read().decode("utf-8", errors="replace")
                raise AgentApiError(response.status_code, _detail(body, response.status_code))
            for line in response.iter_lines():
                if not line:
                    continue
                yield json.loads(line)

    def resolve_approval(
        self,
        conversation_id: str,
        approval_id: str,
        *,
        approved: bool,
        grant_scope: str | None = None,
    ) -> None:
        # A second connection: the turn stream is still open on self._http.
        with httpx.Client(timeout=30) as http:
            response = http.post(
                f"{self.base_url}/api/conversations/{conversation_id}/approvals/{approval_id}",
                headers=self._headers(),
                json={"approved": approved, "grant_scope": grant_scope},
            )
        if response.status_code >= 400:
            raise AgentApiError(response.status_code, _detail(response.text, response.status_code))

    def _request(self, method: str, path: str, **kwargs) -> dict:
        response = self._http.request(
            method,
            f"{self.base_url}{path}",
            headers=self._headers(),
            **kwargs,
        )
        if response.status_code >= 400:
            raise AgentApiError(response.status_code, _detail(response.text, response.status_code))
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


def _detail(body: str, status: int) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body or f"HTTP {status}"
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, str):
        return detail
    return body or f"HTTP {status}"
