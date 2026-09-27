"""Public HTTP API (`ai-agent-serve`).

Listens on loopback. Cloudflare Tunnel is the HTTPS path. Supabase access
tokens are checked here. The agent loop and conversation storage are not
in this package yet.
"""

from ai_agent.api.app import create_app

__all__ = ["create_app"]
