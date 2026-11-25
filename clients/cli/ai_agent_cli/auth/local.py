from __future__ import annotations

from dataclasses import dataclass

from ai_agent_cli.client_state import ServerConfig


@dataclass(frozen=True)
class LocalStandaloneAuth:
    token: str

    def bearer_token(self, config: ServerConfig) -> str | None:
        del config
        return self.token