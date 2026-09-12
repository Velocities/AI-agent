from ai_agent.llm.client.errors import ModelMissingError
from ai_agent.llm.http.model_errors import format_model_missing_message
from ai_agent.llm.server.errors import EngineModelMissingError


def test_format_model_missing_message_names_engine() -> None:
    message = format_model_missing_message(
        "qwen3:14b",
        "Ollama",
        "http://localhost:11434",
        available=["llama3:latest"],
    )
    assert "ModelMissingError" in message
    assert "qwen3:14b" in message
    assert "not available with Ollama" in message
    assert "llama3:latest" in message


def test_settings_accepts_legacy_upstream_aliases(monkeypatch) -> None:
    monkeypatch.setenv("LLM_UPSTREAM", "http://localhost:8000")
    from ai_agent.config import Settings

    assert Settings().llm_upstream == "http://localhost:8000"

    monkeypatch.delenv("LLM_UPSTREAM", raising=False)
    monkeypatch.setenv("VLLM_UPSTREAM", "http://legacy-vllm:8000")
    assert Settings().llm_upstream == "http://legacy-vllm:8000"


def test_client_and_server_errors_share_message_format() -> None:
    client = ModelMissingError("missing", "vLLM", "http://localhost:8000")
    server = EngineModelMissingError("missing", "vLLM", "http://localhost:8000")
    assert str(client) == str(server)
    assert "not available with vLLM" in str(client)
