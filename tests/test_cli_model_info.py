"""CLI /model-info lines."""

from ai_agent_cli.remote_repl import model_info_lines


def test_model_info_lines_describe_the_running_model() -> None:
    lines = model_info_lines(
        {
            "engine": "ollama",
            "model": "qwen2.5vl:7b",
            "vision": True,
            "tools": True,
            "vision_source": "probed",
            "tools_source": "probed",
            "capabilities": ["completion", "vision"],
            "family": "qwen2",
            "parameter_size": "7.6B",
            "quantization": "Q4_K_M",
            "context_length": 32768,
        }
    )
    assert lines[0] == "qwen2.5vl:7b"
    assert "Engine: Ollama" in lines
    assert "Image uploads: yes (reported by the engine)" in lines
    assert "Tools: yes (reported by the engine)" in lines
    assert "Family: qwen2" in lines
    assert "Size: 7.6B" in lines
    assert "Quantization: Q4_K_M" in lines
    assert "Context length: 32768" in lines
    assert "Capabilities: completion, vision" in lines


def test_model_info_lines_when_the_snapshot_is_missing() -> None:
    assert model_info_lines(None) == ["Model information is unavailable."]


def test_model_info_lines_mark_configured_vision() -> None:
    lines = model_info_lines(
        {
            "engine": "vllm",
            "model": "Qwen/Qwen2.5-VL-7B-Instruct",
            "vision": True,
            "tools": True,
            "vision_source": "configured",
            "tools_source": "warmup",
        }
    )
    assert lines[0] == "Qwen/Qwen2.5-VL-7B-Instruct"
    assert "Engine: vLLM" in lines
    assert "Image uploads: yes (set by the server operator)" in lines
    assert "Tools: yes (checked when the server started)" in lines
    assert not any(line.startswith("Family:") for line in lines)
    assert not any(line.startswith("Capabilities:") for line in lines)
