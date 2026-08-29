from ai_agent.cli.app import main
from ai_agent.cli.config_cmd import COPY_WARNING, main as config_main


def test_ai_agent_config_dispatches_help() -> None:
    assert main(["config"]) == 0


def test_config_show_prints_transport() -> None:
    assert config_main(["show"]) == 0


def test_copy_warning_mentions_sandbox() -> None:
    assert ".ai-agent/ssh" in COPY_WARNING
    assert "copy" in COPY_WARNING.lower()
