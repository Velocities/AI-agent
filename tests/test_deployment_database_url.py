from ai_agent.conversations.db import (
    database_url_for_admin_cli,
    deployment_database_url,
    shared_deployment_database_path,
)


def test_service_db_uses_conversation_database_from_settings() -> None:
    from ai_agent.config import Settings

    settings = Settings(conversation_database="sqlite:////var/lib/ai-agent/conversations.db")
    assert database_url_for_admin_cli(settings, service_db=True) == (
        "sqlite:////var/lib/ai-agent/conversations.db"
    )
    assert deployment_database_url(settings) == "sqlite:////var/lib/ai-agent/conversations.db"


def test_service_db_falls_back_to_shared_path_when_unset() -> None:
    from ai_agent.config import Settings

    settings = Settings(conversation_database="")
    url = database_url_for_admin_cli(settings, service_db=True)
    assert shared_deployment_database_path().as_posix() in url
