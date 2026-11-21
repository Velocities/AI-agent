from ai_agent.config import Settings


def test_legacy_ollama_aliases_set_context_and_output() -> None:
    settings = Settings(
        OLLAMA_NUM_CTX=8192,
        OLLAMA_NUM_PREDICT=512,
    )
    assert settings.llm_context_length == 8192
    assert settings.llm_max_output_tokens == 512


def test_vllm_max_tokens_alias_sets_output_cap() -> None:
    settings = Settings(VLLM_MAX_TOKENS=2048)
    assert settings.llm_max_output_tokens == 2048