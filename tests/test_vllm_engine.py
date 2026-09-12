import json
from unittest.mock import MagicMock

from ai_agent.llm.http.errors import LLMErrorKind
from ai_agent.llm.http.session import LlmSessionError
from ai_agent.llm.server.engine.vllm import VLLMEngine


def test_vllm_list_models_maps_openai_payload() -> None:
    session = MagicMock()
    session.base_url = "http://localhost:8000"
    session.get_json.return_value = {
        "data": [{"id": "meta-llama/Llama-3.1-8B-Instruct"}],
    }
    engine = VLLMEngine(session, "meta-llama/Llama-3.1-8B-Instruct")
    payload = engine.list_models()
    assert payload == {"models": [{"name": "meta-llama/Llama-3.1-8B-Instruct"}]}


def test_vllm_healthcheck_reports_missing_model() -> None:
    session = MagicMock()
    session.base_url = "http://localhost:8000"
    session.get_json.return_value = {"data": [{"id": "other-model"}]}
    engine = VLLMEngine(session, "missing-model")
    health = engine.healthcheck()
    assert health.ok is False
    assert "ModelMissingError" in health.message
    assert "missing-model" in health.message


def test_vllm_chat_lines_emit_canonical_ndjson() -> None:
    sse_lines = [
        'data: {"model":"meta-llama/Llama-3.1-8B-Instruct","choices":[{"delta":{"content":"Hel"},"finish_reason":null}]}',
        'data: {"model":"meta-llama/Llama-3.1-8B-Instruct","choices":[{"delta":{"content":"lo"},"finish_reason":null}]}',
        'data: {"model":"meta-llama/Llama-3.1-8B-Instruct","choices":[{"delta":{},"finish_reason":"stop"}]}',
        "data: [DONE]",
    ]

    class _Stream:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def iter_lines(self):
            yield from sse_lines

    session = MagicMock()
    session.base_url = "http://localhost:8000"
    session.stream_post.return_value = _Stream()
    engine = VLLMEngine(session, "meta-llama/Llama-3.1-8B-Instruct")

    lines = list(
        engine.chat_lines(
            {
                "model": "meta-llama/Llama-3.1-8B-Instruct",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
            }
        )
    )

    payloads = [json.loads(line) for line in lines]
    assert payloads[0]["message"]["content"] == "Hel"
    assert payloads[1]["message"]["content"] == "lo"
    assert payloads[-1]["done"] is True
    assert payloads[-1]["done_reason"] == "stop"
    session.stream_post.assert_called_once()
    assert session.stream_post.call_args.args[0] == "/v1/chat/completions"


def test_vllm_chat_lines_map_tool_call_deltas() -> None:
    sse_lines = [
        (
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"respond",'
            '"arguments":"{\\"finished\\": true, \\"message\\": \\"Hel"}}]},"finish_reason":null}]}'
        ),
        (
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"lo\\"}"}}]},'
            '"finish_reason":"tool_calls"}]}'
        ),
        "data: [DONE]",
    ]

    class _Stream:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def iter_lines(self):
            yield from sse_lines

    session = MagicMock()
    session.stream_post.return_value = _Stream()
    engine = VLLMEngine(session, "test-model")
    lines = list(
        engine.chat_lines(
            {
                "model": "test-model",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
            }
        )
    )
    payloads = [json.loads(line) for line in lines]
    tool_chunks = [
        item
        for item in payloads
        if item.get("message", {}).get("tool_calls")
        and not item.get("done")
    ]
    assert tool_chunks
    final = payloads[-1]
    assert final["done"] is True
    assert final["message"]["tool_calls"][0]["function"]["name"] == "respond"
