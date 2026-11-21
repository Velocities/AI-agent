"""Container launch contract. Some bodies are still TODOs."""

from pathlib import Path

import pytest

from ai_agent.workflows.container import ContainerMount, SandboxContainerSpec


def test_run_argv_never_opts_out_of_daemon_user_namespace_remap(tmp_path: Path):
    """Container root must not be host root.

    Remapping is the daemon's userns-remap setting. The only --userns value
    docker run accepts is "host", which disables it, so the argv never has one.
    """
    sleep = tmp_path / "user" / "conversation"
    sleep.mkdir(parents=True)
    argv = SandboxContainerSpec(
        image="ai-agent-workflow:text-lab-" + "ab" * 8,
        container_name="wf" + "cd" * 16,
        mounts=(ContainerMount(source=sleep, target="/work", read_only=False),),
        sleep_root=tmp_path,
    ).run_argv()
    assert "--userns" not in argv
    assert "--privileged" not in argv


def test_run_argv_rejects_docker_socket_mount():
    """The container must not be able to drive the host Docker daemon.

    TODO: a mount of /var/run/docker.sock raises SandboxSpecError.
    TODO: a mount whose source name is docker.sock, whatever the target, raises.
    TODO: the accepted argv never contains docker.sock.
    """
    pytest.skip("TODO")


def test_run_argv_rejects_host_network_pid_and_privileged():
    """Host namespaces are an escape.

    TODO: network="host" raises SandboxSpecError.
    TODO: a mount whose target is /, /home, or /etc raises SandboxSpecError.
    TODO: a mount other than /work or /nix/store raises SandboxSpecError.
    """
    pytest.skip("TODO")


def test_sleep_volume_must_stay_under_the_sleep_root():
    """The writable mount is the sleep area, not the user's home.

    TODO: /work sourced from a directory under sleep_root is accepted.
    TODO: /work sourced from a home directory raises SandboxSpecError.
    TODO: a read-only /work raises SandboxSpecError.
    TODO: two /work mounts raise SandboxSpecError.
    """
    pytest.skip("TODO")


def test_nix_store_mount_is_optional_and_read_only():
    """The baked image needs no store mount. A shared store must be read-only.

    TODO: a spec with only /work is accepted.
    TODO: an extra read-only /nix/store mount is accepted.
    TODO: a writable /nix/store mount raises SandboxSpecError.
    """
    pytest.skip("TODO")
