from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ai_agent.config import LlmTransport, Settings
from ai_agent.llm.base import LLMErrorKind
from ai_agent.llm.factory import create_http_session
from ai_agent.llm.session import LlmHttpSession, LlmSessionError
from ai_agent.llm.ssh_sandbox import (
    ResolvedSshHost,
    append_known_hosts,
    copy_identity_into_sandbox,
    disable_remote_provider_env,
    host_setup_next_steps,
    is_host_key_failure,
    list_ssh_host_aliases,
    parse_keyscan_lines,
    parse_ssh_g,
    scan_host_keys,
    remote_provider_env_values,
    upsert_env_values,
    write_sandbox_host_config,
)
from ai_agent.llm.ssh_tunnel import SshTunnel, build_ssh_forward_command, parse_remote_bind


def test_host_key_failure_detection() -> None:
    message = (
        "SSH tunnel exited before it was ready. "
        "No ED25519 host key is known for 192.168.1.10 and you have requested "
        "strict checking.\nHost key verification failed."
    )
    assert is_host_key_failure(message) is True
    assert is_host_key_failure("Connection refused") is False


def test_parse_and_append_known_hosts(tmp_path: Path) -> None:
    raw = "# comment\n192.168.1.10 ssh-ed25519 AAAA\n\n"
    lines = parse_keyscan_lines(raw)
    assert lines == ["192.168.1.10 ssh-ed25519 AAAA"]
    kex_noise = (
        "# 10.0.0.1:22 SSH-2.0-OpenSSH_9.6p1 Ubuntu-3ubuntu13.18\n"
        "choose_kex: unsupported KEX method sntrup761x25519-sha512@openssh.com\n"
    )
    assert parse_keyscan_lines(kex_noise) == []
    known = tmp_path / "known_hosts"
    append_known_hosts(known, lines)
    append_known_hosts(known, lines)
    assert known.read_text(encoding="utf-8").count("ssh-ed25519") == 1


def test_scan_host_keys_falls_back_to_ssh_when_keyscan_hits_kex_bug(
    tmp_path: Path,
) -> None:
    keyscan_err = (
        "# 10.0.0.1:22 SSH-2.0-OpenSSH_9.6p1 Ubuntu-3ubuntu13.18\n"
        "choose_kex: unsupported KEX method sntrup761x25519-sha512@openssh.com\n"
    )
    recorded = tmp_path / "written"

    def fake_run(argv, **kwargs):
        result = MagicMock()
        result.stdout = ""
        result.stderr = keyscan_err
        if argv and argv[0] == "ssh-keyscan":
            return result
        known = None
        for item in argv:
            if item.startswith("UserKnownHostsFile="):
                known = Path(item.split("=", 1)[1])
        if known is not None:
            known.write_text("10.0.0.1 ssh-ed25519 AAAATEST\n", encoding="utf-8")
            recorded.write_text(str(known), encoding="utf-8")
        result.stderr = "Permission denied (publickey).\n"
        return result

    with patch("ai_agent.llm.ssh_sandbox.subprocess.run", side_effect=fake_run):
        lines = scan_host_keys("10.0.0.1", 22, user="ai")
    assert lines == ["10.0.0.1 ssh-ed25519 AAAATEST"]


def test_list_ssh_host_aliases_skips_wildcards(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.write_text(
        "Host *\n    IdentitiesOnly yes\nHost gpu-box laptop\n    User admin\nHost work\n",
        encoding="utf-8",
    )
    assert list_ssh_host_aliases(config) == ["gpu-box", "laptop", "work"]


def test_parse_ssh_g_reads_identity_and_port() -> None:
    output = (
        "hostname 192.168.1.10\n"
        "user admin\n"
        "port 2222\n"
        "identityfile /tmp/id_ed25519\n"
        "identityfile /tmp/other\n"
    )
    host = parse_ssh_g(output, alias="gpu-box")
    assert host.hostname == "192.168.1.10"
    assert host.user == "admin"
    assert host.port == 2222
    assert host.identity_files[0] == Path("/tmp/id_ed25519")


def test_copy_identity_and_write_sandbox(tmp_path: Path) -> None:
    source = tmp_path / "id_ed25519"
    source.write_text("PRIVATE", encoding="utf-8")
    (tmp_path / "id_ed25519.pub").write_text("ssh-ed25519 AAAA test", encoding="utf-8")
    sandbox = tmp_path / "sandbox"
    dest = copy_identity_into_sandbox(source, sandbox, stem="id_gpu-box")
    assert dest.read_text(encoding="utf-8") == "PRIVATE"
    assert Path(str(dest) + ".pub").is_file()
    host = ResolvedSshHost(
        alias="gpu-box",
        hostname="192.168.1.10",
        user="admin",
        port=22,
        identity_files=[dest],
    )
    config = write_sandbox_host_config(sandbox, host, dest)
    text = config.read_text(encoding="utf-8")
    assert "Host gpu-box" in text
    assert "IdentitiesOnly yes" in text
    assert "UserKnownHostsFile" in text
    assert "~/.ssh" not in text


def test_upsert_env_preserves_other_keys(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("OLLAMA_MODEL=qwen3:14b\nAGENT_LOG_LEVEL=INFO\n", encoding="utf-8")
    upsert_env_values(env, remote_provider_env_values(alias="gpu-box", config_path=tmp_path / "config"))
    text = env.read_text(encoding="utf-8")
    assert "OLLAMA_MODEL=qwen3:14b" in text
    assert "OLLAMA_TRANSPORT=ssh" in text
    assert "OLLAMA_SSH_HOST=gpu-box" in text
    disable_remote_provider_env(env)
    text = env.read_text(encoding="utf-8")
    assert "OLLAMA_TRANSPORT=http" in text


def test_host_setup_next_steps_point_at_wrapper() -> None:
    key = Path("host-setup.pub")
    text = host_setup_next_steps(key_file=key, linux=False)
    assert "ai-agent host-setup" in text
    assert "host-setup.pub" in text
    linux = host_setup_next_steps(key_file=key, linux=True)
    assert "--linux" in linux


def test_build_ssh_forward_command_uses_sandbox(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.write_text("Host gpu-box\n", encoding="utf-8")
    settings = Settings()
    settings.ollama_ssh_config = config
    settings.ollama_ssh_host = "gpu-box"
    settings.ollama_ssh_remote = "127.0.0.1:11434"
    command = build_ssh_forward_command(settings, local_port=23456, ssh_bin="ssh")
    assert command[:4] == ["ssh", "-N", "-F", str(config)]
    assert "127.0.0.1:23456:127.0.0.1:11434" in command
    assert "gpu-box" in command
    assert "BatchMode=yes" in command


def test_parse_remote_bind() -> None:
    assert parse_remote_bind("127.0.0.1:11434") == ("127.0.0.1", 11434)
    with pytest.raises(ValueError):
        parse_remote_bind("noport")


def test_tunnel_ensure_raises_when_dead() -> None:
    process = MagicMock()
    process.poll.return_value = 1
    tunnel = SshTunnel(process, 1234, "127.0.0.1:11434")
    with pytest.raises(LlmSessionError) as exc:
        tunnel.ensure()
    assert exc.value.kind == LLMErrorKind.SESSION_CLOSED


def test_session_runs_before_request() -> None:
    called = {"n": 0}

    def gate() -> None:
        called["n"] += 1
        raise LlmSessionError(LLMErrorKind.SESSION_CLOSED, "SSH tunnel is gone.")

    session = LlmHttpSession("http://127.0.0.1:9", before_request=gate)
    with pytest.raises(LlmSessionError) as exc:
        session.get_json("/api/tags")
    assert exc.value.kind == LLMErrorKind.SESSION_CLOSED
    assert called["n"] == 1
    session.close()


def test_factory_starts_tunnel_for_ssh_transport(tmp_path: Path) -> None:
    settings = Settings()
    settings.ollama_transport = LlmTransport.SSH
    settings.ollama_ssh_host = "gpu-box"
    tunnel = MagicMock()
    tunnel.local_url = "http://127.0.0.1:34567"
    tunnel.ensure = MagicMock()
    tunnel.close = MagicMock()
    with patch("ai_agent.llm.factory.start_ssh_tunnel", return_value=tunnel) as start:
        session = create_http_session(settings)
        start.assert_called_once()
        assert session.base_url == "http://127.0.0.1:34567"
        session.close()
        tunnel.close.assert_called_once()


def test_factory_http_skips_tunnel() -> None:
    settings = Settings()
    settings.ollama_transport = LlmTransport.HTTP
    with patch("ai_agent.llm.factory.start_ssh_tunnel") as start:
        session = create_http_session(settings)
        start.assert_not_called()
        assert session.base_url.rstrip("/") == settings.ollama_host.rstrip("/")
        session.close()
