from pathlib import Path

from ai_agent.docker_broker.host_runtime import (
    broker_state_root,
    broker_subprocess_env,
    docker_config_dir,
)


def test_broker_subprocess_env_points_home_at_state_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AI_AGENT_DOCKER_BROKER_STATE", str(tmp_path))
    env = broker_subprocess_env(base={"PATH": "/bin", "LANG": "C.UTF-8"})
    assert env["HOME"] == str(tmp_path)
    assert env["DOCKER_CONFIG"] == str(docker_config_dir(tmp_path))
    assert env["PATH"] == "/bin"


def test_default_state_root() -> None:
    assert broker_state_root() == Path("/var/lib/ai-docker")