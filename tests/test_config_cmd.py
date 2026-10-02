from unittest.mock import MagicMock

from ai_agent.cli.app import main
from ai_agent.cli.config_cmd import COPY_WARNING, main as config_main
from ai_agent.cli.host_setup import main as host_setup_main


def test_ai_agent_config_dispatches_help() -> None:
    assert main(["config"]) == 0


def test_config_show_prints_transport() -> None:
    assert config_main(["show"]) == 0


def test_execution_target_list(tmp_path, monkeypatch) -> None:
    repo = MagicMock()
    repo.list_for_user.return_value = []
    monkeypatch.setattr(
        "ai_agent.cli.execution_target_cmd._open_repo",
        lambda *_a, **_k: (f"sqlite:///{tmp_path / 'test.sqlite3'}", repo, MagicMock()),
    )
    assert config_main(
        ["execution-target", "list", "--user-id", "11111111-1111-4111-8111-111111111111"]
    ) == 0


def test_copy_warning_mentions_sandbox() -> None:
    assert ".ai-agent/ssh" in COPY_WARNING
    assert "copy" in COPY_WARNING.lower()


def test_host_setup_requires_a_key() -> None:
    assert host_setup_main([]) == 1
