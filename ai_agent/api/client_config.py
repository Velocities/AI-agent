from __future__ import annotations

from pydantic import BaseModel

from ai_agent.config import Settings

# Public so a client can load Supabase before it has an access token.
CLIENT_CONFIG_PATH = "/api/client-config"


class ClientConfigBody(BaseModel):
    supabase_url: str
    supabase_publishable_key: str


def client_config_for(settings: Settings) -> ClientConfigBody | None:
    """Supabase settings a chat client may embed. None when the server has none."""
    url = settings.supabase_url.strip().rstrip("/")
    key = settings.supabase_anon_key.strip()
    if not url or not key:
        return None
    return ClientConfigBody(supabase_url=url, supabase_publishable_key=key)
