from __future__ import annotations

from typing import Protocol

from ai_agent_cli.client_state import ServerConfig


class ChatAuth(Protocol):
    """Swappable bearer-token source for the HTTP chat client."""

    def bearer_token(self, config: ServerConfig) -> str | None: ...