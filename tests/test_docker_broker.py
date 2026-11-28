"""Docker stays inside the container. These tests call the broker directly.

No model is involved. A recording runner stands in for the Docker CLI, and a
refused request must leave that runner untouched. An accepted request is a
list beginning with ``docker`` whose command text comes after the container
name, so it cannot be a host shell.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ai_agent.commands.ast import SingleCommand, WriteFileCommand, parse_command_expr
from ai_agent.commands.executor import CommandExecutor, CommandResult
from ai_agent.docker_broker.authorize import BrokerRejected, authorize
from ai_agent.docker_broker.broker import DockerBroker
from ai_agent.docker_broker.client import SocketDockerBroker
from ai_agent.docker_broker.server import BrokerServer
from ai_agent.execution_targets.docker import DockerExecutionTarget
from ai_agent.execution_targets.workflow import WorkflowExecutionTarget
from ai_agent.workflows.container import ContainerMount, WorkflowContainerSpec
from ai_agent.workflows.image import docker_build_argv, docker_image_inspect_argv, image_tag
from ai_agent.workflows.manifests import default_workflow_image_root, load_workflow

_TAG = "ai-agent-workflow:text-lab-" + "ab" * 8
_WF = "wf" + "cd" * 16


def _recorder(calls: list[dict]):
    def run(argv, *, timeout, stdin=None):
        calls.append({"argv": list(argv), "stdin": stdin, "timeout": timeout})
        return subprocess.CompletedProcess(list(argv), 0, "ok", "")

    return run


def _executor(captured: list[list[str]]) -> CommandExecutor:
    executor = MagicMock(spec=CommandExecutor)

    def run(expr):
        captured.append(list(expr.argv))
        return CommandResult(
            success=True,
            exit_status=0,
            stdout="ok",
            stderr="",
            duration_ms=1,
            rendered="wrapped",
        )

    executor.run.side_effect = run
    executor.timeout = 30
    return executor


def _target(captured: list[list[str]], **kwargs) -> DockerExecutionTarget:
    return DockerExecutionTarget(
        name="web",
        container=kwargs.pop("container", "nginx"),
        executor=_executor(captured),
        **kwargs,
    )


def _command(argv: list[str], cwd: str | None = None) -> SingleCommand:
    return SingleCommand(argv=argv, cwd=cwd)


def test_exec_runs_only_inside_the_registered_container() -> None:
    captured: list[list[str]] = []
    target = _target(captured)
    result = target.run(_command(["nginx", "-t"]))
    assert result.success
    assert captured == [["docker", "exec", "-i", "nginx", "nginx", "-t"]]
    assert captured[0][0] == "docker"
    host = captured[0]
    assert host.index("nginx") < host.index("-t")
    assert "--privileged" not in host
    assert "--mount" not in host
    assert "-v" not in host


def test_shell_text_stays_one_argument_inside_the_container() -> None:
    captured: list[list[str]] = []
    target = _target(captured)
    payload = "id; touch /tmp/pwned $(whoami) `uname` && cat /etc/shadow"
    target.run(_command(["sh", "-c", payload]))
    host = captured[0]
    assert host[:4] == ["docker", "exec", "-i", "nginx"]
    assert host[4:] == ["sh", "-c", payload]
    assert host[0] != "sh"
    assert host[0] != "bash"
    assert isinstance(host, list)
    joined = " ".join(host)
    assert payload in joined
    assert joined.startswith("docker exec -i nginx ")


def test_smuggled_docker_flags_are_the_container_command() -> None:
    captured: list[list[str]] = []
    target = _target(captured)
    inner = [
        "docker",
        "run",
        "--privileged",
        "--userns=host",
        "-v",
        "/var/run/docker.sock:/var/run/docker.sock",
        "alpine",
        "id",
    ]
    target.run(_command(inner))
    host = captured[0]
    assert host[:4] == ["docker", "exec", "-i", "nginx"]
    assert host[4:] == inner
    assert host.index("nginx") < host.index("--privileged")
    assert host.index("nginx") < host.index("--userns=host")
    assert host.index("nginx") < host.index("-v")
    assert host[0] == "docker"


def test_container_user_workdir_and_binary_cannot_escape() -> None:
    command = _command(["id"])
    containers = [
        "nginx; id",
        "$(id)",
        "-v",
        "--privileged",
        "nginx --privileged",
        "nginx\nid",
        "",
        "/var/run/docker.sock",
        "nginx/evil",
        "nginx;touch /tmp/pwned",
    ]
    for name in containers:
        captured: list[list[str]] = []
        result = _target(captured, container=name).run(command)
        assert result.success is False, name
        assert result.metadata["docker_rejected"] is True
        assert captured == [], name

    users = ["--privileged", "root;id", "root\n--volume=/:/host", "-u", "root && id"]
    for user in users:
        captured = []
        result = _target(captured, user=user).run(command)
        assert result.success is False, user
        assert captured == [], user

    workdirs = [
        "--privileged",
        "--volume=/:/host",
        "/var/run/docker.sock",
        "/\n--privileged",
        "$(id)",
        "/tmp;id",
        "/",
        "/work/../../etc",
    ]
    for cwd in workdirs:
        captured = []
        result = _target(captured).run(_command(["id"], cwd=cwd))
        assert result.success is False, cwd
        assert captured == [], cwd

    binaries = ["/bin/sh", "bash", "docker; id", "/usr/bin/docker", "sh"]
    for binary in binaries:
        captured = []
        result = _target(captured, docker_bin=binary).run(command)
        assert result.success is False, binary
        assert captured == [], binary


def test_write_file_on_a_docker_target_does_not_touch_the_host() -> None:
    captured: list[list[str]] = []
    target = _target(captured)
    result = target.run(WriteFileCommand(path="/tmp/pwned", content="id"))
    assert result.success is False
    assert captured == []


def test_attached_broker_is_used_instead_of_the_host_executor() -> None:
    captured: list[list[str]] = []
    calls: list[dict] = []
    target = DockerExecutionTarget(
        name="web",
        container="nginx",
        executor=_executor(captured),
        broker=DockerBroker(_recorder(calls)),
    )
    result = target.run(_command(["id"]))
    assert result.success
    assert captured == []
    assert calls[0]["argv"] == ["docker", "exec", "-i", "nginx", "id"]
    assert isinstance(calls[0]["argv"], list)


def test_broker_refuses_native_shell_and_host_docker_flags() -> None:
    calls: list[dict] = []
    broker = DockerBroker(_recorder(calls))
    refused = [
        ["/bin/sh", "-c", "id"],
        ["bash", "-c", "id"],
        ["sh", "-c", "touch /tmp/pwned"],
        ["sudo", "id"],
        ["docker", "run", "--privileged", "--userns=host", "alpine", "id"],
        ["docker", "exec", "--privileged", "-i", "nginx", "id"],
        ["docker", "exec", "-i", "-v", "/:/host", "nginx", "id"],
        [
            "docker",
            "exec",
            "-i",
            "--mount",
            "type=bind,source=/var/run/docker.sock,target=/var/run/docker.sock",
            "nginx",
            "id",
        ],
        ["docker", "exec", "-i", "--userns=host", "nginx", "id"],
        ["docker", "exec", "-i", "--network=host", "nginx", "id"],
        ["docker", "exec", "-i", "nginx; id", "id"],
        ["/usr/bin/docker", "exec", "-i", "nginx", "id"],
        ["docker", "rm", "-f", "nginx"],
        ["docker", "start", "nginx"],
        ["docker", "exec", "-i", "nginx"],
    ]
    for argv in refused:
        with pytest.raises(BrokerRejected):
            broker.invoke(argv, timeout=5)
    assert calls == []

    allowed = broker.exec(container="nginx", argv=["id"], timeout=5)
    assert allowed.returncode == 0
    assert calls == [{"argv": ["docker", "exec", "-i", "nginx", "id"], "stdin": None, "timeout": 5}]


def test_broker_refuses_fields_that_would_change_the_sandbox() -> None:
    calls: list[dict] = []
    broker = DockerBroker(_recorder(calls))
    for extra in (
        {"privileged": True},
        {"mounts": ["/var/run/docker.sock"]},
        {"network": "host"},
        {"userns": "host"},
    ):
        with pytest.raises(BrokerRejected):
            broker.handle(
                {
                    "op": "exec",
                    "container": "nginx",
                    "argv": ["id"],
                    "timeout": 5,
                    **extra,
                }
            )
    with pytest.raises(BrokerRejected):
        broker.handle({"op": "shell", "argv": ["id"], "timeout": 5})
    assert calls == []


def _workflow_spec(tmp_path: Path) -> WorkflowContainerSpec:
    sleep_root = tmp_path / "sleep"
    sleep = sleep_root / "user" / "conversation"
    sleep.mkdir(parents=True)
    return WorkflowContainerSpec(
        image=_TAG,
        container_name=_WF,
        mounts=(ContainerMount(source=sleep, target="/work", read_only=False),),
        sleep_root=sleep_root,
    )


def test_workflow_run_cannot_mount_the_host_or_drop_the_user_namespace(tmp_path: Path) -> None:
    spec = _workflow_spec(tmp_path)
    argv = spec.run_argv()
    calls: list[dict] = []
    broker = DockerBroker(_recorder(calls), sleep_root=spec.sleep_root)
    assert broker.invoke(argv, timeout=5).returncode == 0
    assert calls[0]["argv"] == argv
    assert "--privileged" not in argv

    calls.clear()
    privileged = ["docker", "run", "--privileged", *argv[2:]]
    host_ns = [*argv[:5], "--userns", "host", *argv[5:]]
    sock = argv.copy()
    mount_at = sock.index("--mount") + 1
    sock[mount_at] = "type=bind,source=/var/run/docker.sock,target=/var/run/docker.sock"
    home = argv.copy()
    home[home.index("--mount") + 1] = "type=bind,source=/home,target=/work"
    propagation = argv.copy()
    propagation[mount_at] += ",bind-propagation=shared"
    for bad in (privileged, host_ns, sock, home, propagation):
        with pytest.raises(BrokerRejected):
            broker.invoke(bad, timeout=5)
    assert calls == []


def test_workflow_run_argv_uses_syntax_docker_accepts(tmp_path: Path) -> None:
    argv = _workflow_spec(tmp_path).run_argv()
    assert "--userns" not in argv
    mount = argv[argv.index("--mount") + 1]
    assert mount.split(",") == [
        "type=bind",
        f"source={tmp_path / 'sleep' / 'user' / 'conversation'}",
        "target=/work",
    ]


def test_read_only_mount_round_trips_through_the_broker(tmp_path: Path) -> None:
    spec = _workflow_spec(tmp_path)
    store = ContainerMount(source=Path("/nix/store"), target="/nix/store", read_only=True)
    spec = WorkflowContainerSpec(
        image=spec.image,
        container_name=spec.container_name,
        mounts=(*spec.mounts, store),
        sleep_root=spec.sleep_root,
    )
    argv = spec.run_argv()
    assert "type=bind,source=/nix/store,target=/nix/store,readonly" in argv
    calls: list[dict] = []
    broker = DockerBroker(_recorder(calls), sleep_root=spec.sleep_root)
    assert broker.invoke(argv, timeout=5).returncode == 0


def test_run_guard_refuses_containers_when_dockerd_does_not_remap(tmp_path: Path) -> None:
    spec = _workflow_spec(tmp_path)
    calls: list[dict] = []
    broker = DockerBroker(
        _recorder(calls),
        sleep_root=spec.sleep_root,
        run_guard=lambda: "dockerd is not running with userns-remap",
    )
    with pytest.raises(BrokerRejected, match="userns-remap"):
        broker.invoke(spec.run_argv(), timeout=5)
    assert calls == []
    inspect = ["docker", "inspect", "-f", "{{.State.Running}}", _WF]
    assert broker.invoke(inspect, timeout=5).returncode == 0


def test_workflow_build_context_is_the_staged_closure() -> None:
    root = default_workflow_image_root()
    manifest = load_workflow(root, "text-lab")
    argv = docker_build_argv(manifest, workflow_image_root=root, nix_system="x86_64-linux")
    assert argv[:4] == ["docker", "buildx", "build", "--load"]
    assert authorize(argv, workflow_image_root=root) == argv
    context = Path(argv[-1])
    assert context.parent == (root / ".build").resolve()
    assert (context / "tools" / "count-lines" / "1.0.0" / "count_lines.py").is_file()
    assert "textkit" not in (context / "workflow.lock.json").read_text(encoding="utf-8")
    lines_libs = (context / "tools" / "count-lines" / "1.0.0" / "libraries.json").read_text(
        encoding="utf-8"
    )
    assert '"textkit"' in lines_libs
    assert not (context / "tools" / "fetch-pages").exists()
    assert (context / "libraries" / "textkit" / "1.0.0" / "textkit.py").is_file()
    tag = image_tag(manifest, root)
    assert authorize(docker_image_inspect_argv(tag))[-1] == tag
    with pytest.raises(BrokerRejected):
        authorize([*argv[:-1], "/"], workflow_image_root=root)
    with pytest.raises(BrokerRejected):
        authorize(
            ["docker", "build", "--network=host", "-t", tag, str(root)],
            workflow_image_root=root,
        )
    with pytest.raises(BrokerRejected):
        authorize(
            ["docker", "buildx", "build", "--push", *argv[4:]],
            workflow_image_root=root,
        )


def test_workflow_write_does_not_splice_content_into_a_host_shell() -> None:
    calls: list[dict] = []
    content = "'; touch /tmp/pwned; echo "
    target = WorkflowExecutionTarget(
        container=_WF,
        executor=_executor([]),
        workflow_name="text-lab",
        broker=DockerBroker(_recorder(calls)),
    )
    result = target.run(WriteFileCommand(path="/work/notes.txt", content=content))
    assert result.success
    host = calls[0]["argv"]
    assert host[0] == "docker"
    assert host[:6] == ["docker", "exec", "-i", "-w", "/work", _WF]
    assert calls[0]["stdin"] == content
    assert content not in host
    assert "/bin/sh" in host
    outside = target.run(parse_command_expr({"type": "single", "argv": ["id"], "cwd": "/etc"}))
    assert outside.success is False
    assert len(calls) == 1


def test_socket_server_does_not_run_a_rejected_command(tmp_path: Path) -> None:
    calls: list[dict] = []
    path = Path(f"/tmp/ai-broker-{os.getpid()}.sock")
    if path.exists():
        path.unlink()
    server = BrokerServer(
        path,
        runner=_recorder(calls),
        workflow_image_root=tmp_path,
        api_uid=os.getuid(),
    )
    server.start()
    try:
        deadline = time.time() + 2
        while not path.exists():
            if time.time() > deadline:
                raise AssertionError("broker socket was not created")
            time.sleep(0.02)
        client = SocketDockerBroker(path)
        refused = client.invoke(["/bin/sh", "-c", "id"], timeout=5)
        assert refused.returncode == 126
        assert calls == []
        other_calls: list[dict] = []
        other_path = Path(f"/tmp/ai-broker-peer-{os.getpid()}.sock")
        if other_path.exists():
            other_path.unlink()
        stranger = BrokerServer(
            other_path,
            runner=_recorder(other_calls),
            workflow_image_root=tmp_path,
            api_uid=0 if os.getuid() != 0 else 65534,
        )
        stranger.start()
        try:
            deadline = time.time() + 2
            while not other_path.exists():
                if time.time() > deadline:
                    raise AssertionError("peer-check socket was not created")
                time.sleep(0.02)
            blocked = SocketDockerBroker(other_path).exec(
                container="nginx", argv=["id"], timeout=5
            )
            assert blocked.returncode == 126
            assert other_calls == []
        finally:
            stranger.close()
        allowed = client.exec(container="nginx", argv=["id"], timeout=5)
        assert allowed.returncode == 0
        assert calls[0]["argv"] == ["docker", "exec", "-i", "nginx", "id"]
        assert isinstance(calls[0]["argv"], list)
    finally:
        server.close()
