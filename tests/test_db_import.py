import importlib


def test_conversations_db_imports_without_unix_pwd(monkeypatch) -> None:
    """Windows and CI must load the conversation store without a top-level pwd import."""
    monkeypatch.delitem(importlib.sys.modules, "ai_agent.conversations.db", raising=False)
    module = importlib.import_module("ai_agent.conversations.db")
    path = module.default_database_path()
    assert path.name == "conversations.db"
    assert "ai-agent" in path.as_posix()