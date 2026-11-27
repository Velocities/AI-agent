from ai_agent_cli.client_state import ServerConfig
from ai_agent_cli.terminal_chat import (
    _ConversationMemory,
    _is_local_config,
    _remember_conversation_id,
    _active_conversation_id,
)


def test_local_config_detection() -> None:
    local = ServerConfig(server_url="http://127.0.0.1:1", supabase_url="", supabase_publishable_key="")
    remote = ServerConfig(
        server_url="https://x",
        supabase_url="https://sb",
        supabase_publishable_key="key",
    )
    assert _is_local_config(local)
    assert not _is_local_config(remote)


def test_conversation_memory_never_touches_disk() -> None:
    memory = _ConversationMemory()
    assert _active_conversation_id(memory) is None
    _remember_conversation_id("abc", memory)
    assert _active_conversation_id(memory) == "abc"